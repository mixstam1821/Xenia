"""
geometry.py — pure reprojection / coordinate math for Xenia.

No FastAPI, no caching, no scene loading here —
just array-in/array-out geometry: GEOS/CGMS -> lat/lon decoding, area-def
construction, and warping (geostationary, generic lat/lon) to WGS84 /
Mercator pixel grids.

Depends only on numpy + lazy-imported pyproj/scipy/pyresample (imported
inline inside functions, same as before the split).
"""

import math
import numpy as np
from typing import Optional
from fastapi import HTTPException

from state import _render_cancel

__all__ = [
    "_decode_geos_coord",
    "_get_gm_attrs",
    "_cgms_xy_to_latlon",
    "_build_mercator_output",
    "_reproject_cf_geostationary_cgms",
    "_reproject_cgms_grid",
    "_reproject_cgms_sparse",
    "_area_def_from_cf_geostationary",
    "_is_lat_like_dim",
    "_is_lon_like_dim",
    "_spatial_axes",
    "da_to_2d",
    "_warp_equirect_to_mercator",
    "reproject_to_wgs84",
    "_latlon_coords_from_da",
    "_reproject_from_latlon_2d",
    "_unwrap_longitudes",
]


def _unwrap_longitudes(lon_v: np.ndarray) -> np.ndarray:
    """
    If longitudes straddle the antimeridian (both near -180 and +180
    present), shift the negative branch by +360 so the array becomes
    continuous. Returns a NEW array; bounds computed from this array
    may exceed 180 and must be wrapped back for the final bounds.
    """
    lon_v = lon_v.copy()
    has_neg_near = np.any(lon_v < -150.0)
    has_pos_near = np.any(lon_v >  150.0)
    if has_neg_near and has_pos_near:
        # crosses the seam — shift negative side into 180..360 range
        lon_v = np.where(lon_v < 0, lon_v + 360.0, lon_v)
    return lon_v


def _decode_geos_coord(coord_da) -> np.ndarray:
    vals  = np.asarray(coord_da.values, dtype=np.float64)
    attrs = getattr(coord_da, "attrs", {})
    if vals.dtype.kind == "f" and np.nanmax(np.abs(vals)) < 1.0:
        return vals
    scale  = attrs.get("scale_factor", None)
    offset = attrs.get("add_offset",   None)
    if scale is not None:
        vals = vals * float(scale)
    if offset is not None:
        vals = vals + float(offset)
    units = str(attrs.get("units", "radian")).lower()
    if "micro" in units:
        vals = vals * 1e-6
    return vals


def _get_gm_attrs(da, raw_ds) -> dict:
    attrs   = getattr(da, "attrs", {})
    gm_name = attrs.get("grid_mapping")
    if not gm_name:
        coord_str = attrs.get("coordinate", "")
        if "mtg_geos" in coord_str.lower() or "geos" in coord_str.lower():
            if raw_ds is not None:
                for vname, vda in raw_ds.data_vars.items():
                    if getattr(vda, "attrs", {}).get("grid_mapping_name") == "geostationary":
                        return dict(vda.attrs)
        return {}
    for src in filter(None, [raw_ds, getattr(da, "coords", None)]):
        try:
            if hasattr(src, "__getitem__") and gm_name in src:
                gm_attrs = dict(getattr(src[gm_name], "attrs", {}))
                if gm_attrs:
                    return gm_attrs
        except Exception:
            continue
    return {}


def _cgms_xy_to_latlon(x_rad: np.ndarray, y_rad: np.ndarray,
                        h: float, r_eq: float, r_pol: float,
                        lon_0: float) -> tuple:
    a    = (np.sin(x_rad)**2
            + np.cos(x_rad)**2 * (np.cos(y_rad)**2
                                  + (r_eq / r_pol)**2 * np.sin(y_rad)**2))
    b    = -2.0 * h * np.cos(x_rad) * np.cos(y_rad)
    disc = b**2 - 4.0 * a * (h**2 - r_eq**2)
    on_disk   = disc >= 0.0
    safe_disc = np.where(on_disk, disc, 0.0)
    rs  = np.where(on_disk, (-b - np.sqrt(safe_disc)) / (2.0 * a), np.nan)
    Sx  = rs * np.cos(x_rad) * np.cos(y_rad)
    Sy  = rs * np.sin(x_rad)
    Sz  = rs * np.cos(x_rad) * np.sin(y_rad)
    lon = np.where(
        on_disk,
        np.degrees(np.arctan2(Sy, h - Sx)) + lon_0,
        np.nan,
    ).astype(np.float32)
    lat = np.where(
        on_disk,
        np.degrees(np.arctan2(
            (r_eq / r_pol)**2 * Sz,
            np.sqrt((h - Sx)**2 + Sy**2),
        )),
        np.nan,
    ).astype(np.float32)
    return lon, lat, on_disk


def _build_mercator_output(lat_v, lon_v, val_v, dx_deg, dy_deg, max_px) -> tuple:
    import math as _math
    from scipy.spatial import cKDTree

    if _render_cancel.is_set():
        raise HTTPException(499, "Render cancelled")


    lon_v = _unwrap_longitudes(lon_v)

    s = float(np.nanmin(lat_v));  n = float(np.nanmax(lat_v))
    w = float(np.nanmin(lon_v));  e = float(np.nanmax(lon_v))
    # w = max(-180.0, w);  e = min(180.0, e)
    s = max( -85.0, s);  n = min( 85.0, n)

    def _lat_to_merc_y(lat_deg):
        lat_r = np.radians(np.clip(lat_deg, -85.05, 85.05))
        return np.log(np.tan(np.pi / 4.0 + lat_r / 2.0))

    def _merc_y_to_lat(y):
        return np.degrees(2.0 * np.arctan(np.exp(y)) - np.pi / 2.0)

    merc_y_n = _lat_to_merc_y(n)
    merc_y_s = _lat_to_merc_y(s)
    out_nlon = max(2, min(max_px, int(round((e - w) / dx_deg))))
    merc_y_range  = merc_y_n - merc_y_s
    lon_range_rad = np.radians(e - w)
    out_nlat = max(2, min(max_px, int(round(out_nlon * merc_y_range / lon_range_rad))))

    merc_ys     = np.linspace(merc_y_n, merc_y_s, out_nlat)
    out_lons    = np.linspace(w, e, out_nlon)
    out_lats_1d = _merc_y_to_lat(merc_ys)
    out_lon2d, out_lat2d = np.meshgrid(out_lons, out_lats_1d)

    def _xyz(la, lo):
        la_r = np.radians(la);  lo_r = np.radians(lo)
        return np.column_stack([
            np.cos(la_r) * np.cos(lo_r),
            np.cos(la_r) * np.sin(lo_r),
            np.sin(la_r),
        ])

    tree    = cKDTree(_xyz(lat_v, lon_v))
    if _render_cancel.is_set():
        raise HTTPException(499, "Render cancelled")
    tgt_xyz = _xyz(out_lat2d.ravel(), out_lon2d.ravel())
    diag_deg     = _math.sqrt(dx_deg**2 + dy_deg**2)
    chord_radius = 2.0 * _math.sin(_math.radians(diag_deg * 4.0) / 2.0)
    _, idxs  = tree.query(tgt_xyz, k=1, distance_upper_bound=chord_radius)

    if _render_cancel.is_set():
        raise HTTPException(499, "Render cancelled")
    out_flat = np.full(out_nlat * out_nlon, np.nan, dtype=np.float32)
    hit = idxs < len(val_v)
    out_flat[hit] = val_v[idxs[hit]]
    return out_flat.reshape(out_nlat, out_nlon), [w, s, e, n]


def _reproject_cf_geostationary_cgms(arr: np.ndarray, da, raw_ds=None,
                                      max_px: int = 3072) -> tuple:
    import math as _math
    gm_attrs = _get_gm_attrs(da, raw_ds)
    if not gm_attrs or gm_attrs.get("grid_mapping_name") != "geostationary":
        return None
    h_val = float(gm_attrs.get("perspective_point_height", 35786400.0))
    r_eq  = float(gm_attrs.get("semi_major_axis",          6378137.0))
    r_pol = float(gm_attrs.get("semi_minor_or_axis",
                  gm_attrs.get("semi_minor_axis",          6356752.3142)))
    lon_0 = float(gm_attrs.get("longitude_of_projection_origin", 0.0))
    h = h_val + r_eq
    coords = getattr(da, "coords", {})
    if raw_ds is not None and ("x" not in coords or "y" not in coords):
        coords = raw_ds.coords
    if "x" not in coords or "y" not in coords:
        return None
    x_vals = _decode_geos_coord(coords["x"])
    y_vals = _decode_geos_coord(coords["y"])
    arr_squeezed = np.squeeze(arr)
    is_sparse = (arr_squeezed.ndim == 1 or
                 (x_vals.ndim == 1 and y_vals.ndim == 1 and
                  len(x_vals) == len(y_vals) and
                  len(x_vals) != arr_squeezed.shape[-1]))
    if is_sparse:
        return _reproject_cgms_sparse(arr_squeezed, x_vals, y_vals,
                                       h, r_eq, r_pol, lon_0, max_px)
    else:
        return _reproject_cgms_grid(arr_squeezed, x_vals, y_vals,
                                     h, r_eq, r_pol, lon_0, max_px)


def _reproject_cgms_grid(arr, x_vals, y_vals, h, r_eq, r_pol, lon_0, max_px):
    import math as _math
    ny_src, nx_src = arr.shape
    step = max(1, int(_math.ceil(max(ny_src, nx_src) / max_px)))
    if step > 1:
        x_vals = x_vals[::step]
        y_vals = y_vals[::step]
        arr    = arr[::step, ::step]
    ny, nx = arr.shape
    X, Y   = np.meshgrid(x_vals, y_vals)
    lon, lat, on_disk = _cgms_xy_to_latlon(X, Y, h, r_eq, r_pol, lon_0)
    valid = on_disk & np.isfinite(arr)
    if not valid.any():
        return None
    lat_v = lat[valid].astype(np.float64)
    lon_v = lon[valid].astype(np.float64)
    val_v = arr[valid].astype(np.float32)
    dx_deg = abs(np.degrees(x_vals[1] - x_vals[0])) if nx > 1 else 0.01
    dy_deg = abs(np.degrees(y_vals[0] - y_vals[1])) if ny > 1 else 0.01
    return _build_mercator_output(lat_v, lon_v, val_v, dx_deg, dy_deg, max_px)


def _reproject_cgms_sparse(arr_1d, x_vals, y_vals, h, r_eq, r_pol, lon_0, max_px):
    import math as _math
    n_px = len(x_vals)
    step = max(1, int(_math.ceil(n_px / (max_px * max_px))))
    if step > 1:
        x_vals = x_vals[::step]
        y_vals = y_vals[::step]
        arr_1d = arr_1d[::step] if arr_1d.ndim == 1 else arr_1d.ravel()[::step]
    valid_mask = np.isfinite(arr_1d)
    if not valid_mask.any():
        return None
    lon_px, lat_px, on_disk = _cgms_xy_to_latlon(x_vals, y_vals, h, r_eq, r_pol, lon_0)
    keep = on_disk & valid_mask & np.isfinite(lon_px) & np.isfinite(lat_px)
    if not keep.any():
        return None
    lat_v = lat_px[keep].astype(np.float64)
    lon_v = lon_px[keep].astype(np.float64)
    val_v = arr_1d[keep].astype(np.float32)
    dx_deg = abs(np.degrees(x_vals[1] - x_vals[0])) if len(x_vals) > 1 else 0.0032
    dy_deg = dx_deg
    return _build_mercator_output(lat_v, lon_v, val_v, dx_deg, dy_deg, max_px)


def _area_def_from_cf_geostationary(da, raw_ds=None):
    try:
        from pyresample import geometry as prgeom
        attrs = getattr(da, "attrs", {})
        gm_name = attrs.get("grid_mapping")
        if not gm_name:
            return None
        gm_attrs = {}
        for src in filter(None, [raw_ds, getattr(da, "coords", None), getattr(da, "attrs", None)]):
            try:
                if hasattr(src, "__getitem__") and gm_name in src:
                    gm_attrs = dict(src[gm_name].attrs if hasattr(src[gm_name], "attrs") else {})
                    if gm_attrs:
                        break
            except Exception:
                continue
        if not gm_attrs or gm_attrs.get("grid_mapping_name") != "geostationary":
            return None
        lon_0  = float(gm_attrs.get("longitude_of_projection_origin", 0.0))
        h      = float(gm_attrs.get("perspective_point_height", 35786400.0))
        a      = float(gm_attrs.get("semi_major_axis", 6378137.0))
        b      = float(gm_attrs.get("semi_minor_axis", 6356752.3142))
        sweep  = str(gm_attrs.get("sweep_angle_axis", "y"))
        coords = getattr(da, "coords", {})
        if "x" not in coords or "y" not in coords:
            return None
        x_vals = np.asarray(coords["x"].values, dtype=np.float64)
        y_vals = np.asarray(coords["y"].values, dtype=np.float64)
        x_units = str(getattr(coords["x"], "attrs", {}).get("units", "radian"))
        y_units = str(getattr(coords["y"], "attrs", {}).get("units", "radian"))
        x_m = x_vals * h if "rad" in x_units.lower() else x_vals
        y_m = y_vals * h if "rad" in y_units.lower() else y_vals
        nx = len(x_m); ny = len(y_m)
        dx = abs(x_m[1] - x_m[0]) if nx > 1 else abs(x_m[0])
        dy = abs(y_m[0] - y_m[1]) if ny > 1 else abs(y_m[0])
        left   = float(x_m.min()) - dx / 2
        right  = float(x_m.max()) + dx / 2
        bottom = float(y_m.min()) - dy / 2
        top    = float(y_m.max()) + dy / 2
        proj_dict = {"proj": "geos", "lon_0": lon_0, "h": h, "a": a, "b": b, "units": "m", "sweep": sweep}
        return prgeom.AreaDefinition("cf_geos", "CF geostationary", "cf_geos", proj_dict, nx, ny, [left, bottom, right, top])
    except Exception:
        return None


def _is_lat_like_dim(name: str) -> bool:
    n = str(name).lower()
    return n in ("lat", "latitude", "y", "ny", "nj") or "row" in n or n.endswith("lat")


def _is_lon_like_dim(name: str) -> bool:
    n = str(name).lower()
    return n in ("lon", "longitude", "x", "nx", "ni") or "col" in n or n.endswith("lon")


def _spatial_axes(dims, shape):
    lat_idx = lon_idx = None
    for i, d in enumerate(dims):
        if lat_idx is None and _is_lat_like_dim(d):
            lat_idx = i
        if lon_idx is None and _is_lon_like_dim(d):
            lon_idx = i
    if lat_idx is not None and lon_idx is not None and lat_idx != lon_idx:
        return {lat_idx, lon_idx}
    if len(shape) >= 2:
        sorted_axes = sorted(range(len(shape)), key=lambda i: shape[i], reverse=True)
        return set(sorted_axes[:2])
    return set(range(len(shape)))


def da_to_2d(da, extra_dims: Optional[dict] = None) -> np.ndarray:
    if extra_dims and hasattr(da, "isel"):
        sel = {k: int(v) for k, v in extra_dims.items() if k in da.dims}
        if sel:
            da = da.isel(**sel)
    try:
        import dask
        with dask.config.set(scheduler='synchronous'):
            computed = da.compute() if hasattr(da, 'compute') else da

        arr = computed.values if hasattr(computed, "values") else np.asarray(computed)

    except Exception:

        arr = da.values if hasattr(da, "values") else np.asarray(da)

    if isinstance(arr, np.ma.MaskedArray):
        arr = arr.filled(np.nan)
    is_int    = np.issubdtype(arr.dtype, np.integer)
    orig_dtype = arr.dtype
    arr = arr.astype(np.float64)
    attrs = getattr(da, "attrs", {})
    fill  = attrs.get("_FillValue", attrs.get("missing_value", None))
    if fill is not None:
        try:
            fval = float(fill)
            if is_int and np.issubdtype(orig_dtype, np.unsignedinteger):
                arr[arr >= float(np.iinfo(orig_dtype).max) - 1] = np.nan
            elif np.isfinite(fval):
                arr[arr == fval] = np.nan
        except (TypeError, ValueError):
            pass
    valid_range = attrs.get("valid_range", None)
    if valid_range is not None and is_int:
        try:
            lo, hi = float(valid_range[0]), float(valid_range[1])
            arr[(arr < lo) | (arr > hi)] = np.nan
        except Exception:
            pass
    scale  = attrs.get("scale_factor", None)
    offset = attrs.get("add_offset",   None)
    if scale is not None:
        try: arr = arr * float(scale)
        except Exception: pass
    if offset is not None:
        try: arr = arr + float(offset)
        except Exception: pass
    arr = arr.astype(np.float32)
    pre_dims  = list(da.dims) if hasattr(da, "dims") else []
    pre_shape = arr.shape
    kept_dims = ([d for d, s in zip(pre_dims, pre_shape) if s != 1]
                  if len(pre_dims) == len(pre_shape) else [])

    arr = np.squeeze(arr)
    if arr.ndim == 1:
        return arr
    if arr.ndim > 2:
        if len(kept_dims) == arr.ndim:
            spatial_axes = _spatial_axes(kept_dims, arr.shape)
        else:
            sorted_axes = sorted(range(arr.ndim), key=lambda i: arr.shape[i], reverse=True)
            spatial_axes = set(sorted_axes[:2])
        idx = tuple(slice(None) if i in spatial_axes else 0 for i in range(arr.ndim))
        arr = arr[idx]

    if arr.ndim not in (1, 2):
        raise ValueError(f"Cannot reduce dataset to 2-D: shape={arr.shape}")
    
    return arr



# ── reprojection ──────────────────────────────────────────────────────────────
def _warp_equirect_to_mercator(arr_eq: np.ndarray, bounds: list, max_px: int = 3072,
                                interpolate: bool = False) -> tuple:
    w, s, e, n = bounds
    # Mercator output range must be clamped to ±85, but arr_eq's rows
    # span the FULL original bounds (s..n) — do NOT overwrite s/n used
    # for lats_eq, or rows get mislabeled and the image shifts/misaligns.
    s_out = max(-85.0, s)
    n_out = min(85.0, n)

    def _lat_to_merc_y(lat_deg):
        lat_r = np.radians(np.clip(lat_deg, -85.05, 85.05))
        return np.log(np.tan(np.pi / 4.0 + lat_r / 2.0))

    def _merc_y_to_lat(y):
        return np.degrees(2.0 * np.arctan(np.exp(y)) - np.pi / 2.0)

    h_eq, w_eq = arr_eq.shape
    # arr_eq rows span the ORIGINAL [s, n], not the clamped output range
    lats_eq = np.linspace(n, s, h_eq)   # full range, row 0 = n (true top)

    merc_y_n = _lat_to_merc_y(n_out)
    merc_y_s = _lat_to_merc_y(s_out)
    merc_y_range  = merc_y_n - merc_y_s
    lon_range_rad = max(np.radians(e - w), 1e-6)
    out_nlat = max(2, min(max_px, int(round(w_eq * merc_y_range / lon_range_rad))))

    merc_ys  = np.linspace(merc_y_n, merc_y_s, out_nlat)
    out_lats = np.clip(_merc_y_to_lat(merc_ys), s_out, n_out)

    if interpolate:
        lats_eq_asc = lats_eq[::-1]
        row_idx_asc = np.arange(h_eq, dtype=np.float64)[::-1]
        out_lats_clipped = np.clip(out_lats, lats_eq_asc[0], lats_eq_asc[-1])
        frac_idx = np.interp(out_lats_clipped, lats_eq_asc, row_idx_asc)
        lo = np.floor(frac_idx).astype(int)
        hi = np.clip(lo + 1, 0, h_eq - 1)
        lo = np.clip(lo, 0, h_eq - 1)
        t  = (frac_idx - lo)[:, None]

        row_lo = arr_eq[lo, :]
        row_hi = arr_eq[hi, :]
        both_valid = np.isfinite(row_lo) & np.isfinite(row_hi)
        arr_merc = np.where(
            both_valid,
            row_lo * (1.0 - t) + row_hi * t,
            np.where(np.isfinite(row_lo), row_lo, row_hi),
        )
    else:
        lats_eq_asc = lats_eq[::-1]
        out_lats_clipped = np.clip(out_lats, lats_eq[-1], lats_eq[0])
        idxs_asc = np.searchsorted(lats_eq_asc, out_lats_clipped, side="left")
        idxs_asc = np.clip(idxs_asc, 0, h_eq - 1)
        row_idxs = (h_eq - 1) - idxs_asc
        arr_merc = arr_eq[row_idxs, :]

    # Return the CLAMPED output bounds (this part was already correct)
    return arr_merc.astype(np.float32), [w, s_out, e, n_out]

def reproject_to_wgs84(arr: np.ndarray, area_def, max_px: int = 3072) -> tuple:
    from pyresample import geometry as prgeom
    if isinstance(area_def, prgeom.SwathDefinition):
        try:
            lons = np.asarray(area_def.lons, dtype=np.float64)
            lats = np.asarray(area_def.lats, dtype=np.float64)
        except Exception as e:
            raise ValueError(f"Could not extract lons/lats from SwathDefinition: {e}")
        return _reproject_from_latlon_2d(arr, lats, lons, max_px=max_px)

    import pyproj
    from pyresample import kd_tree as kdt
    left, bottom, right, top = area_def.area_extent
    src_crs = None
    for attr in ("crs", "proj_dict", "proj_str", "wkt"):
        val = getattr(area_def, attr, None)
        if val is not None:
            try:
                src_crs = pyproj.CRS(val)
                break
            except Exception:
                continue
    if src_crs is None:
        src_crs = pyproj.CRS("+proj=geos +lon_0=0 +h=35786023 +ellps=GRS80")

    transformer = pyproj.Transformer.from_crs(src_crs, "EPSG:4326", always_xy=True)
    h_src, w_src = arr.shape
    sample_xs, sample_ys = [], []
    for frac in [i / 32.0 for i in range(33)]:
        x = left   + frac * (right  - left)
        y = bottom + frac * (top    - bottom)
        sample_xs += [x,      x,     left,  right]
        sample_ys += [bottom, top,   y,     y]

    raw_lons, raw_lats = transformer.transform(sample_xs, sample_ys)
    valid = [
        (lo, la) for lo, la in zip(raw_lons, raw_lats)
        if math.isfinite(lo) and math.isfinite(la)
        and -180.0 <= lo <= 180.0 and -90.0 <= la <= 90.0
    ]
    if not valid:
        w, e, s, n = -81.0, 81.0, -81.0, 81.0
    else:
        lons_v, lats_v = zip(*valid)
        w = max(-180.0, min(lons_v)); e = min( 180.0, max(lons_v))
        s = max( -90.0, min(lats_v)); n = min(  90.0, max(lats_v))

    scale = min(1.0, max_px / max(h_src, w_src))
    if scale < 1.0:
        new_h = max(1, int(round(h_src * scale)))
        new_w = max(1, int(round(w_src * scale)))
        row_idx = np.linspace(0, h_src - 1, new_h, dtype=int)
        col_idx = np.linspace(0, w_src - 1, new_w, dtype=int)
        arr = arr[np.ix_(row_idx, col_idx)]
        proj_id = getattr(area_def, "proj_id", getattr(area_def, "area_id", "native"))
        crs_val = getattr(area_def, "crs", getattr(area_def, "proj_dict", getattr(area_def, "proj_str", src_crs.to_wkt())))
        area_def = prgeom.AreaDefinition(area_def.area_id, area_def.description, proj_id, crs_val, new_w, new_h, area_def.area_extent)
        h_src, w_src = new_h, new_w

    aspect = (e - w) / max(n - s, 1e-6)
    out_h  = h_src
    out_w  = max(1, int(round(out_h * aspect)))

    target_area = prgeom.AreaDefinition(
        "wgs84_out", "WGS84 longlat", "wgs84",
        {"proj": "longlat", "datum": "WGS84", "no_defs": True},
        out_w, out_h, [w, s, e, n],
    )
    px  = abs(right - left)  / max(w_src, 1)
    py  = abs(top   - bottom) / max(h_src, 1)
    roi = math.sqrt(px**2 + py**2) * 3.0

    if _render_cancel.is_set():
        raise HTTPException(499, "Render cancelled")
    arr_eq = kdt.resample_nearest(
        area_def, arr.astype(np.float32), target_area,
        radius_of_influence=roi, fill_value=np.nan, nprocs=1,
    ).astype(np.float32)
    return _warp_equirect_to_mercator(arr_eq, [w, s, e, n], max_px=max_px)


def _latlon_coords_from_da(da):
    if da is None or not hasattr(da, "coords"):
        return None, None, False
    lat_names = ("latitude", "lat", "LAT", "nav_lat", "XLAT", "Latitude")
    lon_names = ("longitude", "lon", "LON", "nav_lon", "XLONG", "Longitude")
    lat_arr = lon_arr = None
    for name in lat_names:
        if name in da.coords:
            c = da.coords[name].values
            if -90.5 <= float(np.nanmin(c)) and float(np.nanmax(c)) <= 90.5:
                lat_arr = c.astype(np.float64)
                break
    for name in lon_names:
        if name in da.coords:
            c = da.coords[name].values
            if -360.5 <= float(np.nanmin(c)) and float(np.nanmax(c)) <= 360.5:
                lon_arr = c.astype(np.float64)
                break
    if lat_arr is None or lon_arr is None:
        return None, None, False
    lon_arr = np.where(lon_arr > 180.0, lon_arr - 360.0, lon_arr)
    is_1d   = (lat_arr.ndim == 1 and lon_arr.ndim == 1)
    return lat_arr, lon_arr, is_1d


def _reproject_from_latlon_2d(arr, lat2d, lon2d, max_px=3072):
    from pyresample import geometry as prgeom
    from pyresample import kd_tree as kdt
    valid_mask = (
        np.isfinite(lat2d) & np.isfinite(lon2d) &
        np.isfinite(arr) &
        (lat2d >= -90) & (lat2d <= 90) &
        (lon2d >= -180) & (lon2d <= 180)
    )
    if not valid_mask.any():
        return arr, [-80.0, -80.0, 80.0, 80.0]
    lats_v = lat2d[valid_mask]; lons_v = lon2d[valid_mask]
    lons_v = _unwrap_longitudes(lons_v)
    s = float(np.nanmin(lats_v)); n = float(np.nanmax(lats_v))
    w = float(np.nanmin(lons_v)); e = float(np.nanmax(lons_v))
    bounds = [w, max(-90.0, s), e, min(90.0, n)]

    if np.any(lons_v > 180.0):
        lon2d = np.where(lon2d < 0, lon2d + 360.0, lon2d)
    h_src, w_src = arr.shape
    scale = min(1.0, max_px / max(h_src, w_src))
    if scale < 1.0:
        new_h  = max(1, int(round(h_src * scale)))
        new_w  = max(1, int(round(w_src * scale)))
        row_idx = np.linspace(0, h_src - 1, new_h, dtype=int)
        col_idx = np.linspace(0, w_src - 1, new_w, dtype=int)
        arr   = arr  [np.ix_(row_idx, col_idx)]
        lat2d = lat2d[np.ix_(row_idx, col_idx)]
        lon2d = lon2d[np.ix_(row_idx, col_idx)]
        h_src, w_src = new_h, new_w
    src_swath = prgeom.SwathDefinition(lons=lon2d, lats=lat2d)
    aspect    = (e - w) / max(n - s, 1e-6)
    out_h     = h_src; out_w = max(1, int(round(out_h * aspect)))
    target_area = prgeom.AreaDefinition(
        "wgs84_out", "WGS84 longlat", "wgs84",
        {"proj": "longlat", "datum": "WGS84", "no_defs": True},
        out_w, out_h, [w, s, e, n],
    )
    lat_spacing = abs(n - s) / max(h_src, 1)
    lon_spacing = abs(e - w) / max(w_src, 1)
    roi = math.sqrt(lat_spacing**2 + lon_spacing**2) * 111320 * 3.0
    if _render_cancel.is_set():
        raise HTTPException(499, "Render cancelled")

    result = kdt.resample_nearest(
        src_swath, arr.astype(np.float32), target_area,
        radius_of_influence=max(roi, 50000), fill_value=np.nan, nprocs=1,
    )
    return result.astype(np.float32), bounds