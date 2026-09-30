"""Exact sections of meshes by axis-aligned planes: the loops 2D draws.

`MeshSections` cuts every compartment of a MeshSet at once and hands back
closed polylines, the same ones `trimesh.Trimesh.section` gives; see its
docstring and `tests/test_contour_sections.py` for what "the same" means.
`viewer.contours` draws them.
"""

from __future__ import annotations

from collections import OrderedDict

import numpy as np

from ..core.meshfmt import MeshSet

#: A vertex this close to the plane counts as lying ON it. The value is
#: trimesh's `tol.merge`, which `trimesh.Trimesh.section` applies, so every
#: face is classified the way the sections drawn before this module computed
#: its own were classified.
ON_PLANE_TOL = 1e-8

#: Contour edges shorter than this are merged away; see `_drawable`. A
#: contour line is drawn 0.35 um wide, 3500 times this.
MIN_EDGE_UM = 1e-4

#: Planes whose sections an overlay keeps, so revisiting one costs no
#: geometry. One plane of every compartment is 26-300 KB across the shipped
#: meshes, so this holds at most about 40 MB per overlay, and only an
#: overlay that has been drawn holds any.
SECTION_CACHE_PLANES = 128


class MeshSections:
    """Exact sections of every compartment of a MeshSet by axis-aligned planes.

    One slice step used to call `trimesh.Trimesh.section` once per
    compartment. That is 18-28 calls per plane, and most of each went on
    building a general `Path3D` -- merging vertices, a graph traversal, a
    KD-tree -- to recover loops the mesh topology already defines. That was
    26 ms of a 37 ms step in FAFB14 and about 100 ms in GRABE.

    This does the whole atlas at once, in array operations:

    - Only the compartments whose bounds hold the plane are looked at, and
      their faces are culled by their extent along the sliced axis, kept
      per axis.
    - Each remaining face is classified exactly as trimesh classifies it --
      two vertices on one side and one on the other, a vertex on the plane
      between the other two, or an edge on the plane -- and yields the same
      segment.
    - A segment ends on a mesh edge or a mesh vertex, and it is joined to
      its neighbors by THAT identity, not by rounding coordinates. Two faces
      sharing an edge therefore share the point exactly. On a closed
      manifold every such point has two segments, and walking them gives
      each loop directly: every compartment's in one graph search
      (`_loops`), and every loop's too-close points dropped in one pass
      (`_drawable`). Done per compartment, in Python, those two were most
      of a plane's time.

    A compartment whose segments are not a set of simple loops -- an open
    or non-manifold mesh -- is handed to `trimesh` for that plane instead,
    so its output is what it always was, closed loops only. Across the six
    shipped atlases and three neuropil sets that is one compartment in
    about 19,000 cut on 120 planes each.

    Elsewhere the loops are trimesh's to within 2e-4 um -- its own 1e-5 um
    vertex merge, and the points closer than MIN_EDGE_UM that `_drawable`
    drops -- apart from where each starts and which way it runs
    (`tests/test_contour_sections.py`).
    One case differs on purpose: at a mesh seam, where distinct vertices
    share a position, trimesh's merging joined two loops into a figure eight
    and drew part of it twice.

    Sections are cached per plane, for every compartment rather than only
    the selected ones, so a change of selection, label or fill redraws from
    the cache without touching geometry.
    """

    def __init__(self, meshset: MeshSet, max_planes: int = SECTION_CACHE_PLANES) -> None:
        self.meshset = meshset
        self.max_planes = max_planes
        self._offsets = np.asarray(meshset.face_offsets)
        self._per_axis: dict[int, tuple] = {}
        self._planes: OrderedDict[tuple[int, float], dict[int, list[np.ndarray]]] = (
            OrderedDict()
        )

    def at(self, axis: int, position: float) -> dict[int, list[np.ndarray]]:
        """Compartment index -> closed polylines, for the plane x[axis] = position."""
        key = (int(axis), float(position))
        hit = self._planes.get(key)
        if hit is not None:
            self._planes.move_to_end(key)
            return hit
        out = self._compute(*key)
        self._planes[key] = out
        while len(self._planes) > self.max_planes:
            self._planes.popitem(last=False)
        return out

    # -- geometry --------------------------------------------------------

    def _extent(self, axis: int):
        """Per-face and per-compartment (min, max) along one axis."""
        if axis not in self._per_axis:
            coord = self.meshset.vertices[:, axis][self.meshset.faces]
            fmin, fmax = coord.min(axis=1), coord.max(axis=1)
            offsets = self._offsets
            k = self.meshset.n_compartments
            lo = np.full(k, np.inf)
            hi = np.full(k, -np.inf)
            filled = np.flatnonzero(np.diff(offsets) > 0)
            if len(filled):
                starts = offsets[filled]
                lo[filled] = np.minimum.reduceat(fmin, starts)
                hi[filled] = np.maximum.reduceat(fmax, starts)
            self._per_axis[axis] = (fmin, fmax, lo, hi)
        return self._per_axis[axis]

    def _compute(self, axis: int, p: float) -> dict[int, list[np.ndarray]]:
        fmin, fmax, lo, hi = self._extent(axis)
        # A compartment is sectioned only when the plane is inside its
        # bounds, as `contours_at` always required, so only its faces are
        # looked at: a plane crosses a fraction of an atlas.
        offsets = self._offsets
        near, owner = [], []
        for index in np.flatnonzero((lo <= p) & (p <= hi)).tolist():
            a, b = offsets[index], offsets[index + 1]
            hit = np.flatnonzero((fmin[a:b] <= p + ON_PLANE_TOL)
                                 & (fmax[a:b] >= p - ON_PLANE_TOL))
            near.append(hit + a)
            owner.append(np.full(len(hit), index))
        if not near:
            return {}
        near, owner = np.concatenate(near), np.concatenate(owner)
        if not len(near):
            return {}
        vertices = self.meshset.vertices
        # int64: an edge key is a product of two vertex ids.
        faces = self.meshset.faces[near].astype(np.int64)
        dist = vertices[:, axis][faces].astype(np.float64) - p
        sign = np.zeros(dist.shape, dtype=np.int8)
        sign[dist < -ON_PLANE_TOL] = -1
        sign[dist > ON_PLANE_TOL] = 1
        above = (sign > 0).sum(axis=1)
        below = (sign < 0).sum(axis=1)
        on = 3 - above - below
        n = len(vertices)
        rows, ends = [], []

        # Two vertices on one side, one on the other: the segment joins the
        # two edges leaving the lone vertex.
        basic = np.flatnonzero((on == 0) & (above > 0) & (below > 0))
        if len(basic):
            s = sign[basic]
            lone = np.argmax(s == np.where(s.sum(axis=1) > 0, -1, 1)[:, None], axis=1)
            a, b, c = _rolled(faces[basic], lone)
            rows.append(basic)
            ends.append(np.column_stack((_edge_key(a, b, n), _edge_key(a, c, n))))
        # A vertex on the plane between the other two: from that vertex to
        # the edge opposite it.
        through = np.flatnonzero((on == 1) & (above == 1) & (below == 1))
        if len(through):
            zero = np.argmax(sign[through] == 0, axis=1)
            a, b, c = _rolled(faces[through], zero)
            rows.append(through)
            ends.append(np.column_stack((a, _edge_key(b, c, n))))
        # An edge on the plane. Only the face whose third vertex is above
        # contributes it, so the two faces sharing it do not draw it twice;
        # this is trimesh's rule too.
        edge = np.flatnonzero((on == 2) & (above == 1))
        if len(edge):
            off = np.argmax(sign[edge] != 0, axis=1)
            _a, b, c = _rolled(faces[edge], off)
            rows.append(edge)
            ends.append(np.column_stack((b, c)))
        if not rows:
            return {}

        rows = np.concatenate(rows)
        keys, nodes = np.unique(np.concatenate(ends).ravel(), return_inverse=True)
        points = _node_points(vertices, keys, axis, p, n)
        walk, lengths, loop_owners, handed_back = _loops(
            nodes.reshape(-1, 2), owner[rows], len(keys))
        rings, closed = points[walk], np.ones(len(lengths), dtype=bool)
        if len(handed_back):
            # Their loops join the others, so the whole plane is cleaned at
            # once and each compartment keeps its place in the order.
            extra = [(index, loop) for index in handed_back.tolist()
                     for loop in self._trimesh_section(index, axis, p)]
            shut = np.array([len(loop) > 1 and np.array_equal(loop[0], loop[-1])
                             for _index, loop in extra], dtype=bool)
            rings = np.vstack([rings] + [loop[:-1] if c else loop
                                         for (_i, loop), c in zip(extra, shut, strict=True)])
            lengths = np.concatenate((lengths, [len(loop) - c for (_i, loop), c
                                                in zip(extra, shut, strict=True)]))
            loop_owners = np.concatenate((loop_owners, [i for i, _loop in extra]))
            closed = np.concatenate((closed, shut))
        out: dict[int, list[np.ndarray]] = {}
        for index, loop in _drawable(rings, lengths, closed, loop_owners):
            out.setdefault(index, []).append(loop)
        return out

    def _trimesh_section(self, index: int, axis: int, p: float) -> list[np.ndarray]:
        """What every compartment used to get: trimesh's section, closed loops only.

        `Path3D.discrete` leaves out open curves, so a section with loose
        ends has always drawn only its loops.
        """
        import trimesh

        v, f = self.meshset.compartment(index)
        origin = np.zeros(3)
        origin[axis] = p
        normal = np.zeros(3)
        normal[axis] = 1.0
        try:
            mesh = trimesh.Trimesh(vertices=v, faces=f, process=False)
            section = mesh.section(plane_origin=origin, plane_normal=normal)
        except Exception:  # noqa: BLE001 - a tangent plane degenerates
            return []
        if section is None:
            return []
        out = []
        for poly in section.discrete:
            if len(poly) < 2:
                continue
            pts = np.asarray(poly, dtype=float)
            pts[:, axis] = p
            out.append(pts)
        return out


def _rolled(faces: np.ndarray, first: np.ndarray):
    """The three vertex columns of each face, starting at column `first`."""
    r = np.arange(len(faces))
    return faces[r, first], faces[r, (first + 1) % 3], faces[r, (first + 2) % 3]


def _edge_key(a: np.ndarray, b: np.ndarray, n: int) -> np.ndarray:
    """One integer per undirected mesh edge, above every vertex id."""
    return n + np.minimum(a, b) * n + np.maximum(a, b)


def _node_points(vertices, keys, axis: int, p: float, n: int) -> np.ndarray:
    """Coordinates of each segment end: a vertex, or where an edge crosses.

    Each crossing is computed once, from the edge in a fixed direction, so
    every face that ends a segment on that edge ends it at the same point.
    """
    points = np.empty((len(keys), 3))
    is_vertex = keys < n
    points[is_vertex] = vertices[keys[is_vertex]]
    edge = keys[~is_vertex] - n
    u = vertices[edge // n].astype(np.float64)
    w = vertices[edge % n].astype(np.float64)
    t = (p - u[:, axis]) / (w[:, axis] - u[:, axis])
    points[~is_vertex] = u + t[:, None] * (w - u)
    # Exactly on the plane, so napari shows them on this slice.
    points[:, axis] = p
    return points


def _drawable(rings: np.ndarray, lengths: np.ndarray, closed: np.ndarray,
              owners: np.ndarray) -> list[tuple[int, np.ndarray]]:
    """(compartment, loop) for each loop left after dropping the points no one
    can tell apart, in compartment order.

    `rings` holds every loop's points end to end, `lengths` how many each
    has, without the repeated first point of a `closed` one. Each loop
    comes back as a polyline, closed ones repeating their first point.

    Two kinds of point go:

    - Points within MIN_EDGE_UM of the point kept before them. GRABE's
      slider steps fall on its vertex grid, so a vertex a hair off the plane
      sends every edge around it through the plane at nearly one point: 13%
      of its contour edges were shorter than 1e-3 um. Invisible, but each
      is a vertex napari triangulates on every step: dropping them cuts the
      triangulation of a filled GRABE slice by a sixth.
    - Points float32 cannot tell from the one before, which napari stores
      and MIN_EDGE_UM may not cover above 1024 um. The zero-length edge
      they make stops napari's pure-Python fill: where it closes the loop,
      `KeyError: (0, 0)`.

    Every point dropped is within MIN_EDGE_UM of one kept. A loop left with
    fewer than three points, too small to see, is dropped with them. Every
    rule that looks back to an earlier point stops at a loop's first point,
    which is always kept, so all loops are cleaned at once.
    """
    if not len(lengths):
        return []
    starts = np.concatenate(([0], np.cumsum(lengths)[:-1])).astype(int)
    which = np.repeat(np.arange(len(lengths)), lengths)
    first = np.zeros(len(rings), dtype=bool)
    first[starts[lengths > 0]] = True

    keep = first.copy()
    keep[1:] |= np.linalg.norm(np.diff(rings, axis=0), axis=1) >= MIN_EDGE_UM
    if not keep.all():
        # A run of short edges can wander; keep whatever strays from the
        # point that heads the run.
        head = np.maximum.accumulate(np.where(keep, np.arange(len(rings)), 0))
        keep |= np.linalg.norm(rings - rings[head], axis=1) >= MIN_EDGE_UM
    kept = np.flatnonzero(keep)
    f32 = rings[kept].astype(np.float32)
    distinct = first[kept]
    distinct[1:] |= np.any(f32[1:] != f32[:-1], axis=1)
    kept, f32 = kept[distinct], f32[distinct]
    # A closed loop also loses the points at its end that come back to its
    # first, but never the first itself.
    of = which[kept]
    # Each loop's kept points are one run, headed by its first point, so
    # the end is trimmed a point at a time, every loop at once.
    begin = np.searchsorted(kept, starts)
    count = np.bincount(of, minlength=len(lengths))
    while True:
        end = begin + count - 1
        trim = closed & (count > 1)
        at = end[trim]
        trim[trim] = np.all(f32[at] == f32[begin[trim]], axis=1) | (
            np.linalg.norm(rings[kept[at]] - rings[kept[begin[trim]]], axis=1) < MIN_EDGE_UM)
        if not trim.any():
            break
        count[trim] -= 1
    kept = kept[np.arange(len(kept)) - begin[of] < count[of]]
    shown = (lengths >= 3) & (count >= 3)

    # Every loop kept, in compartment order, each closed one ending on its
    # first point again: one gather, cut into loops.
    order = np.flatnonzero(shown)
    order = order[np.argsort(owners[order], kind="stable")]
    size = count[order] + closed[order]
    begin = np.concatenate(([0], np.cumsum(count)[:-1]))[order]
    at = np.concatenate(([0], np.cumsum(size)))
    index = np.empty(at[-1], dtype=int)
    step = np.arange(at[-1]) - np.repeat(at[:-1], size)
    index[:] = kept[np.repeat(begin, size) + np.minimum(step, np.repeat(count[order], size) - 1)]
    end = at[1:] - 1
    index[end[closed[order]]] = kept[begin[closed[order]]]
    loops = np.split(rings[index], at[1:-1])
    return list(zip(owners[order].tolist(), loops, strict=True))


def _loops(segments: np.ndarray, owners: np.ndarray, k: int):
    """Every simple loop the segments form, all compartments at once.

    `segments` join points 0..k-1; `owners` is each segment's compartment.
    Returns (the points of every loop end to end, how many each has, the
    compartment of each, the compartments whose segments are not simple
    loops). Simple loops means every point ends exactly two distinct
    segments.

    Compartments share no mesh vertex or edge, so no point is shared
    between two of them either, and every loop is walked in one graph. Each
    point's two neighbors are its segments' other ends, in segment order; a
    loop starts at its point that comes first in key order and goes to that
    point's first neighbor. The walk is a depth-first search from one extra
    node joined to each loop's start, which on a loop visits its points in
    order.
    """
    from scipy.sparse import csr_matrix
    from scipy.sparse.csgraph import connected_components, depth_first_order

    ends = segments.ravel()
    bad = (segments[:, 0] == segments[:, 1]) | np.any(
        np.bincount(ends, minlength=k)[segments] != 2, axis=1)
    handed_back = np.unique(owners[bad])
    if len(handed_back):
        return _without(segments, owners, handed_back)
    if not k:
        return np.empty(0, int), np.empty(0, int), np.empty(0, int), handed_back
    neighbor = segments[:, ::-1].ravel()[np.argsort(ends, kind="stable")]
    node_owner = np.empty(k, dtype=int)
    node_owner[segments] = owners[:, None]
    # Two segments joining the same two points: that point's neighbors are
    # one point twice. Not a simple loop either.
    twice = neighbor[0::2] == neighbor[1::2]
    if twice.any():
        return _without(segments, owners, np.unique(node_owner[twice]))

    ring_graph = csr_matrix((np.ones(2 * k), neighbor, np.arange(0, 2 * k + 1, 2)),
                            shape=(k, k))
    _n, label = connected_components(ring_graph, directed=False)
    _labels, head = np.unique(label, return_index=True)
    head = head[np.lexsort((head, node_owner[head]))]
    graph = csr_matrix(
        (np.ones(2 * k + len(head)), np.concatenate((neighbor, head)),
         np.concatenate((np.arange(0, 2 * k + 1, 2), [2 * k + len(head)]))),
        shape=(k + 1, k + 1))
    walk = depth_first_order(graph, k, directed=True, return_predecessors=False)[1:]
    is_head = np.zeros(k, dtype=bool)
    is_head[head] = True
    starts = np.flatnonzero(is_head[walk])
    lengths = np.diff(np.append(starts, len(walk)))
    return walk, lengths, node_owner[walk[starts]], handed_back


def _without(segments: np.ndarray, owners: np.ndarray, dropped: np.ndarray):
    """`_loops` of every compartment but `dropped`, which it hands back."""
    keep = ~np.isin(owners, dropped)
    ids, local = np.unique(segments[keep].ravel(), return_inverse=True)
    walk, lengths, loop_owners, more = _loops(local.reshape(-1, 2), owners[keep], len(ids))
    return ids[walk], lengths, loop_owners, np.union1d(dropped, more)


__all__ = ["MIN_EDGE_UM", "ON_PLANE_TOL", "SECTION_CACHE_PLANES", "MeshSections"]
