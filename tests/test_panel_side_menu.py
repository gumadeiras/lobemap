"""The Sides menu: a row's boxes act on the sides it chooses.

One row holds every side of a glomerulus or neuropil. With Sides set to
Left or Right, its Show, Label and Fill boxes and the header checkboxes act
on that side alone, so one side can be shown, named or filled again; each
box shows the row's state on the chosen sides, half ticked where they
differ. Read off what the canvas draws, as `test_panel_sides` does.
"""

from __future__ import annotations

import numpy as np
import pytest
from viewer_harness import (
    assert_renders_loops,
    click_header,
    contour_loops,
    drawn,
    launched,
    pump,
    rendered_labels,
    session,
)

pytestmark = pytest.mark.requires_data
pytest.importorskip("napari")


def _choose(page, sides: str) -> None:
    """Pick `sides` in a tab's Sides menu, as a user does."""
    page.sides_menu.setCurrentIndex(page.sides_menu.findText(sides))
    pump(300)


def _row(tab, name: str) -> int:
    from lobemap.viewer.panel import NAME_COL

    return next(r for r in range(tab.table.rowCount())
                if tab.table.item(r, NAME_COL).text() == name)


def _box(tab, name: str, column: int):
    return tab.table.item(_row(tab, name), column).checkState()


def _tick(tab, name: str, column: int, on: bool = True) -> None:
    from qtpy.QtCore import Qt

    tab.table.item(_row(tab, name), column).setCheckState(
        Qt.CheckState.Checked if on else Qt.CheckState.Unchecked)
    pump(300)


def _sides(tab, name: str) -> dict[str, int]:
    """The mesh index of each side of the row of `name`, by side."""
    row = tab.row_at(_row(tab, name))
    return {side.where: side.index for side in row.sides}


def _through(viewer, meshset, indices) -> None:
    """Put the plane where it cuts every one of `indices`."""
    axis = int(viewer.dims.order[0])
    spans = [meshset.compartment(i)[0][:, axis] for i in indices]
    low, high = max(s.min() for s in spans), min(s.max() for s in spans)
    assert low < high, "they share no plane"
    viewer.dims.set_point(axis, float((low + high) / 2))
    pump(400)


def test_one_side_is_shown_alone_and_its_boxes_say_so(monkeypatch):
    """Sides set to Right, Show ticked on DA1: the right DA1 alone, as a mesh
    in 3D and an outline on the slice. Its Show box is ticked under Right,
    half ticked under Both and clear under Left."""
    from qtpy.QtCore import Qt

    from lobemap.viewer.panel import VISIBLE_COL

    with launched(monkeypatch, "view", "GRABE") as (code, viewer):
        assert code == 0
        sess = session(viewer)
        tab, page = sess.panel.tab("grabe2015"), sess.panel.page_of("grabe2015")
        contour = sess.contours["grabe2015"]
        assert page.sides_menu.currentText() == "Both"
        tab.select([])
        pump(300)
        sides = _sides(tab, "DA1")
        assert set(sides) == {"Left", "Right"}

        _choose(page, "Right")
        _tick(tab, "DA1", VISIBLE_COL)
        assert drawn(tab.surface) == {sides["Right"]}
        assert _box(tab, "DA1", VISIBLE_COL) == Qt.CheckState.Checked
        assert tab.header.state(VISIBLE_COL) == Qt.CheckState.PartiallyChecked
        _choose(page, "Both")
        assert _box(tab, "DA1", VISIBLE_COL) == Qt.CheckState.PartiallyChecked
        _choose(page, "Left")
        assert _box(tab, "DA1", VISIBLE_COL) == Qt.CheckState.Unchecked
        # Choosing a side changes what the boxes say, never what is drawn.
        assert drawn(tab.surface) == {sides["Right"]}

        viewer.dims.ndisplay = 2
        pump(300)
        _through(viewer, tab.surface.meshset, sides.values())
        assert {owner for owner, _loop in contour_loops(contour)} == {sides["Right"]}
        # Ticked under Left, the left joins it; cleared under Right, the
        # right goes and the left stays.
        _tick(tab, "DA1", VISIBLE_COL)
        assert {owner for owner, _loop in contour_loops(contour)} == set(sides.values())
        _choose(page, "Right")
        _tick(tab, "DA1", VISIBLE_COL, on=False)
        assert {owner for owner, _loop in contour_loops(contour)} == {sides["Left"]}
        viewer.dims.ndisplay = 3
        pump(300)
        assert drawn(tab.surface) == {sides["Left"]}


def test_label_and_fill_act_on_the_chosen_side_of_the_slice(monkeypatch):
    from qtpy.QtCore import Qt

    from lobemap.viewer.panel import FILL_COL, LABEL_COL

    with launched(monkeypatch, "view", "GRABE", "--ndisplay", "2") as (code, viewer):
        assert code == 0
        sess = session(viewer)
        tab, page = sess.panel.tab("grabe2015"), sess.panel.page_of("grabe2015")
        contour = sess.contours["grabe2015"]
        sides = _sides(tab, "DM2")
        _through(viewer, tab.surface.meshset, sides.values())

        _choose(page, "Left")
        _tick(tab, "DM2", LABEL_COL)
        _tick(tab, "DM2", FILL_COL)
        assert contour.labels == {sides["Left"]} and contour.filled == {sides["Left"]}
        assert_renders_loops(contour)          # the left filled, as drawn
        written = rendered_labels(contour)
        assert [text for text, _pos, _rgba in written] == ["DM2"]
        left = max((loop for owner, loop in contour_loops(contour) if owner == sides["Left"]),
                   key=len)
        xy = list(viewer.dims.displayed)
        np.testing.assert_allclose(written[0][1], left[:, xy].mean(axis=0)[::-1], atol=1e-3)

        _choose(page, "Right")
        assert _box(tab, "DM2", LABEL_COL) == Qt.CheckState.Unchecked
        _tick(tab, "DM2", FILL_COL)
        assert contour.filled == set(sides.values()) and contour.labels == {sides["Left"]}
        _choose(page, "Both")
        assert _box(tab, "DM2", FILL_COL) == Qt.CheckState.Checked
        assert _box(tab, "DM2", LABEL_COL) == Qt.CheckState.PartiallyChecked
        assert_renders_loops(contour)


def test_the_header_checkbox_acts_on_the_listed_rows_chosen_sides(monkeypatch):
    from qtpy.QtCore import Qt

    from lobemap.viewer.panel import VISIBLE_COL

    with launched(monkeypatch, "view", "GRABE") as (code, viewer):
        assert code == 0
        sess = session(viewer)
        tab, page = sess.panel.tab("grabe2015"), sess.panel.page_of("grabe2015")
        everything = set(tab.surface.selection)
        tab.filter.setText("DA")
        pump(300)
        listed = tab.listed()
        assert 2 < len(listed) < tab.table.rowCount()
        right = {side.index for row in listed for side in row.sides if side.where == "Right"}

        _choose(page, "Right")
        assert tab.header.state(VISIBLE_COL) == Qt.CheckState.Checked
        click_header(tab, VISIBLE_COL)          # clears the listed rows' right sides
        pump(300)
        assert drawn(tab.surface) == everything - right
        assert tab.header.state(VISIBLE_COL) == Qt.CheckState.Unchecked
        _choose(page, "Both")
        assert tab.header.state(VISIBLE_COL) == Qt.CheckState.PartiallyChecked
        assert {_box(tab, row.name, VISIBLE_COL) for row in listed} == {
            Qt.CheckState.PartiallyChecked}
        click_header(tab, VISIBLE_COL)          # half ticked: ticks every side
        pump(300)
        assert drawn(tab.surface) == everything


def test_a_midline_neuropil_is_on_either_side(monkeypatch):
    """A neuropil across the midline has no left or right to leave out:
    Left and Right both act on it."""
    from qtpy.QtCore import Qt

    from lobemap.viewer.panel import VISIBLE_COL

    with launched(monkeypatch, "view", "FAFB14") as (code, viewer):
        assert code == 0
        sess = session(viewer)
        tab = sess.panel.open("fafb_neuropil")
        page = sess.panel.page_of("fafb_neuropil")
        pump(300)
        middle = next(row for row in tab.rows.values()
                      if [side.where for side in row.sides] == ["Midline"])
        for sides in ("Left", "Right"):
            _choose(page, sides)
            tab.select([])
            pump(300)
            _tick(tab, middle.name, VISIBLE_COL)
            assert drawn(tab.surface) == set(middle.indices), sides
            assert _box(tab, middle.name, VISIBLE_COL) == Qt.CheckState.Checked


def test_the_sides_menu_takes_the_wheel_only_with_focus(monkeypatch):
    from qtpy.QtCore import QPoint, QPointF, Qt
    from qtpy.QtGui import QWheelEvent
    from qtpy.QtWidgets import QApplication

    with launched(monkeypatch, "view", "GRABE") as (code, viewer):
        assert code == 0
        menu = session(viewer).panel.page_of("grabe2015").sides_menu
        assert menu.focusPolicy() != Qt.FocusPolicy.WheelFocus
        for dy in (-120, 120, -360):
            centre = QPointF(menu.rect().center())
            event = QWheelEvent(centre, QPointF(menu.mapToGlobal(menu.rect().center())),
                                QPoint(0, 0), QPoint(0, dy), Qt.MouseButton.NoButton,
                                Qt.KeyboardModifier.NoModifier, Qt.ScrollPhase.NoScrollPhase,
                                False)
            QApplication.sendEvent(menu, event)
            pump()
            assert menu.currentText() == "Both", dy
