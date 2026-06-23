"""
state.py — shared mutable singletons for Xenia.

These objects must be the SAME instance everywhere they're used — main.py's
routes set/clear/read them, and geometry.py / rendering.py read/write them
deep inside the render pipeline. Putting them in their own module (instead
of main.py) lets every other module import them without a circular import
(main.py -> rendering.py -> main.py would break).

Import with: from state import *
"""

import threading
from concurrent.futures import ThreadPoolExecutor

__all__ = [
    "_LRUCache",
    "_render_cancel",
    "_render_lock",
    "_GEOM_CACHE",
    "_RENDER_CACHE",
    "_NEIGHBOUR_INFO_CACHE",
    "_INFLIGHT",
    "_INFLIGHT_LOCK",
    "_INFLIGHT_RESULTS",
    "_NATIVE_EXECUTOR",
]


class _LRUCache:
    """Thread-safe LRU cache backed by an ordered dict."""

    def __init__(self, maxsize: int = 64):
        from collections import OrderedDict
        self._data: "OrderedDict" = __import__("collections").OrderedDict()
        self._maxsize = maxsize
        self._lock = threading.RLock()

    def get(self, key):
        with self._lock:
            if key not in self._data:
                return None
            self._data.move_to_end(key)
            return self._data[key]

    def put(self, key, value):
        with self._lock:
            if key in self._data:
                self._data.move_to_end(key)
            self._data[key] = value
            if len(self._data) > self._maxsize:
                self._data.popitem(last=False)

    def __len__(self):
        with self._lock:
            return len(self._data)

    def clear(self):
        with self._lock:
            self._data.clear()

    def keys(self):
        with self._lock:
            return list(self._data.keys())



_render_cancel = threading.Event()
_render_lock = threading.Lock()

# Geometry cache: stores (arr_wgs: np.ndarray float32, bounds: list, vmin_auto, vmax_auto)
# Key: geom_key string = sha256 of (resolved_filepath, dataset, quality, extra_dims_json)
_GEOM_CACHE = _LRUCache(maxsize=32)

# Full render cache: stores (png_bytes, bounds, vmin, vmax, shape)
# Key: render_key string = sha256 of (geom_key + colormap + vmin + vmax)
_RENDER_CACHE = _LRUCache(maxsize=64)
_NEIGHBOUR_INFO_CACHE = _LRUCache(maxsize=8)

# In-flight deduplication: prevent two identical concurrent requests from both
# computing the same expensive reprojection.
_INFLIGHT: dict = {}
_INFLIGHT_LOCK = threading.Lock()
_INFLIGHT_RESULTS: dict = {}

# ── Dedicated native-work thread ─────────────────────────────────────────────
_NATIVE_EXECUTOR = ThreadPoolExecutor(max_workers=1, thread_name_prefix="xenia-native")