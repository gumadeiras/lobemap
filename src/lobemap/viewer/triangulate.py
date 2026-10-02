"""A ring's outline and fill as triangles, as napari's Shapes draws them.

`stroke` gives the triangles of a closed ring drawn some width wide, and
`fill` the triangles covering its inside exactly. Both use bermuda, the
compiled triangulation napari's Shapes uses, and fall back to napari's own
where bermuda is missing, fails or panics. `contours` draws with them.
"""

from __future__ import annotations

import numpy as np

from . import napari_private

#: napari's miter limit for a path's joins: past it a join is beveled.
MITER_LIMIT = 3.0


def stroke(ring: np.ndarray, width: float) -> tuple[np.ndarray, np.ndarray]:
    """Triangles drawing a closed ring `width` wide, exactly as napari strokes one.

    The same call napari's Shapes makes for every path it draws, so joins,
    bevels and width are napari's own; the ring is closed, so its first
    point is joined like any other instead of meeting itself in two butt
    ends.
    """
    ring = np.ascontiguousarray(ring, dtype=np.float32)
    made = _bermuda("triangulate_path_edge", ring, closed=True, limit=MITER_LIMIT)
    centers, offsets, triangles = (napari_private.triangulate_edge(ring) if made is None
                                   else made)
    return centers + width * offsets, np.asarray(triangles, dtype=np.int64)


def _bermuda(name: str, *args, **kwargs):
    """bermuda's `name(*args, **kwargs)`, or None where it is missing or fails.

    bermuda is Rust, and on a few rings it panics -- "Segment not found in
    interval" for the male CNS `LA(L)` cut at y = 198 um -- which pyo3
    raises as a PanicException: a BaseException, so no `except Exception`
    sees it, and one that escaped the prefetch would end its thread. napari's
    own triangulation stands in.
    """
    try:
        import bermuda

        return getattr(bermuda, name)(*args, **kwargs)
    except Exception:  # noqa: BLE001 - missing, or failed on these points
        return None
    except BaseException as exc:
        if type(exc).__name__ != "PanicException":
            raise
        return None


def _rotation(degrees: float) -> np.ndarray:
    t = np.radians(degrees)
    return np.array([[np.cos(t), -np.sin(t)], [np.sin(t), np.cos(t)]])


#: The symmetries of the square, which move no float32 point off its value.
_SQUARE = [np.reshape(m, (2, 2)).astype(float) for m in (
    (1, 0, 0, 1), (0, 1, 1, 0), (1, 0, 0, -1), (-1, 0, 0, 1),
    (-1, 0, 0, -1), (0, 1, -1, 0), (0, -1, 1, 0), (0, -1, -1, 0))]

#: Each way a ring is turned for bermuda, in order, until one is filled
#: exactly: the symmetries of the square, then rotations about its mean.
_TURNS = _SQUARE + [_rotation(a) for a in (7, 17, 29, 41, 53, 67, 79, 97, 113, 131)]


def fill(ring: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """Triangles covering the inside of a simple closed ring, exactly.

    A fan from the ring's centroid when every fan triangle turns the same
    way: the ring is then star-shaped about that point, and the fan tiles
    its inside with no overlap and no gap. Most sections are, and the fan
    is one array operation. Otherwise the triangulation napari's Shapes
    uses for a polygon, bermuda's -- checked, since bermuda overlaps
    triangles in some rings: about 3% of the glomerulus sections that are
    not star-shaped, covering up to 2.5% more than the ring, and 6% of the
    neuropil ones, up to 18%. A fill at `contours.FILL_ALPHA` shows each
    overlap darker. Where it overlaps moves with the order its sweep meets
    the points in, so the ring is given to it turned (`_TURNS`) until a
    turn covers it. Of the 90,479 sections that are not star-shaped when every
    shipped mesh is cut every 0.5 um along each axis, the ring as it is and
    two turns of it left 134 to napari's own pure-Python triangulation,
    exact but 75-560 ms a ring, on the UI thread when a step reached the
    plane before the prefetch. All the turns leave none, there or on the
    planes halfway between.

    A ring that crosses or touches itself -- bermuda puts a point where it
    crosses, as the ring is or reflected, or a point repeats -- has no
    fill covering exactly what it encloses, and napari's covers what
    bermuda's does: bermuda's own is kept, as napari's Shapes draws it.
    Only a simple ring no turn covers is left to napari, and a ring
    bermuda cannot triangulate at all.
    """
    ring = np.asarray(ring, dtype=np.float64)
    nxt = np.roll(ring, -1, axis=0)
    cross = ring[:, 0] * nxt[:, 1] - ring[:, 1] * nxt[:, 0]
    area = cross.sum() / 2.0
    if area != 0.0:
        center = ((ring + nxt) * cross[:, None]).sum(axis=0) / (6.0 * area)
        a, b = ring - center, nxt - center
        turn = a[:, 0] * b[:, 1] - a[:, 1] * b[:, 0]
        if np.all(turn * np.sign(area) >= 0.0):
            n = len(ring)
            idx = np.arange(1, n + 1)
            faces = np.column_stack((np.zeros(n, np.int64), idx, np.roll(idx, -1)))
            return np.vstack((center[None, :], ring)), faces
    ring32 = np.ascontiguousarray(ring, dtype=np.float32)
    first, crosses = None, False
    for k, turn in enumerate(_TURNS):
        about = ring.mean(axis=0) if k >= len(_SQUARE) else np.zeros(2)
        turned = np.ascontiguousarray((ring32 - about) @ turn.T, dtype=np.float32)
        made = _bermuda("triangulate_polygons_face", [turned])
        if made is None:
            continue
        triangles, points = np.asarray(made[0], np.int64), np.asarray(made[1], np.float32)
        if first is None:               # bermuda's, as napari's Shapes draws it
            first = points.astype(np.float64) @ turn + about, triangles
        triangles = _ring_index(turned, points, triangles)
        if triangles is None:
            # A point where the ring crosses itself; a rotated ring can
            # only seem to, from rounding.
            crosses = k < len(_SQUARE)
            if crosses:
                break
            continue
        if _covers(ring32.astype(np.float64), triangles, ring32):
            return ring32.astype(np.float64), triangles
    if first is not None and (crosses or len(np.unique(ring32, axis=0)) < len(ring32)):
        return first
    try:
        points, triangles = napari_private.triangulate_face(ring32)
    except Exception:
        if first is None:
            raise
        return first
    made = np.asarray(points, dtype=np.float64), np.asarray(triangles, dtype=np.int64)
    return made if first is None or _covers(*made, ring32) else first


def _ring_index(given: np.ndarray, points: np.ndarray, triangles: np.ndarray):
    """bermuda's triangles, which index the `points` it made, as indices into
    the ring it was `given`; None if it made a point the ring does not have.

    Points are matched by their float32 bits, with -0 as 0.
    """
    keys = (given + np.float32(0)).view(np.uint64).ravel()
    order = np.argsort(keys)
    ranked = keys[order]
    used = np.unique(triangles)
    want = (points[used] + np.float32(0)).view(np.uint64).ravel()
    at = np.minimum(np.searchsorted(ranked, want), len(ranked) - 1)
    if not np.array_equal(ranked[at], want):
        return None
    index = np.zeros(len(points), np.int64)
    index[used] = order[at]
    return index[triangles]


def _covers(points: np.ndarray, triangles: np.ndarray, ring: np.ndarray) -> bool:
    """Whether the triangles cover exactly the area inside `ring`: none overlap.

    Areas are taken about the ring's first point, so coordinates far from
    the origin cancel nothing away.
    """
    origin = ring[0].astype(np.float64)
    r = ring.astype(np.float64) - origin
    want = abs(float(np.dot(r[:, 0], np.roll(r[:, 1], -1))
                     - np.dot(r[:, 1], np.roll(r[:, 0], -1)))) / 2.0
    p = points - origin
    a, b, c = (p[triangles[:, k]] for k in range(3))
    got = float(np.abs((b[:, 0] - a[:, 0]) * (c[:, 1] - a[:, 1])
                       - (b[:, 1] - a[:, 1]) * (c[:, 0] - a[:, 0])).sum()) / 2.0
    return abs(got - want) <= 1e-6 * want + 1e-12
