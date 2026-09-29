"""A checked row is a drawn glomerulus, in 3D and in 2D, whatever happened.

The panel used to keep its own idea of what was shown: a hidden atlas read
"N / N shown", compaction switched a mesh back on under a 2D slice, and a
remembered visibility went stale across mode switches. Each test drives
the real controls and compares the rows, the count and the rendered
geometry (`viewer_harness.drawn`), not the selection alone.
"""

from __future__ import annotations

import random
import statistics
import time

import pytest
from viewer_harness import (
    SPACES,
    assert_rows_match_drawing,
    checked,
    drawn,
    launched,
    mode_layer,
    pump,
    session,
)

pytestmark = pytest.mark.requires_data
pytest.importorskip("napari")


def _buttons(tab):
    from qtpy.QtWidgets import QPushButton

    return {b.text(): b for b in tab.findChildren(QPushButton)}


def _tick(tab, index: int, on: bool) -> None:
    from qtpy.QtCore import Qt

    from lobemap.viewer.panel import VISIBLE_COL

    row = tab._row_of(index)
    tab.table.item(row, VISIBLE_COL).setCheckState(Qt.Checked if on else Qt.Unchecked)


@pytest.mark.parametrize("space", SPACES)
@pytest.mark.parametrize("ndisplay", ["3", "2"])
def test_every_tab_draws_what_it_checks_on_open(monkeypatch, space, ndisplay):
    with launched(monkeypatch, "view", space, "--ndisplay", ndisplay) as (code, viewer):
        assert code == 0
        pump(300)
        sess = session(viewer)
        assert_rows_match_drawing(sess)
        primary = sess.registry.primary_atlas(space).id
        for name, tab in sess.panel.tabs.items():
            if name != primary:
                # Secondary atlases and reference shells open off, and say so.
                assert checked(tab) == set(), name
                assert tab.count.text().startswith("0 / "), (name, tab.count.text())


def test_a_hidden_atlas_shows_exactly_the_row_ticked(monkeypatch):
    """Unticking one row of a hidden atlas used to show all the others."""
    with launched(monkeypatch, "view", "JRCFIB2018F") as (code, viewer):
        sess = session(viewer)
        tab = sess.panel.tabs["schlegel2021_s12"]
        _tick(tab, 7, True)
        pump(300)
        assert drawn(tab.surface, tab.contour) == {7}
        assert_rows_match_drawing(sess)
        _tick(tab, 7, False)
        pump(300)
        assert drawn(tab.surface, tab.contour) == set()
        assert_rows_match_drawing(sess)


def test_show_all_on_a_hidden_shell_checks_and_draws_every_row(monkeypatch):
    with launched(monkeypatch, "view", "FAFB14") as (code, viewer):
        sess = session(viewer)
        tab = sess.panel.tabs["fafb_neuropil"]
        _buttons(tab)["Show all"].click()
        pump(300)
        everything = set(range(tab.surface.meshset.n_compartments))
        assert drawn(tab.surface, tab.contour) == everything
        assert_rows_match_drawing(sess)


def test_compaction_does_not_bring_the_mesh_back_in_2d(monkeypatch):
    with launched(monkeypatch, "view", "GRABE", "--ndisplay", "2") as (code, viewer):
        sess = session(viewer)
        tab = sess.panel.tabs["grabe2015"]
        _tick(tab, 3, False)
        pump(400)                       # past the 250 ms compaction
        assert not tab.surface.layer.visible, "the mesh came back under the slice"
        assert tab.contour.layer.visible
        assert_rows_match_drawing(sess)


def test_rows_and_drawing_agree_after_mode_switches(monkeypatch):
    """The reproduced case -- none in 3D, all in 2D, back to 3D -- then a
    seeded run of every kind of change interleaved with switches."""
    with launched(monkeypatch, "view", "JRCFIB2018F") as (code, viewer):
        sess = session(viewer)
        tab = sess.panel.tabs["neuprint_hemibrain"]
        _buttons(tab)["Show none"].click()
        viewer.dims.ndisplay = 2
        _buttons(tab)["Show all"].click()
        viewer.dims.ndisplay = 3
        pump(300)
        assert drawn(tab.surface, tab.contour) == set(range(tab.surface.meshset.n_compartments))
        assert_rows_match_drawing(sess)

        rng = random.Random(1)
        names = list(sess.panel.tabs)
        for _step in range(30):
            tab = sess.panel.tabs[rng.choice(names)]
            action = rng.choice(("tick", "untick", "all", "none", "invert", "mode"))
            n = tab.surface.meshset.n_compartments
            if action == "mode":
                viewer.dims.ndisplay = 5 - viewer.dims.ndisplay
            elif action in ("tick", "untick"):
                _tick(tab, rng.randrange(n), action == "tick")
            else:
                label = {"all": "Show all", "none": "Show none", "invert": "Invert"}[action]
                _buttons(tab)[label].click()
            pump(300)
            assert_rows_match_drawing(sess)


def test_the_layer_list_eye_is_a_selection_change(monkeypatch):
    """Hiding a layer from napari's list unchecks its rows; showing it again
    gives them back, in either mode."""
    with launched(monkeypatch, "view", "GRABE") as (code, viewer):
        sess = session(viewer)
        tab = sess.panel.tabs["grabe2015"]
        _tick(tab, 0, False)
        kept = set(tab.surface.selection)
        for ndisplay in (3, 2):
            viewer.dims.ndisplay = ndisplay
            layer = mode_layer(tab.surface, tab.contour)
            layer.visible = False
            pump(300)
            assert checked(tab) == set() and drawn(tab.surface, tab.contour) == set()
            assert_rows_match_drawing(sess)
            layer.visible = True
            pump(300)
            assert checked(tab) == kept
            assert_rows_match_drawing(sess)


@pytest.mark.parametrize("space", SPACES)
def test_a_row_toggle_takes_under_10_ms(monkeypatch, space):
    """PERF-3: the synchronous part of one checkbox toggle, in 3D.

    Timed around `setCheckState`, which runs the whole handler chain the
    click does, with events pumped between toggles so the deferred
    compaction never lands inside a measurement. Median of 20, after a
    warm-up. It was 44-218 ms, nearly all of it no-op `visible` writes.
    """
    with launched(monkeypatch, "view", space) as (code, viewer):
        sess = session(viewer)
        tab = sess.panel.tabs[sess.registry.primary_atlas(space).id]
        _tick(tab, 0, False)
        pump(300)
        times = []
        for i in range(20):
            index = 1 + i % 4
            on = index not in tab.surface.selection
            start = time.perf_counter()
            _tick(tab, index, on)
            times.append((time.perf_counter() - start) * 1000)
            pump(5)
        assert statistics.median(times) < 10.0, sorted(times)
