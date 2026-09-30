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

    - Faces are culled by their extent along the sliced axis, kept per axis.
    - Each remaining face is classified exactly as trimesh classifies it --
      two vertices on one side and one on the other, a vertex on the plane
      between the other two, or an edge on the plane -- and yields the same
      segment.
    - A segment ends on a mesh edge or a mesh vertex, and it is joined to
      its neighbors by THAT identity, not by rounding coordinates. Two faces
      sharing an edge therefore share the point exactly. On a closed
      manifold every such point has two segments, and walking them gives
      each loop directly.

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
        near = np.flatnonzero((fmin <= p + ON_PLANE_TOL) & (fmax >= p - ON_PLANE_TOL))
        owner = np.searchsorted(self._offsets, near, side="right") - 1
        # A compartment is sectioned only when the plane is inside its
        # bounds, as `contours_at` always required.
        inside = (lo[owner] <= p) & (p <= hi[owner])
        near, owner = near[inside], owner[inside]
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
        owners = owner[rows]
        segments = nodes.reshape(-1, 2)

        out: dict[int, list[np.ndarray]] = {}
        order = np.argsort(owners, kind="stable")
        cuts = np.flatnonzero(np.diff(owners[order])) + 1
        for group in np.split(order, cuts):
            owner = int(owners[group[0]])
            loops = _loops(segments[group], points)
            if loops is None:
                loops = self._trimesh_section(owner, axis, p)
            loops = [kept for kept in map(_drawable, loops) if kept is not None]
            if loops:
                out[owner] = loops
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


def _drawable(loop: np.ndarray) -> np.ndarray | None:
    """A loop without the points no one can tell apart, or None.

    Two kinds go:

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
    fewer than three points, too small to see, is dropped with them.
    """
    closed = len(loop) > 1 and np.array_equal(loop[0], loop[-1])
    ring = loop[:-1] if closed else loop
    if len(ring) < 3:
        return None
    keep = np.ones(len(ring), dtype=bool)
    keep[1:] = np.linalg.norm(np.diff(ring, axis=0), axis=1) >= MIN_EDGE_UM
    if not keep.all():
        # A run of short edges can wander; keep whatever strays from the
        # point that heads the run.
        head = np.maximum.accumulate(np.where(keep, np.arange(len(ring)), 0))
        keep |= np.linalg.norm(ring - ring[head], axis=1) >= MIN_EDGE_UM
    kept = np.flatnonzero(keep)
    f32 = ring[kept].astype(np.float32)
    distinct = np.ones(len(kept), dtype=bool)
    distinct[1:] = np.any(f32[1:] != f32[:-1], axis=1)
    kept, f32 = kept[distinct], f32[distinct]
    while closed and len(kept) > 1 and (
        np.array_equal(f32[-1], f32[0])
        or np.linalg.norm(ring[kept[-1]] - ring[0]) < MIN_EDGE_UM
    ):
        kept, f32 = kept[:-1], f32[:-1]
    if len(kept) < 3:
        return None
    if len(kept) == len(ring):
        return loop
    out = ring[kept]
    return np.vstack((out, out[:1])) if closed else out


def _loops(segments: np.ndarray, points: np.ndarray) -> list[np.ndarray] | None:
    """Closed polylines from segments that form simple loops, else None.

    Simple loops means every point ends exactly two distinct segments. Each
    polyline repeats its first point at the end, as trimesh's closed ones do.
    """
    ids, local = np.unique(segments.ravel(), return_inverse=True)
    local = local.reshape(-1, 2)
    k = len(ids)
    if np.any(local[:, 0] == local[:, 1]):
        return None
    if np.any(np.bincount(local.ravel(), minlength=k) != 2):
        return None
    ordered = np.sort(local, axis=1)
    if len(np.unique(ordered[:, 0] * k + ordered[:, 1])) != len(ordered):
        return None
    # Each point's two neighbors, found by sorting the segment ends.
    flat = local.ravel()
    neighbor = local[:, ::-1].ravel()[np.argsort(flat, kind="stable")].reshape(k, 2)
    first, second = neighbor[:, 0].tolist(), neighbor[:, 1].tolist()
    seen = bytearray(k)
    loops = []
    for start in range(k):
        if seen[start]:
            continue
        walk = [start]
        seen[start] = 1
        prev, cur = start, first[start]
        while cur != start:
            walk.append(cur)
            seen[cur] = 1
            nxt = first[cur]
            if nxt == prev:
                nxt = second[cur]
            prev, cur = cur, nxt
        walk.append(start)
        loops.append(points[ids[walk]])
    return loops


__all__ = ["MIN_EDGE_UM", "ON_PLANE_TOL", "SECTION_CACHE_PLANES", "MeshSections"]
