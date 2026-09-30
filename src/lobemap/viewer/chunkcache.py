"""Decoded stain chunks, kept for the next 2D slice step.

The virtual stains are OME-Zarr stores cut in 64-voxel cubes. A 2D slice
needs one voxel layer of every chunk the plane crosses, but a chunk is
compressed whole, so each step decompresses 64 planes and uses one. The next
step lands in the same chunks and decompresses them all again. Kept decoded,
those chunks serve every plane they hold from memory.

dask sat here before, with napari's opportunistic cache, and that cached the
chunks too. What it could not avoid is its own bookkeeping: building,
ordering and running a task graph costs milliseconds per compute, and napari
computes twice per step, once for the plane and once for the thumbnail. A
step that only copies cached chunks costs well under a millisecond here.

Chunks that are not cached are read by a pool of threads, each reading one
chunk file and decoding it. The stores are zarr v2 on local disk, where a
chunk is one file named by its index and compressed by one codec, so this
is the whole of what zarr would do for them; zarr's own reader serializes
through its event loop and is two to three times slower here. Any other
store is read through zarr.

3D reads its levels whole, through `read_whole`, which assembles them from
the chunk files without keeping any: `images.FineLevel` holds each such
level as an array for the layer's life, so a return to 3D is served from
memory, and the cache holds 2D's chunks only. Any other read larger than
half the budget is assembled the same way, so no single read can flush
everything else out.
"""

from __future__ import annotations

import os
import threading
from collections import OrderedDict
from concurrent.futures import ThreadPoolExecutor
from itertools import product
from operator import index
from pathlib import Path

import numpy as np

#: Decoded bytes kept per stain, for 2D. A maximized window shows the FAFB
#: stain's second level, 60 MB a chunk layer; zoomed into its full-resolution
#: level, a chunk layer is 100 MB. So this holds a few chunk layers, and a
#: plane only needs the one it lies in.
CACHE_BYTES = 512 * 2**20

_POOL: ThreadPoolExecutor | None = None
_POOL_LOCK = threading.Lock()


def _pool() -> ThreadPoolExecutor:
    global _POOL
    with _POOL_LOCK:
        if _POOL is None:
            _POOL = ThreadPoolExecutor(max_workers=min(8, os.cpu_count() or 1),
                                       thread_name_prefix="lobemap-chunks")
        return _POOL


class ChunkCache:
    """Least recently used decoded chunks, within a byte budget.

    Thread-safe: napari's asynchronous slicing reads from a worker thread
    while the main thread may read for a picked value.
    """

    def __init__(self, max_bytes: int = CACHE_BYTES):
        self.max_bytes = int(max_bytes)
        self.nbytes = 0
        self._items: OrderedDict = OrderedDict()
        self._lock = threading.Lock()

    def __len__(self) -> int:
        return len(self._items)

    def get_many(self, keys) -> list:
        """The cached array for each key, or None; one lock for all."""
        out = []
        with self._lock:
            for key in keys:
                arr = self._items.get(key)
                if arr is not None:
                    self._items.move_to_end(key)
                out.append(arr)
        return out

    def put(self, key, arr: np.ndarray) -> None:
        with self._lock:
            old = self._items.pop(key, None)
            if old is not None:
                self.nbytes -= old.nbytes
            self._items[key] = arr
            self.nbytes += arr.nbytes
            while self.nbytes > self.max_bytes and len(self._items) > 1:
                _, gone = self._items.popitem(last=False)
                self.nbytes -= gone.nbytes


class _ChunkFiles:
    """One chunk at a time from a zarr v2 array on local disk.

    Exactly what the v2 format specifies: the file named by the chunk's
    key holds the whole chunk, edge chunks padded, compressed by the
    array's compressor; an absent file is all fill value.
    """

    def __init__(self, array):
        meta = array.metadata
        self.root = Path(array.store.root).resolve() / array.path
        self.key = meta.encode_chunk_key
        self.codec = meta.compressor
        self.fill = meta.fill_value
        self.dtype = np.dtype(array.dtype)
        self.chunks = tuple(int(c) for c in array.chunks)
        self.shape = tuple(int(n) for n in array.shape)

    @classmethod
    def of(cls, array) -> _ChunkFiles | None:
        """A reader for `array`, or None when it is not exactly that store.

        Exactly: zarr v2 on local disk, C order, one compressor and no
        filter, a plain number type in this machine's byte order, and
        chunks that tile the array. That is how `core.zarrfmt` writes the
        stains. Anything else -- zarr v3, sharding, a filter, F order, no
        compressor, a structured or byte-swapped dtype -- is read by zarr.
        """
        # Imported here: a space without a stain never needs zarr.
        from zarr.storage import LocalStore

        try:
            meta = array.metadata
            dtype = np.dtype(array.dtype)
            plain = (
                meta.zarr_format == 2
                and isinstance(array.store, LocalStore)
                and not meta.filters
                and meta.order == "C"
                and meta.compressor is not None
                and dtype.kind in "biuf"
                and dtype.isnative
                and len(array.chunks) == len(array.shape)
            )
            return cls(array) if plain else None
        except (AttributeError, TypeError):
            return None

    def read(self, idx) -> np.ndarray:
        inside = tuple(slice(0, min(c, n - i * c))
                       for i, c, n in zip(idx, self.chunks, self.shape, strict=True))
        try:
            raw = (self.root / self.key(idx)).read_bytes()
        except FileNotFoundError:
            size = tuple(s.stop for s in inside)
            return np.full(size, self.fill if self.fill is not None else 0, self.dtype)
        full = np.frombuffer(self.codec.decode(raw), dtype=self.dtype).reshape(self.chunks)
        return full[inside]


class CachedLevel:
    """One pyramid level of a chunked store, read through a `ChunkCache`.

    Indexing with slices alone returns another lazy view, as dask does:
    napari first cuts `data[displayed]` with the slider axis left whole, and
    only then picks the plane, so the first cut must not read anything.
    An integer, a strided slice or `np.asarray` reads; anything else napari
    never sends goes to the store unchanged.
    """

    def __init__(self, array, cache: ChunkCache, key, box=None, files=False):
        self._array = array
        self._cache = cache
        self._key = key
        self._files = _ChunkFiles.of(array) if files is False else files
        self.chunks = tuple(int(c) for c in array.chunks)
        self.dtype = np.dtype(array.dtype)
        full = tuple((0, int(n)) for n in array.shape)
        self._box = full if box is None else box
        self.shape = tuple(b - a for a, b in self._box)

    @property
    def ndim(self) -> int:
        return len(self.shape)

    @property
    def size(self) -> int:
        return int(np.prod(self.shape, dtype=np.int64))

    @property
    def nbytes(self) -> int:
        return self.size * self.dtype.itemsize

    def __repr__(self) -> str:
        return f"CachedLevel(shape={self.shape}, dtype={self.dtype}, chunks={self.chunks})"

    def __array__(self, dtype=None, copy=None):
        out = self._read(*(np.array(v) for v in zip(*self._box, strict=True)))
        return out if dtype is None else out.astype(dtype, copy=False)

    def __getitem__(self, key):
        box = _box(key, self.shape)
        if box is None:
            whole = tuple(slice(a, b) for a, b in self._box)
            return np.asarray(self._array[whole])[key]
        origin = [a for a, _ in self._box]
        if all(not is_int and step == 1 for _, _, step, is_int in box):
            return CachedLevel(self._array, self._cache, self._key, tuple(
                (o + start, o + stop) for o, (start, stop, _, _) in zip(origin, box, strict=True)),
                self._files)
        lo = np.array([o + b[0] for o, b in zip(origin, box, strict=True)])
        hi = np.array([o + b[1] for o, b in zip(origin, box, strict=True)])
        block = self._read(lo, hi)
        return block[tuple(0 if b[3] else slice(None, None, b[2]) for b in box)]

    def _read(self, lo: np.ndarray, hi: np.ndarray, keep: bool = True) -> np.ndarray:
        """The box [lo, hi) of the level, from cached chunks where it can.

        With `keep` false, or a box too big to cache, the chunks it reads are
        not kept.
        """
        if np.any(hi <= lo):
            return np.empty(tuple(np.maximum(hi - lo, 0)), dtype=self.dtype)
        # Per axis: each chunk index the box crosses, where its part lands in
        # the output, and where that part sits in the chunk. Their products
        # are the cells; built by `product`, not per cell, since a plane of
        # the finest level crosses hundreds of chunks.
        index, dst, src = [], [], []
        for a, ci in enumerate(self.chunks):
            lo_a, hi_a = int(lo[a]), int(hi[a])
            first, last = lo_a // ci, (hi_a - 1) // ci
            index.append(range(first, last + 1))
            starts = [i * ci for i in index[-1]]
            dst.append([slice(max(lo_a, t) - lo_a, min(hi_a, t + ci) - lo_a) for t in starts])
            src.append([slice(max(lo_a, t) - t, min(hi_a, t + ci) - t) for t in starts])
        cells = list(product(*index))
        out = np.empty(tuple(hi - lo), dtype=self.dtype)
        spanned = len(cells) * int(np.prod(self.chunks)) * self.dtype.itemsize
        if not keep or spanned > self._cache.max_bytes // 2:
            return self._read_through(cells, product(*dst), product(*src), out, lo, hi)
        arrays = self._cache.get_many([(self._key, idx) for idx in cells])
        missing = [idx for idx, arr in zip(cells, arrays, strict=True) if arr is None]
        fetched = self._fetch(missing) if missing else {}
        for idx, arr, d, s in zip(cells, arrays, product(*dst), product(*src), strict=True):
            out[d] = (fetched[idx] if arr is None else arr)[s]
        return out

    def _read_through(self, cells, dst, src, out, lo, hi) -> np.ndarray:
        """A read too big to cache, straight into `out`."""
        if self._files is None:
            return np.asarray(self._array[tuple(slice(a, b) for a, b in zip(lo, hi, strict=True))])

        def one(job):
            idx, d, s = job
            out[d] = self._files.read(idx)[s]

        list(_pool().map(one, zip(cells, dst, src, strict=True)))
        return out

    def _fetch(self, missing) -> dict:
        """Read the missing chunks, and cache each."""
        if self._files is not None:
            chunks = dict(zip(missing, _pool().map(self._files.read, missing), strict=True))
        else:
            chunks = self._fetch_box(missing)
        for idx, chunk in chunks.items():
            self._cache.put((self._key, idx), chunk)
        return chunks

    def _fetch_box(self, missing) -> dict:
        """Through zarr: one read of the box around the missing chunks."""
        c, n = self.chunks, self._array.shape
        first = [min(idx[a] for idx in missing) for a in range(len(c))]
        last = [max(idx[a] for idx in missing) for a in range(len(c))]
        origin = [f * ci for f, ci in zip(first, c, strict=True)]
        region = tuple(slice(o, min((m + 1) * ci, na))
                       for o, m, ci, na in zip(origin, last, c, n, strict=True))
        block = np.asarray(self._array[region])
        out = {}
        for idx in product(*(range(f, m + 1) for f, m in zip(first, last, strict=True))):
            part = tuple(slice(i * ci - o, min((i + 1) * ci, na) - o)
                         for i, ci, o, na in zip(idx, c, origin, n, strict=True))
            out[idx] = np.ascontiguousarray(block[part])
        return out


def _box(key, shape):
    """Per axis (start, stop, step, is_int) for a basic index, else None."""
    if not isinstance(key, tuple):
        key = (key,)
    if any(k is Ellipsis for k in key):
        at = next(i for i, k in enumerate(key) if k is Ellipsis)
        fill = (slice(None),) * (len(shape) - len(key) + 1)
        key = key[:at] + fill + key[at + 1:]
    if len(key) > len(shape):
        return None
    key = key + (slice(None),) * (len(shape) - len(key))
    out = []
    for k, n in zip(key, shape, strict=True):
        if isinstance(k, slice):
            start, stop, step = k.indices(n)
            if step < 0:
                return None
            out.append((start, max(start, stop), step, False))
            continue
        try:
            i = index(k)
        except TypeError:
            return None
        if i < 0:
            i += n
        if not 0 <= i < n:
            raise IndexError(f"index {k} is out of bounds for an axis of size {n}")
        out.append((i, i + 1, 1, True))
    return out


def read_whole(level) -> np.ndarray:
    """A whole pyramid level as an array, read without filling the cache.

    For a `CachedLevel`, straight from its chunk files by the thread pool;
    for anything else, whatever reading it whole does.
    """
    if isinstance(level, CachedLevel):
        lo, hi = (np.array(v) for v in zip(*level._box, strict=True))
        return level._read(lo, hi, keep=False)
    return np.asarray(level[...])


def cached_levels(levels, cache: ChunkCache | None = None) -> list:
    """Each chunked level wrapped over one shared cache; others unchanged."""
    cache = ChunkCache() if cache is None else cache
    out = []
    for i, arr in enumerate(levels):
        chunks = getattr(arr, "chunks", None)
        regular = (isinstance(chunks, tuple) and len(chunks) == len(arr.shape)
                   and all(isinstance(ci, int) for ci in chunks))
        out.append(CachedLevel(arr, cache, i) if regular and not isinstance(arr, np.ndarray)
                   else arr)
    return out


__all__ = ["CACHE_BYTES", "CachedLevel", "ChunkCache", "cached_levels", "read_whole"]
