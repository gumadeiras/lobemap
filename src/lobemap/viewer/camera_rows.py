"""The View dock's zoom and perspective: the camera's own two numbers.

Both are napari's camera's, kept in step with it both ways, so the mouse,
Fit to window and napari's camera popup move them, and they move the view:

- **Zoom** is napari's zoom factor: how many screen pixels one micrometer
  of the brain takes, since napari's world is in micrometers here
  (`core.units`). It is the number napari's popup shows. A percentage of
  the fitted view was the other plain choice, but the fit differs by brain,
  mode, window size and turn, so one percentage would have meant a
  different size each time.
- **Perspective** is the 3D camera's field of view, 0 to 90 degrees; 0 is
  flat, with no perspective, as lobemap opens. It applies to 3D alone, so
  Slice view disables it, and its tooltip says so.

The zoom box is sized for its widest number, not for the one it shows, so
the dock does not reflow while the mouse zooms.
"""

from __future__ import annotations

from qtpy.QtWidgets import QAbstractSpinBox, QDoubleSpinBox, QSizePolicy, QSpinBox

ZOOM = "Zoom"
ZOOM_UNIT = " pixels per µm"
ZOOM_TIP = (
    "How large the brain is drawn: screen pixels per micrometer of the brain. "
    "Scrolling on the image zooms too."
)
#: The zoom box's range: napari's popup offers 0.01 to 100.
ZOOM_RANGE = (0.001, 1000.0)
PERSPECTIVE = "Perspective"
PERSPECTIVE_TIP = (
    "How much larger near parts of the brain look than far ones: a camera's "
    "field of view, from 0°, flat, to 90°. 3D only."
)
FLAT = "0° (flat)"


class CameraRows:
    """The zoom box and the perspective box, and the camera they follow.

    Not a widget: the View dock lays the two out as rows of its own form,
    labeled `ZOOM` and `PERSPECTIVE`. Connected to the viewer's camera
    and its display mode once; the dock outlives every scene, and so do
    they.
    """

    def __init__(self, viewer) -> None:
        self.viewer = viewer
        camera = viewer.scene.camera

        self.zoom = QDoubleSpinBox()
        self.zoom.setRange(*ZOOM_RANGE)
        self.zoom.setDecimals(3)
        self.zoom.setStepType(QAbstractSpinBox.StepType.AdaptiveDecimalStepType)
        self.zoom.setSuffix(ZOOM_UNIT)
        # A value is taken once it is entered, not at each keystroke.
        self.zoom.setKeyboardTracking(False)
        self.zoom.setToolTip(ZOOM_TIP)
        self.zoom.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)

        self.perspective = QSpinBox()
        self.perspective.setRange(0, 90)
        self.perspective.setSuffix("°")
        self.perspective.setSpecialValueText(FLAT)
        self.perspective.setKeyboardTracking(False)
        self.perspective.setToolTip(PERSPECTIVE_TIP)

        self._show_zoom()
        self._show_perspective()
        self._on_mode()
        self.zoom.valueChanged.connect(self._set_zoom)
        self.perspective.valueChanged.connect(self._set_perspective)
        camera.events.zoom.connect(self._show_zoom)
        camera.events.perspective.connect(self._show_perspective)
        viewer.dims.events.ndisplay.connect(self._on_mode)

    def _show_zoom(self, event=None) -> None:
        _quietly(self.zoom, float(self.viewer.scene.camera.zoom))

    def _show_perspective(self, event=None) -> None:
        _quietly(self.perspective, round(float(self.viewer.scene.camera.perspective)))

    def _set_zoom(self, value: float) -> None:
        self.viewer.scene.camera.zoom = float(value)

    def _set_perspective(self, value: int) -> None:
        self.viewer.scene.camera.perspective = float(value)

    def _on_mode(self, event=None) -> None:
        three_d = self.viewer.dims.ndisplay == 3
        if not three_d:
            # A value typed in 3D leaves its text selected, and a disabled box
            # drew the selection as an enabled one does.
            self.perspective.lineEdit().deselect()
        self.perspective.setEnabled(three_d)


def _quietly(box, value) -> None:
    """Show `value` in `box` without handing it back to the camera."""
    box.blockSignals(True)
    try:
        box.setValue(value)
    finally:
        box.blockSignals(False)


__all__ = [
    "FLAT",
    "PERSPECTIVE",
    "ZOOM",
    "ZOOM_UNIT",
    "CameraRows",
]
