"""A failed space switch gives back the user's own scene, not its defaults.

The user changes everything a scene lets them change, through its controls;
a switch then fails at one point of the build; and what is drawn afterwards
-- rows, outlines, labels, fills, plane, mirror, camera -- is compared with
what was drawn before, together with the controls that say so.
"""

from __future__ import annotations

import numpy as np
import pytest
from viewer_harness import (
    assert_renders_loops,
    assert_rows_match_drawing,
    checked,
    contour_loops,
    docks,
    drawn,
    handler_counts,
    launched,
    layer_names,
    planes_cut,
    pump,
    rendered_labels,
    session,
    switch_to,
    switcher,
)

pytestmark = pytest.mark.requires_data
pytest.importorskip("napari")

#: Three atlases and a neuropil set, so every kind of tab is exercised.
SPACE = "JRCFIB2018F"
PRIMARY = "neuprint_hemibrain"
SECONDARY = "schlegel2021_s11"
NEUROPIL = "neuprint_hemibrain_neuropil"
LINE = "Orco-GAL4 & GH146-GAL4"
TARGET = "GRABE"


def _buttons(tab):
    from qtpy.QtWidgets import QPushButton

    return {b.text(): b for b in tab.findChildren(QPushButton)}


def _boxes(tab, column) -> set[int]:
    from qtpy.QtCore import Qt

    return {tab._index_of(r) for r in range(tab.table.rowCount())
            if tab.table.item(r, column).checkState() == Qt.Checked}


def _tick(tab, column, index, on=True) -> None:
    from qtpy.QtCore import Qt

    tab.table.item(tab._row_of(index), column).setCheckState(
        Qt.Checked if on else Qt.Unchecked)


def _camera(viewer):
    camera = viewer.scene.camera
    return (np.asarray(camera.center, float), float(camera.zoom),
            np.asarray(camera.angles, float))


def _home(viewer):
    """The camera the home button gives; the camera is then put back as it was."""
    camera = viewer.scene.camera
    saved = (tuple(camera.center), camera.zoom, tuple(camera.angles), camera.perspective)
    viewer.window._qt_viewer.viewerButtons.resetViewButton.click()
    pump()
    home = _camera(viewer)
    camera.center, camera.zoom, camera.angles, camera.perspective = saved
    pump()
    return home


def _triads(viewer) -> dict:
    """What each corner triad draws: shown or not, its turn, its labels."""
    from lobemap.viewer.axes import _ANATOMY_ATTR, _vispy_axes_overlay

    overlay = _vispy_axes_overlay(viewer)
    out = {}
    for name, node in (("array", overlay.node.axes),
                       ("anatomy", getattr(overlay, _ANATOMY_ATTR, None))):
        if node is None:
            out[name] = None
            continue
        matrix = getattr(node.transform, "matrix", None)
        out[name] = (bool(node.visible),
                     None if matrix is None else np.round(matrix, 6).tolist(),
                     list(np.atleast_1d(node.text.text)))
    return out


def _user_scene(viewer) -> None:
    """Change what a user can change, through the controls they would use."""
    from lobemap.viewer.panel import FILL_COL, LABEL_COL, VISIBLE_COL

    sw = switcher(viewer)
    sess = sw.session
    two_d = viewer.dims.ndisplay == 2
    if two_d:
        # Another slice axis in the menu, then a few planes along it.
        sw.slice.setCurrentIndex(sw.slice.findData(1))
        pump()
        axis = int(viewer.dims.order[0])
        assert axis == 1
        viewer.dims.set_current_step(axis, viewer.dims.current_step[axis] + 3)
    sw.mirror.click()
    pump()

    panel = sess.panel
    primary = panel.tabs[PRIMARY]
    shown = sorted(primary.surface.selection)
    for index in shown[:3]:
        _tick(primary, VISIBLE_COL, index, on=False)
    if two_d:                       # labels and fills are 2D controls
        cut = sorted(planes_cut(primary.surface))
        _buttons(primary)["Label all"].click()
        _tick(primary, LABEL_COL, cut[0], on=False)
        for index in cut[1:4]:
            _tick(primary, FILL_COL, index)

    neuropil = panel.tabs[NEUROPIL]
    panel.setCurrentWidget(neuropil)
    names = neuropil.surface.meshset.names
    _tick(neuropil, VISIBLE_COL, names.index(next(n for n in names if n.startswith("AL"))))

    secondary = panel.tabs[SECONDARY]
    panel.setCurrentWidget(secondary)
    _buttons(secondary)["Show all"].click()
    menu = secondary.lines
    menu.setCurrentIndex(next(i for i in range(menu.count())
                              if menu.itemText(i).startswith(LINE + " (")))
    if two_d:
        _buttons(secondary)["Fill all"].click()
    secondary.filter.setText("DA")

    camera = viewer.scene.camera
    camera.zoom = camera.zoom * 1.7
    camera.center = tuple(np.asarray(camera.center, float) + (0.0, 11.0, -7.0))
    if viewer.dims.ndisplay == 3:
        camera.angles = (12.0, -33.0, 71.0)
    pump(400)


def _rendered(viewer) -> dict:
    """What is on screen, and what the controls say about it."""
    from lobemap.viewer.panel import FILL_COL, LABEL_COL

    sw = switcher(viewer)
    sess = sw.session
    out = {
        "space": sess.space,
        "title": viewer.title,
        "ndisplay": viewer.dims.ndisplay,
        "order": tuple(viewer.dims.order),
        "point": tuple(round(float(p), 6) for p in viewer.dims.point),
        "slice menu": sw.slice.currentText(),
        "mirror box": sw.mirror.isChecked(),
        "open tab": sess.panel.tabText(sess.panel.currentIndex()),
        "layers": layer_names(viewer),
        "visible": sorted(layer.name for layer in viewer.layers if layer.visible),
        "affines": {layer.name: np.round(layer.affine.affine_matrix, 6).tolist()
                    for layer in viewer.layers},
        "docks": len(docks(viewer, "Compartments")),
        "handlers": handler_counts(viewer),
        # Building the next scene turns both triads onto its space.
        "triads": _triads(viewer),
    }
    for name, tab in sess.panel.tabs.items():
        contour = sess.contours.get(name)
        out[name] = {
            "rows": checked(tab),
            "drawn": drawn(tab.surface, contour),
            "label boxes": _boxes(tab, LABEL_COL),
            "fill boxes": _boxes(tab, FILL_COL),
            "filter": tab.filter.text(),
            "hidden rows": {tab._index_of(r) for r in range(tab.table.rowCount())
                            if tab.table.isRowHidden(r)},
            "line": tab.lines.currentText(),
            "count": tab.count.text(),
            "n rows": tab.table.rowCount(),
        }
        if contour is not None and contour.layer.visible:
            # What the slice visuals draw: `assert_renders_loops` checks the
            # vispy buffers are these loops, filled and labeled as listed.
            assert_renders_loops(contour)
            loops = contour_loops(contour)
            names = contour.meshset.names
            out[name]["labels drawn"] = sorted(
                text for text, _pos, _rgba in rendered_labels(contour))
            out[name]["filled drawn"] = sorted(
                names[owner] for owner, _loop in loops if owner in contour.filled)
            out[name]["outlines"] = [np.round(loop, 5).tobytes() for _owner, loop in loops]
    return out


def _assert_same(before: dict, after: dict) -> None:
    diff = {k: (before[k], after.get(k)) for k in before if before[k] != after.get(k)}
    assert not diff, diff


def _fail_in_asset_loading(monkeypatch, viewer):
    """GRABE's atlas mesh is unreadable, after its images are in the viewer."""
    from lobemap.core.registry import Registry

    real = Registry.mesh

    def mesh(self, asset_id):
        if asset_id == "grabe2015_glomeruli":
            raise OSError("grabe2015_glomeruli is unreadable")
        return real(self, asset_id)

    monkeypatch.setattr(Registry, "mesh", mesh)
    return "unreadable"


def _fail_in_panel(monkeypatch, viewer):
    """The compartment panel is built, then breaks before it is docked."""
    from lobemap.viewer import panel

    real = panel.CompartmentPanel.__init__

    def init(self, *args, **kwargs):
        real(self, *args, **kwargs)
        raise RuntimeError("the panel broke")

    monkeypatch.setattr(panel.CompartmentPanel, "__init__", init)
    return "the panel broke"


def _fail_in_dock(monkeypatch, viewer):
    real = viewer.window.add_dock_widget

    def refuse(widget, *args, **kwargs):
        if kwargs.get("name") == "Compartments":
            raise RuntimeError("the dock refused")
        return real(widget, *args, **kwargs)

    monkeypatch.setattr(viewer.window, "add_dock_widget", refuse)
    return "the dock refused"


def _fail_after_hooks(monkeypatch, viewer):
    """Picking, contours and the display mode are live; the home button fails."""
    from lobemap.viewer import app

    real = app.install_home_orientation
    failures = []

    def refuse_once(*args, **kwargs):
        if not failures:
            failures.append(True)
            raise RuntimeError("home refused")
        return real(*args, **kwargs)

    monkeypatch.setattr(app, "install_home_orientation", refuse_once)
    return "home refused"


def _fail_after_the_load(monkeypatch, viewer):
    """The scene is complete; mirroring it, the switcher's own step, fails."""
    from lobemap.viewer.app import SceneSession

    real = SceneSession.set_mirror

    def set_mirror(self, on):
        if self.space == TARGET:
            raise RuntimeError("the mirror broke")
        return real(self, on)

    monkeypatch.setattr(SceneSession, "set_mirror", set_mirror)
    return "the mirror broke"


FAILURES = {
    "asset": _fail_in_asset_loading,
    "panel": _fail_in_panel,
    "dock": _fail_in_dock,
    "hooks": _fail_after_hooks,
    "after load": _fail_after_the_load,
}


@pytest.mark.parametrize("ndisplay", ["2", "3"])
@pytest.mark.parametrize("where", list(FAILURES))
def test_a_failed_switch_gives_back_the_users_scene(monkeypatch, where, ndisplay):
    with launched(monkeypatch, "view", SPACE, "--ndisplay", ndisplay) as (
        code, viewer,
    ):
        assert code == 0
        _user_scene(viewer)
        home = _home(viewer)
        before = _rendered(viewer)
        camera = _camera(viewer)
        kept = session(viewer)
        # The scene really is the user's, not the space's defaults.
        assert before["mirror box"]
        assert before[SECONDARY]["line"].startswith(LINE)
        assert before[SECONDARY]["rows"]
        assert 0 < len(before[SECONDARY]["hidden rows"]) < before[SECONDARY]["n rows"]
        assert before[NEUROPIL]["drawn"]
        assert before["open tab"] == SECONDARY[:20]
        if ndisplay == "2":
            assert before["order"][0] == 1
            assert before[PRIMARY]["labels drawn"]
            assert before[PRIMARY]["filled drawn"]

        want = FAILURES[where](monkeypatch, viewer)
        switch_to(viewer, TARGET)
        pump(400)

        assert want in switcher(viewer).status.text()
        _assert_same(before, _rendered(viewer))
        assert session(viewer) is kept
        center, zoom, angles = _camera(viewer)
        assert np.allclose(center, camera[0], atol=1e-6), (center, camera[0])
        assert zoom == pytest.approx(camera[1], rel=1e-9)
        assert np.allclose(angles, camera[2], atol=1e-6), (angles, camera[2])
        # Home faces this space, mirrored as it is, not the one that failed.
        center, zoom, angles = _home(viewer)
        assert np.allclose(center, home[0], atol=1e-6), (center, home[0])
        assert zoom == pytest.approx(home[1], rel=1e-9)
        assert np.allclose(angles, home[2], atol=1e-6), (angles, home[2])

        # And it is still the scene being driven: the plane moves its
        # outlines, and a row still reaches the drawing.
        if ndisplay == "2":
            axis = int(viewer.dims.order[0])
            viewer.dims.set_current_step(axis, viewer.dims.current_step[axis] + 1)
            pump(300)
        assert_rows_match_drawing(session(viewer))


def test_a_switch_that_succeeds_still_replaces_the_scene(monkeypatch):
    """Built beside the old scene, the new one is left alone and framed."""
    with launched(monkeypatch, "view", SPACE, "--ndisplay", "2") as (code, viewer):
        assert code == 0
        _user_scene(viewer)
        switch_to(viewer, TARGET)
        pump(400)
        sess = session(viewer)
        assert sess.space == TARGET
        assert switcher(viewer).status.text() == ""
        assert all(name.startswith(("grabe", "Grabe")) for name in layer_names(viewer)), (
            layer_names(viewer))
        assert len(docks(viewer, "Compartments")) == 1
        # The mirror carries over; the anatomy chosen for the slice does too.
        assert sess.mirrored
        assert switcher(viewer).slice.currentText().startswith("Anterior-Posterior")
        # On the new scene's own grid, cutting its atlas.
        axis = int(viewer.dims.order[0])
        start, _stop, step = viewer.dims.range[axis]
        k = (viewer.dims.point[axis] - start) / step
        assert k == pytest.approx(round(k), abs=1e-6)
        assert_rows_match_drawing(sess)
        assert drawn(sess.surfaces["grabe2015"], sess.contours["grabe2015"])
