"""
rendering.py — colorization, single-band rendering, and RGB composite
pipeline for Xenia.

  • array_to_png_bytes / rgba_array_to_png_bytes — float32 array -> PNG
  • _compute_geometry / render_array — single-band dataset render path
  • RGB composite path: _reproject_rgb_bands, _render_rgb_bypass, _dust_manual,
    _rgb_scene_to_rgba_array, _warp_equirect_to_mercator_rgb,
    _bands_to_rgb_inputs, _apply_recipe_stretch, _rgb_bands_to_rgba
  • _COMPOSITE_RECIPES / _RECIPE_ALIASES / _RGB_CHANNEL_INPUTS — composite
    definitions (dust, true color, Night Microphysics/Fog, etc.)

Depends on geometry.py for the actual warp/reprojection math. Does NOT
depend on scenes.py — `scene` objects are accepted duck-typed (whatever
load_scene() in scenes.py returned) and never imported here.

"""

import io
import json
import math
import hashlib
import numpy as np
import PIL.Image
from typing import Optional
from fastapi import HTTPException

from state import _render_cancel, _GEOM_CACHE, _NEIGHBOUR_INFO_CACHE

from geometry import (
    reproject_to_wgs84,
    _reproject_cf_geostationary_cgms,
    _latlon_coords_from_da,
    _warp_equirect_to_mercator,
    _reproject_from_latlon_2d,
    _build_mercator_output,
)

__all__ = [
    "array_to_png_bytes",
    "_sanitize_bounds",
    "_compute_geometry",
    "render_array",
    "_reproject_rgb_bands",
    "_render_rgb_bypass",
    "_dust_manual",
    "_rgb_scene_to_rgba_array",
    "_warp_equirect_to_mercator_rgb",
    "_bands_to_rgb_inputs",
    "_get_recipe",
    "_apply_recipe_stretch",
    "_rgb_bands_to_rgba",
    "rgba_array_to_png_bytes",
    "_COMPOSITE_RECIPES",
    "_RECIPE_ALIASES",
    "_RGB_CHANNEL_INPUTS",
]

def array_to_png_bytes(arr: np.ndarray, colormap: str, vmin, vmax,
                       custom_colors: Optional[str] = None) -> bytes:
    """
    Convert float32 2-D array to RGBA PNG bytes.
    custom_colors: JSON string like '{"0":"#ff0000","0.5":"#00ff00","1":"#0000ff"}'
    """
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.colors as mcolors

    arr   = arr.astype(np.float64)
    valid = arr[~np.isnan(arr)]

    if vmin is None:
        vmin = float(np.percentile(valid, 2)) if valid.size else 0.0
    if vmax is None:
        vmax = float(np.percentile(valid, 98)) if valid.size else 1.0
    if abs(vmax - vmin) < 1e-10:
        vmax = vmin + 1.0

    norm = mcolors.Normalize(vmin=vmin, vmax=vmax, clip=True)

    if custom_colors:
        try:
            raw = json.loads(custom_colors)
            stops = sorted((float(k), v) for k, v in raw.items())
            cmap  = mcolors.LinearSegmentedColormap.from_list(
                "custom", [(pos, color) for pos, color in stops]
            )
        except Exception:
            cmap = matplotlib.colormaps.get(colormap, matplotlib.colormaps["viridis"])
    else:
        try:
            cmap = matplotlib.colormaps[colormap]
        except KeyError:
            cmap = matplotlib.colormaps["viridis"]

    rgba  = cmap(norm(arr))
    rgba[np.isnan(arr), 3] = 0.0
    rgba8 = (rgba * 255).clip(0, 255).astype(np.uint8)
    img   = PIL.Image.fromarray(rgba8, mode="RGBA")
    buf   = io.BytesIO()
    img.save(buf, format="PNG", optimize=False, compress_level=1)
    return buf.getvalue()


def _sanitize_bounds(bounds: list) -> list:
    w, s, e, n = bounds
    bad = {k: v for k, v in dict(W=w, S=s, E=e, N=n).items() if not math.isfinite(v)}
    if bad:
        raise HTTPException(
            500,
            f"Reprojection produced non-finite bounds {bad}. "
            "The file's projection info may be missing or all pixels are fill. "
            "Call /api/inspect?filepath=... to examine the file structure."
        )
    return [
        max(-180.0, min(180.0, w)),
        max( -90.0, min( 90.0, s)),
        max(-180.0, min(180.0, e)),
        max( -90.0, min( 90.0, n)),
    ]


# ── core geometry pipeline (result cached separately from colorization) ────────
def _compute_geometry(arr: np.ndarray, area, da=None, raw_ds=None,
                      max_px: int = 3072) -> tuple:
    """
    Returns (arr_wgs float32, bounds list).  This is the expensive part.
    Result is stored in _GEOM_CACHE.
    """


    if da is not None:
        lat, lon, is1d = _latlon_coords_from_da(da)

    if area is not None:
        try:
            arr_wgs, bounds = reproject_to_wgs84(arr, area, max_px=max_px)
            if not all(math.isfinite(v) for v in bounds):
                raise ValueError(f"non-finite bounds from satpy area: {bounds}")
            return arr_wgs, bounds
        except Exception:
            area = None

    if area is None:
        if da is not None:
            cgms_result = _reproject_cf_geostationary_cgms(arr, da, raw_ds=raw_ds, max_px=max_px)
            if cgms_result is not None:
                return cgms_result

        if arr.ndim == 1:

            # ── NEW: AMV / explicit lat-lon scatter ──────────────────────────────
            # Check if the file has geographic lat/lon coords (not geostationary x/y).
            # AMV products store lat/lon as int16 with scale_factor=0.01.
            if raw_ds is not None and (
                any(n in raw_ds for n in ("latitude", "lat")) and
                any(n in raw_ds for n in ("longitude", "lon"))
            ):
                lat_name = next(n for n in ("latitude", "lat") if n in raw_ds)
                lon_name = next(n for n in ("longitude", "lon") if n in raw_ds)

                def _decode_coord(var):
                    v  = raw_ds[var].values.astype(np.float64)
                    sf = float(np.asarray(raw_ds[var].attrs.get("scale_factor", 1.0)).flat[0])
                    fv = raw_ds[var].attrs.get("_FillValue", None)
                    if fv is not None:
                        v = np.where(v == float(np.asarray(fv).flat[0]), np.nan, v)
                    return v * sf

                lat_v = _decode_coord(lat_name)
                lon_v = _decode_coord(lon_name)

                # Decode data values (scale_factor on the variable itself)
                val_v = arr.astype(np.float64)
                if da is not None and da.name in raw_ds:
                    sf = float(np.asarray(raw_ds[da.name].attrs.get("scale_factor", 1.0)).flat[0])
                    fv = raw_ds[da.name].attrs.get("_FillValue", None)
                    if fv is not None:
                        val_v = np.where(val_v == float(np.asarray(fv).flat[0]), np.nan, val_v)
                    val_v = val_v * sf

                val_v = val_v.astype(np.float32)
                valid = np.isfinite(lat_v) & np.isfinite(lon_v) & np.isfinite(val_v)
                if not valid.any():
                    raise ValueError("AMV scatter: all points are fill/NaN after masking.")

                dx = 32.0 / 111.0  # AMV grid_distance is 32 km ≈ 0.288°
                arr_wgs, bounds = _build_mercator_output(
                    lat_v[valid], lon_v[valid], val_v[valid],
                    dx_deg=dx, dy_deg=dx, max_px=max_px,
                )
                return arr_wgs, bounds
            # ── END AMV branch ───────────────────────────────────────────────────


            # Sparse geostationary encoding (e.g. LI L2 flash_accumulation).
            # x/y are geostationary column/row angles (int16 with scale/offset).
            # Decode via mtg_geos_projection → lat/lon → scatter grid.
            if da is None:
                raise ValueError("1-D dataset with no DataArray context.")

            ds = raw_ds  # _XarrayScene._ds
            if ds is None:
                raise ValueError("1-D dataset: no raw_ds available for x/y lookup.")

            # --- decode x/y geostationary angles ---
            def _decode(var):
                v = ds[var].values.astype(np.float64)
                sf = float(ds[var].attrs.get("scale_factor", np.array(1.0)).flat[0])
                ao = float(ds[var].attrs.get("add_offset",   np.array(0.0)).flat[0])
                fv_raw = ds[var].attrs.get("_FillValue", None)
                if fv_raw is not None:
                    fv = float(np.asarray(fv_raw).flat[0])
                    v = np.where(v == fv, np.nan, v)
                return v * sf + ao  # radians

            if "x" not in ds or "y" not in ds:
                raise ValueError("1-D dataset: no x/y geostationary coordinates found.")

            x_rad = _decode("x")  # azimuth   (column) in radians
            y_rad = _decode("y")  # elevation (row)    in radians

            # --- geostationary → lat/lon (CGMS formula) ---
            gm = ds["mtg_geos_projection"] if "mtg_geos_projection" in ds else None
            if gm is None:
                # fallback defaults for MTG
                h   = 35786400.0 + 6378137.0  # perspective_point_height + semi_major
                r_eq = 6378137.0
                r_pol= 6356752.314
            else:
                pph  = float(np.asarray(gm.attrs.get("perspective_point_height", 35786400.0)).flat[0])
                r_eq = float(np.asarray(gm.attrs.get("semi_major_axis", 6378137.0)).flat[0])
                r_pol= float(np.asarray(gm.attrs.get("semi_minor_axis", 6356752.314)).flat[0])
                h    = pph + r_eq

            cos_x = np.cos(x_rad);  sin_x = np.sin(x_rad)
            cos_y = np.cos(y_rad);  sin_y = np.sin(y_rad)
            a = sin_x**2 + cos_x**2 * (cos_y**2 + (r_eq/r_pol)**2 * sin_y**2)
            b = -2.0 * h * cos_x * cos_y
            disc = b**2 - 4.0*a*(h**2 - r_eq**2)
            valid_disc = disc >= 0
            rs = np.where(valid_disc, (-b - np.sqrt(np.maximum(disc, 0))) / (2.0*a), np.nan)
            Sx = rs * cos_x * cos_y
            Sy = rs * sin_x
            Sz = rs * cos_x * sin_y
            lon_rad = np.arctan2(Sy, h - Sx)
            lat_rad = np.arctan2((r_eq/r_pol)**2 * Sz,
                                 np.sqrt((h - Sx)**2 + Sy**2))
            lat_deg = np.degrees(lat_rad)
            lon_deg = np.degrees(lon_rad)

            # --- decode flash_accumulation values ---
            val = arr.astype(np.float32)  # already scaled by da_to_2d / scene loader

            finite = (np.isfinite(lat_deg) & np.isfinite(lon_deg) &
                      np.isfinite(val) & valid_disc)
            lat_f = lat_deg[finite]; lon_f = lon_deg[finite]; val_f = val[finite]

            if lat_f.size == 0:
                raise ValueError("LI sparse dataset: no valid points after decoding.")

            # --- scatter onto 0.05° grid ---
            res = 0.05
            lat_min = float(np.floor(lat_f.min() / res) * res)
            lat_max = float(np.ceil (lat_f.max() / res) * res)
            lon_min = float(np.floor(lon_f.min() / res) * res)
            lon_max = float(np.ceil (lon_f.max() / res) * res)
            n_lat = max(1, int(round((lat_max - lat_min) / res)) + 1)
            n_lon = max(1, int(round((lon_max - lon_min) / res)) + 1)
            grid  = np.full((n_lat, n_lon), np.nan, dtype=np.float32)
            r_idx = np.clip(((lat_max - lat_f) / res).astype(int), 0, n_lat - 1)
            c_idx = np.clip(((lon_f - lon_min) / res).astype(int), 0, n_lon - 1)
            grid[r_idx, c_idx] = val_f

            bounds = [lon_min, lat_min, lon_max, lat_max]
            arr_wgs, bounds = _warp_equirect_to_mercator(grid, bounds, max_px=max_px)
            return arr_wgs, bounds


        lat_arr, lon_arr, is_1d = _latlon_coords_from_da(da)

        if lat_arr is not None and is_1d:
            lat_1d = lat_arr.copy(); lon_1d = lon_arr.copy(); arr_in = arr.copy()
            lon_sort_idx = np.argsort(lon_1d)
            lon_1d = lon_1d[lon_sort_idx]; arr_in = arr_in[:, lon_sort_idx]
            if len(lat_1d) > 1 and float(lat_1d[0]) < float(lat_1d[-1]):
                lat_1d = lat_1d[::-1]; arr_in = np.flipud(arr_in)
            arr_wgs = arr_in
            s = float(lat_1d[-1]); n = float(lat_1d[0])
            w = float(lon_1d[0]);  e = float(lon_1d[-1])
            bounds = [max(-180.0, w), max(-90.0, s), min(180.0, e), min(90.0, n)]
            # Regular 1-D lat/lon grid → rows are uniform in latitude,
            # so linear interpolation between adjacent rows removes the
            # small sub-pixel N/S snap from nearest-row lookup.
            arr_wgs, bounds = _warp_equirect_to_mercator(arr_wgs, bounds, max_px=max_px,
                                                          interpolate=True)
            return arr_wgs, bounds

        elif lat_arr is not None and not is_1d:
            arr_wgs, bounds = _reproject_from_latlon_2d(arr, lat_arr, lon_arr, max_px=max_px)

        else:
            arr_wgs = arr
            bounds  = [-180.0, -90.0, 180.0, 90.0]

        arr_wgs, bounds = _warp_equirect_to_mercator(arr_wgs, bounds, max_px=max_px)

    return arr_wgs, bounds

def render_array(arr: np.ndarray, area, colormap: str, vmin, vmax,
                 max_px: int = 3072, da=None, raw_ds=None,
                 geom_key: Optional[str] = None,
                 custom_colors: Optional[str] = None):
    """
    Full pipeline: 2D array → reproject → PNG bytes + bounds.
    Uses geometry cache if geom_key supplied.
    Returns (png_bytes, bounds, arr_shape, geom_key).
    """
    # Try geometry cache first
    cached_geom = _GEOM_CACHE.get(geom_key) if geom_key else None

    if cached_geom is not None:
        arr_wgs, bounds, _, _ = cached_geom
    else:
        arr_wgs, bounds = _compute_geometry(arr, area, da=da, raw_ds=raw_ds, max_px=max_px)
        valid = arr_wgs[~np.isnan(arr_wgs)]
        auto_vmin = float(np.percentile(valid, 2))  if valid.size else 0.0
        auto_vmax = float(np.percentile(valid, 98)) if valid.size else 1.0
        if geom_key:
            _GEOM_CACHE.put(geom_key, (arr_wgs, bounds, auto_vmin, auto_vmax))

    png = array_to_png_bytes(arr_wgs, colormap, vmin, vmax, custom_colors=custom_colors)
    return png, bounds, arr_wgs.shape, geom_key

def _reproject_rgb_bands(arr: np.ndarray, area, max_px: int = 3072) -> tuple:
    """
    Reproject HxWxC float32 from a satpy AreaDefinition to equirectangular WGS84.
    Uses _NEIGHBOUR_INFO_CACHE so repeated calls for the same file/quality are fast.
    Returns (arr_eq float32 HxWxC, bounds [w, s, e, n]).
    """
    from pyresample import geometry as prgeom
    from pyresample.kd_tree import get_neighbour_info, get_sample_from_neighbour_info
    import pyproj

    h_src, w_src = arr.shape[0], arr.shape[1]
    n_bands      = arr.shape[2]

    # Hard downsample cap — kd_tree cost is O(N log N); FCI full-disk is 11136².
    MAX_SRC = 2048
    if max(h_src, w_src) > MAX_SRC:
        scale   = MAX_SRC / max(h_src, w_src)
        new_h   = max(1, int(round(h_src * scale)))
        new_w   = max(1, int(round(w_src * scale)))
        row_idx = np.linspace(0, h_src - 1, new_h, dtype=int)
        col_idx = np.linspace(0, w_src - 1, new_w, dtype=int)
        arr     = arr[np.ix_(row_idx, col_idx)]
        h_src, w_src = new_h, new_w
        proj_id = getattr(area, "proj_id", getattr(area, "area_id", "native"))
        crs_val = getattr(area, "crs", getattr(area, "proj_dict",
                  getattr(area, "proj_str", None)))
        area = prgeom.AreaDefinition(
            area.area_id, area.description, proj_id, crs_val,
            new_w, new_h, area.area_extent,
        )

    # Geographic bounds via sampling
    left, bottom, right, top = area.area_extent
    src_crs = None
    for attr in ("crs", "proj_dict", "proj_str", "wkt"):
        val = getattr(area, attr, None)
        if val is not None:
            try:
                src_crs = pyproj.CRS(val)
                break
            except Exception:
                continue
    if src_crs is None:
        src_crs = pyproj.CRS("+proj=geos +lon_0=0 +h=35786023 +ellps=GRS80")

    transformer = pyproj.Transformer.from_crs(src_crs, "EPSG:4326", always_xy=True)
    sample_xs, sample_ys = [], []
    for frac in [i / 32.0 for i in range(33)]:
        x = left + frac * (right - left)
        y = bottom + frac * (top - bottom)
        sample_xs += [x, x, left, right]
        sample_ys += [bottom, top, y, y]
    raw_lons, raw_lats = transformer.transform(sample_xs, sample_ys)
    valid_pts = [
        (lo, la) for lo, la in zip(raw_lons, raw_lats)
        if math.isfinite(lo) and math.isfinite(la)
        and -180.0 <= lo <= 180.0 and -90.0 <= la <= 90.0
    ]
    if not valid_pts:
        w_b, e_b, s_b, n_b = -81.0, 81.0, -81.0, 81.0
    else:
        lons_v, lats_v = zip(*valid_pts)
        w_b = max(-180.0, min(lons_v)); e_b = min(180.0, max(lons_v))
        s_b = max(-90.0,  min(lats_v)); n_b = min(90.0,  max(lats_v))
    bounds = [w_b, s_b, e_b, n_b]

    aspect     = (e_b - w_b) / max(n_b - s_b, 1e-6)
    out_h      = h_src
    out_w      = max(1, int(round(out_h * aspect)))
    target_area = prgeom.AreaDefinition(
        "wgs84_rgb", "WGS84 longlat", "wgs84",
        {"proj": "longlat", "datum": "WGS84", "no_defs": True},
        out_w, out_h, [w_b, s_b, e_b, n_b],
    )

    px  = abs(right - left)  / max(w_src, 1)
    py  = abs(top   - bottom) / max(h_src, 1)
    roi = math.sqrt(px**2 + py**2) * 3.0

    # Neighbour info cache — keyed on geometry only, not on composite/colormap
    ni_key = hashlib.sha256(
        f"{area.area_id}|{out_w}|{out_h}|{roi:.2f}".encode()
    ).hexdigest()[:20]
    ni = _NEIGHBOUR_INFO_CACHE.get(ni_key)
    if ni is None:
        ni = get_neighbour_info(
            area, target_area,
            radius_of_influence=roi,
            neighbours=1, nprocs=1,
        )
        _NEIGHBOUR_INFO_CACHE.put(ni_key, ni)
    valid_input_index, valid_output_index, index_array, _ = ni

    if _render_cancel.is_set():
        raise HTTPException(499, "Render cancelled")

    out_bands = [
        get_sample_from_neighbour_info(
            'nn', target_area.shape,
            arr[:, :, b].astype(np.float32).ravel(),
            valid_input_index, valid_output_index, index_array,
            fill_value=np.nan,
        ).reshape(target_area.shape)
        for b in range(n_bands)
    ]
    return np.stack(out_bands, axis=-1).astype(np.float32), bounds





def _render_rgb_bypass(scene, composite: str, max_px: int = 3072) -> tuple:
    import dask.array as dsa

    channel_names = _RGB_CHANNEL_INPUTS.get(composite)
    if channel_names is None:
        raise ValueError(f"No bypass channel map for composite '{composite}'")

    scene.load(list(channel_names))

    def _get(name):
        da = scene[name]
        if hasattr(da, 'data') and isinstance(da.data, dsa.Array):
            return np.squeeze(da.data.compute(scheduler='synchronous').astype(np.float32))
        v = da.values if hasattr(da, "values") else np.asarray(da)
        if isinstance(v, np.ma.MaskedArray):
            v = v.filled(np.nan)
        return np.squeeze(v.astype(np.float32))

    bands = {name: _get(name) for name in channel_names}

    # ── NEW: align all bands to the largest shape ──────────────────────
    shapes = [b.shape for b in bands.values()]
    target_shape = max(shapes, key=lambda s: s[0] * s[1])
    aligned = {}
    for name, arr in bands.items():
        if arr.shape == target_shape:
            aligned[name] = arr
        else:
            # nearest-neighbour upsample via index repetition
            ry = target_shape[0] / arr.shape[0]
            rx = target_shape[1] / arr.shape[1]
            row_idx = np.clip(
                (np.arange(target_shape[0]) / ry).astype(int), 0, arr.shape[0] - 1)
            col_idx = np.clip(
                (np.arange(target_shape[1]) / rx).astype(int), 0, arr.shape[1] - 1)
            aligned[name] = arr[np.ix_(row_idx, col_idx)]
    bands = aligned
    # ──────────────────────────────────────────────────────────────────

    r_arr, g_arr, b_arr = _bands_to_rgb_inputs(composite, bands)
    arr = np.stack([r_arr, g_arr, b_arr], axis=-1)

    primary = next(iter(bands.values()))
    nan_mask = ~np.isfinite(primary) | (primary < 10)

    first_channel = channel_names[0]
    da   = scene[first_channel]
    area = da.attrs.get("area") if hasattr(da, "attrs") else getattr(da, "area", None)

    if area is None:
        rgba = _rgb_bands_to_rgba(arr, composite=composite)
        rgba[:, :, 3] = np.where(nan_mask, 0, 255).astype(np.uint8)
        return rgba, [-81.0, -81.0, 81.0, 81.0]

    out_arr, bounds = _reproject_rgb_bands(arr, area, max_px)
    out_arr, bounds = _warp_equirect_to_mercator_rgb(out_arr, bounds, max_px=max_px)
    rgba = _rgb_bands_to_rgba(out_arr, composite=composite)
    return rgba, bounds




def _dust_manual(scene, max_px=3072):
    """Kept for compatibility — routes through the unified bypass path."""
    return _render_rgb_bypass(scene, "dust", max_px)

def _reproject_rgb_bands(arr: np.ndarray, area, max_px: int = 3072) -> tuple:
    """
    Reproject an HxWxC float32 array from a satpy AreaDefinition to equirectangular WGS84.
    Uses cached neighbour info so repeated calls for the same file geometry are fast.
    Returns (arr_eq float32 HxWxC, bounds [w,s,e,n]).
    """
    from pyresample import geometry as prgeom
    from pyresample.kd_tree import get_neighbour_info, get_sample_from_neighbour_info
    import pyproj

    h_src, w_src = arr.shape[0], arr.shape[1]
    n_bands      = arr.shape[2]

    # ── hard downsample cap before the expensive kd_tree call ────────────────
    MAX_SRC = 2048
    if max(h_src, w_src) > MAX_SRC:
        scale   = MAX_SRC / max(h_src, w_src)
        new_h   = max(1, int(round(h_src * scale)))
        new_w   = max(1, int(round(w_src * scale)))
        row_idx = np.linspace(0, h_src - 1, new_h, dtype=int)
        col_idx = np.linspace(0, w_src - 1, new_w, dtype=int)
        arr     = arr[np.ix_(row_idx, col_idx)]
        h_src, w_src = new_h, new_w

        proj_id = getattr(area, "proj_id", getattr(area, "area_id", "native"))
        crs_val = getattr(area, "crs", getattr(area, "proj_dict",
                  getattr(area, "proj_str", None)))
        area = prgeom.AreaDefinition(
            area.area_id, area.description, proj_id, crs_val,
            new_w, new_h, area.area_extent,
        )

    # ── compute geographic bounds ─────────────────────────────────────────────
    left, bottom, right, top = area.area_extent
    src_crs = None
    for attr in ("crs", "proj_dict", "proj_str", "wkt"):
        val = getattr(area, attr, None)
        if val is not None:
            try:
                import pyproj as _pp
                src_crs = _pp.CRS(val)
                break
            except Exception:
                continue
    if src_crs is None:
        src_crs = pyproj.CRS("+proj=geos +lon_0=0 +h=35786023 +ellps=GRS80")

    transformer = pyproj.Transformer.from_crs(src_crs, "EPSG:4326", always_xy=True)
    sample_xs, sample_ys = [], []
    for frac in [i / 32.0 for i in range(33)]:
        x = left + frac * (right - left)
        y = bottom + frac * (top - bottom)
        sample_xs += [x, x, left, right]
        sample_ys += [bottom, top, y, y]
    raw_lons, raw_lats = transformer.transform(sample_xs, sample_ys)
    valid_pts = [
        (lo, la) for lo, la in zip(raw_lons, raw_lats)
        if math.isfinite(lo) and math.isfinite(la)
        and -180.0 <= lo <= 180.0 and -90.0 <= la <= 90.0
    ]
    if not valid_pts:
        w_b, e_b, s_b, n_b = -81.0, 81.0, -81.0, 81.0
    else:
        lons_v, lats_v = zip(*valid_pts)
        w_b = max(-180.0, min(lons_v)); e_b = min(180.0, max(lons_v))
        s_b = max(-90.0,  min(lats_v)); n_b = min(90.0,  max(lats_v))
    bounds = [w_b, s_b, e_b, n_b]

    # ── target area ───────────────────────────────────────────────────────────
    aspect  = (e_b - w_b) / max(n_b - s_b, 1e-6)
    out_h   = h_src
    out_w   = max(1, int(round(out_h * aspect)))
    target_area = prgeom.AreaDefinition(
        "wgs84_rgb", "WGS84 longlat", "wgs84",
        {"proj": "longlat", "datum": "WGS84", "no_defs": True},
        out_w, out_h, [w_b, s_b, e_b, n_b],
    )

    px  = abs(right - left)  / max(w_src, 1)
    py  = abs(top   - bottom) / max(h_src, 1)
    roi = math.sqrt(px**2 + py**2) * 3.0

    # ── neighbour info cache ──────────────────────────────────────────────────

    ni_key = hashlib.sha256(
        f"{area.area_id}|{h_src}x{w_src}|{out_w}x{out_h}|{roi:.2f}".encode()
    ).hexdigest()[:20]
    ni = _NEIGHBOUR_INFO_CACHE.get(ni_key)
    if ni is None:
        ni = get_neighbour_info(
            area, target_area,
            radius_of_influence=roi,
            neighbours=1, nprocs=1,
        )
        _NEIGHBOUR_INFO_CACHE.put(ni_key, ni)
    valid_input_index, valid_output_index, index_array, _ = ni

    # ── resample all bands ────────────────────────────────────────────────────
    if _render_cancel.is_set():
        raise HTTPException(499, "Render cancelled")

    expected_len = arr.shape[0] * arr.shape[1]
    if valid_input_index.shape[0] != expected_len:
        raise HTTPException(
            500,
            f"Neighbour-info/source size mismatch ({valid_input_index.shape[0]} "
            f"vs {expected_len}) — refusing to resample to avoid a native crash. "
            "This indicates a stale cache entry; please retry."
        )

    out_bands = [
        get_sample_from_neighbour_info(
            'nn', target_area.shape,
            arr[:, :, b].astype(np.float32).ravel(),
            valid_input_index, valid_output_index, index_array,
            fill_value=np.nan,
        ).reshape(target_area.shape)
        for b in range(n_bands)
    ]
    return np.stack(out_bands, axis=-1).astype(np.float32), bounds

def _rgb_scene_to_rgba_array(scene, composite: str, max_px: int = 3072) -> tuple:
    """
    Main entry point for all RGB composites.
    Uses bypass path (direct channel load + recipe) for all known composites.
    Falls back to satpy composite stack only for unknowns.
    """
    import dask.array as dsa

    if _render_cancel.is_set():
        raise HTTPException(499, "Render cancelled")

    # Fast path: known composite with a direct channel map
    if composite in _RGB_CHANNEL_INPUTS:
        return _render_rgb_bypass(scene, composite, max_px)

    # Slow path: ask satpy to compute the composite (true_color, cloud_top, etc.)
    scene.load([composite])
    if composite not in scene:
        available = (list(scene.available_composite_names())
                     if hasattr(scene, 'available_composite_names') else [])
        raise ValueError(
            f"Composite '{composite}' could not be loaded. "
            f"Available: {available[:10]}. "
            f"This composite may require solar angle data not present in this file."
        )

    if _render_cancel.is_set():
        raise HTTPException(499, "Render cancelled")

    da = scene[composite]
    try:
        if hasattr(da, 'data') and isinstance(da.data, dsa.Array):
            arr = da.data.compute(scheduler='synchronous')
        else:
            import dask
            with dask.config.set(scheduler='synchronous'):
                da  = da.compute()
            arr = da.values if hasattr(da, "values") else np.asarray(da)
    except Exception:
        arr = da.values if hasattr(da, "values") else np.asarray(da)

    if isinstance(arr, np.ma.MaskedArray):
        arr = arr.filled(np.nan)
    arr = arr.astype(np.float32)

    if arr.ndim == 2:
        arr = np.stack([arr, arr, arr], axis=0)
    if arr.ndim == 3 and arr.shape[0] in (3, 4):
        arr = np.moveaxis(arr, 0, -1)
    elif arr.ndim == 3 and arr.shape[2] in (3, 4):
        pass
    else:
        raise ValueError(f"Unexpected composite array shape: {arr.shape}")

    area = da.attrs.get("area") if hasattr(da, "attrs") else None
    if area is None:
        area = getattr(da, "area", None)

    if area is None:
        rgba = _rgb_bands_to_rgba(arr, composite=composite)
        return rgba, [-81.0, -81.0, 81.0, 81.0]

    if _render_cancel.is_set():
        raise HTTPException(499, "Render cancelled")

    out_arr, bounds = _reproject_rgb_bands(arr, area, max_px)
    out_arr, bounds = _warp_equirect_to_mercator_rgb(out_arr, bounds, max_px=max_px)
    rgba = _rgb_bands_to_rgba(out_arr, composite=composite)
    return rgba, bounds




def _warp_equirect_to_mercator_rgb(arr_eq: np.ndarray, bounds: list,
                                    max_px: int = 3072) -> tuple:
    """Single-pass mercator warp for HxWxC arrays — 3x faster than per-band loop."""
    w, s, e, n = bounds
    s_out = max(-85.0, s)
    n_out = min(85.0, n)

    def _lat_to_merc_y(lat_deg):
        lat_r = np.radians(np.clip(lat_deg, -85.05, 85.05))
        return np.log(np.tan(np.pi / 4.0 + lat_r / 2.0))

    def _merc_y_to_lat(y):
        return np.degrees(2.0 * np.arctan(np.exp(y)) - np.pi / 2.0)

    h_eq, w_eq = arr_eq.shape[0], arr_eq.shape[1]
    lats_eq = np.linspace(n, s, h_eq)

    merc_y_n      = _lat_to_merc_y(n_out)
    merc_y_s      = _lat_to_merc_y(s_out)
    merc_y_range  = merc_y_n - merc_y_s
    lon_range_rad = max(np.radians(e - w), 1e-6)
    out_nlat = max(2, min(max_px, int(round(w_eq * merc_y_range / lon_range_rad))))

    merc_ys  = np.linspace(merc_y_n, merc_y_s, out_nlat)
    out_lats = np.clip(_merc_y_to_lat(merc_ys), s_out, n_out)

    lats_eq_asc       = lats_eq[::-1]
    out_lats_clipped  = np.clip(out_lats, lats_eq[-1], lats_eq[0])
    idxs_asc          = np.searchsorted(lats_eq_asc, out_lats_clipped, side="left")
    idxs_asc          = np.clip(idxs_asc, 0, h_eq - 1)
    row_idxs          = (h_eq - 1) - idxs_asc

    # Index all bands at once — single numpy operation instead of 3 loops
    arr_merc = arr_eq[row_idxs, :, :]
    return arr_merc.astype(np.float32), [w, s_out, e, n_out]

# ══════════════════════════════════════════════════════════════════════════════
#  EUMETSAT FCI RGB RECIPES
# https://eumetrain.org/sites/default/files/2025-11/RGB_recipes.pdf
#  Format: [(min, max, gamma), ...] for R, G, B
#  If min > max, channel is inverted (linear stretch direction reversed).
#  gamma=1 means no gamma correction (linear only).
#  Source: EUMETSAT "Compilation of RGB Recipes" (METEOSAT/FCI section)
# ══════════════════════════════════════════════════════════════════════════════
_COMPOSITE_RECIPES = {
    # Airmass: WV6.3-WV7.3, IR9.7-IR10.5, WV6.3 (inverted)
    "airmass": [
        (-23.8, 1.4, 1.0),
        (-39.7, 4.1, 1.0),
        (244.5, 209.4, 1.0),
    ],

    # 24h Microphysics (cloud): IR12.3-IR10.5, IR10.5-IR8.7 (gamma 1.2), IR10.5
    "24h_microphysics": [
        (-7.1, 2.4, 1.0),
        (0.2, 5.2, 1.2),
        (247.8, 303.1, 1.0),
    ],

    # Night Microphysics (mid-latitude tuning, default)
    "night_microphysics": [
        (-4.0, 2.0, 1.0),
        (-4.0, 6.0, 1.0),
        (243.0, 293.0, 1.0),
    ],
    # Tropical variant
    "night_microphysics_tropical": [
        (-7.1, 2.4, 1.0),
        (-2.9, 1.1, 1.0),
        (273.0, 300.0, 1.0),
    ],

    # Day Cloud Phase: NIR1.6, NIR2.2, VIS0.6 — all reflectance %, /100 -> 0-1
    "cloud_phase": [
        (0.0, 50.0, 1.0),
        (0.0, 50.0, 1.0),
        (0.0, 100.0, 1.0),
    ],
    "cloud_phase_distinction": [
        (0.0, 50.0, 1.0),
        (0.0, 50.0, 1.0),
        (0.0, 100.0, 1.0),
    ],

    # Day Microphysics: VIS0.8, IR3.8refl (gamma 2.5), IR10.5
    "day_microphysics": [
        (0.0, 100.0, 1.0),
        (0.0, 60.0, 2.5),
        (203.0, 323.0, 1.0),
    ],

    # Day Cloud Type / cimss_cloud_type: NIR1.3 (gamma 1.5), VIS0.6 (gamma 0.75), NIR1.6
    "cimss_cloud_type": [
        (0.0, 10.0, 1.5),
        (0.0, 80.0, 0.75),
        (0.0, 80.0, 1.0),
    ],
    "cloud_type": [
        (0.0, 10.0, 1.5),
        (0.0, 80.0, 0.75),
        (0.0, 80.0, 1.0),
    ],

    # Day Severe Storms / Convection (mid-latitude): WV6.3-WV7.3, IR3.8-IR10.5 (gamma 0.5), NIR1.6-VIS0.6
    "convection": [
        (-30.0, 0.0, 1.0),
        (0.0, 55.0, 0.5),
        (-70.0, 20.0, 1.0),
    ],
    "day_severe_storms": [
        (-30.0, 0.0, 1.0),
        (0.0, 55.0, 0.5),
        (-70.0, 20.0, 1.0),
    ],
    # Tropical Severe Storms variant
    "day_severe_storms_tropical": [
        (-35.0, 5.0, 1.0),
        (-5.0, 75.0, 0.33),
        (-75.0, 25.0, 1.0),
    ],

    # Overshooting Tops: WV6.3-IR10.5, IR9.7-IR10.5, WV6.3 (inverted)
    "overshooting_tops": [
        (-50, 5, 1.0),
        (-30, 25, 0.5),
        (243, 193, 1.0),
    ],

    # 24h Microphysics Dust: IR12.3-IR10.5, IR10.5-IR8.7 (gamma 2.5), IR10.5
    "dust": [
        (-7.1, 2.4, 1.0),
        (0.2, 12.7, 2.5),
        (260.9, 289.0, 1.0),
    ],

    # 24h Microphysics Ash: IR12.3-IR10.5, IR10.5-IR8.7, IR10.5
    "ash": [
        (-7.1, 2.4, 1.0),
        (-3.2, 4.4, 1.0),
        (242.8, 303.1, 1.0),
    ],

    # Fire Temperature: IR3.8 (gamma 0.4), NIR2.2, NIR1.6
    "fire_temperature": [
        (273.0, 333.0, 0.4),
        (0.0, 100.0, 1.0),
        (0.0, 75.0, 1.0),
    ],

    # Day Fire (Natural Fire Color): IR3.8 (gamma 0.4), VIS0.8, VIS0.6
    "day_severe_storms_fire": [
        (273.0, 333.0, 0.4),
        (0.0, 100.0, 1.0),
        (0.0, 100.0, 1.0),
    ],

    # Natural Color: NIR1.6, VIS0.8, VIS0.6 — all 0-100%
    "natural_color": [
        (0.0, 100.0, 1.0),
        (0.0, 100.0, 1.0),
        (0.0, 100.0, 1.0),
    ],

    # Fog: same channel triad as Ash/Dust family — IR12.3-IR10.5, IR10.5-IR8.7, IR10.5
    # NOTE: PDF does not list a standalone "Fog" recipe for FCI; SEVIRI fog tables
    # are not in this document either. Using dust-family ranges as placeholder —
    # verify against actual rendered output.
    "fog": [
        (-4.0, 2.0, 1.0),
        (0.0, 6.0, 1.0),
        (243.0, 283.0, 1.0),
    ],

    # Snow RGB: VIS0.8 (0-100%, g=1.7), NIR1.6 (0-70%, g=1.7), IR3.8refl (0-30%, g=1.7)
    "snow": [
        (0.0, 100.0, 1.7),
        (0.0,  70.0, 1.7),
        (0.0,  30.0, 1.7),
    ],

    "true_color": [
        (0.0, 0.0, 0.0),
        (0.0, 0.0, 0.0),
        (0.0, 0.0, 0.0),
    ],

}

# Aliases / variants that should reuse another recipe's parameters
_RECIPE_ALIASES = {
    "cloud_phase_raw":              "cloud_phase",
    "cloud_phase_distinction_raw":  "cloud_phase_distinction",
    "cimss_cloud_type_raw":         "cimss_cloud_type",
    "cloud_type_with_night_ir105":  "cloud_type",
    "cloud_phase_with_night_ir105": "cloud_phase",
    "natural_color_raw":            "natural_color",
    "night_microphysics_tropical":  "night_microphysics_tropical",
    "day_severe_storms_tropical":   "day_severe_storms_tropical",
    "ash":                          "ash",
}

# Maps each composite name to the raw FCI channel names to load directly,
# bypassing satpy's composite stack entirely.
# Tuple order = (Red_input, Green_input, Blue_input).
# Where a channel is reused (e.g. IR10.5 appears in R and B), list it once —
# scene.load() deduplicates automatically.
_RGB_CHANNEL_INPUTS = {
    # IR-difference composites — all inputs are brightness temperatures (K)
    "dust":               ("ir_87", "ir_105", "ir_123"),
    "ash":                ("ir_87", "ir_105", "ir_123"),
    "fog":                ("ir_87", "ir_105", "ir_123"),
    "night_microphysics": ("ir_87", "ir_105", "ir_123"),
    "24h_microphysics":   ("ir_87", "ir_105", "ir_123"),

    # WV-difference + IR composites — inputs are BT (K)
    "airmass":            ("wv_63", "wv_73", "ir_97", "ir_105"),
    "overshooting_tops":  ("wv_63", "ir_97", "ir_105"),

    # Daytime visible/NIR composites — inputs are reflectance (0–100 %)
    "natural_color":      ("nir_16",  "vis_08", "vis_06"),
    "cloud_phase":        ("nir_16",  "nir_22", "vis_06"),
    "cloud_phase_distinction": ("nir_16", "nir_22", "vis_06"),
    "day_microphysics":   ("vis_08",  "nir_16",  "ir_105"),
    "cloud_type":         ("nir_13",  "vis_06",  "nir_16"),
    "day_severe_storms": ("wv_63", "wv_73", "ir_38", "ir_105", "nir_16", "vis_06"),
    "convection":        ("wv_63", "wv_73", "ir_38", "ir_105", "nir_16", "vis_06"),
    "fire_temperature":       ("ir_38", "nir_22", "nir_16"),
    # Snow RGB: VIS0.8, NIR1.6, IR3.8 — satpy cannot compute without SZA, bypass.
    "snow":                   ("vis_08", "nir_16", "ir_38"),
    # EUMETSAT True Colour channels. Bypasses satpy (needs SZA+Rayleigh).
    "true_color":         ("vis_08","vis_06", "vis_05", "vis_04"),

}

# Maps composite → function that takes loaded band arrays and returns (R, G, B)
# arrays in the correct physical units for _COMPOSITE_RECIPES to stretch.
# Each function receives a dict {channel_name: np.ndarray (float32, already calibrated)}.
def _bands_to_rgb_inputs(composite: str, bands: dict) -> tuple:
    """
    Return (R, G, B) arrays in the physical units expected by _COMPOSITE_RECIPES.
    IR channels arrive in Kelvin. VIS/NIR channels arrive in reflectance (0-100%).
    Difference composites must be computed here before the recipe stretch.
    """
    c = composite

    # ── IR-difference family ──────────────────────────────────────────────────
    if c in ("dust", "ash", "24h_microphysics"):
        ir087 = bands["ir_87"]; ir105 = bands["ir_105"]; ir123 = bands["ir_123"]
        return (ir123 - ir105,   # R: BT diff
                ir105 - ir087,   # G: BT diff
                ir105)           # B: raw BT

    if c in ("fog", "night_microphysics"):
        ir087 = bands["ir_87"]; ir105 = bands["ir_105"]; ir123 = bands["ir_123"]
        return (ir123 - ir105,
                ir105 - ir087,
                ir105)

    # ── WV/IR family ──────────────────────────────────────────────────────────
    if c == "airmass":
        wv063 = bands["wv_63"]; wv073 = bands["wv_73"]
        ir097 = bands["ir_97"]; ir105 = bands["ir_105"]
        return (wv063 - wv073,   # R: WV diff
                ir097 - ir105,   # G: IR diff
                wv063)           # B: raw WV BT (recipe inverts via lo>hi)

    if c == "overshooting_tops":
        wv063 = bands["wv_63"]; ir097 = bands["ir_97"]; ir105 = bands["ir_105"]
        return (wv063 - ir105,
                ir097 - ir105,
                wv063)

    # ── Daytime visible/NIR family ────────────────────────────────────────────
    if c == "natural_color":
        return (bands["nir_16"], bands["vis_08"], bands["vis_06"])

    if c in ("cloud_phase", "cloud_phase_distinction"):
        return (bands["nir_16"], bands["nir_22"], bands["vis_06"])

    if c == "day_microphysics":
        # Green channel is IR3.8 reflectance component — recipe expects 0-60% range
        return (bands["vis_08"], bands["nir_16"], bands["ir_105"])

    if c == "cloud_type":
        return (bands["nir_13"], bands["vis_06"], bands["nir_16"])



    if c == "true_color":
        # Normalize 0-110% → [0,1]
        GAMMA = 2.3

        def _tc(ch):
            x = np.clip(ch / 110.0, 0.0, 1.0)
            return np.power(x, 1.0 / GAMMA).astype(np.float32)

        R = _tc(bands["vis_06"])
        B = _tc(bands["vis_04"])
        F = 0.15
        G_hybrid = (1.0 - F) * np.clip(bands["vis_05"] / 110.0, 0.0, 1.0) \
                + F         * np.clip(bands["vis_08"] / 110.0, 0.0, 1.0)
        G = np.power(G_hybrid, 1.0 / GAMMA).astype(np.float32)

        # Sigmoid contrast — steepness k controls contrast, pivot at 0.5
        def _sigmoid(x, k=8.0):
            return (1.0 / (1.0 + np.exp(-k * (x - 0.5)))).astype(np.float32)

        R = _sigmoid(R)
        G = _sigmoid(G)
        B = _sigmoid(B)

        return (R, G, B)


    if c == "snow":
        # Blue = IR3.8 solar reflectance proxy: linear map 270K->0%, 330K->30%
        _ir38_refl = np.clip((bands["ir_38"] - 270.0) * 0.5, 0.0, 30.0)
        return (bands["vis_08"], bands["nir_16"], _ir38_refl)

    if c == "fire_temperature":
        return (bands["ir_38"], bands["nir_22"], bands["nir_16"])

    if c in ("day_severe_storms", "convection"):
        return (
            bands["wv_63"] - bands["wv_73"],          # R
            bands["ir_38"] - bands["ir_105"],          # G
            bands["nir_16"] - bands.get("vis_06", 0),  # B
        )
    # Fallback — return whatever was loaded in order
    vals = list(bands.values())
    return (vals[0], vals[1] if len(vals) > 1 else vals[0],
            vals[2] if len(vals) > 2 else vals[0])


def _get_recipe(composite: str):
    if composite in _COMPOSITE_RECIPES:
        return _COMPOSITE_RECIPES[composite]
    if composite in _RECIPE_ALIASES:
        return _COMPOSITE_RECIPES.get(_RECIPE_ALIASES[composite])
    return None

def _apply_recipe_stretch(arr: np.ndarray, recipe: list, reflectance_is_fraction: bool = False) -> np.ndarray:
    out = np.empty_like(arr)
    for i, (lo, hi, gamma) in enumerate(recipe):
        ch = arr[:, :, i]
        scale_lo, scale_hi = lo, hi
        # If recipe range looks like a percentage (>1) but data is 0-1 fraction, rescale
        if reflectance_is_fraction and max(abs(lo), abs(hi)) > 1.5:
            scale_lo, scale_hi = lo / 100.0, hi / 100.0
        if scale_lo > scale_hi:
            frac = np.clip((scale_lo - ch) / (scale_lo - scale_hi), 0.0, 1.0)
        else:
            frac = np.clip((ch - scale_lo) / (scale_hi - scale_lo), 0.0, 1.0)
        if gamma != 1.0:
            frac = np.power(frac, 1.0 / gamma)
        out[:, :, i] = frac
    return out




def _rgb_bands_to_rgba(arr: np.ndarray, composite: str = "") -> np.ndarray:
    h, w    = arr.shape[0], arr.shape[1]
    nan_mask = np.isnan(arr[:, :, 0]) | np.isnan(arr[:, :, 1]) | np.isnan(arr[:, :, 2])
    arr = np.nan_to_num(arr, nan=0.0)

    recipe = _get_recipe(composite)
    # gamma=0.0 is a sentinel: band handler pre-built the 0-1 output (e.g. true_color
    # piecewise stretch) — skip ALL further stretching, just clip and use as-is.
    _recipe_prebuilt = recipe is not None and all(g == 0.0 for _, _, g in recipe)
    if _recipe_prebuilt:
        arr = np.clip(arr, 0.0, 1.0)
    elif recipe is not None:
        arr = _apply_recipe_stretch(arr, recipe)
    else:
        # Fallback: generic percentile auto-stretch for unknown composites
        max_val = float(np.nanmax(arr)) if arr.size else 1.0
        if max_val > 1.5:
            arr = arr / 255.0
        for i in range(min(3, arr.shape[2])):
            ch = arr[:, :, i]
            lo = np.percentile(ch[ch > 0], 2) if (ch > 0).any() else 0.0
            hi = np.percentile(ch[ch > 0], 98) if (ch > 0).any() else 1.0
            if hi > lo:
                arr[:, :, i] = np.clip((ch - lo) / (hi - lo), 0.0, 1.0)
        arr = np.clip(arr ** 0.7, 0, 1)

    rgba = np.zeros((h, w, 4), dtype=np.uint8)
    rgba[:, :, 0] = (arr[:, :, 0] * 255).astype(np.uint8)
    rgba[:, :, 1] = (arr[:, :, 1] * 255).astype(np.uint8)
    rgba[:, :, 2] = (arr[:, :, 2] * 255).astype(np.uint8)
    rgba[:, :, 3] = np.where(nan_mask, 0, 255).astype(np.uint8)
    return rgba

def rgba_array_to_png_bytes(rgba: np.ndarray) -> bytes:
    img = PIL.Image.fromarray(rgba, mode="RGBA")
    buf = io.BytesIO()
    img.save(buf, format="PNG", optimize=False, compress_level=1)
    return buf.getvalue()