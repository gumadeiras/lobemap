"""The driver-line filter and the VFB link, restored from `main`.

Both driven through their widgets and checked against what is drawn.
"""

from __future__ import annotations

import pytest
from viewer_harness import (
    REGISTRY,
    assert_rows_match_drawing,
    checked,
    drawn,
    hover,
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
    ("GRABE", "grabe2015"),               # both lobes: two rows per glomerulus
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
        members = _members(tab, line)
        assert members, f"{line} labels nothing in {atlas}"
        menu = tab.lines
        index = next(i for i in range(menu.count())
                     if menu.itemText(i).startswith(line + " ("))
        assert menu.itemText(index) == f"{line} ({len(members)})"
        menu.setCurrentIndex(index)
        pump(300)
        assert checked(tab) == members
        assert tab.count.text() == f"{len(members)} / {tab.table.rowCount()} shown"
        if ndisplay == "3":
            assert drawn(tab.surface) == members
        assert_rows_match_drawing(sess)

        # Changing a row by hand means the line no longer names what is shown.
        from qtpy.QtCore import Qt

        from lobemap.viewer.panel import VISIBLE_COL

        row = tab._row_of(next(iter(members)))
        tab.table.item(row, VISIBLE_COL).setCheckState(Qt.Unchecked)
        assert menu.currentIndex() == 0


def test_the_intersection_preset_is_offered_where_it_applies(monkeypatch):
    with launched(monkeypatch, "view", "FAFB14") as (code, viewer):
        menu = session(viewer).panel.tabs["benton2025"].lines
        texts = [menu.itemText(i) for i in range(menu.count())]
        assert texts[0] == "Driver line..."
        assert any(t.startswith("Orco-GAL4 & GH146-GAL4 (") for t in texts), texts
        # A neuropil tab has no glomeruli to filter, so no menu.
        assert not session(viewer).panel.tabs["fafb_neuropil"].lines.isVisibleTo(
            session(viewer).panel.tabs["fafb_neuropil"]
        )


# -- VFB --------------------------------------------------------------------


def test_the_vfb_button_opens_the_selected_glomerulus(monkeypatch):
    import webbrowser

    from lobemap.viewer.panel import NAME_COL

    opened = []
    monkeypatch.setattr(webbrowser, "open", lambda url, *a, **k: opened.append(url))
    with launched(monkeypatch, "view", "JRCFIB2018F") as (code, viewer):
        tab = session(viewer).panel.tabs["neuprint_hemibrain"]
        vfb = next(b for b in _buttons(tab).values() if b.text().startswith("VFB"))
        assert not vfb.isEnabled(), "nothing is selected yet"
        row = next(r for r in range(tab.table.rowCount())
                   if tab.table.item(r, NAME_COL).text() == "DA1(R)")
        tab.table.selectRow(row)
        assert vfb.isEnabled() and vfb.text() == "VFB: DA1"
        vfb.click()
        assert opened == [(
            "https://www.virtualflybrain.org/term/"
            "antennal-lobe-glomerulus-da1-fbbt_00003932/"
        )]
        assert vfb.toolTip() == opened[0]


def test_hovering_a_glomerulus_points_the_vfb_button_at_it(monkeypatch):
    from qtpy.QtCore import Qt

    from lobemap.viewer.panel import VISIBLE_COL

    with launched(monkeypatch, "view", "FAFB14") as (code, viewer):
        tab = session(viewer).panel.tabs["benton2025"]
        index = tab.surface.meshset.names.index("DA1")
        _buttons(tab)["Show none"].click()
        tab.table.item(tab._row_of(index), VISIBLE_COL).setCheckState(Qt.Checked)
        pump(300)
        assert hover(viewer, tab.surface.meshset.centroid(index)) == "benton2025: DA1"
        vfb = next(b for b in _buttons(tab).values() if b.text().startswith("VFB"))
        assert vfb.text() == "VFB: DA1"
