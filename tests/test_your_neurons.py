"""Your neurons in a scene: tubes in 3D, and in Slice view each tube's exact
section, cut from its skeleton, mirrored and turned with the scene.

No fetched data: a synthetic scene (`turned_harness`) and neurons made of
straight runs, whose sections are known: the ellipse a cylinder of the
tube's radius leaves on the plane.
"""

from __future__ import annotations

import numpy as np
import pytest
import trimesh
import turned_harness as th
from viewer_harness import hover, pump

from lobemap.core.neurons import TUBE_RADIUS_UM
from lobemap.viewer.neurons import KEY, TITLE, Neuron, SkeletonSections, build
from lobemap.viewer.sections import PlaneFrame

napari = pytest.importorskip("napari")

R = TUBE_RADIUS_UM


def _run(start, direction, length=30.0, step=0.5):
    """A straight skeleton: points `step` apart from `start` along `direction`."""
    direction = np.asarray(direction, float) / np.linalg.norm(direction)
    points = np.asarray(start, float) + np.arange(0, length, step)[:, None] * direction
    return points, np.r_[-1, np.arange(len(points) - 1)]


def test_a_section_is_the_ellipse_the_tube_cuts_on_the_plane():
    direction = np.array([0.5, 0.2, 1.0])
    unit = direction / np.linalg.norm(direction)
    points, parents = _run((10.0, 20.0, 0.0), direction)
    loops = SkeletonSections([(points, parents)]).at(2, 7.3)[0]
    assert len(loops) == 1
    loop = loops[0]
    assert np.allclose(loop[0], loop[-1]) and np.allclose(loop[:, 2], 7.3)
    # The cylinder about the run, cut by z = 7.3, as trimesh cuts it: an
    # ellipse about the run's crossing, its long axis along the run.
    cylinder = trimesh.creation.cylinder(radius=R, height=60.0, sections=256)
    cylinder.apply_transform(trimesh.geometry.align_vectors([0, 0, 1], unit))
    cylinder.apply_translation(points[0])
    exact = np.asarray(cylinder.section(plane_origin=(0, 0, 7.3),
                                        plane_normal=(0, 0, 1)).vertices)
    center = exact.mean(axis=0)
    major = np.r_[unit[:2], 0.0] / np.linalg.norm(unit[:2])
    minor = np.cross((0.0, 0.0, 1.0), major)
    long, short = (np.abs((exact - center) @ axis).max() for axis in (major, minor))
    assert long == pytest.approx(R / unit[2], rel=1e-3)
    assert short == pytest.approx(R, rel=1e-3)
    # Every drawn point is on that ellipse.
    u, v = (loop - center) @ major, (loop - center) @ minor
    assert np.allclose((u / long) ** 2 + (v / short) ** 2, 1.0, atol=2e-3)


def test_a_run_in_the_plane_is_cut_no_longer_than_it_reaches():
    points, parents = _run((0.0, 0.0, 5.0), (1.0, 0.0, 0.0001), length=3.0, step=1.0)
    loops = SkeletonSections([(points, parents)]).at(2, 5.0001)[0]
    for loop in loops:
        assert np.ptp(loop[:, 0]) <= 2 * (R + 0.5) + 1e-9


def test_a_frame_cuts_the_skeleton_where_it_cuts_its_points():
    points, parents = _run((0.0, 0.0, 0.0), (0.2, 0.3, 1.0))
    turn = np.eye(4)
    turn[:3, :3] = trimesh.transformations.rotation_matrix(0.4, (1, 1, 0))[:3, :3]
    frame = PlaneFrame(turn)
    sections = SkeletonSections([(points, parents)])
    framed = sections.at(2, 6.0, frame=frame)[0]
    straight = SkeletonSections([(frame.apply(points), parents)]).at(2, 6.0)[0]
    assert np.allclose(np.vstack(framed), np.vstack(straight))
    sections.drop_frames()
    assert sections.at(2, 6.0, frame=frame) is not None


@pytest.fixture
def viewer():
    v = napari.Viewer(show=False, ndisplay=2)
    yield v
    v.close()
    pump()


def _scene(viewer, registry):
    session = th.build(viewer, registry)
    center = np.asarray(th.BODIES[0][1], float)
    neurons = [
        Neuron("alpha neuron", "test", *_run(center - (0, 0, 15), (0.1, 0.3, 1.0)), "#ff4d6d"),
        Neuron("beta neuron", "test", *_run(center - (15, 0, 0), (1.0, 0.0, 0.2)), "#00e5ff"),
    ]
    session.set_part(KEY, lambda: build(viewer, neurons, session.mirror_args()))
    th.settle_canvas(viewer)
    th.through_middle(viewer, 2, session.contours["synthetic"])
    th.settle_canvas(viewer)
    return session, neurons


def _assert_sections_on_the_plane(viewer, session) -> None:
    contour = session.contours[KEY]
    origin, normal = th.plane_in_mesh(viewer, contour)
    normal = normal / np.linalg.norm(normal)
    loops = th.loops_in_mesh(contour, th.to_mesh(contour))
    assert loops, "nothing drawn"
    for _owner, loop in loops:
        assert np.abs((loop - origin) @ normal).max() < 1e-6


@pytest.mark.parametrize("mirrored", [False, True])
@pytest.mark.parametrize("angles", [(0, 0, 0), (40, 0, 0), (15, 25, 0)])
def test_slice_view_draws_each_section_on_the_plane_shown(viewer, registry, mirrored, angles):
    session, _neurons = _scene(viewer, registry)
    session.set_mirror(mirrored)
    session.set_rotation(*angles)
    th.settle_canvas(viewer)
    _assert_sections_on_the_plane(viewer, session)


def test_a_neuron_is_named_under_the_cursor_and_hidden_by_its_selection(viewer, registry):
    session, neurons = _scene(viewer, registry)
    contour = session.contours[KEY]
    owner, loop = th.loops_in_mesh(contour)[0]
    at = np.asarray(contour.layer.data_to_world(loop[:-1].mean(axis=0)), float)
    assert hover(viewer, at) == f"{neurons[owner].name} — {TITLE}"
    surface = session.surfaces[KEY]
    surface.set_selection({1 - owner})
    pump()
    assert all(o != owner for o, _loop in th.loops_in_mesh(contour))
    viewer.dims.ndisplay = 3
    pump()
    assert surface.layer.visible and not contour.layer.visible


def test_taking_the_neurons_out_leaves_no_layer(viewer, registry):
    session, _neurons = _scene(viewer, registry)
    layers = [session.surfaces[KEY].layer, session.contours[KEY].layer]
    session.set_rotation(15, 25, 0)
    session.set_part(KEY, None)
    assert KEY not in session.surfaces and KEY not in session.contours
    assert all(layer not in viewer.layers for layer in layers)
    th.settle_canvas(viewer)
    th.assert_on_the_plane(viewer, session)
