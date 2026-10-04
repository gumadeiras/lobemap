"""The napari application entry point, and the hooks that drive a scene.

This is the viewer's public module: `run` and `load_space` open a space, and
the scene assembly (`scene`), the image display defaults (`images`), the
camera helpers (`view`) and the request errors (`request`) are importable
from here as well.
"""

from __future__ import annotations

import contextlib
import weakref

import numpy as np

from ..core.registry import Registry
from . import buttons
from .axes import apply_axis_mode
from .chrome import add_dock, lock_layers, tidy
from .images import (
    BASE_DISPLAY,
    ROLE_DISPLAY,
    VIEW3D_MAX_AXIS,
    VIEW3D_MAX_VOXELS,
    default_colormap,
    display_for,
    level_for_3d,
    pin_level,
    show_images,
)
from .napari_private import before_slicing
from .request import (
    REFERENCE_ROLES,
    MissingAssets,
    ViewRequestError,
    check_request,
    show_targets,
)
from .scene import (
    REFERENCE_CONTOUR_COLOR,
    SceneSession,
    build_scene,
    show_primary_atlas,
)
from .slicing import DEFAULT_SLICE_AXIS, order_for, polygon_at
from .view import (
    MIRROR_AXIS,
    fit_view,
    install_home_orientation,
    install_initial_fit,
    keep_orientation,
    maximize,
    orient_anterior,
)

#: The compartment panel's dock, on the right.
PANEL_TITLE = "Glomeruli and neuropils"

#: The View dock, on the left; see `switcher`.
VIEW_TITLE = "View"

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
      texture, read in the background when it is large (`images.FineLevel`).
      In 2D the lock is released so zoom-driven selection works.
    - **`dims.order` is permuted only in 2D**, to put the slider on the
      chosen slice axis. In 3D it must stay the identity, because napari
      permutes an Image by it and a Surface not at all (see `DIMS_ORDER_XYZ`).

    - **The 2D plane is kept through 3D.** On the way back napari puts the
      slider of the first axis in the order at the camera's depth, which in
      3D's identity order is x: a plane chosen on x was lost, the others
      kept. So the plane 2D left on is put back on its axis.

    With a `session`, it also moves an empty 2D slice onto the shown atlases,
    follows the mirror and the slice axis, sets the panel's 2D-only controls,
    and turns the camera onto the anatomy the first time 3D is entered.
    """
    for name, surface in surfaces.items():
        if name in contours:
            surface.pair(contours[name])

    #: The slice axis and plane 2D was on when it last left for 3D.
    left: dict = {}

    def _apply(event=None) -> None:
        three_d = viewer.dims.ndisplay == 3
        ndim = viewer.dims.ndim
        axis = session.slice_axis if session is not None else DEFAULT_SLICE_AXIS
        if event is not None and ndim == 3:
            # An event is a change of mode. Leaving 2D, the order is still
            # 2D's and the plane where the user left it.
            if three_d:
                slider = int(viewer.dims.order[0])
                left.update(axis=slider, point=float(viewer.dims.point[slider]))
            elif left.pop("axis", None) == axis:
                viewer.dims.set_point(axis, left.pop("point"))
        want_order = (
            tuple(range(ndim)) if three_d or ndim != 3 else order_for(axis)
        )
        shown_later = False
        if tuple(viewer.dims.order) != want_order:
            if three_d and event is not None:
                # napari announces a change of order only once every handler
                # of this change of mode has run, and slices every visible
                # layer again then. A mesh shown before it would be built
                # twice, its normals computed each time: 0.22 s of GRABE's
                # 0.48 s. So the meshes are shown once the order is in.
                # Connected first, in case napari announces it at once.
                shown_later = True

                def _ordered(_event=None) -> None:
                    viewer.dims.events.order.disconnect(_ordered)
                    for surface in surfaces.values():
                        surface.sync()

                viewer.dims.events.order.connect(_ordered)
            viewer.dims.order = want_order
        space = None
        if session is not None:
            space = session.registry.spaces.get(session.space)
            # After the order: the triads are drawn for the displayed axes.
            if space is not None:
                apply_axis_mode(viewer, space, mirror_axis=session.reflect_axis())
        for layer in images:
            pin_level(layer, three_d)
        if not three_d and session is not None:
            # Before the contours turn on, so they draw once, on this plane.
            session.populate_plane()
        if not shown_later:
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
    _meshes_of(viewer).update(surfaces.values())
    return [(viewer.dims.events.ndisplay, _apply)]


#: Each viewer's atlas surfaces, held weakly: `_hide_meshes` runs before
#: every slice for the viewer's life, and must not keep a scene alive.
_MESHES: weakref.WeakKeyDictionary = weakref.WeakKeyDictionary()


def _meshes_of(viewer) -> weakref.WeakSet:
    """The viewer's surfaces, hidden before napari slices anything for 2D.

    A mesh napari slices for 2D loses its 3D build, which
    `AtlasSurface.sync` shows again on the way back if nothing changed.
    napari slices on a change of mode before any handler of ours runs,
    so this goes through `before_slicing`.
    """
    meshes = _MESHES.get(viewer)
    if meshes is None:
        meshes = _MESHES[viewer] = weakref.WeakSet()
        ref = weakref.ref(viewer)

        def _hide_meshes() -> None:
            live = ref()
            if live is None or live.dims.ndisplay != 2:
                return
            for surface in list(meshes):
                surface.hide_mesh()

        before_slicing(viewer, _hide_meshes)
    return meshes


#: How far, in screen pixels, the cursor may move between press and release
#: for the press to be a click rather than a drag.
CLICK_SLOP = 4.0


def install_picking(viewer, surfaces, contours, panel=None) -> list:
    """Name the glomerulus under the cursor, and select it on a click.

    Returns the viewer callbacks it added, so a scene switch can remove them.

    Hovering only says what is under the cursor, in the status bar: "VA3
    (left) — Benton 2025", the panel row's words and whose it is. It moves
    nothing. It used to select the row as well, which switched the panel's
    tab, moved its selection, scrolled its table and refilled its details
    under the user's eyes. A click that does not drag selects the row, as a
    click in the table does; a drag turns or pans the view and selects
    nothing.

    On the VIEWER, not on each layer. napari sends a layer's mouse callbacks
    only while that layer is the active one, and one atlas is drawn by two
    layers -- a mesh in 3D, its outlines in 2D -- while the user can make
    any layer active, so hovering named nothing until the right layer
    happened to be selected. The viewer's callbacks run on every move, and
    this asks each layer the current mode draws: surfaces in 3D, contours in
    2D, the atlases before the reference shells.

    In 3D the ray is tested against the shown compartments' boxes and then
    their triangles (`AtlasSurface.pick`), not against every triangle of
    the layer as napari's own Surface pick does -- 40 ms a mouse move on
    Benton. Under perspective the ray starts at the eye, which zoomed in can
    be inside the brain. In 2D the contour loops are tested directly, inside
    the loop rather than on its stroke. `Shapes.get_value` cannot be used for
    them: napari rounds each shape's slice position to a whole number and
    compares it with the unrounded plane, so off a whole-micrometer plane it
    found no shape at all.

    The dicts are read on every move, so a part the session builds later
    (`SceneSession.realize`) is picked too.

    The words stay once the cursor rests. napari works out the status bar's
    words for the cursor itself, in a thread of its own, once the cursor is
    over the canvas -- the active layer's name and the value under the
    cursor -- and they arrived a moment after these and replaced them:
    "neuPrint · 3D [306, 174, 198]: 7, 23185" where "DA3 (right) — neuPrint"
    had been, naming the hidden 3D layer in Slice view. So napari's own
    reckoning names the compartment first (`name_the_cursor`), and gives its
    own words only where no compartment is.
    """

    def _pick(event):
        """(part, compartment, words) under the cursor, or None."""
        return _pick_at(event.position, getattr(event, "view_direction", None),
                        getattr(event, "dims_displayed", None) or viewer.dims.displayed)

    def _pick_at(position, view_direction, dims_displayed):
        three_d = viewer.dims.ndisplay == 3
        order = sorted(
            surfaces,
            key=lambda n: surfaces[n].layer.metadata.get("lobemap", {}).get("role")
            in REFERENCE_ROLES,
        )
        for name in order:
            surface = surfaces[name]
            overlay = contours.get(name)
            if three_d or overlay is None:
                if not surface.layer.visible or not three_d:
                    continue
                index = surface.pick(
                    position, view_direction, dims_displayed,
                    from_position=viewer.scene.camera.perspective > 0,
                )
            else:
                if not overlay.layer.visible:
                    continue
                shown = list(viewer.dims.displayed)
                point = overlay.layer.world_to_data(position)
                shape = polygon_at(
                    [np.asarray(path)[:, shown] for path in overlay.paths],
                    np.asarray(point)[shown],
                )
                label = overlay.name_at_shape(shape)
                index = overlay.meshset.names.index(label) if label else None
            if index is not None:
                tab = panel.tabs.get(name) if panel is not None else None
                said = tab.describe(index) if tab is not None else ""
                return name, index, said or f"{surface.display_names[index]} — {surface.name}"
        return None

    def _on_move(_viewer, event):
        if getattr(event, "buttons", None):
            return          # a drag: rotating or panning, not pointing
        picked = _pick(event)
        if picked is not None:
            viewer.status = picked[2]

    def _words(position, view_direction) -> str | None:
        """What napari's status says for the cursor; see `name_the_cursor`."""
        picked = _pick_at(position, view_direction, viewer.dims.displayed)
        return None if picked is None else picked[2]

    # Found through the callback, so a scene torn down names nothing.
    _on_move.lobemap_words = _words
    name_the_cursor(viewer)

    def _on_press(_viewer, event):
        if getattr(event, "button", 1) != 1:
            return          # not the left button: napari's own, or a menu
        start = np.asarray(event.pos, float)
        yield
        while event.type == "mouse_move":
            if np.hypot(*(np.asarray(event.pos, float) - start)) > CLICK_SLOP:
                return      # a drag
            yield
        picked = _pick(event)
        if picked is not None:
            viewer.status = picked[2]
            if panel is not None:
                panel.highlight(picked[0], picked[1])

    viewer.mouse_move_callbacks.append(_on_move)
    viewer.mouse_drag_callbacks.append(_on_press)
    return [_on_move, _on_press]


def name_the_cursor(viewer) -> None:
    """Give the status bar lobemap's words for what the cursor is over.

    napari reckons the status bar's words for the cursor whenever it moves
    over the canvas, in a thread, and whenever another layer is made active:
    the active layer's name, the cursor's position and the value there.
    Here that reckoning asks the scene's picking first (`install_picking`),
    and keeps napari's words for where no compartment is. So whichever layer
    is active, 2D or 3D, the words that stay are the compartment's.

    The scene's picking is found through its mouse callback, which a scene
    switch removes, so the scene shown is the one asked. Once per viewer.
    While a switch builds the next scene (`hold_status`), the words are left
    as they are.
    """
    from .napari_private import status_for_cursor

    def _words(position, view_direction) -> str | None:
        for callback in reversed(list(viewer.mouse_move_callbacks)):
            words = getattr(callback, "lobemap_words", None)
            if words is not None:
                return words(position, view_direction)
        return None

    status_for_cursor(viewer, _words, held=lambda: viewer in _HELD)


#: The viewers building a scene beside the one shown; see `hold_status`.
_HELD: weakref.WeakSet = weakref.WeakSet()


@contextlib.contextmanager
def hold_status(viewer):
    """Leave the status bar's words as they are while a switch builds the
    next scene, and reckon them anew once it is done.

    napari keeps layer names unique, so the next scene's layers are named
    "neuPrint · 3D [1]" until the scene they were built beside is gone
    (`SceneSession.take_names`). napari's status thread kept reckoning the
    status bar's words meanwhile, from the active layer's name, and the
    status bar could show the numbered name after the switch.
    """
    _HELD.add(viewer)
    try:
        yield
    finally:
        _HELD.discard(viewer)
        viewer.update_status_from_cursor()


def show_main_layer(viewer, registry: Registry, session: SceneSession) -> None:
    """Make the primary atlas's 3D layer the active one.

    napari makes the last layer added active, which after a load is an
    outline layer: the layer settings showed napari's drawing tools for it,
    and the status bar their keys. The primary atlas is what a scene opens
    on, so its controls are the ones worth showing first.
    """
    primary = registry.primary_atlas(session.space)
    surface = session.surfaces.get(primary.id) if primary is not None else None
    if surface is not None:
        viewer.layers.selection.active = surface.layer


def window_title(registry: Registry, space: str) -> str:
    """'lobemap — Hemibrain (female, EM)': the brain open, by its title."""
    return f"lobemap — {registry.spaces[space].title or space}"


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
    behind to be driven by the next one. A scene already in the viewer is
    left in place: the switcher builds the next scene beside it and tears it
    down only once that build has succeeded.

    Only the primary atlas is built; the rest of the scene is built the
    first time it is needed (`SceneSession.realize`), from meshes a thread
    starts reading as this build begins (`deferred`). On a cold open it is
    done before this returns. In a switch it can still be reading then, and
    is done by the end of the switch, or within 45 ms of it. The images are
    shown once the plane and the 3D pyramid level are set, so a space
    opened alone reads each once. See `build_scene`.
    """
    session = SceneSession(viewer, registry, space)
    try:
        build_scene(viewer, registry, space, into=session, defer=True)

        from .panel import CompartmentPanel

        session.panel = CompartmentPanel(
            viewer, session.surfaces, registry=registry,
            contours=session.contours, space=space,
            names=list(session.parts), realize=session.realize,
        )
        session.dock = add_dock(viewer, session.panel, PANEL_TITLE, "right")
        session.callbacks += install_picking(
            viewer, session.surfaces, session.contours, panel=session.panel
        )
        session.handlers += install_display_mode(
            viewer, session.surfaces, session.contours, session.images,
            session=session,
        )
        show_images(session.images)
        if show:
            session.show(show)
        install_home_orientation(viewer, registry.spaces[space],
                                 reflect_axis=session.reflect_axis)
        keep_orientation(viewer)
        lock_layers(viewer)
        show_main_layer(viewer, registry, session)
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
    registry=None,
) -> None:
    """Open `space` in a new window and run the event loop.

    Everything that can be checked without a window is checked first --
    the space, `--show`, and whether the data is on disk -- so a mistake
    is a one-line error instead of a traceback behind an empty window.
    `show` applies to this first scene only; a space picked later opens
    with its own defaults. `registry`, when given, was loaded from the same
    roots and is used instead of loading them again.
    """
    import napari

    if registry is None:
        registry = Registry.load(registry_root, data_root=data_root)
    if space is None:
        raise ViewRequestError("need a space")
    check_request(registry, space, show, on_disk=True)

    viewer = napari.Viewer(title=window_title(registry, space), ndisplay=ndisplay)
    try:
        def _load(target: str, show: tuple[str, ...] = ()):
            # Unfitted: a switch builds beside the open scene, and a fit
            # now would frame both. The switcher fits once the old one is
            # gone, and the first scene is fitted below.
            session = load_space(viewer, registry, target, show=show, fit=False)
            viewer.title = window_title(registry, session.space)
            return session

        session = _load(space, tuple(show))

        from .switcher import SpaceSwitcher

        switcher = SpaceSwitcher(viewer, registry, session, _load)
        # Added ONCE and never torn down, unlike the compartment panel: it is
        # the control that does the switching, so it cannot be owned by the
        # scene it replaces. Left, tabbed with napari's layer settings, so the
        # right column is the compartment panel's alone; see `chrome.tidy`.
        view_dock = add_dock(viewer, switcher, VIEW_TITLE, "left")
        tidy(viewer, view_dock, session.dock)
        buttons.install(viewer)
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
    "CLICK_SLOP",
    "DIMS_ORDER_XYZ",
    "MIRROR_AXIS",
    "PANEL_TITLE",
    "REFERENCE_CONTOUR_COLOR",
    "ROLE_DISPLAY",
    "VIEW3D_MAX_AXIS",
    "VIEW3D_MAX_VOXELS",
    "VIEW_TITLE",
    "MissingAssets",
    "SceneSession",
    "ViewRequestError",
    "build_scene",
    "check_request",
    "default_colormap",
    "display_for",
    "fit_view",
    "hold_status",
    "install_display_mode",
    "install_home_orientation",
    "install_initial_fit",
    "install_picking",
    "level_for_3d",
    "load_space",
    "maximize",
    "name_the_cursor",
    "orient_anterior",
    "run",
    "show_main_layer",
    "show_primary_atlas",
    "show_targets",
    "window_title",
]
