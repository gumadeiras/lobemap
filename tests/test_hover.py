"""Hovering names the glomerulus under the cursor, from the first frame.

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
    contour_loops,
    hover,
    launched,
    pump,
    session,
)

pytestmark = pytest.mark.requires_data
pytest.importorskip("napari")


def _inside_contour(overlay) -> np.ndarray:
    """A world point inside the largest drawn loop of the overlay."""
    paths = [loop for _owner, loop in contour_loops(overlay)]
    assert paths, "nothing drawn to hover over"
    path = max(paths, key=len)
    return path.mean(axis=0)


@pytest.mark.parametrize("space", SPACES)
def test_hover_names_the_glomerulus_in_3d_and_2d(monkeypatch, space):
    from qtpy.QtCore import Qt
    from qtpy.QtWidgets import QPushButton

    from lobemap.viewer.panel import VISIBLE_COL

    with launched(monkeypatch, "view", space) as (code, viewer):
        assert code == 0
        sess = session(viewer)
        primary = sess.registry.primary_atlas(space).id
        tab = sess.panel.tabs[primary]
        surface = tab.surface
        index = surface.meshset.n_compartments // 2
        name = surface.meshset.names[index]
        # Through the table: nothing, then one row ticked.
        next(b for b in tab.findChildren(QPushButton) if b.text() == "Show none").click()
        tab.table.item(tab._row_of(index), VISIBLE_COL).setCheckState(Qt.Checked)
        pump(300)
        want = f"{primary}: {name}"

        # First open, 3D: nothing selected in the layer list by us.
        assert hover(viewer, surface.meshset.centroid(index)) == want
        assert tab._index_of(tab.table.currentRow()) == index

        viewer.dims.ndisplay = 2
        pump()
        assert hover(viewer, _inside_contour(tab.contour)) == want

        viewer.dims.ndisplay = 3
        pump()
        assert hover(viewer, surface.meshset.centroid(index)) == want


def test_hover_over_nothing_says_nothing(monkeypatch):
    with launched(monkeypatch, "view", "GRABE", "--ndisplay", "2") as (code, viewer):
        far = np.asarray(viewer.dims.point, float)
        far[list(viewer.dims.displayed)] = -1e4
        assert hover(viewer, far) == ""


def test_the_3d_pick_agrees_with_napari_and_keeps_moves_cheap(monkeypatch):
    """napari's own pick tests all 298k Benton triangles, ~40 ms a move."""
    import statistics
    import time

    from vispy.app.canvas import MouseEvent

    with launched(monkeypatch, "view", "FAFB14") as (code, viewer):
        surface = session(viewer).surfaces["benton2025"]
        canvas = viewer.window._qt_viewer.canvas
        x, y = canvas_position(viewer, surface.meshset.centroid(10))
        times, hits = [], 0
        for dx in range(-40, 41, 8):
            for dy in (-20, 0, 20):
                event = MouseEvent(type="mouse_move", pos=(x + dx, y + dy),
                                   modifiers=(), buttons=[])
                start = time.perf_counter()
                canvas._on_mouse_move(event)
                times.append((time.perf_counter() - start) * 1000)
                position = viewer.cursor.position
                direction = viewer.cursor._view_direction
                theirs = surface.layer.get_value(position, view_direction=direction,
                                                 dims_displayed=[0, 1, 2], world=True)
                theirs = theirs[0] if isinstance(theirs, tuple) else theirs
                theirs = None if theirs is None else round(float(theirs))
                assert surface.pick(position, direction, [0, 1, 2]) == theirs
                hits += theirs is not None
        assert hits > 10, "the grid missed the atlas"
        assert statistics.median(times) < 10.0, sorted(times)


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
