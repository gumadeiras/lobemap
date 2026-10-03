"""No table scrolls sideways in the right-hand column at 1440x900, and each
tab's title sits in the middle of its tab.

The tables used to need 1,041-1,132 px in a 364-484 px dock. Each brain is
opened in a real window laid out at 1440x900, never put on screen, with
every source's table built; then again with the column at the 440 px the
panel asks for. The titles are measured on the tab bar as drawn.
"""

from __future__ import annotations

import contextlib
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


#: The room, in screen pixels, between a tab's title as drawn and its edges.
TAB_MARGIN_X, TAB_MARGIN_Y = 10, 5


def _drawn_text(bar, index: int):
    """The tab's rect and the box around its title's pixels, both in logical
    pixels: in each row of the tab, the pixels unlike the row's background.

    Read off the tab bar as Qt draws it, so it is where the text is, not
    where a font metric says it should be. The rounded top corners and the
    one-pixel frame are left out.
    """
    from collections import Counter

    pixmap = bar.grab()
    image = pixmap.toImage()
    ratio = pixmap.devicePixelRatio()
    rect = bar.tabRect(index)
    x0, y0 = round(rect.left() * ratio), round(rect.top() * ratio)
    x1, y1 = round((rect.right() + 1) * ratio), round((rect.bottom() + 1) * ratio)
    edge, corner = round(2 * ratio), round(5 * ratio)
    hits = []
    for y in range(y0 + edge, y1 - edge):
        xs = [x for x in range(x0 + edge, x1 - edge)
              if not (y < y0 + corner and (x < x0 + corner or x >= x1 - corner))]
        colors = [image.pixelColor(x, y).getRgb()[:3] for x in xs]
        background = Counter(colors).most_common(1)[0][0]
        hits += [(x, y) for x, c in zip(xs, colors, strict=True)
                 if sum(abs(a - b) for a, b in zip(c, background, strict=True)) > 90]
    if not hits:
        return rect, None
    xs, ys = [h[0] for h in hits], [h[1] for h in hits]
    return rect, (min(xs) / ratio, min(ys) / ratio, (max(xs) + 1) / ratio, (max(ys) + 1) / ratio)


#: How much the room above a title's ink may differ from the room below it,
#: and the room left of it from the room right of it, in screen pixels.
OFF_CENTRE = 1.0


@contextlib.contextmanager
def _style(name: str | None):
    """The whole application drawn in another style, `None` its own, and
    given back after."""
    from qtpy.QtWidgets import QApplication

    own = QApplication.style().name()
    if name is not None:
        QApplication.setStyle(name)
        pump(100)
    try:
        yield
    finally:
        if name is not None:
            QApplication.setStyle(own)
            pump(100)


@pytest.mark.parametrize("style", [None, "Fusion"], ids=["native", "fusion"])
def test_every_tab_title_is_centred_with_room_inside_its_tab(monkeypatch, style):
    """Measured on the drawn tab bar, in every brain, under the platform's
    own style and under Fusion: each title in full, clear of its tab's
    edges and in the middle of it by its ink -- as much room above it as
    below, and on its left as on its right -- and every tab in view without
    scrolling."""
    from qtpy.QtWidgets import QApplication, QToolButton

    with launched(monkeypatch, "view", SPACES[0]) as (code, viewer), _style(style):
        assert code == 0
        if style is None:
            assert QApplication.style().name() == "macos"
        _lay_out(viewer)
        for space in SPACES:
            if space != SPACES[0]:
                switch_to(viewer, space)
                pump(100)
            bar = session(viewer).panel.tabBar()
            assert [bar.tabText(i) for i in range(bar.count())] == (
                ["Glomeruli"] if space == "GRABE" else ["Glomeruli", "Neuropils"])
            # No scroll arrows: the tabs fit the column.
            assert not [b for b in bar.findChildren(QToolButton) if b.isVisible()], space
            assert bar.tabRect(bar.count() - 1).right() < bar.width(), space
            for current in range(bar.count()):
                bar.setCurrentIndex(current)
                pump(50)
                for i in range(bar.count()):
                    rect, box = _drawn_text(bar, i)
                    title = bar.tabText(i)
                    assert box is not None, (space, title)
                    left, top, right, bottom = box
                    margins = (left - rect.left(), rect.right() + 1 - right,
                               top - rect.top(), rect.bottom() + 1 - bottom)
                    assert min(margins[:2]) >= TAB_MARGIN_X, (space, title, margins)
                    assert min(margins[2:]) >= TAB_MARGIN_Y, (space, title, margins)
                    assert abs(margins[0] - margins[1]) <= OFF_CENTRE, (space, title, margins)
                    assert abs(margins[2] - margins[3]) <= OFF_CENTRE, (space, title, margins)
                    # In full: as wide as the font draws the whole title.
                    full = bar.fontMetrics().horizontalAdvance(title)
                    assert right - left >= full - 3, (space, title, right - left, full)
            bar.setCurrentIndex(0)


def test_the_tab_bar_draws_what_qt_draws_but_for_where_each_title_sits(monkeypatch):
    """With the titles left where Qt puts them, the panel's tab bar and a
    plain one draw the same pixels, in the window's style: the tabs, their
    frame and the base under them are the style's, and only the titles move."""
    from qtpy.QtCore import QPointF
    from qtpy.QtWidgets import QTabBar, QTabWidget, QWidget

    from lobemap.viewer.panel import TAB_PADDING, TabBar

    with launched(monkeypatch, "view", "FAFB14") as (code, viewer):
        assert code == 0
        _lay_out(viewer)
        monkeypatch.setattr(TabBar, "ink_offset", lambda self, text: QPointF(0.0, 0.0))
        images = []
        for kind in (QTabBar, TabBar):
            tabs = QTabWidget()
            tabs.setTabBar(kind())
            tabs.tabBar().setStyleSheet(TAB_PADDING)
            for title in ("Glomeruli", "Neuropils"):
                tabs.addTab(QWidget(), title)
            viewer.window.add_dock_widget(tabs, area="right")
            pump(100)
            images.append(tabs.tabBar().grab().toImage())
        assert images[0].size() == images[1].size()
        assert images[0] == images[1]


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
