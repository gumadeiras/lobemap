"""The Your data tab in the real viewer: open, place, fit, save and keep your
images, and add your neurons, in the brains they belong to.

Driven through `lobemap view`, as a user opens it (`viewer_harness.launched`),
in GRABE, with an image and neurons made here: the image's voxels and the
neurons' points are placed where each test can say what must be drawn.
"""

from __future__ import annotations

import time

import numpy as np
import pytest
import tifffile
from viewer_harness import click, docks, launched, pump, switch_to

from lobemap.core.placement import alignment_path, apply, corners, middle
from lobemap.viewer import placing
from lobemap.viewer.neurons import KEY, TITLE
from lobemap.viewer.your_data import YourData

pytestmark = pytest.mark.requires_data

SHAPE = (96, 96, 50)


def _tab(viewer) -> YourData:
    found = viewer.window._qt_window.findChildren(YourData)
    assert len(found) == 1, found
    return found[0]


def _wait(until, seconds: float = 30.0) -> None:
    end = time.perf_counter() + seconds
    while not until():
        assert time.perf_counter() < end, "timed out"
        pump(20)


@pytest.fixture
def stack(tmp_path):
    """An ImageJ stack, 1 x 1 x 2 um voxels, as (z, y, x)."""
    path = tmp_path / "fly1.tif"
    zyx = np.random.default_rng(0).integers(0, 1000, SHAPE[::-1], dtype=np.uint16)
    tifffile.imwrite(path, zyx, imagej=True, resolution=(1.0, 1.0),
                     metadata={"spacing": 2.0, "unit": "micron", "axes": "ZYX"})
    return path


def _opened(monkeypatch, *argv):
    context = launched(monkeypatch, "view", "GRABE", "--ndisplay", "2", *argv)
    code, viewer = context.__enter__()
    assert code == 0
    tab = _tab(viewer)
    if any(a == "--image" for a in argv):
        _wait(lambda: tab.images.images())
    return context, viewer, tab


def test_the_tab_comes_after_view_and_layer_settings(monkeypatch):
    context, viewer, _tab_ = _opened(monkeypatch)
    try:
        window = viewer.window._qt_window
        (view,), (yours,) = docks(viewer, "View"), docks(viewer, "Your data")
        assert yours in window.tabifiedDockWidgets(view)
        from qtpy.QtWidgets import QTabBar

        bars = [[bar.tabText(i) for i in range(bar.count())]
                for bar in window.findChildren(QTabBar)]
        assert ["View", "Layer settings", "Your data"] in bars, bars
    finally:
        context.__exit__(None, None, None)


@pytest.mark.parametrize("space", ["FAFB14", "JRCFIB2018F", "JRCFIB2022M", "GRABE"])
def test_the_tab_fits_its_column_with_no_sideways_scroll(monkeypatch, stack, space):
    """Laid out for real at 1440 x 900, an image open: the voxel size and
    the image center were three boxes side by side, and the Coordinates menu
    held each brain's whole title, and the tab scrolled sideways."""
    from qtpy.QtCore import Qt

    context = launched(monkeypatch, "view", space, "--image", str(stack))
    code, viewer = context.__enter__()
    try:
        assert code == 0
        tab = _tab(viewer)
        _wait(lambda: tab.images.images())
        window = viewer.window._qt_window
        window.setAttribute(Qt.WidgetAttribute.WA_DontShowOnScreen, True)
        window.resize(1440, 900)
        window.show()
        docks(viewer, "Your data")[0].raise_()
        pump(300)
        assert tab.widget().minimumSizeHint().width() <= tab.viewport().width()
        assert tab.horizontalScrollBar().maximum() == 0
    finally:
        context.__exit__(None, None, None)


def test_an_image_opens_where_the_view_looks_between_the_maps_and_the_atlas(
        monkeypatch, stack):
    context, viewer, tab = _opened(monkeypatch, "--image", str(stack))
    try:
        image = tab.images.images()[0]
        assert image.voxel_um == (1.0, 1.0, 2.0) and image.voxel_stated
        names = [layer.name for layer in viewer.layers]
        assert names.index("fly1.tif · slice") < names.index("Grabe 2015 · 3D")
        assert names.index("Confocal image (Grabe 2015)") < names.index("fly1.tif · 3D")
        session = tab.session
        dims = viewer.dims
        point = np.array(dims.point, float)
        point[list(dims.displayed)] = np.asarray(viewer.scene.camera.center)[-2:]
        assert np.allclose(middle(image.matrix, image.shape),
                           placing.space_point(session, point), atol=1e-6)
        assert image.placed.slices[0].visible and not image.placed.volumes[0].visible
    finally:
        context.__exit__(None, None, None)


def test_turns_undo_reset_and_save(monkeypatch, stack):
    context, viewer, tab = _opened(monkeypatch, "--image", str(stack))
    try:
        box = tab.images
        image = box.current()
        opened = image.matrix.copy()
        box.place.turns[placing.LINE_OF_SIGHT][1].click()
        box.place.larger.click()
        assert not np.allclose(image.matrix, opened) and len(image.history) == 2
        assert box.list.item(0).text().endswith("•")
        box.undo()
        box.place.reset.click()
        assert np.allclose(image.matrix, opened)
        box.place.turns[placing.VERTICAL][0].click()
        turned = image.matrix.copy()
        box.save.click()
        assert alignment_path(stack).exists() and image.saved
        assert box.list.item(0).text() == "fly1.tif"
        box.remove.click()
        assert not box.images() and not any("fly1" in layer.name for layer in viewer.layers)
        box.open_path(stack)
        _wait(lambda: box.images())
        assert np.allclose(box.images()[0].matrix, turned)
    finally:
        context.__exit__(None, None, None)


def test_landmarks_clicked_in_slice_view_fit_the_image_to_the_glomeruli(monkeypatch, stack):
    """The image's voxels are where a known placement puts the glomeruli;
    clicking each where the image shows it, then Fit, finds that placement."""
    context, viewer, tab = _opened(monkeypatch, "--image", str(stack))
    try:
        box, rows = tab.images, tab.images.landmarks
        image, session = box.current(), tab.session
        names = [rows.glomerulus.itemData(i) for i in range(rows.glomerulus.count())]
        left = [n for n in names if n.endswith("(L)")]
        lobe = np.mean([rows.targets[n] for n in left], axis=0)
        box.apply(placing.centered(image.matrix, image.shape, lobe))
        truth = image.matrix.copy()
        truth[:3, 3] += (4.0, -3.0, 2.0)

        def inside(name) -> bool:
            index = apply(np.linalg.inv(truth), rows.targets[name])[0]
            return bool(np.all(index > 2) and np.all(index < np.array(SHAPE) - 3))

        chosen = [n for n in left if inside(n)][::3][:6]
        assert len(chosen) == 6
        world = placing.world_matrix(session)
        for name in chosen:
            index = apply(np.linalg.inv(truth), rows.targets[name])[0]
            shown = apply(world @ image.matrix, index)[0]
            rows.glomerulus.setCurrentIndex(rows.glomerulus.findData(name))
            rows.click.setChecked(True)
            axis = int(viewer.dims.order[0])
            viewer.dims.set_point(axis, float(shown[axis]))
            camera = list(viewer.scene.camera.center)
            camera[-2:] = shown[list(viewer.dims.displayed)]
            viewer.scene.camera.center = tuple(camera)
            pump()
            click(viewer, shown)
            assert not rows.click.isChecked()
        assert [m.name for m in image.landmarks] == chosen
        rows.kind.setCurrentText("Similarity")
        rows.fit.click()
        # A click lands on a canvas pixel and a slider plane, a few tenths
        # of a micrometer from the point aimed at: across the whole image,
        # the fit is within a micrometer of the placement clicked.
        box_corners = corners(image.shape)
        assert np.abs(apply(image.matrix, box_corners)
                      - apply(truth, box_corners)).max() < 1.0
        assert "6 landmarks" in rows.result.text()
        off = [float(rows.table.item(r, 1).text().split()[0]) for r in range(6)]
        assert max(off) <= 0.5
    finally:
        context.__exit__(None, None, None)


def test_each_brain_keeps_its_own_data(monkeypatch, stack):
    context, viewer, tab = _opened(monkeypatch, "--image", str(stack))
    try:
        box = tab.images
        box.place.turns[placing.HORIZONTAL][1].click()
        kept = box.current().matrix.copy()
        switch_to(viewer, "FAFB14")
        assert tab.session.space == "FAFB14" and not box.images()
        assert not any("fly1" in layer.name for layer in viewer.layers)
        switch_to(viewer, "GRABE")
        assert len(box.images()) == 1 and np.allclose(box.current().matrix, kept)
        assert box.current().placed.slices[0] in viewer.layers
        assert box.current().placed in tab.session.placed
    finally:
        context.__exit__(None, None, None)


def _swc(path, points) -> None:
    path.write_text("".join(f"{i + 1} 3 {x} {y} {z} 0.5 {i if i else -1}\n"
                            for i, (x, y, z) in enumerate(points)))


def test_an_swc_neuron_in_this_brain_s_coordinates_is_drawn_and_named(
        monkeypatch, tmp_path):
    context, viewer, tab = _opened(monkeypatch)
    try:
        session, box = tab.session, tab.neurons
        primary = session.surfaces[session.registry.primary_atlas("GRABE").id]
        center = primary.meshset.centroid(0).astype(float)
        points = center + np.linspace(-20, 20, 41)[:, None] * np.array([0.3, 0.2, 0.93])
        path = tmp_path / "pn.swc"
        _swc(path, points)
        box.frame.setCurrentIndex(1)                     # this brain
        box.units.setCurrentText("micrometers")
        box.add_neuron(str(path))
        _wait(lambda: KEY in session.surfaces)
        assert box.list.count() == 1 and box.status.text() == ""
        surface, contour = session.surfaces[KEY], session.contours[KEY]
        # Under the glomeruli, so a neurite inside one shows through it.
        names = [layer.name for layer in viewer.layers]
        assert names.index(contour.layer.name) < names.index("Grabe 2015 · 3D")
        axis = int(viewer.dims.order[0])
        viewer.dims.set_point(axis, float(center[axis]))
        pump()
        assert contour.layer.visible and contour.paths, "no section drawn"
        crossing = np.mean(contour.paths[0][:-1], axis=0)
        assert np.linalg.norm(contour.layer.data_to_world(crossing) - center) < 1.0
        assert surface.name == TITLE
        box.list.item(0).setCheckState(box.list.item(0).checkState().__class__(0))
        assert not surface.selection and not contour.layer.visible
        switch_to(viewer, "JRCFIB2018F")
        assert KEY not in tab.session.surfaces
        switch_to(viewer, "GRABE")
        assert KEY in tab.session.surfaces and box.list.count() == 1
    finally:
        context.__exit__(None, None, None)


def test_a_neuron_outside_the_brain_says_its_coordinates_may_be_wrong(monkeypatch, tmp_path):
    context, viewer, tab = _opened(monkeypatch)
    try:
        path = tmp_path / "far.swc"
        _swc(path, [(1e6, 1e6, 1e6), (1e6 + 5, 1e6, 1e6)])
        tab.neurons.frame.setCurrentIndex(1)
        tab.neurons.add_neuron(str(path))
        _wait(lambda: tab.neurons.list.count())
        assert "outside this brain" in tab.neurons.status.text()
    finally:
        context.__exit__(None, None, None)


def test_grabe_takes_no_flywire_neuron_and_says_why(monkeypatch):
    """No network: the bridge is refused before FlyWire is asked."""
    from lobemap.core import neurons as nr

    monkeypatch.setattr(nr, "fetch_flywire", lambda *a, **k: (np.zeros((2, 3)),
                                                              np.array([-1, 0])))
    context, viewer, tab = _opened(monkeypatch)
    try:
        tab.neurons.add_neuron("720575940623636701")
        _wait(lambda: "no link" in tab.neurons.status.text())
        assert not tab.neurons.list.count()
    finally:
        context.__exit__(None, None, None)


def test_your_layers_are_removed_in_the_tab_not_the_layer_list(monkeypatch, stack):
    from lobemap.viewer.guards import YOURS_KEPT

    shown = []
    monkeypatch.setattr("napari.utils.notifications.show_info", shown.append)
    context, viewer, tab = _opened(monkeypatch, "--image", str(stack))
    try:
        layer = tab.images.current().placed.slices[0]
        viewer.layers.selection = {layer}
        viewer.layers.remove_selected()
        assert layer in viewer.layers
        assert shown == [YOURS_KEPT.format(names=repr(layer.name))]
    finally:
        context.__exit__(None, None, None)


@pytest.mark.parametrize("argv, words", [
    (("--image", "missing.tif"), "no such file"),
    (("--image", "notes.txt"), "TIFF and NRRD"),
    (("--neuron", "neuron.swc"), "Your data tab"),
    (("--neuron", "DA1"), "not a FlyWire root ID"),
])
def test_view_refuses_data_it_cannot_open_before_any_window(monkeypatch, capsys, tmp_path,
                                                          argv, words):
    (tmp_path / "neuron.swc").write_text("1 1 0 0 0 1 -1\n")
    monkeypatch.chdir(tmp_path)
    with launched(monkeypatch, "view", "GRABE", *argv) as (code, viewer):
        assert code == 2 and viewer is None
    assert words in capsys.readouterr().err
