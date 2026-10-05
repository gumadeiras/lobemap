"""Two tabs per brain, and a source menu at the top of each.

The tabs name what they hold, Glomeruli and Neuropils; the menu picks which
atlas of that kind the table shows and cites it underneath. Choosing a
source shows its table and builds it if it was left for later, as opening
its own tab did, and draws nothing it did not draw before. A click in the
canvas on a compartment of another source chooses that source. Everything
is driven through the widgets and read back from what is drawn.
"""

from __future__ import annotations

import pytest
from viewer_harness import (
    SPACES,
    assert_rows_match_drawing,
    checked,
    click,
    drawn,
    every_index,
    launched,
    pump,
    session,
    switch_to,
)

pytestmark = pytest.mark.requires_data
pytest.importorskip("napari")

def _show(viewer) -> None:
    from qtpy.QtCore import Qt

    window = viewer.window._qt_window
    window.setAttribute(Qt.WidgetAttribute.WA_DontShowOnScreen, True)
    window.resize(1440, 900)
    window.show()
    pump(300)


def _pick(page, title: str) -> None:
    """Choose a source in a tab's menu, by what it says, as a user does."""
    page.menu.setCurrentIndex(page.menu.findText(title))
    pump(300)


def _drawing(viewer, sess) -> dict:
    """What the canvas draws: each visible layer, and each part's compartments."""
    out = {"visible": sorted(layer.name for layer in viewer.layers if layer.visible)}
    for name, surface in sess.surfaces.items():
        out[name] = drawn(surface, sess.contours.get(name))
    return out


def test_each_brain_opens_on_its_own_atlas_and_cites_each_source(monkeypatch):
    """Which tabs and sources there are is `test_panel_consistency`'s."""
    from qtpy.QtCore import Qt

    with launched(monkeypatch, "view", SPACES[0]) as (code, viewer):
        assert code == 0
        for space in SPACES:
            switch_to(viewer, space)
            panel = session(viewer).panel
            pages = [panel.widget(i) for i in range(panel.count())]
            # Each opens on the glomeruli, showing the brain's own atlas.
            primary = session(viewer).registry.primary_atlas(space).id
            assert panel.tabText(panel.currentIndex()) == "Glomeruli"
            assert panel.current() == primary
            for page in pages:
                # The citation under the menu is the chosen source's, which
                # each menu item also gives as its tooltip.
                for i in range(page.menu.count()):
                    page.menu.setCurrentIndex(i)
                    about = page.menu.itemData(i, Qt.ItemDataRole.ToolTipRole)
                    assert page.citation.text() == about and " et al. " in about


@pytest.mark.parametrize("ndisplay", ["3", "2"])
def test_choosing_a_source_shows_its_table_and_draws_nothing_new(monkeypatch, ndisplay):
    with launched(monkeypatch, "view", "JRCFIB2018F", "--ndisplay", ndisplay) as (
        code, viewer,
    ):
        assert code == 0
        sess = session(viewer)
        panel = sess.panel
        page = panel.pages["Glomeruli"]
        assert "schlegel2021_s11" in sess.pending
        before = _drawing(viewer, sess)

        _pick(page, "Schlegel (sensory)")
        # Built, as its own tab used to be the first time it opened, and shown.
        assert "schlegel2021_s11" in sess.surfaces and "schlegel2021_s11" not in sess.pending
        tab = panel.tabs["schlegel2021_s11"]
        assert page.stack.currentWidget() is tab
        assert panel.current() == "schlegel2021_s11"
        assert page.citation.text() == (
            "Schlegel et al. 2021, eLife, file 11: glomeruli defined from sensory neurons")
        # Nothing more is drawn, and nothing less: its rows are unchecked.
        after = _drawing(viewer, sess)
        assert after.pop("schlegel2021_s11") == set()
        assert after == before
        assert checked(tab) == set()
        assert_rows_match_drawing(sess)

        # Back to neuPrint: its table again, the drawing still the same.
        _pick(page, "neuPrint")
        assert page.stack.currentWidget() is panel.tabs["neuprint_hemibrain"]
        assert {k: v for k, v in _drawing(viewer, sess).items() if k != "schlegel2021_s11"} \
            == before

        # The Neuropils tab builds the source its menu shows when it opens.
        assert "neuprint_hemibrain_neuropil" in sess.pending
        panel.setCurrentWidget(panel.pages["Neuropils"])
        pump(300)
        assert "neuprint_hemibrain_neuropil" in sess.surfaces
        assert panel.current() == "neuprint_hemibrain_neuropil"
        assert checked(panel.tabs["neuprint_hemibrain_neuropil"]) == set()
        assert_rows_match_drawing(sess)


@pytest.mark.parametrize("ndisplay", [3, 2])
def test_a_click_on_another_sources_compartment_chooses_that_source(monkeypatch, ndisplay):
    """A deliberate act, so the panel may change: the tab, the source and the row."""
    from viewer_harness import contour_loops

    with launched(monkeypatch, "view", "JRCFIB2018F") as (code, viewer):
        assert code == 0
        _show(viewer)
        sess = session(viewer)
        panel = sess.panel
        glomeruli = panel.pages["Glomeruli"]
        # Schlegel (sensory) alone drawn, then the neuPrint table chosen
        # again and the neuropils open: the clicked source is on show nowhere.
        _pick(glomeruli, "Schlegel (sensory)")
        schlegel = panel.tabs["schlegel2021_s11"]
        schlegel.select(every_index(schlegel))
        panel.tabs["neuprint_hemibrain"].select([])
        _pick(glomeruli, "neuPrint")
        panel.setCurrentWidget(panel.pages["Neuropils"])
        pump(300)
        panel.tabs["neuprint_hemibrain_neuropil"].select([])
        viewer.dims.ndisplay = ndisplay
        pump(400)
        index = schlegel.surface.meshset.names.index("DA1")
        if ndisplay == 3:
            target = schlegel.surface.meshset.centroid(index)
        else:
            axis = int(viewer.dims.order[0])
            viewer.dims.set_point(axis, float(schlegel.surface.meshset.centroid(index)[axis]))
            pump(400)
            loops = [lp for owner, lp in contour_loops(sess.contours["schlegel2021_s11"])
                     if owner == index]
            target = max(loops, key=len).mean(axis=0)

        said = click(viewer, target)
        assert said == "DA1 (right) — Schlegel (sensory)"
        assert panel.tabText(panel.currentIndex()) == "Glomeruli"
        assert glomeruli.menu.currentText() == "Schlegel (sensory)"
        assert glomeruli.stack.currentWidget() is schlegel
        row = schlegel.selected()
        assert row is not None and index in row.indices
        assert schlegel.detail_title.text() == "DA1"


def _places(page, panel) -> dict:
    """Where the menus, the citation and the table sit, in the panel. The
    source menu by its corner and height: it is as wide as its longest
    source's name, which differs between tabs and brains."""
    def rect(widget):
        corner = widget.mapTo(panel, widget.rect().topLeft())
        return (corner.x(), corner.y(), widget.width(), widget.height())

    menu = rect(page.menu)
    assert menu[2] == page.menu.sizeHint().width(), menu
    return {"menu": (menu[0], menu[1], menu[3]), "sides": rect(page.sides_menu),
            "citation": rect(page.citation), "tables": rect(page.body)}


def test_the_menu_sits_in_the_same_place_in_every_tab_and_brain(monkeypatch):
    """One source or three, glomeruli or neuropils: the same places, and the
    Sides menu at the same place under it."""
    with launched(monkeypatch, "view", SPACES[0]) as (code, viewer):
        assert code == 0
        _show(viewer)
        places = {}
        for space in SPACES:
            switch_to(viewer, space)
            pump(300)
            panel = session(viewer).panel
            for kind, page in panel.pages.items():
                panel.setCurrentWidget(page)
                pump(200)
                for i in range(page.menu.count()):
                    page.menu.setCurrentIndex(i)
                    pump(100)
                    places[(space, kind, page.menu.itemText(i))] = _places(page, panel)
        assert len(places) == 9
        assert len({repr(p) for p in places.values()}) == 1, places
