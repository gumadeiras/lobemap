"""The napari application entry point, and the hooks that drive a scene.

This is the viewer's public module: `run` and `load_space` open a space, and
the scene assembly (`scene`), the image display defaults (`images`), the
camera helpers (`view`) and the request errors (`request`) are importable
from here as well.
"""

from __future__ import annotations

import numpy as np

from ..core.registry import Registry
from .axes import apply_axis_mode
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
    GIMBAL_NUDGE_DEG,
    MIRROR_AXIS,
    fit_view,
    install_home_orientation,
    install_initial_fit,
    maximize,
    orient_anterior,
)

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
            pin_level(layer, three_d)
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

    The dicts are read on every move, so a part the session builds later
    (`SceneSession.realize`) is picked too.
    """

    def _on_move(_viewer, event):
        if getattr(event, "buttons", None):
            return          # a drag: rotating or panning, not pointing
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
                    [np.asarray(path)[:, shown] for path in overlay.paths],
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
    first time it is needed (`SceneSession.realize`), and the images are
    shown once the plane and the 3D pyramid level are set, so each is read
    once. See `build_scene`.
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
        session.dock = viewer.window.add_dock_widget(
            session.panel, area="right", name="Compartments"
        )
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
            # Unfitted: a switch builds beside the open scene, and a fit
            # now would frame both. The switcher fits once the old one is
            # gone, and the first scene is fitted below.
            session = load_space(viewer, registry, target, show=show, fit=False)
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
