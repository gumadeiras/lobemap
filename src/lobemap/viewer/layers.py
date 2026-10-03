"""Building and rebuilding napari layers from a MeshSet.

One Surface layer per atlas, rebuilt from the current compartment selection.
One layer per glomerulus would be simpler but yields an unusable layer list at
~60 glomeruli x several atlases.

Picking: napari's Surface._get_value_3d does ray-triangle intersection and
returns the barycentric-interpolated vertex value. Because compartments are
disjoint meshes, all three vertices of any triangle share one compartment
index, so that value is EXACTLY the index -- identification is unambiguous.
(In 2D, Surface._get_value returns None; slice contours cover that case.)
"""

from __future__ import annotations

import itertools
import weakref

import numpy as np

from ..core.meshfmt import MeshSet
from . import napari_private
from .view import reflect_vertices


#: A qualitative palette that stays distinguishable at ~60 entries by cycling
#: hue fast and dithering lightness.
def categorical_colors(n: int, seed: int = 0) -> np.ndarray:
    rng = np.random.default_rng(seed)
    golden = 0.61803398875
    h = (np.arange(n) * golden + rng.random() * 0.0) % 1.0
    s = np.where(np.arange(n) % 2 == 0, 0.62, 0.85)
    v = np.where(np.arange(n) % 3 == 0, 0.95, 0.78)
    return _hsv_to_rgba(h, s, v)


def canonical_colors(compartments, canonical_order, fallback=(0.6, 0.6, 0.6, 1.0)):
    """One color per canonical glomerulus, shared by every atlas.

    Color was previously the compartment's position in its own file, so DA1
    came out orange in Bates (index 39 of 58) and red-brown in Benton (index
    34 of 58). In a viewer whose whole purpose is superposing atlases in one
    space, the same glomerulus has to be the same color, or the overlay
    cannot be read.

    `canonical_order` fixes the palette: a name's color depends only on its
    position in the shared vocabulary, so adding an atlas never recolors an
    existing one. A compartment carrying several canonical names -- Grabe's
    unresolved VP1 -- takes the color of the first, and the parts of a split
    -- Schlegel's VM6l/VM6m/VM6v -- all take VM6's, which is what makes them
    read as one structure.
    """
    index = {name: i for i, name in enumerate(canonical_order)}
    palette = categorical_colors(max(len(canonical_order), 1))
    out = np.empty((len(compartments), 4), dtype=float)
    for row, comp in enumerate(compartments):
        pick = next((index[c] for c in comp.canonical if c in index), None)
        out[row] = fallback if pick is None else palette[pick]
    return out


def _hsv_to_rgba(h: np.ndarray, s: np.ndarray, v: np.ndarray) -> np.ndarray:
    i = np.floor(h * 6.0).astype(int) % 6
    f = h * 6.0 - np.floor(h * 6.0)
    p, q, t = v * (1 - s), v * (1 - f * s), v * (1 - (1 - f) * s)
    r = np.choose(i, [v, q, p, p, t, v])
    g = np.choose(i, [t, v, v, q, p, p])
    b = np.choose(i, [p, p, t, v, v, q])
    return np.stack([r, g, b, np.ones_like(r)], axis=1)


#: What a surface's colormap is called in napari's layer settings: an
#: atlas's, and a neuropil set's. napari keeps every colormap it is given
#: by name, for the session, and its menus are as wide as the longest:
#: named after their layers, with ids in them, they widened the layer
#: settings by up to 60 px. Each surface holds an entry of its own,
#: numbered after the first, "Glomerulus colors (2)"; see `_take_colormap`.
GLOMERULUS_COLORS = "Glomerulus colors"
NEUROPIL_COLORS = "Neuropil colors"

#: Every colormap entry a surface has taken, by name, and the surface that
#: holds it, or None once it is given back.
_HOLDERS: dict[str, weakref.ref | None] = {}

#: A surface's layer: its part's title, and what it draws.
MESH_NAME = "{} · 3D"


def step_colormap(colors: np.ndarray, name: str = GLOMERULUS_COLORS):
    """A napari Colormap mapping value i to colors[i] with no blending.

    With 'zero' interpolation napari wants one more control point than color:
    the controls are bin *edges*, so n colors need n+1 edges.

    A single color is duplicated first. vispy's GLSL step generator asserts
    `ncolors >= 2`, so a one-compartment mesh -- a single-ROI reference shell --
    otherwise brings the whole viewer down when the layer is created, with an
    AssertionError far from the cause.
    """
    from napari.utils import Colormap

    colors = np.asarray(colors, dtype=float)
    if len(colors) == 1:
        colors = np.repeat(colors, 2, axis=0)
    n = len(colors)
    return Colormap(
        colors=colors,
        controls=np.linspace(0.0, 1.0, n + 1),
        interpolation="zero",
        name=name,
    )


def _take_colormap(holder, colors, base: str):
    """A colormap entry of napari's that `holder` alone recolors, showing `colors`.

    napari keeps every colormap it is given, by name, for the session, in
    the one list every layer's colormap menu shows, and replaces none: a
    colormap given under a name it holds with other colors is kept beside
    it, numbered. Each selection used to be such a colormap, so the menu
    gained an entry with each row toggled. Each surface takes the first
    of `base`, "`base` (2)", ... that no live surface holds: one a surface
    gone before it held, recolored, or a new one. It recolors that entry
    in place from then on (`_recolor`) and gives it back when its scene is
    torn down (`stop`). A name napari holds for anyone else is passed by.
    Two surfaces of the same colors so never share one entry, which a
    recolor would change under both.
    """
    from napari.utils.colormaps import AVAILABLE_COLORMAPS

    n = max(len(colors), 2)                 # as `step_colormap` makes them
    for k in itertools.count(1):
        name = base if k == 1 else f"{base} ({k})"
        if name in _HOLDERS:
            ref = _HOLDERS[name]
            if ref is not None and ref() is not None:
                continue                    # a live surface's
            entry = AVAILABLE_COLORMAPS[name]
            if len(entry.colors) != n:
                continue
            _recolor(entry, colors)
        elif name in AVAILABLE_COLORMAPS:
            continue                        # not lobemap's
        else:
            entry = step_colormap(colors, name=name)
        _HOLDERS[name] = weakref.ref(holder)
        return entry


def _recolor(entry, colors) -> None:
    """Give a colormap entry `step_colormap`'s colors for `colors`, in place."""
    colors = np.asarray(colors, dtype=float)
    entry.colors = np.repeat(colors, 2, axis=0) if len(colors) == 1 else colors


def direct_label_colormap(values_to_colors, name: str = GLOMERULUS_COLORS):
    """A napari colormap painting each label value with a given RGBA.

    Labels are a segmentation, so they need a value->color dict rather than
    the stepped ramp a Surface uses; napari calls that DirectLabelColormap.
    `None` is the fallback for any value not listed, and is transparent --
    an unnamed label should disappear rather than take some other
    glomerulus's color.
    """
    from napari.utils.colormaps import DirectLabelColormap

    color_dict = {int(v): tuple(float(x) for x in c)
                  for v, c in values_to_colors.items()}
    color_dict[None] = (0.0, 0.0, 0.0, 0.0)
    return DirectLabelColormap(color_dict=color_dict, name=name)


def colors_by_name(surface) -> dict[str, tuple]:
    """Compartment name -> the RGBA that surface actually paints it."""
    return {
        name: tuple(surface.colors[i])
        for i, name in enumerate(surface.meshset.names)
    }


def match_label_colors(layer, surfaces) -> int:
    """Paint a Labels layer the same colors as the meshes of the same names.

    The voxel masks and the meshes are two renderings of one segmentation, so
    a glomerulus that is olive as a mesh has to be olive as voxels too, or the
    two layers cannot be read against each other at all.

    The join is by NAME, and the colors are read out of the Surface layer
    rather than recomputed: recomputing would mean repeating the palette,
    the canonical ordering and the fallback, and any divergence between the
    two copies would show up as a quiet mismatch rather than an error. The
    value->name map travels in the volume's own metadata, written at ingest
    (`label_names`), so nothing here needs the source Amira header.

    Returns how many values were colored; 0 means nothing matched and the
    layer is left with napari's own colors.
    """
    names = (layer.metadata.get("lobemap", {}) or {}).get("label_names")
    if not names:
        return 0

    wanted = set(names.values())
    best, best_hits = None, 0
    for surface in surfaces:
        hits = len(wanted & set(surface.meshset.names))
        if hits > best_hits:
            best, best_hits = surface, hits
    if best is None:
        return 0

    palette = colors_by_name(best)
    mapping = {int(v): palette[n] for v, n in names.items() if n in palette}
    if not mapping:
        return 0
    layer.colormap = direct_label_colormap(mapping)
    return len(mapping)


def contrast_limits_for(n: int) -> tuple[float, float]:
    """Limits that place integer value i at the CENTER of color bin i.

    Using (0, n-1) would land values on bin boundaries, where rounding decides
    the color.
    """
    return (-0.5, n - 0.5)


class AtlasSurface:
    """A Surface layer bound to a MeshSet and a mutable selection."""

    def __init__(
        self,
        viewer,
        meshset: MeshSet,
        name: str,
        selection: list[int] | None = None,
        colors: np.ndarray | None = None,
        opacity: float = 0.75,
        blending: str = "translucent",
        compact_delay_ms: int = 250,
        display_names: list[str] | None = None,
        shading: str = "smooth",
        visible: bool = True,
        layer=None,
        mirror: tuple[int, float] | None = None,
        colormap_name: str = GLOMERULUS_COLORS,
    ) -> None:
        """`name` is the part's plain title; the layer is `MESH_NAME` of it.
        `layer` is a hidden Surface layer to take over rather than add one:
        a stand-in a scene added for this mesh before it was read
        (`deferred`). It is given everything a new layer would be.
        `mirror` is (axis, center) for a surface built while the view is
        reflected (`set_mirror`)."""
        self.viewer = viewer
        self.meshset = meshset
        #: The part's plain title, which its layers and hover text name it by.
        self.name = name
        n = meshset.n_compartments
        #: What a reader sees for each compartment: its published name, with
        #: any doubt about it (`Compartment.label`). `meshset.names` stays the
        #: identity every lookup uses.
        self.display_names = list(meshset.names if display_names is None
                                  else display_names)
        self.colors = categorical_colors(n) if colors is None else colors
        self.selection: set[int] = set(
            range(n) if selection is None else selection
        )
        self.compact_delay_ms = compact_delay_ms
        self._timer = None
        #: (axis, center) while the view is reflected, else None; see
        #: `_present`.
        self._mirror = None if mirror is None else (int(mirror[0]), float(mirror[1]))
        #: The layer that draws this selection in 2D -- the slice contours --
        #: once the display mode pairs them. See `sync`.
        self.twin = None
        #: Called after napari's own visibility toggle changed the selection,
        #: so the compartment table can follow it.
        self.listeners: list = []
        #: The selection an eye toggle hid, given back when it is shown again.
        self._stashed: set[int] | None = None
        self._syncing = False
        self._resident: list[int] = sorted(self.selection)
        v, f, vals = meshset.select(sorted(self.selection))
        v, f = self._present(v, f)
        #: This surface's own entry in napari's colormaps; see `_take_colormap`.
        self._colormap = _take_colormap(self, self.colors, colormap_name)
        settings = {
            "colormap": self._colormap,
            "contrast_limits": contrast_limits_for(n),
            "opacity": opacity,
            # Given here rather than set afterwards, so vispy never computes
            # the vertex normals a shell drawn with "none" does not use: they
            # are most of the cost of showing a large mesh in 3D, 0.45 s for
            # the hemibrain neuropils.
            "shading": shading,
            "blending": blending,
        }
        if layer is None:
            self.layer = viewer.add_surface(
                (v, f, vals), name=MESH_NAME.format(name), **settings,
                # A scene makes its surfaces hidden and lets `sync` show each
                # in the mode that draws it: napari slices a visible layer as
                # it is added, so a surface made visible was sliced for nothing
                # in 2D, and in 3D had its normals computed twice.
                visible=visible,
            )
        else:
            # Hidden first, and shaded before it has the mesh, for the same
            # reasons; a stand-in switched on is being built to be shown.
            layer.visible = False
            layer.shading = settings.pop("shading")
            layer.data = (v, f, vals)
            layer.name = MESH_NAME.format(name)
            for key, value in settings.items():
                setattr(layer, key, value)
            layer.visible = visible
            self.layer = layer
        self.layer.metadata["lobemap"] = {"meshset": meshset, "kind": "atlas"}
        self.layer.events.visible.connect(self._on_eye)
        #: Whether napari's vispy node still holds this layer's 3D build of
        #: its current data; see `hide_mesh`.
        self._built_3d = False
        self.layer.events.set_data.connect(self._on_built)
        self.layer.events.data.connect(self._on_changed)
        for setting in ("affine", "scale", "translate", "rotate", "shear", "shading"):
            getattr(self.layer.events, setting).connect(self._on_set_in_2d)

    # -- the 3D build, kept through 2D -------------------------------------
    #
    # napari rebuilds a Surface's vispy mesh every time the layer is shown,
    # and vispy computes its vertex normals anew for it: 0.21 s for GRABE's
    # 1.57 M faces on every entry into 3D, for a mesh that did not change.
    # So the mesh is hidden before napari slices it for 2D (`hide_mesh`),
    # which leaves the node its 3D build, and is shown again without a
    # refresh when nothing it was built from has changed since.

    def _on_built(self, event=None) -> None:
        self._built_3d = self.viewer.dims.ndisplay == 3

    def _on_changed(self, event=None) -> None:
        # A visible layer is rebuilt by napari straight after; a hidden one
        # is not, so the node is left with the old mesh.
        if not self.layer.visible:
            self._built_3d = False

    def _on_set_in_2d(self, event=None) -> None:
        # napari sets these on the node for the displayed axes: a transform,
        # and the shading, which a 2D node has none of, so a mesh restyled in
        # 2D would come back into 3D unlit.
        if self.viewer.dims.ndisplay != 3:
            self._built_3d = False

    def hide_mesh(self) -> None:
        """Hide the mesh before napari slices it for 2D, keeping its 3D build.

        Only a mesh with a twin: one without draws in 2D itself.
        """
        if (self.twin is None or not self.layer.visible
                or self.layer not in self.viewer.layers):
            return
        self._syncing = True
        try:
            with napari_private.no_scene_update(self.viewer, self.layer):
                self.layer.visible = False
        finally:
            self._syncing = False

    def _show_mesh(self) -> None:
        if self._built_3d and self.viewer.dims.ndisplay == 3:
            with napari_private.shown_unsliced(self.layer):
                self.layer.visible = True
        else:
            self.layer.visible = True

    # -- orientation -----------------------------------------------------

    def _present(self, vertices, faces):
        """Geometry as UPLOADED: reflected, with its winding reversed, while
        the view is reflected.

        A surface reflects its own vertices rather than riding on
        `layer.affine` as the images and contours do. napari loads the
        affine into the vispy NODE transform, and a determinant -1 transform
        there reverses the rasterized winding, which flips
        `gl_FrontFacing`; vispy's smooth shading negates the normal by
        exactly that (`normal = gl_FrontFacing ? normal : -normal`), so
        every glomerulus came out lit from inside. Reflecting the vertices
        keeps the node transform proper, and reversing the winding puts
        back the orientation the reflection took away.

        Re-winding ALONE, as this used to, does nothing visible: it flips
        the normals and `gl_FrontFacing` together and they cancel. Measured
        on GRABE in 3D, the node's signed volume and share of outward
        normals: +2.672e+05 and 76.8% unmirrored,
        -2.672e+05 and 23.2% under the affine mirror re-wound, +2.672e+05
        and 76.8% with the vertices reflected.

        Applied wherever geometry is uploaded, because `compact` re-uploads
        straight from the MeshSet on a debounce. The MeshSet itself is never
        touched, so the data and every measurement taken from it are not.
        """
        if self._mirror is None:
            return vertices, faces
        axis, center = self._mirror
        return (reflect_vertices(vertices, center, axis),
                np.ascontiguousarray(faces[:, ::-1]))

    @property
    def mirrored(self) -> bool:
        """Whether this surface is drawn reflected."""
        return self._mirror is not None

    def set_mirror(self, axis: int | None, center: float = 0.0) -> None:
        """Reflect this surface about `center` along `axis`, or stop."""
        want = None if axis is None else (int(axis), float(center))
        if want == self._mirror:
            return
        self._mirror = want
        if not self._resident:
            return
        v, f, vals = self.meshset.select(self._resident)
        v, f = self._present(v, f)
        self.layer.data = (v, f, vals)
        # Moved, not shrunk: a hidden layer would keep its old extent.
        napari_private.clear_extent(self.layer)

    # -- selection -------------------------------------------------------
    #
    # Two-stage, because the costs are wildly asymmetric (measured on 77
    # compartments / 158k vertices):
    #
    #   layer.data = ...        77 ms   <- napari revalidates + re-uploads
    #   layer.colormap = ...     0.9 ms <- alpha per compartment
    #
    # So a toggle repaints immediately by setting hidden compartments to
    # alpha 0, and the geometry is compacted on a short debounce. Compaction
    # still matters: while hidden geometry is resident it is invisible but
    # still absorbs the 3D pick ray, so `name_at_value` filters to the
    # current selection to cover the transient.
    #
    # The selection is also the ONLY record of what is shown. A layer is
    # visible exactly when something is selected and the current mode draws
    # it, so a checked row is a drawn glomerulus in either mode, and there
    # is no remembered visibility to go stale across 2D/3D switches.

    def set_visible(self, index: int, visible: bool) -> None:
        if visible:
            self.selection.add(index)
        else:
            self.selection.discard(index)
        self._stashed = None
        self.refresh()

    def set_selection(self, indices) -> None:
        self.selection = set(indices)
        self._stashed = None
        self.refresh()

    def show_all(self) -> None:
        self.set_selection(range(self.meshset.n_compartments))

    def show_none(self) -> None:
        self.set_selection([])

    def refresh(self) -> None:
        """Repaint now (cheap); compact the geometry shortly (expensive)."""
        self.sync(redraw=True)
        if self.selection:
            self._apply_alpha()
        self._schedule_compact()

    def pair(self, twin) -> None:
        """Let `twin` -- a contour overlay -- draw this selection in 2D.

        Visibility is left to the next `sync`, which the display mode runs
        once it has put the slider on the right axis and plane.
        """
        if self.twin is twin:
            return
        self.twin = twin
        twin.layer.events.visible.connect(self._on_eye)

    def draws_now(self) -> bool:
        """Whether this layer, rather than its twin, draws in this mode."""
        return self.twin is None or self.viewer.dims.ndisplay == 3

    def mode_layer(self):
        """The layer the current mode draws this selection with."""
        return self.layer if self.draws_now() else self.twin.layer

    def sync(self, redraw: bool = False) -> None:
        """Show the selection in whichever layer the current mode draws.

        Each visibility is written only when it changes: napari does NOT
        short-circuit a no-op write to `visible`, and assigning True to an
        already-visible layer cost 40-200 ms here, which was nearly all of
        a row toggle. `redraw` recomputes the twin's contours for a changed
        selection; a twin switched on redraws itself.
        """
        shown = bool(self.selection)
        mesh = shown and self.draws_now()
        self._syncing = True
        try:
            if self.layer.visible != mesh:
                if mesh:
                    self._show_mesh()
                else:
                    self.layer.visible = False
            twin = self.twin
            if twin is not None:
                twin.selection = set(self.selection)
                want = shown and not mesh
                if twin.layer.visible != want:
                    twin.layer.visible = want
                elif want and redraw:
                    twin.refresh()
        finally:
            self._syncing = False

    def _on_eye(self, event=None) -> None:
        """napari's visibility toggle, read as a change to the selection.

        Hiding the layer the mode draws unchecks everything, and remembers
        it; showing it again gives that back, or everything if there was
        nothing to give. Without this the eye and the table disagreed.
        """
        if self._syncing:
            return
        layer = self.mode_layer()
        source = getattr(event, "source", layer)
        if source is not layer:
            # The eye of the layer this mode does not draw -- the mesh in 2D,
            # the contours in 3D -- still means this atlas. Turned on, it
            # shows the atlas where the mode draws it and goes back off;
            # ignored, it drew the whole mesh over a slice with no row checked.
            if not source.visible:
                return
            if self.selection:
                self.sync()
                return
            showing = True
        elif layer.visible == bool(self.selection):
            return
        else:
            showing = layer.visible
        if showing:
            restored = self._stashed or set(range(self.meshset.n_compartments))
            self.selection, self._stashed = set(restored), None
        else:
            self._stashed, self.selection = set(self.selection), set()
        self.refresh()
        for listener in list(self.listeners):
            listener()

    def _apply_alpha(self) -> None:
        colors = self.colors.copy()
        mask = np.zeros(len(colors), dtype=bool)
        mask[sorted(self.selection)] = True
        colors[:, 3] = np.where(mask, 1.0, 0.0)
        _recolor(self._colormap, colors)
        self.layer.colormap = self._colormap

    def _schedule_compact(self) -> None:
        if self.compact_delay_ms <= 0:
            self.compact()
            return
        try:
            from qtpy.QtCore import QTimer
        except ImportError:  # pragma: no cover - no Qt
            return
        if self._timer is None:
            self._timer = QTimer()
            self._timer.setSingleShot(True)
            self._timer.timeout.connect(self.compact)
        self._timer.start(self.compact_delay_ms)

    def stop(self) -> None:
        """Cancel a pending compaction, and give back the colormap entry,
        for a scene being torn down."""
        if self._timer is not None:
            self._timer.stop()
        ref = _HOLDERS.get(self._colormap.name)
        if ref is not None and ref() is self:
            _HOLDERS[self._colormap.name] = None

    def compact(self) -> None:
        """Upload only the selected compartments. Restores exact picking.

        Geometry only. It used to switch the layer back on as well, so in
        2D the mesh reappeared under the slice a quarter second after any
        row change; visibility belongs to `sync` alone.
        """
        want = sorted(self.selection)
        if not want or want == self._resident:
            return
        v, f, vals = self.meshset.select(want)
        v, f = self._present(v, f)
        self.layer.data = (v, f, vals)
        self._resident = want
        self._apply_alpha()

    # -- identification --------------------------------------------------

    def pick(self, position, view_direction, dims_displayed) -> int | None:
        """The shown compartment a view ray through `position` meets first.

        napari's own Surface pick tests every triangle of the layer -- about
        40 ms for Benton's 298k -- and hovering asks on every mouse move.
        Bounding boxes first: only the compartments whose box the ray enters
        are tested, nearest box first, stopping once no remaining box starts
        nearer than a hit already found. Only selected compartments count,
        so geometry awaiting compaction cannot answer for a hidden one.
        """
        from napari.utils.geometry import find_nearest_triangle_intersection

        if view_direction is None or not self.selection:
            return None
        start, end = self.layer.get_ray_intersections(
            position, view_direction, list(dims_displayed), world=True
        )
        if start is None or end is None:
            return None
        start = np.asarray(start, dtype=float)
        direction = np.asarray(end, dtype=float) - start
        length = float(np.linalg.norm(direction))
        if length == 0.0:
            return None
        direction /= length
        if self._mirror is not None:
            # The ray is in the uploaded geometry's coordinates, reflected;
            # the boxes and triangles below are the MeshSet's (`_present`).
            axis, center = self._mirror
            start[axis] = 2.0 * center - start[axis]
            direction[axis] = -direction[axis]
        lo, hi = self._boxes()
        indices = np.array(sorted(self.selection))
        with np.errstate(divide="ignore", invalid="ignore"):
            near = (lo[indices] - start) / direction
            far = (hi[indices] - start) / direction
        enter = np.nanmax(np.minimum(near, far), axis=1)
        leave = np.nanmin(np.maximum(near, far), axis=1)
        crossed = leave >= np.maximum(enter, 0.0)
        best, best_t = None, np.inf
        for j in np.flatnonzero(crossed)[np.argsort(enter[crossed])]:
            if enter[j] > best_t:
                break
            v, f = self.meshset.compartment(int(indices[j]))
            hit, point = find_nearest_triangle_intersection(start, direction, v[f])
            if hit is None:
                continue
            t = float(np.dot(np.asarray(point) - start, direction))
            if t < best_t:
                best, best_t = int(indices[j]), t
        return best

    def _boxes(self) -> tuple[np.ndarray, np.ndarray]:
        """(K, 3) lowest and highest vertex of each compartment, cached."""
        if getattr(self, "_box_cache", None) is None:
            v = np.asarray(self.meshset.vertices, dtype=float)
            starts = np.asarray(self.meshset.vertex_offsets[:-1])
            lo = np.full((self.meshset.n_compartments, 3), np.nan)
            hi = np.full((self.meshset.n_compartments, 3), np.nan)
            filled = np.diff(self.meshset.vertex_offsets) > 0
            lo[filled] = np.minimum.reduceat(v, starts[filled], axis=0)
            hi[filled] = np.maximum.reduceat(v, starts[filled], axis=0)
            self._box_cache = (lo, hi)
        return self._box_cache

    def name_at_value(self, value: float | None) -> str | None:
        """Map a picked vertex value back to a compartment name.

        Returns None for a compartment that is currently hidden: between a
        toggle and the debounced compaction its geometry is still resident and
        can intercept the ray, and reporting an invisible glomerulus would be
        worse than reporting nothing.
        """
        if value is None:
            return None
        i = round(float(value))
        if 0 <= i < self.meshset.n_compartments and i in self.selection:
            return self.meshset.names[i]
        return None
