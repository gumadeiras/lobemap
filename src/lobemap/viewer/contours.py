"""Slice contours: exact mesh-plane intersections drawn as napari Shapes.

This is the only overlay mode in which two atlases
are genuinely readable together. Nested semi-transparent surfaces are
unreadable past two; outlines are not.

Contours are computed exactly, by intersecting the mesh with the current slice
plane, rather than by rasterizing. That keeps them crisp at any zoom and avoids
committing the pipeline to a voxel grid.

They also restore identification in 2D: napari's Surface._get_value returns
None in 2D, but Shapes._get_value returns a shape index, so the contour layer
is what makes a sliced glomerulus clickable.
"""

from __future__ import annotations

import warnings
from collections import OrderedDict

import numpy as np

from ..core.meshfmt import MeshSet

#: Slice-label point size. Was 7, which read as small against the contours.
TEXT_SIZE = 10.5

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


class ContourOverlay:
    """One Shapes layer per atlas, recomputed as the slice slider moves."""

    def __init__(
        self,
        viewer,
        meshset: MeshSet,
        name: str,
        color,
        selection: set[int] | None = None,
        axis: int | None = None,
        width: float = 0.35,
        colors=None,
    ) -> None:
        self.viewer = viewer
        self.meshset = meshset
        self.name = name
        #: Compartments whose name is drawn on the slice. Empty by default:
        #: with several atlases loaded every glomerulus would be written two
        #: or three times over, so labels are opt-in per glomerulus.
        self.labels: set[int] = set()
        #: Compartments drawn as filled polygons rather than open paths.
        #: A napari `path` cannot be filled at all -- it is an open
        #: polyline -- so filling means changing the shape type, not just
        #: the face color. Mesh-plane intersections are closed loops, so
        #: reading them as polygons is geometrically honest.
        self.filled: set[int] = set()
        self.color = color
        #: Per-compartment RGBA, taken from the Surface layer, so a
        #: glomerulus outline and its label are the color of its own mesh
        #: rather than one color for the whole atlas. None keeps `color`,
        #: which is what the reference neuropil shells use.
        self.colors = None if colors is None else np.asarray(colors, float)
        self._axis = axis
        self.width = width
        self.selection = set(
            range(meshset.n_compartments) if selection is None else selection
        )
        self.sections = MeshSections(meshset)
        self._shape_index: list[int] = []
        #: What the layer currently shows, as `_state` describes it. A
        #: refresh that would draw the same thing again returns at once:
        #: one 2D/3D switch reaches `refresh` from three separate hooks,
        #: and each of them used to rebuild every shape.
        self._drawn = None
        #: Whether the text is the blank constant rather than one string per
        #: shape, which saves re-sending it on every step while nothing is
        #: labeled. The layer is created with it.
        self._text_blank = True
        #: Whether any drawn shape is filled, so its face color needs undoing.
        self._faces_filled = False
        self._fill_rgba = None

        self.layer = viewer.add_shapes(
            data=[],
            name=f"{name} [contours]",
            shape_type="path",
            edge_color=color,
            edge_width=width,
            face_color="transparent",
            ndim=3,
            visible=False,
            text={"string": {"constant": ""}, "size": TEXT_SIZE,
                  "color": color, "anchor": "center"},
        )
        self.layer.metadata["lobemap"] = {"kind": "contours", "atlas": name}

        # Redraw when the layer is switched on. `refresh` returns early while
        # hidden -- it would otherwise recompute intersections for every
        # atlas on every slider step, visible or not -- so a layer ticked on
        # stayed EMPTY until the slider next moved. Ticking on a contour
        # layer is exactly how you show a second atlas in 2D, so this read as
        # contours randomly missing from the slice you were looking at, and
        # only in the hemibrain, the one space with more than one atlas.
        self.layer.events.visible.connect(self._on_visible)

    def _on_visible(self, event=None) -> None:
        if self.layer.visible:
            self.refresh()

    # -- geometry --------------------------------------------------------

    @property
    def axis(self) -> int:
        """The axis being sliced: whatever napari's slider is on.

        `viewer.dims.order[0]` is the first non-displayed axis. Reading it
        live means rolling the dims, or displaying x-y instead of y-z, moves
        the contours with the slider instead of silently leaving them cutting
        the wrong plane.
        """
        if self._axis is not None:
            return self._axis
        order = tuple(self.viewer.dims.order)
        return int(order[0]) if order else 0

    def slice_position(self) -> float:
        """Coordinate of the current slice along the sliced axis, in mesh units.

        The slider is in WORLD coordinates and the meshes are cut in their
        own. The two differ under the mirror, a reflection on `layer.affine`
        about x: slicing along x, world x is the reflection of mesh x, and a
        contour computed at the world value lay on a plane napari does not
        show. Through the layer's own transform, the plane is the one on
        screen whatever the affine.
        """
        dims = self.viewer.dims
        axis = self.axis
        point = getattr(dims, "point", None)
        if point is not None and len(point) > axis:
            if len(point) == self.layer.ndim:
                return float(self.layer.world_to_data(point)[axis])
            return float(point[axis])
        # Older napari: derive from the step index and the axis range.
        step = dims.current_step[axis]
        lo, _hi, span = dims.range[axis]
        return float(lo + step * span)

    def contours_at(self, position: float) -> tuple[list[np.ndarray], list[int]]:
        """Polylines crossing the plane, plus the compartment each came from."""
        sections = self.sections.at(self.axis, position)
        paths: list[np.ndarray] = []
        owners: list[int] = []
        for index in sorted(self.selection):
            for pts in sections.get(index, ()):
                paths.append(pts)
                owners.append(index)
        return paths, owners

    def _text_color(self, owners):
        colors = self._colors_for(owners)
        if colors is self.color:
            return self.color
        from napari.layers.utils.color_encoding import ManualColorEncoding

        # The encoding itself, not a dict or a list. A list of N colors
        # napari cannot tell from one color given component-wise, and it
        # silently collapsed it to a single constant -- `text.color` came
        # back 0-dimensional. A dict it parses by building a pydantic
        # TypeAdapter each time, which was most of a label update's cost.
        return ManualColorEncoding(array=colors, default=self.color)

    FILL_ALPHA = 0.35

    @staticmethod
    def _as_rgba(spec) -> tuple[float, float, float, float]:
        """Any color napari accepts -> four floats.

        A layer's color is not always a sequence of numbers: the neuropil
        shells are the hex string "#9aa0a6", and indexing that gives "#",
        so filling one raised `could not convert string to float`. Names
        and hex both have to go through napari's own parser.
        """
        from napari.utils.colormaps.standardize_color import transform_color

        return tuple(float(v) for v in np.asarray(transform_color(spec))[0])

    def _face_colors(self, owners):
        """Per-shape face color: the mesh color, faded, or transparent."""
        if self._fill_rgba is None:
            # Parsed once per compartment rather than once per shape per step.
            specs = (list(self.colors) if self.colors is not None
                     else [self.color] * self.meshset.n_compartments)
            table = np.array([self._as_rgba(spec) for spec in specs]).reshape(-1, 4)
            table[:, 3] = self.FILL_ALPHA
            self._fill_rgba = table
        owners = np.asarray(owners, dtype=int)
        filled = np.fromiter((i in self.filled for i in owners.tolist()), bool,
                             count=len(owners))
        out = np.zeros((len(owners), 4))
        out[filled] = self._fill_rgba[owners[filled]]
        return out

    def _shape_types(self, owners):
        return ["polygon" if i in self.filled else "path" for i in owners]

    def _colors_for(self, owners):
        """One RGBA per shape, from the compartment that shape came from."""
        if self.colors is None:
            return self.color
        return self.colors[np.asarray(owners, dtype=int)]

    # -- updates ---------------------------------------------------------

    def _state(self, axis: int, position: float) -> tuple:
        """Everything the drawn shapes depend on that can change.

        Not `color`, `colors` or `width`, which are the overlay's for its
        life: `_draw` relies on the layer's defaults being `color` and
        `width` too.
        """
        shown = frozenset(self.selection)
        return (
            axis, position, shown,
            frozenset(self.filled & shown), frozenset(self.labels & shown),
        )

    def refresh(self) -> None:
        # Nothing to cut in 3D, where no axis is sliced: the display-mode hook
        # hides contours there, but a scene opening in 3D switches the primary
        # atlas's contour on before that hook runs, and drawing it then cost a
        # 3D Shapes build at every load.
        if not self.layer.visible or self.viewer.dims.ndisplay != 2:
            return
        axis = self.axis
        position = self.slice_position()
        state = self._state(axis, position)
        if state == self._drawn and self.layer.nshapes == len(self._shape_index):
            return
        paths, owners = self.contours_at(position)
        self._draw(paths, owners)
        self._drawn = state

    def _draw(self, paths, owners) -> None:
        """Replace every shape in ONE data write.

        The shape type travels with each shape. Assigning `data` and then
        `shape_type` looks equivalent and is not: the setter re-adds every
        shape onto a shape list that already holds the previous ones, and
        once the layer has been displayed in 2D those carry 2D mesh
        vertices. Stacking them against 3D ones raised "array at index 0 has
        size 2 and the array at index 1 has size 3" on the second switch
        back into 2D.

        One write rather than clearing and then adding, because napari
        recomputes the extent of every layer, and the dims from it, on each
        data event, and a write emits two of them.

        The write keeps each position's old attributes and gives new
        positions the layer's defaults: width 1, this overlay's `color`, no
        fill. Each attribute written afterwards costs napari a full redraw
        of the layer, labels included, so only those that can be wrong are.
        """
        self._shape_index = list(owners)
        layer = self.layer
        # napari lays the labels out again after every write below, and blank
        # ones cost nothing, so they go blank until the shapes are final and
        # are then laid out once.
        self._blank_text()
        filled = bool(self.filled.intersection(owners))
        writes = [("data", list(zip(paths, self._shape_types(owners), strict=True)))]
        if paths:
            if len(paths) > layer.nshapes:
                writes.append(("edge_width", [self.width] * len(paths)))
            if self.colors is not None:
                writes.append(("edge_color", self._colors_for(owners)))
            if filled or self._faces_filled:
                writes.append(("face_color", self._face_colors(owners)))
        # napari redraws the layer-list thumbnail after each write,
        # rasterizing every shape each time; after the last is enough.
        with layer.block_thumbnail_update():
            for name, value in writes[:-1]:
                setattr(layer, name, value)
        setattr(layer, *writes[-1])
        self._faces_filled = filled
        # Text after data: napari requires one string per shape, so setting it
        # first would leave the counts disagreeing.
        self._apply_text(owners, paths)

    def _apply_text(self, owners: list[int], paths) -> None:
        """Write the labels, changing only the text's string and color.

        Size and anchor are set once, when the layer is made. Assigning a
        whole `layer.text` rebuilt napari's text manager on every slice
        step, five times the cost of updating these two fields in place.
        """
        if not (self.labels and self.labels.intersection(owners)):
            self._blank_text()
            return
        self._update_text({
            "string": self._label_strings(owners, paths),
            # One color per shape, matching that glomerulus's mesh. A single
            # color for the layer would put every label in the atlas color
            # while the outline under it was its own.
            "color": self._text_color(owners),
        }, blank=False)

    def _blank_text(self) -> None:
        """No label on any shape.

        A constant rather than a string per shape: napari broadcasts it to
        any number of shapes, so it stays right through later writes without
        being sent again.
        """
        if self._text_blank:
            return
        from napari.layers.utils.string_encoding import ConstantStringEncoding

        self._update_text({"string": ConstantStringEncoding(constant="")}, blank=True)

    def _update_text(self, values: dict, blank: bool) -> None:
        try:
            # One update, which napari reports as one event and so lays the
            # labels out once however many fields change.
            self.layer.text.update(values, recurse=False)
            self._text_blank = blank
        except Exception as exc:      # noqa: BLE001 - never worth a crash
            self._text_blank = False
            # Reported once rather than swallowed: if napari changes its text
            # API this is the only thing that tells us.
            if not getattr(self, "_text_warned", False):
                self._text_warned = True
                warnings.warn(f"slice labels unavailable: {exc!r}",
                              RuntimeWarning, stacklevel=2)

    def set_selection(self, indices) -> None:
        self.selection = set(indices)
        self.refresh()

    def set_labels(self, indices) -> None:
        """Choose which compartments write their name on the slice."""
        self.labels = set(indices)
        self.refresh()

    def set_fill(self, index: int, on: bool) -> None:
        self.filled.add(index) if on else self.filled.discard(index)
        self.refresh()

    def set_fills(self, indices) -> None:
        self.filled = set(indices)
        self.refresh()

    def set_label(self, index: int, on: bool) -> None:
        self.labels.add(index) if on else self.labels.discard(index)
        self.refresh()

    def _label_strings(self, owners: list[int], paths) -> list[str]:
        """One string per shape; blank except on each compartment's longest.

        A glomerulus can cross the plane as several separate polylines -- a
        concave one, or a compartment made of disconnected bodies -- and
        writing its name on all of them stacks the same text on itself. The
        longest contour is the one a reader would point at.
        """
        best: dict[int, int] = {}
        for i, (owner, path) in enumerate(zip(owners, paths)):
            if owner not in self.labels:
                continue
            if owner not in best or len(path) > len(paths[best[owner]]):
                best[owner] = i
        chosen = set(best.values())
        return [
            self.meshset.names[owner] if i in chosen else ""
            for i, owner in enumerate(owners)
        ]

    def name_at_shape(self, shape_index: int | None) -> str | None:
        """Map a picked Shapes index back to a compartment name."""
        if shape_index is None or not (0 <= shape_index < len(self._shape_index)):
            return None
        return self.meshset.names[self._shape_index[shape_index]]


def install(viewer, overlays: dict[str, ContourOverlay]) -> list[tuple]:
    """Keep contours in step with the slider.

    Returns (event, handler) pairs. Switching scenes replaces the overlays,
    and a handler left connected would go on refreshing layers belonging to
    a torn-down scene, so the caller needs to be able to disconnect them.

    Visibility is deliberately NOT set here. `viewer.app.install_display_mode`
    owns it, because it also adds and removes the layers and has to mirror each
    contour against its own surface -- two handlers on the same event, each
    with its own idea of what should be visible, is how a layer ends up
    visible in a mode that cannot draw it.

    The display-mode hook also refreshes the contours it reveals, so on a
    switch into 2D these handlers usually find nothing left to draw; a
    refresh that would redraw what is already there returns at once.
    """

    def _on_display_change(event=None) -> None:
        if viewer.dims.ndisplay == 2:
            for overlay in overlays.values():
                overlay.refresh()

    def _on_step(event=None) -> None:
        if viewer.dims.ndisplay != 2:
            return
        for overlay in overlays.values():
            overlay.refresh()

    pairs = [
        (viewer.dims.events.ndisplay, _on_display_change),
        (viewer.dims.events.current_step, _on_step),
        (viewer.dims.events.order, _on_step),
    ]
    for event, handler in pairs:
        event.connect(handler)
    _on_display_change()
    return pairs
