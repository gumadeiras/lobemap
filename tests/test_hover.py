"""Hovering names the glomerulus under the cursor, from the first frame.

It names it in the status bar and selects nothing; a click selects its row.

The mouse moves go through napari's own canvas handler, so which layer is
active -- the reason hovering did nothing on first open -- decides the
outcome exactly as it does for a user. One compartment is shown, so the
only thing under the cursor is the one expected.
"""

from __future__ import annotations

import numpy as np
import pytest
from viewer_harness import (
    SPACES,
    canvas_position,
    clear_all,
    click,
    contour_loops,
    hover,
    launched,
    pump,
    session,
)

pytestmark = pytest.mark.requires_data
pytest.importorskip("napari")


def _inside_contour(overlay, owner: int) -> np.ndarray:
    """A world point inside the largest drawn loop of one compartment."""
    paths = [loop for drawn, loop in contour_loops(overlay) if drawn == owner]
    assert paths, "nothing drawn to hover over"
    path = max(paths, key=len)
    return path.mean(axis=0)


@pytest.mark.parametrize("space", SPACES)
def test_hover_names_the_glomerulus_in_3d_and_2d(monkeypatch, space):
    from qtpy.QtCore import Qt

    from lobemap.viewer.panel import VISIBLE_COL

    with launched(monkeypatch, "view", space) as (code, viewer):
        assert code == 0
        sess = session(viewer)
        primary = sess.registry.primary_atlas(space).id
        tab = sess.panel.tabs[primary]
        surface = tab.surface
        index = surface.meshset.n_compartments // 2
        name = surface.meshset.names[index]
        # Through the table: nothing, then one row ticked, every side of it.
        clear_all(tab)
        tab.table.item(tab.table_row(index), VISIBLE_COL).setCheckState(Qt.Checked)
        pump(300)
        # The row's name and side, and whose it is, in words.
        from lobemap.core.names import parse_roi

        bare, suffix = parse_roi(name)
        side = sess.registry.atlases[primary].compartments[index].side or suffix
        title = sess.registry.asset_of(primary).title
        want = f"{bare} ({ {'L': 'left', 'R': 'right'}[side]}) — {title}"

        # First open, 3D: nothing selected in the layer list by us. Hover
        # names it and selects nothing; a click selects its row.
        assert hover(viewer, surface.meshset.centroid(index)) == want
        assert tab.selected() is None
        assert click(viewer, surface.meshset.centroid(index)) == want
        assert index in tab.selected().indices

        viewer.dims.ndisplay = 2
        pump()
        assert hover(viewer, _inside_contour(tab.contour, index)) == want

        viewer.dims.ndisplay = 3
        pump()
        assert hover(viewer, surface.meshset.centroid(index)) == want


def test_hover_over_nothing_says_nothing(monkeypatch):
    with launched(monkeypatch, "view", "GRABE", "--ndisplay", "2") as (code, viewer):
        far = np.asarray(viewer.dims.point, float)
        far[list(viewer.dims.displayed)] = -1e4
        assert hover(viewer, far) == ""


def test_the_3d_pick_agrees_with_napari_and_keeps_moves_cheap(monkeypatch):
    """napari's own pick tests all 298k Benton triangles, ~40 ms a move; a
    whole move here, napari's handling and ours, costs a fraction of that.
    Measured against napari's pick in the same run, so a slower machine
    moves both."""
    import statistics
    import time

    from vispy.app.canvas import MouseEvent

    with launched(monkeypatch, "view", "FAFB14") as (code, viewer):
        surface = session(viewer).surfaces["benton2025"]
        canvas = viewer.window._qt_viewer.canvas
        x, y = canvas_position(viewer, surface.meshset.centroid(10))
        times, theirs_times, hits = [], [], 0
        for dx in range(-40, 41, 8):
            for dy in (-20, 0, 20):
                event = MouseEvent(type="mouse_move", pos=(x + dx, y + dy),
                                   modifiers=(), buttons=[])
                start = time.perf_counter()
                canvas._on_mouse_move(event)
                times.append((time.perf_counter() - start) * 1000)
                position = viewer.cursor.position
                direction = viewer.cursor._view_direction
                start = time.perf_counter()
                theirs = surface.layer.get_value(position, view_direction=direction,
                                                 dims_displayed=[0, 1, 2], world=True)
                theirs_times.append((time.perf_counter() - start) * 1000)
                theirs = theirs[0] if isinstance(theirs, tuple) else theirs
                theirs = None if theirs is None else round(float(theirs))
                assert surface.pick(position, direction, [0, 1, 2]) == theirs
                hits += theirs is not None
        assert hits > 10, "the grid missed the atlas"
        assert statistics.median(times) < statistics.median(theirs_times) / 2, (
            sorted(times), sorted(theirs_times))


def test_a_drag_does_not_pick(monkeypatch):
    from vispy.app.canvas import MouseEvent

    with launched(monkeypatch, "view", "GRABE") as (code, viewer):
        surface = session(viewer).surfaces["grabe2015"]
        viewer.status = ""
        event = MouseEvent(type="mouse_move", modifiers=(), buttons=[1],
                           pos=canvas_position(viewer, surface.meshset.centroid(0)))
        viewer.window._qt_viewer.canvas._on_mouse_move(event)
        pump()
        assert viewer.status == ""


def _cursor(viewer):
    """Real Qt events for the cursor: entering the window, which starts
    napari's status thread as it does for a user, then the canvas, which
    makes napari reckon the status for the cursor; `move(world)` moves it
    over a world point. napari reckons in its thread, a moment after the
    move: `rest` waits past that."""
    from qtpy.QtCore import QEvent, QPointF, Qt
    from qtpy.QtGui import QEnterEvent, QMouseEvent
    from qtpy.QtWidgets import QApplication

    window = viewer.window._qt_window
    native = viewer.window._qt_viewer.canvas.native

    def enter(widget) -> None:
        here = QPointF(1.0, 1.0)
        QApplication.sendEvent(widget, QEnterEvent(here, here, QPointF(widget.mapToGlobal(
            here.toPoint()))))

    def move(world) -> None:
        enter(native)
        here = QPointF(*canvas_position(viewer, world))
        QApplication.sendEvent(native, QMouseEvent(
            QEvent.Type.MouseMove, here, here, QPointF(native.mapToGlobal(here.toPoint())),
            Qt.MouseButton.NoButton, Qt.MouseButton.NoButton, Qt.KeyboardModifier.NoModifier))

    def rest() -> str:
        pump(600)
        return str(viewer.status)

    enter(window)
    return window.status_thread, move, rest


@pytest.mark.parametrize("space", SPACES)
def test_the_name_stays_once_the_cursor_rests(monkeypatch, space):
    """napari's own status for the cursor, reckoned in its thread a moment
    after each move -- the active layer's name and the value under the
    cursor -- replaced the name: "neuPrint · 3D [306, 174, 198]: 7, 23185".
    With the cursor at rest over a compartment, in 3D and in Slice view and
    whichever layer is active, the name is what stays."""
    with launched(monkeypatch, "view", space) as (code, viewer):
        assert code == 0
        sess = session(viewer)
        tab = sess.panel.tabs[sess.registry.primary_atlas(space).id]
        surface = tab.surface
        index = surface.meshset.n_compartments // 2
        clear_all(tab)
        from qtpy.QtCore import Qt

        from lobemap.viewer.panel import VISIBLE_COL

        tab.table.item(tab.table_row(index), VISIBLE_COL).setCheckState(Qt.Checked)
        pump(300)
        want = tab.describe(index)
        thread, move, rest = _cursor(viewer)
        try:
            assert thread.isRunning()
            layers = [surface.layer, tab.contour.layer, *sess.images]
            for ndisplay, world in ((3, surface.meshset.centroid(index)),
                                    (2, None), (3, surface.meshset.centroid(index))):
                viewer.dims.ndisplay = ndisplay
                pump(300)
                if world is None:
                    world = _inside_contour(tab.contour, index)
                for layer in layers:
                    viewer.layers.selection.active = layer
                    move(world)
                    assert rest() == want, (ndisplay, layer.name)
                # Away from it, napari's own words, as before.
                far = np.asarray(world, float) + 1e4
                move(far)
                assert rest() != want, ndisplay
        finally:
            thread.terminate()
            thread.wait()


def test_a_switch_never_shows_a_numbered_layer_name(monkeypatch):
    """The next brain is built beside the open one, so napari numbers the
    names both have, "neuPrint · 3D [1]", until the open one is gone; its
    status thread kept reckoning the status bar's words from them meanwhile.
    With the thread running and the cursor over the canvas, nothing napari
    reckons during the switch, nor anything the status bar shows after it,
    carries a numbered name."""
    import re

    numbered = re.compile(r" \[\d+\]")
    with launched(monkeypatch, "view", "JRCFIB2018F") as (code, viewer):
        sess = session(viewer)
        tab = sess.panel.tabs[sess.registry.primary_atlas("JRCFIB2018F").id]
        thread, move, rest = _cursor(viewer)
        try:
            move(np.asarray(tab.surface.meshset.centroid(0), float) + 1e4)
            rest()
            shown, reckoned = [], []
            viewer.events.status.connect(lambda event: shown.append(str(event.value)))

            def reckon(event=None) -> None:
                # What napari's thread would reckon at this moment of the build.
                reckoned.append(viewer._calc_status_from_cursor())
                reckoned.append([layer.name for layer in viewer.layers])

            viewer.layers.events.inserted.connect(reckon)
            from viewer_harness import switch_to

            switch_to(viewer, "JRCFIB2022M")
            viewer.layers.events.inserted.disconnect(reckon)
            assert any(numbered.search(name) for names in reckoned[1::2] for name in names), (
                "nothing was numbered: the switch no longer builds beside the open brain")
            assert all(status is None for status in reckoned[0::2]), reckoned[0::2]
            rest()
            move(np.asarray(viewer.scene.camera.center, float))
            shown.append(rest())
            assert not any(numbered.search(text) for text in shown), shown
            assert not any(numbered.search(layer.name) for layer in viewer.layers)
        finally:
            thread.terminate()
            thread.wait()
