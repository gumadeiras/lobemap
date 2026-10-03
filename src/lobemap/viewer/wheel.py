"""The mouse wheel changes a box or a menu only once it has keyboard focus.

Qt hands a wheel event to the box or menu under the cursor, which steps its
value: a scroll that only passed over the View dock turned the view to
"Vertical axis −2.0°", and over Brain it would open another brain. Guarded,
a box or menu without focus leaves the event to the widgets around it, so
the wheel changes nothing there. A click, or Tab, gives it focus, and the
wheel then steps it as before; a wheel event no longer gives focus.
"""

from __future__ import annotations

from qtpy.QtCore import QEvent, QObject, Qt


class _Guard(QObject):
    def eventFilter(self, watched, event) -> bool:
        if event.type() == QEvent.Type.Wheel and not watched.hasFocus():
            # Ignored, so Qt passes it on to the parents of the widget.
            event.ignore()
            return True
        return False


def guard_wheel(*widgets) -> None:
    """Let the wheel change each of `widgets` only while it has focus."""
    for widget in widgets:
        if widget.focusPolicy() == Qt.FocusPolicy.WheelFocus:
            widget.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        widget.installEventFilter(_Guard(widget))


__all__ = ["guard_wheel"]
