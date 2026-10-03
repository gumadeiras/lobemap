"""An image seen in a turned 2D view: its levels, resampled when napari reads them.

napari slices an image only along its voxel grid. A view turned across that
grid shows a plane oblique to it, so the image layer is handed, for as long
as the view is turned, a lazy volume in the turned world instead of its own
(`TurnedImage`): axis-aligned with napari's world, it is sliced as any image
is -- at the pyramid level napari picks for the canvas, over the region the
canvas shows -- and each plane napari asks for is sampled from the image's
own levels there. The layer, its controls and its place in the list are the
image's own; only its data and translate change, and come back at rest and
in 3D (`viewer.turned`).

- **Geometry.** The turned volume keeps the layer's affine (the mirror) and
  its scale in plane; along the slider its planes are one slider step
  apart and its translate puts them exactly on the slider's positions, so
  the image and the contours are cut on one plane. Each of its voxels is
  sampled at the specimen point it shows: through the turn, the mirror and
  the layer's scale and translate, onto a level's own voxel centers -- a
  level built by block means is centered `(f - 1) / 2` voxels in
  (`core.zarrfmt`), which napari's own display of a level does not account
  for.
- **Levels.** In plane they step by the square root of two, not two, so napari,
  which reads the coarsest level holding a voxel per screen pixel, reads at
  most about twice the canvas's pixels rather than four times. Each samples
  the finest level of the image no coarser than itself. Along the slider
  axis no level is coarser, so every level holds every plane.
- **Sampling.** Stains trilinearly, label volumes by nearest voxel, in the
  image's own data type. An image in memory is sampled whole, in bands of
  rows side by side; a chunked one tile by tile, each tile from the box of
  voxels it needs, read through the chunk cache and kept, with a margin, for
  the next step: a step moves the plane a voxel, and a box that still holds
  what its tile needs is not read again (`Tiles`). A tile is long where the
  plane runs level through the image and short where it climbs, so its box
  -- what is copied, and the chunks it reads -- stays thin (`tile_shape`).
"""

from __future__ import annotations

import threading
from collections import OrderedDict
from concurrent.futures import ThreadPoolExecutor

import numpy as np

#: Turned pixels per tile, each way: also the chunks napari is told the
#: turned volume has, so a pan reads whole tiles.
TILE = 128

#: Voxels a tile's box is read past what the tile needs, each way.
PAD = 4

#: Bytes of tile boxes kept for the next step, per image.
BOX_BYTES = 128 * 2**20

#: Bytes of sampled tiles kept, per image: a plane seen again, or panned
#: back to, is not sampled again.
SAMPLE_BYTES = 96 * 2**20

#: In-plane step between the turned levels.
LEVEL_STEP = np.sqrt(2.0)

_POOL: ThreadPoolExecutor | None = None
_POOL_LOCK = threading.Lock()


def _pool() -> ThreadPoolExecutor:
    global _POOL
    with _POOL_LOCK:
        if _POOL is None:
            from .chunkcache import WORKERS

            _POOL = ThreadPoolExecutor(max_workers=WORKERS,
                                       thread_name_prefix="lobemap-resample")
        return _POOL


def level_geometry(levels) -> list[tuple[np.ndarray, np.ndarray]]:
    """(factor, first center) of each level, per axis, in level-0 voxels.

    A pyramid `core.zarrfmt` wrote halves each axis by block means, so a
    level whose factor is `f` has its first voxel centered `(f - 1) / 2`
    in. Any other pyramid is placed as napari places it: voxel `j` of a
    level at `j * f`, where `f` is the ratio of the shapes.
    """
    from ..core.zarrfmt import pyramid_levels

    shapes = [tuple(int(n) for n in level.shape) for level in levels]
    written = pyramid_levels(shapes[0])
    if [s for s, _f in written[:len(shapes)]] == shapes and len(written) >= len(shapes):
        out = []
        for _shape, factors in written[:len(shapes)]:
            f = np.asarray(factors, float)
            out.append((f, (f - 1.0) / 2.0))
        return out
    base = np.asarray(shapes[0], float)
    return [(base / np.asarray(s, float), np.zeros(len(s))) for s in shapes]


class Kept:
    """Arrays by key, least recently used out, within a byte budget.

    Thread-safe; shared by every level of one image, so the budget is the
    image's.
    """

    def __init__(self, max_bytes: int) -> None:
        self.max_bytes = int(max_bytes)
        self.nbytes = 0
        self._items: OrderedDict = OrderedDict()
        self._lock = threading.Lock()

    def get(self, key, holds=None):
        """The value kept under `key`, if `holds(value)` -- or None."""
        with self._lock:
            hit = self._items.get(key)
            if hit is None or (holds is not None and not holds(hit)):
                return None
            self._items.move_to_end(key)
            return hit

    def put(self, key, value, nbytes: int) -> None:
        with self._lock:
            old = self._items.pop(key, None)
            if old is not None:
                self.nbytes -= _bytes(old)
            self._items[key] = value
            self.nbytes += int(nbytes)
            while self.nbytes > self.max_bytes and len(self._items) > 1:
                _key, gone = self._items.popitem(last=False)
                self.nbytes -= _bytes(gone)


def _bytes(value) -> int:
    return int(value.nbytes if isinstance(value, np.ndarray) else value[2].nbytes)


class Tiles:
    """Tiles of samples of one source level, at affine positions.

    `source` is an array in memory or a `chunkcache.CachedLevel`; `order`
    is 1 for trilinear, 0 for the nearest voxel; `boxes` keeps the voxels
    each tile read (`Kept`). Thread-safe: tiles are sampled side by side,
    for napari's reads on the UI thread.
    """

    def __init__(self, source, order: int, dtype, boxes: Kept) -> None:
        self.source = source
        self.order = int(order)
        self.dtype = np.dtype(dtype)
        self._boxes = boxes

    def shape(self, du, dv) -> tuple[int, int]:
        """(rows, columns) of the tiles a plane with these steps is cut in."""
        chunks = getattr(self.source, "chunks", None)
        if not isinstance(chunks, tuple) or not all(isinstance(c, int) for c in chunks):
            return (TILE, TILE)                 # in memory: no box to keep thin
        return tile_shape(du, dv, chunks)

    def tile(self, origin, du, dv, shape, key) -> np.ndarray:
        """(h, w) samples at `origin + i du + j dv`, in the source's voxels.

        `key` names the tile on its turned level, so it keeps its box --
        the voxels it reads, with a margin -- from one step to the next.
        """
        from .chunkcache import CachedLevel

        h, w = (int(n) for n in shape)
        out = np.zeros((h, w), self.dtype)
        origin, du, dv = (np.asarray(v, float) for v in (origin, du, dv))
        source = self.source
        if not isinstance(source, CachedLevel):
            self._sample(np.asarray(source), origin, du, dv, out)
            return out
        size = np.asarray(source.shape)
        ends = np.array([origin + a * du + b * dv for a in (0, h - 1) for b in (0, w - 1)])
        lo = np.maximum(np.floor(ends.min(axis=0)).astype(int), 0)
        hi = np.minimum(np.floor(ends.max(axis=0)).astype(int) + 2, size)
        if np.any(hi <= lo):
            return out
        box_lo, box = self._box(source, key, lo, hi)
        self._sample(box, origin - box_lo, du, dv, out)
        return out

    def _sample(self, volume, origin, du, dv, out) -> None:
        from scipy.ndimage import affine_transform

        matrix = np.zeros((3, 4))
        matrix[:, 0], matrix[:, 1], matrix[:, 3] = du, dv, origin
        affine_transform(volume, matrix, output_shape=out.shape + (1,),
                         output=out.reshape(out.shape + (1,)), order=self.order,
                         mode="constant", cval=0, prefilter=False)

    def _box(self, source, key, lo, hi):
        """The voxels [lo, hi) of the source, from a kept box when one holds them."""
        kept = self._boxes.get((id(source), key),
                               lambda k: np.all(k[0] <= lo) and np.all(k[1] >= hi))
        if kept is not None:
            return kept[0], kept[2]
        size = np.asarray(source.shape)
        lo, hi = np.maximum(lo - PAD, 0), np.minimum(hi + PAD, size)
        box = source._read(lo, hi)
        self._boxes.put((id(source), key), (lo, hi, box), box.nbytes)
        return lo, box


#: What reading one chunk's part of a box costs, in voxels copied: the
#: Python around each piece of a box (`chunkcache.CachedLevel._read`).
CELL_COST = 150_000


def tile_shape(du, dv, chunks=(64, 64, 64)) -> tuple[int, int]:
    """(rows, columns) of the tiles a plane is sampled in: the shape whose
    boxes of source voxels are cheapest to read, per pixel.

    A tile `h` by `w` needs `|du| h + |dv| w + 2` voxels along each source
    axis, read from as many chunks as that box crosses. A square tile on a
    plane tilted 37 degrees needs a box a third as deep as it is wide, and
    one long where the plane runs level, a few voxels -- but crosses more
    chunks, each of which costs a copy of its own.
    """
    du, dv = np.abs(np.asarray(du, float)), np.abs(np.asarray(dv, float))
    chunks = np.asarray(chunks, float)
    best, cost = (TILE, TILE), np.inf
    for rows in (16, 32, 64, 128, 256, 512, 1024):
        for cols in (16, 32, 64, 128, 256, 512, 1024):
            if not 8192 <= rows * cols <= 65536:
                continue
            extent = du * rows + dv * cols + 2.0
            cells = np.prod(np.ceil(extent / chunks) + 1.0)
            got = (np.prod(extent) + CELL_COST * cells) / (rows * cols)
            if got < cost:
                best, cost = (rows, cols), got
    return best


class TurnedLevel:
    """One level of a `TurnedImage`, read a plane at a time.

    Indexing with slices alone returns another lazy view, as dask does:
    napari first cuts the displayed region and only then picks the plane.
    An integer, or `np.asarray`, samples.
    """

    def __init__(self, image: TurnedImage, level: int, shape, box=None) -> None:
        self._image = image
        self._level = level
        full = tuple((0, int(n)) for n in shape)
        self._box = full if box is None else box
        self.shape = tuple(b - a for a, b in self._box)
        self.dtype = image.dtype
        self.chunks = (TILE,) * len(self.shape)

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
        return f"TurnedLevel(level={self._level}, shape={self.shape}, dtype={self.dtype})"

    def __array__(self, dtype=None, copy=None):
        lo, hi = (np.array(v) for v in zip(*self._box, strict=True))
        out = self._image.read(self._level, lo, hi)
        return out if dtype is None else out.astype(dtype, copy=False)

    def __getitem__(self, key):
        from .chunkcache import _box

        box = _box(key, self.shape)
        if box is None:
            return np.asarray(self)[key]
        origin = [a for a, _ in self._box]
        if all(not is_int and step == 1 for _, _, step, is_int in box):
            return TurnedLevel(self._image, self._level, self.shape, tuple(
                (o + start, o + stop) for o, (start, stop, _, _) in zip(origin, box, strict=True)))
        lo = np.array([o + b[0] for o, b in zip(origin, box, strict=True)])
        hi = np.array([o + b[1] for o, b in zip(origin, box, strict=True)])
        block = self._image.read(self._level, lo, hi)
        return block[tuple(0 if b[3] else slice(None, None, b[2]) for b in box)]


class TurnedImage:
    """An image layer's data in a turned 2D view: its turned levels, and translate.

    `sources` are the layer's own levels, the list sampled from, which a 3D
    level read in the background can be swapped into (`images.FineLevel`).
    `scale` and `translate` are the layer's, `mirror` its affine at rest,
    `turn` the view's (`rotation.Turn`), `order` the 2D `dims.order`, and
    `position` the slice position in the layer's data before the mirror,
    which the turned planes are put on, one per `step`. The layer is handed
    `data`, `translate` and `scale`.
    """

    def __init__(self, sources, multiscale: bool, scale, translate, mirror, turn,
                 order, position: float, step: float, labels: bool) -> None:
        self.sources = sources
        self.multiscale = bool(multiscale)
        self.order = 0 if labels else 1
        first = sources[0]
        self.dtype = np.dtype(first.dtype)
        self.axis, self.rows, self.cols = (int(a) for a in order)
        scale = np.asarray(scale, float)
        translate = np.asarray(translate, float)
        grid = scale.copy()
        grid[self.axis] = float(step)
        #: The turned volume's voxel size: the layer's, and the slider's step.
        self.scale = grid
        mirror = np.asarray(mirror, float)
        # q = G p: the turn in the layer's pre-mirror coordinates.
        g = np.linalg.inv(mirror) @ turn.affine() @ mirror
        self._g_inverse = np.linalg.inv(g)
        self._scale, self._source_translate = scale, translate
        shape = np.asarray(first.shape)
        corners = np.array([[(n - 1) * bit for n, bit in zip(shape, bits, strict=True)]
                            for bits in np.ndindex(2, 2, 2)], float)
        turned = (np.c_[translate + corners * scale, np.ones(8)] @ g.T)[:, :3]
        lo, hi = turned.min(axis=0), turned.max(axis=0)
        origin = np.floor(lo / grid) * grid
        a = self.axis
        origin[a] = position - np.ceil((position - lo[a]) / grid[a] - 1e-9) * grid[a]
        top = np.maximum(hi, origin)
        self.translate = origin
        size = np.floor((top - origin) / grid + 1e-9).astype(int) + 1
        self.geometry = level_geometry(sources) if self.multiscale else [
            (np.ones(3), np.zeros(3))]
        self._tiles: dict[int, Tiles] = {}
        #: The voxels each tile read, and the tiles sampled, by (level,
        #: plane, row, column).
        self._boxes = Kept(BOX_BYTES)
        self._kept = Kept(SAMPLE_BYTES)
        self._shapes, self._uses = self._pyramid(size)
        self.levels = [TurnedLevel(self, k, s) for k, s in enumerate(self._shapes)]

    @property
    def data(self):
        """What the layer is handed: its levels, or its one level."""
        return self.levels if self.multiscale else self.levels[0]

    def _pyramid(self, size) -> tuple[list[tuple], list[int]]:
        """The turned levels' shapes, and the source level each samples."""
        if not self.multiscale:
            return [tuple(int(n) for n in size)], [0]
        shown = [self.rows, self.cols]
        coarsest = float(self.geometry[-1][0][shown].min())
        shapes, uses, k = [], [], 0
        while True:
            factor = LEVEL_STEP ** k
            if factor > coarsest * (1 + 1e-9) and shapes:
                break
            shape = np.asarray(size).copy()
            shape[shown] = np.maximum(1, np.ceil(size[shown] / factor).astype(int))
            if shapes and tuple(shape) == shapes[-1]:
                break
            shapes.append(tuple(int(n) for n in shape))
            # The finest source level no coarser than this one, in plane.
            uses.append(max(i for i, (f, _c) in enumerate(self.geometry)
                            if f[shown].max() <= factor * (1 + 1e-9)))
            k += 1
        return shapes, uses

    def _tiles_of(self, k: int) -> Tiles:
        use = self._uses[k]
        tiles = self._tiles.get(use)
        if tiles is None or tiles.source is not self.sources[use]:
            tiles = self._tiles[use] = Tiles(self.sources[use], self.order, self.dtype,
                                             self._boxes)
        return tiles

    def to_source(self, k: int):
        """(P, p0): source-level voxel `P @ j + p0` for turned voxel `j` of level `k`."""
        d = np.asarray(self._shapes[0], float) / np.asarray(self._shapes[k], float)
        f, center = self.geometry[self._uses[k]]
        # j -> turned level-0 voxel -> q -> pre-mirror point -> source voxel.
        linear = np.diag(self.scale * d)
        g = self._g_inverse
        p_linear = g[:3, :3] @ linear
        p0 = g[:3, :3] @ self.translate + g[:3, 3]
        to_voxel = 1.0 / (self._scale * f)
        P = (p_linear * to_voxel[:, None])
        b = (p0 - self._source_translate) / self._scale
        return P, (b - center) / f

    def read(self, k: int, lo, hi) -> np.ndarray:
        """The box [lo, hi) of turned level `k`.

        Plane by plane, from whole tiles of the level -- sampled side by
        side, and kept: a pan, or a plane seen again, reads them from memory.
        """
        lo, hi = np.asarray(lo, int), np.asarray(hi, int)
        out = np.zeros(tuple(np.maximum(hi - lo, 0)), self.dtype)
        if out.size == 0:
            return out
        P, p0 = self.to_source(k)
        tiles = self._tiles_of(k)
        a, r, c = self.axis, self.rows, self.cols
        du, dv = P[:, r], P[:, c]
        rows, cols = tiles.shape(du, dv)
        level = self._shapes[k]
        view = np.moveaxis(out, (a, r, c), (0, 1, 2))
        for n, plane in enumerate(range(lo[a], hi[a])):
            spans = [(ti, tj) for ti in range(lo[r] // rows, (hi[r] - 1) // rows + 1)
                     for tj in range(lo[c] // cols, (hi[c] - 1) // cols + 1)]

            def one(span, plane=plane):
                ti, tj = span
                key = (k, plane, ti, tj)
                hit = self._kept.get(key)
                if hit is None:
                    i0, j0 = ti * rows, tj * cols
                    shape = (min(rows, level[r] - i0), min(cols, level[c] - j0))
                    j = np.zeros(3)
                    j[a], j[r], j[c] = plane, i0, j0
                    hit = tiles.tile(P @ j + p0, du, dv, shape, (k, ti, tj))
                    self._kept.put(key, hit, hit.nbytes)
                return span, hit

            for (ti, tj), tile in _pool().map(one, spans):
                i0, j0 = ti * rows, tj * cols
                si = slice(max(lo[r], i0), min(hi[r], i0 + tile.shape[0]))
                sj = slice(max(lo[c], j0), min(hi[c], j0 + tile.shape[1]))
                view[n, si.start - lo[r]:si.stop - lo[r], sj.start - lo[c]:sj.stop - lo[c]] = \
                    tile[si.start - i0:si.stop - i0, sj.start - j0:sj.stop - j0]
        return out

    @property
    def nbytes(self) -> int:
        """Bytes this keeps: the tile boxes, and the tiles sampled."""
        return self._boxes.nbytes + self._kept.nbytes


__all__ = [
    "BOX_BYTES",
    "CELL_COST",
    "LEVEL_STEP",
    "PAD",
    "SAMPLE_BYTES",
    "TILE",
    "Kept",
    "Tiles",
    "TurnedImage",
    "TurnedLevel",
    "level_geometry",
    "tile_shape",
]
