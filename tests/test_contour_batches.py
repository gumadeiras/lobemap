"""Large collections of tube sections stay exact without per-ring fill work."""

import numpy as np
import pytest

from lobemap.viewer import triangulate
from lobemap.viewer.contours import _PlaneGeometry
from lobemap.viewer.neurons import SkeletonSections
from lobemap.viewer.sections import PlaneFrame


def _sections(count=389):
    rng = np.random.default_rng(8)
    points = rng.uniform(-100, 100, (2 * count, 3))
    points[::2, 2], points[1::2, 2] = -1, 1
    parents = np.full(2 * count, -1)
    parents[1::2] = np.arange(0, 2 * count, 2)
    return SkeletonSections([(points, parents)])


@pytest.mark.parametrize("axis", [0, 1, 2])
@pytest.mark.parametrize("turned", [False, True])
def test_many_ellipse_fills_are_identical_without_individual_triangulation(monkeypatch,
                                                                          axis, turned):
    import trimesh

    frame = PlaneFrame(trimesh.transformations.rotation_matrix(.4, (1, 1, 0))) if turned else None
    sections = _sections().at(axis, 0, frame=frame)
    plane = [d for d in range(3) if d != axis]
    vertices, faces, count = [], [], 0
    for loop in sections[0]:
        v, f = triangulate.fill(loop[:-1][:, plane])
        vertices.append(v)
        faces.append(f + count)
        count += len(v)
    expected = np.vstack(vertices).astype(np.float32), np.vstack(faces)
    calls = []
    fill = triangulate.fill

    def spy(ring):
        calls.append(len(ring))
        return fill(ring)

    monkeypatch.setattr(triangulate, "fill", spy)
    actual = _PlaneGeometry(sections, axis, 0, 0.1).fills([0])[0][0]
    for got, want in zip(actual, expected, strict=True):
        np.testing.assert_array_equal(got, want)
    assert len(calls) <= 1, "each ellipse went through the general polygon filler"


@pytest.mark.parametrize("stage", ["sections", "outlines", "fills"])
def test_one_large_neuron_gives_way_within_a_plane(stage):
    sections = _sections(1024)
    cut = sections.at(2, 0)
    calls = []
    pause = lambda: calls.append(True)
    if stage == "sections":
        sections.at(2, 0.25, pause=pause)
    elif stage == "outlines":
        _PlaneGeometry(cut, 2, 0, 0.1, pause=pause)
    else:
        _PlaneGeometry(cut, 2, 0, 0.1).add_fills([0], pause=pause)
    assert len(calls) >= (1 if stage == "sections" else 16), (
        f"{stage} ignored the worker's pause within one large neuron")


@pytest.mark.parametrize("rings", [
    [],
    [np.array([[0, 0], [1, 0], [0, 1]])],
    [np.array([[0, 0], [2, 0], [2, 2], [1, 0.5], [0, 2]]),
     np.array([[0, 0], [1, 0], [0, 1]])],
    [np.array([[0, 0], [2, 2], [2, 0], [0, 2]])] * 2,
    [np.array([[0, 0], [3, 0], [3, 3], [2, 3], [2, 1], [1, 1], [1, 3], [0, 3]])] * 2,
])
def test_batch_fills_keep_the_general_polygon_behavior(rings):
    expected, triangles, count = [], [], 0
    for ring in rings:
        points, faces = triangulate.fill(ring)
        expected.append(points)
        triangles.append(faces + count)
        count += len(points)
    points, faces = triangulate.fills(rings)
    np.testing.assert_array_equal(points, np.vstack(expected) if expected else np.empty((0, 2)))
    np.testing.assert_array_equal(faces, np.vstack(triangles) if triangles else np.empty((0, 3)))
