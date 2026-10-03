"""The stain levels napari slices: the same voxels as the store, read once.

Every test builds its own store with `Volume.save`, the writer the shipped
stains came from, so none needs fetched data.
"""

from __future__ import annotations

import numpy as np
import pytest

from lobemap.core.imagefmt import Volume
from lobemap.viewer import chunkcache
from lobemap.viewer.chunkcache import CachedLevel, ChunkCache, cached_levels


@pytest.fixture
def store(tmp_path):
    """A pyramid in 16-voxel chunks, with edge chunks and one absent chunk."""
    rng = np.random.default_rng(0)
    data = rng.integers(1, 255, (70, 45, 38)).astype(np.uint8)
    data[:16, :16, :16] = 0          # all fill value: zarr writes no file
    got = Volume.load(Volume(data=data, voxel_um=(1.0,) * 3).save(
        tmp_path / "s.zarr", chunks=(16, 16, 16), min_extent=8))
    assert got.is_multiscale
    return data, got.levels


def _reads(monkeypatch):
    """Count chunk files read."""
    count = [0]
    real = chunkcache._ChunkFiles.read

    def read(self, idx):
        count[0] += 1
        return real(self, idx)

    monkeypatch.setattr(chunkcache._ChunkFiles, "read", read)
    return count


def _napari_keys(shape):
    """The indexes napari sends: a plane on each axis, whole or a chunk-aligned
    tile, then picked out of a view that leaves the slider axis whole."""
    for axis in range(3):
        for k in (0, shape[axis] // 2, shape[axis] - 1):
            tile = [slice(None)] * 3
            yield axis, k, tuple(tile)
            tile = [slice(3, min(n, 35)) for n in shape]
            tile[axis] = slice(None)
            yield axis, k, tuple(tile)


def test_every_plane_napari_asks_for_matches_the_store(store):
    data, levels = store
    wrapped = cached_levels(levels)
    for level, arr in zip(wrapped, levels, strict=True):
        assert isinstance(level, CachedLevel)
        truth = np.asarray(arr[:])
        for axis, k, tile in _napari_keys(level.shape):
            view = level[tile]                     # displayed axes only
            assert isinstance(view, CachedLevel), "the first cut must stay lazy"
            pick = [slice(None)] * 3
            pick[axis] = k
            got = view[tuple(pick)]
            want = truth[tile][tuple(pick)]
            assert got.shape == want.shape and np.array_equal(got, want), (axis, k, tile)
    assert np.array_equal(np.asarray(wrapped[0]), data)


def test_other_indexes_match_the_store(store):
    _, levels = store
    level, truth = cached_levels(levels)[0], np.asarray(levels[0][:])
    for key in [(5, 7, 9), (-1, slice(None), 3), (Ellipsis, 2), np.int64(3),
                (slice(1, 50, 3), slice(None), 4), (slice(60, 10), slice(None), 0)]:
        got = np.asarray(level[key])
        assert got.shape == truth[key].shape and np.array_equal(got, truth[key]), key
    with pytest.raises(IndexError):
        level[70, 0, 0]


def test_the_next_plane_in_a_chunk_reads_nothing(store, monkeypatch):
    """The point of the cache: a step within a chunk layer is served from memory."""
    _, levels = store
    level = cached_levels(levels)[0]
    reads = _reads(monkeypatch)
    level[:, :, 20]
    first = reads[0]
    assert first >= 5 * 3, "one chunk per chunk the plane crosses"
    for k in range(21, 32):                                    # same 16-deep layer
        level[:, :, k]
    assert reads[0] == first


def test_a_level_too_big_for_the_budget_is_read_but_not_kept(store):
    """3D asks for a whole level; keeping it would evict every 2D chunk."""
    _, levels = store
    cache = ChunkCache(max_bytes=2 * 16**3)
    level = cached_levels(levels, cache)[0]
    got = np.asarray(level)
    assert np.array_equal(got, np.asarray(levels[0][:]))
    assert len(cache) == 0


def test_the_budget_evicts_least_recently_used():
    cache = ChunkCache(max_bytes=3 * 100)
    for key in "abc":
        cache.put(key, np.zeros(100, np.uint8))
    cache.get_many(["a"])                     # a is now the most recent
    cache.put("d", np.zeros(100, np.uint8))
    assert cache.get_many("abcd")[1] is None, "b was least recently used"
    assert all(arr is not None for arr in cache.get_many("acd"))
    assert cache.nbytes == 300


def test_stepping_stays_within_the_budget(store):
    _, levels = store
    cache = ChunkCache(max_bytes=20 * 16**3)  # under the four chunk layers it steps through
    level = cached_levels(levels, cache)[0]
    truth = np.asarray(levels[0][:])
    for k in range(0, 70, 5):
        assert np.array_equal(level[k, :, :], truth[k])
        assert 0 < cache.nbytes <= cache.max_bytes


def test_a_store_it_cannot_read_directly_goes_through_zarr(store):
    _, levels = store
    level = CachedLevel(levels[0], ChunkCache(), 0, files=None)
    truth = np.asarray(levels[0][:])
    assert np.array_equal(level[:, :, 7], truth[:, :, 7])
    assert np.array_equal(np.asarray(level), truth)


def test_numpy_levels_are_left_alone():
    arr = np.zeros((4, 4, 4), np.uint8)
    assert cached_levels([arr])[0] is arr


def test_napari_slices_the_same_plane_from_the_cache(store):
    """Through a real napari layer: the 2D slice it hands to vispy."""
    napari = pytest.importorskip("napari")
    _, levels = store
    viewer = napari.Viewer(show=False)
    try:
        layer = viewer.add_image(cached_levels(levels), multiscale=True)
        viewer.dims.order = (2, 1, 0)
        for k in (3, 17, 30):
            viewer.dims.set_current_step(2, k)
            level = layer.data_level
            shown = np.asarray(layer._slice.image.raw)
            z = int(np.round(k / layer.downsample_factors[level][2]))
            want = np.asarray(levels[level][:, :, z]).T
            corners = layer.corner_pixels
            want = want[corners[0, 1]:corners[1, 1] + 1, corners[0, 0]:corners[1, 0] + 1]
            assert np.array_equal(shown, want), (k, level)
    finally:
        viewer.close()


@pytest.mark.parametrize("layout", [
    {"dtype": ">u2"},                                   # byte-swapped
    {"dtype": "u1", "order": "F"},
    {"dtype": "u1", "compressors": None},
    {"dtype": "u1", "filters": "delta"},
    {"dtype": "u1", "zarr_format": 3},
])
def test_any_other_layout_is_read_by_zarr(tmp_path, layout):
    """The direct reader takes exactly the stains' layout; zarr reads the rest."""
    import zarr
    from numcodecs import Delta, Zstd

    layout = dict(layout)
    fmt = layout.pop("zarr_format", 2)
    dtype = np.dtype(layout.pop("dtype"))
    if layout.get("filters") == "delta":
        layout["filters"] = [Delta(dtype=dtype.str)]
    kwargs = {"compressors": Zstd()} if fmt == 2 else {}
    kwargs.update(layout)
    arr = zarr.create_array(store=str(tmp_path / "a.zarr"), shape=(40, 30, 20),
                            chunks=(16, 16, 16), dtype=dtype, zarr_format=fmt, **kwargs)
    truth = np.random.default_rng(1).integers(0, 200, arr.shape).astype(dtype)
    arr[:] = truth
    arr = zarr.open_array(str(tmp_path / "a.zarr"), mode="r")
    assert chunkcache._ChunkFiles.of(arr) is None
    level = CachedLevel(arr, ChunkCache(), 0)
    assert np.array_equal(level[:, :, 7], truth[:, :, 7])
    assert np.array_equal(level[5], truth[5])


def test_the_shipped_layout_is_read_directly(store):
    _, levels = store
    assert all(chunkcache._ChunkFiles.of(arr) is not None for arr in levels)


def test_a_whole_level_for_3d_is_read_but_not_kept(store):
    """3D keeps its levels itself (`images.FineLevel`); the cache stays 2D's."""
    from lobemap.viewer.chunkcache import read_whole

    _, levels = store
    cache = ChunkCache()
    level = cached_levels(levels, cache)[0]
    assert np.array_equal(read_whole(level), np.asarray(levels[0][:]))
    assert len(cache) == 0
    plain = np.arange(24).reshape(2, 3, 4)
    assert np.array_equal(read_whole(plain), plain)


def _slow_reads(monkeypatch, seconds):
    """Make every chunk file read take `seconds`, and record each read's thread."""
    import threading

    real = chunkcache._ChunkFiles.read
    log = []

    def read(self, idx):
        log.append(threading.current_thread().name)
        import time

        time.sleep(seconds)
        return real(self, idx)

    monkeypatch.setattr(chunkcache._ChunkFiles, "read", read)
    return log


def test_a_read_from_the_ui_thread_waits_behind_one_batch_of_a_background_read(
        store, monkeypatch):
    """A whole level read in the background shares the pool a batch at a time.

    Handed over at once, its chunks queued every read the UI thread made
    meanwhile behind the whole level. Here the level is 45 chunks of 20 ms
    each, about 120 ms for the pool; the UI thread's read, made once the
    background read is under way, may wait for one batch, not the rest.
    """
    import threading
    import time

    from lobemap.viewer.chunkcache import WORKERS, read_whole

    _, levels = store
    whole, plane = cached_levels(levels)[0], cached_levels(levels)[0]
    _slow_reads(monkeypatch, 0.02)
    out = {}
    background = threading.Thread(
        target=lambda: out.update(level=read_whole(whole, stop=threading.Event())))
    background.start()
    time.sleep(0.03)                                 # the first batch is in
    started = time.perf_counter()
    got = plane[0, 0, 0]                             # one chunk, kept: a UI read
    waited = time.perf_counter() - started
    background.join()
    assert got == np.asarray(levels[0][0, 0, 0])
    assert np.array_equal(out["level"], np.asarray(levels[0][:]))
    # Its own read, plus one batch of the background read at most.
    assert waited < 3 * 0.02, (waited, WORKERS)


def test_a_stopped_background_read_ends_at_its_next_batch(store, monkeypatch):
    import threading
    import time

    from lobemap.viewer.chunkcache import WORKERS, read_whole

    _, levels = store
    level = cached_levels(levels)[0]
    log = _slow_reads(monkeypatch, 0.01)
    stop = threading.Event()
    out = {}
    background = threading.Thread(target=lambda: out.update(level=read_whole(level, stop=stop)))
    background.start()
    while not log:
        time.sleep(0.001)
    stop.set()
    background.join()
    assert out["level"] is None
    assert len(log) <= 2 * WORKERS, "read on after it was stopped"


@pytest.mark.parametrize("fill", [7, 200])
def test_an_absent_chunk_reads_as_the_fill_value(tmp_path, fill):
    """zarr writes no file for a chunk that is all fill value; the direct
    reader gives that chunk the array's fill value, as zarr does, not zeros."""
    import zarr
    from numcodecs import Zstd

    path = tmp_path / "a.zarr"
    arr = zarr.create_array(store=str(path), shape=(40, 30, 20), chunks=(16, 16, 16),
                            dtype="u1", zarr_format=2, compressors=Zstd(), fill_value=fill)
    truth = np.random.default_rng(2).integers(0, 255, arr.shape).astype(np.uint8)
    truth[16:32, :16, :16] = fill                 # chunk (1, 0, 0): all fill value
    arr[:] = truth
    arr = zarr.open_array(str(path), mode="r")
    files = chunkcache._ChunkFiles.of(arr)
    assert files is not None, "not read directly"
    assert not (path / files.key((1, 0, 0))).exists(), "zarr wrote the chunk"
    assert (path / files.key((0, 0, 0))).exists()
    level = CachedLevel(arr, ChunkCache(), 0)
    for k in (16, 20, 31):
        assert np.array_equal(level[k], truth[k]), k
        assert np.array_equal(level[:, :, k % 20], truth[:, :, k % 20]), k
    assert np.array_equal(np.asarray(level), truth)
