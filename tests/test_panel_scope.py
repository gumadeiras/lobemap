"""Which panel controls work where, and which rows each one acts on.

Label and Fill draw on the 2D slice only, so their cells and their header
checkboxes are disabled in 3D; each header checkbox names its rows. Where
the panel sits is `test_view_dock`'s.
"""

from __future__ import annotations

import pytest
from viewer_harness import click_header, launched, pump, session, ticked

pytestmark = pytest.mark.requires_data
pytest.importorskip("napari")


def _enabled(item) -> bool:
    from qtpy.QtCore import Qt

    return bool(item.flags() & Qt.ItemIsEnabled)


# -- 2D-only controls ------------------------------------------------------


def test_label_and_fill_are_disabled_in_3d_only(monkeypatch):
    """Their cells and header checkboxes; in 3D a click on the header
    changes no row and draws nothing, and the tooltip says when it works."""
    from lobemap.viewer.panel import FILL_COL, LABEL_COL, VISIBLE_COL

    with launched(monkeypatch, "view", "FAFB14") as (code, viewer):
        sess = session(viewer)
        for ndisplay, usable in ((3, False), (2, True), (3, False)):
            viewer.dims.ndisplay = ndisplay
            pump()
            for name, tab in sess.panel.tabs.items():
                for col in (LABEL_COL, FILL_COL):
                    cells = {_enabled(tab.table.item(r, col))
                             for r in range(tab.table.rowCount())}
                    assert cells == {usable}, (name, col, ndisplay)
                    assert tab.header.is_enabled(col) is usable, (name, col, ndisplay)
                    tip = tab.table.horizontalHeaderItem(col).toolTip()
                    assert tip.endswith("Slice view only."), tip
                    if not usable:
                        before = ticked(tab, col)
                        click_header(tab, col)
                        assert ticked(tab, col) == before, (name, col)
                        if tab.contour is not None:
                            assert not tab.contour.labels and not tab.contour.filled
                # The rows themselves work in both modes.
                assert tab.header.is_enabled(VISIBLE_COL)


# -- the header scopes -----------------------------------------------------


def test_each_header_checkbox_says_which_rows_it_acts_on(monkeypatch):
    from lobemap.viewer.panel import CHECK_COLUMNS

    with launched(monkeypatch, "view", "JRCFIB2018F") as (code, viewer):
        for tab in session(viewer).panel.tabs.values():
            kind = "glomerulus" if tab.is_atlas else "neuropil"
            for col in CHECK_COLUMNS:
                tip = tab.table.horizontalHeaderItem(col).toolTip()
                assert f"every listed {kind}" in tip, (col, tip)
