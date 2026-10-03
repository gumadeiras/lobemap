"""The glomerulus table: sorting, the fill toggle, and the annotation join.

Every tab of a kind shows the same columns; `test_panel_consistency.py`
compares them across all four spaces, and this file drives one of each.

Sorting is the risky one. Every handler used to treat the visual row as
the compartment id -- `_set_rows`, the filter, `highlight` -- which is
true only while the table is in insertion order. Once a header click can
reorder it, a row number means nothing, so these check behavior AFTER a
sort rather than before. Nor is a row one compartment: it is every side of
one, so a box ticked acts on each.
"""

from __future__ import annotations

import pytest

pytest.importorskip("napari")


@pytest.fixture
def tab(core_data, registry):
    import napari

    from lobemap.viewer.app import build_scene
    from lobemap.viewer.panel import CompartmentPanel

    try:
        viewer = napari.Viewer(show=False, ndisplay=3)
    except Exception as exc:                        # pragma: no cover
        pytest.skip(f"no Qt display: {exc}")
    try:
        surfaces, contours = build_scene(viewer, registry, "JRCFIB2018F")
        panel = CompartmentPanel(viewer, surfaces, registry=registry,
                                 contours=contours)
        yield panel.tabs["neuprint_hemibrain"]
    finally:
        viewer.close()


def _col(tab, name):
    from lobemap.viewer.panel import GLOMERULUS_COLUMNS

    return GLOMERULUS_COLUMNS.index(name)


def _click(tab, text):
    """Press one of the tab's buttons, the way a user does."""
    from qtpy.QtWidgets import QPushButton

    buttons = {b.text(): b for b in tab.findChildren(QPushButton)}
    assert text in buttons, f"no {text!r} button in {sorted(buttons)}"
    buttons[text].click()


def _drawn(tab) -> set[int]:
    """The compartments the canvas shows, not the ones the panel holds.

    In 2D the cross-sections on the contour layer; in 3D the mesh's
    resident compartments that its colormap does not make transparent.
    """
    import numpy as np

    if tab.surface.viewer.dims.ndisplay == 2 and tab.contour is not None:
        from viewer_harness import contour_loops

        return {owner for owner, _loop in contour_loops(tab.contour)}
    layer = tab.surface.layer
    if not layer.visible:
        return set()
    values = np.unique(np.asarray(layer.data[2]))
    lo, hi = layer.contrast_limits
    alpha = layer.colormap.map((values - lo) / (hi - lo))[:, 3]
    return {round(float(v)) for v, a in zip(values, alpha) if a > 0}


def test_it_opens_sorted_by_glomerulus_one_row_each(tab):
    from lobemap.viewer.panel import NAME_COL

    shown = [tab.table.item(r, NAME_COL).text() for r in range(tab.table.rowCount())]
    keys = [tab.row_at(r).sort_key() for r in range(tab.table.rowCount())]
    assert keys == sorted(keys)
    # D once, for both its sides, then DA1.
    assert shown[:3] == ["D", "DA1", "DA2"], shown[:3]
    assert len(shown) == len(set(shown)) == len(tab.rows)
    assert tab.table.isSortingEnabled()


def test_numbers_sort_naturally():
    """DA10 after DA9, which plain string order gets wrong."""
    from lobemap.viewer.panel import natural_key

    assert natural_key("DA9") < natural_key("DA10")
    assert sorted(["VC10", "VC2", "VC1"], key=natural_key) == \
        ["VC1", "VC2", "VC10"]


def test_a_row_no_longer_means_a_compartment_index(tab):
    """The premise of the whole refactor.

    hemibrain's names happen to arrive alphabetical, so the DEFAULT sort
    is a no-op there and proves nothing. Reverse it to force the case
    every handler now has to survive.
    """
    from qtpy.QtCore import Qt

    from lobemap.viewer.panel import NAME_COL

    tab.table.sortItems(NAME_COL, Qt.DescendingOrder)
    pairs = {r: tab.row_at(r) for r in range(tab.table.rowCount())}
    assert any(r != row.key for r, row in pairs.items()), "sorting changed nothing"
    # Still a bijection: every compartment present exactly once.
    assert sorted(i for row in pairs.values() for i in row.indices) == \
        list(range(tab.surface.meshset.n_compartments))
    # And picking still lands on the right glomerulus.
    tab.highlight(0)
    assert 0 in tab.row_at(tab.table.currentRow()).indices
    tab.table.sortItems(NAME_COL, Qt.AscendingOrder)


def test_highlight_finds_the_row_for_an_index(tab):
    from lobemap.core.names import parse_roi
    from lobemap.viewer.panel import NAME_COL

    index = 7
    tab.highlight(index)
    row = tab.table.currentRow()
    assert index in tab.row_at(row).indices, (
        "highlight jumped to a row number, not to the compartment"
    )
    assert tab.table.item(row, NAME_COL).text() == \
        parse_roi(tab.surface.meshset.names[index])[0]


def test_show_none_then_all_round_trips(tab):
    n = tab.surface.meshset.n_compartments
    _click(tab, "None")
    assert tab.surface.selection == set()
    assert _drawn(tab) == set(), "Show none left glomeruli on screen"
    _click(tab, "All")
    assert tab.surface.selection == set(range(n))
    assert _drawn(tab) == set(range(n)), "Show all did not draw them all"


def test_filtered_only_selects_the_right_compartments(tab):
    """The filter hides rows; the selection must be in index space."""
    tab.filter.setText("DA1")
    _click(tab, "Matches")
    chosen = {tab.surface.meshset.names[i] for i in _drawn(tab)}
    assert chosen, "nothing matched DA1"
    assert all("da1" in n.lower() for n in chosen), chosen
    assert _drawn(tab) == tab.surface.selection
    tab.filter.setText("")


def test_the_fill_column_drives_the_contour_overlay(tab):
    from qtpy.QtCore import Qt

    from lobemap.viewer.panel import FILL_COL

    assert tab.contour is not None
    # D: a glomerulus with both sides in the hemibrain.
    row = 0
    sides = set(tab.row_at(row).indices)
    assert len(sides) == 2 and not sides & tab.contour.filled
    tab.table.item(row, FILL_COL).setCheckState(Qt.Checked)
    assert sides <= tab.contour.filled, "ticking fill did not reach every side"
    tab.table.item(row, FILL_COL).setCheckState(Qt.Unchecked)
    assert not sides & tab.contour.filled


def test_fill_and_label_are_independent(tab):
    from qtpy.QtCore import Qt

    from lobemap.viewer.panel import FILL_COL, LABEL_COL

    row = 5
    sides = set(tab.row_at(row).indices)
    tab.table.item(row, FILL_COL).setCheckState(Qt.Checked)
    assert sides <= tab.contour.filled
    assert not sides & tab.contour.labels
    tab.table.item(row, LABEL_COL).setCheckState(Qt.Checked)
    assert sides <= tab.contour.filled and sides <= tab.contour.labels
    tab.table.item(row, FILL_COL).setCheckState(Qt.Unchecked)


def test_annotation_columns_are_populated(tab):
    from lobemap.viewer.panel import NAME_COL

    rec = _col(tab, "Receptor")
    got = {}
    for r in range(tab.table.rowCount()):
        name = tab.table.item(r, NAME_COL).text()
        got[name] = tab.table.item(r, rec).text()
    hits = [v for v in got.values() if v != "—"]
    assert len(hits) > 30, f"only {len(hits)} rows carry a receptor"
    # Joined on the standard name: the published one here is `DA1(R)`.
    assert got["DA1"] == "Or67d", got["DA1"]


@pytest.fixture
def fafb_tabs(core_data, registry):
    """FAFB has both kinds of layer: one atlas and one neuropil set."""
    import napari

    from lobemap.viewer.app import build_scene
    from lobemap.viewer.panel import CompartmentPanel

    try:
        viewer = napari.Viewer(show=False, ndisplay=3)
    except Exception as exc:                        # pragma: no cover
        pytest.skip(f"no Qt display: {exc}")
    try:
        surfaces, contours = build_scene(viewer, registry, "FAFB14")
        # Bound to a name: an inline `CompartmentPanel(...).tabs` lets the
        # panel be collected, and Qt then deletes the widgets underneath.
        panel = CompartmentPanel(viewer, surfaces, registry=registry,
                                 contours=contours)
        yield panel.tabs
    finally:
        viewer.close()


def _visible_headers(tab):
    return [
        tab.table.horizontalHeaderItem(i).text()
        for i in range(tab.table.columnCount())
        if not tab.table.isColumnHidden(i)
    ]


def test_a_neuropil_layer_is_not_described_as_glomeruli(fafb_tabs):
    """A neuropil has no receptor, and its details are its full name."""
    tab = fafb_tabs["fafb_neuropil"]
    assert tab.is_atlas is False
    assert _visible_headers(tab) == ["Show", "Neuropil", "Label", "Fill"]
    assert tab.detail_fields == ("Sides", "Full name", "Source")


def test_an_atlas_layer_keeps_its_columns(fafb_tabs):
    tab = fafb_tabs["benton2025"]
    assert tab.is_atlas is True
    assert _visible_headers(tab) == ["Show", "Glomerulus", "Label", "Fill", "Receptor"]
    # The rest of the annotation is in the details, in a fixed order.
    assert tab.detail_fields == ("Sides", "Standard name", "Receptor", "Co-receptor",
                                 "Sensory neuron", "Sensillum", "Organ")


def test_fill_and_label_still_work_on_a_neuropil_tab(fafb_tabs):
    """The two columns that are kept must still drive the layer."""
    from qtpy.QtCore import Qt

    from lobemap.viewer.panel import FILL_COL, LABEL_COL

    tab = fafb_tabs["fafb_neuropil"]
    if tab.contour is None:
        pytest.skip("no contour overlay for the neuropil layer")
    sides = set(tab.row_at(2).indices)
    tab.table.item(2, FILL_COL).setCheckState(Qt.Checked)
    assert sides <= tab.contour.filled
    tab.table.item(2, LABEL_COL).setCheckState(Qt.Checked)
    assert sides <= tab.contour.labels


def test_columns_are_sized_to_fit_the_dock(fafb_tabs):
    """Checkboxes a fixed width, the name to its contents, and the
    receptor takes what is left, shortened rather than scrolled."""
    from qtpy.QtWidgets import QHeaderView

    from lobemap.viewer.panel import CHECK_WIDTH, FILL_COL, LABEL_COL, VISIBLE_COL

    assert 36 <= CHECK_WIDTH <= 40
    tab = fafb_tabs["benton2025"]
    header = tab.table.horizontalHeader()
    modes = [header.sectionResizeMode(c) for c in range(tab.table.columnCount())]
    assert modes == [QHeaderView.Fixed, QHeaderView.ResizeToContents,
                     QHeaderView.Fixed, QHeaderView.Fixed, QHeaderView.Stretch]
    for col in (VISIBLE_COL, LABEL_COL, FILL_COL):
        assert tab.table.columnWidth(col) == CHECK_WIDTH
    # The full receptor list is in the tooltip, however short the cell.
    rec = _col(tab, "Receptor")
    cells = [tab.table.item(r, rec) for r in range(tab.table.rowCount())]
    assert all(c.toolTip() == (c.text() if c.text() != "—" else "Not recorded")
               for c in cells)


def test_a_hex_color_spec_does_not_break_filling():
    """The bug: neuropil shells are the string "#9aa0a6", and indexing a
    string gives "#", so filling one raised `could not convert string to
    float`. Only the atlases carry per-compartment arrays."""
    from lobemap.viewer.contours import ContourOverlay

    for spec in ("#9aa0a6", "#ff7f0e", "white", (0.1, 0.2, 0.3, 1.0)):
        r, g, b, a = ContourOverlay._as_rgba(spec)
        assert all(0.0 <= v <= 1.0 for v in (r, g, b, a)), spec


def _fill_alphas(contour) -> set[float]:
    """The alpha of every filled triangle the contour's mesh visual draws."""
    from viewer_harness import assert_renders_loops, rendered_mesh

    assert_renders_loops(contour)
    _vertices, faces, colors = rendered_mesh(contour)
    alphas = {round(float(a), 4) for a in colors[faces[:, 0], 3]} if len(faces) else set()
    return alphas - {1.0}


def test_fill_all_works_on_a_neuropil_layer(session):
    """End to end, in 2D, where the contours actually draw."""

    viewer, sess = session
    tab = sess.panel.tabs["fafb_neuropil"]
    if tab.contour is None:
        pytest.skip("no contour overlay")
    viewer.dims.ndisplay = 2
    _click(tab, "All")
    assert _drawn(tab), "the slice cuts no neuropil"

    _click(tab, "Fill")
    assert tab.contour.filled == set(tab.surface.selection)
    assert _fill_alphas(tab.contour) == {round(tab.contour.FILL_ALPHA, 4)}

    _click(tab, "No fill")
    assert tab.contour.filled == set()
    assert _fill_alphas(tab.contour) == set()


def test_fill_buttons_track_the_checkboxes(session):
    from qtpy.QtCore import Qt

    from lobemap.viewer.panel import FILL_COL

    viewer, sess = session
    viewer.dims.ndisplay = 2
    tab = sess.panel.tabs["benton2025"]
    _click(tab, "Fill")
    states = {tab.table.item(r, FILL_COL).checkState()
              for r in range(tab.table.rowCount())}
    assert states == {Qt.Checked}, "Fill all left boxes unticked"
    _click(tab, "No fill")
    states = {tab.table.item(r, FILL_COL).checkState()
              for r in range(tab.table.rowCount())}
    assert states == {Qt.Unchecked}, "Fill none left boxes ticked"


def test_the_buttons_are_two_aligned_rows(fafb_tabs):
    """A labelled row per kind of action, the buttons lined up in columns."""
    from qtpy.QtWidgets import QGridLayout

    tab = fafb_tabs["benton2025"]
    grid = next(iter(tab.findChildren(QGridLayout)))
    placed: dict[int, dict[int, str]] = {}
    for i in range(grid.count()):
        row, col, _, _ = grid.getItemPosition(i)
        placed.setdefault(row, {})[col] = grid.itemAt(i).widget().text()

    assert [placed[0][c] for c in sorted(placed[0])] == [
        "Show", "All", "None", "Matches", "Invert"
    ]
    # In 3D, which this fixture is, the slice row says when it works.
    assert [placed[1][c] for c in sorted(placed[1])] == [
        "Slice view only", "Names", "No names", "Fill", "No fill"
    ]


def test_show_all_and_show_none_still_drive_visibility(fafb_tabs):
    """Renaming must not have detached them from their slots."""
    from qtpy.QtWidgets import QGridLayout, QPushButton

    tab = fafb_tabs["benton2025"]
    grid = next(iter(tab.findChildren(QGridLayout)))
    by_text = {
        grid.itemAt(i).widget().text(): grid.itemAt(i).widget()
        for i in range(grid.count())
        if isinstance(grid.itemAt(i).widget(), QPushButton)
    }
    n = tab.surface.meshset.n_compartments
    by_text["None"].click()
    assert tab.surface.selection == set()
    by_text["All"].click()
    assert tab.surface.selection == set(range(n))


def _name_cells(tab):
    """Each side's published name -> the name cell of its row."""
    from lobemap.viewer.panel import NAME_COL

    return {side.published: tab.table.item(r, NAME_COL)
            for r in range(tab.table.rowCount()) for side in tab.row_at(r).sides}


def test_a_renamed_glomerulus_is_marked_and_says_why(tab):
    """hemibrain carries the Schlegel rename chain: VC3l -> VC3 and so on.

    The mark is on the atlas's own name, and the standard name is in the
    tooltip and the details: there is no column for it to repeat the name
    in on every other row.
    """
    cells = _name_cells(tab)
    marked = {n: c.text() for n, c in cells.items() if c.text().endswith("*")}
    assert marked == {"VC3l(R)": "VC3l*", "VC3m(R)": "VC3m*", "VC5(R)": "VC5*"}
    assert cells["VC3l(R)"].toolTip() == (
        "This atlas calls it VC3l; its standard name is VC3 (renamed)."
    )
    tab.highlight(tab.surface.meshset.names.index("VC5(R)"))
    assert tab.details["Standard name"].text() == "VM6"


def test_a_bare_name_matching_its_standard_name_is_not_marked(tab):
    """`DA1(R)` and `DA1` are one glomerulus written two ways."""
    cells = _name_cells(tab)
    assert cells["DA1(R)"].text() == "DA1"
    assert cells["DA1(R)"].toolTip() == ""


def test_the_search_reaches_the_annotation_and_nothing_hidden(tab):
    """The name, as published too, and every annotation field; not the side."""
    def shown(needle):
        tab.filter.setText(needle)
        hit = {side.published for r in range(tab.table.rowCount())
               if not tab.table.isRowHidden(r) for side in tab.row_at(r).sides}
        tab.filter.setText("")
        return hit

    assert shown("Or67d") == {"DA1(R)"}, "receptor not searched"
    assert len(shown("Orco")) > 10, "co-receptor not searched"
    assert len(shown("antenna")) > 10, "organ not searched"
    assert "DP1m(R)" in shown("sacIII-d"), "sensillum not searched"
    assert shown("ab9A") == {"D(L)", "D(R)"}, "sensory neuron not searched"
    assert shown("DA1(R)") == {"DA1(R)"}, "the published name not searched"
    assert "VC5(R)" in shown("VM6"), "the standard name not searched"
    assert shown("Right") == set(), "the side is not a search field"
    assert shown("zzzz") == set()


@pytest.fixture
def session(core_data, registry):
    """A full FAFB session, so the display-mode hook is installed."""
    import napari

    from lobemap.viewer.app import load_space

    try:
        viewer = napari.Viewer(show=False, ndisplay=3)
    except Exception as exc:                        # pragma: no cover
        pytest.skip(f"no Qt display: {exc}")
    try:
        yield viewer, load_space(viewer, registry, "FAFB14", fit=False)
    finally:
        viewer.close()


@pytest.mark.parametrize("layer", ["fafb_neuropil", "benton2025"])
def test_showing_in_2d_draws_contours_not_meshes(session, layer):
    """The bug: `Show all` in 2D switched the mesh on under the slice.

    `AtlasSurface.refresh` turns its layer on whenever anything is
    selected, which is right in 3D. The display-mode hook only fires on an
    `ndisplay` change, so nothing put the mesh back.
    """
    viewer, sess = session
    tab = sess.panel.tabs[layer]
    if tab.contour is None:
        pytest.skip("no contour overlay")
    viewer.dims.ndisplay = 2

    _click(tab, "All")
    assert tab.surface.layer.visible is False, "mesh switched on in 2D"
    assert tab.contour.layer.visible is True, "contours left off in 2D"

    _click(tab, "None")
    assert tab.surface.layer.visible is False
    assert tab.contour.layer.visible is False


@pytest.mark.parametrize("layer", ["fafb_neuropil", "benton2025"])
def test_a_single_checkbox_obeys_the_mode_too(session, layer):
    """`set_visible` bypassed `_push`, so fixing the buttons left this."""
    from qtpy.QtCore import Qt

    from lobemap.viewer.panel import VISIBLE_COL

    viewer, sess = session
    tab = sess.panel.tabs[layer]
    if tab.contour is None:
        pytest.skip("no contour overlay")
    viewer.dims.ndisplay = 2
    _click(tab, "None")

    tab.table.item(0, VISIBLE_COL).setCheckState(Qt.Checked)
    assert tab.surface.layer.visible is False, "mesh switched on in 2D"
    assert tab.contour.layer.visible is True


def test_3d_still_shows_the_mesh(session):
    viewer, sess = session
    tab = sess.panel.tabs["benton2025"]
    viewer.dims.ndisplay = 3
    _click(tab, "All")
    assert tab.surface.layer.visible is True
    assert _drawn(tab) == set(range(tab.surface.meshset.n_compartments))
    if tab.contour is not None:
        assert tab.contour.layer.visible is False


# -- which table opens -----------------------------------------------------
#
# Reference geometry is built into the scene before the atlases so that it
# sits underneath them, which once made a neuropil shell the first tab. The
# panel then opened on the one table with no glomeruli behind it.

@pytest.mark.requires_data
@pytest.mark.parametrize("space,expect", [
    ("JRCFIB2018F", "neuprint_hemibrain"),   # three atlases; spaces.toml picks
    ("FAFB14", "benton2025"),                # one atlas, behind fafb_neuropil
])
def test_it_opens_on_the_spaces_primary_atlas(registry, space, expect):
    import napari

    from lobemap.viewer.app import build_scene
    from lobemap.viewer.panel import CompartmentPanel

    try:
        viewer = napari.Viewer(show=False, ndisplay=3)
    except Exception as exc:                        # pragma: no cover
        pytest.skip(f"no Qt display: {exc}")
    try:
        surfaces, contours = build_scene(viewer, registry, space)
        panel = CompartmentPanel(viewer, surfaces, registry=registry,
                                 contours=contours, space=space)
        assert panel.tabText(panel.currentIndex()) == "Glomeruli"
        assert panel.current() == expect
        assert panel.currentWidget().stack.currentWidget() is panel.tabs[expect]
        assert panel.tabs[expect].is_atlas
    finally:
        viewer.close()


@pytest.mark.requires_data
def test_the_open_tab_is_the_atlas_that_is_drawn(registry):
    """The panel and the canvas must agree on which atlas is showing."""
    import napari

    from lobemap.viewer.app import build_scene
    from lobemap.viewer.panel import CompartmentPanel

    try:
        viewer = napari.Viewer(show=False, ndisplay=3)
    except Exception as exc:                        # pragma: no cover
        pytest.skip(f"no Qt display: {exc}")
    try:
        surfaces, contours = build_scene(viewer, registry, "JRCFIB2018F")
        panel = CompartmentPanel(viewer, surfaces, registry=registry,
                                 contours=contours, space="JRCFIB2018F")
        visible = [name for name, s in surfaces.items()
                   if name in registry.atlases and s.layer.visible]
        assert visible == [panel.current()]
    finally:
        viewer.close()


@pytest.mark.requires_data
def test_the_glomeruli_come_before_the_neuropils(registry):
    """Neuropil and brain shells read last, whatever order the scene built,
    and in a tab of their own.

    They are added to the scene FIRST, so without a reordering step the
    panel led with them.
    """
    import napari

    from lobemap.viewer.app import build_scene
    from lobemap.viewer.panel import CompartmentPanel

    try:
        viewer = napari.Viewer(show=False, ndisplay=3)
    except Exception as exc:                        # pragma: no cover
        pytest.skip(f"no Qt display: {exc}")
    try:
        surfaces, contours = build_scene(viewer, registry, "JRCFIB2018F")
        panel = CompartmentPanel(viewer, surfaces, registry=registry,
                                 contours=contours, space="JRCFIB2018F")
        assert [panel.tabText(i) for i in range(panel.count())] == ["Glomeruli", "Neuropils"]
        for i, atlas in ((0, True), (1, False)):
            page = panel.widget(i)
            assert {panel.tabs[name].is_atlas for name in page.names} == {atlas}
        assert len(panel.widget(1).names) == 1, "this space has reference geometry"
    finally:
        viewer.close()
