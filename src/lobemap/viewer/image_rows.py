"""The rows of the Your data tab that place the selected image: by hand, and
by landmarks.

By hand (`PlaceRows`): its voxel size and its center as numbers, one row
per axis, and turns, resizes and flips as buttons, each about the image's
center and on screen as you see it (`placing`), so a turn about the line of
sight turns the image in the plane you are looking at. Dragging moves it in
that plane.

By landmarks (`LandmarkRows`): choose a glomerulus, click its center in the
image in Slice view, and repeat; Fit then places the image so each clicked
point lands as near as it can on its glomerulus's centroid in the brain's
primary atlas (`core.placement`). Each landmark's distance from its
glomerulus is listed, and kept up to date as the image moves.
"""

from __future__ import annotations

import numpy as np
from qtpy.QtCore import Qt
from qtpy.QtWidgets import (
    QAbstractItemView,
    QCheckBox,
    QComboBox,
    QDoubleSpinBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
)

from ..core.names import parse_roi
from ..core.placement import (
    FitError,
    Landmark,
    apply,
    fit_affine,
    fit_similarity,
    middle,
    residuals,
    with_voxel,
)
from . import placing
from .chrome import GRID
from .rotation_rows import ROWS
from .rows import SIDES, natural_key
from .wheel import guard_wheel

VOXEL = "Voxel size"
VOXEL_TIP = ("The size of the image's voxels along its own {axis} axis. Changing it "
             "keeps the image's center where it is.")
CENTER = "Image center"
CENTER_TIP = ("Where the center of the image is along the brain's {axis} axis. Type a "
              "value to move the image there.")
TURN_BY_TIP = "How far each turn button turns the image."
SIZE_TIP = "Make the image smaller or larger about its center, by the step beside."
FLIP_TIP = "Mirror the image about its center, as you see it on screen."
DRAG = "Drag to move the image"
DRAG_TIP = ("While ticked, dragging in the view moves the selected image in the plane "
            "of the screen, and the view stays still.")
UNDO_TIP = "Put the image back as it was before the last change."
RESET_TIP = "Put the image back as it was opened. Undo brings back the change."

LANDMARKS = "Landmarks"
LANDMARKS_TIP = (
    "Place the image by glomeruli: choose one, click its center in the image in "
    "Slice view, and repeat. Fit then moves the image so each landmark is as near as "
    "it can be to the center of its glomerulus in the atlas named above.")
CLICK = "Click its center"
CLICK_TIP = "Then click the center of the glomerulus in the image. Slice view only."
CLICKING = "Click the center of {name} in the image."
OUTSIDE = "That point is outside the image."
REMOVE_TIP = "Remove the selected landmark."
FITS = {
    "Similarity": ("Move, turn, one scale and, if the landmarks ask for it, a mirror. "
                   "Trusts the voxel size. Needs 3 landmarks."),
    "Affine": ("Also stretches and shears: corrects a wrong voxel size, but follows "
               "the landmarks' errors. Needs 4 landmarks, not all in one plane."),
}
FITTED = "Fitted to {n} landmarks: {mean:.1f} µm off on average, {most:.1f} µm at most."

#: The turn rows: the View dock's names of the screen's axes (`rotation_rows`),
#: and the axis each turns about (`placing`).
_AXES = {"spin": placing.LINE_OF_SIGHT, "tilt": placing.HORIZONTAL, "turn": placing.VERTICAL}
ROW_TEXTS = tuple((text, _AXES[angle]) for text, angle, _tip in ROWS)


def _box(low: float, high: float, decimals: int, tip: str, suffix: str = "") -> QDoubleSpinBox:
    box = QDoubleSpinBox()
    box.setRange(low, high)
    box.setDecimals(decimals)
    box.setSuffix(suffix)
    box.setKeyboardTracking(False)
    box.setToolTip(tip)
    return box


def _button(text: str, tip: str, clicked) -> QPushButton:
    button = QPushButton(text)
    button.setToolTip(tip)
    button.clicked.connect(clicked)
    return button


def _row(*widgets) -> QHBoxLayout:
    row = QHBoxLayout()
    row.setContentsMargins(0, 0, 0, 0)
    row.setSpacing(GRID)
    for widget in widgets:
        row.addWidget(widget)
    row.addStretch(1)
    return row


def _quietly(box, value) -> None:
    box.blockSignals(True)
    try:
        box.setValue(value)
    finally:
        box.blockSignals(False)


class PlaceRows:
    """Voxel size, center, turns, size, flips, dragging, undo and reset.

    Not a widget: the tab lays the rows out in its own form (`add_to`). Each
    control hands a new placement to the tab (`ImagesBox.apply`).
    """

    def __init__(self, box) -> None:
        self.box = box
        #: One box per axis, x, y and z, each a row of its own: side by side
        #: they made the tab wider than its column.
        self.voxel = [_box(0.001, 1000.0, 3, VOXEL_TIP.format(axis=a), " µm") for a in "xyz"]
        self.center = [_box(-1e5, 1e5, 1, CENTER_TIP.format(axis=a), " µm") for a in "xyz"]
        for spin in self.voxel:
            spin.valueChanged.connect(self._on_voxel)
        for spin in self.center:
            spin.valueChanged.connect(self._on_center)
        self.turn_by = _box(0.1, 180.0, 1, TURN_BY_TIP, "°")
        self.turn_by.setValue(5.0)
        #: (minus, plus) per screen axis, in the View dock's order.
        self.turns = {}
        for text, axis in ROW_TEXTS:
            self.turns[axis] = tuple(
                _button(sign, f"Turn the image about the {text.lower()}.",
                        lambda _=False, a=axis, s=s: self._turn(a, s))
                for sign, s in (("−", -1.0), ("+", 1.0)))
        self.size_by = _box(0.1, 50.0, 1, SIZE_TIP, " %")
        self.size_by.setValue(5.0)
        self.smaller = _button("−", SIZE_TIP, lambda: self._size(-1.0))
        self.larger = _button("+", SIZE_TIP, lambda: self._size(1.0))
        self.flip_lr = _button("Left–right", FLIP_TIP, lambda: self._flip(False))
        self.flip_tb = _button("Top–bottom", FLIP_TIP, lambda: self._flip(True))
        self.drag = QCheckBox(DRAG)
        self.drag.setToolTip(DRAG_TIP)
        self.drag.toggled.connect(self._on_drag)
        self.undo = _button("Undo", UNDO_TIP, box.undo)
        self.reset = _button("Reset", RESET_TIP, self._reset)
        guard_wheel(*self.voxel, *self.center, self.turn_by, self.size_by)
        self._dragging = False

    def add_to(self, form) -> None:
        for heading, boxes in ((VOXEL, self.voxel), (CENTER, self.center)):
            form.addRow(QLabel(heading))
            for axis, box in zip("xyz", boxes, strict=True):
                form.addRow(axis, box)
        form.addRow("Turn by", self.turn_by)
        for text, axis in ROW_TEXTS:
            form.addRow(text, _row(*self.turns[axis]))
        form.addRow("Size", _row(self.smaller, self.larger, self.size_by))
        form.addRow("Flip", _row(self.flip_lr, self.flip_tb))
        form.addRow(None, self.drag)
        form.addRow(None, _row(self.undo, self.reset))

    def controls(self) -> list:
        return [*self.voxel, *self.center, self.turn_by, self.size_by, self.smaller,
                self.larger, self.flip_lr, self.flip_tb, self.drag, self.undo, self.reset,
                *(b for pair in self.turns.values() for b in pair)]

    def show(self, image) -> None:
        """Show `image`'s voxel size and center, or disable every row."""
        for control in self.controls():
            control.setEnabled(image is not None)
        if image is None:
            self.stop_dragging()
            return
        for spin, value in zip(self.voxel, image.voxel_um, strict=True):
            _quietly(spin, value)
        for spin, value in zip(self.center, middle(image.matrix, image.shape), strict=True):
            _quietly(spin, float(value))
        self.undo.setEnabled(bool(image.history))
        self.reset.setEnabled(bool(image.history))

    # -- by hand -------------------------------------------------------------------

    def _on_voxel(self, _value=None) -> None:
        image = self.box.current()
        voxel = tuple(spin.value() for spin in self.voxel)
        if image is not None and voxel != tuple(image.voxel_um):
            self.box.apply(with_voxel(image.matrix, image.shape, image.voxel_um, voxel),
                           voxel_um=voxel)

    def _on_center(self, _value=None) -> None:
        image = self.box.current()
        if image is not None:
            point = [spin.value() for spin in self.center]
            self.box.apply(placing.centered(image.matrix, image.shape, point))

    def _turn(self, axis: int, sign: float) -> None:
        image = self.box.current()
        if image is not None:
            self.box.apply(placing.turned(self.box.session, image.matrix, image.shape,
                                          axis, sign * self.turn_by.value()))

    def _size(self, sign: float) -> None:
        image = self.box.current()
        if image is not None:
            factor = 1.0 + self.size_by.value() / 100.0
            self.box.apply(placing.scaled(image.matrix, image.shape,
                                          factor if sign > 0 else 1.0 / factor))

    def _flip(self, top_bottom: bool) -> None:
        image = self.box.current()
        if image is not None:
            self.box.apply(placing.flipped(self.box.session, image.matrix, image.shape,
                                           top_bottom))

    def _reset(self) -> None:
        image = self.box.current()
        if image is not None and image.history:
            matrix, voxel, landmarks = image.history[0]
            self.box.apply(matrix, voxel, landmarks)

    # -- dragging ----------------------------------------------------------------------

    def _on_drag(self, on: bool) -> None:
        viewer = self.box.viewer
        if on and not self._dragging:
            self._dragging = True
            viewer.scene.camera.mouse_pan = False
            viewer.mouse_drag_callbacks.append(self._drag)
        elif not on and self._dragging:
            self._dragging = False
            viewer.scene.camera.mouse_pan = True
            if self._drag in viewer.mouse_drag_callbacks:
                viewer.mouse_drag_callbacks.remove(self._drag)

    def stop_dragging(self) -> None:
        """Give the mouse back to the view."""
        if self.drag.isChecked():
            self.drag.setChecked(False)
        else:
            self._on_drag(False)

    def _drag(self, _viewer, event):
        if getattr(event, "button", 1) != 1 or self.box.current() is None:
            return
        last = np.asarray(event.pos, float)
        first = True
        yield
        while event.type == "mouse_move":
            image = self.box.current()
            pos = np.asarray(event.pos, float)
            if image is None:
                return
            if np.any(pos != last):
                self.box.apply(placing.dragged(self.box.session, image.matrix, pos - last),
                               record=first)
                first, last = False, pos
            yield


def landmark_name(published: str) -> str:
    """'DA1 (left)': a glomerulus as a landmark is listed."""
    bare, side = parse_roi(published)
    where = SIDES.get(side or "")
    return f"{bare} ({where.lower()})" if where else bare


class LandmarkRows:
    """Choose a glomerulus, click it, list the landmarks, and fit."""

    def __init__(self, box) -> None:
        self.box = box
        self.heading = QLabel(LANDMARKS)
        self.heading.setToolTip(LANDMARKS_TIP)
        self.glomerulus = QComboBox()
        self.glomerulus.setToolTip(LANDMARKS_TIP)
        self.click = QPushButton(CLICK)
        self.click.setToolTip(CLICK_TIP)
        self.click.setCheckable(True)
        self.click.toggled.connect(self._on_click)
        self.table = QTableWidget(0, 2)
        self.table.setHorizontalHeaderLabels(["Glomerulus", "Off by"])
        self.table.verticalHeader().setVisible(False)
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.horizontalHeader().setSectionResizeMode(
            QHeaderView.ResizeMode.Stretch)
        self.table.setFixedHeight(5 * 24 + 2 * GRID)
        self.remove = _button("Remove landmark", REMOVE_TIP, self._remove)
        self.kind = QComboBox()
        for name, tip in FITS.items():
            self.kind.addItem(name)
            self.kind.setItemData(self.kind.count() - 1, tip, Qt.ItemDataRole.ToolTipRole)
        self.kind.setToolTip(FITS["Similarity"])
        self.kind.currentTextChanged.connect(lambda name: self.kind.setToolTip(FITS[name]))
        self.fit = _button("Fit", "Place the image by its landmarks.", self._fit)
        self.result = QLabel("")
        self.result.setWordWrap(True)
        guard_wheel(self.glomerulus, self.kind)
        #: Each glomerulus's centroid in the brain's primary atlas, by its
        #: published name; and the names in the menu's order.
        self.targets: dict[str, np.ndarray] = {}
        #: The image shown last; see `show`.
        self._image = None
        self._viewer = box.viewer
        self._viewer.dims.events.ndisplay.connect(self._on_mode)
        self._on_mode()

    def add_to(self, form) -> None:
        form.addRow(self.heading)
        form.addRow("Glomerulus", self.glomerulus)
        form.addRow(None, self.click)
        form.addRow(self.table)
        form.addRow(None, self.remove)
        form.addRow("Fit", _row(self.kind, self.fit))
        form.addRow(self.result)

    def controls(self) -> list:
        return [self.glomerulus, self.click, self.remove, self.kind, self.fit]

    def attach(self, session) -> None:
        """Take the glomeruli of `session`'s primary atlas as the targets."""
        primary = session.registry.primary_atlas(session.space)
        surface = session.surfaces.get(primary.id) if primary is not None else None
        self.targets = {}
        if surface is not None:
            meshset = surface.meshset
            self.targets = {name: np.asarray(meshset.centroid(i), float)
                            for i, name in enumerate(meshset.names)}
        self.glomerulus.clear()
        for name in sorted(self.targets, key=lambda n: natural_key(landmark_name(n))):
            self.glomerulus.addItem(landmark_name(name), name)
        self.heading.setText(f"{LANDMARKS} ({surface.name})" if surface else LANDMARKS)

    def detach(self) -> None:
        self.click.setChecked(False)
        self.targets = {}
        self.glomerulus.clear()

    def show(self, image) -> None:
        """List `image`'s landmarks, each with how far it is from its glomerulus.

        A newly selected image is fitted as an affine if the file left any of
        its voxel size unstated: a similarity would trust a size that is a
        guess.
        """
        if image is not self._image:
            self._image = image
            if image is not None:
                self.kind.setCurrentText("Similarity" if image.voxel_stated else "Affine")
        on = image is not None and bool(self.targets)
        for control in self.controls():
            control.setEnabled(on)
        self._on_mode()
        if not on:
            self.click.setChecked(False)
            self.table.setRowCount(0)
            self.result.setText("")
            return
        off = self._residuals(image)
        self.table.setRowCount(len(image.landmarks))
        for r, (mark, distance) in enumerate(zip(image.landmarks, off, strict=True)):
            name = QTableWidgetItem(landmark_name(mark.name))
            value = QTableWidgetItem("—" if distance is None else f"{distance:.1f} µm")
            value.setTextAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
            self.table.setItem(r, 0, name)
            self.table.setItem(r, 1, value)
        self.remove.setEnabled(bool(image.landmarks))

    def _residuals(self, image) -> list:
        known = [m for m in image.landmarks if m.name in self.targets]
        off = iter(residuals(image.matrix, [m.index for m in known],
                             [self.targets[m.name] for m in known])) if known else iter(())
        return [float(next(off)) if m.name in self.targets else None
                for m in image.landmarks]

    def _on_mode(self, event=None) -> None:
        two_d = self._viewer.dims.ndisplay == 2
        if not two_d:
            self.click.setChecked(False)
        self.click.setEnabled(two_d and self.box.current() is not None and bool(self.targets))

    # -- clicking ----------------------------------------------------------------------

    def _on_click(self, on: bool) -> None:
        callbacks = self._viewer.mouse_drag_callbacks
        if on:
            if self._clicked not in callbacks:
                callbacks.append(self._clicked)
            self.box.say(CLICKING.format(name=self.glomerulus.currentText()))
        elif self._clicked in callbacks:
            callbacks.remove(self._clicked)

    def _clicked(self, _viewer, event):
        """A click that does not drag puts the landmark there."""
        from .app import CLICK_SLOP

        if getattr(event, "button", 1) != 1:
            return
        start = np.asarray(event.pos, float)
        yield
        while event.type == "mouse_move":
            if np.hypot(*(np.asarray(event.pos, float) - start)) > CLICK_SLOP:
                return
            yield
        self._put(np.asarray(event.position, float))

    def _put(self, world) -> None:
        image, name = self.box.current(), self.glomerulus.currentData()
        if image is None or name is None:
            return
        space = placing.space_point(self.box.session, world)
        index = apply(np.linalg.inv(image.matrix), space)[0]
        shape = np.asarray(image.shape, float)
        if np.any(index < -0.5) or np.any(index > shape - 0.5):
            self.box.say(OUTSIDE)
            return
        marks = [m for m in image.landmarks if m.name != name]
        marks.append(Landmark(name, tuple(float(v) for v in index)))
        self.click.setChecked(False)
        self.box.say("")
        self.box.apply(image.matrix, landmarks=marks)

    def _remove(self) -> None:
        image, row = self.box.current(), self.table.currentRow()
        if image is not None and 0 <= row < len(image.landmarks):
            marks = list(image.landmarks)
            del marks[row]
            self.box.apply(image.matrix, landmarks=marks)

    def _fit(self) -> None:
        image = self.box.current()
        if image is None:
            return
        known = [m for m in image.landmarks if m.name in self.targets]
        index = np.array([m.index for m in known], float).reshape(-1, 3)
        target = np.array([self.targets[m.name] for m in known], float).reshape(-1, 3)
        try:
            if self.kind.currentText() == "Affine":
                matrix = fit_affine(index, target)
            else:
                matrix = fit_similarity(index, target, image.voxel_um)
        except FitError as exc:
            self.result.setText(str(exc).capitalize() + ".")
            return
        off = residuals(matrix, index, target)
        self.box.apply(matrix)
        self.result.setText(FITTED.format(n=len(known), mean=float(off.mean()),
                                          most=float(off.max())))


__all__ = ["LandmarkRows", "PlaceRows", "landmark_name"]
