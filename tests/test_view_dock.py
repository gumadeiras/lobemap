"""The View dock and napari's own window, as lobemap lays them out.

The layout is measured on a window laid out for real at 1440 x 900: the
View dock tabbed with napari's layer settings above the layer list on the
left, the compartment panel alone on the right, and the canvas between.
The controls are checked by what they do to the viewer, and the outline
layers by napari's own layer state, not by any widget's text.
"""

from __future__ import annotations

import contextlib
import re
from itertools import pairwise

import numpy as np
import pytest
from viewer_harness import (
    SPACES,
    every_index,
    launched,
    pump,
    session,
    switch_to,
    switcher,
)

from lobemap.viewer.chrome import LEFT_WIDTH, RIGHT_WIDTH

pytestmark = pytest.mark.requires_data
pytest.importorskip("napari")

TITLES = {
    "FAFB14": "FAFB (female, EM)",
    "JRCFIB2018F": "Hemibrain (female, EM)",
    "JRCFIB2022M": "Male CNS (EM)",
    "GRABE": "Grabe 2015 (live, light microscopy)",
}
PANEL = "Glomeruli and neuropils"
#: The narrowest canvas the layout may leave at 1440 px. The left column
#: can be no narrower than napari's layer settings, whose colormap menus
#: list every colormap a session has registered. Named after their layers,
#: lobemap's made the column 416 px after a few brains, and the canvas 558.
MIN_CANVAS = 560


def _show(viewer, width: int = 1440, height: int = 900):
    """Lay the window out for real, at this size, without putting it on screen."""
    from qtpy.QtCore import Qt

    window = viewer.window._qt_window
    window.setAttribute(Qt.WidgetAttribute.WA_DontShowOnScreen, True)
    window.resize(width, height)
    window.show()
    pump(300)
    return window


def _dock(window, title: str):
    from qtpy.QtWidgets import QDockWidget

    found = [d for d in window.findChildren(QDockWidget) if d.windowTitle() == title]
    assert len(found) == 1, (title, found)
    return found[0]


def _tabs(window) -> list[tuple[list[str], int]]:
    from qtpy.QtWidgets import QTabBar

    return [([bar.tabText(i) for i in range(bar.count())], bar.currentIndex())
            for bar in window.findChildren(QTabBar) if bar.isVisible()]


def _assert_layout(viewer) -> None:
    """The window matches the approved map, and nothing scrolls sideways."""
    from qtpy.QtCore import Qt
    from qtpy.QtWidgets import QAbstractScrollArea, QDockWidget, QPushButton

    window = viewer.window._qt_window
    qt_viewer = viewer.window._qt_viewer
    view, panel = _dock(window, "View"), _dock(window, PANEL)
    settings, layers = _dock(window, "Layer settings"), _dock(window, "Layers")
    canvas = qt_viewer.canvas.native
    left = canvas.mapTo(window, canvas.rect().topLeft()).x()
    right = left + canvas.width()

    assert window.width() == 1440, window.width()
    assert canvas.width() >= MIN_CANVAS, canvas.width()
    # The columns as laid out: the panel at its width, the left one as narrow
    # as its docks allow.
    assert panel.width() == RIGHT_WIDTH, panel.width()
    floor = max(dock.minimumSizeHint().width() for dock in (view, settings, layers))
    assert view.width() == max(LEFT_WIDTH, floor), (view.width(), floor)
    # Left: the View tab, shown, ahead of the layer settings, above the list.
    assert settings in window.tabifiedDockWidgets(view)
    assert (["View", "Layer settings"], 0) in _tabs(window), _tabs(window)
    for dock in (view, layers):
        assert window.dockWidgetArea(dock) == Qt.DockWidgetArea.LeftDockWidgetArea
        assert dock.geometry().right() < left, (dock.windowTitle(), dock.geometry())
    assert layers.y() > view.y() + view.height() - 1
    # Right: the panel alone, at full height.
    right_docks = [d for d in window.findChildren(QDockWidget) if d.isVisible()
                   and window.dockWidgetArea(d) == Qt.DockWidgetArea.RightDockWidgetArea]
    assert right_docks == [panel], [d.windowTitle() for d in right_docks]
    assert panel.x() > right
    assert panel.height() >= canvas.height(), (panel.height(), canvas.height())
    # Every brain's title fits the Brain menu's text field, cut short in none.
    from qtpy.QtWidgets import QStyle, QStyleOptionComboBox

    combo = switcher(viewer).combo
    option = QStyleOptionComboBox()
    combo.initStyleOption(option)
    field = combo.style().subControlRect(QStyle.ComplexControl.CC_ComboBox, option,
                                         QStyle.SubControl.SC_ComboBoxEditField, combo)
    for i in range(combo.count()):
        title = combo.itemText(i)
        assert combo.fontMetrics().horizontalAdvance(title) <= field.width(), (
            title, field.width())
    # Nothing in the left column scrolls sideways.
    for dock in (view, settings, layers):
        for area in dock.findChildren(QAbstractScrollArea):
            assert not area.horizontalScrollBar().isVisible(), (dock.windowTitle(), area)
    # No dock can be closed for good; lobemap's come back from the Window menu.
    for dock in window.findChildren(QDockWidget):
        assert not dock.findChildren(QPushButton, "QTitleBarCloseButton"), dock.windowTitle()
    menu = viewer.window.window_menu.actions()
    for dock in (view, panel):
        assert dock.toggleViewAction() in menu, dock.windowTitle()


@pytest.mark.parametrize("space", SPACES)
def test_the_window_is_laid_out_as_the_map(monkeypatch, space):
    with launched(monkeypatch, "view", space) as (code, viewer):
        assert code == 0
        _show(viewer)
        for ndisplay in (3, 2):
            viewer.dims.ndisplay = ndisplay
            pump(200)
            _assert_layout(viewer)
        assert viewer.title == f"lobemap — {TITLES[space]}"


def test_a_switch_keeps_the_layout_and_a_hidden_dock_comes_back(monkeypatch):
    with launched(monkeypatch, "view", "GRABE") as (code, viewer):
        assert code == 0
        window = _show(viewer)
        switch_to(viewer, "FAFB14")
        pump(300)
        _assert_layout(viewer)
        assert viewer.title == f"lobemap — {TITLES['FAFB14']}"
        for title in ("View", PANEL):
            dock = _dock(window, title)
            dock.close()
            pump()
            assert not dock.isVisible()
            dock.toggleViewAction().trigger()
            pump()
            assert dock.isVisible(), title


def test_the_view_controls_drive_the_viewer(monkeypatch):
    """3D and Slice, Fit to window and Sections do what napari's buttons do."""
    from qtpy.QtCore import Qt

    with launched(monkeypatch, "view", "JRCFIB2018F") as (code, viewer):
        assert code == 0
        window = _show(viewer)
        sw, sess = switcher(viewer), session(viewer)
        camera = viewer.scene.camera

        def mode_shown(three_d: bool) -> None:
            assert sw.three_d.isChecked() is three_d
            assert sw.slice_view.isChecked() is not three_d
            # Sections stays in view, disabled in 3D, and says why.
            assert sw.slice.isVisible() and sw.slice.isEnabled() is not three_d
            assert sw.slice_note.isVisible() is three_d
            assert sw.slice_note.text() == "Slice view only"
            assert sw.legend.isVisible() is three_d

        mode_shown(True)
        sw.slice_view.click()
        pump()
        assert viewer.dims.ndisplay == 2
        mode_shown(False)
        # Sections pick the slice axis.
        sw.slice.setCurrentIndex(sw.slice.findText("Sagittal", Qt.MatchFlag.MatchStartsWith))
        pump()
        assert int(viewer.dims.order[0]) == sess.slice_axis == int(sw.slice.currentData()) == 0
        # napari's own shortcut, still live, keeps the buttons in step.
        viewer.dims.ndisplay = 3
        pump()
        mode_shown(True)
        sw.three_d.click()
        assert viewer.dims.ndisplay == 3

        # Fit to window gives the camera napari's Home button gave, in both modes.
        for ndisplay in (3, 2):
            viewer.dims.ndisplay = ndisplay
            pump()
            homes = []
            for press in (sw.home.click,
                          viewer.window._qt_viewer.viewerButtons.resetViewButton.click):
                camera.zoom = camera.zoom * 1.7
                if ndisplay == 3:
                    camera.angles = (17.0, 42.0, -63.0)
                press()
                pump()
                homes.append((tuple(camera.center), camera.zoom, tuple(camera.angles)))
            (center, zoom, angles), (center2, zoom2, angles2) = homes
            assert center == pytest.approx(center2) and zoom == pytest.approx(zoom2)
            assert angles == pytest.approx(angles2), homes

        # napari's viewer and layer buttons are back, around the layer list;
        # `test_napari_buttons` drives them.
        qt_viewer = viewer.window._qt_viewer
        layers = _dock(window, "Layers")
        for row in (qt_viewer.viewerButtons, qt_viewer.layerButtons):
            assert row.isVisible() and layers.isAncestorOf(row)


def _rows(form) -> list[tuple[int, int, bool]]:
    """(top, bottom, is a gap) of each row of a form, as laid out."""
    from qtpy.QtWidgets import QFormLayout

    roles = (QFormLayout.ItemRole.LabelRole, QFormLayout.ItemRole.FieldRole,
             QFormLayout.ItemRole.SpanningRole)
    out = []
    for row in range(form.rowCount()):
        rects = [form.itemAt(row, role).geometry() for role in roles
                 if form.itemAt(row, role) is not None]
        top = min(r.top() for r in rects)
        bottom = max(r.top() + r.height() for r in rects)
        out.append((top, bottom, bottom == top))
    return out


def _gaps(widgets, horizontal: bool) -> list[int]:
    """The space between each widget and the next, along a row or a column."""
    if horizontal:
        return [b.x() - (a.x() + a.width()) for a, b in pairwise(widgets)]
    return [b.y() - (a.y() + a.height()) for a, b in pairwise(widgets)]


def test_the_view_dock_sits_on_one_grid(monkeypatch):
    """Measured as laid out, in every brain, in 3D and Slice view: no push
    button wider than its text and a grid unit either side; every other
    control at its own width; every control one height, with at least half
    a grid unit above and below its text; labels ending on one column and
    controls starting a grid unit after it; rows a grid unit apart in a
    group and two between groups; and napari's buttons a grid unit apart."""
    from qtpy.QtWidgets import (
        QAbstractSpinBox,
        QCheckBox,
        QComboBox,
        QFormLayout,
        QPushButton,
    )

    from lobemap.viewer.chrome import CONTROL_HEIGHT, GRID

    with launched(monkeypatch, "view", "GRABE") as (code, viewer):
        assert code == 0
        _show(viewer)
        sw = switcher(viewer)
        form = sw.layout()
        qt_viewer = viewer.window._qt_viewer
        for space in ("FAFB14", "JRCFIB2018F", "JRCFIB2022M", "GRABE"):
            switch_to(viewer, space)
            for ndisplay in (3, 2):
                viewer.dims.ndisplay = ndisplay
                pump(200)
                buttons = sw.findChildren(QPushButton)
                assert {b.text() for b in buttons} >= {
                    "3D", "Slice", "Fit to window", "Reset rotation"}
                for button in buttons:
                    text = button.fontMetrics().horizontalAdvance(button.text())
                    assert button.width() <= text + 2 * GRID + 2, (
                        space, button.text(), button.width(), text)
                for control in sw.findChildren((QComboBox, QCheckBox, QAbstractSpinBox)):
                    assert control.width() == control.sizeHint().width(), (
                        space, type(control).__name__, control.width())
                # Heights: one for every control, never tight around its text.
                controls = sw.findChildren(
                    (QPushButton, QComboBox, QCheckBox, QAbstractSpinBox))
                assert {c.height() for c in controls} == {CONTROL_HEIGHT}, sorted(
                    {(type(c).__name__, c.height()) for c in controls})
                for control in controls:
                    text = control.fontMetrics().height()
                    assert control.height() >= text + 2 * (GRID // 2), (
                        type(control).__name__, control.height(), text)
                # One label column, one control column.
                margin = form.contentsMargins()
                assert (margin.left(), margin.top(), margin.right()) == (GRID,) * 3
                ends, starts = set(), set()
                for row in range(form.rowCount()):
                    if form.itemAt(row, QFormLayout.ItemRole.SpanningRole) is not None:
                        continue                # a heading, a gap or wrapped text
                    label = form.itemAt(row, QFormLayout.ItemRole.LabelRole)
                    field = form.itemAt(row, QFormLayout.ItemRole.FieldRole)
                    if label is not None and label.widget() is not None:
                        widget = label.widget()
                        ends.add(widget.x() + widget.width())
                    if field is not None:
                        starts.add(field.geometry().left())
                assert len(ends) == 1 and starts == {ends.pop() + GRID}, (space, starts)
                # Rows: a grid unit apart, two across a gap row.
                gaps, after_gap = [], False
                last = None
                for top, bottom, gap in _rows(form):
                    if gap:
                        after_gap = True
                        continue
                    if last is not None:
                        gaps.append((top - last, 2 * GRID if after_gap else GRID))
                    last, after_gap = bottom, False
                assert all(got == want for got, want in gaps), (space, ndisplay, gaps)
                # Inside a row: the controls a grid unit apart, Fit to window two.
                assert _gaps([sw.three_d, sw.slice_view, sw.home], True) == [GRID, 2 * GRID]
                assert _gaps([sw.camera.perspective, sw.camera.note], True) == [GRID]
                assert _gaps([sw.slice, sw.align, sw.slice_note], False) == [GRID, GRID]
                assert _gaps([sw.mirror, sw.flip], False) == [GRID]
                # napari's rows: a grid unit between buttons; delete at the far end.
                viewer_row = [getattr(qt_viewer.viewerButtons, name) for name in (
                    "consoleButton", "ndisplayButton", "rollDimsButton",
                    "transposeDimsButton", "gridViewButton", "resetViewButton")]
                layer_row = [getattr(qt_viewer.layerButtons, name) for name in (
                    "newPointsButton", "newShapesButton", "newLabelsButton")]
                assert set(_gaps(viewer_row, True)) == {GRID}
                assert set(_gaps(layer_row, True)) == {GRID}
                delete = qt_viewer.layerButtons.deleteButton
                assert delete.x() + delete.width() > qt_viewer.layerButtons.width() - GRID


def test_the_mirror_reflects_and_another_brain_clears_it(monkeypatch):
    with launched(monkeypatch, "view", "GRABE") as (code, viewer):
        assert code == 0
        sw = switcher(viewer)
        sw.mirror.click()
        pump()
        assert session(viewer).mirrored
        sw.mirror.click()
        pump()
        assert not session(viewer).mirrored
        sw.mirror.click()
        switch_to(viewer, "FAFB14")
        assert not session(viewer).mirrored and not sw.mirror.isChecked()


def test_the_main_layer_is_active_and_no_layer_of_lobemaps_can_be_edited(monkeypatch):
    """By napari's layer state: what is active, what is editable, what mode.

    napari's transform tool, key 2 on a surface, moved a mesh off the image
    it is registered to; its drawing tools drew into the outline layers.
    """
    with launched(monkeypatch, "view", "JRCFIB2018F", "--ndisplay", "2") as (code, viewer):
        assert code == 0
        sess = session(viewer)
        main = sess.surfaces[sess.registry.primary_atlas(sess.space).id].layer
        assert viewer.layers.selection.active is main
        assert set(viewer.layers.selection) == {main}

        # A part built later, its tab opened, is locked too.
        tab = sess.panel.tab("neuprint_hemibrain_neuropil")
        pump()
        ours = list(viewer.layers)
        kinds = {layer.metadata["lobemap"]["kind"] for layer in ours}
        assert {"atlas", "contours"} <= kinds, kinds
        placed = {layer.name: np.asarray(layer.affine.affine_matrix) for layer in ours}

        def assert_locked() -> None:
            for layer in ours:
                assert layer.editable is False, layer.name
                assert layer.help == "", layer.name
                for mode in ("transform", "add_rectangle", "paint"):
                    with contextlib.suppress(ValueError):   # not this layer's mode
                        layer.mode = mode
                    assert layer.mode == "pan_zoom", (layer.name, mode)
                assert np.array_equal(layer.affine.affine_matrix, placed[layer.name])

        assert_locked()
        # napari makes a layer editable again on entering 2D, and a surface
        # whenever it is given new data, as a row ticked on gives it.
        tab.select(every_index(tab))
        pump(400)
        for ndisplay in (3, 2):
            viewer.dims.ndisplay = ndisplay
            pump()
            assert_locked()
        for layer in ours:
            viewer.layers.selection.active = layer
            pump()
            assert viewer.help == "", layer.name

        # A layer of the user's own can still be drawn in and moved.
        mine = viewer.add_shapes(ndim=3)
        pump()
        mine.mode = "add_rectangle"
        assert mine.editable and mine.mode == "add_rectangle"
        mine.mode = "transform"
        assert mine.mode == "transform"


def test_the_canvas_keeps_its_width_through_every_brain(monkeypatch):
    """Short colormap names keep napari's layer settings, and so the left
    column, narrow; each surface keeps its own colors under them."""
    from lobemap.viewer.layers import step_colormap

    names = re.compile(r"^(Glomerulus|Neuropil) colors( \(\d+\))?$")
    with launched(monkeypatch, "view", "FAFB14") as (code, viewer):
        assert code == 0
        _show(viewer)
        for space in ("JRCFIB2018F", "JRCFIB2022M", "GRABE", "FAFB14"):
            switch_to(viewer, space)
            sess = session(viewer)
            for name in list(sess.parts):
                tab = sess.panel.tab(name)
                if tab is not None:
                    # Each selection is a colormap napari keeps by name.
                    tab.select(every_index(tab)[::2])
                    tab.select(every_index(tab))
            for ndisplay in (2, 3):
                viewer.dims.ndisplay = ndisplay
                pump(300)
                _assert_layout(viewer)
            for surface in sess.surfaces.values():
                cmap = surface.layer.colormap
                assert names.match(cmap.name), cmap.name
                want = step_colormap(surface.colors, name="want").colors
                assert np.allclose(cmap.colors, want), (surface.name, cmap.name)


def test_the_view_dock_says_everything_in_words(monkeypatch):
    """Every string the dock shows: the approved wording, and no ids or tags."""
    from qtpy.QtCore import Qt
    from qtpy.QtWidgets import QAbstractButton, QComboBox, QLabel

    with launched(monkeypatch, "view", "FAFB14") as (code, viewer):
        assert code == 0
        sw = switcher(viewer)
        registry = session(viewer).registry
        menu = sw.combo
        brains = {menu.itemData(i): menu.itemText(i) for i in range(menu.count())}
        assert brains == TITLES
        # The row is labeled Brain: no title says it again.
        assert sw.layout().labelForField(menu).text() == "Brain"
        repeated = [t for t in brains.values() if re.search(r"\bbrain\b", t, re.IGNORECASE)]
        assert not repeated, brains
        tips = {menu.itemData(i): menu.itemData(i, Qt.ItemDataRole.ToolTipRole)
                for i in range(menu.count())}
        assert tips["FAFB14"] == ("FAFB (full adult fly brain): female, electron "
                                  "microscopy. Shown in the FAFB14 template.")
        assert tips["GRABE"] == ("Grabe 2015: live, light microscopy. Shown in the "
                                 "Grabe 2015 template.")
        for space, template in (("FAFB14", "FAFB14"), ("JRCFIB2018F", "JRCFIB2018F"),
                                ("JRCFIB2022M", "JRCFIB2022M"),
                                ("GRABE", "Grabe 2015")):
            assert f"the {template} template" in tips[space], tips[space]
        for space in ("FAFB14", "JRCFIB2018F", "JRCFIB2022M"):
            assert "electron microscopy" in tips[space], tips[space]
        assert sw.slice.itemText(0) == "Frontal (17.5° off anterior–posterior)"
        assert [sw.slice.itemText(i).split(" (")[0] for i in range(sw.slice.count())] == [
            "Frontal", "Horizontal", "Sagittal"]
        assert sw.slice.toolTip() == (
            "Which sections the slider steps through, and the axis it steps along. "
            "Unless aligned below, the sections follow the image's own grid, at the "
            "angle shown from that axis. Slice view only.")
        assert sw.align.text() == "Align sections to the anatomical axes"
        assert all(axis in sw.align.toolTip() for axis in (
            "anterior–posterior", "dorsal–ventral", "medial–lateral"))
        # No "true plane" anywhere: each section names the axis it steps along.
        shown = [sw.slice.itemText(i) for i in range(sw.slice.count())]
        shown += [sw.slice.toolTip(), sw.align.text(), sw.align.toolTip()]
        assert not any(re.search(r"\btrue\b", text) for text in shown), shown
        assert sw.mirror.text() == "Mirror the brain left to right"
        assert sw.flip.text() == "Flip the picture upside down"
        # Standalone checkboxes: no row label repeats their words, and they
        # share none of theirs but "the".
        assert sw.layout().labelForField(sw.picture) is None
        assert set(sw.mirror.text().lower().split()) & set(sw.flip.text().lower().split()) == {
            "the"}
        assert sw.flip.toolTip() == (
            "Show the picture upside down. Display only; the data do not change. With "
            "the mirror, a front view turns 180°. Opening another brain turns it off.")
        assert sw.mirror.toolTip() == (
            "Show the brain as its mirror image, to compare a left lobe with a right "
            "one. Display only; the data do not change. The corner arrows follow. "
            "Opening another brain turns it off.")
        assert sw.legend.text() == (
            "Arrows: A anterior, P posterior, D dorsal, V ventral, L left, R right. "
            "x, y, z are the image's own axes.")

        shown = []
        for widget in sw.findChildren(QLabel) + sw.findChildren(QAbstractButton):
            shown += [widget.text(), widget.toolTip()]
        for combo in sw.findChildren(QComboBox):
            shown.append(combo.toolTip())
            for i in range(combo.count()):
                shown += [combo.itemText(i),
                          combo.itemData(i, Qt.ItemDataRole.ToolTipRole) or ""]
        ids = set(registry.assets) | set(registry.atlases)
        for text in filter(None, shown):
            assert not re.search(r"[A-Za-z0-9]_[A-Za-z0-9]", text), text
            assert not re.search(r"[\[\]]", text), text
            assert not any(re.search(rf"\b{re.escape(i)}\b", text) for i in ids), text


def test_the_status_line_says_what_happened(monkeypatch):
    """Opening, a brain that cannot open, and one that opens but cannot be fitted."""
    from lobemap.viewer import scene
    from lobemap.viewer import switcher as module

    with launched(monkeypatch, "view", "GRABE") as (code, viewer):
        assert code == 0
        sw = switcher(viewer)
        seen = []
        real = sw._load

        def missing(space):
            seen.append(sw.status.text())
            raise FileNotFoundError(f"{space}: fafb_stain.zarr")

        sw._load = missing
        switch_to(viewer, "FAFB14")
        assert seen == ["Opening FAFB (female, EM)…"]
        assert sw.status.text() == (
            "Could not open FAFB (female, EM): its data are not downloaded; "
            "run lobemap fetch. Your view is unchanged.")
        assert session(viewer).space == "GRABE"
        assert sw.combo.currentData() == "GRABE"

        def unfitted(self):
            raise RuntimeError("no fit")

        sw._load = real
        monkeypatch.setattr(scene.SceneSession, "settle_view", unfitted)
        switch_to(viewer, "FAFB14")
        assert session(viewer).space == "FAFB14"
        assert sw.status.text() == (
            "Opened FAFB (female, EM), but could not fit it to the window.")

    assert module.plain_reason(MemoryError()) == "there is not enough memory"
    assert module.plain_reason(PermissionError()) == (
        "a data file could not be read; the terminal has the details")
    assert module.plain_reason(ValueError("x_y")) == (
        "an unexpected error; the terminal has the details")
