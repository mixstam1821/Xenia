"""
Xenia — FastAPI backend. Defines all HTTP routes (/api/render, /api/rgb,
/api/inspect, /api/datasets, etc.) and orchestrates the full request
lifecycle: scene loading (scenes.py), reprojection (geometry.py), colorization
and PNG export (rendering.py), using shared caches and cancel tokens from state.py.

"""

import os
import sys
import faulthandler

# ── crash diagnostics ────────────────────────────────────────────────────────
_CRASH_LOG_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "crash_trace.log")
_crash_log_fh = open(_CRASH_LOG_PATH, "a", buffering=1)
faulthandler.enable(file=_crash_log_fh, all_threads=True)

import json
import zipfile
import asyncio
import threading
import traceback
import io
import math
import hashlib
import struct
from concurrent.futures import TimeoutError as FuturesTimeout
from pathlib import Path
from datetime import datetime, timezone
from typing import Optional, List
from urllib.parse import unquote
from functools import lru_cache
import re
import numpy as np
from fastapi import FastAPI, HTTPException, Query, BackgroundTasks, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from state import *
from geometry import *
from scenes import *
from rendering import *
from scenes import _SCENE_ACCESS_LOCK



def _run_native(fn, *args, timeout: float = 120.0, **kwargs):
    """
    Run a native-heavy call (pyresample/proj/HDF5-touching) on the single
    dedicated worker thread in state._NATIVE_EXECUTOR instead of whatever
    anyio threadpool thread happened to handle this request.

    Why: FastAPI/Starlette hands each sync `def` route to a *different*
    short-lived thread from anyio's pool. Native extensions used deep in
    geometry.py/rendering.py (pyresample's OpenMP-backed KD-tree resampler,
    PROJ, HDF5 via netcdf4/h5netcdf/h5py) are not guaranteed safe to
    first-initialize from an arbitrary, soon-to-be-recycled thread — that
    race is what caused the segfault. Funnelling every such call through
    one persistent thread means the native libs only ever get touched by
    a thread that lives for the whole process, eliminating the race.

    If the worker thread's process-level native state is ever left
    corrupted by a near-miss, this also gives us one place to detect a
    dead/unresponsive worker and surface it as a normal HTTP error
    instead of the request just hanging or the server dying silently.
    """
    future = _NATIVE_EXECUTOR.submit(fn, *args, **kwargs)
    try:
        return future.result(timeout=timeout)
    except FuturesTimeout:
        _render_cancel.set()
        raise HTTPException(
            504,
            "Render timed out in native processing stage (reprojection took "
            f"longer than {int(timeout)}s). The render has been cancelled — "
            "try again, or use a lower quality setting."
        )
import warnings
warnings.filterwarnings("ignore")
# ── PROJ conflict fix ─────────────────────────────────────────────────────────
def _fix_proj_data():
    try:
        import rasterio as _rio
        _rio_dir = os.path.dirname(_rio.__file__)
        _candidates = [
            os.path.join(_rio_dir, "proj_data"),
            os.path.join(_rio_dir, "..", "share", "proj"),
            os.path.join(sys.prefix, "share", "proj"),
            os.path.join(sys.prefix, "Library", "share", "proj"),
        ]
        for c in _candidates:
            c = os.path.normpath(c)
            if os.path.isfile(os.path.join(c, "proj.db")):
                os.environ["PROJ_DATA"] = c
                os.environ["PROJ_LIB"]  = c
                break
    except Exception:
        pass

_fix_proj_data()

from dotenv import load_dotenv
load_dotenv()

import xarray as xr
import PIL.Image

# NOTE: Scene, group_files, find_files_and_readers, SATPY_AVAILABLE now
# come from scenes.py (imported via `from scenes import *` above).

try:
    import eumdac
    EUMDAC_AVAILABLE = True
except ImportError:
    EUMDAC_AVAILABLE = False



# Add this helper near the top of main.py, after imports:
def _extract_timestamp_from_path(filepath: str) -> str:
    import re
    name = Path(filepath).name

    # FCI L1c: _OPE_20260616184007_20260616184935_ → use scan start
    m = re.search(r'_OPE_(\d{14})_(\d{14})', name)
    if m:
        s = m.group(1)  # scan start
        return f"{s[:4]}-{s[4:6]}-{s[6:8]} {s[8:10]}:{s[10:12]} UTC"

    # LSASAF / general: delimiter before 14-digit, anything after
    m = re.search(r'[_,](\d{14})(?:[_,.]|$)', name)
    if m:
        s = m.group(1)
        return f"{s[:4]}-{s[4:6]}-{s[6:8]} {s[8:10]}:{s[10:12]} UTC"

    # With T separator: 20250601T060000Z
    m = re.search(r'(\d{8})T(\d{4,6})Z?', name)
    if m:
        d, t = m.group(1), m.group(2)[:4]
        return f"{d[:4]}-{d[4:6]}-{d[6:]} {t[:2]}:{t[2:]} UTC"

    return ""

from contextlib import asynccontextmanager

@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup: increase thread pool so dataset reads don't queue behind renders
    import anyio.to_thread
    limiter = anyio.to_thread.current_default_thread_limiter()
    limiter.total_tokens = 20
    yield
    # Shutdown: nothing needed

app = FastAPI(title="MTG Viewer", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# ── config ────────────────────────────────────────────────────────────────────
# NOTE: DATA_DIR is defined in scenes.py (imported via `from scenes import *`).
DATA_DIR.mkdir(exist_ok=True)

EUMETSAT_KEY    = os.environ.get("EUMETSAT_KEY", "")
EUMETSAT_SECRET = os.environ.get("EUMETSAT_SECRET", "")

# https://api.eumetsat.int/data/browse/collections
COLLECTIONS = {
    # --- FCI L1c ---
    "FCI L1c NR":                    "EO:EUM:DAT:0662",  # Normal Resolution
    "FCI L1c HR":                    "EO:EUM:DAT:0665",  # High Resolution

    # --- FCI L2 ---
    "FCI L2 Cloud Mask":             "EO:EUM:DAT:0678",  # Cloud Mask (netCDF)
    "FCI L2 Cloud Type":             "EO:EUM:DAT:0680",  # Cloud Type
    "FCI L2 CTH":                    "EO:EUM:DAT:0681",  # Cloud Top Temperature and Height
    "FCI L2 OCA":                    "EO:EUM:DAT:0684",  # Optimal Cloud Analysis
    "FCI L2 ASR":                    "EO:EUM:DAT:0677",  # All Sky Radiance (netCDF)
    "FCI L2 AMV":                    "EO:EUM:DAT:0676",  # Atmospheric Motion Vectors (netCDF)
    "FCI L2 GII":                    "EO:EUM:DAT:0683",  # Global Instability Indices
    "FCI L2 OLR":                    "EO:EUM:DAT:0685",  # Outgoing LW Radiation at TOA
    "FCI L2 LST":                    "EO:EUM:DAT:1088",  # Land Surface Temperature
    "FCI L2 SST":                    "EO:EUM:DAT:0694",  # Sea Surface Temperature
    "FCI L2 Fire":                   "EO:EUM:DAT:0682",  # Active Fire Monitoring (netCDF)
    "FCI L2 CSRM":                   "EO:EUM:DAT:0679",  # Clear Sky Reflectance Map
    "FCI L2 Precip Rate":            "EO:EUM:DAT:1086",  # Precipitation Rate (blended FCI IR / LEO MW)
    "FCI L2 Precip Accum":           "EO:EUM:DAT:1087",  # Accumulated Precipitation (blended MW+IR)
    "FCI L2 Snow Mask":              "EO:EUM:DAT:1091",  # Snow Detection (VIS/NIR)

    # --- LI L2 ---
    "LI L2 Lightning Events":        "EO:EUM:DAT:0690",  # Lightning Events Filtered
    "LI L2 Lightning Groups":        "EO:EUM:DAT:0782",  # Lightning Groups
    "LI L2 Lightning Flashes":       "EO:EUM:DAT:0691",  # Lightning Flashes
    "LI L2 Accum Flashes":           "EO:EUM:DAT:0686",  # Accumulated Flashes
    "LI L2 Accum Flash Area":        "EO:EUM:DAT:0687",  # Accumulated Flash Area
    "LI L2 Accum Flash Radiance":    "EO:EUM:DAT:0688",  # Accumulated Flash Radiance
}

download_jobs: dict[str, dict] = {}

# ── models ────────────────────────────────────────────────────────────────────
class DownloadRequest(BaseModel):
    collection: str
    start: str
    end: str
    limit: int = 3

class RenderRequest(BaseModel):
    filepath: str
    dataset: str
    reader: Optional[str] = None
    colormap: str = "RdYlBu_r"
    vmin: Optional[float] = None
    vmax: Optional[float] = None

class RecolorRequest(BaseModel):
    geom_key: str
    colormap: str = "RdYlBu_r"
    vmin: Optional[float] = None
    vmax: Optional[float] = None


# ══════════════════════════════════════════════════════════════════════════════
#  PERFORMANCE CACHES  
# ══════════════════════════════════════════════════════════════════════════════

# NOTE: _LRUCache class, _render_cancel, _render_lock, _GEOM_CACHE,
# _RENDER_CACHE, _NEIGHBOUR_INFO_CACHE now live in state.py (imported via
# `from state import *` above) since geometry.py/rendering.py need the
# SAME instances, not copies.
_INFLIGHT: dict[str, threading.Event] = {}
_INFLIGHT_LOCK = threading.Lock()
_INFLIGHT_RESULTS: dict[str, object] = {}


def _make_geom_key(filepath: str, dataset: str, quality: str, extra_dims_json: str) -> str:
    """Stable cache key for the expensive reprojection step."""
    raw = f"{filepath}|{dataset}|{quality}|{extra_dims_json}"
    return hashlib.sha256(raw.encode()).hexdigest()[:24]


def _make_render_key(geom_key: str, colormap: str, vmin, vmax) -> str:
    raw = f"{geom_key}|{colormap}|{vmin}|{vmax}"
    return hashlib.sha256(raw.encode()).hexdigest()[:24]


# NOTE: _unwrap_longitudes moved to geometry.py (it's called internally by
# reproject_to_wgs84 / _reproject_from_latlon_2d, so it has to live there —
# imported back via `from geometry import *` above).


# ── ZIP auto-extraction ───────────────────────────────────────────────────────
# ── helpers ───────────────────────────────────────────────────────────────────
def get_eumdac_token():
    if not EUMDAC_AVAILABLE:
        raise HTTPException(503, "eumdac not installed. pip install eumdac")
    if not EUMETSAT_KEY:
        raise HTTPException(503, "EUMETSAT_KEY env var not set")
    return eumdac.AccessToken((EUMETSAT_KEY, EUMETSAT_SECRET))

_ANCILLARY_SUFFIXES = ("_earth_sun_distance", "_sun_earth_distance", "_counts",)

def _is_renderable_dataset(name: str) -> bool:
    nl = name.lower()
    return not any(nl.endswith(s) for s in _ANCILLARY_SUFFIXES)




# ── routes ────────────────────────────────────────────────────────────────────

@app.get("/api/collections")
def list_collections():
    return COLLECTIONS


@app.get("/api/render_raw")
def render_raw(
    geom_key: str,
):
    """
    Returns the cached float32 reprojected array as raw binary:
    4-byte header (uint32 rows, uint32 cols), then row-major float32 values.
    NaNs are preserved as NaN bytes.
    """
    cached_geom = _GEOM_CACHE.get(geom_key)
    if cached_geom is None:
        raise HTTPException(404, f"Geometry not in cache (key={geom_key}). Call /api/render first.")
    arr_wgs, bounds, _, _ = cached_geom
    rows, cols = arr_wgs.shape
    header = struct.pack("<II", rows, cols)
    body = arr_wgs.astype("<f4").tobytes()
    return Response(content=header + body, media_type="application/octet-stream")



@app.get("/api/files")
def list_files():
    extract_eumetsat_zips()
    product_dirs: set[Path] = set()
    for d in DATA_DIR.iterdir():
        if d.is_dir() and any(d.rglob("*.nc")):
            product_dirs.add(d)

    top_level_nc: list[Path] = []
    for p in DATA_DIR.rglob("*.nc"):
        inside_product = any(p.is_relative_to(pd) for pd in product_dirs)
        if not inside_product:
            top_level_nc.append(p)

    files = []
    for p in sorted(top_level_nc):
        rel = str(p.relative_to(DATA_DIR))
        stat = p.stat()
        files.append({
            "path":      rel,
            "size_mb":   round(stat.st_size / 1e6, 1),
            "mtime":     stat.st_mtime,
            "name":      p.name,
            "suffix":    p.suffix,
        })
    for d in sorted(product_dirs):
        rel  = str(d.relative_to(DATA_DIR))
        nc_files = list(d.rglob("*.nc"))
        size = sum(f.stat().st_size for f in nc_files) / 1e6
        mtime = max(f.stat().st_mtime for f in nc_files) if nc_files else 0
        files.append({
            "path":      rel,
            "size_mb":   round(size, 1),
            "mtime":     mtime,
            "name":      d.name,
            "suffix":    "",
        })
    return files


class SetDataDirRequest(BaseModel):
    path: str

@app.post("/api/set_data_dir")
def set_data_dir(req: SetDataDirRequest):
    import scenes
    p = Path(req.path).expanduser().resolve()
    if not p.is_dir():
        raise HTTPException(400, f"Directory does not exist: {p}")
    scenes.DATA_DIR = p
    # also update the module-level name that main.py uses via `from scenes import *`
    globals()["DATA_DIR"] = p
    _GEOM_CACHE.clear()
    _RENDER_CACHE.clear()
    return {"data_dir": str(p)}

@app.get("/api/get_data_dir")
def get_data_dir():
    import scenes
    return {"data_dir": str(scenes.DATA_DIR)}



@app.get("/api/inspect")
def inspect_file(filepath: str):
    import concurrent.futures
    from state import _NATIVE_EXECUTOR

    def _do_inspect():
        filenames = get_filenames_for_path(filepath)
        nc_file   = filenames[0]

        def _arr_summary(arr):
            a = np.asarray(arr, dtype=float).ravel()
            valid = a[np.isfinite(a)]
            if valid.size == 0:
                return {"shape": list(arr.shape), "all_nan": True}
            return {
                "shape":   list(arr.shape),
                "min":     round(float(valid.min()), 6),
                "max":     round(float(valid.max()), 6),
                "has_nan": bool(valid.size < a.size),
            }

        def _inspect_via_h5py(nc_file, group=None):
            """Use h5py directly — more robust to thread re-init than netCDF4/xarray."""
            import h5py
            with h5py.File(nc_file, "r") as f:
                grp = f[group] if group else f
                if not grp.keys():
                    return None

                def _h5_attrs(obj):
                    return {k: str(v)[:120] for k, v in obj.attrs.items()}

                def _h5_var_attrs(ds):
                    return {k: str(ds.attrs[k])[:80] for k in ds.attrs}

                result = {
                    "file":         nc_file,
                    "global_attrs": _h5_attrs(grp),
                    "dimensions":   {},   # h5py has no named dims; filled from shapes
                    "coordinates":  {},
                    "variables":    {},
                    "grid_mapping": {},
                }

                coord_kw = {"lat", "latitude", "lon", "longitude",
                            "time", "x", "y", "level", "pressure"}

                def _visit(name, obj):
                    if not isinstance(obj, h5py.Dataset):
                        return
                    attrs  = _h5_var_attrs(obj)
                    shape  = list(obj.shape)
                    size   = int(np.prod(shape)) if shape else 0
                    entry  = {
                        "dims":  [str(d) for d in obj.dims] if obj.dims else [],
                        "shape": shape,
                        "dtype": str(obj.dtype),
                        "attrs": attrs,
                    }
                    if size < 500_000:
                        try:
                            raw = obj[()]
                            arr = np.asarray(raw, dtype=np.float64)
                            entry.update(_arr_summary(arr))
                        except Exception as e:
                            entry["read_error"] = str(e)

                    leaf = name.split("/")[-1]
                    if leaf.lower() in coord_kw or attrs.get("axis"):
                        result["coordinates"][leaf] = entry
                    else:
                        result["variables"][leaf] = entry

                    gm = attrs.get("grid_mapping")
                    if gm and not result["grid_mapping"] and gm in grp:
                        gm_attrs = {k: str(grp[gm].attrs[k]) for k in grp[gm].attrs}
                        result["grid_mapping"] = {"variable": gm, "attrs": gm_attrs}

                grp.visititems(_visit)
                if not result["variables"] and not result["coordinates"]:
                    return None
                return result

        # Walk candidate groups — h5py only, no netCDF4/xarray file open
        with _SCENE_ACCESS_LOCK:
            groups_to_try = [None, "PRODUCT", "product", "data", "Data"]
            for group in groups_to_try:
                try:
                    r = _inspect_via_h5py(nc_file, group)
                    if r is not None:
                        return r
                except Exception:
                    continue

            # Last resort: list top-level groups
            try:
                import h5py
                with h5py.File(nc_file, "r") as f:
                    groups = list(f.keys())
                raise HTTPException(400, f"All groups empty. Top-level groups: {groups}")
            except HTTPException:
                raise
            except Exception:
                raise HTTPException(400, "Could not open file with h5py.")

    future = _NATIVE_EXECUTOR.submit(_do_inspect)
    try:
        return future.result(timeout=25)
    except concurrent.futures.TimeoutError:
        raise HTTPException(503, "inspect timed out")
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(400, str(e))

@app.get("/api/datasets")
def list_datasets(filepath: str, reader: Optional[str] = None):
    import concurrent.futures
    
    def _do_list():
        scene     = load_scene(filepath, reader)
        available = scene.available_dataset_names()
        renderable = sorted(n for n in available if _is_renderable_dataset(n))
        result = []
        for name in renderable:
            try:
                da    = scene[name]
                dims  = list(da.dims)  if hasattr(da, "dims")  else []
                shape = list(da.shape) if hasattr(da, "shape") else []
                if len(shape) >= 2 and len(dims) == len(shape):
                    spatial_axes = _spatial_axes(dims, shape)
                elif len(shape) >= 2:
                    sorted_axes = sorted(range(len(shape)), key=lambda i: shape[i], reverse=True)
                    spatial_axes = set(sorted_axes[:2])
                else:
                    spatial_axes = set(range(len(shape)))
                extra = []
                for i, (d, s) in enumerate(zip(dims, shape)):
                    if i in spatial_axes: continue
                    if s <= 1: continue
                    coord_vals = []
                    try:
                        if hasattr(da, "coords") and d in da.coords:
                            raw = da.coords[d].values
                            coord_vals = [str(v) for v in raw]
                    except Exception:
                        pass
                    if not coord_vals:
                        coord_vals = [str(k) for k in range(s)]
                    extra.append({"name": d, "size": s, "values": coord_vals})
                result.append({"name": name, "dims": dims, "shape": shape, "extra_dims": extra})
            except Exception:
                result.append({"name": name, "dims": [], "shape": [], "extra_dims": []})
        return result

    # Check scene cache first — if already cached this returns instantly
    cache_key = (filepath, reader)
    if _cache_get(cache_key) is not None:
        try:
            return _do_list()
        except HTTPException:
            raise
        except Exception as e:
            raise HTTPException(400, str(e))

    # Not cached — run with timeout so a stuck render doesn't block forever
    # Not cached — submit to the persistent _NATIVE_EXECUTOR so HDF5/netcdf4
    # C libs are always touched from the same long-lived thread (never a
    # throwaway ThreadPoolExecutor thread → no segfault on first HDF5 init).
    from state import _NATIVE_EXECUTOR
    future = _NATIVE_EXECUTOR.submit(_do_list)
    try:
        return future.result(timeout=25)
    except concurrent.futures.TimeoutError:
        raise HTTPException(503, "Dataset read timed out (backend busy). "
                                 "Stop any running render and try again.")
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(400, str(e))

@app.get("/api/render")
def render_dataset(
    filepath:      str,
    dataset:       str,
    reader:        Optional[str]   = None,
    colormap:      str             = "RdYlBu_r",
    vmin:          Optional[float] = None,
    vmax:          Optional[float] = None,
    quality:       str             = "normal",
    extra_dims:    Optional[str]   = None,
    custom_colors: Optional[str]   = None,
):
    try:
        max_px = 4096 if quality == "high" else 3072

        edims: Optional[dict] = None
        if extra_dims:
            try:
                edims = json.loads(extra_dims)
            except Exception:
                pass

        edims_json = json.dumps(edims, sort_keys=True) if edims else "{}"

        abs_path = str(resolve_filepath(filepath))
        geom_key  = _make_geom_key(abs_path, dataset, quality, edims_json)
        render_key = _make_render_key(geom_key, colormap,
                                      str(vmin) if vmin is not None else "auto",
                                      str(vmax) if vmax is not None else "auto")

        # Full render cache hit — no lock needed, instant
        cached_render = _RENDER_CACHE.get(render_key)
        if cached_render and not custom_colors:
            png_bytes, bounds, out_vmin, out_vmax, shape = cached_render
            headers = {
                "X-Bounds":    ",".join(str(round(b, 4)) for b in bounds),
                "X-Vmin":      str(round(out_vmin, 4)),
                "X-Vmax":      str(round(out_vmax, 4)),
                "X-Dataset":   dataset,
                "X-Shape":     f"{shape[0]}x{shape[1]}",
                "X-GeomKey":   geom_key,
                "X-Cached":    "1",
                "X-Timestamp": _extract_timestamp_from_path(filepath),
                "Access-Control-Expose-Headers":
                    "X-Bounds,X-Vmin,X-Vmax,X-Dataset,X-Shape,X-GeomKey,X-Cached,X-Timestamp",
            }
            return StreamingResponse(io.BytesIO(png_bytes), media_type="image/png", headers=headers)

        # Geometry cache hit → only re-colorize, fast, no lock needed
        cached_geom = _GEOM_CACHE.get(geom_key)
        if cached_geom and not custom_colors:
            arr_wgs, bounds, auto_vmin, auto_vmax = cached_geom
            out_vmin = vmin if vmin is not None else auto_vmin
            out_vmax = vmax if vmax is not None else auto_vmax
            png_bytes = array_to_png_bytes(arr_wgs, colormap, out_vmin, out_vmax)
            bounds    = _sanitize_bounds(bounds)
            shape     = arr_wgs.shape
            _RENDER_CACHE.put(render_key, (png_bytes, bounds, out_vmin, out_vmax, shape))
            headers = {
                "X-Bounds":    ",".join(str(round(b, 4)) for b in bounds),
                "X-Vmin":      str(round(out_vmin, 4)),
                "X-Vmax":      str(round(out_vmax, 4)),
                "X-Dataset":   dataset,
                "X-Shape":     f"{shape[0]}x{shape[1]}",
                "X-GeomKey":   geom_key,
                "X-Cached":    "geom",
                "X-Timestamp": _extract_timestamp_from_path(filepath),
                "Access-Control-Expose-Headers":
                    "X-Bounds,X-Vmin,X-Vmax,X-Dataset,X-Shape,X-GeomKey,X-Cached,X-Timestamp",
            }
            return StreamingResponse(io.BytesIO(png_bytes), media_type="image/png", headers=headers)


        # ── Expensive path: only one render at a time ──────────────────────
        if not _render_lock.acquire(blocking=False):
            raise HTTPException(
                409,
                "A render is already in progress. Stop it (⏹) or wait for it to finish "
                "before starting another."
            )

        try:
            _render_cancel.clear()  # reset cancel flag for new render


            import dask as _dask
            scene = load_scene(filepath, reader)


            # ── Hold _SCENE_ACCESS_LOCK for all HDF5/netCDF4 handle access ──
            # The cached scene object wraps a shared file handle. Concurrent
            # requests (e.g. /api/stats, /api/datasets) calling scene[name] or
            # .values on the same handle from different threads is a data race
            # → segfault. The lock serializes all handle touches; it is an
            # RLock so re-entry from load_scene itself is safe.
            # We hold it until da_to_2d() returns a plain numpy array, after
            # which no file handle is touched and the lock can be released.
            with _SCENE_ACCESS_LOCK, _dask.config.set(scheduler='synchronous'):
                scene.load([dataset])
                if dataset not in scene:
                    raise HTTPException(400, f"Dataset '{dataset}' not in scene after load.")

                da = scene[dataset]


                # ── UXarray branch ────────────────────────────────────────
                if isinstance(scene, _UXarrayScene):
                    grid     = da.uxgrid
                    face_lon = grid.face_lon.values.astype(np.float64)
                    face_lat = grid.face_lat.values.astype(np.float64)
                    val_v    = np.asarray(da.values, dtype=np.float32)
                    valid    = np.isfinite(val_v)
                    dx_deg   = float(np.degrees(np.nanmean(np.diff(np.sort(np.unique(face_lon))))))
                # ── end UXarray branch (numpy arrays extracted, lock still held until after) ──

                if not isinstance(scene, _UXarrayScene):
                    arr    = da_to_2d(da, extra_dims=edims)
                    area   = da.attrs.get("area") if hasattr(da, "attrs") else None
                    if area is None:
                        area = getattr(da, "area", None)
                    raw_ds = scene._ds if isinstance(scene, _XarrayScene) else None

            # ── Lock released — everything below works on plain numpy only ──

            if isinstance(scene, _UXarrayScene):
                arr_wgs, bounds = _run_native(
                    _build_mercator_output,
                    face_lat[valid], face_lon[valid], val_v[valid],
                    dx_deg=max(dx_deg, 0.01), dy_deg=max(dx_deg, 0.01),
                    max_px=max_px,
                )
                bounds = _sanitize_bounds(bounds)
                valid_wgs = arr_wgs[~np.isnan(arr_wgs)]
                auto_vmin = float(np.percentile(valid_wgs, 2))  if valid_wgs.size else 0.0
                auto_vmax = float(np.percentile(valid_wgs, 98)) if valid_wgs.size else 1.0
                out_vmin  = vmin if vmin is not None else auto_vmin
                out_vmax  = vmax if vmax is not None else auto_vmax
                _GEOM_CACHE.put(geom_key, (arr_wgs, bounds, auto_vmin, auto_vmax))
                png_bytes = array_to_png_bytes(arr_wgs, colormap, out_vmin, out_vmax)
                shape = arr_wgs.shape
                _RENDER_CACHE.put(render_key, (png_bytes, bounds, out_vmin, out_vmax, shape))
                headers = {
                    "X-Bounds":    ",".join(str(round(b, 4)) for b in bounds),
                    "X-Vmin":      str(round(out_vmin, 4)),
                    "X-Vmax":      str(round(out_vmax, 4)),
                    "X-Dataset":   dataset,
                    "X-Shape":     f"{shape[0]}x{shape[1]}",
                    "X-GeomKey":   geom_key,
                    "X-Cached":    "0",
                    "X-Timestamp": _extract_timestamp_from_path(filepath),
                    "Access-Control-Expose-Headers":
                        "X-Bounds,X-Vmin,X-Vmax,X-Dataset,X-Shape,X-GeomKey,X-Cached,X-Timestamp",
                }
                return StreamingResponse(io.BytesIO(png_bytes), media_type="image/png", headers=headers)

            valid       = arr[~np.isnan(arr)]


            auto_vmin   = float(np.percentile(valid, 2))  if valid.size else 0.0
            auto_vmax   = float(np.percentile(valid, 98)) if valid.size else 1.0
            out_vmin    = vmin if vmin is not None else auto_vmin
            out_vmax    = vmax if vmax is not None else auto_vmax


            png_bytes, bounds, shape, _ = _run_native(
                render_array,
                arr, area, colormap, out_vmin, out_vmax, max_px,
                da=da, raw_ds=raw_ds, geom_key=geom_key,
                custom_colors=custom_colors,
            )


            bounds = _sanitize_bounds(bounds)


            if not custom_colors:
                _RENDER_CACHE.put(render_key, (png_bytes, bounds, out_vmin, out_vmax, shape))


            headers = {
                "X-Bounds":    ",".join(str(round(b, 4)) for b in bounds),
                "X-Vmin":      str(round(out_vmin, 4)),
                "X-Vmax":      str(round(out_vmax, 4)),
                "X-Dataset":   dataset,
                "X-Shape":     f"{shape[0]}x{shape[1]}",
                "X-GeomKey":   geom_key,
                "X-Cached":    "0",
                "X-Timestamp": _extract_timestamp_from_path(filepath),
                "Access-Control-Expose-Headers":
                    "X-Bounds,X-Vmin,X-Vmax,X-Dataset,X-Shape,X-GeomKey,X-Cached,X-Timestamp",
            }
            return StreamingResponse(io.BytesIO(png_bytes), media_type="image/png", headers=headers)
        finally:
            _render_lock.release()


    except HTTPException:
        raise
    except Exception:
        raise HTTPException(500, f"Render failed:\n{traceback.format_exc()}")


@app.get("/api/recolor")
def recolor_dataset(
    geom_key:      str,
    colormap:      str             = "RdYlBu_r",
    vmin:          Optional[float] = None,
    vmax:          Optional[float] = None,
    custom_colors: Optional[str]   = None,
):
    """
    Ultra-fast recolor: uses cached geometry, only re-runs colormap.
    Returns PNG + same headers as /api/render.
    Used by frontend when only colormap / vmin / vmax change.
    """
    cached_geom = _GEOM_CACHE.get(geom_key)
    if cached_geom is None:
        raise HTTPException(404, f"Geometry not in cache (key={geom_key}). "
                                  "Call /api/render first.")
    arr_wgs, bounds, auto_vmin, auto_vmax = cached_geom
    out_vmin = vmin if vmin is not None else auto_vmin
    out_vmax = vmax if vmax is not None else auto_vmax

    png_bytes = array_to_png_bytes(arr_wgs, colormap, out_vmin, out_vmax,
                                   custom_colors=custom_colors)
    bounds_s  = _sanitize_bounds(bounds)
    shape     = arr_wgs.shape

    headers = {
        "X-Bounds":    ",".join(str(round(b, 4)) for b in bounds_s),
        "X-Vmin":      str(round(out_vmin, 4)),
        "X-Vmax":      str(round(out_vmax, 4)),
        "X-GeomKey":   geom_key,
        "X-Shape":     f"{shape[0]}x{shape[1]}",
        "X-Cached":    "recolor",
        "Access-Control-Expose-Headers":
            "X-Bounds,X-Vmin,X-Vmax,X-GeomKey,X-Shape,X-Cached",
    }
    return StreamingResponse(io.BytesIO(png_bytes), media_type="image/png", headers=headers)


@app.get("/api/cache_info")
def cache_info():
    """Debug: inspect cache occupancy."""
    return {
        "scene_cache":      len(_scene_cache),
        "geom_cache":       len(_GEOM_CACHE),
        "render_cache":     len(_RENDER_CACHE),
        "neighbour_cache":  len(_NEIGHBOUR_INFO_CACHE),
        "geom_keys":        _GEOM_CACHE.keys()[:10],
    }

@app.post("/api/cache_clear")
def cache_clear():
    """Clear all caches (useful after data update)."""
    _scene_cache.clear()
    _scene_cache_order.clear()
    _GEOM_CACHE.clear()
    _RENDER_CACHE.clear()
    _NEIGHBOUR_INFO_CACHE.clear()
    return {"cleared": True}


@app.post("/api/cancel_render")
def cancel_render():
    """Signal the backend to abandon the current render as soon as possible."""
    _render_cancel.set()
    return {"cancelled": True}


@app.get("/api/stats")
def dataset_stats(
    filepath:   str,
    dataset:    str,
    reader:     Optional[str] = None,
    extra_dims: Optional[str] = None,
):
    try:
        edims: Optional[dict] = None
        if extra_dims:
            try:
                edims = json.loads(extra_dims)
            except Exception:
                pass

        abs_path   = str(resolve_filepath(filepath))
        edims_json = json.dumps(edims, sort_keys=True) if edims else "{}"
        geom_key   = _make_geom_key(abs_path, dataset, "normal", edims_json)
        cached_geom = _GEOM_CACHE.get(geom_key)
        if cached_geom:
            arr_wgs, _, auto_vmin, auto_vmax = cached_geom
            valid = arr_wgs[~np.isnan(arr_wgs)]
            import dask as _dask
            scene = load_scene(filepath, reader)
            with _SCENE_ACCESS_LOCK, _dask.config.set(scheduler='synchronous'):
                da = scene[dataset]
            attrs = getattr(da, "attrs", {})
            return {
                "dataset":   dataset,
                "units":     attrs.get("units", ""),
                "long_name": attrs.get("long_name", dataset),
                "min":       round(float(np.min(valid)),  4) if valid.size else None,
                "max":       round(float(np.max(valid)),  4) if valid.size else None,
                "mean":      round(float(np.mean(valid)), 4) if valid.size else None,
                "p2":        round(float(np.percentile(valid,  2)), 4) if valid.size else None,
                "p98":       round(float(np.percentile(valid, 98)), 4) if valid.size else None,
                "shape":     list(arr_wgs.shape),
                "valid_px":  int(valid.size),
                "total_px":  int(arr_wgs.size),
                "sparse":    arr_wgs.ndim == 1,
                "source":    "geom_cache",
            }

        import dask as _dask
        scene = load_scene(filepath, reader)
        with _SCENE_ACCESS_LOCK, _dask.config.set(scheduler='synchronous'):
            scene.load([dataset])
            da  = scene[dataset]
            arr = da_to_2d(da, extra_dims=edims)
        valid = arr[~np.isnan(arr)]
        attrs = getattr(da, "attrs", {})
        return {
            "dataset":   dataset,
            "units":     attrs.get("units", ""),
            "long_name": attrs.get("long_name", dataset),
            "min":       round(float(np.min(valid)),  4) if valid.size else None,
            "max":       round(float(np.max(valid)),  4) if valid.size else None,
            "mean":      round(float(np.mean(valid)), 4) if valid.size else None,
            "p2":        round(float(np.percentile(valid,  2)), 4) if valid.size else None,
            "p98":       round(float(np.percentile(valid, 98)), 4) if valid.size else None,
            "shape":     list(arr.shape),
            "valid_px":  int(valid.size),
            "total_px":  int(arr.size),
            "sparse":    arr.ndim == 1,
            "source":    "fresh",
        }
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(500, str(e))

class TimeseriesRequest(BaseModel):
    filepath: str
    dataset: str
    reader: Optional[str] = None
    lat: float
    lon: float
    time_dim: str = ""
    extra_dims: Optional[dict] = None

@app.post("/api/timeseries")
def timeseries(req: TimeseriesRequest):
    try:
        import dask as _dask
        scene = load_scene(req.filepath, req.reader)
        with _dask.config.set(scheduler='synchronous'):
            scene.load([req.dataset])
        da = scene[req.dataset]

        # ── auto-detect time-like dim ──────────────────────────────────
        _TIME_RE = re.compile(
            r'^(time|year|month|day|hour|date|step|forecast|valid|lead|reftime|t)$',
            re.IGNORECASE
        )
        time_dim = req.time_dim if req.time_dim else ""

        if not time_dim or time_dim not in da.dims:
            # 1) name match
            for d in da.dims:
                if _TIME_RE.match(str(d)):
                    time_dim = str(d)
                    break
            # 2) coordinate values look like years or ISO dates
            if not time_dim or time_dim not in da.dims:
                for d in da.dims:
                    if hasattr(da, "coords") and d in da.coords:
                        vals = da.coords[d].values
                        if len(vals) > 1:
                            v = str(vals[0])
                            if (re.match(r'^\d{4}$', v) and 1900 <= int(v) <= 2100):
                                time_dim = str(d)
                                break
                            if re.match(r'^\d{4}-\d{2}', v):
                                time_dim = str(d)
                                break

        if not time_dim or time_dim not in da.dims:
            raise HTTPException(400, f"No time-like dimension found in dims: {list(da.dims)}")

        lat_arr, lon_arr, is_1d = _latlon_coords_from_da(da)
        if lat_arr is None:
            raise HTTPException(400, "No lat/lon coordinates found — "
                                      "timeseries-by-click only supports plain lat/lon grids.")

        if is_1d:
            row = int(np.argmin(np.abs(lat_arr - req.lat)))
            col = int(np.argmin(np.abs(lon_arr - req.lon)))
        else:
            d2 = (lat_arr - req.lat) ** 2 + (lon_arr - req.lon) ** 2
            flat = int(np.nanargmin(d2))
            row, col = (int(x) for x in np.unravel_index(flat, d2.shape))

        # Map row/col onto the actual lat/lon dim names
        dims = list(da.dims)
        sel = dict(req.extra_dims or {})
        for d in dims:
            if d == time_dim:
                continue
            if _is_lat_like_dim(d):
                sel[d] = row
            elif _is_lon_like_dim(d):
                sel[d] = col

        sel = {k: int(v) for k, v in sel.items() if k in dims}
        sliced = da.isel(**sel)

        with _dask.config.set(scheduler='synchronous'):
            arr = sliced.compute().values if hasattr(sliced, "compute") else sliced.values
        arr = np.asarray(arr, dtype=np.float64)

        attrs = getattr(da, "attrs", {})
        fill = attrs.get("_FillValue", attrs.get("missing_value", None))
        if fill is not None:
            try:
                arr = np.where(arr == float(fill), np.nan, arr)
            except Exception:
                pass
        scale  = attrs.get("scale_factor", None)
        offset = attrs.get("add_offset", None)
        if scale is not None:  arr = arr * float(scale)
        if offset is not None: arr = arr + float(offset)

        values = [None if not math.isfinite(v) else round(float(v), 4) for v in arr]

        labels = None
        if hasattr(da, "coords") and time_dim in da.coords:
            try:
                labels = [str(t) for t in da.coords[time_dim].values]
            except Exception:
                pass
        if labels is None:
            labels = [str(i) for i in range(len(values))]

        return {"labels": labels, "values": values, "units": attrs.get("units", "")}

    except HTTPException:
        raise
    except Exception:
        raise HTTPException(500, traceback.format_exc())

# Composites verified to work for FCI L1c full-disk files
KNOWN_GOOD_COMPOSITES = {
    "true_color":         "True Color",
    "natural_color":      "Natural Color",
    "airmass":            "Airmass",
    "dust":               "Dust (IR)",
    "fog":                "Fog",
    "ash":                "Ash (volcanic)",
    "cloud_phase":        "Cloud Phase",
    "night_microphysics": "Night Microphysics",
    "day_microphysics":   "Day Microphysics",
    "24h_microphysics":   "24h Microphysics",
    "cloud_type":         "Cloud Type",
    "cloud_top":          "Cloud Top",
    "day_severe_storms":  "Day Severe Storms",
    "convection":         "Convection",
    "snow":               "Snow",
    "fire_temperature":   "Fire Temperature",
    "overshooting_tops":  "Overshooting Tops",

}

@app.get("/api/composites")
def list_composites(filepath: str, reader: Optional[str] = None):
    try:
        scene = load_scene(filepath, reader)
        if hasattr(scene, "available_composite_names"):
            available = set(scene.available_composite_names())
            result = {k: v for k, v in KNOWN_GOOD_COMPOSITES.items() if k in available}
        else:
            result = dict(KNOWN_GOOD_COMPOSITES)
        return result
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(400, str(e))
    

@app.get("/api/render_rgb")
def render_rgb(
    filepath:  str,
    composite: str,
    reader:    Optional[str] = None,
    quality:   str           = "normal",
):
    try:
        if not SATPY_AVAILABLE:
            raise HTTPException(503, "satpy not available — RGB composites require satpy")
        max_px = 4096 if quality == "high" else 3072

        abs_path = str(resolve_filepath(filepath))
        rgb_key  = _make_geom_key(abs_path, f"__rgb__{composite}", quality, "{}")
        cached   = _RENDER_CACHE.get(rgb_key)
        if cached:
            png_bytes, bounds, _, _, shape = cached
            headers = {
                "X-Bounds":    ",".join(str(round(b, 4)) for b in bounds),
                "X-Composite": composite,
                "X-Shape":     f"{shape[0]}x{shape[1]}",
                "X-Cached":    "1",
                "X-Timestamp": _extract_timestamp_from_path(filepath),
                "Access-Control-Expose-Headers": "X-Bounds,X-Composite,X-Shape,X-Cached,X-Timestamp",
            }
            return StreamingResponse(io.BytesIO(png_bytes), media_type="image/png", headers=headers)

        if not _render_lock.acquire(blocking=False):
            raise HTTPException(
                409,
                "A render is already in progress. Stop it (⏹) or wait for it to finish "
                "before starting another."
            )

        try:
            _render_cancel.clear()

            name_guess = detect_reader_from_name(filepath)
            # BUG FIX (segfault root cause for true_color/RGB on non-FCI
            # files): this used to unconditionally fall back to
            # "fci_l1c_nc" whenever neither an explicit `reader` query
            # param nor filename-based detection (`name_guess`) found a
            # match. For a TROPOMI/S5P file (or any non-FCI file), that
            # forces satpy to parse it with the FCI L1c reader — a
            # format it was never designed for. Symptom: satpy prints
            # "No sensor name specified in HDF5 file" (it can't find the
            # FCI-specific metadata it's looking for) and then segfaults
            # in its native HDF5 parsing path. Passing ANY explicit
            # reader also bypasses load_scene()'s TROPOMI/UGRID fast
            # paths and its xarray fallback entirely, since those only
            # trigger when reader is None.
            #
            # Fix: only force "fci_l1c_nc" when there's a real signal
            # this IS an FCI file. Otherwise pass reader=None so
            # load_scene() can run its existing (correct) auto-detection
            # — including the TROPOMI fast path — exactly as the
            # single-band /api/render route already does.
            name_upper = Path(filepath).name.upper()
            looks_like_fci = (
                "_OPE_" in name_upper or "FCI" in name_upper
                or (name_guess and "fci" in str(name_guess).lower())
            )
            if reader:
                actual_reader = reader
            elif name_guess:
                actual_reader = name_guess
            elif looks_like_fci:
                actual_reader = "fci_l1c_nc"
            else:
                actual_reader = None  # let load_scene() auto-detect (TROPOMI, etc.)
            scene = load_scene(filepath, actual_reader)

            rgba, bounds = _rgb_scene_to_rgba_array(scene, composite, max_px=max_px)
            bounds = _sanitize_bounds(bounds)
            png_bytes = rgba_array_to_png_bytes(rgba)

            _RENDER_CACHE.put(rgb_key, (png_bytes, bounds, None, None, rgba.shape))

            headers = {
                "X-Bounds":    ",".join(str(round(b, 4)) for b in bounds),
                "X-Composite": composite,
                "X-Shape":     f"{rgba.shape[0]}x{rgba.shape[1]}",
                "X-Cached":    "0",
                "X-Timestamp": _extract_timestamp_from_path(filepath),
                "Access-Control-Expose-Headers": "X-Bounds,X-Composite,X-Shape,X-Cached,X-Timestamp",
            }
            return StreamingResponse(io.BytesIO(png_bytes), media_type="image/png", headers=headers)
        finally:
            _render_lock.release()
    except HTTPException:
        raise
    except Exception:
        raise HTTPException(500, f"RGB render failed:\n{traceback.format_exc()}")

# ── animation ─────────────────────────────────────────────────────────────────
class AnimationRequest(BaseModel):
    filepaths: List[str]
    dataset:   str
    reader:    Optional[str] = None
    colormap:  str           = "RdYlBu_r"
    vmin:      Optional[float] = None
    vmax:      Optional[float] = None


@app.post("/api/animation_info")
def animation_info(req: AnimationRequest):
    try:
        global_vmin = global_vmax = None
        global_bounds = None
        frame_info    = []
        for fp in req.filepaths:
            try:
                scene = load_scene(fp, req.reader)
                import dask as _dask
                with _dask.config.set(scheduler='synchronous'):
                    scene.load([req.dataset])
                if req.dataset not in scene:
                    frame_info.append({"filepath": fp, "error": "dataset not found"})
                    continue
                da    = scene[req.dataset]
                with _dask.config.set(scheduler='synchronous'):
                    arr = da_to_2d(da)
                valid = arr[~np.isnan(arr)]
                if valid.size:
                    fmin = float(np.percentile(valid, 2))
                    fmax = float(np.percentile(valid, 98))
                    global_vmin = fmin if global_vmin is None else min(global_vmin, fmin)
                    global_vmax = fmax if global_vmax is None else max(global_vmax, fmax)
                if global_bounds is None:
                    area   = da.attrs.get("area") if hasattr(da, "attrs") else None
                    if area is None:
                        area = getattr(da, "area", None)
                    raw_ds = scene._ds if isinstance(scene, _XarrayScene) else None
                    _, bounds, _, _ = _run_native(
                        render_array,
                        arr, area, "viridis", None, None, 512, da=da, raw_ds=raw_ds,
                    )
                    try:
                        global_bounds = _sanitize_bounds(bounds)
                    except Exception:
                        global_bounds = bounds
                frame_info.append({"filepath": fp, "ok": True})
            except Exception as e:
                frame_info.append({"filepath": fp, "error": str(e)})
        return {
            "frames":     len(req.filepaths),
            "vmin":       round(global_vmin, 4) if global_vmin is not None else None,
            "vmax":       round(global_vmax, 4) if global_vmax is not None else None,
            "bounds":     global_bounds,
            "frame_info": frame_info,
        }
    except Exception as e:
        raise HTTPException(500, str(e))


@app.get("/api/render_frame")
def render_frame(
    filepath: str,
    dataset:  str,
    reader:   Optional[str]   = None,
    colormap: str             = "RdYlBu_r",
    vmin:     Optional[float] = None,
    vmax:     Optional[float] = None,
):
    return render_dataset(
        filepath=filepath, dataset=dataset, reader=reader,
        colormap=colormap, vmin=vmin, vmax=vmax, quality="normal",
    )


# ── download ──────────────────────────────────────────────────────────────────
async def _run_download(job_id, collection_id, start, end, limit):
    download_jobs[job_id]["status"] = "running"
    try:
        token      = get_eumdac_token()
        datastore  = eumdac.DataStore(token)
        collection = datastore.get_collection(collection_id)
        start_dt   = datetime.fromisoformat(start).replace(tzinfo=timezone.utc)
        end_dt     = datetime.fromisoformat(end).replace(tzinfo=timezone.utc)
        products   = list(collection.search(dtstart=start_dt, dtend=end_dt))[:limit]
        download_jobs[job_id]["total"] = len(products)
        for i, product in enumerate(products):
            dest = DATA_DIR / str(product)
            if not dest.exists():
                with product.open() as fsrc, open(dest, "wb") as fdst:
                    while chunk := fsrc.read(1024 * 1024):
                        fdst.write(chunk)
            download_jobs[job_id]["done"] = i + 1
            download_jobs[job_id]["last"] = str(product)
        extract_eumetsat_zips()
        download_jobs[job_id]["status"] = "complete"
    except Exception as e:
        download_jobs[job_id]["status"] = "error"
        download_jobs[job_id]["error"]  = str(e)


@app.post("/api/download")
async def start_download(req: DownloadRequest, background_tasks: BackgroundTasks):
    if not EUMDAC_AVAILABLE:
        raise HTTPException(503, "eumdac not installed")
    job_id        = datetime.now().strftime("%Y%m%d%H%M%S%f")
    collection_id = COLLECTIONS.get(req.collection)
    if not collection_id:
        raise HTTPException(400, f"Unknown collection: {req.collection}")
    download_jobs[job_id] = {"status": "queued", "done": 0, "total": 0}
    background_tasks.add_task(
        _run_download, job_id, collection_id, req.start, req.end, req.limit
    )
    return {"job_id": job_id}


@app.post("/api/force_restart")
def force_restart(background_tasks: BackgroundTasks):
    _render_cancel.set()

    def _hardkill():
        import time, os, signal, subprocess, sys
        time.sleep(0.5)
        try:
            os.kill(os.getpid(), signal.SIGTERM)
        except Exception:
            pass
        time.sleep(1.0)
        # If still alive, relaunch via subprocess then SIGKILL self
        subprocess.Popen([sys.executable] + sys.argv,
                         close_fds=True,
                         start_new_session=True)
        os.kill(os.getpid(), signal.SIGKILL)

    background_tasks.add_task(_hardkill)
    return {"restarting": True}



@app.get("/api/render_status")
def render_status():
    """
    Non-blocking check: is a render currently running?
    Frontend uses this to disable the dataset list while rendering.
    """
    busy = not _render_lock.acquire(blocking=False)
    if not busy:
        _render_lock.release()
    return {"busy": busy}
 


@app.get("/api/download/{job_id}")
def download_status(job_id: str):
    job = download_jobs.get(job_id)
    if not job:
        raise HTTPException(404, "Job not found")
    return job


@app.get("/api/projection_support")
def projection_support():
    try:
        import maplibre
        version = getattr(maplibre, "__version__", "unknown")
    except ImportError:
        version = "not installed (frontend uses CDN)"
    return {"maplibre_version": version, "globe_projection": True}


@app.get("/api/debug_cgms")
def debug_cgms(filepath: str, dataset: str = "LST"):
    filenames = get_filenames_for_path(filepath)
    ds = xr.open_dataset(filenames[0], engine="netcdf4", mask_and_scale=True)
    da = ds[dataset]
    x_vals = ds.coords["x"].values
    y_vals = ds.coords["y"].values
    x_units = ds.coords["x"].attrs.get("units", "?")
    h_val = 42164160.0; r_eq = 6378137.0; r_pol = 6356752.3142
    xc = float(x_vals[len(x_vals)//2]); yc = float(y_vals[len(y_vals)//2])
    a = np.sin(xc)**2 + np.cos(xc)**2 * (np.cos(yc)**2 + (r_eq/r_pol)**2 * np.sin(yc)**2)
    b = -2.0 * h_val * np.cos(xc) * np.cos(yc)
    disc = b**2 - 4.0 * a * (h_val**2 - r_eq**2)
    rs = (-b - np.sqrt(disc)) / (2.0 * a)
    Sx = rs * np.cos(xc) * np.cos(yc); Sy = rs * np.sin(xc); Sz = rs * np.cos(xc) * np.sin(yc)
    lon_c = float(np.degrees(np.arctan2(Sy, h_val - Sx)))
    lat_c = float(np.degrees(np.arctan2((r_eq/r_pol)**2 * Sz, np.sqrt((h_val-Sx)**2 + Sy**2))))
    return {
        "x_shape": len(x_vals), "y_shape": len(y_vals), "x_units": x_units,
        "x_first": float(x_vals[0]), "x_last": float(x_vals[-1]),
        "y_first": float(y_vals[0]), "y_last": float(y_vals[-1]),
        "x_step": float(x_vals[1]-x_vals[0]), "dx_deg": float(abs(np.degrees(x_vals[1]-x_vals[0]))),
        "centre_pixel_lon": round(lon_c, 3), "centre_pixel_lat": round(lat_c, 3),
        "arr_shape": list(da.shape),
        "gm_attrs": {k: str(v) for k, v in ds[da.attrs["grid_mapping"]].attrs.items()},
    }



# ── Pre-warm _NATIVE_EXECUTOR: force netCDF4/HDF5 C-library init on the
# persistent native thread at startup, not on the first request.
# Without this, the first xr.open_dataset call from any endpoint hits the
# HDF5 global init from a cold thread → segfault.
def _warmup_native_libs():
    try:
        import netCDF4  # noqa: F401 — triggers HDF5 C-lib init
        import h5py     # noqa: F401 — triggers HDF5 C-lib init (h5py path)
        # Force actual HDF5 handle open/close cycle to complete library init
        import tempfile, os
        tmp = tempfile.mktemp(suffix=".nc")
        try:
            import numpy as np
            ds = netCDF4.Dataset(tmp, "w")
            ds.close()
            os.unlink(tmp)
        except Exception:
            pass
    except Exception:
        pass

_NATIVE_EXECUTOR.submit(_warmup_native_libs).result(timeout=15)

# ── serve frontend ────────────────────────────────────────────────────────────
frontend = Path(__file__).parent.parent / "frontend"
if frontend.exists():
    app.mount("/", StaticFiles(directory=str(frontend), html=True), name="frontend")