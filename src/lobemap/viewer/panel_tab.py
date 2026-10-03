"""One tab of the compartment panel: one mesh's compartments, as a table.

A view bound to one layer, never a union across atlases -- that is what
keeps it usable as atlases accumulate (design section 7). The table is for
bulk selection; it complements click-to-identify rather than replacing it:
picking in the canvas selects the row here, and vice versa.

A checked row is a drawn compartment, in either mode: the rows are the
selection, and the selection is what `AtlasSurface.sync` draws.

Every tab of a kind shows the same columns, details and search, from
`rows`: a glomerulus tab for an atlas, a neuropil tab for reference
geometry. What a column means is decided there, not here.
"""

from __future__ import annotations

import webbrowser

from qtpy.QtCore import Qt
from qtpy.QtGui import QColor, QFont
from qtpy.QtWidgets import (
    QAbstractItemView,
    QComboBox,
    QFormLayout,
    QGridLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from . import rows as R

#: The columns, by position. The first five mean the same in both kinds of
#: tab; a glomerulus tab adds the receptor.
VISIBLE_COL, NAME_COL, SIDE_COL, LABEL_COL, FILL_COL, RECEPTOR_COL = range(6)
GLOMERULUS_COLUMNS = ("Show", "Glomerulus", "Side", "Label", "Fill", R.RECEPTOR)
NEUROPIL_COLUMNS = ("Show", "Neuropil", "Side", "Label", "Fill")

#: The checkbox columns, a fixed width each: they hold nothing to size to.
CHECK_COLUMNS = (VISIBLE_COL, LABEL_COL, FILL_COL)
CHECK_WIDTH = 38

SHOW_TIP = "Draw it in 3D and on the slice"
LABEL_TIP = "Write the name on the slice (Slice view only)"
FILL_TIP = "Fill the outline on the slice (Slice view only)"

#: Rows carry their compartment index here. Once the table can be sorted,
#: the visual row is no longer the compartment id and nothing may assume it.
INDEX_ROLE = Qt.UserRole

#: First entry of the driver-line menu, which applies nothing.
LINE_PROMPT = "Driver line: none"
LINE_TIP = ("Show the glomeruli that a driver line labels, "
            "from lobemap's reference table")

ON_SLICE = "On slice"
#: The same row in 3D, where it draws nothing. Two lines, so the label
#: column stays as narrow as the buttons beside it allow.
ON_SLICE_3D = "On slice\n(Slice view only)"

VFB_TEXT = "Open in Virtual Fly Brain"
VFB_NONE = "Select a glomerulus with a Virtual Fly Brain term to open it"


def _words(is_atlas: bool) -> tuple[str, str]:
    """What one row is, and what several are, in this kind of tab."""
    return ("glomerulus", "glomeruli") if is_atlas else ("neuropil", "neuropils")


def _bulk_buttons(is_atlas: bool) -> tuple[tuple[str, str], tuple[str, str]]:
    """(text, tooltip) of the Show row, then of the On slice row."""
    one, many = _words(is_atlas)
    show = (
        ("All", f"Show every {one} in this tab"),
        ("None", f"Hide every {one} in this tab"),
        ("Matches", f"Show only the {many} that match the search"),
        ("Invert", f"Show the hidden {many} and hide the shown ones"),
    )
    on_slice = (
        ("Names", f"Write the name of every shown {one} on the slice"),
        ("No names", f"Remove the name of every {one} from the slice"),
        ("Fill", f"Fill the outline of every shown {one} on the slice"),
        ("No fill", f"Draw the outline of every {one} on the slice without fill"),
    )
    return show, on_slice


class _Cell(QTableWidgetItem):
    """A text cell that sorts on a key rather than by raw code point.

    The name sorts naturally and then by side; the side by side and then
    name; anything else naturally on its text.
    """

    def __init__(self, text: str, key=None) -> None:
        super().__init__(text)
        self.key = key if key is not None else (R.natural_key(text),)
        if text == R.MISSING:
            self.setToolTip(R.MISSING_TIP)

    def __lt__(self, other):
        if isinstance(other, _Cell):
            return self.key < other.key
        return super().__lt__(other)


class AtlasTab(QWidget):
    """The table of one mesh: an atlas's glomeruli, or a neuropil set."""

    def __init__(self, surface, compartments=None, contour=None,
                 annotation=None, is_atlas: bool = True, lines=None,
                 neuropil_names=None) -> None:
        super().__init__()
        self.surface = surface
        self.contour = contour
        #: False for a neuropil layer: the same widget, with the columns and
        #: details of a neuropil.
        self.is_atlas = is_atlas
        self.compartments = list(compartments or [])
        names = surface.meshset.names
        built = (R.glomerulus_rows(names, self.compartments, annotation or {})
                 if is_atlas else R.neuropil_rows(names, neuropil_names or {}))
        #: Compartment index -> what its row shows.
        self.rows: dict[int, R.Row] = {row.index: row for row in built}
        self.columns = GLOMERULUS_COLUMNS if is_atlas else NEUROPIL_COLUMNS
        self.detail_fields = R.GLOMERULUS_DETAILS if is_atlas else R.NEUROPIL_DETAILS
        self._updating = False
        self._three_d: bool | None = None
        one, _many = _words(is_atlas)

        layout = QVBoxLayout()
        layout.setContentsMargins(4, 4, 4, 4)

        self.filter = QLineEdit()
        self.filter.setPlaceholderText(
            "Search name, receptor, sensillum, organ…" if is_atlas
            else "Search neuropils…"
        )
        self.filter.textChanged.connect(self._apply_filter)
        layout.addWidget(self.filter)

        #: Driver-line presets: the glomeruli each line labels, by the
        #: reference table.
        self.lines = QComboBox()
        self.lines.setToolTip(LINE_TIP)
        self.lines.addItem(LINE_PROMPT, ())
        self.lines.currentIndexChanged.connect(self._apply_line)
        layout.addWidget(self.lines)

        # The details first, though they sit below the table: selecting a
        # row fills them, and the table can select one as it is built.
        details = self._make_details(one)
        layout.addLayout(self._make_buttons(is_atlas))
        layout.addWidget(self._make_table(), stretch=1)
        layout.addWidget(details)

        self.count = QLabel()
        layout.addWidget(self.count)
        self.setLayout(layout)

        self._fill_lines(lines or {})
        self.lines.setVisible(is_atlas and self.lines.count() > 1)
        self.vfb.setVisible(is_atlas)
        self._on_row_selected()

        # The table follows the eye in napari's layer list, and the count
        # follows whichever layer the mode draws.
        surface.listeners.append(self._sync_rows)
        surface.layer.events.visible.connect(self._update_count)
        if contour is not None:
            contour.layer.events.visible.connect(self._update_count)
        self._update_count()

    # -- building --------------------------------------------------------

    def _make_buttons(self, is_atlas: bool) -> QGridLayout:
        """The Show row above the On slice row, each button in a column."""
        grid = QGridLayout()
        grid.setSpacing(4)
        show, on_slice = _bulk_buttons(is_atlas)
        slots = {
            "All": self._all, "None": self._none,
            "Matches": self._filtered_only, "Invert": self._invert,
            "Names": self._labels_for_shown, "No names": self._no_labels,
            "Fill": self._fill_for_shown, "No fill": self._no_fill,
        }
        self.on_slice = QLabel(ON_SLICE)
        self._two_d_buttons: list[QPushButton] = []
        for r, (title, buttons) in enumerate(((QLabel("Show"), show),
                                              (self.on_slice, on_slice))):
            grid.addWidget(title, r, 0)
            for c, (text, tip) in enumerate(buttons, start=1):
                button = QPushButton(text)
                button.setToolTip(tip)
                button.clicked.connect(slots[text])
                grid.addWidget(button, r, c)
                if r == 1:
                    self._two_d_buttons.append(button)
        for c in range(1, 5):
            grid.setColumnStretch(c, 1)
        # As wide as the 3D wording in either mode, so switching modes does
        # not shift the buttons sideways.
        metrics = self.on_slice.fontMetrics()
        grid.setColumnMinimumWidth(0, max(
            metrics.horizontalAdvance(line) for line in ON_SLICE_3D.splitlines()
        ))
        return grid

    def _make_table(self) -> QTableWidget:
        n = self.surface.meshset.n_compartments
        self.table = table = QTableWidget(n, len(self.columns))
        table.setHorizontalHeaderLabels(list(self.columns))
        for col, tip in ((VISIBLE_COL, SHOW_TIP), (LABEL_COL, LABEL_TIP),
                         (FILL_COL, FILL_TIP)):
            table.horizontalHeaderItem(col).setToolTip(tip)
        table.verticalHeader().setVisible(False)
        table.setSelectionBehavior(QAbstractItemView.SelectRows)
        table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        table.setWordWrap(False)
        table.setTextElideMode(Qt.ElideRight)

        # Fits the dock without scrolling sideways: fixed checkbox columns,
        # the name and side as wide as they need, and the last text column
        # takes what is left, shortening a long receptor list rather than
        # widening the table. The tooltip has it in full.
        header = table.horizontalHeader()
        header.setMinimumSectionSize(24)
        header.setStretchLastSection(False)
        header.setSectionsClickable(True)
        for col in CHECK_COLUMNS:
            header.setSectionResizeMode(col, QHeaderView.Fixed)
            table.setColumnWidth(col, CHECK_WIDTH)
        header.setSectionResizeMode(SIDE_COL, QHeaderView.ResizeToContents)
        stretch = RECEPTOR_COL if self.is_atlas else NAME_COL
        header.setSectionResizeMode(NAME_COL, QHeaderView.ResizeToContents)
        header.setSectionResizeMode(stretch, QHeaderView.Stretch)

        # Sorting must be off while the rows are built, or Qt reorders them
        # underneath the loop and the cells land on the wrong rows.
        table.setSortingEnabled(False)
        selection = self.surface.selection
        for r, row in enumerate(self.rows.values()):
            table.setItem(r, VISIBLE_COL, self._box(row.index, row.index in selection))
            table.setItem(r, NAME_COL, self._name_cell(row))
            side = _Cell(row.side, key=(row.sort_key()[1], R.natural_key(row.name)))
            side.setData(INDEX_ROLE, row.index)
            table.setItem(r, SIDE_COL, side)
            table.setItem(r, LABEL_COL, self._box(row.index, False, LABEL_TIP))
            table.setItem(r, FILL_COL, self._box(row.index, False, FILL_TIP))
            if self.is_atlas:
                receptor = row.details[R.RECEPTOR]
                cell = _Cell(receptor)
                if receptor != R.MISSING:
                    cell.setToolTip(receptor)
                cell.setData(INDEX_ROLE, row.index)
                table.setItem(r, RECEPTOR_COL, cell)

        # Natural order on the name, then side, and clickable headers from
        # here on: the table is long enough that scanning it unsorted is the
        # wrong default.
        table.setSortingEnabled(True)
        table.sortItems(NAME_COL, Qt.AscendingOrder)
        table.itemChanged.connect(self._on_item_changed)
        table.itemSelectionChanged.connect(self._on_row_selected)
        return table

    @staticmethod
    def _box(index: int, checked: bool, tip: str = "") -> QTableWidgetItem:
        box = QTableWidgetItem()
        box.setFlags(box.flags() | Qt.ItemIsUserCheckable)
        box.setCheckState(Qt.Checked if checked else Qt.Unchecked)
        box.setData(INDEX_ROLE, index)
        if tip:
            box.setToolTip(tip)
        return box

    def _name_cell(self, row: R.Row) -> _Cell:
        """The name in its draw color, marked if it is not the standard one."""
        cell = _Cell(row.shown_name, key=row.sort_key())
        rgba = self.surface.colors[row.index]
        cell.setForeground(
            QColor.fromRgbF(float(rgba[0]), float(rgba[1]), float(rgba[2]))
        )
        if row.name_tip:
            cell.setToolTip(row.name_tip)
        cell.setData(INDEX_ROLE, row.index)
        return cell

    def _make_details(self, one: str) -> QWidget:
        """The selected row's details, always in the kind's order.

        Below the table rather than in it: they are too many to be columns
        in a dock this narrow, and only one row's are read at a time.
        """
        box = QWidget()
        form = QFormLayout(box)
        form.setContentsMargins(2, 4, 2, 0)
        form.setVerticalSpacing(2)
        self.detail_title = QLabel()
        bold = QFont(self.detail_title.font())
        bold.setBold(True)
        self.detail_title.setFont(bold)
        self._no_selection = f"Select a {one} to see its details"
        form.addRow(self.detail_title)
        #: Field -> the label showing its value for the selected row.
        self.details: dict[str, QLabel] = {}
        for name in self.detail_fields:
            value = QLabel()
            value.setWordWrap(True)
            value.setTextInteractionFlags(Qt.TextSelectableByMouse)
            form.addRow(name, value)
            self.details[name] = value
        #: Opens the Virtual Fly Brain term page of the selected glomerulus.
        self.vfb = QPushButton(VFB_TEXT)
        self.vfb.clicked.connect(self._open_vfb)
        form.addRow(self.vfb)
        return box

    # -- helpers ---------------------------------------------------------
    #
    # The visual row and the compartment index are different numbers once
    # the table can be sorted. Every row carries its index in INDEX_ROLE;
    # nothing below may use a row number as a compartment id.

    def _index_of(self, row: int) -> int | None:
        item = self.table.item(row, VISIBLE_COL)
        if item is None:
            return None
        value = item.data(INDEX_ROLE)
        return None if value is None else int(value)

    def _row_of(self, index: int) -> int | None:
        for row in range(self.table.rowCount()):
            if self._index_of(row) == index:
                return row
        return None

    def _push(self, selection: set[int]) -> None:
        """Show exactly these compartments, in whichever layer the mode draws.

        The surface draws its own selection in the mesh or, paired, in its
        contours (`AtlasSurface.sync`), so a bulk button and a single row's
        checkbox reach the same code and cannot disagree about the mode.
        """
        self.surface.set_selection(selection)
        self._selection_changed()

    def _selection_changed(self) -> None:
        self._update_count()
        # A driver line stays named only while it is what is shown.
        wanted = self.lines.currentData()
        if self.lines.currentIndex() > 0 and set(wanted or ()) != self.surface.selection:
            self.lines.blockSignals(True)
            self.lines.setCurrentIndex(0)
            self.lines.blockSignals(False)

    def _sync_rows(self) -> None:
        """Check exactly the selected rows, after the eye changed them."""
        self._set_checks(VISIBLE_COL, self.surface.selection)
        self._selection_changed()

    def _update_count(self, event=None) -> None:
        """How many are drawn, which is the checked ones or none.

        None only while napari's eye has the drawing layer off in a way the
        surface did not take as a selection change -- the wrong mode's layer
        switched on, say -- so the count never claims what is not drawn.
        """
        n = self.table.rowCount()
        shown = len(self.surface.selection)
        if shown and not self.surface.mode_layer().visible:
            self.count.setText(
                f"None shown: the layer is off in the layer list ({shown} checked)"
            )
        else:
            self.count.setText(f"{shown} of {n} shown")

    def set_mode(self, three_d: bool) -> None:
        """Disable the slice-only controls in 3D, where they draw nothing."""
        if three_d == self._three_d:
            return
        self._three_d = three_d
        for button in self._two_d_buttons:
            button.setEnabled(not three_d)
        self.on_slice.setEnabled(not three_d)
        self.on_slice.setText(ON_SLICE_3D if three_d else ON_SLICE)
        self._updating = True
        try:
            for row in range(self.table.rowCount()):
                for col in (LABEL_COL, FILL_COL):
                    item = self.table.item(row, col)
                    flags = item.flags()
                    item.setFlags(flags & ~Qt.ItemIsEnabled if three_d
                                  else flags | Qt.ItemIsEnabled)
        finally:
            self._updating = False
        self._update_count()

    # -- driver lines, details and VFB -----------------------------------

    def _fill_lines(self, lines) -> None:
        """One entry per driver line labelling any glomerulus of this atlas."""
        for line, names in lines.items():
            members = tuple(sorted(
                i for i, row in self.rows.items()
                if row.reference_name and row.reference_name in names
            ))
            if members:
                self.lines.addItem(f"{line} ({len(members)})", members)

    def _apply_line(self, index: int) -> None:
        if index <= 0:
            return
        self._set_indices(self.lines.itemData(index) or ())

    def selected(self) -> R.Row | None:
        """The row the details describe: the first selected, if any."""
        model = self.table.selectionModel()
        picked = model.selectedRows() if model else []
        index = self._index_of(picked[0].row()) if picked else None
        return self.rows.get(index) if index is not None else None

    def _on_row_selected(self) -> None:
        row = self.selected()
        if row is None:
            self.detail_title.setText(self._no_selection)
        else:
            known = row.side not in (R.MISSING, "")
            self.detail_title.setText(f"{row.name}, {row.side}" if known else row.name)
        for name, label in self.details.items():
            value = row.details[name] if row is not None else ""
            label.setText(value)
            label.setToolTip(R.MISSING_TIP if value == R.MISSING else "")
        url = row.vfb if row is not None else ""
        self.vfb.setEnabled(bool(url))
        self.vfb.setToolTip(
            f"Open the Virtual Fly Brain page for {row.reference_name}" if url
            else VFB_NONE
        )

    def _open_vfb(self) -> None:
        """Open the selected glomerulus's term page on Virtual Fly Brain."""
        row = self.selected()
        if row is not None and row.vfb:
            webbrowser.open(row.vfb)

    # -- handlers --------------------------------------------------------

    def _on_item_changed(self, item: QTableWidgetItem) -> None:
        if self._updating:
            return
        if item.column() in (LABEL_COL, FILL_COL):
            if self.contour is not None:
                index = int(item.data(INDEX_ROLE))
                on = item.checkState() == Qt.Checked
                if item.column() == LABEL_COL:
                    self.contour.set_label(index, on)
                else:
                    self.contour.set_fill(index, on)
            return
        if item.column() != VISIBLE_COL:
            return
        index = int(item.data(INDEX_ROLE))
        visible = item.checkState() == Qt.Checked
        self.surface.set_visible(index, visible)
        self._selection_changed()

    def _set_checks(self, column: int, indices) -> set[int]:
        """Tick exactly these compartments in `column`, whatever the order."""
        wanted = set(indices)
        self._updating = True
        try:
            for row in range(self.table.rowCount()):
                item = self.table.item(row, column)
                index = self._index_of(row)
                if item is not None and index is not None:
                    item.setCheckState(
                        Qt.Checked if index in wanted else Qt.Unchecked
                    )
        finally:
            self._updating = False
        return wanted

    def _set_labels(self, indices) -> None:
        wanted = self._set_checks(LABEL_COL, indices)
        if self.contour is not None:
            self.contour.set_labels(wanted)

    def _set_fills(self, indices) -> None:
        wanted = self._set_checks(FILL_COL, indices)
        if self.contour is not None:
            self.contour.set_fills(wanted)

    def _labels_for_shown(self) -> None:
        """Name whatever is currently shown -- the useful bulk action."""
        self._set_labels(set(self.surface.selection))

    def _no_labels(self) -> None:
        self._set_labels(set())

    def _fill_for_shown(self) -> None:
        """Fill whatever is currently shown, matching `Names`."""
        self._set_fills(set(self.surface.selection))

    def _no_fill(self) -> None:
        self._set_fills(set())

    def _set_indices(self, indices) -> None:
        """Show exactly these COMPARTMENTS, whatever order the rows are in."""
        wanted = set(indices)
        self._updating = True
        selection = set()
        for row in range(self.table.rowCount()):
            index = self._index_of(row)
            if index is None:
                continue
            on = index in wanted
            self.table.item(row, VISIBLE_COL).setCheckState(
                Qt.Checked if on else Qt.Unchecked
            )
            if on:
                selection.add(index)
        self._updating = False
        self._push(selection)

    def select(self, indices) -> None:
        """Check exactly these compartments, and draw them."""
        self._set_indices(indices)

    def _all(self) -> None:
        self._set_indices(set(self.rows))

    def _none(self) -> None:
        self._set_indices(set())

    def _filtered_only(self) -> None:
        """Check exactly the compartments whose rows the search keeps."""
        self._set_indices({
            self._index_of(r) for r in range(self.table.rowCount())
            if not self.table.isRowHidden(r) and self._index_of(r) is not None
        })

    def _invert(self) -> None:
        self._set_indices(set(self.rows) - set(self.surface.selection))

    def _apply_filter(self, text: str) -> None:
        """Keep the rows the search matches, by `Row.matches` alone: the
        same fields in every tab of a kind, and nothing a column hides."""
        for r in range(self.table.rowCount()):
            row = self.rows.get(self._index_of(r))
            self.table.setRowHidden(r, row is None or not row.matches(text))

    # -- picking ---------------------------------------------------------

    def describe(self, index: int) -> str:
        """The status bar's words for a compartment under the cursor."""
        row = self.rows.get(index)
        return R.hover_line(row, self.surface.name) if row is not None else ""

    def highlight(self, index: int) -> None:
        """Select and scroll to the row for a compartment picked in the canvas.

        Found by index rather than assumed to BE the index: after a sort
        the two differ, and picking used to jump to whatever glomerulus
        happened to occupy that row.
        """
        row = self._row_of(index)
        if row is not None:
            self.table.selectRow(row)
            self.table.scrollToItem(self.table.item(row, NAME_COL))


__all__ = [
    "CHECK_COLUMNS",
    "CHECK_WIDTH",
    "FILL_COL",
    "GLOMERULUS_COLUMNS",
    "INDEX_ROLE",
    "LABEL_COL",
    "LINE_PROMPT",
    "NAME_COL",
    "NEUROPIL_COLUMNS",
    "RECEPTOR_COL",
    "SIDE_COL",
    "VISIBLE_COL",
    "AtlasTab",
]
