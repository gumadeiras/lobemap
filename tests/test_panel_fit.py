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


# -- heights and the spacing grid -----------------------------------------


def _rooms(panel, sess) -> dict[str, tuple[int, int]]:
    """Each kind of control's least (height, its text's line height), over
    every table now: the tabs, the table's rows and header, the search, the
    menus and the buttons."""
    from qtpy.QtWidgets import QPushButton

    least: dict[str, tuple[int, int]] = {}

    def note(kind: str, height: int, metrics) -> None:
        room = (height, metrics.height())
        if kind not in least or room[0] - room[1] < least[kind][0] - least[kind][1]:
            least[kind] = room

    bar = panel.tabBar()
    for i in range(bar.count()):
        note("tab", bar.tabRect(i).height(), bar.fontMetrics())
    for name in list(sess.parts):
        tab = panel.open(name)
        pump(50)
        table = tab.table
        note("table row", table.rowHeight(0), table.fontMetrics())
        note("table header", table.horizontalHeader().height(),
             table.horizontalHeader().fontMetrics())
        note("search", tab.filter.height(), tab.filter.fontMetrics())
        if tab.lines.isVisible():
            note("driver line", tab.lines.height(), tab.lines.fontMetrics())
        for button in tab.findChildren(QPushButton):
            if button.isVisible():
                note("button", button.height(), button.fontMetrics())
        menu = panel.page_of(name).menu
        note("source menu", menu.height(), menu.fontMetrics())
    return least


@pytest.mark.parametrize("ndisplay", ["3", "2"])
def test_every_control_keeps_the_grids_room_around_its_text(monkeypatch, ndisplay):
    """Sized to its words across, never squeezed down to them: every
    control's height leaves at least `GAP` above and below its line of
    text, in every tab of every brain."""
    from lobemap.viewer.panel_tab import GAP

    with launched(monkeypatch, "view", SPACES[0], "--ndisplay", ndisplay) as (code, viewer):
        assert code == 0
        _lay_out(viewer)
        for space in SPACES:
            if space != SPACES[0]:
                switch_to(viewer, space)
                pump(100)
            rooms = _rooms(session(viewer).panel, session(viewer))
            assert {"tab", "table row", "table header", "search", "button",
                    "source menu"} <= set(rooms), rooms
            tight = {kind: room for kind, room in rooms.items()
                     if room[0] < room[1] + 2 * GAP}
            assert not tight, (space, tight)


def _box(widget, page) -> tuple[int, int, int, int]:
    corner = widget.mapTo(page, widget.rect().topLeft())
    return corner.x(), corner.y(), widget.width(), widget.height()


@pytest.mark.parametrize("ndisplay", ["3", "2"])
def test_the_panel_sits_on_one_grid(monkeypatch, ndisplay):
    """Measured on the laid-out widgets, in every tab of every brain.

    One edge for every label's text and one for every control beside a
    label, the source menu, its citation, the values and Open in Virtual
    Fly Brain; `MARGIN` around a tab's contents; `GAP` between the parts of
    a group and `GROUP_GAP` between groups; and each label's text in full.
    """
    from lobemap.viewer.panel_tab import GAP, GROUP_GAP, MARGIN

    with launched(monkeypatch, "view", SPACES[0], "--ndisplay", ndisplay) as (code, viewer):
        assert code == 0
        _lay_out(viewer)
        edges, ends = set(), set()
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
                    ("menu", page.menu), ("citation", page.citation),
                    ("search", tab.filter), ("lines", tab.lines), ("table", tab.table),
                    ("count", tab.count), ("title", tab.detail_title))}
                form = tab.detail_title.parentWidget().layout()
                values = list(tab.details.values())
                # One edge for the controls, one for the end of the labels.
                edges |= {box["menu"][0], box["citation"][0],
                          *(_box(v, page)[0] for v in values)}
                if tab.vfb.isVisible():
                    edges.add(_box(tab.vfb, page)[0])
                labels = [page.layout().itemAt(0).layout().labelForField(page.menu),
                          *(form.labelForField(v) for v in values)]
                for label in labels:
                    margins = label.contentsMargins()
                    ends.add(_box(label, page)[0] + label.width() - margins.right()
                             - max(label.indent(), 0))
                    # Its text in full, from the left of its box.
                    assert label.indent() == 0, (space, name, label.text())
                    room = label.width() - margins.left() - margins.right()
                    assert label.fontMetrics().horizontalAdvance(label.text()) <= room, (
                        space, name, label.text(), room)
                # The margin, and the gaps within and between groups.
                assert box["menu"][1] == MARGIN, (space, name, box["menu"])
                assert box["search"][0] == MARGIN, (space, name, box["search"])
                assert page.width() - sum(box["menu"][0::2]) == MARGIN, (space, name)
                assert box["citation"][1] - sum(box["menu"][1::2]) == GAP
                assert box["search"][1] - sum(box["citation"][1::2]) == GROUP_GAP
                above = box["lines"] if tab.lines.isVisible() else box["search"]
                if tab.lines.isVisible():
                    assert box["lines"][1] - sum(box["search"][1::2]) == GAP
                assert box["table"][1] - sum(above[1::2]) == GROUP_GAP, (space, name)
                assert box["table"][0] == MARGIN, (space, name, box["table"])
                assert box["count"][1] - sum(box["table"][1::2]) == GAP
                assert box["title"][1] - sum(box["count"][1::2]) == GROUP_GAP
                tops = [box["title"], *(_box(v, page) for v in values)]
                assert {b[1] - sum(a[1::2]) for a, b in itertools.pairwise(tops)} == {GAP}
        assert len(edges) == 1, edges
        assert len(ends) == 1, ends
