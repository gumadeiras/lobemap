"""The driver-line filter and the VFB link, restored from `main`.

Both driven through their widgets and checked against what is drawn.
"""

from __future__ import annotations

import pytest
from viewer_harness import (
    REGISTRY,
    assert_rows_match_drawing,
    checked,
    clear_all,
    click,
    drawn,
    launched,
    pump,
    session,
)

pytestmark = pytest.mark.requires_data
pytest.importorskip("napari")


def _buttons(tab):
    from qtpy.QtWidgets import QPushButton

    return {b.text(): b for b in tab.findChildren(QPushButton)}


# -- driver lines -----------------------------------------------------------


def _members(tab, line: str) -> set[int]:
    """Compartments whose reference row -- by canonical name, then by the
    published one -- lists `line`, computed here from the table itself."""
    from lobemap.core import reference

    lines = reference.lines(REGISTRY)[line]
    table = reference.load(REGISTRY)
    out = set()
    for comp in tab.compartments:
        for key in [*comp.canonical, comp.published_name]:
            row = table.get(key) or table.get(key.lower())
            if row:
                if row[reference.KEY] in lines:
                    out.add(comp.local_id)
                break
    return out


@pytest.mark.parametrize(("space", "atlas"), [
    ("FAFB14", "benton2025"),
    ("GRABE", "grabe2015"),               # both lobes: two sides per row
    ("JRCFIB2018F", "neuprint_hemibrain"),
])
@pytest.mark.parametrize("line", ["Orco-GAL4 & GH146-GAL4", "Ir25a-T2A-QF2"])
@pytest.mark.parametrize("ndisplay", ["3", "2"])
def test_a_driver_line_shows_the_glomeruli_it_labels(monkeypatch, space, atlas,
                                                      line, ndisplay):
    with launched(monkeypatch, "view", space, "--ndisplay", ndisplay) as (
        code, viewer,
    ):
        sess = session(viewer)
        tab = sess.panel.tabs[atlas]
        from lobemap.core.names import parse_roi

        members = _members(tab, line)
        assert members, f"{line} labels nothing in {atlas}"
        # The menu counts glomeruli, and shows every side of each.
        glomeruli = {parse_roi(tab.surface.meshset.names[i])[0] for i in members}
        menu = tab.lines
        index = next(i for i in range(menu.count())
                     if menu.itemText(i).startswith(line + " ("))
        assert menu.itemText(index) == f"{line} ({len(glomeruli)})"
        menu.setCurrentIndex(index)
        pump(300)
        assert checked(tab) == members
        assert tab.count.text() == f"{len(glomeruli)} of {tab.table.rowCount()} shown"
        if ndisplay == "3":
            assert drawn(tab.surface) == members
        assert_rows_match_drawing(sess)

        # Changing a row by hand means the line no longer names what is shown.
        from qtpy.QtCore import Qt

        from lobemap.viewer.panel import VISIBLE_COL

        row = tab.table_row(next(iter(members)))
        tab.table.item(row, VISIBLE_COL).setCheckState(Qt.Unchecked)
        assert menu.currentIndex() == -1
        assert menu.currentText() == "" and menu.placeholderText() == "None"


def test_the_intersection_preset_is_offered_where_it_applies(monkeypatch):
    with launched(monkeypatch, "view", "FAFB14") as (code, viewer):
        menu = session(viewer).panel.tabs["benton2025"].lines
        texts = [menu.itemText(i) for i in range(menu.count())]
        # Lines only: no item that does nothing.
        assert all(t.endswith(")") for t in texts), texts
        assert any(t.startswith("Orco-GAL4 & GH146-GAL4 (") for t in texts), texts
        # A neuropil tab has no glomeruli to filter, so no menu.
        assert not session(viewer).panel.tabs["fafb_neuropil"].lines.isVisibleTo(
            session(viewer).panel.tabs["fafb_neuropil"]
        )


def _lay_out(viewer) -> None:
    from qtpy.QtCore import Qt

    window = viewer.window._qt_window
    window.setAttribute(Qt.WidgetAttribute.WA_DontShowOnScreen, True)
    window.resize(1440, 900)
    window.show()
    pump(300)


def test_the_driver_line_keeps_its_label_and_offers_lines_only(monkeypatch):
    """"Driver line" stays beside the menu, on the label column, with a line
    chosen or none; the menu lists the lines alone, and says None while no
    line is what is shown, as when it opens. Under Sides set to Right, a
    line shows its right glomeruli and leaves the left as they were."""
    from lobemap.viewer.panel_tab import LINE_NONE

    with launched(monkeypatch, "view", "GRABE") as (code, viewer):
        assert code == 0
        _lay_out(viewer)
        sess = session(viewer)
        tab, page = sess.panel.tabs["grabe2015"], sess.panel.page_of("grabe2015")
        menu = tab.lines
        label = tab.line_row.layout().labelForField(menu)

        def beside() -> None:
            assert label.isVisible() and label.text() == "Driver line"
            assert label.x() + label.width() + tab.line_row.layout().horizontalSpacing() == menu.x()
            assert abs(label.geometry().center().y() - menu.geometry().center().y()) <= 1

        assert (menu.currentIndex(), menu.currentText()) == (-1, "")
        assert menu.placeholderText() == LINE_NONE
        beside()
        texts = [menu.itemText(i) for i in range(menu.count())]
        assert texts and all(t.endswith(")") and t != LINE_NONE for t in texts), texts
        index = next(i for i, t in enumerate(texts) if t.startswith("Orco-GAL4 ("))
        members = set(menu.itemData(index))
        menu.setCurrentIndex(index)
        pump(300)
        assert menu.currentText() == texts[index]
        beside()
        assert drawn(tab.surface) == members

        # Sides: Right, then the line again: the right members, and every
        # left side as before.
        tab.select(range(tab.surface.meshset.n_compartments))
        page.sides_menu.setCurrentIndex(page.sides_menu.findText("Right"))
        pump(300)
        assert menu.currentIndex() == -1
        menu.setCurrentIndex(index)
        pump(300)
        left = {side.index for row in tab.rows.values() for side in row.sides
                if side.where == "Left"}
        assert drawn(tab.surface) == left | (members - left)
        assert menu.currentText() == texts[index]


def test_the_count_says_what_the_search_lists_and_what_is_shown(monkeypatch):
    """With every row listed the count says how many are shown; while a
    search hides rows it says how many it lists as well, and fits the
    column."""
    with launched(monkeypatch, "view", "FAFB14") as (code, viewer):
        assert code == 0
        _lay_out(viewer)
        tab = session(viewer).panel.tabs["benton2025"]
        n = tab.table.rowCount()
        assert tab.count.text() == f"{n} of {n} shown"
        tab.filter.setText("DA")
        pump(100)
        listed = len(tab.listed())
        assert 0 < listed < n
        assert tab.count.text() == f"{listed} listed · {n} of {n} shown"
        clear_all(tab)
        assert tab.count.text() == f"{listed} listed · {n - listed} of {n} shown"
        assert tab.count.sizeHint().width() <= tab.count.width() <= tab.width()
        tab.filter.setText("")
        pump(100)
        assert tab.count.text() == f"{n - listed} of {n} shown"


# -- VFB --------------------------------------------------------------------


def test_the_vfb_button_opens_the_selected_glomerulus(monkeypatch):
    import webbrowser

    opened = []
    monkeypatch.setattr(webbrowser, "open", lambda url, *a, **k: opened.append(url))
    with launched(monkeypatch, "view", "JRCFIB2018F") as (code, viewer):
        tab = session(viewer).panel.tabs["neuprint_hemibrain"]
        vfb = _buttons(tab)["Open in Virtual Fly Brain"]
        assert not vfb.isEnabled(), "nothing is selected yet"
        assert vfb.toolTip() == (
            "Select a glomerulus with a Virtual Fly Brain term to open it"
        )
        index = tab.surface.meshset.names.index("DA1(R)")
        tab.table.selectRow(tab.table_row(index))
        assert vfb.isEnabled()
        assert vfb.toolTip() == "Open the Virtual Fly Brain page for DA1"
        vfb.click()
        assert opened == [(
            "https://www.virtualflybrain.org/term/"
            "antennal-lobe-glomerulus-da1-fbbt_00003932/"
        )]


def test_clicking_a_glomerulus_points_the_vfb_button_at_it(monkeypatch):
    from qtpy.QtCore import Qt

    from lobemap.viewer.panel import VISIBLE_COL

    with launched(monkeypatch, "view", "FAFB14") as (code, viewer):
        tab = session(viewer).panel.tabs["benton2025"]
        index = tab.surface.meshset.names.index("DA1")
        clear_all(tab)
        tab.table.item(tab.table_row(index), VISIBLE_COL).setCheckState(Qt.Checked)
        pump(300)
        assert click(viewer, tab.surface.meshset.centroid(index)) == "DA1 (left) — Benton 2025"
        vfb = _buttons(tab)["Open in Virtual Fly Brain"]
        assert vfb.isEnabled()
        assert vfb.toolTip() == "Open the Virtual Fly Brain page for DA1"
        assert tab.detail_title.text() == "DA1"
        assert tab.details["Sides"].text() == "Left"
