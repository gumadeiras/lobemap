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
