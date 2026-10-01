"""What a space puts in the viewer, and the session that can take it out again.

`build_scene` adds a space's reference meshes, images and atlases, each atlas
with its slice contours; `SceneSession` records what one load created, so a
switch can tear it down again without touching anything else.
"""

from __future__ import annotations

import contextlib
from dataclasses import dataclass

from ..core.registry import Registry
from .axes import apply_axis_mode
from .contours import ContourOverlay
from .contours import install as install_contours
from .deferred import Deferred
from .images import add_images, show_images, stop_levels
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
    mirror_center,
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


@dataclass(frozen=True)
class ScenePart:
    """One mesh a space shows: a neuropil or brain shell, or an atlas."""

    #: The scene's key for it: the asset id of a shell, the atlas id.
    name: str
    asset: object
    #: None for reference geometry.
    atlas: object = None

    @property
    def reference(self) -> bool:
        return self.atlas is None


def scene_parts(registry: Registry, space: str) -> list[ScenePart]:
    """Every mesh `space` shows that is on disk, reference geometry first."""
    parts = [ScenePart(asset.id, asset)
             for asset in registry.assets_in_space(space)
             if asset.role in REFERENCE_ROLES and asset.path.exists()]
    for atlas in registry.atlases_in_space(space):
        asset = registry.assets.get(atlas.asset)
        if asset is not None and asset.path.exists():
            parts.append(ScenePart(atlas.id, asset, atlas))
    return parts


def contour_styles(parts) -> dict[str, tuple[str, float]]:
    """Each part's contour color and width, by its place in the scene.

    Assigned over every part, built or not, so an atlas built on first use
    gets the color it would have had.
    """
    palette = iter(ATLAS_CONTOUR_COLORS * 4)
    return {
        part.name: (REFERENCE_CONTOUR_COLOR, REFERENCE_CONTOUR_WIDTH)
        if part.reference else (next(palette), 0.35)
        for part in parts
    }


def make_surface(viewer, registry: Registry, space: str, part: ScenePart) -> AtlasSurface:
    """The Surface layer of one part, every compartment selected and resident.

    Made hidden: `AtlasSurface.sync` shows it in the mode that draws it.
    """
    meshset = registry.mesh(part.asset.id)
    if part.reference:
        # Additive, not translucent: a translucent shell writes depth and so
        # hides the very glomeruli it is meant to give context to.
        surface = AtlasSurface(
            viewer, meshset, name=part.asset.id + _tag(meshset), opacity=0.35,
            blending="additive", shading="none", visible=False,
        )
    else:
        atlas = part.atlas
        surface = AtlasSurface(
            viewer, meshset, name=(atlas.title or atlas.id) + _tag(meshset),
            # The SPACE's vocabulary, not a global one: a glomerulus is
            # one color across the atlases it can be compared with, which
            # is exactly the atlases sharing its space.
            colors=canonical_colors(atlas.compartments, registry.vocabulary(space)),
            display_names=[c.label for c in atlas.compartments] or None,
            visible=False,
        )
    surface.layer.metadata["lobemap"].update(
        id=part.name, asset=part.asset.id, role=part.asset.role
    )
    return surface


def make_contour(viewer, surface: AtlasSurface, style, reference: bool) -> ContourOverlay:
    """The slice contours of one surface, hidden until its display mode shows them."""
    color, width = style
    return ContourOverlay(
        viewer,
        surface.meshset,
        name=surface.name,
        color=color,
        width=width,
        selection=set(surface.selection),
        # The atlas palette, so an outline and its label match the mesh.
        # Reference shells stay a single gray: they are context, and
        # coloring each neuropil would compete with the glomeruli.
        colors=None if reference else surface.colors,
        display_names=surface.display_names,
    )


def build_scene(
    viewer,
    registry: Registry,
    space: str,
    into=None,
    defer: bool = False,
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

    With `defer`, which needs `into`, only the primary atlas is built. The
    other atlases and the reference shells open unchecked, so nothing of
    them is drawn, and building their meshes, layers and tables was most of
    what opening a space cost -- about 0.6 s of the hemibrain's. They are
    left in `into.pending` for `SceneSession.realize`, which builds each the
    first time it is needed, and in `into.deferred`, which gives each one
    reaching outside the rest a stand-in, so the sliders and the view span
    the whole scene from the start. The surfaces and images are left hidden
    for `load_space` to show once the mode, the plane and the pyramid level
    are set, so each is read once. Without it, everything is built and shown.
    """
    if space not in registry.spaces:
        raise ViewRequestError(
            f"unknown space {space!r}; known spaces: {', '.join(sorted(registry.spaces))}"
        )
    if defer and into is None:
        raise ValueError("defer needs a session to build the rest later")

    parts = scene_parts(registry, space)
    by_name = {part.name: part for part in parts}
    styles = contour_styles(parts)
    primary = registry.primary_atlas(space)
    surfaces: dict[str, AtlasSurface] = {}
    pending: dict[str, ScenePart] = {}
    later = {part.name: part for part in parts
             if defer and (primary is None or part.name != primary.id)}
    if into is not None:
        into.surfaces, into.pending = surfaces, pending
        into.parts, into.styles = by_name, styles
        if later:
            # Made first: it reads their bounds while the rest is built.
            into.deferred = Deferred(viewer, registry, later,
                                     show=lambda name: into.show([name]))

    def _add(part: ScenePart) -> None:
        if part.name in later:
            pending[part.name] = part
            return
        try:
            surfaces[part.name] = make_surface(viewer, registry, space, part)
        except (FileNotFoundError, KeyError):
            pass                    # unreadable: left out, as a missing file is

    # Reference geometry first, so it sits underneath.
    for part in parts:
        if part.reference:
            _add(part)

    images = add_images(viewer, registry, space)
    if into is not None:
        into.images = images

    for part in parts:
        if not part.reference:
            _add(part)

    if not surfaces and not pending:
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
        for name, surface in surfaces.items():
            contours[name] = make_contour(viewer, surface, styles[name],
                                          by_name[name].reference)
        # The overlays carry their own event handlers, so a scene switch can
        # disconnect them without build_scene having to hand them back. The
        # handlers read the dict itself, so an overlay added to it later is
        # kept in step too.
        handlers = install_contours(viewer, contours)
        for overlay in contours.values():
            overlay.handlers = handlers
        if into is not None:
            into.contour_handlers = handlers

    show_primary_atlas(registry, space, surfaces, contours)
    if not defer:
        for surface in surfaces.values():
            surface.sync()
        show_images(images)
    elif into.deferred is not None:
        into.deferred.hold(into.all_layers())

    # Anatomical names for the dimension sliders and napari's own axis
    # overlay. No layer of our own: see `viewer/axes.py`. It shows the
    # anatomy in 3D and the voxel grid in 2D, and is kept up to date by
    # `install_display_mode`, whose handlers a scene switch disconnects
    # -- connecting here instead leaked one per switch. `load_space`, which
    # defers, installs that display mode next, and it applies the triads
    # with the mirror: once is enough.
    if not defer:
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
        #: Every mesh the space shows, by scene key, built or not.
        self.parts: dict[str, ScenePart] = {}
        #: The parts not built yet; see `realize`.
        self.pending: dict[str, ScenePart] = {}
        #: Their stand-ins; see `deferred`.
        self.deferred: Deferred | None = None
        #: Each part's contour color and width.
        self.styles: dict[str, tuple] = {}
        #: The contour handlers every overlay shares; see `build_scene`.
        self.contour_handlers: list[tuple] = []
        #: Display-only left-right reflection. Held per session, so
        #: switching space rebuilds unmirrored and the control re-asserts
        #: itself rather than the state surviving invisibly.
        self.mirrored = False
        self._mirror_center: float | None = None
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
        if self.deferred is not None:
            out += self.deferred.layers()
        return out

    def reflect_axis(self) -> int | None:
        """The array axis the scene is shown mirrored along, or None."""
        return MIRROR_AXIS if self.mirrored else None

    @property
    def mirror_center(self) -> float:
        """The plane the mirror reflects about: the mid-plane of the scene.

        Every part counts, built or not, so the plane is the same whichever
        tabs have been opened: a part not built yet lies within the layers
        there are, or has a stand-in that spans it (`deferred`). It is also
        the mid-plane of the sliders, which span the same layers, so the
        reflected slider grid is the same grid and the plane stays on it.
        Measured while nothing is mirrored, because `extent.world` includes
        the reflection, and held while the mirror is on.
        """
        if self.mirrored and self._mirror_center is not None:
            return self._mirror_center
        return mirror_center(self.all_layers())

    def realize(self, name: str):
        """Build a part `build_scene` deferred; return its surface and contours.

        The first time it is needed -- its tab opened, or `--show` naming it
        -- and not before. Built as every part used to be at load: all its
        geometry resident, hidden, nothing selected, so showing it is the
        cheap alpha change it always was, and its extent is what it was. It
        gets its contours and their color, the pairing that draws it in the
        right layer for the mode, the mirror, and its place in the layer
        stack, and its stand-in, if it had one, goes once it is in. The
        layer selection is left as the user had it. All or nothing: a
        failure removes whatever was added.
        """
        if name in self.surfaces:
            return self.surfaces[name], self.contours.get(name)
        part = self.pending[name]
        layers = self.viewer.layers
        selected, active = list(layers.selection), layers.selection.active
        added = []
        try:
            surface = make_surface(self.viewer, self.registry, self.space, part)
            added.append(surface.layer)
            surface.set_selection(set())
            contour = None
            if USE_SLICE_CONTOURS:
                contour = make_contour(self.viewer, surface, self.styles[name],
                                       part.reference)
                added.append(contour.layer)
                contour.handlers = self.contour_handlers
                surface.pair(contour)
            surface.sync()          # nothing selected: both layers off
            self._stack(surface.layer, self._rank(name))
            if contour is not None:
                self._stack(contour.layer, self._rank(name, contour=True))
            if self.mirrored:
                apply_mirror(added, True, self.mirror_center)
                surface.set_mirrored(True)
        except BaseException:
            for layer in added:
                with contextlib.suppress(Exception):
                    layers.remove(layer)
            raise
        del self.pending[name]
        self.surfaces[name] = surface
        if contour is not None:
            self.contours[name] = contour
        if self.deferred is not None:
            self.deferred.release(name)
        with contextlib.suppress(Exception):
            layers.selection.clear()
            layers.selection.update(selected)
            if active in selected:
                layers.selection.active = active
        return surface, contour

    def _rank(self, name: str, contour: bool = False) -> int:
        """Where a part's layer sits, bottom first, as `build_scene` adds them:
        shells, images, atlases, then every contour layer."""
        position = list(self.parts).index(name)
        if contour:
            return 30_000 + position
        return position if self.parts[name].reference else 20_000 + position

    def _stack(self, layer, rank: int) -> None:
        """Move `layer`, just added on top, under this scene's layers ranked above it."""
        ranks = {id(image): 10_000 + i for i, image in enumerate(self.images)}
        for key, surface in self.surfaces.items():
            ranks[id(surface.layer)] = self._rank(key)
        for key, overlay in self.contours.items():
            ranks[id(overlay.layer)] = self._rank(key, contour=True)
        layers = self.viewer.layers
        above = [i for i, other in enumerate(layers) if ranks.get(id(other), -1) > rank]
        if above:
            layers.move(layers.index(layer), min(above))

    def set_mirror(self, on: bool) -> None:
        """Show the space reflected, or stop.

        The triads are re-derived rather than left alone: a mirror
        reverses handedness, so an unmirrored anatomical triad over
        mirrored data would name the wrong side, which is the single
        error this project has had to correct most often.
        """
        if on and not self.mirrored:
            self._mirror_center = self.mirror_center
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

        Through the panel, so the table says what is drawn; a part not built
        yet is built for it.
        """
        targets = show_targets(self.registry, self.space)
        wanted: set[str] = set()
        for name in names:
            if name not in targets:
                raise ViewRequestError(f"--show {name!r} names nothing in {self.space}")
            wanted |= targets[name]
        for key, part in self.parts.items():
            if part.asset.id not in wanted:
                continue
            if key not in self.surfaces and key not in self.pending:
                continue                    # could not be read
            if self.panel is not None:
                tab = self.panel.tab(key)
                if tab is not None:
                    tab.select(range(tab.surface.meshset.n_compartments))
            else:
                self.realize(key)[0].show_all()
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
        stop_levels(self.images)
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
        self.pending, self.deferred = {}, None


__all__ = [
    "ATLAS_CONTOUR_COLORS",
    "REFERENCE_CONTOUR_COLOR",
    "REFERENCE_CONTOUR_WIDTH",
    "USE_SLICE_CONTOURS",
    "ScenePart",
    "SceneSession",
    "build_scene",
    "contour_styles",
    "make_contour",
    "make_surface",
    "scene_parts",
    "show_primary_atlas",
]
