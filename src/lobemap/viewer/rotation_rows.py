"""The View dock's rotation rows: one angle about each axis of the screen.

Always in view, in 3D and in Slice view, so a turned view is never hidden
behind a closed group. Each row is named by the screen axis it turns about,
in the order of 0.1's controls -- line of sight, vertical, horizontal, which
were "Z/slice", "Y/vertical" and "X/horizontal" -- and not by x, y and z:
those name the image's own axes, which differ from the screen's once the
slice axis changes. What the angles mean is `rotation`'s, where they are
spin, tilt and turn.
"""

from __future__ import annotations

from qtpy.QtCore import Signal
from qtpy.QtWidgets import (
    QDoubleSpinBox,
    QFormLayout,
    QLabel,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

HEADING = "Rotate around"
HEADING_TIP = (
    "Turn the view, in 3D and in Slice view, where a turn about the vertical "
    "or horizontal axis cuts oblique sections. Dragging in 3D leaves the "
    "angles as they are; a new angle or Home view puts the camera at Home "
    "turned by them."
)
#: Each row: its label, the angle of `rotation` it sets, and its positive sense.
ROWS = (
    ("Line of sight", "spin",
     "Turn the picture in the screen plane. Positive is counterclockwise."),
    ("Vertical axis", "turn",
     ("Turn about the screen's vertical axis. Positive moves the near side to "
      "your right.")),
    ("Horizontal axis", "tilt",
     "Turn about the screen's horizontal axis. Positive brings the top toward you."),
)
RESET = "Reset rotation"
RESET_TIP = "Set all three angles to 0°."


class RotationRows(QWidget):
    """A heading, one angle box per screen axis, and a reset button.

    `changed` carries (spin, tilt, turn) once per edit: an arrow step, or a
    typed value once it is entered, never each keystroke, since a turn
    across the image grid resamples the image.
    """

    changed = Signal(float, float, float)

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.heading = QLabel(HEADING)
        self.heading.setToolTip(HEADING_TIP)
        rows = QFormLayout()
        rows.setContentsMargins(12, 0, 0, 0)
        #: The angle boxes by the angle they set: "spin", "tilt", "turn".
        self.box: dict[str, QDoubleSpinBox] = {}
        for text, angle, tip in ROWS:
            box = QDoubleSpinBox()
            box.setRange(-180.0, 180.0)
            box.setWrapping(True)
            box.setSingleStep(1.0)
            box.setDecimals(1)
            box.setSuffix("°")
            box.setKeyboardTracking(False)
            box.setToolTip(tip)
            box.valueChanged.connect(self._on_value)
            label = QLabel(text)
            label.setToolTip(tip)
            label.setBuddy(box)
            rows.addRow(label, box)
            self.box[angle] = box
        self.rows = rows
        self.reset = QPushButton(RESET)
        self.reset.setToolTip(RESET_TIP)
        self.reset.clicked.connect(self._on_reset)
        rows.addRow(self.reset)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(2)
        layout.addWidget(self.heading)
        layout.addLayout(rows)

    def angles(self) -> tuple[float, float, float]:
        """(spin, tilt, turn), as `SceneSession.set_rotation` takes them."""
        return tuple(self.box[a].value() for a in ("spin", "tilt", "turn"))

    def _on_value(self, _value: float) -> None:
        self.changed.emit(*self.angles())

    def _on_reset(self) -> None:
        """All three to zero, as one change rather than three."""
        if not any(self.angles()):
            return
        for box in self.box.values():
            box.blockSignals(True)
            box.setValue(0.0)
            box.blockSignals(False)
        self._on_value(0.0)


__all__ = ["HEADING", "RESET", "ROWS", "RotationRows"]
