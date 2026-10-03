"""The View dock's rotation group: three angles, folded away by default.

Folded, its header still says the angles, so a turned view is never hidden
behind a closed group. What the angles mean is `rotation`'s; the dock hands
them to the open scene (`switcher.SpaceSwitcher`).
"""

from __future__ import annotations

from qtpy.QtCore import Qt, Signal
from qtpy.QtWidgets import (
    QDoubleSpinBox,
    QFormLayout,
    QLabel,
    QPushButton,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

#: Each angle's box: its label, and its positive sense.
ANGLES = (
    ("Spin (in the screen plane)",
     "Turn the picture in the screen plane. Positive is counterclockwise."),
    ("Tilt (top toward you)",
     "Turn about the screen's horizontal axis. Positive brings the top toward you."),
    ("Turn (about the vertical)",
     "Turn about the screen's vertical axis. Positive moves the front to your right."),
)
HEADER = "Rotation  {}"
HEADER_TIP = (
    "Spin, tilt and turn, in degrees. They work in 3D and in Slice view, where "
    "tilt and turn cut oblique sections. Dragging in 3D leaves them as they "
    "are; a new angle or Home view puts the camera at Home turned by them."
)
RESET = "Reset rotation"
RESET_TIP = "Set all three angles to 0°."


def degrees(value: float) -> str:
    """'30°', '12.5°', '-90°': one decimal, and none when it is zero."""
    text = f"{value:.1f}".removesuffix(".0")
    return f"{'0' if text == '-0' else text}°"


class RotationGroup(QWidget):
    """A header that folds the three angle boxes and the reset button away.

    `changed` carries (spin, tilt, turn) once per edit: an arrow step, or a
    typed value once it is entered, never each keystroke, since a turn
    across the image grid resamples it.
    """

    changed = Signal(float, float, float)

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.header = QToolButton()
        self.header.setCheckable(True)
        self.header.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
        self.header.setAutoRaise(True)
        self.header.setToolTip(HEADER_TIP)
        self.header.toggled.connect(self._fold)

        self.body = QWidget()
        form = QFormLayout(self.body)
        form.setContentsMargins(16, 0, 0, 0)
        #: The spin, tilt and turn boxes, in that order.
        self.boxes: list[QDoubleSpinBox] = []
        for text, tip in ANGLES:
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
            form.addRow(label, box)
            self.boxes.append(box)
        self.reset = QPushButton(RESET)
        self.reset.setToolTip(RESET_TIP)
        self.reset.clicked.connect(self._on_reset)
        form.addRow(self.reset)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(2)
        layout.addWidget(self.header)
        layout.addWidget(self.body)
        self._fold(False)
        self._show_angles()

    def angles(self) -> tuple[float, float, float]:
        spin, tilt, turn = (box.value() for box in self.boxes)
        return spin, tilt, turn

    def _fold(self, unfolded: bool) -> None:
        self.body.setVisible(unfolded)
        self.header.setArrowType(Qt.ArrowType.DownArrow if unfolded
                                 else Qt.ArrowType.RightArrow)

    def _show_angles(self) -> None:
        self.header.setText(HEADER.format(", ".join(degrees(a) for a in self.angles())))

    def _on_value(self, _value: float) -> None:
        self._show_angles()
        self.changed.emit(*self.angles())

    def _on_reset(self) -> None:
        """All three to zero, as one change rather than three."""
        if not any(self.angles()):
            return
        for box in self.boxes:
            box.blockSignals(True)
            box.setValue(0.0)
            box.blockSignals(False)
        self._on_value(0.0)


__all__ = ["ANGLES", "HEADER", "RESET", "RotationGroup", "degrees"]
