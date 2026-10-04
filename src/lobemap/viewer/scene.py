"""What a space puts in the viewer, and the session that can take it out again.

`build_scene` adds a space's reference meshes, images and atlases, each atlas
with its slice contours; `SceneSession` records what one load created, so a
switch can tear it down again without touching anything else. How the scene
is turned, mirrored and flipped is `pose`'s.
"""

from __future__ import annotations

import contextlib
import re

from ..core.registry import Registry
from . import prefetch
from .axes import apply_axis_mode
from .contours import ContourOverlay
from .contours import install as install_contours
from .deferred import Deferred
from .images import add_images, show_images, stop_levels
from .layers import AtlasSurface, match_label_colors
from .parts import (
    ATLAS_CONTOUR_COLORS,
    REFERENCE_CONTOUR_COLOR,
    REFERENCE_CONTOUR_WIDTH,
    ScenePart,
    contour_styles,
    make_contour,
    make_surface,
    scene_parts,
)
from .pose import ScenePose
from .request import MissingAssets, ViewRequestError, show_targets
from .rotation import register
from .slicing import (
    DEFAULT_SLICE_AXIS,
    busiest_plane,
    compartment_spans,
    crosses,
)
from .turned import TurnedView
from .view import (
    MIRROR_AXIS,
    apply_mirror,
    center_sliders,
    fit_view,
    install_home_orientation,
)

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

#: The number napari puts after a layer name another layer already has.
_NUMBERED = re.compile(r" \[\d+\]$")


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
    are set, so each is read once; beside another scene, the sliders are set
    once it is gone (`SceneSession.settle_view`), and a 2D image is read
    again there. Without it, everything is built and shown.
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
            # Made first: its thread reads their corners while the rest is
            # built, and then their meshes.
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
    else:
        if into.deferred is not None:
            into.deferred.hold(into.all_layers())
        # napari opens the sliders mid-way along the first layer it is
        # given, and a scene built whole adds its first neuropil set first,
        # or else its image. Deferred, that set is no layer yet, and a scene
        # built beside the one it replaces is not the first: so a slice axis
        # chosen right after the open landed on another plane, 26 um off on x
        # in FAFB14. The sliders are put there, on this scene's own grid:
        # beside another scene, once it is gone (`SceneSession.settle_view`).
        first = parts[0]
        bounds = (into.deferred.bounds(first.name)
                  if first.reference and into.deferred is not None else None)
        if bounds is not None:
            into.sliders = (*bounds, 1.0)
        elif images:
            extent = viewer.layers.get_extent([images[0]])
            into.sliders = (*extent.world, extent.step)
        if len(viewer.layers) == len(into.all_layers()):
            into.open_sliders()

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


class SceneSession(ScenePose):
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
        #: Callbacks added to the viewer's mouse move and drag callbacks.
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
        #: Where the sliders go, as `center_sliders` takes it; see `open_sliders`.
        self.sliders: tuple | None = None
        self._spans: dict[tuple[str, int], object] = {}
        #: The angles the scene is turned by, and what they move; see `turned`.
        self.turned = TurnedView(self)

    def all_layers(self) -> list:
        """Every layer this session owns."""
        out = [s.layer for s in self.surfaces.values()] + self.affine_layers()
        if self.deferred is not None:
            out += self.deferred.layers()
        return out

    def affine_layers(self) -> list:
        """The layers the mirror moves by `layer.affine`: the contours and
        images. The surfaces and their stand-ins reflect their own vertices
        (`AtlasSurface._present`, `Deferred.set_mirror`).
        """
        out = [c.layer for c in self.contours.values()]
        out += [layer for layer in self.images if layer not in out]
        return out

    def realize(self, name: str):
        """Build a part `build_scene` deferred; return its surface and contours.

        The first time it is needed -- its tab opened, or `--show` naming it
        -- and not before. Built as every part used to be at load: all its
        geometry resident, hidden, nothing selected, so showing it is the
        cheap alpha change it always was, and its extent is what it was. It
        gets its contours and their color, the pairing that draws it in the
        right layer for the mode, the mirror, and its place in the layer
        stack. Its mesh layer is its stand-in, if it had one, taken over. The
        layer selection is left as the user had it. All or nothing: a
        failure removes whatever was added.
        """
        if name in self.surfaces:
            return self.surfaces[name], self.contours.get(name)
        with prefetch.held():
            return self._realize(name)

    def _realize(self, name: str):
        part = self.pending[name]
        if self.deferred is not None:
            # Read by the thread `build_scene` started; a read under way is
            # waited for, so the mesh is read once and not here (`deferred`).
            self.deferred.wait(name)
        meshset = self.registry.mesh(part.asset.id)
        stand_in = self.deferred.adopt(name) if self.deferred is not None else None
        layers = self.viewer.layers
        selected, active = list(layers.selection), layers.selection.active
        added = [] if stand_in is None else [stand_in]
        try:
            surface = make_surface(
                self.viewer, self.registry, self.space, part, meshset, layer=stand_in,
                mirror=(MIRROR_AXIS, self.mirror_center) if self.mirrored else None)
            if stand_in is None:
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
            if self.mirrored and contour is not None:
                apply_mirror([contour.layer], True, self.mirror_center)
            if contour is not None:
                # Placed on the turned plane, as the parts already built are.
                self.turned.adopt(contour)
        except BaseException:
            for layer in added:
                with contextlib.suppress(Exception):
                    layers.remove(layer)
            raise
        del self.pending[name]
        self.surfaces[name] = surface
        if contour is not None:
            self.contours[name] = contour
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
        """Move `layer` under this scene's layers ranked above it, or on top.

        Just added, it is on top; a stand-in taken over is at the bottom.
        """
        ranks = {id(image): 10_000 + i for i, image in enumerate(self.images)}
        for key, surface in self.surfaces.items():
            ranks[id(surface.layer)] = self._rank(key)
        for key, overlay in self.contours.items():
            ranks[id(overlay.layer)] = self._rank(key, contour=True)
        layers = self.viewer.layers
        above = [i for i, other in enumerate(layers) if ranks.get(id(other), -1) > rank]
        layers.move(layers.index(layer), min(above) if above else len(layers))

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

        A view turned across the grid keeps its plane: it passes through the
        pivot, and the spans here are along the grid. The plane a turn put
        back at rest is put back first (`TurnedView.take_plane`).
        """
        plane = self.turned.take_plane()
        if plane is not None and int(self.viewer.dims.order[0]) == plane[0]:
            self.viewer.dims.set_point(*plane)
        if self.turned.kind not in (None, "spin"):
            return False
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
        register(self.viewer, self.turned)
        space = self.registry.spaces.get(self.space)
        if space is None:
            return
        apply_axis_mode(self.viewer, space, mirror_axis=self.reflect_axis())
        install_home_orientation(self.viewer, space, reflect_axis=self.reflect_axis)

    def open_sliders(self, keep=()) -> None:
        """Put the sliders where `build_scene` found them to go, once, but for
        the axes in `keep`."""
        if self.sliders is not None:
            sliders, self.sliders = self.sliders, None
            center_sliders(self.viewer, *sliders, keep=keep)

    def take_names(self) -> None:
        """Give each layer back the name napari numbered, once the scene it
        was built beside is gone.

        napari keeps layer names unique, and the next scene is built while
        the open one is still there: a name both have -- "Neuropil stain
        (from synapses)", "neuPrint · 3D" -- came out "... [1]".
        """
        for layer in self.all_layers():
            name = _NUMBERED.sub("", layer.name)
            if name != layer.name:
                layer.name = name

    def settle_view(self) -> None:
        """Frame this scene once it is the only one loaded.

        It was built beside the scene it replaces, so the plane and the fit
        it got then were computed over both. The sliders are put where this
        scene alone puts them (`open_sliders`), in 3D once 2D is entered. In
        2D the plane is put on this scene's own slider grid and onto its
        atlases; in either mode the view is fitted to what is left.
        """
        dims = self.viewer.dims
        if self.sliders is not None and dims.ndisplay == 3:
            # They draw nothing in 3D, and moving them draws every surface
            # anew, 46 of 55 ms in the hemibrain: so not until 2D is entered.
            # The plane then stays at the camera's depth, where napari puts
            # it, and this scene's own handlers draw it after this one.
            def _entered(event=None) -> None:
                if dims.ndisplay == 2:
                    dims.events.ndisplay.disconnect(_entered)
                    self.handlers.remove((dims.events.ndisplay, _entered))
                    self.open_sliders(keep=dims.not_displayed)

            dims.events.ndisplay.connect(_entered, position="first")
            self.handlers.append((dims.events.ndisplay, _entered))
        else:
            self.open_sliders()
        # Onto the grid: napari snaps an off-grid point a moment later, and
        # the contours would be drawn a second time on the neighbor plane.
        dims.current_step = tuple(dims.current_step)
        self.set_slice_axis(self.slice_axis)
        if dims.ndisplay == 3:
            fit_view(self.viewer)

    def teardown(self) -> None:
        self.turned.close()
        for event, handler in self.handlers:
            with contextlib.suppress(Exception):
                event.disconnect(handler)
        self.handlers = []
        for overlay in self.contours.values():
            for event, handler in getattr(overlay, "handlers", ()) or ():
                with contextlib.suppress(Exception):
                    event.disconnect(handler)
        for callback in self.callbacks:
            for callbacks in (self.viewer.mouse_move_callbacks,
                              self.viewer.mouse_drag_callbacks):
                with contextlib.suppress(ValueError):
                    callbacks.remove(callback)
        self.callbacks = []
        for surface in self.surfaces.values():
            surface.stop()
        stop_levels(self.images)
        if self.deferred is not None:
            self.deferred.stop()
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
