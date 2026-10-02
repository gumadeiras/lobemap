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

import numpy as np

from ..core.meshfmt import MeshSet

#: Slice-label point size. Was 7, which read as small against the contours.
TEXT_SIZE = 10.5


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
        self._cache: dict[int, object] = {}
        self._shape_index: list[int] = []

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

    def _mesh(self, index: int):
        """Trimesh for one compartment, built once and reused per slice."""
        if index not in self._cache:
            import trimesh

            v, f = self.meshset.compartment(index)
            self._cache[index] = trimesh.Trimesh(
                vertices=v, faces=f, process=False
            )
        return self._cache[index]

    def slice_position(self) -> float:
        """World coordinate of the current slice along the sliced axis."""
        dims = self.viewer.dims
        point = getattr(dims, "point", None)
        if point is not None and len(point) > self.axis:
            return float(point[self.axis])
        # Older napari: derive from the step index and the axis range.
        step = dims.current_step[self.axis]
        lo, _hi, span = dims.range[self.axis]
        return float(lo + step * span)

    def contours_at(self, position: float) -> tuple[list[np.ndarray], list[int]]:
        """Polylines crossing the plane, plus the compartment each came from."""
        origin = np.zeros(3)
        origin[self.axis] = position
        normal = np.zeros(3)
        normal[self.axis] = 1.0

        paths: list[np.ndarray] = []
        owners: list[int] = []
        for index in sorted(self.selection):
            mesh = self._mesh(index)
            lo, hi = mesh.bounds[0][self.axis], mesh.bounds[1][self.axis]
            if not (lo <= position <= hi):
                continue  # cheap reject before the intersection
            try:
                section = mesh.section(plane_origin=origin, plane_normal=normal)
            except Exception:  # noqa: BLE001, S112 - a tangent plane degenerates
                continue
            if section is None:
                continue
            for poly in section.discrete:
                if len(poly) < 2:
                    continue
                pts = np.asarray(poly, dtype=float)
                # Pin exactly to the plane so napari shows it on this slice.
                pts[:, self.axis] = position
                paths.append(pts)
                owners.append(index)
        return paths, owners

    def _text_color(self, owners):
        colors = self._colors_for(owners)
        if colors is self.color:
            return self.color
        return {"array": colors, "default": self.color}

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
        out = []
        for i in owners:
            if i not in self.filled:
                out.append((0.0, 0.0, 0.0, 0.0))
                continue
            spec = (self.colors[i] if self.colors is not None
                    and 0 <= i < len(self.colors) else self.color)
            r, g, b, _ = self._as_rgba(spec)
            out.append((r, g, b, self.FILL_ALPHA))
        return out

    def _shape_types(self, owners):
        return ["polygon" if i in self.filled else "path" for i in owners]

    def _colors_for(self, owners):
        """One RGBA per shape, from the compartment that shape came from."""
        if self.colors is None:
            return self.color
        return [
            self.colors[i] if 0 <= i < len(self.colors) else self.color
            for i in owners
        ]

    # -- updates ---------------------------------------------------------

    def refresh(self) -> None:
        if not self.layer.visible:
            return
        paths, owners = self.contours_at(self.slice_position())
        self._shape_index = owners
        # Clear, then add with the shape type given explicitly. Assigning
        # `data` and then `shape_type` looks equivalent and is not: the
        # setter re-adds every shape onto a shape list that already holds the
        # previous ones, and once the layer has been displayed in 2D those
        # carry 2D mesh vertices. Stacking them against 3D ones raised
        # "array at index 0 has size 2 and the array at index 1 has size 3"
        # on the second switch back into 2D.
        self.layer.data = []
        if paths:
            self.layer.add(
                paths,
                shape_type=self._shape_types(owners),
                edge_color=self._colors_for(owners),
                face_color=self._face_colors(owners),
                edge_width=self.width,
            )
        # Text after data: napari requires one string per shape, so setting it
        # first would leave the counts disagreeing.
        self._apply_text(owners, paths)

    def _apply_text(self, owners: list[int], paths) -> None:
        strings = self._label_strings(owners, paths) if paths else []
        try:
            self.layer.text = {
                "string": strings,
                "size": TEXT_SIZE,
                # One color per shape, matching that glomerulus's mesh. A
                # single color for the layer would put every label in the
                # atlas color while the outline under it was its own.
                #
                # Spelled as ManualColorEncoding rather than a bare list:
                # napari cannot tell a list of N colors from one color
                # given component-wise, and silently collapsed the list to a
                # single constant -- `text.color` came back 0-dimensional.
                "color": self._text_color(owners),
                "anchor": "center",
            }
        except Exception as exc:      # noqa: BLE001 - never worth a crash
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
