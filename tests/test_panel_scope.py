"""Which panel controls work where, and which rows each one acts on.

Label and Fill draw on the 2D slice only, so they are disabled in 3D; the
space picker heads the right column; each bulk button names its rows.
"""

from __future__ import annotations

import pytest
from viewer_harness import launched, pump, session, switch_to

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


# -- the dock order and the button scopes ----------------------------------


def _dock_tops(viewer):
    from qtpy.QtCore import Qt
    from qtpy.QtWidgets import QDockWidget

    window = viewer.window._qt_window
    # Laid out for real, but never put on screen.
    window.setAttribute(Qt.WA_DontShowOnScreen, True)
    window.resize(1400, 900)
    window.show()
    pump(100)
    tops = {d.windowTitle(): d.geometry().top()
            for d in window.findChildren(QDockWidget) if d.isVisible()}
    return tops["Space"], tops["Compartments"]


def test_the_space_picker_sits_above_the_compartments(monkeypatch):
    with launched(monkeypatch, "view", "GRABE") as (code, viewer):
        space, panel = _dock_tops(viewer)
        assert space < panel, (space, panel)
        switch_to(viewer, "FAFB14")
        space, panel = _dock_tops(viewer)
        assert space < panel, "a switch put the picker back below"


def test_each_bulk_button_says_which_rows_it_acts_on(monkeypatch):
    with launched(monkeypatch, "view", "JRCFIB2018F") as (code, viewer):
        for tab in session(viewer).panel.tabs.values():
            kind = "glomer" if tab.is_atlas else "neuropil"
            for label, button in _buttons(tab).items():
                if label == "Open in Virtual Fly Brain":
                    continue
                assert kind in button.toolTip(), (label, button.toolTip())
            assert tab.on_slice.text() == "On slice\n(Slice view only)"
