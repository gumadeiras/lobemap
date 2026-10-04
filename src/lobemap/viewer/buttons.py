"""napari's own buttons around the layer list, in step with the View dock.

napari puts two rows of buttons around its layer list. Over it: new points,
shapes and labels layers, and delete. Under it: the console, 2D/3D, roll,
transpose, grid and home. They stay napari's, drawn as napari draws them,
and each one either does what it did, in step with the View dock, or is off
and says why (`install`):

- **2D/3D** is the View dock's 3D and Slice, and **home** its Fit to window:
  both are napari's display mode and `viewer.reset_view`, lobemap's Home
  (`view.install_home_orientation`), which keeps the rotation and the flip.
  **Roll**, and its key, pick the next choice of the Sections menu, in the
  menu's order, and wrap (`switcher.SpaceSwitcher.next_sections`). Each
  control follows the viewer's state, not the other's clicks, so the two
  stay in step whichever is used. Roll is off in 3D, as Sections is.
- **The camera popup**, a right-click on 2D/3D. Its up/down menu is the
  View dock's flip, its zoom and perspective the dock's (`camera_rows`); each
  follows the others while it is open. Its angles turn the camera as a drag
  does, which the dock's rotation boxes do not follow. Left along the
  horizontal, and away along the depth, would mirror the picture with no
  control to say so: their menus are off (`view.keep_orientation`). So is
  "Sync 2D/3D camera", and View > Toggle Synced 2D/3D Camera (⌘U) is
  refused (`keep_synced`): unsynced, napari keeps a camera for each mode,
  and a trip between 3D and Slice view changed the zoom the dock showed.
- **The roll popup**, a right-click on roll, lists the axes to drag. A drag
  that swaps the two axes on screen is undone (`SpaceSwitcher._on_order`),
  and its help says why.
- **Transpose** and **grid** are off. One mirrors the picture across its
  diagonal, the other splits the outlines from the image they lie on, and
  the View dock would show neither. Transpose's Option-click, which turned
  every layer 90°, is off with it. Their actions say why and do nothing, by
  whichever key napari's preferences bind to them -- ⌘T, ⌘⌥T and ⌘G unless
  rebound (`take_action`).
- **New layer** buttons add the user's own layers, and **delete** deletes
  them; lobemap's own are locked and passed by (`chrome.lock_layers`), and
  lobemap says why (`guards`).

napari has no public API for its buttons or their popups. They are reached
through `Window._qt_viewer`, by the names napari gives them, and
`tests/test_napari_private.py` checks each. Its actions are napari's action
manager's, replaced by name.
"""

from __future__ import annotations

import weakref

from .axes import keep_scene_axes_off
from .guards import guard_layers

TRANSPOSE_OFF = (
    "Off in lobemap: swapping the two axes on screen shows the brain mirrored, "
    "with no control to say so. To mirror the brain, use Mirror the brain left "
    "to right; to turn the picture, use Rotate around: Line of sight. "
    "Option-click, which turned every layer, is off too."
)
ROTATE_OFF = (
    "Off in lobemap: turning every layer 90° would leave the corner arrows, "
    "the rotation boxes and Fit to window showing another view. To turn the "
    "picture, use Rotate around: Line of sight."
)
GRID_OFF = (
    "Off in lobemap: a grid draws each layer in a tile of its own, so the "
    "outlines no longer lie on the image they belong to. Its settings are off "
    "too."
)
ROLL_TIP = (
    "Slice along the next choice of the Sections menu. Right-click to drag "
    "the axes into order."
)
ROLL_3D = "Slice view only: in 3D every axis is shown. In Slice view, this picks the next sections."
ROLL_POPUP_TIP = (
    "Drag an axis to the top to slice along it, as Sections does. The two axes "
    "under it keep their order: swapping them would show the brain mirrored, "
    "so a swap is undone. To mirror the brain, use Mirror the brain left to "
    "right."
)
VERTICAL_TIP = (
    "Down shows the picture upright; up shows it upside down, as Flip the "
    "picture upside down does."
)
HORIZONTAL_OFF = (
    "Off in lobemap: left would show the picture mirrored, with no control to "
    "say so. To mirror the brain, use Mirror the brain left to right; for the "
    "mirror image of the picture, flip it upside down and turn it 180° about "
    "the line of sight."
)
DEPTH_OFF = (
    "Off in lobemap: away would show the brain mirrored, with no control to "
    "say so. To see it from behind, turn it 180° about the vertical axis."
)
SYNC_OFF = (
    "Off in lobemap: 3D and Slice view share one camera, so the zoom and "
    "the view the dock shows hold across a change of mode."
)
DELETE_TIP = (
    "Delete the selected layers you added. lobemap's own layers are locked, "
    "and stay: the panel and the View tab draw them. To hide one, click its "
    "eye, or untick its rows in the panel."
)

#: napari's actions that do nothing in lobemap, and what each says.
OFF_ACTIONS = {
    "napari:transpose_axes": TRANSPOSE_OFF,
    "napari:rotate_layers": ROTATE_OFF,
    "napari:toggle_grid": GRID_OFF,
}

#: Each lobemap viewer's own handlers of napari's actions; see `take_action`.
_TAKEN: weakref.WeakKeyDictionary = weakref.WeakKeyDictionary()


def install(viewer) -> None:
    """Make napari's two button rows and their popups lobemap's; once per window."""
    from .chrome import GRID

    qt_viewer = viewer.window._qt_viewer
    row, layer_row = qt_viewer.viewerButtons, qt_viewer.layerButtons
    # On the View dock's grid: a grid unit between buttons, as between its
    # controls. Delete stays apart, at the far end.
    for buttons in (row, layer_row):
        buttons.layout().setSpacing(GRID)
    for button, why in ((row.transposeDimsButton, TRANSPOSE_OFF),
                        (row.gridViewButton, GRID_OFF)):
        # Disabled, a button takes no click and opens no popup.
        _enable(button, False)
        button.setToolTip(why)
    # Option-click on transpose turned every layer, through this filter.
    row.transposeDimsButton.removeEventFilter(row)
    layer_row.deleteButton.setToolTip(DELETE_TIP)

    roll = row.rollDimsButton

    def _on_mode(event=None) -> None:
        three_d = viewer.dims.ndisplay == 3
        _enable(roll, not three_d)
        roll.setToolTip(ROLL_3D if three_d else ROLL_TIP)

    viewer.dims.events.ndisplay.connect(_on_mode)
    _on_mode()
    # Each after napari's own slot, which has opened the popup by then.
    row.ndisplayButton.customContextMenuRequested.connect(
        lambda _pos: _camera_popup(viewer, row))
    roll.customContextMenuRequested.connect(lambda _pos: _roll_popup(row))
    for action, why in OFF_ACTIONS.items():
        take_action(viewer, action, _saying(why))
    keep_synced(viewer)
    keep_scene_axes_off(viewer)
    guard_layers(viewer)


def take_action(viewer, name: str, handler) -> None:
    """Run `handler(viewer)` for napari's action `name` in this viewer.

    By the action rather than by its key: napari's preferences can bind any
    key to an action, and a key rebound there to grid mode turned it on. So
    the action itself is replaced, once per process, by one that runs the
    handler a lobemap viewer gave and napari's own command in any other
    viewer; every key, button and menu napari binds to the action, now or
    later, reaches it. napari injects the viewer by the annotation, as it
    does into its own command.
    """
    from napari.components import ViewerModel
    from napari.utils.action_manager import action_manager

    _TAKEN.setdefault(viewer, {})[name] = handler
    action = action_manager._actions[name]
    if getattr(action.command, "_lobemap", False):
        return
    napari_command = action.command

    def command(viewer: ViewerModel) -> None:
        handler = _TAKEN.get(viewer, {}).get(name)
        if handler is None:
            napari_command(viewer)
        else:
            handler(viewer)

    command.__annotations__ = {"viewer": ViewerModel, "return": None}
    command.__name__ = command.__qualname__ = napari_command.__name__
    command._lobemap = True
    action_manager.register_action(name, command, action.description,
                                   action.keymapprovider, action.repeatable)


def _saying(why: str):
    """An action's handler that says `why` and does nothing else."""
    from napari.utils.notifications import show_info

    def off(viewer=None) -> None:
        show_info(why)

    return off


def keep_synced(viewer) -> None:
    """Keep napari's 2D and 3D cameras one camera, and say why when asked not to.

    napari's View menu and its camera popup can unsync them, and each mode
    then keeps its own center, zoom and angles: a trip between 3D and Slice
    view changed the zoom, and the rotation the dock showed was not the
    one in view. lobemap shows one camera, so the change is put back.
    """
    from napari.utils.notifications import show_info

    camera = viewer.scene.camera
    ref = weakref.ref(viewer)

    def _synced(event=None) -> None:
        if ref() is not None and not camera.synced:
            camera.synced = True
            show_info(SYNC_OFF)

    camera.events.synced.connect(_synced)
    _synced()


def _camera_popup(viewer, row) -> None:
    """Make napari's camera popup, just opened, lobemap's.

    The menus that would mirror the picture are off, and say why. Its zoom,
    its perspective and its up/down menu follow the camera while it is open,
    as the View dock does, so a change made in either shows in both.
    """
    camera = viewer.scene.camera
    three_d = viewer.dims.ndisplay == 3
    row.vertical_combo.setToolTip(VERTICAL_TIP)
    row.horizontal_combo.setEnabled(False)
    row.horizontal_combo.setToolTip(HORIZONTAL_OFF)
    if three_d:
        row.depth_combo.setEnabled(False)
        row.depth_combo.setToolTip(DEPTH_OFF)
    row.camera_synced_checkbox.setEnabled(False)
    row.camera_synced_checkbox.setToolTip(SYNC_OFF)

    vertical, zoom = row.vertical_combo, row.zoom
    perspective = row.perspective if three_d else None
    follow = [
        (camera.events.zoom, lambda event=None: _quietly(zoom.setValue, zoom, camera.zoom)),
        (camera.events.orientation, lambda event=None: _quietly(
            vertical.setCurrentEnum, vertical, camera.orientation[1])),
    ]
    if perspective is not None:
        follow.append((camera.events.perspective, lambda event=None: _quietly(
            perspective.setValue, perspective, camera.perspective)))
    for event, handler in follow:
        event.connect(handler)

    def _closed(_result=None) -> None:
        for event, handler in follow:
            event.disconnect(handler)

    # napari keeps a closed popup, hidden; it stops following once closed.
    vertical.window().finished.connect(_closed)


def _roll_popup(row) -> None:
    """Give napari's axis-order popup, just opened, lobemap's help."""
    from qtpy.QtWidgets import QAbstractItemView, QWidget

    for sorter in row.findChildren(QWidget, "dim_sorter"):
        for widget in sorter.findChildren(QWidget, "help_label"):
            widget.setToolTip(ROLL_POPUP_TIP)
        for widget in sorter.findChildren(QAbstractItemView):
            widget.setToolTip(ROLL_POPUP_TIP)


def _enable(button, on: bool) -> None:
    """Enable a button, or disable it and fade it to half, as napari fades
    its own disabled console button: its icons show no disabled state."""
    from qtpy.QtWidgets import QGraphicsOpacityEffect

    effect = button.graphicsEffect()
    if effect is None:
        effect = QGraphicsOpacityEffect(button)
        effect.setOpacity(0.5)
        button.setGraphicsEffect(effect)
    effect.setEnabled(not on)
    button.setEnabled(on)


def _quietly(setter, widget, value) -> None:
    """Show `value` in one of the popup's widgets without handing it back."""
    widget.blockSignals(True)
    try:
        setter(value)
    finally:
        widget.blockSignals(False)


__all__ = [
    "DELETE_TIP",
    "DEPTH_OFF",
    "GRID_OFF",
    "HORIZONTAL_OFF",
    "OFF_ACTIONS",
    "ROLL_3D",
    "ROLL_POPUP_TIP",
    "ROLL_TIP",
    "ROTATE_OFF",
    "SYNC_OFF",
    "TRANSPOSE_OFF",
    "VERTICAL_TIP",
    "install",
    "keep_synced",
    "take_action",
]
