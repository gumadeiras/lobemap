"""Your images in the Your data tab: open, show, place, fit and save them.

An image is opened into the brain that is open, and stays with that brain:
its placement is into that brain's space. It opens where its alignment file
put it in that brain (`core.placement.read_alignment`), or else unturned,
its center where the view is looking. A voxel size the file does not state
is 1 µm until you set it, and the tab says so.

Every change of placement is undone by Undo, back to the image as it was
opened; Save keeps it, with the landmarks, in the alignment file beside the
image, and the next opening in this brain starts from there.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

import numpy as np
from qtpy.QtCore import Qt
from qtpy.QtWidgets import (
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QWidget,
)

from ..core.placement import Alignment, placed_at, read_alignment, write_alignment
from ..core.user_image import SUFFIXES, OpenedImage, read_image
from .background import Job
from .chrome import GRID, add_gap, fit_form, grid_form
from .image_rows import LandmarkRows, PlaceRows
from .placed import PlacedImage
from .placing import space_point

OPEN = "Open image…"
OPEN_TIP = ("Open a TIFF or NRRD stack of your own, to place it in this brain. Its "
            "channels are shown in green, magenta, cyan and yellow.")
REMOVE = "Remove"
REMOVE_TIP = "Take the selected image out of this brain. Unsaved changes are lost."
SAVE = "Save alignment"
SAVE_TIP = ("Keep where the image is, its voxel size and its landmarks, beside the image "
            "in <name>.lobemap.json. It opens there next time, in this brain.")
LIST_TIP = "Your images in this brain. Untick one to hide it; select one to place it."
#: The file dialog's filter.
FILTER = "Images ({})".format(" ".join(f"*{s}" for s in SUFFIXES))

#: Voxel size, um, of an axis the file does not state.
UNSTATED_UM = 1.0

#: The percentiles of an image's values its contrast opens on.
CONTRAST_PERCENTILES = (0.5, 99.8)


@dataclass
class YourImage:
    """An image of yours in one brain: its voxels, and where they are placed."""

    opened: OpenedImage
    matrix: np.ndarray
    voxel_um: tuple[float, float, float]
    #: Whether every voxel size is stated, by the file or the alignment file.
    voxel_stated: bool
    contrast: list[tuple[float, float]]
    landmarks: list = field(default_factory=list)
    visible: bool = True
    #: Whether the placement is the one the alignment file keeps.
    saved: bool = True
    #: Each placement before the present one, oldest first.
    history: list = field(default_factory=list)
    #: How the scene draws it, while it is in one.
    placed: PlacedImage | None = None

    @property
    def path(self) -> Path:
        return self.opened.path

    @property
    def name(self) -> str:
        return self.opened.path.name

    @property
    def shape(self) -> tuple[int, int, int]:
        return self.opened.shape


def contrast_of(channel: np.ndarray) -> tuple[float, float]:
    """The contrast a channel opens on: its values' middle 99.3%."""
    sample = channel[tuple(slice(None, None, max(1, n // 128)) for n in channel.shape)]
    lo, hi = (float(v) for v in np.percentile(sample, CONTRAST_PERCENTILES))
    return (lo, hi if hi > lo else lo + 1.0)


def opened_in(opened: OpenedImage, space: str, center) -> YourImage:
    """`opened` in `space`: where its alignment file puts it, or at `center`."""
    contrast = [contrast_of(channel) for channel in opened.channels]
    kept = read_alignment(opened.path, space)
    if kept is not None:
        return YourImage(opened, kept.matrix, tuple(kept.voxel_um), True, contrast,
                         list(kept.landmarks))
    stated = all(v is not None for v in opened.voxel_um)
    voxel = tuple(UNSTATED_UM if v is None else float(v) for v in opened.voxel_um)
    return YourImage(opened, placed_at(opened.shape, voxel, center), voxel, stated, contrast)


class ImagesBox(QWidget):
    """The images part of the Your data tab."""

    def __init__(self, viewer, parent=None) -> None:
        super().__init__(parent)
        self.viewer = viewer
        self.session = None
        #: Each brain's images, by space id.
        self._images: dict[str, list[YourImage]] = {}
        self._jobs: list[Job] = []

        self.open = QPushButton(OPEN)
        self.open.setToolTip(OPEN_TIP)
        self.open.clicked.connect(self._choose)
        self.list = QListWidget()
        self.list.setToolTip(LIST_TIP)
        self.list.setFixedHeight(4 * 24 + 2 * GRID)
        self.list.itemChanged.connect(self._on_tick)
        self.list.currentRowChanged.connect(self._on_row)
        self.remove = QPushButton(REMOVE)
        self.remove.setToolTip(REMOVE_TIP)
        self.remove.clicked.connect(self._remove)
        self.save = QPushButton(SAVE)
        self.save.setToolTip(SAVE_TIP)
        self.save.clicked.connect(self._save)
        self.status = QLabel("")
        self.status.setWordWrap(True)
        self.place = PlaceRows(self)
        self.landmarks = LandmarkRows(self)

        buttons = QHBoxLayout()
        buttons.setContentsMargins(0, 0, 0, 0)
        buttons.setSpacing(GRID)
        buttons.addWidget(self.remove)
        buttons.addWidget(self.save)
        buttons.addStretch(1)
        heading = QLabel("<b>Images</b>")
        form = grid_form(self)
        form.addRow(heading)
        form.addRow(self.open)
        form.addRow(self.list)
        form.addRow(buttons)
        form.addRow(self.status)
        add_gap(form)
        self.place.add_to(form)
        add_gap(form)
        self.landmarks.add_to(form)
        fit_form(self, form, (self.open, self.remove, self.save,
                              *self.place.controls(), *self.landmarks.controls()))
        self.refresh()

    # -- the brain open ---------------------------------------------------------

    def images(self) -> list[YourImage]:
        return self._images.setdefault(self.session.space, []) if self.session else []

    def attach(self, session) -> None:
        """Show this brain's images in `session`, a scene just opened."""
        self.session = session
        for image in self.images():
            self._draw(image)
        self.landmarks.attach(session)
        self._fill_list()
        self.say_notes()

    def detach(self) -> None:
        """The scene is gone, and the layers with it; the images stay."""
        self.landmarks.detach()
        self.place.stop_dragging()
        for image in self.images():
            image.placed = None
        for job in self._jobs:
            job.cancel()
        self._jobs = []
        self.session = None

    def _draw(self, image: YourImage) -> None:
        image.placed = PlacedImage(self.viewer, image.name, image.opened.channels,
                                   image.matrix, image.contrast)
        image.placed.listeners.append(lambda: self._shown(image))
        self.session.add_placed(image.placed)
        image.placed.set_visible(image.visible)

    def _shown(self, image: YourImage) -> None:
        """napari's eye showed or hid `image`."""
        image.visible = image.placed.visible
        self._fill_list()

    # -- the list ------------------------------------------------------------------

    def current(self) -> YourImage | None:
        row = self.list.currentRow()
        images = self.images()
        return images[row] if 0 <= row < len(images) else None

    def _fill_list(self, select: int | None = None) -> None:
        row = self.list.currentRow() if select is None else select
        self.list.blockSignals(True)
        try:
            self.list.clear()
            for image in self.images():
                item = QListWidgetItem(image.name + ("" if image.saved else " •"))
                item.setFlags(item.flags() | Qt.ItemFlag.ItemIsUserCheckable)
                item.setCheckState(Qt.CheckState.Checked if image.visible
                                   else Qt.CheckState.Unchecked)
                item.setToolTip(str(image.path))
                self.list.addItem(item)
            if self.list.count():
                self.list.setCurrentRow(min(max(row, 0), self.list.count() - 1))
        finally:
            self.list.blockSignals(False)
        self.refresh()

    def _on_tick(self, item) -> None:
        image = self.images()[self.list.row(item)]
        image.visible = item.checkState() == Qt.CheckState.Checked
        if image.placed is not None:
            image.placed.set_visible(image.visible)

    def refresh(self) -> None:
        """Show the selected image's state in every control."""
        image = self.current()
        self.remove.setEnabled(image is not None)
        self.save.setEnabled(image is not None and not image.saved)
        self.place.show(image)
        self.landmarks.show(image)

    def _on_row(self, _row: int = -1) -> None:
        """Another image selected: say what its file left to do."""
        self.say_notes()
        self.refresh()

    def say_notes(self) -> None:
        """Say how the selected image was read, and what its file left unstated."""
        image = self.current()
        self.say("" if image is None else self._words(image))

    @staticmethod
    def _words(image: YourImage) -> str:
        notes = list(image.opened.notes)
        if not image.voxel_stated:
            notes.append("The file does not state every voxel size: set it below.")
        return " ".join(n if n.endswith(".") else n[0].upper() + n[1:] + "." for n in notes)

    def say(self, text: str) -> None:
        self.status.setText(text)

    # -- opening, removing and saving ------------------------------------------------

    def _choose(self) -> None:
        path, _ = QFileDialog.getOpenFileName(self, OPEN.rstrip("…"), "", FILTER)
        if path:
            self.open_path(path)

    def open_path(self, path) -> None:
        """Open `path` into this brain, in the background."""
        if self.session is None:
            return
        session, path = self.session, Path(path)
        self.say(f"Opening {path.name}…")

        def done(opened: OpenedImage) -> None:
            if self.session is not session or session.closed:
                return
            try:
                image = opened_in(opened, session.space, self._view_center())
            except ValueError as exc:
                self.say(str(exc))
                return
            self.images().append(image)
            self._draw(image)
            self._fill_list(select=len(self.images()) - 1)
            self.say_notes()

        def failed(exc) -> None:
            if self.session is session and not session.closed:
                self.say(str(exc))

        self._jobs = [job for job in self._jobs if job.running]
        self._jobs.append(Job(lambda: read_image(path), done, failed))

    def _view_center(self) -> np.ndarray:
        """The point of the space at the middle of the view."""
        dims = self.viewer.dims
        point = np.array(dims.point, float)
        shown = list(dims.displayed)
        point[shown] = np.asarray(self.viewer.scene.camera.center, float)[-len(shown):]
        return space_point(self.session, point)

    def _remove(self) -> None:
        image = self.current()
        if image is None:
            return
        self.place.stop_dragging()
        if image.placed is not None:
            self.session.drop_placed(image.placed)
            image.placed = None
        self.images().remove(image)
        self._fill_list()
        self.say_notes()

    def _save(self) -> None:
        image = self.current()
        if image is None:
            return
        try:
            path = write_alignment(image.path, self.session.space, Alignment(
                image.matrix, image.voxel_um, list(image.landmarks)))
        except (OSError, ValueError) as exc:
            self.say(f"Not saved: {exc}")
            return
        image.saved = True
        self.say(f"Saved in {path.name}.")
        self._fill_list()

    # -- placing ----------------------------------------------------------------------

    def apply(self, matrix, voxel_um=None, landmarks=None, record: bool = True) -> None:
        """Place the selected image by `matrix`, with its voxel size and
        landmarks if given; `record` keeps the placement before for Undo."""
        image = self.current()
        if image is None or self.session is None:
            return
        if record:
            image.history.append((image.matrix, image.voxel_um, list(image.landmarks)))
        image.matrix = np.asarray(matrix, float)
        if voxel_um is not None:
            image.voxel_um, image.voxel_stated = tuple(voxel_um), True
        if landmarks is not None:
            image.landmarks = list(landmarks)
        was_saved, image.saved = image.saved, False
        if image.placed is not None:
            self.session.place(image.placed, image.matrix)
        if was_saved:
            self._fill_list()
        else:
            self.refresh()

    def undo(self) -> None:
        """Put the selected image back as it was before the last change."""
        image = self.current()
        if image is None or not image.history:
            return
        matrix, voxel, landmarks = image.history.pop()
        self.apply(matrix, voxel, landmarks, record=False)


__all__ = ["ImagesBox", "YourImage", "contrast_of", "opened_in"]
