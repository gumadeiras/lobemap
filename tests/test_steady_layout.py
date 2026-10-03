"""Hovering moves nothing; a click selects; the details hold their size.

The window is laid out for real at 1440 x 900, never put on screen. The
cursor moves over many compartments, in 3D and in 2D, through napari's own
mouse-move path, and every widget of every dock must be where it was and as
large as it was, with the same tab open, the same rows selected and every
table scrolled as it was. Only the status bar's words change. A click that
does not drag selects; one that drags does not.
"""

from __future__ import annotations

import numpy as np
import pytest
from viewer_harness import SPACES, click, contour_loops, hover, launched, pump, session

pytestmark = pytest.mark.requires_data
pytest.importorskip("napari")


def _show(viewer) -> None:
    from qtpy.QtCore import Qt

    window = viewer.window._qt_window
    window.setAttribute(Qt.WidgetAttribute.WA_DontShowOnScreen, True)
    window.resize(1440, 900)
    window.show()
    pump(300)


def _layout(viewer, sess) -> dict:
    """Where every visible dock widget is, and what the panel has chosen."""
    from qtpy.QtWidgets import QAbstractScrollArea, QDockWidget, QWidget

    window = viewer.window._qt_window
    out = {}
    for dock in window.findChildren(QDockWidget):
        title = dock.windowTitle()
        out[("dock", title)] = dock.geometry().getRect()
        # Keyed by place in the dock: Qt hands back new Python wrappers.
        for i, widget in enumerate(dock.findChildren(QWidget)):
            corner = widget.mapTo(window, widget.rect().topLeft())
            out[("widget", title, i, type(widget).__name__)] = (
                widget.isVisible(), corner.x(), corner.y(), widget.width(), widget.height())
        for i, area in enumerate(dock.findChildren(QAbstractScrollArea)):
            out[("scroll", title, i)] = (area.horizontalScrollBar().value(),
                                         area.verticalScrollBar().value())
    panel = sess.panel
    out["tab"] = panel.currentIndex()
    for name, tab in panel.tabs.items():
        model = tab.table.selectionModel()
        out[("selected", name)] = sorted(i.row() for i in model.selectedRows())
        out[("current", name)] = tab.table.currentRow()
        out[("details", name)] = [label.text() for label in tab.details.values()]
    return out


def _targets(viewer, sess) -> list[np.ndarray]:
    """World points over drawn compartments of every part: centroids in 3D,
    inside the loops on the plane in 2D."""
    points = []
    for name, surface in sess.surfaces.items():
        if viewer.dims.ndisplay == 3:
            shown = sorted(surface.selection)
            points += [surface.meshset.centroid(i) for i in shown[:: max(1, len(shown) // 12)]]
        else:
            layer = sess.contours[name].layer
            loops = [loop for _owner, loop in contour_loops(sess.contours[name])]
            points += [layer.data_to_world(loop.mean(axis=0))
                       for loop in loops[:: max(1, len(loops) // 12)]]
    return points


@pytest.mark.parametrize("space", SPACES)
def test_hovering_changes_only_the_status_bar(monkeypatch, space):
    with launched(monkeypatch, "view", space) as (code, viewer):
        assert code == 0
        _show(viewer)
        sess = session(viewer)
        # Every part shown, each tab with a row selected and scrolled to the
        # end, and the primary atlas's tab open.
        for name in list(sess.parts):
            tab = sess.panel.tab(name)
            tab.select(range(tab.table.rowCount()))
            tab.table.selectRow(tab.table.rowCount() - 1)
            tab.table.scrollToBottom()
        sess.panel.setCurrentWidget(sess.panel.tabs[sess.registry.primary_atlas(space).id])
        pump(400)
        for ndisplay in (3, 2):
            viewer.dims.ndisplay = ndisplay
            pump(300)
            before = _layout(viewer, sess)
            said = set()
            for point in _targets(viewer, sess):
                said.add(hover(viewer, point))
                assert _layout(viewer, sess) == before, (space, ndisplay, point)
            # The cursor was over something every time, and named it.
            assert "" not in said and len(said) > 10, (space, ndisplay, sorted(said)[:5])


def test_a_click_selects_and_a_drag_does_not(monkeypatch):
    from viewer_harness import contour_loops as loops_of

    with launched(monkeypatch, "view", "JRCFIB2018F") as (code, viewer):
        assert code == 0
        _show(viewer)
        sess = session(viewer)
        neuropils = sess.panel.tab("neuprint_hemibrain_neuropil")
        neuropils.select([])
        primary = sess.panel.tabs["neuprint_hemibrain"]
        sess.panel.setCurrentWidget(neuropils)
        pump(300)
        index = primary.surface.meshset.n_compartments // 3
        primary.select([index])
        pump(300)
        target = primary.surface.meshset.centroid(index)
        for ndisplay in (3, 2):
            viewer.dims.ndisplay = ndisplay
            pump(300)
            if ndisplay == 2:
                viewer.dims.set_point(int(viewer.dims.order[0]), float(target[viewer.dims.order[0]]))
                pump(300)
                target = max((loop for _o, loop in loops_of(sess.contours["neuprint_hemibrain"])),
                             key=len).mean(axis=0)
            primary.table.clearSelection()
            sess.panel.setCurrentWidget(neuropils)
            pump()
            before = _layout(viewer, sess)
            # A drag turns or pans the view and selects nothing.
            click(viewer, target, drag=40)
            assert sess.panel.currentWidget() is neuropils
            assert primary.selected() is None
            assert _layout(viewer, sess) == before
            # A click opens the row's tab, selects it and fills the details.
            said = click(viewer, target)
            row = primary.selected()
            assert sess.panel.currentWidget() is primary
            assert row is not None and row.index == index, ndisplay
            assert said == primary.describe(index)
            assert primary.detail_title.text().startswith(row.name)
            viewer.dims.ndisplay = 3
            pump()


@pytest.mark.parametrize("space", SPACES)
def test_the_details_hold_their_size_and_show_every_value_in_full(monkeypatch, space):
    with launched(monkeypatch, "view", space) as (code, viewer):
        assert code == 0
        _show(viewer)
        sess = session(viewer)
        for name in list(sess.parts):
            tab = sess.panel.tab(name)
            sess.panel.setCurrentWidget(tab)
            pump(100)
            box = tab.detail_title.parentWidget()
            size = box.size()
            table = tab.table.geometry()
            for row in range(tab.table.rowCount()):
                tab.table.selectRow(row)
                assert box.size() == size and tab.table.geometry() == table, (name, row)
                for field, label in tab.details.items():
                    # Wrapped, never cut short: the text fits the line it has.
                    assert label.heightForWidth(label.width()) <= label.height(), (
                        name, field, label.text())
