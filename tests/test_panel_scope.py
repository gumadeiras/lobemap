"""Which panel controls work where, and which rows each one acts on.

Label and Fill draw on the 2D slice only, so they are disabled in 3D; each
bulk button names its rows. Where the panel sits is `test_view_dock`'s.
"""

from __future__ import annotations

import pytest
from viewer_harness import launched, pump, session

pytestmark = pytest.mark.requires_data
pytest.importorskip("napari")


def _buttons(tab):
    from qtpy.QtWidgets import QPushButton

    return {b.text(): b for b in tab.findChildren(QPushButton)}


def _enabled(item) -> bool:
    from qtpy.QtCore import Qt

    return bool(item.flags() & Qt.ItemIsEnabled)


# -- 2D-only controls ------------------------------------------------------


def test_label_and_fill_are_disabled_in_3d_only(monkeypatch):
    from lobemap.viewer.panel import FILL_COL, LABEL_COL

    with launched(monkeypatch, "view", "FAFB14") as (code, viewer):
        sess = session(viewer)
        for ndisplay, usable in ((3, False), (2, True), (3, False)):
            viewer.dims.ndisplay = ndisplay
            pump()
            for name, tab in sess.panel.tabs.items():
                buttons = _buttons(tab)
                for label in ("Names", "No names", "Fill", "No fill"):
                    assert buttons[label].isEnabled() is usable, (name, label, ndisplay)
                for col in (LABEL_COL, FILL_COL):
                    cells = {_enabled(tab.table.item(r, col))
                             for r in range(tab.table.rowCount())}
                    assert cells == {usable}, (name, col, ndisplay)
                # The rows themselves work in both modes.
                assert buttons["All"].isEnabled()


# -- the button scopes -----------------------------------------------------


def test_each_bulk_button_says_which_rows_it_acts_on(monkeypatch):
    with launched(monkeypatch, "view", "JRCFIB2018F") as (code, viewer):
        for tab in session(viewer).panel.tabs.values():
            kind = "glomer" if tab.is_atlas else "neuropil"
            for label, button in _buttons(tab).items():
                if label == "Open in Virtual Fly Brain":
                    continue
                assert kind in button.toolTip(), (label, button.toolTip())
            assert tab.on_slice.text() == "On slice\n(Slice view only)"
