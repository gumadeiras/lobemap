"""Right-dock compartment table.

A view bound to one atlas layer, joined to the canonical nomenclature, never a
union across atlases -- that is what keeps it usable as atlases accumulate
(design section 7).

Visibility is per-compartment ACROSS atlases (design section 1), so each atlas
gets its own tab driving its own layer, and nothing assumes a single active
atlas.

The table is for bulk selection. It complements click-to-identify rather than
replacing it: picking in the canvas selects the row here, and vice versa.

A checked row is a drawn glomerulus, in either mode: the rows are the
selection, and the selection is what `AtlasSurface.sync` draws.
"""

from __future__ import annotations

import re

from qtpy.QtCore import Qt
from qtpy.QtGui import QColor
from qtpy.QtWidgets import (
    QAbstractItemView,
    QGridLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from ..core import reference

#: Column 0 toggles the mesh; `label` writes the name on the slice and
#: `fill` draws the 2D contour filled. Both are per glomerulus because
#: several atlases in one scene would otherwise act once per atlas.
#:
#: The annotation columns come from `registry/reference/`, joined on the
#: canonical name; see `core.reference`.
REF_COLUMNS = tuple(reference.FIELDS)
COLUMNS = ("", "glomerulus", "canonical", "side", "label", "fill", *REF_COLUMNS)
VISIBLE_COL = 0
NAME_COL = 1
CANONICAL_COL = 2
LABEL_COL = 4
FILL_COL = 5
REF_COL0 = 6

#: Columns that only mean anything for an ATLAS. A neuropil layer has no
#: compartments behind it, so its canonical name, side and annotation are
#: all blank -- seven empty columns claiming the table is about glomeruli
#: when it is listing whole neuropils.
ATLAS_ONLY = (CANONICAL_COL, 3, *range(REF_COL0, 6 + len(REF_COLUMNS)))

#: Rows carry their compartment index here. Once the table can be sorted,
#: the visual row is no longer the compartment id and nothing may assume it.
INDEX_ROLE = Qt.UserRole

#: Canonical names that are not just the published name. Red because these
#: are the rows where the atlas and its space disagree about what a
#: glomerulus is called -- a rename, a merge or a split -- and reading the
#: table without noticing them is how the two get conflated.
DISAGREE_COLOR = "#ff6b6b"


def wants_canonical(compartments) -> bool:
    """Whether this atlas needs the canonical column at all.

    For most atlases it repeats the glomerulus name on every row and says
    nothing. It earns its place only where the atlas disagrees with its
    space's vocabulary somewhere -- a rename, a merge or a split.
    """
    return any(
        _disagrees(c.published_name, c.canonical) for c in compartments
    )


def _disagrees(published: str, canonical) -> bool:
    """True when the canonical name is not simply the published one.

    Compared on the BARE glomerulus: `AL-DA1(R)` and `DA1` are the same
    glomerulus written two ways, and marking every hemibrain row red would
    say nothing. An empty canonical is a gap, not a disagreement.
    """
    from ..core.names import parse_roi

    if not canonical:
        return False
    return tuple(canonical) != (parse_roi(published)[0],)


def _natural_key(text: str):
    """DA10 after DA9, not between DA1 and DA2."""
    return [
        int(part) if part.isdigit() else part.lower()
        for part in re.split(r"(\d+)", text)
    ]


class _Cell(QTableWidgetItem):
    """A cell that sorts naturally rather than by raw code point."""

    def __lt__(self, other):
        if isinstance(other, QTableWidgetItem):
            return _natural_key(self.text()) < _natural_key(other.text())
        return super().__lt__(other)


#: Bulk buttons that act on the 2D slice only, and are disabled in 3D.
TWO_D_ONLY = ("Label all", "Label none", "Fill all", "Fill none")


def _button_tips(title: str) -> dict[str, str]:
    """What each bulk button does, and to which rows: this tab's only."""
    return {
        "Filtered": f"Show exactly the rows of {title} that the filter leaves",
        "Invert": f"Show the unchecked rows of {title} instead of the checked ones",
        "Show all": f"Show every row of {title}",
        "Show none": f"Hide every row of {title}",
        "Label all": f"Write the name of every shown row of {title} on the slice (2D only)",
        "Label none": f"Remove every slice label of {title} (2D only)",
        "Fill all": f"Fill the slice contour of every shown row of {title} (2D only)",
        "Fill none": f"Draw every slice contour of {title} as an outline (2D only)",
    }


class AtlasTab(QWidget):
    def __init__(self, surface, compartments=None, contour=None,
                 annotation=None, is_atlas: bool = True) -> None:
        super().__init__()
        self.surface = surface
        self.contour = contour
        #: False for a neuropil layer: the same widget, minus the columns
        #: that describe a glomerulus.
        self.is_atlas = is_atlas
        self.compartments = list(compartments or [])
        #: Whether this atlas needs the canonical column at all.
        self.show_canonical = wants_canonical(self.compartments)
        #: Glomerulus name -> annotation, from `core.reference`. Empty when
        #: the reference table is absent, which only empties those columns.
        self.reference = annotation or {}
        self._updating = False
        self._three_d: bool | None = None

        layout = QVBoxLayout()
        layout.setContentsMargins(4, 4, 4, 4)

        self.filter = QLineEdit()
        # It has always searched every text column, not just those three.
        self.filter.setPlaceholderText(
            "filter: name, canonical, side, receptor, sensillum, organ..."
        )
        self.filter.textChanged.connect(self._apply_filter)
        layout.addWidget(self.filter)

        # A grid rather than two rows of boxes, so each pair lines up in
        # its own column: the button below a given one is always its
        # opposite. `Show` names what the checkbox in column 0 does, which
        # `All`/`None` left to be guessed now that `Label` and `Fill` have
        # their own pairs. The tooltips say which rows each one acts on.
        buttons = QGridLayout()
        buttons.setSpacing(4)
        tips = _button_tips(surface.name)
        self._two_d_buttons: list[QPushButton] = []
        for col, (top, bottom) in enumerate((
            (("Filtered", self._filtered_only), ("Invert", self._invert)),
            (("Show all", self._all), ("Show none", self._none)),
            (("Label all", self._labels_for_shown),
             ("Label none", self._no_labels)),
            (("Fill all", self._fill_for_shown), ("Fill none", self._no_fill)),
        )):
            for row, (label, slot) in enumerate((top, bottom)):
                button = QPushButton(label)
                button.setToolTip(tips[label])
                button.clicked.connect(slot)
                buttons.addWidget(button, row, col)
                if label in TWO_D_ONLY:
                    self._two_d_buttons.append(button)
            buttons.setColumnStretch(col, 1)
        layout.addLayout(buttons)

        self.table = QTableWidget(surface.meshset.n_compartments, len(COLUMNS))
        labels = list(COLUMNS)
        if not is_atlas:
            labels[NAME_COL] = "neuropil"
        self.table.setHorizontalHeaderLabels(labels)
        self.table.verticalHeader().setVisible(False)
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        header = self.table.horizontalHeader()
        # Every column just wide enough for its widest cell. The annotation
        # columns used to be a fixed 150px, which truncated the long
        # receptor lists and padded the short ones.
        for col in range(len(COLUMNS)):
            header.setSectionResizeMode(col, QHeaderView.ResizeToContents)
        header.setSectionsClickable(True)
        header.setStretchLastSection(False)
        if not is_atlas:
            for col in ATLAS_ONLY:
                self.table.setColumnHidden(col, True)
        if not self.show_canonical:
            self.table.setColumnHidden(CANONICAL_COL, True)

        by_index = {c.local_id: c for c in self.compartments}
        # Sorting must be off while the rows are built, or Qt reorders them
        # underneath the loop and the cells land on the wrong rows.
        self.table.setSortingEnabled(False)
        for row, name in enumerate(surface.meshset.names):
            comp = by_index.get(row)
            check = QTableWidgetItem()
            check.setFlags(check.flags() | Qt.ItemIsUserCheckable)
            check.setCheckState(
                Qt.Checked if row in surface.selection else Qt.Unchecked
            )
            check.setData(INDEX_ROLE, row)
            self.table.setItem(row, VISIBLE_COL, check)

            label = _Cell(name)
            rgba = surface.colors[row]
            label.setForeground(
                QColor.fromRgbF(float(rgba[0]), float(rgba[1]), float(rgba[2]))
            )
            label.setData(INDEX_ROLE, row)
            self.table.setItem(row, NAME_COL, label)
            canonical = ", ".join(comp.canonical) if comp else ""
            canon_cell = _Cell(canonical)
            if comp and _disagrees(name, comp.canonical):
                canon_cell.setForeground(QColor(DISAGREE_COLOR))
                canon_cell.setToolTip(
                    f"{name} is recorded as {canonical} "
                    f"({comp.relation}) in this space's vocabulary"
                )
            self.table.setItem(row, CANONICAL_COL, canon_cell)
            self.table.setItem(row, 3, _Cell((comp.side or "") if comp else ""))

            tips = {
                LABEL_COL: "write this glomerulus's name on the slice (2D)",
                FILL_COL: "draw this glomerulus's 2D contour filled",
            }
            for col, tip in tips.items():
                box = QTableWidgetItem()
                box.setFlags(box.flags() | Qt.ItemIsUserCheckable)
                box.setCheckState(Qt.Unchecked)
                box.setData(INDEX_ROLE, row)
                box.setToolTip(tip)
                self.table.setItem(row, col, box)

            # Annotation, joined on the canonical name rather than the
            # published one: that is the name the reference table uses, and
            # it is what makes the same row match across atlases.
            props = self._reference_for(comp, name) if is_atlas else {}
            for i, key in enumerate(REF_COLUMNS):
                self.table.setItem(row, REF_COL0 + i, _Cell(props.get(key, "")))

        # Alphabetical on the glomerulus by default, and clickable headers
        # from here on: the table is long enough that scanning it unsorted
        # is the wrong default.
        self.table.setSortingEnabled(True)
        self.table.sortItems(NAME_COL, Qt.AscendingOrder)
        self.table.itemChanged.connect(self._on_item_changed)
        layout.addWidget(self.table, stretch=1)

        self.count = QLabel()
        layout.addWidget(self.count)
        self.setLayout(layout)

        # The table follows the eye in napari's layer list, and the count
        # follows whichever layer the mode draws.
        surface.listeners.append(self._sync_rows)
        surface.layer.events.visible.connect(self._update_count)
        if contour is not None:
            contour.layer.events.visible.connect(self._update_count)
        self._update_count()

    # -- helpers ---------------------------------------------------------
    #
    # The visual row and the compartment index are different numbers once
    # the table can be sorted. Every row carries its index in INDEX_ROLE;
    # nothing below may use a row number as a compartment id.

    def _reference_for(self, comp, published: str) -> dict:
        names = list(comp.canonical) if comp and comp.canonical else []
        names.append(published)
        for n in names:
            hit = self.reference.get(n) or self.reference.get(n.lower())
            if hit:
                return hit
        return {}

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

    def _row_text(self, row: int) -> str:
        """Everything on this row that is text.

        Every column except the three checkboxes, which carry no text and
        so contribute nothing -- there is no sense in filtering on `fill`.
        """
        return " ".join(
            (self.table.item(row, c).text() if self.table.item(row, c) else "")
            for c in range(1, len(COLUMNS))
            if c not in (LABEL_COL, FILL_COL)
        ).lower()

    def _push(self, selection: set[int]) -> None:
        """Show exactly these compartments, in whichever layer the mode draws.

        The surface draws its own selection in the mesh or, paired, in its
        contours (`AtlasSurface.sync`), so a bulk button and a single row's
        checkbox reach the same code and cannot disagree about the mode.
        """
        self.surface.set_selection(selection)
        self._update_count()

    def _sync_rows(self) -> None:
        """Check exactly the selected rows, after the eye changed them."""
        self._set_checks(VISIBLE_COL, self.surface.selection)
        self._update_count()

    def _update_count(self, event=None) -> None:
        """How many rows are drawn, which is the checked ones or none.

        None only while napari's eye has the drawing layer off in a way the
        surface did not take as a selection change -- the wrong mode's layer
        switched on, say -- so the count never claims what is not drawn.
        """
        n = self.table.rowCount()
        shown = len(self.surface.selection)
        if shown and not self.surface.mode_layer().visible:
            self.count.setText(f"0 / {n} shown ({shown} checked, layer hidden)")
        else:
            self.count.setText(f"{shown} / {n} shown")

    def set_mode(self, three_d: bool) -> None:
        """Disable the 2D-only controls in 3D, where they draw nothing."""
        if three_d == self._three_d:
            return
        self._three_d = three_d
        for button in self._two_d_buttons:
            button.setEnabled(not three_d)
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
        self._update_count()

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
        """Label whatever is currently visible -- the useful bulk action."""
        self._set_labels(set(self.surface.selection))

    def _no_labels(self) -> None:
        self._set_labels(set())

    def _fill_for_shown(self) -> None:
        """Fill whatever is currently visible, matching `Label all`."""
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

    def _all_indices(self) -> set[int]:
        return {i for i in (self._index_of(r)
                            for r in range(self.table.rowCount()))
                if i is not None}

    def _all(self) -> None:
        self._set_indices(self._all_indices())

    def _none(self) -> None:
        self._set_indices(set())

    def _filtered_only(self) -> None:
        """Check exactly the compartments whose rows pass the filter."""
        self._set_indices({
            self._index_of(r) for r in range(self.table.rowCount())
            if not self.table.isRowHidden(r) and self._index_of(r) is not None
        })

    def _invert(self) -> None:
        self._set_indices(self._all_indices() - set(self.surface.selection))

    def _apply_filter(self, text: str) -> None:
        needle = text.strip().lower()
        for row in range(self.table.rowCount()):
            self.table.setRowHidden(row, bool(needle) and needle not in self._row_text(row))

    # -- picking ---------------------------------------------------------

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


class CompartmentPanel(QTabWidget):
    def __init__(self, viewer, surfaces: dict, registry=None, contours=None,
                 space: str | None = None) -> None:
        super().__init__()
        self.viewer = viewer
        self.tabs: dict[str, AtlasTab] = {}
        contours = contours or {}
        # Read once for the whole panel: every tab joins against the same
        # table, and it is a 62-row csv.
        annotation = reference.load(registry.root) if registry else {}
        # Atlases first, reference geometry last. `build_scene` adds the
        # neuropil and brain shells before the atlases so they sit UNDER
        # the glomeruli, but that is a stacking order and this is a reading
        # order: the tabs with glomeruli in them come first. Sorting on a
        # bool is stable, so each group keeps its scene order.
        def is_reference(name: str) -> bool:
            return registry is None or name not in registry.atlases

        for name in sorted(surfaces, key=is_reference):
            surface = surfaces[name]
            atlas = registry.atlases.get(name) if registry else None
            tab = AtlasTab(
                surface,
                compartments=atlas.compartments if atlas else None,
                contour=contours.get(name),
                annotation=annotation,
                is_atlas=atlas is not None,
            )
            self.tabs[name] = tab
            self.addTab(tab, name[:20])
        self._open_default_tab(registry, space)
        if viewer is not None:
            self.set_mode(viewer.dims.ndisplay == 3)

    def set_mode(self, three_d: bool) -> None:
        for tab in self.tabs.values():
            tab.set_mode(three_d)

    def _open_default_tab(self, registry, space: str | None) -> None:
        """Open on an atlas, never on the reference geometry.

        Neuropil and brain shells are added to the scene first so they sit
        underneath the glomeruli, which also made one of them tab 0. That
        tab lists whole neuropils -- no canonical name, no side, no
        annotation -- so the panel opened on the one tab that says nothing
        about glomeruli.

        Which atlas is the space's own choice, `primary_atlas`, so the open
        tab matches the atlas `show_primary_atlas` leaves drawn. It matters
        only for JRCFIB2018F, the one space carrying several: it opens on
        the neuPrint parcellation the Schlegel pair are compared against.
        """
        atlases = [name for name, tab in self.tabs.items() if tab.is_atlas]
        if not atlases:
            return              # a space with reference geometry only
        target = atlases[0]
        if registry is not None:
            # Derivable from any atlas tab, so a caller that did not name
            # the space still gets the declared choice rather than
            # whichever atlas happens to be built first.
            space = space or registry.atlases[target].native_space
            primary = registry.primary_atlas(space)
            if primary is not None and primary.id in self.tabs:
                target = primary.id
        self.setCurrentWidget(self.tabs[target])

    def highlight(self, layer_name: str, index: int) -> None:
        tab = self.tabs.get(layer_name)
        if tab is None:
            return
        self.setCurrentWidget(tab)
        tab.highlight(index)
