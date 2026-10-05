"""No table scrolls sideways in the right-hand column at 1440x900, and the
panel sits on the View dock's grid.

The tables used to need 1,041-1,132 px in a 364-484 px dock. Each brain is
opened in a real window laid out at 1440x900, never put on screen, with
every source's table built; then again with the column at the 440 px the
panel asks for. Where the tab titles sit is `test_tab_bars`.
"""

from __future__ import annotations

import itertools

import pytest
from viewer_harness import launched, pump, session, switch_to

pytestmark = pytest.mark.requires_data
pytest.importorskip("napari")

SPACES = ("FAFB14", "JRCFIB2018F", "JRCFIB2022M", "GRABE")


def _lay_out(viewer) -> None:
    from qtpy.QtCore import Qt

    window = viewer.window._qt_window
    window.setAttribute(Qt.WA_DontShowOnScreen, True)
    window.resize(1440, 900)
    window.show()
    pump(100)


def _overflowing(sess) -> dict[str, tuple[int, int]]:
    """Each tab whose table is wider than its view: (table, view) widths."""
    from lobemap.viewer.panel import CHECK_COLUMNS

    out = {}
    for name in sess.parts:
        tab = sess.panel.tab(name)
        assert tab is not None, name
        assert sess.panel.open(name) is tab
        pump(30)
        table = tab.table
        need, have = table.horizontalHeader().length(), table.viewport().width()
        if table.horizontalScrollBar().isVisible() or need > have:
            out[name] = (need, have)
        # Each checkbox column as wide as its header's checkbox and name.
        for col in CHECK_COLUMNS:
            want = tab.header.sectionSizeFromContents(col).width()
            assert table.columnWidth(col) == want, (name, col, table.columnWidth(col), want)
    return out


@pytest.mark.parametrize("ndisplay", ["3", "2"])
def test_no_table_scrolls_sideways_at_1440_by_900(monkeypatch, ndisplay):
    from qtpy.QtCore import Qt

    from lobemap.viewer.panel import WIDTH

    with launched(monkeypatch, "view", SPACES[0], "--ndisplay", ndisplay) as (code, viewer):
        assert code == 0
        _lay_out(viewer)
        window = viewer.window._qt_window
        for space in SPACES:
            if space != SPACES[0]:
                switch_to(viewer, space)
                pump(100)
            sess = session(viewer)
            assert sess.space == space
            # As the window lays it out, whatever width that is.
            assert not _overflowing(sess), (space, sess.dock.width())
            # And at the width the panel asks for.
            window.resizeDocks([sess.dock], [WIDTH], Qt.Horizontal)
            pump(100)
            assert sess.panel.width() == WIDTH, (space, sess.panel.width())
            assert not _overflowing(sess), (space, WIDTH)


def test_the_panel_asks_for_the_column_width(monkeypatch):
    from lobemap.viewer.panel import WIDTH

    with launched(monkeypatch, "view", "GRABE") as (code, viewer):
        assert session(viewer).panel.sizeHint().width() == WIDTH == 440


# -- heights, widths and the spacing grid --------------------------------
#
# The panel is on the View dock's grid (`chrome.GRID`, `chrome.CONTROL_HEIGHT`),
# measured here in its own units, not the panel's constants: a grid unit
# between the parts of a group and between a label and its control, two
# between groups, one at the tab's edges, and every menu, button and the
# search as tall as the dock's controls and as wide as their content.


def _controls(tab, page) -> dict[str, object]:
    """The panel's menus, search and button of one table, where shown."""
    out = {"source menu": page.menu, "sides menu": page.sides_menu, "search": tab.filter}
    if tab.lines.isVisible():
        out["driver line"] = tab.lines
    if tab.vfb.isVisible():
        out["button"] = tab.vfb
    return out


@pytest.mark.parametrize("ndisplay", ["3", "2"])
def test_every_control_is_as_tall_as_the_view_docks_and_as_wide_as_its_content(
        monkeypatch, ndisplay):
    """In every tab of every brain: each menu, the search and the button as
    tall as the View dock's controls, never tight round its text; each menu
    and the button as wide as its content, the search across the column;
    the tabs, the table's rows and its header with room round their text."""
    from qtpy.QtWidgets import QComboBox

    from lobemap.viewer.chrome import CONTROL_HEIGHT, GRID

    with launched(monkeypatch, "view", SPACES[0], "--ndisplay", ndisplay) as (code, viewer):
        assert code == 0
        _lay_out(viewer)
        kinds = set()
        for space in SPACES:
            if space != SPACES[0]:
                switch_to(viewer, space)
                pump(100)
            sess = session(viewer)
            bar = sess.panel.tabBar()
            for i in range(bar.count()):
                assert bar.tabRect(i).height() >= bar.fontMetrics().height() + 2 * GRID, space
            for name in list(sess.parts):
                tab = sess.panel.open(name)
                pump(50)
                page = sess.panel.page_of(name)
                header = tab.table.horizontalHeader()
                for kind, height, metrics in (
                        ("table row", tab.table.rowHeight(0), tab.table.fontMetrics()),
                        ("table header", header.height(), header.fontMetrics())):
                    assert height >= metrics.height() + GRID, (space, name, kind, height)
                for kind, control in _controls(tab, page).items():
                    kinds.add(kind)
                    said = (space, name, kind, control.width(), control.height())
                    assert control.height() == CONTROL_HEIGHT, said
                    assert control.height() >= control.fontMetrics().height() + GRID, said
                    if kind == "search":
                        assert control.width() == page.width() - 2 * GRID, said
                    else:
                        assert control.width() == control.sizeHint().width(), said
                    if isinstance(control, QComboBox):
                        longest = max(control.fontMetrics().horizontalAdvance(control.itemText(i))
                                      for i in range(control.count()))
                        assert longest < control.width() <= longest + 6 * GRID, said
                    elif kind == "button":
                        text = control.fontMetrics().horizontalAdvance(control.text())
                        assert control.width() <= text + 2 * GRID + 2, said
                        # As large enabled, a row with a term selected, as not.
                        row = next(r for r in range(tab.table.rowCount())
                                   if tab.row_at(r).vfb)
                        tab.table.selectRow(row)
                        pump(50)
                        assert control.isEnabled(), said
                        assert (control.width(), control.height()) == said[3:], said
                        tab.table.clearSelection()
        assert kinds == {"source menu", "sides menu", "search", "driver line", "button"}


def _box(widget, page) -> tuple[int, int, int, int]:
    corner = widget.mapTo(page, widget.rect().topLeft())
    return corner.x(), corner.y(), widget.width(), widget.height()


def _below(upper, lower) -> int:
    """The room between the bottom of one box and the top of the next."""
    return lower[1] - (upper[1] + upper[3])


@pytest.mark.parametrize("ndisplay", ["3", "2"])
def test_the_panel_sits_on_the_view_docks_grid(monkeypatch, ndisplay):
    """Measured on the laid-out widgets, in every tab of every brain.

    One edge for every label's text and one, a grid unit after it, for
    every control and value beside a label: the source menu, its citation,
    the Sides menu, the driver line, the values and Open in Virtual Fly
    Brain. A grid unit
    round a tab's contents, between the parts of a group, and two between
    groups. Each label's text in full.
    """
    from lobemap.viewer.chrome import GRID
    from lobemap.viewer.panel_grid import ColumnLabel

    with launched(monkeypatch, "view", SPACES[0], "--ndisplay", ndisplay) as (code, viewer):
        assert code == 0
        _lay_out(viewer)
        edges, ends, boxes = set(), set(), set()
        for space in SPACES:
            if space != SPACES[0]:
                switch_to(viewer, space)
                pump(100)
            sess = session(viewer)
            for name in list(sess.parts):
                tab = sess.panel.open(name)
                pump(50)
                page = sess.panel.page_of(name)
                box = {k: _box(w, page) for k, w in (
                    ("menu", page.menu), ("sides", page.sides_menu),
                    ("citation", page.citation), ("search", tab.filter),
                    ("lines", tab.lines), ("table", tab.table),
                    ("count", tab.count), ("title", tab.detail_title))}
                form = tab.detail_title.parentWidget().layout()
                values = list(tab.details.values())
                fields = [page.menu, page.citation, page.sides_menu, *values]
                if tab.vfb.isVisible():
                    fields.append(tab.vfb)
                if tab.lines.isVisible():
                    fields.append(tab.lines)
                edges |= {_box(f, page)[0] for f in fields}
                head = page.layout().itemAt(0).layout()
                labels = [head.labelForField(page.menu), head.labelForField(page.sides_menu),
                          *(form.labelForField(v) for v in values)]
                assert [label.text() for label in labels[:2]] == ["Source", "Sides"], name
                assert all(isinstance(label, ColumnLabel) for label in labels), name
                if tab.lines.isVisible():
                    labels.append(tab.line_row.layout().labelForField(tab.lines))
                for label in labels:
                    margins = label.contentsMargins()
                    ends.add(_box(label, page)[0] + label.width() - margins.right()
                             - max(label.indent(), 0))
                    boxes.add(_box(label, page)[0] + label.width())
                    # Its text in full, from the left of its box.
                    assert label.indent() == 0, (space, name, label.text())
                    room = label.width() - margins.left() - margins.right()
                    assert label.fontMetrics().horizontalAdvance(label.text()) <= room, (
                        space, name, label.text(), room)
                said = (space, name, box)
                # A grid unit round the tab's contents.
                assert box["menu"][1] == GRID, said
                assert box["search"][0] == box["table"][0] == GRID, said
                # A grid unit within a group, two between groups.
                assert _below(box["menu"], box["citation"]) == GRID, said
                assert _below(box["citation"], box["sides"]) == GRID, said
                assert _below(box["sides"], box["search"]) == 2 * GRID, said
                above = box["search"]
                if tab.lines.isVisible():
                    assert _below(box["search"], box["lines"]) == GRID, said
                    above = box["lines"]
                assert _below(above, box["table"]) == 2 * GRID, said
                assert _below(box["table"], box["count"]) == GRID, said
                assert _below(box["count"], box["title"]) == 2 * GRID, said
                tops = [box["title"], *(_box(v, page) for v in values)]
                assert {_below(a, b) for a, b in itertools.pairwise(tops)} == {GRID}, said
        assert len(edges) == 1 and len(ends) == 1, (edges, ends)
        # As in the View dock: a grid unit from a label's box to its control.
        assert len(boxes) == 1 and edges == {boxes.pop() + GRID}, (edges, boxes)


def _ink_left(image, ratio, x0, y0, x1, y1) -> float | None:
    """The left edge of what is drawn in a box of `image` unlike the box's
    commonest color, in logical pixels from the box's left; None if nothing."""
    from collections import Counter

    box = [(x, image.pixelColor(x, y).getRgb()[:3])
           for y in range(round(y0 * ratio), round(y1 * ratio))
           for x in range(round(x0 * ratio), round(x1 * ratio))]
    fill = Counter(c for _x, c in box).most_common(1)[0][0]
    xs = [x for x, c in box if sum(abs(a - b) for a, b in zip(c, fill, strict=True)) > 90]
    return min(xs) / ratio - x0 if xs else None


def test_every_header_name_starts_where_its_column_does(monkeypatch):
    """As drawn: a text column's name starts where its cells' text does, at
    the left, as a checkbox column's starts after the checkbox at its left.
    A centred Receptor sat far from its values."""
    from lobemap.viewer.panel import NAME_COL, RECEPTOR_COL

    with launched(monkeypatch, "view", "FAFB14") as (code, viewer):
        assert code == 0
        _lay_out(viewer)
        for name in ("benton2025", "fafb_neuropil"):
            tab = session(viewer).panel.open(name)
            pump(100)
            table, header = tab.table, tab.table.horizontalHeader()
            pixmap = table.grab()
            image, ratio = pixmap.toImage(), pixmap.devicePixelRatio()
            top = header.mapTo(table, header.rect().topLeft())
            cells = table.viewport().mapTo(table, table.viewport().rect().topLeft())
            columns = (NAME_COL, RECEPTOR_COL) if tab.is_atlas else (NAME_COL,)
            for col in columns:
                left = top.x() + header.sectionViewportPosition(col)
                width = header.sectionSize(col)
                title = _ink_left(image, ratio, left + 1, top.y() + 2, left + width - 1,
                                  top.y() + header.height() - 2)
                row = table.visualItemRect(table.item(0, col))
                text = _ink_left(image, ratio, left + 1, cells.y() + row.top() + 2,
                                 left + width - 1, cells.y() + row.bottom() - 1)
                assert title is not None and text is not None, (name, col)
                assert abs(title - text) <= 3, (name, col, title, text)
