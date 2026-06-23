"""
scenes.py — file/reader detection and Scene loading for Xenia.

DATA_DIR is defined here (moved from main.py) since every path-resolution
helper in this module needs it. main.py imports it back via `from scenes
import DATA_DIR` if needed elsewhere.
"""

import os
import json
import re
import zipfile
import threading
from pathlib import Path
from typing import Optional, List
from urllib.parse import unquote

import numpy as np
import xarray as xr
from fastapi import HTTPException

try:
    from satpy import Scene
    try:
        from satpy.readers.core.grouping import group_files, find_files_and_readers
    except ImportError:
        from satpy.readers import group_files, find_files_and_readers
    SATPY_AVAILABLE = True
except ImportError:
    SATPY_AVAILABLE = False

DATA_DIR = Path(os.environ.get("MTG_DATA_DIR", str(Path(__file__).parent / "data")))

__all__ = [
    "DATA_DIR",
    "SATPY_AVAILABLE",
    "Scene",
    "_scene_cache",
    "_scene_cache_order",
    "_SCENE_ACCESS_LOCK",
    "extract_eumetsat_zips",
    "detect_reader_from_name",
    "probe_satpy_reader",
    "_is_plain_latlon_netcdf",
    "resolve_filepath",
    "_chunk_sort_key",
    "_fci_body_files",
    "get_filenames_for_path",
    "_cache_put",
    "_cache_get",
    "load_scene",
    "_try_create_scene",
    "_XarrayScene",
    "_load_xarray_scene",
    "_load_tropomi_scene",
    "_is_ugrid_file",
    "_UXarrayScene",
    "_load_uxarray_scene",
    "_debug_composite_arrays",
]

def extract_eumetsat_zips():
    for p in sorted(DATA_DIR.iterdir()):
        if p.is_dir():
            continue
        if p.suffix.lower() in (".nc", ".h5", ".hdf5", ".tif", ".tiff"):
            continue
        try:
            with open(p, "rb") as fh:
                magic = fh.read(4)
        except OSError:
            continue
        if magic != b"PK\x03\x04":
            continue
        dest_dir = DATA_DIR / (p.name + "_extracted")
        if dest_dir.exists():
            continue
        dest_dir.mkdir()
        try:
            with zipfile.ZipFile(p, "r") as zf:
                zf.extractall(dest_dir)
        except zipfile.BadZipFile:
            try:
                dest_dir.rmdir()
            except Exception:
                pass


# ── reader detection ──────────────────────────────────────────────────────────
_READER_CANDIDATES = [
        "tropomi_l2",     
    "fci_l1c_nc",
    "fci_l2_nc",
    "li_l2_nc",
    "seviri_l1b_nc",
    "fci_l1c_fdhsi",
    "nc_goes_imager",
    "abi_l1b",
    "clavrx",
]

def detect_reader_from_name(name: str) -> Optional[str]:
    n = name.upper().replace("_EXTRACTED", "")

    if "S5P_" in n or "TROPOMI" in n or "NRTI" in n or "OFFL" in n:
        return "tropomi_l2"          
    if "FCI" in n:
        if "-ASR" in n or "_ASR" in n:
            return None
        if "-AMV" in n or "_AMV" in n:   
            return None                   
        if "L1C" in n or "1C" in n:
            return "fci_l1c_nc"
        if "L2" in n:
            return "fci_l2_nc"   
        return "fci_l1c_nc"
    if "LI" in n and "L2" in n:
        return "li_l2_nc"
    if "W_XX-EUMETSAT" in n and "LI" in n:
        return "li_l2_nc"
    if "HRSEVIRI" in n or ("MSG" in n and "SEVIRI" in n):
        return "seviri_l1b_nc"
    if "LSASAF" in n or "LSA-SAF" in n or "MTLST" in n or "LSA-007" in n:
        return None
    return None

def probe_satpy_reader(filenames: List[str]) -> Optional[str]:
    if not SATPY_AVAILABLE:
        return None
    # Filter out trail/header chunks — satpy can't use them as entry points
    probe_files = [f for f in filenames
                   if "CHK-TRAIL" not in f.upper() and "CHK-HEAD" not in f.upper()]
    if not probe_files:
        probe_files = filenames
    try:
        groups = find_files_and_readers(files=probe_files)
        if groups:
            return next(iter(groups))
    except Exception:
        pass
    for reader in _READER_CANDIDATES:
        try:
            grps = group_files(probe_files, reader=reader)
            if grps:
                return reader
        except Exception:
            continue
    return None


def _is_plain_latlon_netcdf(filenames: List[str]) -> bool:
    try:
        with xr.open_dataset(filenames[0], engine="netcdf4", mask_and_scale=False) as ds:
            lat_names = {"latitude", "lat", "LAT"}
            lon_names = {"longitude", "lon", "LON"}
            all_vars = set(ds.coords) | set(ds.data_vars)   # ← check both
            has_lat = any(n in all_vars for n in lat_names)
            has_lon = any(n in all_vars for n in lon_names)
            if not (has_lat and has_lon):
                return False
            for var in ds.data_vars.values():
                if var.attrs.get("grid_mapping"):
                    return False
            if "x" in ds.coords and "y" in ds.coords:
                x_units = str(ds.coords["x"].attrs.get("units", ""))
                if "rad" in x_units or "projection" in x_units:
                    return False
            return True
    except Exception:
        return False

def resolve_filepath(filepath: str) -> Path:
    filepath = unquote(filepath).strip()
    candidate = DATA_DIR / filepath
    if candidate.exists():
        return candidate
    name = Path(filepath).name
    matches = list(DATA_DIR.rglob(name))
    if len(matches) == 1:
        return matches[0]
    if len(matches) > 1:
        matches.sort(key=lambda p: len(p.parts))
        return matches[0]
    raise HTTPException(404, f"File not found: '{filepath}'. "
                            f"DATA_DIR={DATA_DIR}. "
                            f"Available: {[str(p.relative_to(DATA_DIR)) for p in DATA_DIR.rglob('*.nc')][:20]}")


def _chunk_sort_key(p: str) -> int:
    """Sort FCI chunks: BODY first, TRAIL/HEAD last (satpy needs all but warns on trail)."""
    u = p.upper()
    if "CHK-TRAIL" in u: return 2
    if "CHK-HEAD"  in u: return 2
    if "CHK-BODY"  in u: return 0
    return 1

def _fci_body_files(filenames: List[str]) -> List[str]:
    body = [f for f in filenames
            if "CHK-TRAIL" not in f.upper() and "CHK-HEAD" not in f.upper()]
    return body if body else filenames

def get_filenames_for_path(filepath: str) -> List[str]:
    full = resolve_filepath(filepath)
    if full.is_dir():
        filenames = sorted(
            [str(f) for f in full.rglob("*.nc")],
            key=_chunk_sort_key
        )
        if not filenames:
            raise HTTPException(400, f"No .nc files found under {filepath}")
    else:
        filenames = [str(full)]
    return filenames

# NOTE: _is_lat_like_dim, _is_lon_like_dim, _spatial_axes moved to
# geometry.py — their only caller is da_to_2d(), which lives there.


# ── Scene cache (LRU, 8 slots) ────────────────────────────────────────────────
_scene_cache: dict[tuple, object] = {}
_scene_cache_order: List[tuple] = []
_scene_cache_lock  = threading.Lock()
MAX_CACHED_SCENES  = 8

# Global scene-access lock.
_SCENE_ACCESS_LOCK = threading.RLock()


def _cache_put(key, scene):
    with _scene_cache_lock:
        if key in _scene_cache:
            _scene_cache_order.remove(key)
        _scene_cache[key]   = scene
        _scene_cache_order.append(key)
        while len(_scene_cache_order) > MAX_CACHED_SCENES:
            evict = _scene_cache_order.pop(0)
            _scene_cache.pop(evict, None)


def _cache_get(key):
    with _scene_cache_lock:
        scene = _scene_cache.get(key)
        if scene is not None:
            _scene_cache_order.remove(key)
            _scene_cache_order.append(key)
        return scene


# ── robust Scene loader ────────────────────────────────────────────────────────
def load_scene(filepath: str, reader: Optional[str] = None):
    filenames = get_filenames_for_path(filepath)
    cache_key = (filepath, reader)
    cached = _cache_get(cache_key)
    if cached is not None:
        return cached
    

    # ── UGRID / uxarray fast path ──────────────────────────────────────
    if _is_ugrid_file(filenames) and reader is None:
        try:
            scene = _load_uxarray_scene(filepath, filenames)
            _cache_put(cache_key, scene)
            return scene
        except Exception:
            pass  # fall through


    name_upper = Path(filepath).name.upper()
    is_li_l2 = ("LI" in name_upper and "L2" in name_upper) or \
               ("W_XX-EUMETSAT" in name_upper and "LI" in name_upper)
    if is_li_l2 and reader is None:
        try:
            scene = _load_li_l2_scene(filepath, filenames)
            _cache_put(cache_key, scene)
            return scene
        except Exception as e:
            print(f"LI L2 eager-load failed ({e}), falling through to satpy")

    # ── TROPOMI fast path ─────────────────────────────────────────────
    is_tropomi = any(x in name_upper for x in ("S5P_", "TROPOMI", "NRTI", "OFFL"))
    if is_tropomi and reader is None:
        try:
            scene = _load_tropomi_scene(filepath, filenames)
            _cache_put(cache_key, scene)
            return scene
        except Exception:
            pass  # fall through to satpy


    readers_to_try: List[Optional[str]] = []
    if reader:
        readers_to_try.append(reader)
    
    name_guess = detect_reader_from_name(filepath)

    if not reader and _is_plain_latlon_netcdf(filenames):
        try:
            scene = _load_xarray_scene(filepath, filenames)
            _cache_put(cache_key, scene)
            return scene
        except Exception as e:
            raise HTTPException(400, f"xarray fallback failed for '{filepath}': {e}")

    if name_guess is None and not reader:
        try:
            scene = _load_xarray_scene(filepath, filenames)
            _cache_put(cache_key, scene)
            return scene
        except Exception as e:
            raise HTTPException(400, f"xarray fallback failed for '{filepath}': {e}")

    if name_guess and name_guess not in readers_to_try:
        readers_to_try.append(name_guess)

    probe_result = probe_satpy_reader(_fci_body_files(filenames))
    if probe_result and probe_result not in readers_to_try:
        readers_to_try.append(probe_result)

    for r in _READER_CANDIDATES:
        if r not in readers_to_try:
            readers_to_try.append(r)

    errors = []
    for r in readers_to_try:
        try:
            scene = _try_create_scene(filenames, r)
            if scene.available_dataset_names():
                _cache_put((filepath, r), scene)
                if reader is None:
                    _cache_put(cache_key, scene)
                return scene
            errors.append(f"reader={r}: scene opened but no datasets found")
        except Exception as e:
            errors.append(f"reader={r}: {e}")
            continue

    try:
        scene = _load_xarray_scene(filepath, filenames)
        _cache_put(cache_key, scene)
        return scene
    except Exception as e:
        errors.append(f"xarray fallback: {e}")

    raise HTTPException(
        400,
        f"Could not open '{filepath}' with any reader.\n\nAttempts:\n"
        + "\n".join(f"  • {e}" for e in errors)
    )


def _try_create_scene(filenames: List[str], reader: str) -> "Scene":
    safe_files = _fci_body_files(filenames)
    try:
        return Scene(reader=reader, filenames=safe_files, reader_kwargs={"chunks": "auto"})
    except TypeError:
        return Scene(reader=reader, filenames=safe_files)

# ── xarray fallback scene ─────────────────────────────────────────────────────
class _XarrayScene:
    _LAT_NAMES  = {"latitude", "lat", "LAT", "nav_lat", "XLAT", "lat_0", "Latitude", "lat2d"}
    _LON_NAMES  = {"longitude", "lon", "LON", "nav_lon", "XLONG", "lon_0", "Longitude", "lon2d"}
    _COORD_NAMES = _LAT_NAMES | _LON_NAMES | {
        "time", "level", "pressure", "height", "x", "y",
        "nx", "ny", "nrow", "ncol", "row", "col",
    }

    def __init__(self, ds: xr.Dataset, filepath: str):
        self._ds = ds
        self._filepath = filepath
        self._kept_subgroup_datasets = []  # see _load_tropomi_scene
        self._lat_var = self._find_coord_var(self._LAT_NAMES, -90.5, 90.5)
        self._lon_var = self._find_coord_var(self._LON_NAMES, -360.5, 360.5)

    def _find_coord_var(self, names, vmin, vmax):
        for src in (self._ds.coords, self._ds.data_vars):
            for name in names:
                if name in src:
                    try:
                        v = src[name].values.astype(np.float64)
                        fill = src[name].attrs.get("_FillValue", None)
                        if fill is not None:
                            try:
                                v = v[v != float(fill)]
                            except Exception:
                                pass
                        v = v[np.isfinite(v)]
                        if v.size == 0:
                            continue
                        mn = float(v.min()); mx = float(v.max())
                        if mn >= vmin and mx <= vmax:
                            return name
                    except Exception as e:
                        print(f"FINDCOORD: {name} exception: {e}")
        return None

    def available_dataset_names(self) -> List[str]:
        coord_skip = self._COORD_NAMES | set(filter(None, [self._lat_var, self._lon_var]))
        names = []
        has_latlon = self._lat_var is not None and self._lon_var is not None
        for v in self._ds.data_vars:
            if str(v).lower() in coord_skip:
                continue
            da = self._ds[v]
            if da.ndim == 0:
                continue
            if da.ndim >= 2 and max(da.shape) > 10:
                names.append(str(v))
                continue
            if da.ndim == 1 and da.size > 100:
                attrs = getattr(da, "attrs", {})
                # Original: required grid_mapping/coordinate attr
                # New: also accept if the scene has explicit lat/lon coords (AMV, etc.)
                if attrs.get("grid_mapping") or attrs.get("coordinate") or has_latlon:
                    names.append(str(v))
        return sorted(names)

    def load(self, datasets):
        pass

    def __contains__(self, name):
        return name in self._ds

    def __getitem__(self, name):
        da = self._ds[name]
        coords_to_add = {}
        for var_name, coord_attr in [(self._lat_var, None), (self._lon_var, None)]:
            if var_name is None:
                continue
            if var_name in da.coords:
                continue
            src_da = (self._ds[var_name] if var_name in self._ds.data_vars
                      else self._ds.coords[var_name])
            if set(src_da.dims) and set(src_da.dims).issubset(set(da.dims)):
                coords_to_add[var_name] = src_da
        if coords_to_add:
            try:
                da = da.assign_coords(coords_to_add)
            except Exception:
                pass
        return da

    @property
    def attrs(self):
        return self._ds.attrs


def _load_xarray_scene(filepath: str, filenames: List[str]) -> _XarrayScene:
    nc_file = filenames[0]
    
    # Discover non-empty group
    groups_to_try = [None, "PRODUCT", "product", "data", "Data", 
                     "PRODUCT/SUPPORT_DATA/GEOLOCATIONS",
                     "PRODUCT/SUPPORT_DATA/INPUT_DATA"]
    
    # For S5P/TROPOMI: scan with h5py to find groups with real data
    try:
        import h5py
        with h5py.File(nc_file, "r") as f:
            def _find_groups(name, obj):
                if isinstance(obj, h5py.Group) and len(obj.keys()) > 0:
                    groups_to_try.insert(1, name)  # prioritize discovered groups
            f.visititems(_find_groups)
    except Exception:
        pass
    
    for group in groups_to_try:
        for engine in ("netcdf4", "h5netcdf"):
            try:
                kwargs = {"engine": engine, "chunks": None, "mask_and_scale": True}

                if group is not None:
                    kwargs["group"] = group
                ds = xr.open_dataset(nc_file, **kwargs)
                if ds.data_vars:
                    return _XarrayScene(ds, filepath)
            except Exception:
                continue
    
    raise RuntimeError(f"xarray could not open {nc_file} — "
                       f"tried root + subgroups with netcdf4/h5netcdf")




def _load_tropomi_scene(filepath: str, filenames: List[str]) -> "_XarrayScene":
    nc_file = filenames[0]

    ds = xr.open_dataset(nc_file, engine="netcdf4",
                         group="PRODUCT", mask_and_scale=True,
                         chunks=None)
    ds = ds.load()

    subgroups = [
        "PRODUCT/SUPPORT_DATA/GEOLOCATIONS",
        "PRODUCT/SUPPORT_DATA/DETAILED_RESULTS",
        "PRODUCT/SUPPORT_DATA/INPUT_DATA",
    ]
    for group in subgroups:
        try:
            with xr.open_dataset(nc_file, engine="netcdf4",
                                 group=group, mask_and_scale=True,
                                 chunks=None) as ds_sub:
                ds_sub = ds_sub.load()
                for var in ds_sub.data_vars:
                    if var not in ds:
                        # FIX 2: copy to plain numpy — no file handle reference
                        ds[var] = xr.DataArray(
                            ds_sub[var].values.copy(),
                            dims=ds_sub[var].dims,
                            attrs=ds_sub[var].attrs,
                        )
                for coord in ds_sub.coords:
                    if coord not in ds.coords:
                        ds = ds.assign_coords({coord: xr.DataArray(
                            ds_sub.coords[coord].values.copy(),
                            dims=ds_sub.coords[coord].dims,
                            attrs=ds_sub.coords[coord].attrs,
                        )})
        except Exception:
            continue

    if "time" in ds.dims and ds.sizes.get("time", 1) == 1:
        ds = ds.squeeze("time", drop=True)

    ds = ds.load()
    return _XarrayScene(ds, filepath)




def _load_li_l2_scene(filepath: str, filenames: List[str]) -> "_XarrayScene":
    """Eager-load MTG LI L2 NetCDF — same HDF5-safe pattern as TROPOMI."""
    nc_file = filenames[0]

    # LI L2 files are flat NetCDF4 — open at root, load fully into RAM
    ds = xr.open_dataset(nc_file, engine="netcdf4",
                         mask_and_scale=True, chunks=None)
    ds = ds.load()   # ← force eager: no dask, no open file handle after this

    # Squeeze trivial time dim if present
    if "time" in ds.dims and ds.sizes.get("time", 1) == 1:
        ds = ds.squeeze("time", drop=True)

    return _XarrayScene(ds, filepath)




# Detection
def _is_ugrid_file(filenames: List[str]) -> bool:
    try:
        with xr.open_dataset(filenames[0], engine="netcdf4", mask_and_scale=False) as ds:
            conventions = str(ds.attrs.get("Conventions", ""))
            if "UGRID" in conventions.upper():
                return True
            for var in ds.data_vars:
                if ds[var].attrs.get("cf_role") == "mesh_topology":
                    return True
        return False
    except Exception:
        return False
    

# New scene class
class _UXarrayScene:
    def __init__(self, uxds, filepath: str):
        self._uxds = uxds
        self._filepath = filepath

    def available_dataset_names(self) -> List[str]:
        return [str(v) for v in self._uxds.data_vars]

    def load(self, datasets):
        pass

    def __contains__(self, name):
        return name in self._uxds

    def __getitem__(self, name):
        return self._uxds[name]  # returns UxDataArray

    @property
    def attrs(self):
        return self._uxds.attrs
    



# Loader
def _load_uxarray_scene(filepath: str, filenames: List[str]):
    try:
        import uxarray as ux
    except ImportError:
        raise RuntimeError("uxarray not installed: pip install uxarray")
    
    # uxarray needs the grid file — sometimes same file, sometimes separate
    uxds = ux.open_dataset(filenames[0], filenames[0])
    return _UXarrayScene(uxds, filepath)


def _debug_composite_arrays(composite: str, arr: np.ndarray, stage: str):
    """Print min/max/mean per band to diagnose color issues."""
    if arr.ndim == 3:
        n = arr.shape[-1] if arr.shape[-1] in (3, 4) else arr.shape[0]
        for i in range(min(n, 4)):
            if arr.shape[-1] in (3, 4):
                band = arr[:, :, i]
            else:
                band = arr[i, :, :]
            valid = band[np.isfinite(band)]
            if valid.size:
                print(f"  band[{i}]: min={valid.min():.4f} max={valid.max():.4f} "
                      f"mean={valid.mean():.4f} p2={np.percentile(valid,2):.4f} "
                      f"p98={np.percentile(valid,98):.4f}")
            else:
                print(f"  band[{i}]: all NaN/empty")
