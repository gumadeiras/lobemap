"""Drive napari's own buttons, popups and keys in lobemap's window, and read
back what the screen shows of the specimen.

`right_click` opens a button's popup through Qt's own context-menu event,
`press` sends a key through Qt to the canvas or the layer list, and `told`
collects what napari's notifications say. `handedness` measures whether the
picture shows the specimen as it is or mirrored, from the transforms the
picture is drawn with; `assert_no_hidden_mirror` checks that against what
the View dock's controls say.
"""

from __future__ import annotations

import contextlib

import numpy as np


@contextlib.contextmanager
def popups_offscreen():
    """Lay napari's popups out for real, as the window is, without putting
    them on screen, where they would take the mouse."""
    from napari._qt.dialogs.qt_modal import QtPopup
    from qtpy.QtCore import Qt

    show = QtPopup.show

    def hidden(self, *args):
        self.setAttribute(Qt.WidgetAttribute.WA_DontShowOnScreen, True)
        return show(self, *args)

    QtPopup.show = hidden
    try:
        yield
    finally:
        QtPopup.show = show


def open_popups(widget) -> list:
    """The popups napari has open under `widget`."""
    from napari._qt.dialogs.qt_modal import QtPopup

    return [p for p in widget.findChildren(QtPopup) if p.isVisible()]


def right_click(button) -> list:
    """Right-click `button` through Qt; the popups that opened."""
    from qtpy.QtCore import QPoint
    from qtpy.QtGui import QContextMenuEvent
    from qtpy.QtWidgets import QApplication
    from viewer_harness import pump

    row = button.parentWidget()
    before = {id(p) for p in open_popups(row)}
    QApplication.sendEvent(button, QContextMenuEvent(QContextMenuEvent.Reason.Mouse,
                                                     QPoint(4, 4)))
    pump()
    return [p for p in open_popups(row) if id(p) not in before]


def close_popups(viewer) -> None:
    from viewer_harness import pump

    for popup in open_popups(viewer.window._qt_viewer):
        popup.close()
    pump()


def press(widget, key: str, *mods: str) -> None:
    """A key press and release sent through Qt to `widget`.

    `mods` are Qt's names: "Control" is ⌘ on macOS, as napari's Ctrl is.
    """
    from qtpy.QtCore import Qt
    from qtpy.QtTest import QTest
    from viewer_harness import pump

    flags = Qt.KeyboardModifier.NoModifier
    for mod in mods:
        flags |= getattr(Qt.KeyboardModifier, f"{mod}Modifier")
    QTest.keyClick(widget, getattr(Qt.Key, f"Key_{key}"), flags)
    pump()


@contextlib.contextmanager
def told():
    """What napari's notifications say meanwhile, as a list of strings."""
    from napari.utils.notifications import notification_manager

    said: list[str] = []

    def hear(notification) -> None:
        said.append(str(notification.message))

    notification_manager.notification_ready.connect(hear)
    try:
        yield said
    finally:
        notification_manager.notification_ready.disconnect(hear)


# -- what the screen shows ------------------------------------------------------


def _screen(viewer, world) -> np.ndarray:
    """(canvas x, canvas y, depth) at which a world point is drawn.

    Through vispy's own transform to the canvas. In 2D the depth is the
    world coordinate along the slider's axis, which the screen does not
    show but which orders the three.
    """
    canvas = viewer.window._qt_viewer.canvas
    transform = canvas.view.transform * canvas.view.scene.transform
    world = np.asarray(world, float)
    shown = world[list(viewer.dims.displayed)][::-1]
    if viewer.dims.ndisplay == 2:
        p = np.asarray(transform.map(np.r_[shown, 0.0]), float)
        return np.array([p[0] / p[3], p[1] / p[3], world[int(viewer.dims.order[0])]])
    p = np.asarray(transform.map(shown), float)
    return p[:3] / p[3]


def handedness(viewer, sess) -> int:
    """+1 or -1: the sign of the map from the specimen to the screen.

    The specimen is the primary atlas's own frame, its mesh coordinates; a
    point of it is put in the world by its outline layer, which carries the
    mirror and a 2D turn, through the frame a turn across the image grid
    cuts in, and on screen by vispy. Measured about the point at the middle
    of the view. A turn keeps the sign, a mirror of any kind changes it.
    """
    contour = sess.contours[sess.registry.primary_atlas(sess.space).id]
    frame = contour.frame
    middle = np.asarray(viewer.dims.point, float)
    shown = list(viewer.dims.displayed)
    middle[shown] = np.asarray(viewer.scene.camera.center, float)[-len(shown):]
    origin = np.asarray(contour.layer.world_to_data(middle), float)
    if frame is not None:
        origin = frame.inverse(origin)
    base = _screen(viewer, middle)
    columns = []
    for step in np.eye(3) * 5.0:
        data = origin + step if frame is None else frame.apply(origin + step)
        world = np.asarray(contour.layer.data_to_world(data), float)
        columns.append(_screen(viewer, world) - base)
    det = float(np.linalg.det(np.column_stack(columns)))
    assert abs(det) > 1e-9, "the specimen's map to the screen is flat"
    return 1 if det > 0 else -1


def baseline(viewer, sess, sw) -> dict:
    """The sign `handedness` has with no mirror and no flip, by display mode
    and Sections choice, set through the View dock alone; left in 3D."""
    from viewer_harness import pump

    assert not sw.mirror.isChecked() and not sw.flip.isChecked()
    out = {}
    sw.slice_view.click()
    pump()
    for i in range(sw.slice.count()):
        sw.slice.setCurrentIndex(i)
        pump()
        out[(2, int(sw.slice.currentData()))] = handedness(viewer, sess)
    sw.slice.setCurrentIndex(0)
    sw.three_d.click()
    pump()
    out[(3, None)] = handedness(viewer, sess)
    return out


def assert_no_hidden_mirror(viewer, sess, sw, signs) -> None:
    """The picture shows the specimen as the View dock says: its Sections
    choice, its mirror and its flip, and nothing else.

    The viewer is in the state the dock shows, and the specimen's map to the
    screen has the sign that state gives (`baseline`), changed once by the
    mirror and once by the flip.
    """
    from lobemap.viewer.slicing import order_for

    two_d = viewer.dims.ndisplay == 2
    assert sw.three_d.isChecked() is not two_d
    assert sess.mirrored is sw.mirror.isChecked()
    assert sess.flipped is sw.flip.isChecked()
    camera = [str(o) for o in viewer.scene.camera.orientation]
    assert camera[0] == "towards" and camera[2] == "right", camera
    key = (2, int(sw.slice.currentData())) if two_d else (3, None)
    if two_d:
        axis = int(sw.slice.currentData())
        assert tuple(viewer.dims.order) == order_for(axis), viewer.dims.order
    else:
        assert tuple(viewer.dims.order) == (0, 1, 2), viewer.dims.order
    want = signs[key] * (-1) ** sw.mirror.isChecked() * (-1) ** sw.flip.isChecked()
    assert handedness(viewer, sess) == want, (key, sw.mirror.isChecked(),
                                               sw.flip.isChecked())


def layout(viewer) -> dict:
    """Where every dock widget is and how large: what must not move."""
    from qtpy.QtWidgets import QDockWidget, QWidget

    window = viewer.window._qt_window
    out = {}
    for dock in window.findChildren(QDockWidget):
        title = dock.windowTitle()
        out[("dock", title)] = dock.geometry().getRect()
        for i, widget in enumerate(dock.findChildren(QWidget)):
            corner = widget.mapTo(window, widget.rect().topLeft())
            out[("widget", title, i, type(widget).__name__)] = (
                widget.isVisible(), corner.x(), corner.y(), widget.width(), widget.height())
    return out
