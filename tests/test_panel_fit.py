"""No tab's table scrolls sideways in the right-hand column at 1440x900.

The tables used to need 1,041-1,132 px in a 364-484 px dock. Each brain is
opened in a real window laid out at 1440x900, never put on screen, with
every tab built; then again with the column at the 440 px the panel asks
for.
"""

from __future__ import annotations

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
        sess.panel.setCurrentWidget(tab)
        pump(30)
        table = tab.table
        need, have = table.horizontalHeader().length(), table.viewport().width()
        if table.horizontalScrollBar().isVisible() or need > have:
            out[name] = (need, have)
        for col in CHECK_COLUMNS:
            assert 36 <= table.columnWidth(col) <= 40, (name, col)
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


def test_every_tab_title_has_room_inside_its_tab(monkeypatch):
    """Measured on the drawn tab bar, in every brain: each title in full,
    clear of its tab's edges, and every tab in view without scrolling."""
    from qtpy.QtWidgets import QToolButton

    with launched(monkeypatch, "view", SPACES[0]) as (code, viewer):
        assert code == 0
        _lay_out(viewer)
        for space in SPACES:
            if space != SPACES[0]:
                switch_to(viewer, space)
                pump(100)
            bar = session(viewer).panel.tabBar()
            assert bar.count() >= 1, space
            # No scroll arrows: the tabs fit the column.
            assert not [b for b in bar.findChildren(QToolButton) if b.isVisible()], space
            assert bar.tabRect(bar.count() - 1).right() < bar.width(), space
            for i in range(bar.count()):
                rect, box = _drawn_text(bar, i)
                title = bar.tabText(i)
                assert box is not None, (space, title)
                left, top, right, bottom = box
                margins = (left - rect.left(), rect.right() + 1 - right,
                           top - rect.top(), rect.bottom() + 1 - bottom)
                assert min(margins[:2]) >= TAB_MARGIN_X, (space, title, margins)
                assert min(margins[2:]) >= TAB_MARGIN_Y, (space, title, margins)
                # In full: as wide as the font draws the whole title.
                full = bar.fontMetrics().horizontalAdvance(title)
                assert right - left >= full - 3, (space, title, right - left, full)
