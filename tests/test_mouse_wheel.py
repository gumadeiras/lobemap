"""A scroll over the View dock or the panel's menus changes nothing.

Every box and menu of the View dock, and the panel's Source and Driver line
menus, changes under the mouse wheel only once it has keyboard focus, which
a click or Tab gives it; until then the wheel is left to the widgets around
it. A stray scroll once left the view turned to "Vertical axis −2.0°".
Checked by what the viewer shows -- the camera, the slice axis, the brain
open, the source on show, the glomeruli drawn -- under the platform's own
style, and under Fusion, where a menu takes the wheel as a box does.
(`test_wheel.py` is the Python wheel's.)
"""

from __future__ import annotations

import contextlib

import pytest
from viewer_harness import launched, pump, session, switcher

pytestmark = pytest.mark.requires_data
pytest.importorskip("napari")


def _wheel(widget, notches: int) -> bool:
    """Turn the wheel over `widget`; whether it took the event."""
    from qtpy.QtCore import QPoint, QPointF, Qt
    from qtpy.QtGui import QWheelEvent
    from qtpy.QtWidgets import QApplication

    centre = QPointF(widget.rect().center())
    event = QWheelEvent(centre, widget.mapToGlobal(centre), QPoint(0, 0),
                        QPoint(0, 120 * notches), Qt.MouseButton.NoButton,
                        Qt.KeyboardModifier.NoModifier, Qt.ScrollPhase.NoScrollPhase, False)
    QApplication.sendEvent(widget, event)
    pump()
    return event.isAccepted()


@contextlib.contextmanager
def _style(name: str | None):
    """The application drawn in another style, `None` its own, then given back."""
    from qtpy.QtWidgets import QApplication

    own = QApplication.style().name()
    if name is not None:
        QApplication.setStyle(name)
        pump(100)
    try:
        yield
    finally:
        if name is not None:
            QApplication.setStyle(own)
            pump(100)


def _focus(window, widget, click: bool) -> None:
    """Give `widget` focus as a user does: a click, or Tab."""
    from qtpy.QtCore import Qt
    from qtpy.QtTest import QTest
    from qtpy.QtWidgets import QApplication

    QApplication.setActiveWindow(window)
    pump()
    if click:
        QTest.mouseClick(widget, Qt.MouseButton.LeftButton)
    else:
        widget.setFocus(Qt.FocusReason.TabFocusReason)
    pump()
    assert widget.hasFocus(), widget


def _wheels(widget) -> bool:
    """Whether the style lets the wheel change this kind of control at all.

    A box always; a menu as the platform has it: macOS's never takes the
    wheel, Fusion's does.
    """
    from qtpy.QtWidgets import QComboBox, QStyle

    if not isinstance(widget, QComboBox):
        return True
    return bool(widget.style().styleHint(QStyle.StyleHint.SH_ComboBox_AllowWheelScrolling,
                                         None, widget))


@pytest.mark.parametrize("style", [None, "Fusion"], ids=["native", "fusion"])
def test_the_wheel_changes_a_box_or_menu_only_once_it_has_focus(monkeypatch, style):
    from qtpy.QtCore import Qt
    from qtpy.QtWidgets import QComboBox

    with launched(monkeypatch, "view", "JRCFIB2018F") as (code, viewer), _style(style):
        assert code == 0
        window = viewer.window._qt_window
        window.setAttribute(Qt.WidgetAttribute.WA_DontShowOnScreen, True)
        window.resize(1440, 900)
        window.show()
        pump(300)
        sw, camera = switcher(viewer), viewer.scene.camera
        sess = session(viewer)
        page = sess.panel.pages["Glomeruli"]
        tab = sess.panel.tabs["neuprint_hemibrain"]
        # A brain that would open is asked for, and refused at once: what
        # matters is that the wheel asked.
        asked = []

        def refuse(space):
            asked.append(space)
            raise FileNotFoundError(space)

        sw._load = refuse

        def angles():
            return tuple(round(a, 6) for a in camera.angles)

        # Each control: the mode it works in, and what the viewer shows of it.
        controls = {
            "Brain": (sw.combo, 3, lambda: (session(viewer).space, tuple(asked))),
            "Zoom": (sw.camera.zoom, 3, lambda: round(camera.zoom, 6)),
            "Perspective": (sw.camera.perspective, 3, lambda: camera.perspective),
            "Line of sight": (sw.rotation.box["spin"], 3, angles),
            "Vertical axis": (sw.rotation.box["turn"], 3, angles),
            "Horizontal axis": (sw.rotation.box["tilt"], 3, angles),
            "Sections": (sw.slice, 2, lambda: int(viewer.dims.order[0])),
            # The driver lines first: choosing another source hides them.
            "Driver line": (tab.lines, 3, lambda: frozenset(tab.surface.selection)),
            "Source": (page.menu, 3, lambda: sess.panel.current()),
        }
        for name, (widget, ndisplay, shown) in controls.items():
            viewer.dims.ndisplay = ndisplay
            pump(200)
            assert widget.isEnabled(), name
            assert widget.focusPolicy() != Qt.FocusPolicy.WheelFocus, name
            # Down a notch, for a menu: the next item, where there is one.
            notches = -1 if isinstance(widget, QComboBox) else 1
            drawn = shown()
            assert not widget.hasFocus(), name
            taken = _wheel(widget, notches)
            pump(200)
            assert not taken, name                       # left for the dock
            assert shown() == drawn, name
            _focus(window, widget, click=not isinstance(widget, QComboBox))
            _wheel(widget, notches)
            pump(300)
            if _wheels(widget):
                assert shown() != drawn, name
            else:
                assert shown() == drawn, name
            widget.clearFocus()
        if style is not None:
            assert asked == ["JRCFIB2022M"], asked
