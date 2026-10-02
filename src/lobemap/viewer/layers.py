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

import numpy as np

from ..core.meshfmt import MeshSet


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


def step_colormap(colors: np.ndarray, name: str = "compartments"):
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


def direct_label_colormap(values_to_colors, name: str = "labels"):
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
    layer.colormap = direct_label_colormap(
        mapping, name=f"{layer.name}-colors"
    )
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
    ) -> None:
        self.viewer = viewer
        self.meshset = meshset
        self.name = name
        n = meshset.n_compartments
        self.colors = categorical_colors(n) if colors is None else colors
        self.selection: set[int] = set(
            range(n) if selection is None else selection
        )
        self.compact_delay_ms = compact_delay_ms
        self._timer = None
        #: (axis, centre) while the view is reflected, else None.
        self._mirror: tuple[int, float] | None = None
        self._resident: list[int] = sorted(self.selection)
        v, f, vals = meshset.select(sorted(self.selection))
        v, f = self._present(v, f)
        self.layer = viewer.add_surface(
            (v, f, vals),
            name=name,
            colormap=step_colormap(self.colors, name=f"{name}-colors"),
            contrast_limits=contrast_limits_for(n),
            opacity=opacity,
            shading="smooth",
            blending=blending,
        )
        self.layer.metadata["lobemap"] = {"meshset": meshset, "kind": "atlas"}

    # -- orientation -----------------------------------------------------

    def _present(self, vertices, faces):
        """Geometry as UPLOADED: reflected, if the view is reflected.

        The reflection is applied to the vertices here rather than to
        `layer.affine`, and the winding is reversed along with it. Both
        are needed, for one reason.

        napari loads a layer's affine into the vispy NODE transform. A
        determinant -1 transform there reverses the rasterized winding,
        which flips `gl_FrontFacing`, and vispy's smooth shading path
        negates the normal by exactly that:

            normal = gl_FrontFacing ? normal : -normal;

        so every glomerulus comes out lit from inside. Reflecting the
        vertices instead keeps the node transform proper and the facing
        correct; reversing the winding then puts back the orientation
        the reflection took away.

        It is also why re-winding ALONE does nothing visible: it flips
        the MeshData normal and `gl_FrontFacing` together, and they
        cancel in that expression. Measured on GRABE in 3D, node signed
        volume and the share of outward normals:

            unmirrored                  +2.672e+05   76.8% outward
            affine mirror, re-wound     -2.672e+05   23.2% outward
            affine mirror, not re-wound +2.672e+05   76.8% outward

        The MeshSet is untouched throughout. This changes only what is
        handed to napari, so the data on disk and every measurement
        taken from it are unaffected.
        """
        if self._mirror is None:
            return vertices, faces
        axis, centre = self._mirror
        v = np.array(vertices, dtype=np.float32, copy=True)
        v[:, axis] = np.float32(2.0 * centre) - v[:, axis]
        return v, np.ascontiguousarray(faces[:, ::-1])

    def set_mirror(self, axis: int | None, centre: float = 0.0) -> None:
        """Reflect this surface about `centre` on `axis`, or stop."""
        want = None if axis is None else (int(axis), float(centre))
        if want == self._mirror:
            return
        self._mirror = want
        if not self._resident:
            return
        v, f, vals = self.meshset.select(self._resident)
        v, f = self._present(v, f)
        self.layer.data = (v, f, vals)

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

    def set_visible(self, index: int, visible: bool) -> None:
        if visible:
            self.selection.add(index)
        else:
            self.selection.discard(index)
        self.refresh()

    def set_selection(self, indices) -> None:
        self.selection = set(indices)
        self.refresh()

    def show_all(self) -> None:
        self.set_selection(range(self.meshset.n_compartments))

    def show_none(self) -> None:
        self.set_selection([])

    def refresh(self) -> None:
        """Repaint now (cheap); compact the geometry shortly (expensive)."""
        self._set_visible_if_changed(bool(self.selection))
        if self.selection:
            self._apply_alpha()
        self._schedule_compact()

    def _set_visible_if_changed(self, value: bool) -> None:
        # napari does NOT short-circuit a no-op write to `visible`: assigning
        # True to an already-visible layer costs ~70 ms here, which dwarfs
        # everything else in a toggle. Guard it.
        if self.layer.visible != value:
            self.layer.visible = value

    def _apply_alpha(self) -> None:
        colors = self.colors.copy()
        mask = np.zeros(len(colors), dtype=bool)
        mask[sorted(self.selection)] = True
        colors[:, 3] = np.where(mask, 1.0, 0.0)
        self.layer.colormap = step_colormap(colors, name=f"{self.name}-colors")

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

    def compact(self) -> None:
        """Upload only the selected compartments. Restores exact picking."""
        want = sorted(self.selection)
        if want == self._resident:
            return
        if not want:
            self._set_visible_if_changed(False)
            return
        v, f, vals = self.meshset.select(want)
        v, f = self._present(v, f)
        self.layer.data = (v, f, vals)
        self._resident = want
        self._set_visible_if_changed(True)
        self._apply_alpha()

    # -- identification --------------------------------------------------

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
