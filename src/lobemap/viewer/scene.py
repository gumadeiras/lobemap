"""What a space puts in the viewer, and the session that can take it out again.

`build_scene` adds a space's reference meshes, images and atlases, each atlas
with its slice contours; `SceneSession` records what one load created, so a
switch can tear it down again without touching anything else.
"""

from __future__ import annotations

import contextlib

from ..core.registry import Registry
from .axes import apply_axis_mode
from .contours import ContourOverlay
from .contours import install as install_contours
from .images import add_images
from .layers import AtlasSurface, canonical_colors, match_label_colors
from .request import (
    REFERENCE_ROLES,
    MissingAssets,
    ViewRequestError,
    show_targets,
)
from .slicing import (
    DEFAULT_SLICE_AXIS,
    busiest_plane,
    compartment_spans,
    crosses,
    order_for,
)
from .view import (
    MIRROR_AXIS,
    apply_mirror,
    fit_view,
    install_home_orientation,
)

#: Distinct flat colors for contour overlays, one per atlas, so two atlases
#: superimposed in slice view are told apart by color rather than by shape.
ATLAS_CONTOUR_COLORS = [
    "#ff7f0e", "#1f77b4", "#2ca02c", "#d62728",
    "#9467bd", "#17becf", "#e377c2", "#bcbd22",
]

#: Reference geometry -- neuropil shells, whole brains -- gets a contour too,
#: muted and thin. Without one it has no representation in 2D at all: its
#: Surface is pulled from the layer list there, so an AL outline that was
#: perfectly visible in 3D simply vanished.
REFERENCE_CONTOUR_COLOR = "#9aa0a6"
REFERENCE_CONTOUR_WIDTH = 0.2

#: Whether 2D gets its own exact mesh-plane contour layers, or just shows
#: the Surface layers sliced by napari.
#:
#: Contours exist because nested semi-transparent surfaces stop being
#: readable past two atlases, and because napari's Surface returns no value
#: under the cursor in 2D, so they are also what makes a sliced glomerulus
#: clickable and what carries the per-glomerulus slice labels.
#:
#: On, and two layers per atlas is accepted as the cost.
#:
#: The hope was that showing the Surface layers in 2D would make the Shapes
#: layers unnecessary. It does not: napari slices a Surface by drawing the
#: triangles that straddle the plane, so what appears is their projected
#: footprint -- wide where the surface runs tangent to the slice, absent
#: where it runs perpendicular. A boundary mesh has no interior, so nothing
#: can fill it either. Drawing the exact contours FILLED did give a true
#: cross-section, but it still needed the Shapes layer, so it bought nothing
#: over the outlines and lost their even weight.
#:
#: So: outlines, and a Shapes layer beside every Surface layer.
USE_SLICE_CONTOURS = True


def _tag(meshset) -> str:
    """Mark bridged, degraded and mirrored layers in their name.

    Only ingest-time bridging reaches this now: an asset transformed into
    the space it is declared in, such as the FlyWire neuropils bridged
    FLYWIRE -> FAFB14. The viewer no longer bridges atlases across spaces.
    """
    params = meshset.meta.get("derivation", {}).get("params", {})
    if not params:
        return ""
    bits = ["bridged"]
    if params.get("degraded"):
        bits.append("DEGRADED")
    if params.get("mirror"):
        bits.append("mirrored")
    return " [" + ", ".join(bits) + "]"


def build_scene(
    viewer,
    registry: Registry,
    space: str,
    into=None,
) -> tuple[dict[str, AtlasSurface], dict[str, ContourOverlay]]:
    """Add every atlas native to `space`, plus that space's reference meshes.

    An atlas belongs to exactly one space and is only ever shown there. The
    viewer used to be able to bridge atlases in from other spaces, which made
    a scene's contents span vocabularies: each space names its glomeruli in
    its own terms, so a bridged atlas arrived with names the host space does
    not define, and the panel and the color palette had to reconcile them
    through a single global vocabulary. Dropping it is what lets nomenclature
    be per-space.

    Bridging survives where it is about DATA rather than display -- ingest
    puts an asset into its declared space, and `lobemap bridge` and
    `lobemap reconcile` still compare across spaces on the command line.

    `into` is a `SceneSession` to record into as each part is made, so a
    failure part-way leaves it holding everything it must tear down.
    """
    if space not in registry.spaces:
        raise ViewRequestError(
            f"unknown space {space!r}; known spaces: {', '.join(sorted(registry.spaces))}"
        )

    surfaces: dict[str, AtlasSurface] = {}
    if into is not None:
        into.surfaces = surfaces

    def _meta(surface, key, asset) -> None:
        surface.layer.metadata["lobemap"].update(
            id=key, asset=asset.id, role=asset.role
        )

    # Reference geometry first, so it sits underneath.
    for asset in registry.assets_in_space(space):
        if asset.role not in REFERENCE_ROLES:
            continue
        try:
            meshset = registry.mesh(asset.id)
        except (FileNotFoundError, KeyError):
            continue
        # Additive, not translucent: a translucent shell writes depth and so
        # hides the very glomeruli it is meant to give context to.
        surface = AtlasSurface(
            viewer, meshset, name=asset.id + _tag(meshset), opacity=0.35,
            blending="additive",
        )
        surface.layer.shading = "none"
        _meta(surface, asset.id, asset)
        surfaces[asset.id] = surface

    images = add_images(viewer, registry, space)
    if into is not None:
        into.images = images

    vocabulary = registry.vocabulary(space)
    for atlas in registry.atlases_in_space(space):
        try:
            meshset = registry.mesh(atlas.asset)
        except (FileNotFoundError, KeyError):
            continue
        surfaces[atlas.id] = AtlasSurface(
            viewer, meshset, name=(atlas.title or atlas.id) + _tag(meshset),
            # The SPACE's vocabulary, not a global one: a glomerulus is
            # one color across the atlases it can be compared with, which
            # is exactly the atlases sharing its space.
            colors=canonical_colors(atlas.compartments, vocabulary),
            display_names=[c.label for c in atlas.compartments] or None,
        )
        _meta(surfaces[atlas.id], atlas.id, registry.assets[atlas.asset])

    if not surfaces:
        raise MissingAssets(space, registry)

    # After the atlases, because the colors are read out of their Surface
    # layers rather than recomputed.
    for layer in images:
        if layer.metadata.get("lobemap", {}).get("kind") == "labels":
            match_label_colors(layer, list(surfaces.values()))

    contours: dict[str, ContourOverlay] = {}
    if into is not None:
        into.contours = contours
    if USE_SLICE_CONTOURS:
        _add_contours(viewer, registry, surfaces, into=contours)

    show_primary_atlas(registry, space, surfaces, contours)

    # Anatomical names for the dimension sliders and napari's own axis
    # overlay. No layer of our own: see `viewer/axes.py`. It shows the
    # anatomy in 3D and the voxel grid in 2D, and is kept up to date by
    # `install_display_mode`, whose handlers a scene switch disconnects
    # -- connecting here instead leaked one per switch.
    apply_axis_mode(viewer, registry.spaces[space])

    return surfaces, contours


def show_primary_atlas(registry: Registry, space: str, surfaces,
                       contours=None) -> None:
    """Select the space's primary atlas and nothing of anything else.

    Every atlas native to the space is loaded -- that is what makes them
    superposable -- but two glomerular parcellations drawn on top of each
    other are unreadable, so one opens. Reference geometry opens off too.

    Off means NOTHING SELECTED, not a hidden layer with every row still
    checked: the table's checkboxes are what is drawn, so a secondary atlas
    and a neuropil shell open with their rows unchecked and "0 / N shown",
    and `Show all` or a row tick is what turns them on.
    """
    primary = registry.primary_atlas(space)
    for name, surface in surfaces.items():
        if primary is not None and name == primary.id:
            continue
        surface.set_selection(set())
        if contours and name in contours:
            contours[name].selection = set()


def _add_contours(viewer, registry, surfaces, into=None) -> dict[str, ContourOverlay]:
    """One contour overlay per surface, including the reference geometry."""
    overlays: dict[str, ContourOverlay] = {} if into is None else into
    palette = iter(ATLAS_CONTOUR_COLORS * 4)
    for name, surface in surfaces.items():
        reference = name in registry.assets
        overlays[name] = ContourOverlay(
            viewer,
            surface.meshset,
            name=surface.name,
            color=REFERENCE_CONTOUR_COLOR if reference else next(palette),
            width=REFERENCE_CONTOUR_WIDTH if reference else 0.35,
            selection=set(surface.selection),
            # The atlas palette, so an outline and its label match the mesh.
            # Reference shells stay a single gray: they are context, and
            # coloring each neuropil would compete with the glomeruli.
            colors=None if reference else surface.colors,
            display_names=surface.display_names,
        )
    # The overlays carry their own event handlers, so a scene switch can
    # disconnect them without build_scene having to hand them back.
    handlers = install_contours(viewer, overlays)
    for overlay in overlays.values():
        overlay.handlers = handlers
    return overlays


class SceneSession:
    """One loaded space, and everything needed to unload it again.

    Switching space inside a live viewer is not just `layers.clear()`. The
    display-mode and contour hooks are bound to `viewer.dims.events`, which
    outlives any scene: left connected, they keep firing against surfaces
    whose layers have been removed, so the second scene ends up driven partly
    by the first. The compartment panel is a dock widget and has to be taken
    out of the window rather than dropped on the floor.

    So a session records exactly what it created, and `teardown` undoes it in
    reverse, touching nothing else: a switch builds the next session beside
    this one and only then tears this one down, so a failed build is undone
    without disturbing the scene the user is looking at. Rebuilding in place
    is what makes the switch cheap: the process, the Qt window and the GPU
    context all survive, and only the data is swapped.
    """

    def __init__(self, viewer, registry, space):
        self.viewer = viewer
        self.registry = registry
        self.space = space
        self.surfaces: dict = {}
        self.contours: dict = {}
        self.images: list = []
        self.panel = None
        self.dock = None
        self.handlers: list[tuple] = []
        #: Callbacks added to `viewer.mouse_move_callbacks`.
        self.callbacks: list = []
        #: Display-only left-right reflection. Held per session, so
        #: switching space rebuilds unmirrored and the control re-asserts
        #: itself rather than the state surviving invisibly.
        self.mirrored = False
        #: The plane it reflects about, measured once while unmirrored.
        self.mirror_center = 0.0
        #: The array axis 2D steps along.
        self.slice_axis = DEFAULT_SLICE_AXIS
        #: Whether the camera has been turned onto the anatomy yet. A scene
        #: opened in 2D is oriented the first time it enters 3D.
        self.oriented = False
        self._spans: dict[tuple[str, int], object] = {}

    def all_layers(self) -> list:
        """Every layer this session owns."""
        out = [s.layer for s in self.surfaces.values()]
        out += [c.layer for c in self.contours.values()]
        out += [layer for layer in self.images if layer not in out]
        return out

    def reflect_axis(self) -> int | None:
        """The array axis the scene is shown mirrored along, or None."""
        return MIRROR_AXIS if self.mirrored else None

    def set_mirror(self, on: bool) -> None:
        """Show the space reflected, or stop.

        The triads are re-derived rather than left alone: a mirror
        reverses handedness, so an unmirrored anatomical triad over
        mirrored data would name the wrong side, which is the single
        error this project has had to correct most often.
        """
        self.mirrored = bool(on)
        apply_mirror(self.all_layers(), self.mirrored, self.mirror_center)
        # The reflection reverses every triangle's orientation, so the
        # meshes are re-wound to keep them outward-facing. This does not
        # correct the shading; see `AtlasSurface._oriented`.
        for surface in self.surfaces.values():
            with contextlib.suppress(Exception):
                surface.set_mirrored(self.mirrored)
        space = self.registry.spaces.get(self.space)
        if space is not None:
            apply_axis_mode(self.viewer, space, mirror_axis=self.reflect_axis())
        for overlay in self.contours.values():
            with contextlib.suppress(Exception):
                overlay.refresh()

    def set_slice_axis(self, axis: int) -> None:
        """Step 2D along another array axis; image and contours follow.

        Remembered for the session, so 3D and back keeps it. The contours
        read the axis from `dims.order` and redraw when it changes. The view
        is refitted, since the camera was framing the other plane's axes.
        """
        self.slice_axis = int(axis)
        if self.viewer.dims.ndisplay == 3:
            return
        order = order_for(self.slice_axis)
        # Not a reason to stop: napari's roll button sets the order first,
        # and the new plane still has to be found.
        if tuple(self.viewer.dims.order) != order:
            self.viewer.dims.order = order
        space = self.registry.spaces.get(self.space)
        if space is not None:
            apply_axis_mode(self.viewer, space, mirror_axis=self.reflect_axis())
        self.populate_plane()
        fit_view(self.viewer)

    def _atlas_order(self) -> list[str]:
        primary = self.registry.primary_atlas(self.space)
        names = [n for n in self.surfaces if n in self.registry.atlases]
        return sorted(names, key=lambda n: primary is None or n != primary.id)

    def _world_spans(self, name: str, axis: int):
        key = (name, axis)
        if key not in self._spans:
            self._spans[key] = compartment_spans(self.surfaces[name].meshset, axis)
        spans = self._spans[key][sorted(self.surfaces[name].selection)]
        if self.mirrored and axis == MIRROR_AXIS:
            spans = 2.0 * self.mirror_center - spans[:, ::-1]
        return spans

    def populate_plane(self) -> bool:
        """Move a 2D slice that cuts no shown atlas onto one that does.

        napari opens each slider mid-range, and mid-range of a whole-brain
        volume is nowhere near the antennal lobe: FAFB14, the hemibrain and
        the male CNS all opened 2D on a plane with no glomerulus in it. A
        plane that cuts any shown atlas is the user's and is kept; an empty
        one moves to the plane cutting the most compartments of the first
        shown atlas, the primary one when it is shown. True if it moved.
        """
        shown = [n for n in self._atlas_order() if self.surfaces[n].selection]
        if not shown:
            return False
        axis = int(self.viewer.dims.order[0])
        point = float(self.viewer.dims.point[axis])
        spans = [self._world_spans(name, axis) for name in shown]
        if any(crosses(s, point) for s in spans):
            return False
        target = busiest_plane(spans[0])
        if target is None:
            return False
        # On the slider's own grid: napari snaps an off-grid point a moment
        # later, which drew every contour a second time on a neighbor plane.
        start, _stop, step = self.viewer.dims.range[axis]
        self.viewer.dims.set_current_step(axis, round((target - start) / step))
        return True

    def show(self, names) -> None:
        """Turn on what `--show` names: every compartment of a mesh, or a layer.

        Through the panel, so the table says what is drawn.
        """
        targets = show_targets(self.registry, self.space)
        wanted: set[str] = set()
        for name in names:
            if name not in targets:
                raise ViewRequestError(f"--show {name!r} names nothing in {self.space}")
            wanted |= targets[name]
        for key, surface in self.surfaces.items():
            if surface.layer.metadata["lobemap"].get("asset") not in wanted:
                continue
            tab = self.panel.tabs.get(key) if self.panel is not None else None
            if tab is not None:
                tab.select(range(surface.meshset.n_compartments))
            else:
                surface.show_all()
        for layer in self.images:
            if layer.metadata.get("lobemap", {}).get("asset") in wanted:
                layer.visible = True

    def reassert(self) -> None:
        """Take the viewer back after a scene built beside this one was dropped.

        Building a scene points two things that belong to the viewer at it:
        the axis triads and the home button. The dims, the camera and the
        layer selection are the switcher's to restore (`restore_view`); these
        are this session's, because they depend on its space and its mirror.
        """
        space = self.registry.spaces.get(self.space)
        if space is None:
            return
        apply_axis_mode(self.viewer, space, mirror_axis=self.reflect_axis())
        install_home_orientation(self.viewer, space, reflect_axis=self.reflect_axis)

    def settle_view(self) -> None:
        """Frame this scene once it is the only one loaded.

        It was built beside the scene it replaces, so the plane and the fit
        it got then were computed over both. In 2D the plane is put on this
        scene's own slider grid and onto its atlases; in either mode the
        view is fitted to what is left.
        """
        dims = self.viewer.dims
        # Onto the grid: napari snaps an off-grid point a moment later, and
        # the contours would be drawn a second time on the neighbor plane.
        dims.current_step = tuple(dims.current_step)
        self.set_slice_axis(self.slice_axis)
        if dims.ndisplay == 3:
            fit_view(self.viewer)

    def teardown(self) -> None:
        for event, handler in self.handlers:
            with contextlib.suppress(Exception):
                event.disconnect(handler)
        self.handlers = []
        for overlay in self.contours.values():
            for event, handler in getattr(overlay, "handlers", ()) or ():
                with contextlib.suppress(Exception):
                    event.disconnect(handler)
        for callback in self.callbacks:
            with contextlib.suppress(ValueError):
                self.viewer.mouse_move_callbacks.remove(callback)
        self.callbacks = []
        for surface in self.surfaces.values():
            surface.stop()
        # LAYERS FIRST, then the dock. The other order crashes the process.
        #
        # Removing a dock widget relays out the window, which resizes the
        # canvas and schedules a repaint. Dropping the layers after that has
        # been scheduled frees their GL resources underneath it, and the
        # next paint reads freed memory:
        #
        #   OSError: exception: access violation reading 0x34
        #     vispy/gloo/gl/_gl2.py in glDrawArrays
        #
        # It is 2D-only in practice, because in 3D the surfaces are the
        # layers being drawn and they are removed cleanly; in 2D the Shapes
        # contours are live at the moment the relayout lands. Clearing
        # first means the repaint has nothing stale to draw.
        #
        # This is the fault that went unexplained for several sessions: it
        # looked like a GRABE rendering bug because GRABE was the scene open
        # at the time, and it has no Python frame of its own to point at.
        # Confirmed by bisection -- dock-then-clear faults every run,
        # clear-then-dock survives, in both spaces tested.
        #
        # Only this session's layers. A switch builds the next scene before
        # tearing this one down, and a failed build tears down only itself,
        # so clearing the whole list would take the other scene with it.
        for layer in self.all_layers():
            with contextlib.suppress(Exception):
                if layer in self.viewer.layers:
                    self.viewer.layers.remove(layer)
        if self.dock is not None:
            with contextlib.suppress(Exception):
                self.viewer.window.remove_dock_widget(self.dock)
            # Removing it undocks it but leaves it a child of the window, so
            # one QDockWidget accumulated per scene switch.
            with contextlib.suppress(Exception):
                self.dock.deleteLater()
        self.dock = self.panel = None
        self.surfaces, self.contours, self.images = {}, {}, []


__all__ = [
    "ATLAS_CONTOUR_COLORS",
    "REFERENCE_CONTOUR_COLOR",
    "REFERENCE_CONTOUR_WIDTH",
    "USE_SLICE_CONTOURS",
    "SceneSession",
    "build_scene",
    "show_primary_atlas",
]
