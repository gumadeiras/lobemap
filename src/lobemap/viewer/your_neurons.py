"""Your neurons in the Your data tab: add them from FlyWire or an SWC file,
show, hide and remove them.

A FlyWire neuron is named by its root ID, or by a FlyWire Codex link to it;
its skeleton is fetched and bridged into the open brain in the background
(`core.neurons.load`), which can take seconds the first time. An SWC file
says nothing of its coordinates, so the tab asks: whose they are, and in
what units. A neuron that lands outside the brain is said to, as a likely
sign that the coordinates or units chosen are not the file's.

The neurons stay with the brain they were added to, as your images do.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
from qtpy.QtCore import Qt
from qtpy.QtGui import QColor, QIcon, QPixmap
from qtpy.QtWidgets import (
    QComboBox,
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QWidget,
)

from ..core.neurons import (
    FLYWIRE_LATERAL,
    FLYWIRE_TEMPLATE,
    SWC_UNITS,
    NeuronError,
    load,
    parse_spec,
)
from .background import Job
from .chrome import GRID, fit_form, grid_form
from .neurons import COLORS, KEY, Neuron, build
from .wheel import guard_wheel

FLYWIRE_TIP = ("A FlyWire root ID, or a FlyWire Codex link to a neuron. lobemap "
               "downloads the neuron from FlyWire and moves it into this brain.")
FLYWIRE_HINT = "Root ID or Codex link"
ADD = "Add"
SWC = "Add SWC file…"
SWC_TIP = "Add a neuron from an SWC file, in the coordinates and units chosen below."
COORDINATES_TIP = ("Which brain the SWC file's coordinates come from. lobemap moves "
                   "a neuron from another brain into this one.")
UNITS_TIP = "The units of the SWC file's points."
LIST_TIP = "Your neurons in this brain. Untick one to hide it."
REMOVE_TIP = "Take the selected neuron out of this brain."
READING = "Reading {name}…"
OUTSIDE = ("{name} lies outside this brain: check the coordinates and units "
           "chosen for its file.")


@dataclass(frozen=True)
class Coordinates:
    """Where an SWC file's points may be: a template and its laterality, or
    the open brain's own coordinates (`template` None). The menu shows
    `title`, short so the tab fits its column, and `tip` in full."""

    title: str
    tip: str
    template: str | None
    lateral: str | None


def coordinates(registry, space_id: str) -> list[Coordinates]:
    """The coordinates an SWC file may be in, in the brain `space_id`: FlyWire,
    this brain's own, and every other brain a bridge reaches."""
    space = registry.spaces[space_id]
    out = [Coordinates("FlyWire", "FlyWire's: FAFB v14.1", FLYWIRE_TEMPLATE, FLYWIRE_LATERAL),
           Coordinates("This brain", f"This brain's own: {space.title or space_id}",
                       None, None)]
    if not space.is_island:
        for other in registry.spaces.values():
            if other.id != space_id and not other.is_island:
                title = other.title or other.id
                out.append(Coordinates(title.split(" (")[0], title, other.flybrains_template,
                                       other.lateral_convention))
    return out


def _swatch(color: str) -> QIcon:
    pixmap = QPixmap(12, 12)
    pixmap.fill(QColor(color))
    return QIcon(pixmap)


class NeuronsBox(QWidget):
    """The neurons part of the Your data tab."""

    def __init__(self, viewer, parent=None) -> None:
        super().__init__(parent)
        self.viewer = viewer
        self.session = None
        #: Each brain's neurons, by space id.
        self._neurons: dict[str, list[Neuron]] = {}
        self._jobs: list[Job] = []
        self._added = 0

        self.flywire = QLineEdit()
        self.flywire.setPlaceholderText(FLYWIRE_HINT)
        self.flywire.setToolTip(FLYWIRE_TIP)
        self.flywire.returnPressed.connect(self._add_typed)
        self.add = QPushButton(ADD)
        self.add.setToolTip(FLYWIRE_TIP)
        self.add.clicked.connect(self._add_typed)
        self.swc = QPushButton(SWC)
        self.swc.setToolTip(SWC_TIP)
        self.swc.clicked.connect(self._choose)
        self.frame = QComboBox()
        self.frame.setToolTip(COORDINATES_TIP)
        self.units = QComboBox()
        self.units.addItems(list(SWC_UNITS))
        self.units.setToolTip(UNITS_TIP)
        self.list = QListWidget()
        self.list.setToolTip(LIST_TIP)
        self.list.setFixedHeight(4 * 24 + 2 * GRID)
        self.list.itemChanged.connect(self._on_tick)
        self.remove = QPushButton("Remove")
        self.remove.setToolTip(REMOVE_TIP)
        self.remove.clicked.connect(self._remove)
        self.status = QLabel("")
        self.status.setWordWrap(True)
        guard_wheel(self.frame, self.units)

        typed = QHBoxLayout()
        typed.setContentsMargins(0, 0, 0, 0)
        typed.setSpacing(GRID)
        typed.addWidget(self.flywire, 1)
        typed.addWidget(self.add)
        form = grid_form(self)
        form.addRow(QLabel("<b>Neurons</b>"))
        form.addRow("FlyWire", typed)
        # Right under Add, where what it is reading, or why it could not, is seen.
        form.addRow(self.status)
        form.addRow(None, self.swc)
        form.addRow("Coordinates", self.frame)
        form.addRow("Units", self.units)
        form.addRow(self.list)
        form.addRow(None, self.remove)
        fit_form(self, form, (self.add, self.swc, self.frame, self.units, self.remove))
        self.flywire.setFixedHeight(self.add.height())
        # As wide as its hint, which it cut short at its own size.
        self.flywire.setMinimumWidth(
            self.flywire.fontMetrics().horizontalAdvance(FLYWIRE_HINT) + 3 * GRID)
        self._fill_list()

    # -- the brain open ---------------------------------------------------------

    def neurons(self) -> list[Neuron]:
        return self._neurons.setdefault(self.session.space, []) if self.session else []

    def attach(self, session) -> None:
        """Show this brain's neurons in `session`, a scene just opened."""
        self.session = session
        self.frame.clear()
        for choice in coordinates(session.registry, session.space):
            self.frame.addItem(choice.title, choice)
            self.frame.setItemData(self.frame.count() - 1, choice.tip,
                                   Qt.ItemDataRole.ToolTipRole)
        self._build()
        self._fill_list()

    def detach(self) -> None:
        for job in self._jobs:
            job.cancel()
        self._jobs = []
        self.session = None

    def _build(self) -> None:
        """Draw this brain's neurons, as one part of the scene (`neurons.build`)."""
        session, neurons = self.session, list(self.neurons())
        if not neurons and KEY not in session.surfaces:
            return                  # nothing to draw, or to take out
        session.set_part(KEY, (lambda: build(self.viewer, neurons, session.mirror_args()))
                         if neurons else None)
        surface = session.surfaces.get(KEY)
        if surface is not None:
            surface.listeners.append(self._on_eye)

    def _on_eye(self) -> None:
        """napari's eye showed or hid neurons: tick them as they are drawn."""
        surface = self.session.surfaces.get(KEY) if self.session else None
        if surface is not None:
            for i, neuron in enumerate(self.neurons()):
                neuron.visible = i in surface.selection
        self._fill_list()

    # -- the list ------------------------------------------------------------------

    def _fill_list(self) -> None:
        row = self.list.currentRow()
        self.list.blockSignals(True)
        try:
            self.list.clear()
            for neuron in self.neurons():
                item = QListWidgetItem(_swatch(neuron.color), neuron.name)
                item.setFlags(item.flags() | Qt.ItemFlag.ItemIsUserCheckable)
                item.setCheckState(Qt.CheckState.Checked if neuron.visible
                                   else Qt.CheckState.Unchecked)
                item.setToolTip(neuron.source)
                self.list.addItem(item)
            if self.list.count():
                self.list.setCurrentRow(min(max(row, 0), self.list.count() - 1))
        finally:
            self.list.blockSignals(False)
        on = self.session is not None
        for control in (self.flywire, self.add, self.swc, self.frame, self.units):
            control.setEnabled(on)
        self.remove.setEnabled(on and self.list.count() > 0)

    def _on_tick(self, item) -> None:
        neurons = self.neurons()
        neurons[self.list.row(item)].visible = item.checkState() == Qt.CheckState.Checked
        surface = self.session.surfaces.get(KEY) if self.session else None
        if surface is not None:
            surface.set_selection({i for i, n in enumerate(neurons) if n.visible})

    def _remove(self) -> None:
        row = self.list.currentRow()
        neurons = self.neurons()
        if 0 <= row < len(neurons):
            del neurons[row]
            self._build()
            self._fill_list()

    def say(self, text: str) -> None:
        self.status.setText(text)

    # -- adding ----------------------------------------------------------------------

    def _add_typed(self) -> None:
        text = self.flywire.text().strip()
        if text:
            self.add_neuron(text)

    def _choose(self) -> None:
        path, _ = QFileDialog.getOpenFileName(self, SWC.rstrip("…"), "", "SWC (*.swc)")
        if path:
            self.add_neuron(path)

    def add_neuron(self, text: str) -> None:
        """Add the neuron `text` names -- a root ID, a Codex link, an SWC file
        -- to this brain, in the background."""
        if self.session is None:
            return
        try:
            spec = parse_spec(text)
        except NeuronError as exc:
            self.say(str(exc))
            return
        if spec.root_id is not None and any(n.name == spec.name for n in self.neurons()):
            self.say(f"{spec.name} is already shown.")
            return
        choice = self.frame.currentData()
        template = choice.template if choice is not None else None
        lateral = choice.lateral if choice is not None else None
        units = SWC_UNITS[self.units.currentText()]
        session = self.session
        space = session.registry.spaces[session.space]
        self.say(READING.format(name=spec.name))

        def done(result) -> None:
            if self.session is not session or session.closed:
                return
            points, parents, source = result
            color = COLORS[self._added % len(COLORS)]
            self._added += 1
            neuron = Neuron(spec.name, source, points, parents, color)
            self.neurons().append(neuron)
            self._build()
            self.flywire.clear()
            self._fill_list()
            self.list.setCurrentRow(self.list.count() - 1)
            self.say("" if self._inside(points) else OUTSIDE.format(name=spec.name))

        def failed(exc) -> None:
            if self.session is session and not session.closed:
                self.say(str(exc))

        self._jobs = [job for job in self._jobs if job.running]
        self._jobs.append(Job(lambda: load(spec, space, template, lateral, units),
                              done, failed))

    def _inside(self, points) -> bool:
        """Whether any of `points` is within the box of the brain's meshes:
        the built ones, and the corners of those not read yet (`deferred`)."""
        session = self.session
        boxes = [(surface.meshset.vertices.min(axis=0), surface.meshset.vertices.max(axis=0))
                 for key, surface in session.surfaces.items()
                 if key != KEY and len(surface.meshset.vertices)]
        if session.deferred is not None:
            boxes += [b for b in map(session.deferred.bounds, session.pending) if b is not None]
        if not boxes:
            return True
        lo = np.min([np.asarray(b[0], float) for b in boxes], axis=0)
        hi = np.max([np.asarray(b[1], float) for b in boxes], axis=0)
        points = np.asarray(points, float)
        return bool(np.any(np.all((points >= lo) & (points <= hi), axis=1)))


__all__ = ["Coordinates", "NeuronsBox", "coordinates"]
