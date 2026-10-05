"""The contour prefetch: planes cut ahead are the ones the slider lands on,
draw exactly as planes cut on the spot, and nothing of a plan outlives the
axis, mirror, space or visibility it was made for, nor its thread the viewer.
"""

from __future__ import annotations

import threading

import numpy as np
import pytest
from viewer_harness import (
    assert_renders_loops,
    assert_rows_match_drawing,
    contour_loops,
    drawn,
    launched,
    layer_names,
    pump,
    rendered_labels,
    rendered_mesh,
    session,
    switch_to,
    switcher,
    tick_all,
)

from lobemap.viewer import prefetch
from lobemap.viewer.sections import MeshSections, PlaneCache


def test_the_plane_cache_keeps_to_its_budget():
    cache = PlaneCache(max_bytes=300)
    for key in "abc":
        assert cache.put(key, key.upper(), 100) == key.upper()
    cache.get("a")                                  # a is now the most recent
    assert cache.put("d", "D", 100) == "D"
    assert cache.get("b") is None, "b was least recently used"
    assert cache.nbytes == 300
    # The prefetch evicts only what is not its own, least recent first...
    assert cache.put("e", "E", 100, keep={"a", "e"}) == "E"
    assert cache.get("c") is None and cache.get("a") == "A"
    # ...and keeps nothing rather than evict one of its own.
    assert cache.put("f", "F", 100, keep={"a", "d", "e", "f"}) is None
    assert cache.get("f") is None and cache.nbytes == 300
    # What is kept first stays: both were cut from the same plane.
    assert cache.put("d", "other", 100) == "D"
    cache.grew("d", 50)                             # a fill built on it later
    assert cache.nbytes == 350


napari = pytest.importorskip("napari")


@pytest.fixture
def held_back(monkeypatch):
    """Keep the worker waiting, so a plan is still running when the test acts.

    It waits while the UI thread has worked on a slice in the last
    `QUIET_S`; call the returned function to let it go.
    """
    monkeypatch.setattr(prefetch, "QUIET_S", 30.0)
    prefetch.poke()
    return lambda: monkeypatch.setattr(prefetch, "QUIET_S", 0.03)


def _primary(viewer):
    sess = session(viewer)
    return sess.contours[sess.registry.primary_atlas(sess.space).id]


def _slider_positions(viewer, overlay) -> list[float]:
    """Where the slider can land inside the atlas, by napari's own transform."""
    axis = overlay.axis
    start, _stop, step = viewer.dims.range[axis]
    column = overlay.meshset.vertices[:, axis]
    point = list(viewer.dims.point)
    out = []
    for k in range(int(viewer.dims.nsteps[axis])):
        point[axis] = start + k * step
        position = float(overlay.layer.world_to_data(point)[axis])
        if column.min() <= position <= column.max():
            out.append(position)
    return out


def _assert_all_cut_ahead(viewer, overlay) -> None:
    assert prefetch.settle(60), "the prefetch never finished"
    plan = overlay._plan
    assert plan is not None and plan.error is None and not plan.full
    missing = [p for p in _slider_positions(viewer, overlay)
               if overlay._geometry.get((overlay.axis, p)) is None
               or overlay.sections.planes.get((overlay.axis, p)) is None]
    assert not missing, f"{len(missing)} slider planes not cut ahead"


def _assert_drawn_is_fresh(overlay) -> None:
    """The loops on screen are the plane's sections, cut again from scratch."""
    position = overlay.slice_position()
    fresh = MeshSections(overlay.meshset).at(overlay.axis, position)
    want = [(i, loop) for i in sorted(overlay.selection) for loop in fresh.get(i, ())]
    got = contour_loops(overlay)
    assert [i for i, _ in got] == [i for i, _ in want]
    for (_i, a), (_j, b) in zip(got, want, strict=True):
        np.testing.assert_array_equal(a, b)
    assert_renders_loops(overlay)


@pytest.mark.requires_data
def test_every_slider_plane_is_cut_ahead(monkeypatch):
    with launched(monkeypatch, "view", "FAFB14", "--ndisplay", "2") as (code, viewer):
        assert code == 0
        overlay = _primary(viewer)
        _assert_all_cut_ahead(viewer, overlay)
        held = overlay.sections.planes.nbytes + overlay._geometry.nbytes
        assert held < 100 * 2**20, held


@pytest.mark.requires_data
@pytest.mark.parametrize("space", ["FAFB14", "GRABE"])
def test_a_plane_cut_ahead_draws_exactly_as_one_cut_on_the_spot(monkeypatch, space):
    with launched(monkeypatch, "view", space, "--ndisplay", "2") as (code, viewer):
        overlay = _primary(viewer)
        overlay.set_labels(set(overlay.selection))
        overlay.set_fills(set(overlay.selection))
        _assert_all_cut_ahead(viewer, overlay)
        axis = overlay.axis
        viewer.dims.set_current_step(axis, viewer.dims.current_step[axis] + 5)
        pump()
        assert overlay._geometry.get((axis, overlay.slice_position())) is not None
        ahead = rendered_mesh(overlay), rendered_labels(overlay), contour_loops(overlay)

        # Forget everything cut, and draw the same plane again from scratch.
        overlay.stop()
        overlay.sections = MeshSections(overlay.meshset)
        overlay._geometry = PlaneCache(overlay._geometry.max_bytes)
        overlay._drawn = None
        overlay.refresh()
        spot = rendered_mesh(overlay), rendered_labels(overlay), contour_loops(overlay)
        for a, b in zip(ahead[0], spot[0], strict=True):
            np.testing.assert_array_equal(a, b)
        assert [t for t, _p, _c in ahead[1]] == [t for t, _p, _c in spot[1]]
        for (_s, p, c), (_t, q, d) in zip(ahead[1], spot[1], strict=True):
            np.testing.assert_array_equal(p, q)
            np.testing.assert_array_equal(c, d)
        for (i, a), (j, b) in zip(ahead[2], spot[2], strict=True):
            assert i == j
            np.testing.assert_array_equal(a, b)


@pytest.fixture
def ui_fills(monkeypatch):
    """Every fill triangulated from now on: True for each on the UI thread."""
    from lobemap.viewer import triangulate

    calls = []
    real = triangulate.fill

    def spy(ring):
        calls.append(threading.current_thread() is threading.main_thread())
        return real(ring)

    monkeypatch.setattr(triangulate, "fill", spy)
    return calls


def _assert_filled_ahead(viewer, overlay) -> None:
    """Every slider plane holds the fills of every filled compartment it cuts,
    and the cache counts each plane's bytes once."""
    _assert_all_cut_ahead(viewer, overlay)
    axis = overlay.axis
    for p in _slider_positions(viewer, overlay):
        geometry = overlay._geometry.get((axis, p))
        lacking = (geometry.present & overlay.filled) - set(geometry._fills)
        assert not lacking, f"plane {p}: no fill built ahead for {sorted(lacking)}"
    sizes = list(overlay._geometry._items.values())
    assert all(size == geometry.nbytes for geometry, size in sizes)
    assert overlay._geometry.nbytes == sum(size for _g, size in sizes)


def _first_visits(viewer, overlay, steps) -> None:
    axis = overlay.axis
    for step in steps:
        viewer.dims.set_current_step(axis, viewer.dims.current_step[axis] + step)
        pump()
        _assert_drawn_is_fresh(overlay)


@pytest.mark.requires_data
@pytest.mark.parametrize("space", ["FAFB14", "GRABE"])
def test_a_first_visit_to_a_filled_plane_triangulates_nothing(monkeypatch, ui_fills, space):
    with launched(monkeypatch, "view", space, "--ndisplay", "2") as (code, viewer):
        overlay = _primary(viewer)
        some = set(sorted(overlay.selection)[::2])
        overlay.set_fills(some)
        _assert_filled_ahead(viewer, overlay)
        ui_fills.clear()
        _first_visits(viewer, overlay, (5, -11, 3))
        assert ui_fills.count(True) == 0, "a step triangulated a fill on the UI thread"

        # More fills: the prefetch builds the ones each plane lacks.
        overlay.set_fills(set(overlay.selection))
        _assert_filled_ahead(viewer, overlay)
        ui_fills.clear()
        _first_visits(viewer, overlay, (7, -16, 2))
        assert ui_fills.count(True) == 0, "a step triangulated a fill on the UI thread"
        assert ui_fills.count(False) == 0, "fills were built again"


@pytest.mark.requires_data
def test_every_plane_of_the_largest_atlas_fits_filled(monkeypatch):
    """The male CNS atlas cut along y holds the most geometry of any shipped
    atlas: with every glomerulus filled, every slider plane still fits."""
    with launched(monkeypatch, "view", "JRCFIB2022M", "--ndisplay", "2") as (code, viewer):
        overlay = _primary(viewer)
        menu = switcher(viewer).slice
        menu.setCurrentIndex(menu.findData(1))
        pump()
        assert overlay.axis == 1
        overlay.set_fills(set(range(overlay.meshset.n_compartments)))
        _assert_filled_ahead(viewer, overlay)
        held = overlay.sections.planes.nbytes + overlay._geometry.nbytes
        assert held <= overlay.sections.planes.max_bytes + overlay._geometry.max_bytes


def test_fills_built_by_steps_and_by_the_prefetch_are_kept_once(open_box_viewer,
                                                                ui_fills, held_back):
    """The UI thread fills the planes a step lands on while the prefetch waits;
    the prefetch then fills the rest, and each fill is built and counted once."""
    viewer, overlay = open_box_viewer
    _step_to(viewer, 2, 2.5)
    overlay.layer.visible = True
    pump()
    overlay.set_fills({1})
    for z in (2.0, 0.25, -1.5):
        _step_to(viewer, 2, z)
        _assert_drawn_is_fresh(overlay)
    on_ui = ui_fills.count(True)
    assert on_ui >= 3
    held_back()
    _assert_filled_ahead(viewer, overlay)
    planes = [p for p in _slider_positions(viewer, overlay)
              if 1 in overlay._geometry.get((2, p)).present]
    assert ui_fills.count(True) == on_ui
    assert len(ui_fills) == len(planes), "a fill was built twice"


@pytest.mark.requires_data
def test_a_switch_during_the_prefetch_stops_it(monkeypatch, held_back):
    with launched(monkeypatch, "view", "FAFB14", "--ndisplay", "2") as (code, viewer):
        old = _primary(viewer)
        plan = old._plan
        assert plan is not None and plan.finished is None
        switch_to(viewer, "GRABE")
        assert session(viewer).space == "GRABE"
        assert plan.cancelled
        held_back()
        assert prefetch.settle(60)
        held = (len(old.sections.planes), len(old._geometry))
        pump(300)
        assert (len(old.sections.planes), len(old._geometry)) == held
        # Only the open scene's layers are left.
        assert set(viewer.layers) == set(session(viewer).all_layers()), layer_names(viewer)
        _assert_all_cut_ahead(viewer, _primary(viewer))
        _assert_drawn_is_fresh(_primary(viewer))


@pytest.mark.requires_data
def test_an_axis_change_during_the_prefetch_cuts_the_new_axis(monkeypatch, held_back):
    with launched(monkeypatch, "view", "GRABE", "--ndisplay", "2") as (code, viewer):
        overlay = _primary(viewer)
        first = overlay._plan
        assert first is not None and first.finished is None
        menu = switcher(viewer).slice
        menu.setCurrentIndex(menu.findData(1))
        pump()
        assert overlay.axis == 1
        assert first.cancelled and overlay._plan is not first
        assert overlay._plan.axis == 1
        held_back()
        _assert_all_cut_ahead(viewer, overlay)
        assert first.planes < len(first.positions()), "the first plan was not cut short"
        for step in (-7, 3, 11):
            viewer.dims.set_current_step(1, viewer.dims.current_step[1] + step)
            pump()
            _assert_drawn_is_fresh(overlay)


@pytest.mark.requires_data
def test_a_mirror_during_the_prefetch_cuts_the_mirrored_planes(monkeypatch, held_back):
    with launched(monkeypatch, "view", "FAFB14", "--ndisplay", "2") as (code, viewer):
        overlay = _primary(viewer)
        menu = switcher(viewer).slice
        menu.setCurrentIndex(menu.findData(0))       # along x, the mirror's axis
        pump()
        along_x = overlay._plan
        assert along_x is not None and along_x.axis == 0 and along_x.finished is None
        switcher(viewer).mirror.setChecked(True)
        pump()
        assert along_x.cancelled and overlay._plan is not along_x
        mirrored = set(overlay._plan.positions())
        assert mirrored != set(along_x.positions()), "the mirror moved no plane"
        held_back()
        _assert_all_cut_ahead(viewer, overlay)
        for step in (-9, 4):
            viewer.dims.set_current_step(0, viewer.dims.current_step[0] + step)
            pump()
            _assert_drawn_is_fresh(overlay)
            pump(300)
            assert_rows_match_drawing(session(viewer))


@pytest.fixture
def open_box_viewer():
    """A 2D viewer slicing along z through an open box and a sphere.

    The box is alone in its compartment, so a plane through it gives that
    compartment no loop at all; see `open_box_and_sphere`.
    """
    from test_contour_sections import open_box_and_sphere

    from lobemap.viewer import contours

    viewer = napari.Viewer(show=False, ndisplay=2)
    try:
        viewer.add_image(np.zeros((40, 40, 40), np.uint8), scale=(0.25, 0.25, 0.25),
                         translate=(-3, -4, -4))
        overlay = contours.ContourOverlay(viewer, open_box_and_sphere(), "t", color="red")
        viewer.dims.order = (2, 0, 1)
        contours.install(viewer, {"t": overlay})   # as a scene does: steps redraw
        yield viewer, overlay
    finally:
        viewer.close()              # removing its layer stops its prefetch
        assert prefetch.settle(30)


def _step_to(viewer, axis: int, position: float) -> None:
    start, _stop, step = viewer.dims.range[axis]
    viewer.dims.set_current_step(axis, round((position - start) / step))
    pump()
    assert viewer.dims.point[axis] == pytest.approx(position)


def test_a_step_onto_an_open_compartment_draws_the_new_plane(open_box_viewer):
    viewer, overlay = open_box_viewer
    _step_to(viewer, 2, 2.5)                     # the sphere only
    overlay.layer.visible = True
    pump()
    _assert_drawn_is_fresh(overlay)
    for z in (0.25, -0.5, 2.5, 0.75):            # through the open box, and out
        _step_to(viewer, 2, z)
        assert {i for i, _ in contour_loops(overlay)} == {1}
        _assert_drawn_is_fresh(overlay)
        assert all(np.all(loop[:, 2] == overlay.slice_position())
                   for _i, loop in contour_loops(overlay))
    assert prefetch.settle(30)
    plan = overlay._plan
    assert plan.error is None and plan.skipped == 0 and not plan.full
    assert plan.planes == len(plan.positions()) == len(_slider_positions(viewer, overlay))


def test_a_plane_whose_cut_raises_is_skipped_and_the_rest_are_cut(open_box_viewer,
                                                                 monkeypatch):
    """Either kind: an Exception, or a Rust panic in bermuda, which pyo3 raises
    as a BaseException. Neither ends the worker."""
    from test_contour_sections import PanicException

    viewer, overlay = open_box_viewer
    _step_to(viewer, 2, 2.5)
    positions = _slider_positions(viewer, overlay)
    # The panic's plane is the nearer to the slice, so it is cut first.
    bad = {positions[3]: RuntimeError, positions[-2]: PanicException}
    real = MeshSections._compute

    def compute(self, axis, p, pause=None):
        if p in bad:
            raise bad[p](f"cannot cut {p}")
        return real(self, axis, p, pause)

    monkeypatch.setattr(MeshSections, "_compute", compute)
    overlay.layer.visible = True
    pump()
    assert prefetch.settle(30)
    plan = overlay._plan
    assert plan.skipped == 2 and not plan.full
    assert isinstance(plan.error, PanicException), plan.error
    assert plan.planes == len(positions) - 2
    cut = {p for p in positions if overlay._geometry.get((2, p)) is not None}
    assert cut == set(positions) - set(bad)
    assert not prefetch.busy()
    monkeypatch.setattr(MeshSections, "_compute", real)
    overlay.layer.visible = False                   # and on again: a new plan
    overlay.layer.visible = True
    pump()
    assert prefetch.settle(30)
    assert overlay._plan is not plan and overlay._plan.planes == len(positions)
    for z in (positions[0], positions[-1], *bad):
        _step_to(viewer, 2, z)
        _assert_drawn_is_fresh(overlay)


def test_the_worker_cuts_nothing_while_the_ui_thread_holds_it(open_box_viewer):
    """`prefetch.held`, as building a part of the scene uses it."""
    viewer, overlay = open_box_viewer
    _step_to(viewer, 2, 2.5)
    with prefetch.held():
        overlay.layer.visible = True
        pump(300)
        plan = overlay._plan
        assert plan is not None and prefetch.busy()
        assert plan.planes == 0
    assert prefetch.settle(30)
    assert plan.planes == len(_slider_positions(viewer, overlay))


def _cached(overlay) -> tuple[int, int]:
    return len(overlay.sections.planes), len(overlay._geometry)


@pytest.mark.requires_data
def test_hiding_an_atlas_stops_its_prefetch_and_showing_it_cuts_the_rest(
        monkeypatch, held_back):
    with launched(monkeypatch, "view", "FAFB14", "--ndisplay", "2") as (code, viewer):
        overlay = _primary(viewer)
        first = overlay._plan
        assert first is not None and first.finished is None
        overlay.layer.visible = False               # its eye, in the layer list
        pump()
        assert first.cancelled
        held_back()
        assert prefetch.settle(60)
        held = _cached(overlay)
        pump(300)
        assert _cached(overlay) == held, "a hidden atlas went on being cut"

        overlay.layer.visible = True
        pump()
        assert overlay._plan is not first and not overlay._plan.cancelled
        _assert_all_cut_ahead(viewer, overlay)
        viewer.dims.set_current_step(overlay.axis, viewer.dims.current_step[overlay.axis] + 6)
        pump()
        _assert_drawn_is_fresh(overlay)


@pytest.mark.requires_data
def test_an_atlas_that_shows_nothing_gets_nothing_cut(monkeypatch):
    with launched(monkeypatch, "view", "JRCFIB2018F", "--ndisplay", "2") as (code, viewer):
        sess = session(viewer)
        name = "schlegel2021_s11"
        panel = sess.panel
        tab = panel.open(name)
        pump()
        overlay = sess.contours[name]
        assert prefetch.settle(60)
        assert not overlay.layer.visible
        assert overlay._plan is None and _cached(overlay) == (0, 0)

        tick_all(tab)
        pump()
        assert drawn(tab.surface, overlay)
        _assert_all_cut_ahead(viewer, overlay)
        _assert_drawn_is_fresh(overlay)


@pytest.mark.requires_data
def test_closing_the_viewer_during_the_prefetch_leaves_no_thread(monkeypatch, held_back):
    with launched(monkeypatch, "view", "FAFB14", "--ndisplay", "2") as (code, viewer):
        plan = _primary(viewer)._plan
        assert plan is not None and plan.finished is None and prefetch.busy()
    # Still held back: only the teardown can have stopped it.
    assert plan.cancelled
    for thread in threading.enumerate():
        if thread.name == "lobemap-prefetch":
            thread.join(5)
            assert not thread.is_alive(), "the prefetch thread outlived the viewer"
    assert not prefetch.busy()


@pytest.mark.requires_data
def test_a_new_axis_after_a_finished_prefetch_cuts_every_plane_of_it(monkeypatch):
    """The planes the last axis left are evicted for the new axis's own: the
    male CNS atlas along z and along x does not fit one budget."""
    with launched(monkeypatch, "view", "JRCFIB2022M", "--ndisplay", "2") as (code, viewer):
        overlay = _primary(viewer)
        _assert_all_cut_ahead(viewer, overlay)
        menu = switcher(viewer).slice
        for axis in (0, 1):
            menu.setCurrentIndex(menu.findData(axis))
            pump()
            assert overlay.axis == axis
            _assert_all_cut_ahead(viewer, overlay)
            held = overlay.sections.planes.nbytes + overlay._geometry.nbytes
            assert held < 100 * 2**20, held
            _assert_drawn_is_fresh(overlay)
