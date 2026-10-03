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

#: The columns, by position. The first four mean the same in both kinds of
#: tab; a glomerulus tab adds the receptor. A row is a compartment with all
#: its sides, so there is no side column: the details list the sides.
VISIBLE_COL, NAME_COL, LABEL_COL, FILL_COL, RECEPTOR_COL = range(5)
GLOMERULUS_COLUMNS = ("Show", "Glomerulus", "Label", "Fill", R.RECEPTOR)
NEUROPIL_COLUMNS = ("Show", "Neuropil", "Label", "Fill")

#: The checkbox columns, a fixed width each: they hold nothing to size to.
CHECK_COLUMNS = (VISIBLE_COL, LABEL_COL, FILL_COL)
CHECK_WIDTH = 38

SHOW_TIP = "Draw every side of it in 3D and on the slice"
LABEL_TIP = "Write the name of every side on the slice (Slice view only)"
FILL_TIP = "Fill the outline of every side on the slice (Slice view only)"

#: Cells carry their row's key here (`Row.key`). Once the table can be
#: sorted, the visual row is no longer the row's place and nothing may
#: assume it; nor is a row one compartment, but all its sides.
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

    The name sorts on its row's key; anything else naturally on its text.
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


class _Value(QLabel):
    """One detail's value, as tall as the longest value it can show needs.

    Sized again whenever its width changes, so selecting another row changes
    its text and nothing else. Measured on a plain label with its font and
    margins: this one can be selected with the mouse, so Qt lays its text
    out in a text document, whose height for a width the macOS style gave
    as a line per word -- 66 px held for a value that takes 18.
    """

    def __init__(self, values) -> None:
        super().__init__()
        self.setWordWrap(True)
        self.setTextInteractionFlags(Qt.TextSelectableByMouse)
        #: Every text this value can show.
        self._values = values
        self._width = None

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        if self.width() != self._width:
            self._width = self.width()
            self.setFixedHeight(self.needed())

    def needed(self) -> int:
        """The height the longest of its values takes at its width."""
        probe = QLabel()
        probe.setWordWrap(True)
        probe.setFont(self.font())
        margins = self.contentsMargins()
        inner = max(1, self.width() - margins.left() - margins.right())
        heights = []
        for text in self._values():
            probe.setText(text)
            heights.append(probe.heightForWidth(inner))
        tallest = max(heights, default=probe.sizeHint().height())
        return tallest + margins.top() + margins.bottom()


class AtlasTab(QWidget):
    """The table of one mesh: an atlas's glomeruli, or a neuropil set.

    A row is one compartment with all its sides (`rows.Row`), so its Show,
    Label and Fill boxes act on every side, and a box is half ticked when
    only some sides are: never by the panel's own controls, which act on
    whole rows, but by a selection set in code (`select`).
    """

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
        #: Row key -> what the row shows.
        self.rows: dict[int, R.Row] = {row.key: row for row in built}
        #: Compartment index -> the row holding it.
        self._row_by_index: dict[int, R.Row] = {
            i: row for row in built for i in row.indices
        }
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
        self.table = table = QTableWidget(len(self.rows), len(self.columns))
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
        # the name as wide as it needs, and the last text column takes what
        # is left, shortening a long receptor list rather than widening the
        # table. The tooltip has it in full.
        header = table.horizontalHeader()
        header.setMinimumSectionSize(24)
        header.setStretchLastSection(False)
        header.setSectionsClickable(True)
        for col in CHECK_COLUMNS:
            header.setSectionResizeMode(col, QHeaderView.Fixed)
            table.setColumnWidth(col, CHECK_WIDTH)
        stretch = RECEPTOR_COL if self.is_atlas else NAME_COL
        header.setSectionResizeMode(NAME_COL, QHeaderView.ResizeToContents)
        header.setSectionResizeMode(stretch, QHeaderView.Stretch)

        # Sorting must be off while the rows are built, or Qt reorders them
        # underneath the loop and the cells land on the wrong rows.
        table.setSortingEnabled(False)
        selection = self.surface.selection
        for r, row in enumerate(self.rows.values()):
            table.setItem(r, VISIBLE_COL, self._box(row, selection))
            table.setItem(r, NAME_COL, self._name_cell(row))
            table.setItem(r, LABEL_COL, self._box(row, (), LABEL_TIP))
            table.setItem(r, FILL_COL, self._box(row, (), FILL_TIP))
            if self.is_atlas:
                receptor = row.details[R.RECEPTOR]
                cell = _Cell(receptor)
                if receptor != R.MISSING:
                    cell.setToolTip(receptor)
                cell.setData(INDEX_ROLE, row.key)
                table.setItem(r, RECEPTOR_COL, cell)

        # Natural order on the name, and clickable headers from here on: the
        # table is long enough that scanning it unsorted is the wrong default.
        table.setSortingEnabled(True)
        table.sortItems(NAME_COL, Qt.AscendingOrder)
        table.itemChanged.connect(self._on_item_changed)
        table.itemSelectionChanged.connect(self._on_row_selected)
        return table

    @staticmethod
    def _state(row: R.Row, held) -> Qt.CheckState:
        """Ticked if every side is in `held`, half if some are, else not."""
        n = sum(i in held for i in row.indices)
        if n == len(row.indices):
            return Qt.Checked
        return Qt.PartiallyChecked if n else Qt.Unchecked

    def _box(self, row: R.Row, held, tip: str = "") -> QTableWidgetItem:
        box = QTableWidgetItem()
        box.setFlags(box.flags() | Qt.ItemIsUserCheckable)
        box.setCheckState(self._state(row, held))
        box.setData(INDEX_ROLE, row.key)
        if tip:
            box.setToolTip(tip)
        return box

    def _name_cell(self, row: R.Row) -> _Cell:
        """The name in its draw color, marked if it is not the standard one."""
        cell = _Cell(row.shown_name, key=(row.sort_key(),))
        rgba = self.surface.colors[row.indices[0]]
        cell.setForeground(
            QColor.fromRgbF(float(rgba[0]), float(rgba[1]), float(rgba[2]))
        )
        if row.name_tip:
            cell.setToolTip(row.name_tip)
        cell.setData(INDEX_ROLE, row.key)
        return cell

    def _make_details(self, one: str) -> QWidget:
        """The selected row's details, always in the kind's order.

        Below the table rather than in it: they are too many to be columns
        in a dock this narrow, and only one row's are read at a time. Each
        line is as tall as its longest value in this tab needs, wrapped and
        never cut short (`_Value`), so selecting another row changes their
        text and nothing else: a value that took one line more used to push
        the table up.
        """
        box = QWidget()
        form = QFormLayout(box)
        form.setContentsMargins(2, 4, 2, 0)
        form.setVerticalSpacing(2)
        # The values take the width there is, whatever their text: on macOS
        # they kept their own, so each row selected moved them.
        form.setFieldGrowthPolicy(QFormLayout.FieldGrowthPolicy.AllNonFixedFieldsGrow)
        self.detail_title = QLabel()
        bold = QFont(self.detail_title.font())
        bold.setBold(True)
        self.detail_title.setFont(bold)
        self._no_selection = f"Select a {one} to see its details"
        form.addRow(self.detail_title)
        #: Field -> the label showing its value for the selected row.
        self.details: dict[str, QLabel] = {}
        for name in self.detail_fields:
            value = _Value(lambda name=name: [row.details[name] for row in self.rows.values()])
            form.addRow(name, value)
            self.details[name] = value
        #: Opens the Virtual Fly Brain term page of the selected glomerulus.
        self.vfb = QPushButton(VFB_TEXT)
        self.vfb.clicked.connect(self._open_vfb)
        form.addRow(self.vfb)
        return box

    # -- rows ------------------------------------------------------------
    #
    # The visual row, the row's key and a compartment index are three
    # different numbers once the table can be sorted. Every cell carries its
    # row's key in INDEX_ROLE; nothing below may use a row number as either.

    def row_at(self, table_row: int) -> R.Row | None:
        """The row shown at `table_row` of the table, as it is sorted now."""
        item = self.table.item(table_row, VISIBLE_COL)
        key = item.data(INDEX_ROLE) if item is not None else None
        return None if key is None else self.rows.get(int(key))

    def table_row(self, index: int) -> int | None:
        """Where in the table the row of compartment `index` is now."""
        row = self._row_by_index.get(index)
        if row is None:
            return None
        for r in range(self.table.rowCount()):
            item = self.table.item(r, VISIBLE_COL)
            if item is not None and item.data(INDEX_ROLE) == row.key:
                return r
        return None

    def row_of(self, index: int) -> R.Row | None:
        """The row holding compartment `index`, with its other sides."""
        return self._row_by_index.get(index)

    def _push(self, selection: set[int]) -> None:
        """Show exactly these compartments, in whichever layer the mode draws.

        The surface draws its own selection in the mesh or, paired, in its
        contours (`AtlasSurface.sync`), so a bulk button and a single row's
        checkbox reach the same code and cannot disagree about the mode.
        """
        self.surface.set_selection(selection)
        self._set_checks(VISIBLE_COL, self.surface.selection)
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
        """How many rows are drawn: those with any side drawn, or none.

        None only while napari's eye has the drawing layer off in a way the
        surface did not take as a selection change -- the wrong mode's layer
        switched on, say -- so the count never claims what is not drawn.
        """
        selection = self.surface.selection
        shown = sum(any(i in selection for i in row.indices)
                    for row in self.rows.values())
        if shown and not self.surface.mode_layer().visible:
            self.count.setText(
                f"None shown: the layer is off in the layer list ({shown} checked)"
            )
        else:
            self.count.setText(f"{shown} of {len(self.rows)} shown")

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
        """One entry per driver line labelling any glomerulus of this atlas,
        with how many glomeruli it labels; it shows every side of each."""
        for line, names in lines.items():
            rows = [row for row in self.rows.values()
                    if any(s.reference_name and s.reference_name in names
                           for s in row.sides)]
            members = tuple(sorted(
                s.index for row in rows for s in row.sides
                if s.reference_name and s.reference_name in names
            ))
            if members:
                self.lines.addItem(f"{line} ({len(rows)})", members)

    def _apply_line(self, index: int) -> None:
        if index <= 0:
            return
        self._set_indices(self.lines.itemData(index) or ())

    def selected(self) -> R.Row | None:
        """The row the details describe: the first selected, if any."""
        model = self.table.selectionModel()
        picked = model.selectedRows() if model else []
        return self.row_at(picked[0].row()) if picked else None

    def _on_row_selected(self) -> None:
        row = self.selected()
        self.detail_title.setText(self._no_selection if row is None else row.name)
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
        """A box ticked or cleared by hand: every side of its row follows."""
        if self._updating or item.column() not in CHECK_COLUMNS:
            return
        row = self.rows.get(int(item.data(INDEX_ROLE)))
        if row is None:
            return
        on = item.checkState() == Qt.Checked
        if item.column() == VISIBLE_COL:
            held = set(self.surface.selection)
        elif self.contour is None:
            return
        else:
            held = set(self.contour.labels if item.column() == LABEL_COL
                       else self.contour.filled)
        held = held | set(row.indices) if on else held - set(row.indices)
        if item.column() == VISIBLE_COL:
            self._push(held)
        elif item.column() == LABEL_COL:
            self._set_labels(held)
        else:
            self._set_fills(held)

    def _set_checks(self, column: int, indices) -> set[int]:
        """Tick exactly the rows of these compartments in `column`, half
        where only some of a row's sides are among them."""
        wanted = set(indices)
        self._updating = True
        try:
            for r in range(self.table.rowCount()):
                item = self.table.item(r, column)
                row = self.row_at(r)
                if item is not None and row is not None:
                    state = self._state(row, wanted)
                    if item.checkState() != state:
                        item.setCheckState(state)
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
        n = self.surface.meshset.n_compartments
        self._push({int(i) for i in indices if 0 <= int(i) < n})

    def select(self, indices) -> None:
        """Show exactly these compartments, by mesh index, and tick their rows."""
        self._set_indices(indices)

    def _all(self) -> None:
        self._set_indices(self._row_by_index)

    def _none(self) -> None:
        self._set_indices(set())

    def _filtered_only(self) -> None:
        """Show every side of exactly the rows the search keeps."""
        kept = (self.row_at(r) for r in range(self.table.rowCount())
                if not self.table.isRowHidden(r))
        self._set_indices({i for row in kept if row is not None for i in row.indices})

    def _invert(self) -> None:
        self._set_indices(set(self._row_by_index) - set(self.surface.selection))

    def _apply_filter(self, text: str) -> None:
        """Keep the rows the search matches, by `Row.matches` alone: the
        same fields in every tab of a kind, and nothing a column hides."""
        for r in range(self.table.rowCount()):
            row = self.row_at(r)
            self.table.setRowHidden(r, row is None or not row.matches(text))

    # -- picking ---------------------------------------------------------

    def describe(self, index: int) -> str:
        """The status bar's words for a compartment under the cursor: its
        own side, not its row's every side."""
        row = self._row_by_index.get(index)
        return R.hover_line(row.side(index), self.surface.name) if row is not None else ""

    def highlight(self, index: int) -> None:
        """Select and scroll to the row of a compartment picked in the canvas.

        Found by the compartment's row rather than assumed to BE its index:
        after a sort the two differ, and picking used to jump to whatever
        glomerulus happened to occupy that row.
        """
        r = self.table_row(index)
        if r is not None:
            self.table.selectRow(r)
            self.table.scrollToItem(self.table.item(r, NAME_COL))


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
    "VISIBLE_COL",
    "AtlasTab",
]
