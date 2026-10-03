"""One row per compartment: a row's boxes act on every side of it.

Grabe 2015 has both antennal lobes and FAFB's neuropils both hemispheres, so
a row there is two meshes. Ticking its Show, Label and Fill boxes, as a user
does, must draw, name and fill both sides, in 3D and on the slice, and
clearing them must take both away -- read off what the canvas draws, not
off the panel. Hovering still names the one side under the cursor, and the
details say which sides there are and where they differ.
"""

from __future__ import annotations

import numpy as np
import pytest
from viewer_harness import (
    assert_renders_loops,
    assert_rows_match_drawing,
    contour_loops,
    drawn,
    hover,
    launched,
    pump,
    rendered_labels,
    session,
)

pytestmark = pytest.mark.requires_data
pytest.importorskip("napari")


def _buttons(tab):
    from qtpy.QtWidgets import QPushButton

    return {b.text(): b for b in tab.findChildren(QPushButton)}


def _tick(tab, table_row: int, column: int, on: bool) -> None:
    from qtpy.QtCore import Qt

    tab.table.item(table_row, column).setCheckState(
        Qt.CheckState.Checked if on else Qt.CheckState.Unchecked)
    pump(300)


def _find(tab, name: str) -> int:
    """The table row a reader sees `name` in."""
    from lobemap.viewer.panel import NAME_COL

    return next(r for r in range(tab.table.rowCount())
                if tab.table.item(r, NAME_COL).text() == name)


def _where(meshset, index: int) -> str:
    """The side a mesh name gives, in the words hovering uses."""
    from lobemap.core.names import parse_roi

    return {"L": "left", "R": "right"}[parse_roi(meshset.names[index])[1]]


def _through_both(viewer, meshset, sides) -> None:
    """Put the plane where it cuts every side: the middle of the stretch of
    the slice axis that all of them span."""
    axis = int(viewer.dims.order[0])
    spans = [meshset.compartment(i)[0][:, axis] for i in sides]
    low, high = max(s.min() for s in spans), min(s.max() for s in spans)
    assert low < high, "the sides share no plane"
    viewer.dims.set_point(axis, float((low + high) / 2))
    pump(400)


@pytest.mark.parametrize(("space", "part", "name"), [
    ("GRABE", "grabe2015", "DM2"),
    ("FAFB14", "fafb_neuropil", "AL"),
])
def test_a_rows_boxes_act_on_every_side_in_3d_and_on_the_slice(monkeypatch, space,
                                                                part, name):
    from lobemap.viewer.panel import FILL_COL, LABEL_COL, VISIBLE_COL

    with launched(monkeypatch, "view", space) as (code, viewer):
        assert code == 0
        sess = session(viewer)
        tab = sess.panel.tab(part)
        contour, meshset = sess.contours[part], tab.surface.meshset
        _buttons(tab)["None"].click()
        r = _find(tab, name)
        sides = set(tab.row_at(r).indices)
        assert sorted(meshset.names[i] for i in sides) == sorted(
            n for n in meshset.names if n.startswith(name) and n[len(name)] in "(_")
        assert len(sides) == 2

        # Show: both meshes in 3D, and nothing else.
        _tick(tab, r, VISIBLE_COL, True)
        assert drawn(tab.surface) == sides
        assert tab.count.text() == f"1 of {tab.table.rowCount()} shown"
        assert_rows_match_drawing(sess)
        # Hovering names the side under the cursor, each in turn.
        for i in sides:
            said = hover(viewer, meshset.centroid(i))
            assert said.split(" — ")[0].endswith(f"{_where(meshset, i)})"), said

        # On the slice: both outlined, then both named and filled.
        viewer.dims.ndisplay = 2
        pump(300)
        _through_both(viewer, meshset, sides)
        assert {owner for owner, _loop in contour_loops(contour)} == sides
        _tick(tab, r, LABEL_COL, True)
        _tick(tab, r, FILL_COL, True)
        assert contour.labels == sides and contour.filled == sides
        assert_renders_loops(contour)       # each side's fill and name, as drawn
        assert sorted(text for text, _pos, _rgba in rendered_labels(contour)) == sorted(
            contour.display_names[i] for i in sides)
        for i in sides:
            loop = max((lp for owner, lp in contour_loops(contour) if owner == i), key=len)
            said = hover(viewer, np.asarray(loop).mean(axis=0))
            assert said.split(" — ")[0].endswith(f"{_where(meshset, i)})"), said
        assert_rows_match_drawing(sess)

        # Cleared: both sides lose their name, their fill and their outline.
        _tick(tab, r, FILL_COL, False)
        _tick(tab, r, LABEL_COL, False)
        assert not contour.labels and not contour.filled
        assert rendered_labels(contour) == []
        assert_renders_loops(contour)
        _tick(tab, r, VISIBLE_COL, False)
        assert contour_loops(contour) == []
        viewer.dims.ndisplay = 3
        pump(300)
        assert drawn(tab.surface) == set()
        assert_rows_match_drawing(sess)


def _details(tab, name: str) -> dict[str, str]:
    """What the details say once the row of `name` is selected."""
    tab.table.selectRow(_find(tab, name))
    out = {field: label.text() for field, label in tab.details.items()}
    out["title"] = tab.detail_title.text()
    tab.table.clearSelection()
    return out


def test_the_details_say_which_sides_there_are_and_lose_nothing(monkeypatch):
    """The cases the data hold, as a reader sees them."""
    from viewer_harness import switch_to

    from lobemap.viewer.panel import NAME_COL

    with launched(monkeypatch, "view", "GRABE") as (code, viewer):
        assert code == 0
        tab = session(viewer).panel.tab("grabe2015")
        # Grabe's VP2 is in doubt on both sides, each with its own label.
        vp2 = _details(tab, "VP2 (VM6?)")
        assert vp2["title"] == "VP2 (VM6?)"
        assert vp2["Sides"] == "Left and right"
        tip = tab.table.item(_find(tab, "VP2 (VM6?)"), NAME_COL).toolTip()
        assert tip.startswith("Left: Grabe 2015 labels this region 'VP2_left_VM6andVC6'.")
        assert "\n\nRight: Grabe 2015 labels this region 'VP2_right_VM6andVC6'." in tip
        assert _details(tab, "DA1")["Sides"] == "Left and right"

        switch_to(viewer, "JRCFIB2018F")
        tab = session(viewer).panel.tab("neuprint_hemibrain")
        # The hemibrain's renamed VC3l has its right side only.
        vc3l = _details(tab, "VC3l*")
        assert (vc3l["title"], vc3l["Sides"], vc3l["Standard name"]) == ("VC3l", "Right", "VC3")
        assert tab.table.item(_find(tab, "VC3l*"), NAME_COL).toolTip() == (
            "This atlas calls it VC3l; its standard name is VC3 (renamed).")
        assert _details(tab, "DA2")["Sides"] == "Left and right"
        assert _details(tab, "DA1")["Sides"] == "Right"

        switch_to(viewer, "FAFB14")
        tab = session(viewer).panel.tab("fafb_neuropil")
        assert _details(tab, "AL")["Sides"] == "Left and right"
        midline = [row for row in tab.rows.values() if row.details["Sides"] == "Midline"]
        assert midline and all(len(row.sides) == 1 and row.sides[0].published == row.name
                               for row in midline)
        tab = session(viewer).panel.tab("benton2025")
        assert {row.details["Sides"] for row in tab.rows.values()} == {"Left"}
