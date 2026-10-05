"""The checkbox in each checkbox column's header, by what the canvas draws.

Show, Label and Fill each have one checkbox in their header, for the rows
the search lists: ticked when every listed row is, half ticked when some
are. A click ticks every listed row, or clears them all when all are
ticked. The header is clicked as a user clicks it, and the result read off
what is drawn: the meshes in 3D, and on the slice the outlines, the names
and the fills. The other headers still sort.
"""

from __future__ import annotations

import numpy as np
import pytest
from viewer_harness import (
    assert_rows_match_drawing,
    clear_all,
    click_header,
    drawn,
    every_index,
    launched,
    planes_cut,
    pump,
    rendered_labels,
    rendered_mesh,
    session,
    ticked,
)

pytestmark = pytest.mark.requires_data
pytest.importorskip("napari")


def _cols():
    from lobemap.viewer.panel import FILL_COL, LABEL_COL, NAME_COL, VISIBLE_COL

    return VISIBLE_COL, NAME_COL, LABEL_COL, FILL_COL


def _state(tab, column) -> str:
    return tab.header.state(column).name


def _tick(tab, index: int, state: str) -> None:
    """Set the Show box of compartment `index`'s row, as a click on it does."""
    from qtpy.QtCore import Qt

    from lobemap.viewer.panel import VISIBLE_COL

    tab.table.item(tab.table_row(index), VISIBLE_COL).setCheckState(getattr(Qt.CheckState, state))
    pump()


def _names_written(contour) -> set[str]:
    return {text for text, _pos, _rgba in rendered_labels(contour)}


def _filled_colors(contour) -> set[tuple]:
    """The colors of the fills drawn on the slice, one per filled glomerulus
    color; the outlines are opaque and the fills not."""
    _vertices, _faces, colors = rendered_mesh(contour)
    fill = colors[np.isclose(colors[:, 3], contour.FILL_ALPHA)]
    return {tuple(np.round(c[:3], 4)) for c in fill}


def _outline_colors(contour) -> set[tuple]:
    _vertices, _faces, colors = rendered_mesh(contour)
    return {tuple(np.round(c[:3], 4)) for c in colors[colors[:, 3] == 1.0]}


def test_show_ticks_and_clears_every_row_and_what_is_drawn(monkeypatch):
    """In 3D the meshes, in 2D the outlines on the plane."""
    show, *_ = _cols()
    with launched(monkeypatch, "view", "FAFB14") as (code, viewer):
        assert code == 0
        sess = session(viewer)
        tab = sess.panel.tabs["benton2025"]
        everything = set(every_index(tab))
        pump(300)
        assert _state(tab, show) == "Checked"
        assert drawn(tab.surface, tab.contour) == everything
        for ndisplay in (3, 2):
            viewer.dims.ndisplay = ndisplay
            pump(300)
            click_header(tab, show)
            pump(300)
            assert _state(tab, show) == "Unchecked"
            assert ticked(tab) == set()
            assert drawn(tab.surface, tab.contour) == set(), ndisplay
            click_header(tab, show)
            pump(300)
            assert _state(tab, show) == "Checked"
            assert ticked(tab) == everything
            want = everything if ndisplay == 3 else planes_cut(tab.surface)
            assert want and drawn(tab.surface, tab.contour) == want, ndisplay
            assert_rows_match_drawing(sess)


def test_label_and_fill_write_and_fill_every_row_on_the_slice(monkeypatch):
    show, _name, label, fill = _cols()
    with launched(monkeypatch, "view", "FAFB14", "--ndisplay", "2") as (code, viewer):
        assert code == 0
        sess = session(viewer)
        tab = sess.panel.tabs["benton2025"]
        contour = tab.contour
        everything = set(every_index(tab))
        pump(300)
        cut = planes_cut(tab.surface)
        assert cut, "the slice cuts no glomerulus"
        assert _names_written(contour) == set() and _filled_colors(contour) == set()

        click_header(tab, label)
        assert _state(tab, label) == "Checked" and ticked(tab, label) == everything
        assert _names_written(contour) == {contour.display_names[i] for i in cut}
        click_header(tab, label)
        assert _state(tab, label) == "Unchecked" and ticked(tab, label) == set()
        assert _names_written(contour) == set()

        click_header(tab, fill)
        assert _state(tab, fill) == "Checked" and ticked(tab, fill) == everything
        assert _filled_colors(contour) == _outline_colors(contour) != set()
        click_header(tab, fill)
        assert ticked(tab, fill) == set() and _filled_colors(contour) == set()
        # Show is its own column: the names and fills stayed off.
        assert _state(tab, show) == "Checked"


def test_the_header_is_half_ticked_for_some_rows_and_follows_the_search(monkeypatch):
    show, _name, label, _fill = _cols()
    with launched(monkeypatch, "view", "FAFB14", "--ndisplay", "2") as (code, viewer):
        assert code == 0
        sess = session(viewer)
        tab = sess.panel.tabs["benton2025"]
        contour = tab.contour
        everything = set(every_index(tab))
        da1 = tab.surface.meshset.names.index("DA1")

        # One row unticked by hand, then ticked again.
        _tick(tab, da1, "Unchecked")
        assert _state(tab, show) == "PartiallyChecked"
        assert da1 not in tab.surface.selection
        _tick(tab, da1, "Checked")
        assert _state(tab, show) == "Checked"

        # Search, then tick: the matches, and only they, are shown.
        clear_all(tab)
        assert drawn(tab.surface, contour) == set()
        tab.filter.setText("DA1")
        pump()
        listed = {i for row in tab.listed() for i in row.indices}
        assert da1 in listed and listed < everything
        assert _state(tab, show) == "Unchecked"
        click_header(tab, show)
        pump(300)
        assert ticked(tab) == tab.surface.selection == listed
        assert _state(tab, show) == "Checked"
        # The whole table again: some rows are ticked.
        tab.filter.setText("")
        pump()
        assert _state(tab, show) == "PartiallyChecked"
        # Labels for the listed rows only, which the slice writes where it cuts them.
        tab.filter.setText("DA1")
        click_header(tab, label)
        tab.filter.setText("")
        pump(300)
        assert ticked(tab, label) == listed
        assert _state(tab, label) == "PartiallyChecked"
        cut = planes_cut(tab.surface)
        assert _names_written(contour) == {contour.display_names[i] for i in cut & listed}
        # A half ticked header ticks every row; a search that lists none
        # leaves nothing to act on.
        click_header(tab, show)
        pump(300)
        assert ticked(tab) == everything and _state(tab, show) == "Checked"
        tab.filter.setText("no such glomerulus")
        pump()
        assert not tab.listed() and not tab.header.is_enabled(show)
        click_header(tab, show)
        assert ticked(tab) == everything
        tab.filter.setText("")


def test_a_row_shown_on_one_side_half_ticks_its_box_and_the_header(monkeypatch):
    """The hemibrain has both sides of D: one side shown half ticks its row,
    and the header then ticks every side of every row."""
    show, *_ = _cols()
    with launched(monkeypatch, "view", "JRCFIB2018F") as (code, viewer):
        assert code == 0
        sess = session(viewer)
        tab = sess.panel.tabs["neuprint_hemibrain"]
        row = next(r for r in tab.rows.values() if len(r.indices) == 2)
        clear_all(tab)
        tab.select([row.indices[0]])
        pump(300)
        assert tab.table.item(tab.table_row(row.indices[0]), show).checkState().name == (
            "PartiallyChecked")
        assert _state(tab, show) == "PartiallyChecked"
        click_header(tab, show)
        pump(300)
        assert drawn(tab.surface, tab.contour) == set(every_index(tab))
        assert _state(tab, show) == "Checked"


def test_the_header_draws_each_state_as_the_style_draws_a_checkbox(monkeypatch):
    """Grabbed from the header as drawn: one picture per state, the same
    picture each time a state comes back, and a different one for each."""
    from qtpy.QtCore import Qt

    show, *_ = _cols()
    with launched(monkeypatch, "view", "FAFB14") as (code, viewer):
        assert code == 0
        window = viewer.window._qt_window
        window.setAttribute(Qt.WidgetAttribute.WA_DontShowOnScreen, True)
        window.resize(1440, 900)
        window.show()
        pump(300)
        tab = session(viewer).panel.tabs["benton2025"]
        header = tab.header
        da1 = tab.surface.meshset.names.index("DA1")

        def picture():
            pump()
            x = header.sectionViewportPosition(show)
            return header.grab().copy(x, 0, header.sectionSize(show), header.height()).toImage()

        seen = {"Checked": picture()}
        _tick(tab, da1, "Unchecked")
        seen["PartiallyChecked"] = picture()
        clear_all(tab)
        seen["Unchecked"] = picture()
        assert len({img.cacheKey() for img in seen.values()}) == 3
        assert seen["Unchecked"] != seen["PartiallyChecked"] != seen["Checked"]
        assert seen["Unchecked"] != seen["Checked"]
        click_header(tab, show)
        assert picture() == seen["Checked"]
        _tick(tab, da1, "Unchecked")
        assert picture() == seen["PartiallyChecked"]


def test_the_other_headers_sort_and_the_checkbox_headers_do_not(monkeypatch):
    from qtpy.QtCore import Qt

    show, name, label, fill = _cols()
    with launched(monkeypatch, "view", "FAFB14") as (code, viewer):
        assert code == 0
        tab = session(viewer).panel.tabs["benton2025"]
        table, header = tab.table, tab.header

        def order():
            return [tab.row_at(r).key for r in range(table.rowCount())]

        ascending = order()
        click_header(tab, name)
        assert header.sortIndicatorSection() == name
        assert header.sortIndicatorOrder() == Qt.SortOrder.DescendingOrder
        assert order() == ascending[::-1]
        for column in (show, label, fill):
            click_header(tab, column)
            assert header.sortIndicatorSection() == name, column
            assert order() == ascending[::-1], column
        from lobemap.viewer.panel import RECEPTOR_COL

        click_header(tab, RECEPTOR_COL)
        assert header.sortIndicatorSection() == RECEPTOR_COL
        receptors = [table.item(r, RECEPTOR_COL).text() for r in range(table.rowCount())]
        keys = [table.item(r, RECEPTOR_COL).key for r in range(table.rowCount())]
        assert keys == sorted(keys), receptors[:5]


def test_the_switcher_only_offers_spaces_that_can_load(registry):
    """Offering a space with no ingested data would be a dead end."""
    pytest.importorskip("qtpy")
    from lobemap.viewer.switcher import SpaceSwitcher

    spaces = SpaceSwitcher.loadable_spaces(registry)
    assert "GRABE" in spaces
    assert "FAFB14" in spaces
    for space_id in spaces:
        assert space_id in registry.spaces
