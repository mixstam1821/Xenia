

"""
download_and_export.py
──────────────────────
Downloads FCI L1C NR full-disk slots from EUMETSAT one at a time,
renders them as Web-Mercator PNGs, then deletes the download before
moving to the next time step. Memory is explicitly freed between steps.

Reads EUMETSAT_KEY and EUMETSAT_SECRET from .env in the same directory.

Usage
─────
  python download_and_export.py --composite dust --start 2026-06-20T12:00 --end 2026-06-20T15:00 --freq 1h
  python download_and_export.py --composite natural_color airmass --start 2026-06-20T00:00 --end 2026-06-21T00:00 --freq 6h
  python download_and_export.py --composite dust --hours-back 3 --freq 1h

Frequency format
────────────────
  --freq 1h   → every 1 hour
  --freq 30m  → every 30 minutes
  --freq 2d   → every 2 days
  Supported suffixes: m (minutes), h (hours), d (days)
  The k multiplier can be any positive integer.

Output
──────
  ./exported_pngs/   ← Web-Mercator RGBA PNGs named  1_dust_…png, 2_…png …
  Downloads are deleted immediately after each step is rendered.
"""

import argparse
import gc
import io
import math
import os
import re
import sys
import time
import hashlib
import json
import zipfile
import shutil
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import List, Optional, Tuple
import subprocess

import numpy as np
import PIL.Image
from dotenv import load_dotenv

# ── credentials ───────────────────────────────────────────────────────────────
load_dotenv()
EUMETSAT_KEY    = os.getenv("EUMETSAT_KEY", "")
EUMETSAT_SECRET = os.getenv("EUMETSAT_SECRET", "")

if not EUMETSAT_KEY or not EUMETSAT_SECRET:
    sys.exit(
        "EUMETSAT_KEY and EUMETSAT_SECRET must be set in your .env file.\n"
        "Example:\n"
        "  EUMETSAT_KEY=your_consumer_key\n"
        "  EUMETSAT_SECRET=your_consumer_secret"
    )

import eumdac
import warnings
warnings.filterwarnings("ignore")

# ── directories ───────────────────────────────────────────────────────────────
DOWNLOAD_DIR = Path("./downloaded_fci")
EXPORT_DIR   = Path("./exported_pngs")
DOWNLOAD_DIR.mkdir(exist_ok=True)
EXPORT_DIR.mkdir(exist_ok=True)

FCI_NR_COLLECTION = "EO:EUM:DAT:0662"
MAX_SRC = 2048

# ── neighbour cache (max 2 entries) ───────────────────────────────────────────
_NI_CACHE_MAX = 2
_ni_cache: dict = {}


# ══════════════════════════════════════════════════════════════════════════════
#  RGB RECIPES
# ══════════════════════════════════════════════════════════════════════════════
COMPOSITE_RECIPES = {
    "airmass":            [(-23.8,  1.4, 1.0), (-39.7,  4.1, 1.0), (244.5, 209.4, 1.0)],
    "24h_microphysics":   [( -7.1,  2.4, 1.0), (  0.2,  5.2, 1.2), (247.8, 303.1, 1.0)],
    "night_microphysics": [( -4.0,  2.0, 1.0), ( -4.0,  6.0, 1.0), (243.0, 293.0, 1.0)],
    "cloud_phase":        [(  0.0, 50.0, 1.0), (  0.0, 50.0, 1.0), (  0.0, 100.0, 1.0)],
    "day_microphysics":   [(  0.0,100.0, 1.0), (  0.0, 60.0, 2.5), (203.0, 323.0, 1.0)],
    "cloud_type":         [(  0.0, 10.0, 1.5), (  0.0, 80.0,0.75), (  0.0,  80.0, 1.0)],
    "dust":               [( -7.1,  2.4, 1.0), (  0.2, 12.7, 2.5), (260.9, 289.0, 1.0)],
    "ash":                [( -7.1,  2.4, 1.0), ( -3.2,  4.4, 1.0), (242.8, 303.1, 1.0)],
    "fog":                [( -4.0,  2.0, 1.0), (  0.0,  6.0, 1.0), (243.0, 283.0, 1.0)],
    "natural_color":      [(  0.0,100.0, 1.0), (  0.0,100.0, 1.0), (  0.0, 100.0, 1.0)],
    "overshooting_tops":  [(-23.8,  6.4, 1.0), (-29.9, 23.6, 1.0), (244.5, 191.4, 1.0)],
    # true_color: gamma=0.0 sentinel — bands_to_rgb_inputs returns pre-built [0,1] output,
    # apply_recipe is skipped entirely in build_rgba.
    "true_color":         [(0.0, 0.0, 0.0), (0.0, 0.0, 0.0), (0.0, 0.0, 0.0)],
}

RGB_CHANNEL_INPUTS = {
    "dust":               ("ir_87", "ir_105", "ir_123"),
    "ash":                ("ir_87", "ir_105", "ir_123"),
    "fog":                ("ir_87", "ir_105", "ir_123"),
    "night_microphysics": ("ir_87", "ir_105", "ir_123"),
    "24h_microphysics":   ("ir_87", "ir_105", "ir_123"),
    "airmass":            ("wv_63", "wv_73", "ir_97", "ir_105"),
    "overshooting_tops":  ("wv_63", "ir_97", "ir_105"),
    "natural_color":      ("nir_16", "vis_08", "vis_06"),
    "cloud_phase":        ("nir_16", "nir_22", "vis_06"),
    "day_microphysics":   ("vis_08", "nir_16", "ir_105"),
    "cloud_type":         ("nir_13", "vis_06", "nir_16"),
    "true_color":         ("vis_08", "vis_06", "vis_05", "vis_04"),
}


# ══════════════════════════════════════════════════════════════════════════════
#  FREQUENCY PARSING
# ══════════════════════════════════════════════════════════════════════════════

def parse_freq(freq_str: str) -> timedelta:
    """
    Parse a frequency string like '1h', '30m', '2d' into a timedelta.
    Format: <integer><suffix>  where suffix is m / h / d.
    """
    m = re.fullmatch(r"(\d+)([mhd])", freq_str.strip().lower())
    if not m:
        sys.exit(
            f"Invalid --freq value '{freq_str}'.\n"
            "Expected format: <integer><suffix> where suffix is m, h, or d.\n"
            "Examples: 1h  30m  2d  6h"
        )
    k, unit = int(m.group(1)), m.group(2)
    if k <= 0:
        sys.exit("--freq multiplier must be a positive integer.")
    return {"m": timedelta(minutes=k), "h": timedelta(hours=k), "d": timedelta(days=k)}[unit]


def time_steps(start_dt: datetime, end_dt: datetime, step: timedelta) -> List[Tuple[datetime, datetime]]:
    """
    Return a list of (window_start, window_end) pairs stepping by `step`
    from start_dt to end_dt. Each window is [t, t + step).
    """
    steps = []
    t = start_dt
    while t < end_dt:
        steps.append((t, min(t + step, end_dt)))
        t += step
    return steps


# ══════════════════════════════════════════════════════════════════════════════
#  DOWNLOAD — one slot per time window
# ══════════════════════════════════════════════════════════════════════════════

def download_one_slot(window_start: datetime, window_end: datetime,
                      step_label: str) -> Optional[Path]:
    """
    Find the first available FCI product in [window_start, window_end],
    download and extract it, return the extracted directory path.
    Returns None on failure.
    The caller is responsible for deleting the directory after rendering.
    """
    print(f"\n{'─'*60}")
    print(f"  {step_label}  {window_start.strftime('%Y-%m-%dT%H:%M')} → "
          f"{window_end.strftime('%Y-%m-%dT%H:%M')} UTC")
    print(f"{'─'*60}")

    try:
        token      = eumdac.AccessToken((EUMETSAT_KEY, EUMETSAT_SECRET))
        datastore  = eumdac.DataStore(token)
        collection = datastore.get_collection(FCI_NR_COLLECTION)
        products   = list(collection.search(dtstart=window_start, dtend=window_end))
    except Exception as e:
        print(f"  ✗ EUMETSAT search error: {e}")
        return None

    if not products:
        print(f"  ✗ No FCI products found in this window — skipping.")
        return None

    product  = products[0]
    dest_dir = DOWNLOAD_DIR / str(product)
    zip_path = DOWNLOAD_DIR / f"{product}.zip"

    # Already extracted from a previous run — use as-is, caller must NOT delete
    if dest_dir.exists() and list(dest_dir.rglob("*.nc")):
        print(f"  ✓ Using cached: {product}")
        return dest_dir

    dest_dir.mkdir(exist_ok=True)
    try:
        print(f"  Downloading {product}…")
        with product.open() as remote, open(zip_path, "wb") as local:
            t0 = time.time()
            total = 0
            while chunk := remote.read(1024 * 1024):
                local.write(chunk)
                total += len(chunk)
                print(f"\r    {total/1e6:.1f} MB  "
                      f"{total/1e6/max(time.time()-t0, 0.1):.1f} MB/s  ",
                      end="", flush=True)
        print()

        print(f"  Extracting…")
        with zipfile.ZipFile(zip_path, "r") as zf:
            zf.extractall(dest_dir)
        zip_path.unlink(missing_ok=True)

        print(f"  ✓ Ready: {dest_dir.name}")
        return dest_dir

    except Exception as e:
        print(f"\n  ✗ Download/extract failed: {e}")
        shutil.rmtree(dest_dir, ignore_errors=True)
        zip_path.unlink(missing_ok=True)
        return None


def cleanup_slot(dest_dir: Path):
    """Delete a downloaded+extracted slot directory."""
    if dest_dir and dest_dir.exists():
        shutil.rmtree(dest_dir, ignore_errors=True)
        print(f"  Cleaned up: {dest_dir.name}")


# ══════════════════════════════════════════════════════════════════════════════
#  RENDER PIPELINE
# ══════════════════════════════════════════════════════════════════════════════

def load_fci_scene(slot_dir: Path):
    from satpy import Scene
    filenames = sorted([
        str(f) for f in slot_dir.rglob("*.nc")
        if "CHK-TRAIL" not in f.name.upper()
        and "CHK-HEAD"  not in f.name.upper()
    ])
    if not filenames:
        raise RuntimeError(f"No usable .nc files in {slot_dir}")
    return Scene(reader="fci_l1c_nc", filenames=filenames)


def get_timestamp(scn) -> str:
    try:
        return scn.start_time.strftime("%Y%m%dT%H%MZ")
    except Exception:
        return "unknown"


def bands_to_rgb_inputs(composite, bands):
    c = composite
    if c in ("dust", "ash", "24h_microphysics", "fog", "night_microphysics"):
        return (bands["ir_123"] - bands["ir_105"],
                bands["ir_105"] - bands["ir_87"],
                bands["ir_105"])
    if c == "airmass":
        return (bands["wv_63"] - bands["wv_73"],
                bands["ir_97"] - bands["ir_105"],
                bands["wv_63"])
    if c == "overshooting_tops":
        return (bands["wv_63"] - bands["ir_105"],
                bands["ir_97"] - bands["ir_105"],
                bands["wv_63"])
    if c == "natural_color":
        return bands["nir_16"], bands["vis_08"], bands["vis_06"]
    if c == "cloud_phase":
        return bands["nir_16"], bands["nir_22"], bands["vis_06"]
    if c == "day_microphysics":
        return bands["vis_08"], bands["nir_16"], bands["ir_105"]
    if c == "cloud_type":
        return bands["nir_13"], bands["vis_06"], bands["nir_16"]
    if c == "true_color":
        GAMMA = 2.3
        def _tc(ch):
            x = np.clip(ch / 110.0, 0.0, 1.0)
            return np.power(x, 1.0 / GAMMA).astype(np.float32)
        R = _tc(bands["vis_06"])
        B = _tc(bands["vis_04"])
        F = 0.15
        G_hybrid = ((1.0 - F) * np.clip(bands["vis_05"] / 110.0, 0.0, 1.0)
                  + F         * np.clip(bands["vis_08"] / 110.0, 0.0, 1.0))
        G = np.power(G_hybrid, 1.0 / GAMMA).astype(np.float32)
        def _sigmoid(x, k=8.0):
            return (1.0 / (1.0 + np.exp(-k * (x - 0.5)))).astype(np.float32)
        return _sigmoid(R), _sigmoid(G), _sigmoid(B)
    vals = list(bands.values())
    return vals[0], vals[1], vals[2]


def apply_recipe(arr, recipe):
    out = np.empty_like(arr)
    for i, (lo, hi, gamma) in enumerate(recipe):
        ch = arr[:, :, i]
        frac = (np.clip((lo - ch) / (lo - hi), 0, 1) if lo > hi
                else np.clip((ch - lo) / (hi - lo), 0, 1))
        out[:, :, i] = frac if gamma == 1.0 else np.power(frac, 1.0 / gamma)
    return out


def _get_bounds(area):
    import pyproj
    left, bottom, right, top = area.area_extent
    try:
        src_crs = pyproj.CRS(getattr(area, "crs",
                  getattr(area, "proj_dict", getattr(area, "proj_str", None))))
    except Exception:
        src_crs = pyproj.CRS("+proj=geos +lon_0=0 +h=35786023 +ellps=GRS80")
    tf = pyproj.Transformer.from_crs(src_crs, "EPSG:4326", always_xy=True)
    xs, ys = [], []
    for f in [i / 32 for i in range(33)]:
        x = left + f * (right - left)
        y = bottom + f * (top - bottom)
        xs += [x, x, left, right]
        ys += [bottom, top, y, y]
    lons, lats = tf.transform(xs, ys)
    valid = [(lo, la) for lo, la in zip(lons, lats)
             if math.isfinite(lo) and math.isfinite(la)
             and -180 <= lo <= 180 and -90 <= la <= 90]
    if not valid:
        return -81., -81., 81., 81.
    lv, ltv = zip(*valid)
    return max(-180., min(lv)), max(-90., min(ltv)), min(180., max(lv)), min(90., max(ltv))


def reproject_bands(arr_hwc, area):
    from pyresample import geometry as prgeom
    from pyresample.kd_tree import get_neighbour_info, get_sample_from_neighbour_info

    h, w, nb = arr_hwc.shape
    if max(h, w) > MAX_SRC:
        sc = MAX_SRC / max(h, w)
        nh, nw = max(1, int(round(h * sc))), max(1, int(round(w * sc)))
        ri = np.linspace(0, h - 1, nh, dtype=int)
        ci = np.linspace(0, w - 1, nw, dtype=int)
        arr_hwc = arr_hwc[np.ix_(ri, ci)]
        h, w = nh, nw
        try:
            pid = getattr(area, "proj_id", getattr(area, "area_id", "n"))
            cv  = getattr(area, "crs", getattr(area, "proj_dict",
                  getattr(area, "proj_str", None)))
            area = prgeom.AreaDefinition(
                area.area_id, area.description, pid, cv, nw, nh, area.area_extent)
        except Exception:
            pass

    wb, sb, eb, nb_ = _get_bounds(area)
    asp = (eb - wb) / max(nb_ - sb, 1e-6)
    oh  = h
    ow  = max(1, int(round(oh * asp)))
    ta  = prgeom.AreaDefinition(
        "wgs84", "WGS84", "wgs84",
        {"proj": "longlat", "datum": "WGS84"},
        ow, oh, [wb, sb, eb, nb_])
    left, bottom, right, top = area.area_extent
    px  = abs(right - left) / max(w, 1)
    py  = abs(top - bottom) / max(h, 1)
    roi = math.sqrt(px**2 + py**2) * 3.0

    ni_key = hashlib.sha256(
        f"{getattr(area,'area_id','?')}|{ow}|{oh}|{roi:.2f}".encode()
    ).hexdigest()[:20]

    if ni_key not in _ni_cache:
        if len(_ni_cache) >= _NI_CACHE_MAX:
            oldest = next(iter(_ni_cache))
            del _ni_cache[oldest]
        print(f"      computing neighbour info ({h}×{w} → {oh}×{ow})…")
        _ni_cache[ni_key] = get_neighbour_info(
            area, ta, radius_of_influence=roi, neighbours=1, nprocs=1)
    vi, vo, ia, _ = _ni_cache[ni_key]

    out = [
        get_sample_from_neighbour_info(
            'nn', ta.shape, arr_hwc[:, :, b].ravel(),
            vi, vo, ia, fill_value=np.nan
        ).reshape(ta.shape)
        for b in range(nb)
    ]
    return np.stack(out, -1).astype(np.float32), [wb, sb, eb, nb_]


def warp_mercator(arr_eq, bounds):
    w, s, e, n = bounds
    s_out = max(-85., s)
    n_out = min(85., n)
    def m2y(lat): return np.log(np.tan(math.pi / 4 + np.radians(np.clip(lat, -85.05, 85.05)) / 2))
    def y2m(y):   return np.degrees(2 * np.arctan(np.exp(y)) - math.pi / 2)
    h_eq, w_eq = arr_eq.shape[:2]
    lats_eq = np.linspace(n, s, h_eq)
    yn, ys = m2y(n_out), m2y(s_out)
    out_h = max(2, min(4096, int(round(w_eq * (yn - ys) / max(np.radians(e - w), 1e-6)))))
    out_lats = np.clip(y2m(np.linspace(yn, ys, out_h)), s_out, n_out)
    la_asc = lats_eq[::-1]
    clipped = np.clip(out_lats, lats_eq[-1], lats_eq[0])
    idxs = np.clip(np.searchsorted(la_asc, clipped, "left"), 0, h_eq - 1)
    rows = (h_eq - 1) - idxs
    return arr_eq[rows, :, :].astype(np.float32), [w, s_out, e, n_out]


def build_rgba(arr, composite):
    nan_mask = (np.isnan(arr[:, :, 0]) |
                np.isnan(arr[:, :, 1]) |
                np.isnan(arr[:, :, 2]))
    arr = np.nan_to_num(arr, nan=0.0)
    recipe = COMPOSITE_RECIPES.get(composite)
    _recipe_prebuilt = recipe is not None and all(g == 0.0 for _, _, g in recipe)
    if _recipe_prebuilt:
        arr = np.clip(arr, 0.0, 1.0)
    elif recipe:
        arr = apply_recipe(arr, recipe)
    else:
        for i in range(3):
            ch  = arr[:, :, i]
            pos = ch[ch > 0]
            lo  = np.percentile(pos, 2)  if pos.size else 0.
            hi  = np.percentile(pos, 98) if pos.size else 1.
            arr[:, :, i] = np.clip((ch - lo) / max(hi - lo, 1e-10), 0, 1)
        arr = np.clip(arr ** 0.7, 0, 1)
    h, w = arr.shape[:2]
    rgba = np.zeros((h, w, 4), dtype=np.uint8)
    rgba[:, :, :3] = (arr[:, :, :3] * 255).clip(0, 255).astype(np.uint8)
    rgba[:, :, 3]  = np.where(nan_mask, 0, 255).astype(np.uint8)
    return rgba


def render_one(scn, composite: str) -> Tuple[Optional[np.ndarray], Optional[list]]:
    import dask.array as dsa

    channels = RGB_CHANNEL_INPUTS.get(composite)
    if not channels:
        print(f"    ✗ no channel map for '{composite}'")
        return None, None

    print(f"    loading: {channels}")
    try:
        scn.load(list(channels))
    except Exception as e:
        print(f"    ✗ load error: {e}")
        return None, None

    def _ch(name):
        if name not in scn:
            raise RuntimeError(f"channel '{name}' missing from scene")
        da = scn[name]
        try:
            arr = (da.data.compute(scheduler='synchronous')
                   if hasattr(da, 'data') and isinstance(da.data, dsa.Array)
                   else (da.compute().values if hasattr(da, 'compute') else da.values))
        except Exception:
            arr = da.values if hasattr(da, "values") else np.asarray(da)
        if isinstance(arr, np.ma.MaskedArray):
            arr = arr.filled(np.nan)
        return np.squeeze(arr).astype(np.float32)

    try:
        bands = {ch: _ch(ch) for ch in channels}
    except RuntimeError as e:
        print(f"    ✗ {e}")
        return None, None

    r, g, b  = bands_to_rgb_inputs(composite, bands)
    arr_hwc  = np.stack([r, g, b], axis=-1)

    da   = scn[channels[0]]
    area = da.attrs.get("area") if hasattr(da, "attrs") else getattr(da, "area", None)
    if area is None:
        print(f"    ✗ no area definition")
        return None, None

    print(f"    reprojecting {arr_hwc.shape[0]}×{arr_hwc.shape[1]}…")
    arr_eq, bounds = reproject_bands(arr_hwc, area)
    print(f"    warping to Mercator…")
    arr_merc, bounds = warp_mercator(arr_eq, bounds)
    rgba = build_rgba(arr_merc, composite)
    return rgba, bounds


# ══════════════════════════════════════════════════════════════════════════════
#  PER-SLOT SUBPROCESS ENTRY POINT
# ══════════════════════════════════════════════════════════════════════════════

def _render_slot(slot_dir: Path, composites: list, seq_start: int) -> list:
    """
    Render all composites for ONE slot in a fresh subprocess.
    Prints results to stdout; parent reads them back.
    """
    manifest = []
    seq = seq_start

    try:
        scn_probe = load_fci_scene(slot_dir)
        ts = get_timestamp(scn_probe)
        del scn_probe
        gc.collect()
        print(f"  timestamp: {ts}", flush=True)
    except Exception as e:
        print(f"  ✗ could not load scene: {e}", flush=True)
        return manifest

    for composite in composites:
        print(f"  composite: {composite}", flush=True)
        try:
            scn = load_fci_scene(slot_dir)
        except Exception as e:
            print(f"  ✗ scene load failed for {composite}: {e}", flush=True)
            seq += 1
            continue

        rgba, bounds = render_one(scn, composite)
        del scn
        gc.collect()

        if rgba is None:
            seq += 1
            continue

        w, s, e, n = bounds
        fname = f"{seq}_{composite}_{ts}.png"
        fpath = EXPORT_DIR / fname
        PIL.Image.fromarray(rgba, "RGBA").save(str(fpath), format="PNG", compress_level=1)
        kb = fpath.stat().st_size / 1024
        print(f"  ✓ {fname}  ({rgba.shape[1]}×{rgba.shape[0]} px, {kb:.0f} KB)", flush=True)
        print(f"     bounds: W={w:.2f} S={s:.2f} E={e:.2f} N={n:.2f}", flush=True)
        manifest.append({
            "seq": seq, "file": fname, "composite": composite,
            "timestamp": ts, "bounds": [round(b, 4) for b in bounds],
            "shape": [rgba.shape[0], rgba.shape[1]],
        })
        seq += 1

    return manifest


# ══════════════════════════════════════════════════════════════════════════════
#  MAIN
# ══════════════════════════════════════════════════════════════════════════════

def main():
    parser = argparse.ArgumentParser(
        description="Download FCI L1C slots and render RGB composites, one time step at a time.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python download_and_export.py --composite dust --start 2026-06-20T12:00 --end 2026-06-20T15:00 --freq 1h
  python download_and_export.py --composite natural_color airmass --start 2026-06-20T00:00 --end 2026-06-21T00:00 --freq 6h
  python download_and_export.py --composite dust --hours-back 3 --freq 1h

Frequency format: <integer><suffix>  e.g.  30m  1h  2h  6h  1d  2d
""",
    )
    parser.add_argument("--composite", "-c", nargs="+", default=["dust"],
                        help="One or more composite names (default: dust)")
    parser.add_argument("--start", type=str, default=None,
                        help="Start datetime UTC, e.g. 2026-06-20T12:00")
    parser.add_argument("--end",   type=str, default=None,
                        help="End datetime UTC, e.g. 2026-06-20T15:00")
    parser.add_argument("--hours-back", type=int, default=3,
                        help="If --start/--end not given, search last N hours (default: 3)")
    parser.add_argument("--freq", type=str, default="1h",
                        help="Time step between slots, e.g. 30m / 1h / 2h / 1d (default: 1h)")
    # internal flag — used when the script re-launches itself per slot
    parser.add_argument("--_slot-dir",  type=str, default=None)
    parser.add_argument("--_seq-start", type=int, default=1)
    args = parser.parse_args()
    # Accept both --composite dust natural_color and --composite dust,natural_color
    args.composite = [c for token in args.composite for c in token.split(",") if c]

    # ── INTERNAL MODE: render one slot, print manifest JSON ───────────────────
    if args._slot_dir:
        results = _render_slot(Path(args._slot_dir), args.composite, args._seq_start)
        print(f"__MANIFEST_JSON__:{json.dumps(results)}", flush=True)
        return

    # ── NORMAL MODE ───────────────────────────────────────────────────────────
    if args.start and args.end:
        start_dt = datetime.fromisoformat(args.start).replace(tzinfo=timezone.utc)
        end_dt   = datetime.fromisoformat(args.end).replace(tzinfo=timezone.utc)
    else:
        end_dt   = datetime.now(timezone.utc)
        start_dt = end_dt - timedelta(hours=args.hours_back)

    step     = parse_freq(args.freq)
    windows  = time_steps(start_dt, end_dt, step)
    n_steps  = len(windows)

    print(f"\n{'═'*60}")
    print(f"Xenia — FCI batch export")
    print(f"  Composites : {', '.join(args.composite)}")
    print(f"  Range      : {start_dt.strftime('%Y-%m-%dT%H:%M')} → {end_dt.strftime('%Y-%m-%dT%H:%M')} UTC")
    print(f"  Frequency  : {args.freq}  ({n_steps} time step{'s' if n_steps != 1 else ''})")
    print(f"  Output     : {EXPORT_DIR.resolve()}")
    print(f"{'═'*60}")

    seq = 1

    for step_i, (win_start, win_end) in enumerate(windows, 1):
        label = f"[{step_i}/{n_steps}]"

        # 1. Download (max 1 slot per window)
        slot_dir = download_one_slot(win_start, win_end, label)
        if slot_dir is None:
            print(f"  {label} Skipping — no data.")
            continue

        was_cached = not (slot_dir.parent == DOWNLOAD_DIR and
                          str(slot_dir).endswith(str(slot_dir.name)))
        # More reliable cache check: if the dir existed before we tried to download
        # it, treat it as cached (don't delete after rendering)
        pre_existed = False
        try:
            pre_existed = slot_dir.stat().st_mtime < time.time() - 5
        except Exception:
            pass

        # 2. Render in a fresh subprocess (keeps HDF5/satpy state isolated)
        print(f"\n  {label} Rendering…")
        cmd = [
            sys.executable, __file__,
            "--composite", *args.composite,
            "--_slot-dir",  str(slot_dir),
            "--_seq-start", str(seq),
        ]
        result = subprocess.run(cmd, text=True, capture_output=False)
        if result.returncode != 0:
            print(f"  {label} ✗ subprocess exited with code {result.returncode}")

        # Advance seq counter by counting PNGs produced so far
        seq = len(list(EXPORT_DIR.glob("*.png"))) + 1

        # 3. Delete the download to free disk space
        #    Skip deletion if the slot was already on disk before this run
        if not pre_existed:
            cleanup_slot(slot_dir)
        else:
            print(f"  {label} Keeping cached slot: {slot_dir.name}")

        # 4. Explicit GC between steps
        gc.collect()
        print()

    # ── summary ───────────────────────────────────────────────────────────────
    pngs = sorted(
        EXPORT_DIR.glob("*.png"),
        key=lambda p: [int(t) if t.isdigit() else t for t in p.stem.split("_")],
    )

    print(f"\n{'═'*60}")
    print(f"Done!  {len(pngs)} PNG(s) in {EXPORT_DIR.resolve()}")
    print(f"{'═'*60}")
    for i, p in enumerate(pngs, 1):
        print(f"  {i:>3}. {p.name}")

    print()
    print("HOW TO ANIMATE IN XENIA")
    print("─" * 40)
    print("1. Sidebar → 'PNG Animation' card")
    print("2. 'Choose PNGs (multiple)' → select all files in exported_pngs/")
    print("3. Preset: FCI full disk  (-81, -81, 81, 81)")
    print("4. Leave 'Warp equirect → Mercator' = OFF")
    print("5. Click 'Prepare PNG animation' → enjoy!")
    print()
    print("Files are named  1_dust_…, 2_dust_…  for correct sort order.")


if __name__ == "__main__":
    main()