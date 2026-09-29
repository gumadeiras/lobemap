"""Scene assembly and the napari application entry point.

This is the viewer's public module: `run` and `load_space` open a space, and
the image display defaults (`images`), the camera helpers (`view`) and the
request errors (`request`) are importable from here as well.
"""

from __future__ import annotations

import contextlib

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
#: the last two -- y-z -- and put the slider on x.
#:
#: **2D only.** In 3D napari applies `dims.order` to an Image but NOT to a
#: Surface: `surface/_slice.py` returns `self.data[0]` unpermuted as soon as
#: nothing is non-displayed, while `_scalar_field/_slice.py` always does
#: `np.transpose(data, order)`. A non-identity order in 3D therefore transposes
#: the stain out from under the meshes, with no warning -- it just looks like a
#: registration failure. So 3D keeps the identity order, where the two agree.
DIMS_ORDER_XYZ = (2, 1, 0)

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
                         space=None, mirror_axis=None) -> list[tuple]:
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
    - **`dims.order` is permuted only in 2D**, to put the slider on z. In 3D
      it must stay the identity, because napari permutes an Image by it and a
      Surface not at all (see `DIMS_ORDER_XYZ`).
    """
    for name, surface in surfaces.items():
        if name in contours:
            surface.pair(contours[name])

    def _apply(event=None) -> None:
        three_d = viewer.dims.ndisplay == 3
        ndim = viewer.dims.ndim
        # Identity in 3D, or the stain transposes away from the meshes.
        want_order = (
            tuple(range(ndim)) if three_d or ndim != 3 else DIMS_ORDER_XYZ
        )
        if tuple(viewer.dims.order) != want_order:
            viewer.dims.order = want_order
        # The triad shows the anatomy in 3D and the voxel grid in 2D,
        # and this is already the hook that fires on a mode change and
        # is torn down with the scene.
        if space is not None:
            # A callable, not a value: the mirror is toggled long after
            # this hook is installed, and the triads have to follow it.
            axis = mirror_axis() if callable(mirror_axis) else mirror_axis
            apply_axis_mode(viewer, space, mirror_axis=axis)
        for layer in images:
            info = layer.metadata.get("lobemap", {})
            if "level_3d" not in info:
                continue            # labels carry no pyramid to pin
            layer.locked_data_level = info["level_3d"] if three_d else None
        for surface in surfaces.values():
            surface.sync()

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
        )
    # The overlays carry their own event handlers, so a scene switch can
    # disconnect them without build_scene having to hand them back.
    handlers = install_contours(viewer, overlays)
    for overlay in overlays.values():
        overlay.handlers = handlers
    return overlays


def install_picking(viewer, surfaces, contours, panel=None) -> None:
    """Identify the glomerulus under the cursor, in 3D and in 2D.

    Surface._get_value_3d does ray-triangle intersection and returns the
    barycentric-interpolated vertex value; because compartments are disjoint
    meshes every triangle's vertices share one index, so that value IS the
    compartment index. In 2D Surface._get_value returns None, so the contour
    Shapes layer covers that case.
    """
    by_layer = {s.layer: (name, s) for name, s in surfaces.items()}
    contour_by_layer = {c.layer: (name, c) for name, c in contours.items()}

    def _on_move(layer, event):
        value = layer.get_value(
            event.position,
            view_direction=getattr(event, "view_direction", None),
            dims_displayed=getattr(event, "dims_displayed", None),
            world=True,
        )
        if isinstance(value, tuple):
            value = value[0]
        if value is None:
            return

        if layer in by_layer:
            name, surface = by_layer[layer]
            label = surface.name_at_value(value)
            index = round(float(value)) if label else None
        elif layer in contour_by_layer:
            name, overlay = contour_by_layer[layer]
            label = overlay.name_at_shape(int(value))
            index = (
                overlay.meshset.names.index(label) if label else None
            )
        else:
            return

        if label:
            viewer.status = f"{name}: {label}"
            if panel is not None and index is not None:
                panel.highlight(name, index)

    for surface in surfaces.values():
        surface.layer.mouse_move_callbacks.append(_on_move)
    for overlay in contours.values():
        overlay.layer.mouse_move_callbacks.append(_on_move)


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
        #: Display-only left-right reflection. Held per session, so
        #: switching space rebuilds unmirrored and the control re-asserts
        #: itself rather than the state surviving invisibly.
        self.mirrored = False
        #: The plane it reflects about, measured once while unmirrored.
        self.mirror_center = 0.0

    def all_layers(self) -> list:
        """Every layer this session owns."""
        out = [s.layer for s in self.surfaces.values()]
        out += [c.layer for c in self.contours.values()]
        out += [layer for layer in self.images if layer not in out]
        return out

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
            apply_axis_mode(
                self.viewer, space,
                mirror_axis=MIRROR_AXIS if self.mirrored else None,
            )
        for overlay in self.contours.values():
            with contextlib.suppress(Exception):
                overlay.refresh()

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
        install_picking(
            viewer, session.surfaces, session.contours, panel=session.panel
        )
        # Before any mirror is applied, so the plane is the data's own.
        session.mirror_center = mirror_center(
            [s.layer for s in session.surfaces.values()] + list(session.images)
        )
        session.handlers += install_display_mode(
            viewer, session.surfaces, session.contours, session.images,
            space=registry.spaces[space],
            mirror_axis=lambda: MIRROR_AXIS if session.mirrored else None,
        )
        if show:
            session.show(show)
        orient_anterior(viewer, registry.spaces[space])
        install_home_orientation(viewer, registry.spaces[space])
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
