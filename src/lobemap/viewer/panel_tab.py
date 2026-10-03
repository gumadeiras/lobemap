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

from qtpy.QtCore import QSize, Qt
from qtpy.QtGui import QColor, QFont
from qtpy.QtWidgets import (
    QAbstractItemView,
    QComboBox,
    QFormLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QPushButton,
    QSizePolicy,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from . import rows as R
from .check_header import CheckHeader
from .wheel import guard_wheel

#: The columns, by position. The first four mean the same in both kinds of
#: tab; a glomerulus tab adds the receptor. A row is a compartment with all
#: its sides, so there is no side column: the details list the sides.
VISIBLE_COL, NAME_COL, LABEL_COL, FILL_COL, RECEPTOR_COL = range(5)
GLOMERULUS_COLUMNS = ("Show", "Glomerulus", "Label", "Fill", R.RECEPTOR)
NEUROPIL_COLUMNS = ("Show", "Neuropil", "Label", "Fill")

#: The checkbox columns. Each has a checkbox in its header for the whole
#: column (`CheckHeader`), and is as wide as that checkbox and its name.
CHECK_COLUMNS = (VISIBLE_COL, LABEL_COL, FILL_COL)

LABEL_TIP = "Write the name on the slice (Slice view only)"
FILL_TIP = "Fill the outline on the slice (Slice view only)"

#: Cells carry their row's key here (`Row.key`). Once the table can be
#: sorted, the visual row is no longer the row's place and nothing may
#: assume it; nor is a row one compartment, but all its sides.
INDEX_ROLE = Qt.UserRole

#: First entry of the driver-line menu, which applies nothing.
LINE_PROMPT = "Driver line: none"
LINE_TIP = ("Show the glomeruli that a driver line labels, "
            "from lobemap's reference table")

VFB_TEXT = "Open in Virtual Fly Brain"
VFB_NONE = "Select a glomerulus with a Virtual Fly Brain term to open it"

#: The panel's spacing grid, in pixels. The parts of one group -- a search
#: and its driver lines, a table and its count, a value and the next -- sit
#: `GAP` apart; groups sit `GROUP_GAP` apart, a tab's contents `MARGIN`
#: inside its frame, and a label `2 * GAP` before what it labels.
GAP, GROUP_GAP, MARGIN = 4, 12, 8
#: What labels the source menu at the top of each tab.
SOURCE = "Source"


#: Every label of the panel's label column, in either kind of tab.
COLUMN_LABELS = (SOURCE, *R.GLOMERULUS_DETAILS, *R.NEUROPIL_DETAILS)


class ColumnLabel(QLabel):
    """A label of the panel's label column, its text against the right.

    As wide as the widest of `COLUMN_LABELS` in the font and padding it is
    drawn with, so every label of the column ends at one edge, and the menu
    and the values beside them start at one. Measured when laid out, once
    napari's style has set the font, not when built, before it has. No
    indent: napari's style gives a label a frame, and a framed label with
    none set keeps half an x clear of its right edge, which pushed the
    widest label's first letter out of its box.
    """

    def __init__(self, text: str = "") -> None:
        super().__init__(text)
        self.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        self.setIndent(0)

    def sizeHint(self) -> QSize:
        metrics, margins = self.fontMetrics(), self.contentsMargins()
        widest = max(metrics.horizontalAdvance(text) for text in COLUMN_LABELS)
        return QSize(widest + margins.left() + margins.right(), super().sizeHint().height())

    def minimumSizeHint(self) -> QSize:
        return self.sizeHint()


def _word(is_atlas: bool) -> str:
    """What one row is in this kind of tab."""
    return "glomerulus" if is_atlas else "neuropil"


def toggle_tips(is_atlas: bool) -> dict[int, str]:
    """What each header checkbox does, by column, in this kind of tab."""
    one = _word(is_atlas)
    return {
        VISIBLE_COL: f"Show or hide every listed {one}",
        LABEL_COL: (f"Write or clear the name of every listed {one} on the slice. "
                    "Slice view only."),
        FILL_COL: (f"Fill or empty the outline of every listed {one} on the slice. "
                   "Slice view only."),
    }


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


class SteadyLabel(QLabel):
    """A label as tall as the longest of the texts it can show needs.

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

    Each checkbox column's header has a checkbox for the rows listed, those
    the search keeps: ticked when every one is ticked, half when some are.
    A click ticks every listed row, or clears them all when all are ticked
    (`_toggle`).
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
        one = _word(is_atlas)

        # Three groups, top to bottom: finding rows, the table with its
        # count, and the selected row's details.
        layout = QVBoxLayout()
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(GAP)

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
        guard_wheel(self.lines)
        layout.addWidget(self.lines)

        # The details first, though they sit below the table: selecting a
        # row fills them, and the table can select one as it is built.
        details = self._make_details(one)
        layout.addSpacing(GROUP_GAP - GAP)
        layout.addWidget(self._make_table(), stretch=1)
        self.count = QLabel()
        layout.addWidget(self.count)
        layout.addSpacing(GROUP_GAP - GAP)
        layout.addWidget(details)
        self.setLayout(layout)

        self._fill_lines(lines or {})
        self.lines.setVisible(is_atlas and self.lines.count() > 1)
        self.vfb.setVisible(is_atlas)
        self._on_row_selected()
        self._sync_header()

        # The table follows the eye in napari's layer list, and the count
        # follows whichever layer the mode draws.
        surface.listeners.append(self._sync_rows)
        surface.layer.events.visible.connect(self._update_count)
        if contour is not None:
            contour.layer.events.visible.connect(self._update_count)
        self._update_count()

    # -- building --------------------------------------------------------

    def _make_table(self) -> QTableWidget:
        self.table = table = QTableWidget(len(self.rows), len(self.columns))
        #: The header, with a checkbox for each checkbox column.
        self.header = CheckHeader(CHECK_COLUMNS, table)
        table.setHorizontalHeader(self.header)
        table.setHorizontalHeaderLabels(list(self.columns))
        for col, tip in toggle_tips(self.is_atlas).items():
            table.horizontalHeaderItem(col).setToolTip(tip)
        self.header.toggled.connect(self._toggle)
        table.verticalHeader().setVisible(False)
        table.setSelectionBehavior(QAbstractItemView.SelectRows)
        table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        table.setWordWrap(False)
        table.setTextElideMode(Qt.ElideRight)

        # Fits the dock without scrolling sideways: the checkbox columns and
        # the name as wide as their contents, and the last text column takes
        # what is left, shortening a long receptor list rather than widening
        # the table. The tooltip has it in full.
        header = self.header
        header.setMinimumSectionSize(24)
        header.setStretchLastSection(False)
        header.setSectionsClickable(True)
        for col in (*CHECK_COLUMNS, NAME_COL):
            header.setSectionResizeMode(col, QHeaderView.ResizeToContents)
        stretch = RECEPTOR_COL if self.is_atlas else NAME_COL
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
        never cut short (`SteadyLabel`), so selecting another row changes their
        text and nothing else: a value that took one line more used to push
        the table up.
        """
        box = QWidget()
        form = QFormLayout(box)
        form.setContentsMargins(0, 0, 0, 0)
        form.setVerticalSpacing(GAP)
        form.setHorizontalSpacing(2 * GAP)
        # The values take the width there is, whatever their text: on macOS
        # they kept their own, so each row selected moved them. And the form
        # starts at the left: macOS centred it.
        form.setFieldGrowthPolicy(QFormLayout.FieldGrowthPolicy.AllNonFixedFieldsGrow)
        form.setFormAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop)
        self.detail_title = QLabel()
        bold = QFont(self.detail_title.font())
        bold.setBold(True)
        self.detail_title.setFont(bold)
        self._no_selection = f"Select a {one} to see its details"
        form.addRow(self.detail_title)
        #: Field -> the label showing its value for the selected row.
        self.details: dict[str, QLabel] = {}
        for name in self.detail_fields:
            value = SteadyLabel(lambda name=name: [row.details[name] for row in self.rows.values()])
            form.addRow(ColumnLabel(name), value)
            self.details[name] = value
        #: Opens the Virtual Fly Brain term page of the selected glomerulus,
        #: under the values and as wide as its words.
        self.vfb = QPushButton(VFB_TEXT)
        self.vfb.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
        self.vfb.clicked.connect(self._open_vfb)
        form.addRow(ColumnLabel(), self.vfb)
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
        contours (`AtlasSurface.sync`), so a header checkbox and a single
        row's checkbox reach the same code and cannot disagree about the mode.
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
        """Disable the slice-only columns in 3D, where they draw nothing."""
        if three_d == self._three_d:
            return
        self._three_d = three_d
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
        self._sync_header()
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
        held = self._held(item.column())
        self._apply(item.column(), held | set(row.indices) if on
                    else held - set(row.indices))

    def _held(self, column: int) -> set[int]:
        """The compartments `column` has on: shown, named or filled."""
        if column == VISIBLE_COL:
            return set(self.surface.selection)
        if self.contour is None:
            return {i for r in range(self.table.rowCount())
                    if self.table.item(r, column).checkState() == Qt.Checked
                    for i in self.row_at(r).indices}
        return set(self.contour.labels if column == LABEL_COL else self.contour.filled)

    def _apply(self, column: int, indices) -> None:
        """Have exactly these compartments shown, named or filled."""
        if column == VISIBLE_COL:
            self._push(set(indices))
        elif column == LABEL_COL:
            self._set_labels(indices)
        else:
            self._set_fills(indices)

    def listed(self) -> list[R.Row]:
        """The rows the search keeps, in the table's order."""
        return [self.row_at(r) for r in range(self.table.rowCount())
                if not self.table.isRowHidden(r)]

    def _toggle(self, column: int) -> None:
        """Tick `column` on every listed row, every side of each; or clear
        them all if all are ticked. The rows the search hides keep theirs."""
        listed = {i for row in self.listed() for i in row.indices}
        held = self._held(column)
        clear = self.header.state(column) == Qt.Checked
        self._apply(column, held - listed if clear else held | listed)

    def _sync_header(self) -> None:
        """Each header checkbox as its listed rows have theirs. Label and
        Fill cannot act in 3D, where they draw nothing, nor any of them
        while the search lists nothing."""
        rows = [r for r in range(self.table.rowCount()) if not self.table.isRowHidden(r)]
        for column in CHECK_COLUMNS:
            states = {self.table.item(r, column).checkState() for r in rows}
            if states == {Qt.Checked}:
                state = Qt.Checked
            elif states - {Qt.Unchecked}:
                state = Qt.PartiallyChecked
            else:
                state = Qt.Unchecked
            usable = bool(rows) and (column == VISIBLE_COL or not self._three_d)
            self.header.set_state(column, state, usable)

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
        self._sync_header()
        return wanted

    def _set_labels(self, indices) -> None:
        wanted = self._set_checks(LABEL_COL, indices)
        if self.contour is not None:
            self.contour.set_labels(wanted)

    def _set_fills(self, indices) -> None:
        wanted = self._set_checks(FILL_COL, indices)
        if self.contour is not None:
            self.contour.set_fills(wanted)

    def _set_indices(self, indices) -> None:
        """Show exactly these COMPARTMENTS, whatever order the rows are in."""
        n = self.surface.meshset.n_compartments
        self._push({int(i) for i in indices if 0 <= int(i) < n})

    def select(self, indices) -> None:
        """Show exactly these compartments, by mesh index, and tick their rows."""
        self._set_indices(indices)

    def _apply_filter(self, text: str) -> None:
        """Keep the rows the search matches, by `Row.matches` alone: the
        same fields in every tab of a kind, and nothing a column hides."""
        for r in range(self.table.rowCount()):
            row = self.row_at(r)
            self.table.setRowHidden(r, row is None or not row.matches(text))
        self._sync_header()

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
    "COLUMN_LABELS",
    "FILL_COL",
    "GAP",
    "GLOMERULUS_COLUMNS",
    "GROUP_GAP",
    "INDEX_ROLE",
    "LABEL_COL",
    "LINE_PROMPT",
    "MARGIN",
    "NAME_COL",
    "NEUROPIL_COLUMNS",
    "RECEPTOR_COL",
    "SOURCE",
    "VISIBLE_COL",
    "AtlasTab",
    "ColumnLabel",
    "SteadyLabel",
    "toggle_tips",
]
