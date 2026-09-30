"""Scene assembly and the napari application entry point.

This is the viewer's public module: `run` and `load_space` open a space, and
the image display defaults (`images`), the camera helpers (`view`) and the
request errors (`request`) are importable from here as well.
"""

from __future__ import annotations

import contextlib

import numpy as np

from ..core.registry import Registry
from .axes import apply_axis_mode
from .contours import ContourOverlay
from .contours import install as install_contours
from .images import (
    BASE_DISPLAY,
    ROLE_DISPLAY,
    VIEW3D_MAX_AXIS,
    VIEW3D_MAX_VOXELS,
    add_images,
    default_colormap,
    display_for,
    level_for_3d,
)
from .layers import AtlasSurface, canonical_colors, match_label_colors
from .request import (
    REFERENCE_ROLES,
    MissingAssets,
    ViewRequestError,
    check_request,
    show_targets,
)
from .slicing import (
    DEFAULT_SLICE_AXIS,
    busiest_plane,
    compartment_spans,
    crosses,
    order_for,
    polygon_at,
)
from .view import (
    GIMBAL_NUDGE_DEG,
    MIRROR_AXIS,
    apply_mirror,
    fit_view,
    install_home_orientation,
    install_initial_fit,
    maximize,
    mirror_center,
    orient_anterior,
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

#: Slice x-y and step through z, the way a confocal stack is read. Volume axes
#: are (x, y, z) to match the mesh columns, and napari would otherwise display
#: the last two -- y-z -- and put the slider on x. The slice-axis control
#: picks another order; see `slicing.order_for`.
#:
#: **2D only.** In 3D napari applies `dims.order` to an Image but NOT to a
#: Surface: `surface/_slice.py` returns `self.data[0]` unpermuted as soon as
#: nothing is non-displayed, while `_scalar_field/_slice.py` always does
#: `np.transpose(data, order)`. A non-identity order in 3D therefore transposes
#: the stain out from under the meshes, with no warning -- it just looks like a
#: registration failure. So 3D keeps the identity order, where the two agree.
DIMS_ORDER_XYZ = order_for(DEFAULT_SLICE_AXIS)

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


def install_display_mode(viewer, surfaces, contours, images=(),
                         session=None) -> list[tuple]:
    """Show only what the current `ndisplay` can actually use.

    Returns (event, handler) pairs, so a scene switch can disconnect them;
    see `contours.install`.

    Pairs each surface with its contour overlay, and from then on switches
    them together on 2D/3D:

    - **Meshes in 3D, contours in 2D.** Each atlas draws its selection in
      the layer the mode can read, and hides the other; see
      `AtlasSurface.sync`. Nothing is remembered across a switch, so what
      is checked is what is drawn after any sequence of switches.
      Layers are hidden, never removed from the list: removing a Surface
      layer while the Layer object lives on leaves a stale GL resource, and
      the next scene switch in 2D faulted in `glDrawArrays` on it.
    - **Images pin a pyramid level in 3D.** napari's automatic choice there is
      the coarsest level; `level_for_3d` picks the finest one that fits in a
      texture. In 2D the lock is released so zoom-driven selection works.
    - **`dims.order` is permuted only in 2D**, to put the slider on the
      chosen slice axis. In 3D it must stay the identity, because napari
      permutes an Image by it and a Surface not at all (see `DIMS_ORDER_XYZ`).

    With a `session`, it also moves an empty 2D slice onto the shown atlases,
    follows the mirror and the slice axis, sets the panel's 2D-only controls,
    and turns the camera onto the anatomy the first time 3D is entered.
    """
    for name, surface in surfaces.items():
        if name in contours:
            surface.pair(contours[name])

    def _apply(event=None) -> None:
        three_d = viewer.dims.ndisplay == 3
        ndim = viewer.dims.ndim
        axis = session.slice_axis if session is not None else DEFAULT_SLICE_AXIS
        want_order = (
            tuple(range(ndim)) if three_d or ndim != 3 else order_for(axis)
        )
        if tuple(viewer.dims.order) != want_order:
            viewer.dims.order = want_order
        space = None
        if session is not None:
            space = session.registry.spaces.get(session.space)
            # After the order: the triads are drawn for the displayed axes.
            if space is not None:
                apply_axis_mode(viewer, space, mirror_axis=session.reflect_axis())
        for layer in images:
            info = layer.metadata.get("lobemap", {})
            if "level_3d" not in info:
                continue            # labels carry no pyramid to pin
            layer.locked_data_level = info["level_3d"] if three_d else None
        if not three_d and session is not None:
            # Before the contours turn on, so they draw once, on this plane.
            session.populate_plane()
        for surface in surfaces.values():
            surface.sync()
        if session is None:
            return
        if session.panel is not None:
            session.panel.set_mode(three_d)
        if three_d and not session.oriented and space is not None:
            session.oriented = orient_anterior(
                viewer, space, reflect_axis=session.reflect_axis()
            )

    # Applied before it is connected, so a failure here leaves nothing behind.
    _apply()
    viewer.dims.events.ndisplay.connect(_apply)
    return [(viewer.dims.events.ndisplay, _apply)]


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


def install_picking(viewer, surfaces, contours, panel=None) -> list:
    """Identify the glomerulus under the cursor, in 3D and in 2D.

    Returns the viewer callbacks it added, so a scene switch can remove them.

    On the VIEWER, not on each layer. napari sends a layer's mouse-move
    callbacks only while that layer is the active one, and the active layer
    after a load is the last one added -- a contour layer, hidden in 3D --
    so hovering named nothing until the user happened to select the right
    layer by hand. The viewer's callbacks run on every move, and this asks
    each layer the current mode draws: surfaces in 3D, contours in 2D, the
    atlases before the reference shells.

    In 3D the ray is tested against the shown compartments' boxes and then
    their triangles (`AtlasSurface.pick`), not against every triangle of
    the layer as napari's own Surface pick does -- 40 ms a mouse move on
    Benton. In 2D the contour loops are tested directly, inside the loop
    rather than on its stroke. `Shapes.get_value` cannot be used for them:
    napari rounds each shape's slice position to a whole number and compares
    it with the unrounded plane, so off a whole-micrometer plane it found no
    shape at all. Drags are skipped: they rotate or pan the view.
    """
    order = sorted(
        surfaces,
        key=lambda n: surfaces[n].layer.metadata.get("lobemap", {}).get("role")
        in REFERENCE_ROLES,
    )

    def _on_move(_viewer, event):
        if getattr(event, "buttons", None):
            return          # a drag: rotating or panning, not pointing
        three_d = viewer.dims.ndisplay == 3
        for name in order:
            surface = surfaces[name]
            overlay = contours.get(name)
            if three_d or overlay is None:
                if not surface.layer.visible or not three_d:
                    continue
                index = surface.pick(
                    event.position,
                    getattr(event, "view_direction", None),
                    getattr(event, "dims_displayed", None) or viewer.dims.displayed,
                )
                label = surface.meshset.names[index] if index is not None else None
            else:
                if not overlay.layer.visible:
                    continue
                shown = list(viewer.dims.displayed)
                point = overlay.layer.world_to_data(event.position)
                shape = polygon_at(
                    [np.asarray(path)[:, shown] for path in overlay.layer.data],
                    np.asarray(point)[shown],
                )
                label = overlay.name_at_shape(shape)
                index = overlay.meshset.names.index(label) if label else None
            if label:
                shown_as = surface.display_names[index] if index is not None else label
                viewer.status = f"{name}: {shown_as}"
                if panel is not None and index is not None:
                    panel.highlight(name, index)
                return

    viewer.mouse_move_callbacks.append(_on_move)
    return [_on_move]


class SceneSession:
    """One loaded space, and everything needed to unload it again.

    Switching space inside a live viewer is not just `layers.clear()`. The
    display-mode and contour hooks are bound to `viewer.dims.events`, which
    outlives any scene: left connected, they keep firing against surfaces
    whose layers have been removed, so the second scene ends up driven partly
    by the first. The compartment panel is a dock widget and has to be taken
    out of the window rather than dropped on the floor.

    So a session records exactly what it created, and `teardown` undoes it in
    reverse. Rebuilding in place is what makes the switch cheap: the process,
    the Qt window and the GPU context all survive, and only the data is
    swapped.
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
        with contextlib.suppress(Exception):
            self.viewer.layers.clear()
        if self.dock is not None:
            with contextlib.suppress(Exception):
                self.viewer.window.remove_dock_widget(self.dock)
            # Removing it undocks it but leaves it a child of the window, so
            # one QDockWidget accumulated per scene switch.
            with contextlib.suppress(Exception):
                self.dock.deleteLater()
        self.dock = self.panel = None
        self.surfaces, self.contours, self.images = {}, {}, []


def load_space(
    viewer,
    registry: Registry,
    space: str,
    show: tuple[str, ...] = (),
    fit: bool = True,
) -> SceneSession:
    """Build a scene into a viewer that may already hold one.

    All or nothing: anything that fails part-way -- a corrupt asset, a
    `--show` naming nothing -- tears down what was already built before the
    error propagates, so no layer, dock or handler of a failed scene stays
    behind to be driven by the next one.
    """
    session = SceneSession(viewer, registry, space)
    try:
        build_scene(viewer, registry, space, into=session)

        from .panel import CompartmentPanel

        session.panel = CompartmentPanel(
            viewer, session.surfaces, registry=registry,
            contours=session.contours, space=space,
        )
        session.dock = viewer.window.add_dock_widget(
            session.panel, area="right", name="Compartments"
        )
        session.callbacks += install_picking(
            viewer, session.surfaces, session.contours, panel=session.panel
        )
        # Before any mirror is applied, so the plane is the data's own.
        session.mirror_center = mirror_center(
            [s.layer for s in session.surfaces.values()] + list(session.images)
        )
        session.handlers += install_display_mode(
            viewer, session.surfaces, session.contours, session.images,
            session=session,
        )
        if show:
            session.show(show)
        install_home_orientation(viewer, registry.spaces[space],
                                 reflect_axis=session.reflect_axis)
    except BaseException:
        session.teardown()
        raise
    if fit:
        install_initial_fit(viewer)
    return session


def run(
    registry_root,
    space: str | None = None,
    ndisplay: int = 3,
    show: tuple[str, ...] = (),
    data_root=None,
) -> None:
    """Open `space` in a new window and run the event loop.

    Everything that can be checked without a window is checked first --
    the space, `--show`, and whether the data is on disk -- so a mistake
    is a one-line error instead of a traceback behind an empty window.
    `show` applies to this first scene only; a space picked later opens
    with its own defaults.
    """
    import napari

    registry = Registry.load(registry_root, data_root=data_root)
    if space is None:
        raise ViewRequestError("need a space")
    check_request(registry, space, show, on_disk=True)

    viewer = napari.Viewer(title=f"lobemap - {space}", ndisplay=ndisplay)
    try:
        def _load(target: str, show: tuple[str, ...] = ()):
            session = load_space(viewer, registry, target, show=show)
            viewer.title = f"lobemap - {session.space}"
            return session

        session = _load(space, tuple(show))

        from .switcher import SpaceSwitcher

        switcher = SpaceSwitcher(viewer, registry, session, _load)
        # Added ONCE and never torn down, unlike the compartment panel: it is
        # the control that does the switching, so it cannot be owned by the
        # scene it replaces. Right, beside the compartment panel and above it:
        # the two are the scene's controls, and which space is open is read
        # before anything about it.
        switcher.dock = viewer.window.add_dock_widget(
            switcher, area="right", name="Space", tabify=False
        )
        switcher.settle()
    except BaseException:
        viewer.close()
        raise

    maximize(viewer)
    # Maximizing is asynchronous, so the fit follows the canvas rather than
    # running once and hoping. `load_space` already installed one; this is
    # after the dock widgets, which change the canvas size.
    install_initial_fit(viewer)
    napari.run()


__all__ = [
    "BASE_DISPLAY",
    "DIMS_ORDER_XYZ",
    "GIMBAL_NUDGE_DEG",
    "MIRROR_AXIS",
    "REFERENCE_CONTOUR_COLOR",
    "ROLE_DISPLAY",
    "VIEW3D_MAX_AXIS",
    "VIEW3D_MAX_VOXELS",
    "MissingAssets",
    "SceneSession",
    "ViewRequestError",
    "build_scene",
    "check_request",
    "default_colormap",
    "display_for",
    "fit_view",
    "install_display_mode",
    "install_home_orientation",
    "install_initial_fit",
    "install_picking",
    "level_for_3d",
    "load_space",
    "maximize",
    "orient_anterior",
    "run",
    "show_primary_atlas",
    "show_targets",
]
