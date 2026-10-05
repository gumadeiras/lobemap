"""What lobemap reaches of napari's viewer for the status bar, the camera and
its actions. Split out of `test_napari_private`, which imports these tests,
merges `CHECKED` into its own, and runs them with its `viewer` fixture and its
`need` and `reaching`.
"""

from __future__ import annotations

#: Every private name these tests check, and the test that checks it.
CHECKED = {
    "_calc_status_from_cursor": "test_the_status_napari_reckons_for_the_cursor",
    "_view_direction": "test_the_status_napari_reckons_for_the_cursor",
    "_actions": "test_napari_actions_lobemap_takes_over",
    "_on_view_direction_change": "test_the_light_napari_gives_a_surface",
    "_update_camera_depth": "test_the_fits_and_the_depth_napari_makes",
}


def _helpers():
    from test_napari_private import need, reaching

    return need, reaching


def test_the_status_napari_reckons_for_the_cursor(viewer):
    """`napari_private.status_for_cursor`: napari reckons the status bar's
    words for the cursor in `ViewerModel._calc_status_from_cursor`, which its
    status thread and its change of active layer both call through the
    viewer, and reads the cursor's ray from `Cursor._view_direction`."""
    import inspect

    from napari._qt.threads.status_checker import StatusChecker

    from lobemap.viewer.napari_private import status_for_cursor

    need, reaching = _helpers()
    used = "viewer.napari_private.status_for_cursor"
    with reaching("ViewerModel._calc_status_from_cursor and Cursor._view_direction", used):
        reckon = type(viewer)._calc_status_from_cursor
        callers = (inspect.getsource(StatusChecker.calculate_status)
                   + inspect.getsource(type(viewer).update_status_from_cursor))
        direction = viewer.cursor._view_direction
    need(callable(reckon) and not inspect.signature(reckon).parameters.keys() - {"self"},
         "ViewerModel._calc_status_from_cursor(), taking no argument", used)
    need(callers.count("._calc_status_from_cursor()") == 2,
         "StatusChecker.calculate_status and update_status_from_cursor calling "
         "viewer._calc_status_from_cursor()", used)
    need(direction is None or len(direction) == 3, "Cursor._view_direction", used)

    seen = []
    status_for_cursor(viewer, lambda position, ray: seen.append(ray) or "Named")
    viewer.mouse_over_canvas = True
    viewer.update_status_from_cursor()
    need(viewer.status == "Named" and seen,
         "the viewer's own _calc_status_from_cursor, called through the instance", used)
    viewer.mouse_over_canvas = False


def test_napari_actions_lobemap_takes_over(viewer):
    """`buttons.take_action`: napari's action manager keeps each action's
    command, description, keymap provider and repeatability in `_actions`,
    and binds its keys to the action's injected command, again when one is
    registered anew; napari injects the viewer the key was pressed in."""
    from napari.components import ViewerModel
    from napari.settings import get_settings
    from napari.utils.action_manager import action_manager

    from lobemap.viewer.buttons import take_action

    need, reaching = _helpers()
    used = "viewer.buttons.take_action"
    name = "napari:toggle_grid"
    with reaching("action_manager._actions", used):
        action = action_manager._actions[name]
        parts = (action.command, action.description, action.keymapprovider,
                 action.repeatable)
    need(callable(parts[0]) and isinstance(parts[1], str) and parts[2] is ViewerModel,
         "action_manager._actions[name], an Action of command, description, "
         "keymapprovider and repeatable", used)
    said = []
    take_action(viewer, name, said.append)
    action = action_manager._actions[name]
    need(any(bound is action.injected for bound in ViewerModel.class_keymap.values()),
         "ViewerModel.class_keymap bound to the action registered anew", used)
    action.injected(viewer)
    need(said == [viewer] and not viewer.canvas.grid.enabled,
         "the action's injected command, given the viewer", used)
    need(get_settings().shortcuts.shortcuts.get(name), f"a key for {name}", used)


def test_the_light_napari_gives_a_surface(viewer):
    """`napari_private.light_surface`: napari's surface visual takes a view
    and an up, in vispy's order, lights the mesh from up - view + up x view,
    and keeps that light for its next change of data or shading."""
    import numpy as np

    from lobemap.viewer.napari_private import layer_visual, light_surface

    need, reaching = _helpers()
    used = "viewer.view.light_from_the_camera"
    viewer.dims.ndisplay = 3
    layer = viewer.add_surface((np.eye(3), np.array([[0, 1, 2]])), shading="smooth")
    view, up = np.array([0.0, 0.0, -1.0]), np.array([0.0, -1.0, 0.0])
    with reaching("the surface visual's _on_view_direction_change(view, up)", used):
        light_surface(viewer, layer, view, up)
        light = np.asarray(layer_visual(viewer, layer).node.shading_filter.light_dir, float)
    want = up - view + np.cross(up, view)
    need(np.allclose(light / np.linalg.norm(light), want / np.linalg.norm(want)),
         "the shading filter lit from up - view + up x view", used)
    layer.shading = "flat"
    light = np.asarray(layer_visual(viewer, layer).node.shading_filter.light_dir, float)
    need(np.allclose(light / np.linalg.norm(light), want / np.linalg.norm(want)),
         "the light kept through a change of shading", used)


def test_the_fits_and_the_depth_napari_makes(viewer):
    """`view.install_home_orientation` and `napari_private.hook_extent`:
    napari fits the view through the viewer's own `fit_to_view` when the axis
    order changes, looked up on the instance; and `QtViewer.
    _update_camera_depth` sizes the 3D camera's depth from the layer list's
    extent."""
    import inspect

    import numpy as np
    from napari._qt.qt_viewer import QtViewer

    need, reaching = _helpers()
    used = "viewer.view.install_home_orientation"
    viewer.add_image(np.zeros((4, 5, 6), np.uint8))
    fits = []
    object.__setattr__(viewer, "fit_to_view", lambda **kwargs: fits.append(kwargs))
    viewer.dims.order = (2, 0, 1)
    need(fits == [{}], "dims.events.order calling viewer.fit_to_view(), "
         "looked up on the instance", used)
    used = "viewer.napari_private.hook_extent"
    with reaching("QtViewer._update_camera_depth", used):
        source = inspect.getsource(QtViewer._update_camera_depth)
        viewer.window._qt_viewer._update_camera_depth()
    need("self.viewer.layers.extent" in source and not inspect.signature(
        QtViewer._update_camera_depth).parameters.keys() - {"self"},
         "QtViewer._update_camera_depth(), from viewer.layers.extent", used)


def test_the_camera_popups_sync_box(viewer):
    """`buttons._camera_popup`: napari's camera popup keeps its "Sync 2D/3D
    camera" box as `camera_synced_checkbox`, and the camera its `synced`."""
    from chrome_harness import popups_offscreen, right_click
    from qtpy.QtWidgets import QCheckBox

    need, reaching = _helpers()
    used = "viewer.buttons._camera_popup and keep_synced"
    row = viewer.window._qt_viewer.viewerButtons
    with popups_offscreen(), reaching("QtViewerButtons.camera_synced_checkbox", used):
        popups = right_click(row.ndisplayButton)
        box = row.camera_synced_checkbox
        need(isinstance(box, QCheckBox) and box.isChecked() == viewer.scene.camera.synced
             and hasattr(viewer.scene.camera.events, "synced"),
             "a Sync 2D/3D camera checkbox, and Camera.synced with its event", used)
        for popup in popups:
            popup.close()
