"""Slice contours: exact mesh-plane intersections, drawn as vector geometry.

This is the only overlay mode in which two atlases
are genuinely readable together. Nested semi-transparent surfaces are
unreadable past two; outlines are not.

Contours are computed exactly, by intersecting the mesh with the current slice
plane, rather than by rasterizing. That keeps them crisp at any zoom and avoids
committing the pipeline to a voxel grid.

They also restore identification in 2D: napari's Surface._get_value returns
None in 2D, so the loops drawn here are what hover picking tests
(`viewer.app.install_picking`).

Each atlas has a napari layer for its contours, but draws them with vispy
visuals of its own under that layer (`SliceVisual`): one mesh of outline
and fill triangles, and one text. napari's Shapes rebuilt every shape on
every slider step; see `ContourOverlay`.

The sections and outlines of every slider plane inside a shown atlas are
cut ahead of time off the UI thread (`viewer.prefetch`), so a step to a new
plane only draws.
"""

from __future__ import annotations

import contextlib

import numpy as np

from ..core.meshfmt import MeshSet
from . import napari_private, prefetch
from .sections import MeshSections, PlaneCache

#: Slice-label point size. Was 7, which read as small against the contours.
TEXT_SIZE = 10.5

#: Bytes of outline geometry, and of the fills built on it, an overlay keeps.
#: The outlines of every slider plane inside a shipped atlas along any axis
#: fit: at most 55 MB, the male CNS atlas along y. With
#: `sections.SECTION_CACHE_BYTES`, at most 96 MB an atlas.
GEOMETRY_CACHE_BYTES = 64 * 2**20

#: napari's miter limit for a path's joins: past it a join is beveled.
MITER_LIMIT = 3.0


def _stroke(ring: np.ndarray, width: float) -> tuple[np.ndarray, np.ndarray]:
    """Triangles drawing a closed ring `width` wide, exactly as napari strokes one.

    The same call napari's Shapes makes for every path it draws, so joins,
    bevels and width are napari's own; the ring is closed, so its first
    point is joined like any other instead of meeting itself in two butt
    ends.
    """
    ring = np.ascontiguousarray(ring, dtype=np.float32)
    try:
        import bermuda

        centers, offsets, triangles = bermuda.triangulate_path_edge(
            ring, closed=True, limit=MITER_LIMIT)
    except ImportError:
        centers, offsets, triangles = napari_private.triangulate_edge(ring)
    return centers + width * offsets, np.asarray(triangles, dtype=np.int64)


def _fill(ring: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """Triangles covering the inside of a simple closed ring, exactly.

    A fan from the ring's centroid when every fan triangle turns the same
    way: the ring is then star-shaped about that point, and the fan tiles
    its inside with no overlap and no gap. Most sections are, and the fan
    is one array operation. Otherwise the triangulation napari's Shapes
    uses for a polygon, bermuda's -- checked, since bermuda overlaps
    triangles in some rings: about 3% of the glomerulus sections that are
    not star-shaped, covering up to 2.5% more than the ring, and 6% of the
    neuropil ones, up to 18%. A fill at `FILL_ALPHA` shows each overlap
    darker. The ring with its axes swapped, or mirrored, is triangulated
    instead, which leaves 3 of 12,160 FAFB neuropil sections cut 2 um apart;
    napari's own pure-Python triangulation, exact but tens of milliseconds a
    ring, fills those.
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
    try:
        import bermuda
    except ImportError:
        points, triangles = napari_private.triangulate_face(ring32)
        return np.asarray(points, dtype=np.float64), np.asarray(triangles, dtype=np.int64)
    first = None
    for flip in (_as_is, _swapped, _mirrored):
        triangles, points = bermuda.triangulate_polygons_face(
            [np.ascontiguousarray(flip(ring32))])
        made = flip(np.asarray(points, dtype=np.float64)), np.asarray(triangles, np.int64)
        if _covers(*made, ring32):
            return made
        if first is None:
            first = made
    try:
        points, triangles = napari_private.triangulate_face(ring32)
        made = np.asarray(points, dtype=np.float64), np.asarray(triangles, dtype=np.int64)
    except Exception:  # noqa: BLE001 - keep bermuda's, as napari drew it
        return first
    return made if _covers(*made, ring32) else first


def _as_is(points: np.ndarray) -> np.ndarray:
    return points


def _swapped(points: np.ndarray) -> np.ndarray:
    return points[:, ::-1]


def _mirrored(points: np.ndarray) -> np.ndarray:
    return points * np.array([1, -1], points.dtype)


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


class _PlaneGeometry:
    """What one plane draws, for every compartment it cuts, built once.

    Outlines are built for every compartment on the plane, as the sections
    are, so a change of selection picks triangles out of these arrays rather
    than building any. Fills are built the first time a compartment is
    filled on this plane. Points are kept in the plane's own two axes, as
    float32, which is what vispy is handed.
    """

    def __init__(self, sections: dict[int, list[np.ndarray]], axis: int,
                 position: float, width: float, pause=None) -> None:
        self.axis, self.position = axis, position
        #: The two in-plane array axes, in increasing order.
        self.plane = [d for d in range(3) if d != axis]
        self._sections = sections
        self.present = frozenset(sections)
        verts, faces, owners = [], [], []
        count = 0
        for n, owner in enumerate(sorted(sections)):
            if pause is not None and n % 8 == 7:
                pause()
            for loop in sections[owner]:
                v, f = _stroke(loop[:-1][:, self.plane], width)
                verts.append(v)
                faces.append(f + count)
                owners.append(np.full(len(v), owner, np.int32))
                count += len(v)
        self.vertices, self.faces = _stack(verts, faces)
        #: The compartment each outline point belongs to.
        self.owner = np.concatenate(owners) if owners else np.empty(0, np.int32)
        self._fills: dict[int, tuple[np.ndarray, np.ndarray]] = {}

    def fill(self, owner: int) -> tuple[np.ndarray, np.ndarray]:
        """Triangles filling every loop of one compartment on this plane."""
        if owner not in self._fills:
            verts, faces, count = [], [], 0
            for loop in self._sections.get(owner, ()):
                v, f = _fill(loop[:-1][:, self.plane])
                verts.append(v)
                faces.append(f + count)
                count += len(v)
            self._fills[owner] = _stack(verts, faces)
        return self._fills[owner]

    @property
    def nbytes(self) -> int:
        """What this plane holds: its outlines, and the fills built so far."""
        return int(self.vertices.nbytes + self.faces.nbytes + self.owner.nbytes
                   + sum(v.nbytes + f.nbytes for v, f in self._fills.values()))

    def on_screen(self, points: np.ndarray, displayed) -> np.ndarray:
        """In-plane points as vispy's x, y: the last displayed axis, then the other."""
        xy = list(displayed)[::-1]
        if sorted(xy) == self.plane:
            return points if xy == self.plane else np.ascontiguousarray(points[:, ::-1])
        # The sliced axis on screen: the plane seen edge on.
        full = np.empty((len(points), 3), np.float32)
        full[:, self.plane] = points
        full[:, self.axis] = self.position
        return full[:, xy]


def _stack(verts: list, faces: list) -> tuple[np.ndarray, np.ndarray]:
    """Points as float32 and triangles as uint32, each in one array."""
    return (np.vstack(verts).astype(np.float32) if verts
            else np.empty((0, 2), np.float32),
            np.vstack(faces).astype(np.uint32) if faces
            else np.empty((0, 3), np.uint32))


class SliceVisual:
    """The vispy visuals one overlay draws its slice with.

    Children of the napari layer's own vispy node, so they are drawn where
    and when the layer is: in its place in the layer order, through its
    transform -- the mirror included -- and in its viewbox. Nothing here is
    napari state, so a redraw is two vispy updates and no napari event: no
    extent is recomputed, no shape is re-meshed, no thumbnail is redrawn.

    - `mesh`: the fills, then every outline over them, in one draw.
    - `text`: the labels.
    """

    def __init__(self, viewer, layer) -> None:
        from vispy.scene.visuals import Mesh

        visual = napari_private.layer_visual(viewer, layer)
        self.layer = layer
        self.mesh = Mesh(parent=visual.node)
        self.mesh.order = 0
        # The font napari gives the layer's own text.
        self.text = napari_private.text_visual(visual.node, visual.font_info)
        self.text.order = 1
        self.text.anchors = ("center", "center")
        self.text.font_size = TEXT_SIZE
        self.text.visible = False
        self.mesh.visible = False
        #: Whether each visual has anything to draw.
        self._has_mesh = self._has_text = False
        self._on_blending()
        self._on_opacity()
        layer.events.blending.connect(self._on_blending)
        layer.events.opacity.connect(self._on_opacity)

    def _on_blending(self, event=None) -> None:
        self.mesh.set_gl_state(**napari_private.gl_state(self.layer.blending))
        self.text.set_gl_state(**napari_private.gl_state("translucent"))

    def _on_opacity(self, event=None) -> None:
        self.mesh.opacity = self.text.opacity = self.layer.opacity

    def set_visible(self, on: bool) -> None:
        self.mesh.visible = on and self._has_mesh
        self.text.visible = on and self._has_text

    def draw(self, vertices, faces, colors, on: bool) -> None:
        self._has_mesh = bool(len(faces))
        if self._has_mesh:
            self.mesh.set_data(vertices=vertices, faces=faces, vertex_colors=colors)
        self.mesh.visible = on and self._has_mesh

    def label(self, strings, positions, colors, on: bool) -> None:
        self._has_text = bool(strings)
        if self._has_text:
            self.text.text = strings
            self.text.pos = positions
            self.text.color = colors
        self.text.visible = on and self._has_text


class ContourOverlay:
    """One atlas's slice contours, recomputed as the slice slider moves.

    The layer is a napari Shapes layer that holds no shapes: it is what the
    layer list, the eye, the mirror's affine and the layer order act on.
    What is on the plane is drawn by `SliceVisual`, under that layer's own
    vispy node. A step used to rebuild every shape of a Shapes layer --
    napari meshes each one, redraws the thumbnail, and recomputes every
    layer's extent twice -- which was most of a step's time.
    """

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
        display_names: list[str] | None = None,
    ) -> None:
        self.viewer = viewer
        self.meshset = meshset
        self.name = name
        #: The text written on the slice for each compartment; see
        #: `AtlasSurface.display_names`.
        self.display_names = list(meshset.names if display_names is None
                                  else display_names)
        #: Compartments whose name is drawn on the slice. Empty by default:
        #: with several atlases loaded every glomerulus would be written two
        #: or three times over, so labels are opt-in per glomerulus.
        self.labels: set[int] = set()
        #: Compartments drawn filled as well as outlined. Mesh-plane
        #: intersections are closed loops, so filling them is honest.
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
        self._geometry = PlaneCache(GEOMETRY_CACHE_BYTES)
        #: What the prefetch is computing for, and its plan; see `_prefetch`.
        self._prefetch_key = None
        self._plan = None
        #: Changes each time the layer's transform does, the mirror's included.
        self._moves = 0
        #: The loops drawn now, in data coordinates, and the compartment
        #: each came from: what hover picking tests and `name_at_shape` reads.
        self.paths: list[np.ndarray] = []
        self._shape_index: list[int] = []
        #: What is drawn now, as `_state` describes it. A refresh that would
        #: draw the same thing again returns at once: one 2D/3D switch
        #: reaches `refresh` from three separate hooks.
        self._drawn = None
        self._fill_rgba = None
        self._edge_rgba = None

        self.layer = viewer.add_shapes(
            data=[],
            name=f"{name} [contours]",
            shape_type="path",
            edge_color=color,
            edge_width=width,
            face_color="transparent",
            ndim=3,
            visible=False,
        )
        self.layer.metadata["lobemap"] = {"kind": "contours", "atlas": name}
        self.visual = SliceVisual(viewer, self.layer)
        # The layer holds no shapes, so no step can change its extent.
        napari_private.keep_extent_while_slicing(self.layer)

        # Redraw when the layer is switched on. `refresh` returns early while
        # hidden -- it would otherwise recompute intersections for every
        # atlas on every slider step, visible or not -- so a layer ticked on
        # stayed EMPTY until the slider next moved. Ticking on a contour
        # layer is exactly how you show a second atlas in 2D, so this read as
        # contours randomly missing from the slice you were looking at, and
        # only in the hemibrain, the one space with more than one atlas.
        self.layer.events.visible.connect(self._on_visible)
        for moved in (self.layer.events.affine, self.layer.events.scale,
                      self.layer.events.translate):
            moved.connect(self._on_moved)
        # A scene torn down, or a viewer closed, removes the layer: the
        # prefetch for it stops there.
        viewer.layers.events.removed.connect(self._on_removed)

    def _on_moved(self, event=None) -> None:
        self._moves += 1

    def _on_removed(self, event=None) -> None:
        if getattr(event, "value", None) is self.layer:
            self.stop()

    def stop(self) -> None:
        """Stop the prefetch for good, and stop listening for the layer's removal."""
        if self._plan is not None:
            self._plan.cancel()
        self._plan = None
        self._prefetch_key = ("stopped",)
        with contextlib.suppress(Exception):        # already disconnected
            self.viewer.layers.events.removed.disconnect(self._on_removed)

    def _hold_prefetch(self) -> None:
        """Hidden, or in 3D: nothing more is cut until the contours show again."""
        if self._plan is not None:
            self._plan.cancel()
        if self._prefetch_key != ("stopped",):
            self._prefetch_key = None

    def _on_visible(self, event=None) -> None:
        self.refresh()

    def _showing(self) -> bool:
        """Whether the slice visuals should be on: the layer is, in 2D.

        And the dims are the layer's own: while a scene is torn down napari
        shrinks them as layers go, and a step can land in between.
        """
        dims = self.viewer.dims
        return (bool(self.layer.visible) and dims.ndisplay == 2
                and dims.ndim == self.layer.ndim)

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

    def _geometry_at(self, axis: int, position: float) -> _PlaneGeometry:
        key = (int(axis), float(position))
        hit = self._geometry.get(key)
        if hit is not None:
            return hit
        made = _PlaneGeometry(self.sections.at(*key), *key, self.width)
        return self._geometry.put(key, made, made.nbytes)

    def _build(self, sections, axis: int, position: float, pause=None) -> _PlaneGeometry:
        return _PlaneGeometry(sections, axis, position, self.width, pause)

    def _prefetch(self, axis: int, position: float) -> None:
        """Have every slider plane inside this atlas cut ahead, if not already asked.

        Asked again when the axis, the slider's grid or the layer's
        transform -- the mirror -- changes, since each moves the planes the
        slider can land on. The positions are worked out by the worker from
        a copy of the transform, the way `slice_position` works them out.
        """
        dims = self.viewer.dims
        start, _stop, step = dims.range[axis]
        nsteps = int(dims.nsteps[axis])
        key = (axis, self._moves, float(start), float(step), nsteps)
        if key == self._prefetch_key or self._prefetch_key == ("stopped",):
            return
        if self._plan is not None:
            self._plan.cancel()
        self._prefetch_key = key
        column = self.meshset.vertices[:, axis]
        self._plan = prefetch.Plan(
            self.sections, self._geometry, self._build, axis,
            napari_private.data_from_world(self.layer), dims.point,
            (float(start), float(step), nsteps),
            (float(column.min()), float(column.max())), position,
        )
        prefetch.submit(self._plan)

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

    def _rgba_tables(self) -> tuple[np.ndarray, np.ndarray]:
        """Outline and fill RGBA per compartment, parsed once."""
        if self._edge_rgba is None:
            specs = (list(self.colors) if self.colors is not None
                     else [self.color] * self.meshset.n_compartments)
            table = np.array([self._as_rgba(spec) for spec in specs]).reshape(-1, 4)
            self._edge_rgba = table.astype(np.float32)
            fill = table.copy()
            fill[:, 3] = self.FILL_ALPHA
            self._fill_rgba = fill.astype(np.float32)
        return self._edge_rgba, self._fill_rgba

    # -- updates ---------------------------------------------------------

    def _state(self, axis: int, position: float) -> tuple:
        """Everything the drawn slice depends on that can change.

        Not `color`, `colors` or `width`, which are the overlay's for its
        life.
        """
        shown = frozenset(self.selection)
        return (
            axis, position, tuple(self.viewer.dims.displayed), shown,
            frozenset(self.filled & shown), frozenset(self.labels & shown),
        )

    def refresh(self) -> None:
        # Nothing to cut in 3D, where no axis is sliced: the display-mode hook
        # hides contours there, but a scene opening in 3D switches the primary
        # atlas's contour on before that hook runs.
        showing = self._showing()
        self.visual.set_visible(showing)
        if not showing:
            self._hold_prefetch()
            return
        prefetch.poke()
        axis = self.axis
        position = self.slice_position()
        self._prefetch(axis, position)
        state = self._state(axis, position)
        if state == self._drawn:
            return
        paths, owners = self.contours_at(position)
        self._draw(self._geometry_at(axis, position), paths, owners)
        self._drawn = state

    def _draw(self, geometry: _PlaneGeometry, paths, owners) -> None:
        """Hand the plane's triangles and labels to the visuals.

        Fills first and outlines over them, in one mesh; the outlines are
        selected out of the plane's prebuilt ones by compartment.
        """
        self.paths, self._shape_index = list(paths), list(owners)
        edge_rgba, fill_rgba = self._rgba_tables()
        displayed = list(self.viewer.dims.displayed)
        shown = geometry.present & self.selection
        verts, faces, colors, count = [], [], [], 0
        held = geometry.nbytes
        for owner in sorted(self.filled & shown):
            v, f = geometry.fill(owner)
            verts.append(v)
            faces.append(f + np.uint32(count))
            colors.append(np.broadcast_to(fill_rgba[owner], (len(v), 4)))
            count += len(v)
        stroke = geometry.faces
        if shown != geometry.present:
            keep = np.zeros(self.meshset.n_compartments, bool)
            keep[list(shown)] = True
            stroke = stroke[keep[geometry.owner[stroke[:, 0]]]]
        verts.append(geometry.vertices)
        faces.append(stroke + np.uint32(count) if count else stroke)
        colors.append(edge_rgba[geometry.owner])
        if geometry.nbytes > held:
            self._geometry.grew((geometry.axis, geometry.position), geometry.nbytes - held)
        on = self._showing()
        self.visual.draw(
            geometry.on_screen(np.vstack(verts) if count else verts[0], displayed),
            np.vstack(faces) if count else faces[0],
            np.vstack(colors) if count else colors[0],
            on,
        )
        self._apply_text(owners, paths, displayed, on)

    def _apply_text(self, owners, paths, displayed, on: bool) -> None:
        """Write each labeled compartment's name at its longest loop's center.

        The center is the mean of that loop's points, the closing one
        included, which is where napari's `center` anchor put the text of
        the shape the loop used to be.
        """
        strings, positions, colors = [], [], []
        if self.labels and self.labels.intersection(owners):
            edge_rgba, _fill = self._rgba_tables()
            for i, text in enumerate(self._label_strings(owners, paths)):
                if not text:
                    continue
                strings.append(text)
                positions.append(np.asarray(paths[i])[:, displayed].mean(axis=0)[::-1])
                colors.append(edge_rgba[owners[i]])
        self.visual.label(strings, np.asarray(positions, np.float32).reshape(-1, 2),
                          np.asarray(colors, np.float32).reshape(-1, 4), on)

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
        """One string per loop; blank except on each compartment's longest.

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
            self.display_names[owner] if i in chosen else ""
            for i, owner in enumerate(owners)
        ]

    def name_at_shape(self, shape_index: int | None) -> str | None:
        """Map a drawn loop's index back to a compartment name."""
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
        # In 3D too: a refresh there puts the slice visuals away.
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
    # Before napari slices anything for a step, the prefetch is told to give
    # way at its next pause, so the step does not wait for it.
    napari_private.before_slicing(viewer, prefetch.poke)
    _on_display_change()
    return pairs
