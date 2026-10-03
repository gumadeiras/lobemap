"""A section bermuda overlaps triangles in is filled exactly, and fast.

`triangulate.fill` hands a ring that is not star-shaped to bermuda, turned
each way in `_TURNS` until one covers it, and leaves to napari's own
pure-Python triangulation -- tens to hundreds of milliseconds a ring, on the
UI thread when a step draws a plane the prefetch has not reached -- only a
simple ring no turn covers. A ring that crosses or touches itself never goes
to napari: no fill covers exactly what it encloses, and napari's covers what
bermuda's does.
"""

from __future__ import annotations

import numpy as np
import pytest
from viewer_harness import ring_area

from lobemap.viewer import napari_private, triangulate
from lobemap.viewer.sections import MeshSections

pytest.importorskip("bermuda")


def _area(points, faces) -> float:
    a, b, c = (np.asarray(points, float)[np.asarray(faces)[:, k]] for k in range(3))
    return float(np.abs((b[:, 0] - a[:, 0]) * (c[:, 1] - a[:, 1])
                        - (b[:, 1] - a[:, 1]) * (c[:, 0] - a[:, 0])).sum()) / 2.0


@pytest.fixture
def no_napari(monkeypatch):
    def refuse(ring):
        raise AssertionError(f"napari's pure-Python fill was called on {len(ring)} points")

    monkeypatch.setattr(napari_private, "triangulate_face", refuse)


def _square_turns_overlap(ring) -> bool:
    """Whether bermuda overlaps triangles in the ring however it is reflected."""
    import bermuda

    for turn in triangulate._SQUARE:
        turned = np.ascontiguousarray(ring.astype(float) @ turn.T, np.float32)
        faces, points = bermuda.triangulate_polygons_face([turned])
        if _area(points, faces) == pytest.approx(ring_area(ring), rel=1e-6):
            return False
    return True


@pytest.mark.requires_data("neuprint_cns_neuropil")
@pytest.mark.parametrize(("axis", "position", "name"), [(1, 233.0, "SPS(R)"),
                                                        (2, 180.5, "GNG")])
def test_a_ring_bermuda_overlaps_however_reflected_is_filled_exactly_without_napari(
        registry, no_napari, axis, position, name):
    meshset = registry.mesh("neuprint_cns_neuropil")
    loops = MeshSections(meshset).at(axis, position)[meshset.names.index(name)]
    ring = np.ascontiguousarray(max(loops, key=len)[:-1][:, [d for d in range(3) if d != axis]],
                                np.float32)
    assert _square_turns_overlap(ring), "the case is gone"
    points, faces = triangulate.fill(ring)
    assert _area(points, faces) == pytest.approx(ring_area(ring), rel=1e-9)
    assert {tuple(p) for p in points[np.unique(faces)]} == {tuple(p) for p in
                                                            ring.astype(float)}


@pytest.mark.parametrize("ring", [
    # A bow tie: its two edges cross at (1, 1).
    [[0, 0], [2, 2], [2, 0], [0, 2]],
    # Two triangles wound opposite ways, touching at (1, 1).
    [[0, 0], [1, 1], [2, 0], [2, 2], [1, 1], [0, 2]],
], ids=["crossing", "touching"])
def test_a_ring_that_crosses_itself_is_filled_by_bermuda_alone(no_napari, ring):
    import bermuda

    ring = np.asarray(ring, np.float32) + 100.0
    faces, points = bermuda.triangulate_polygons_face([ring])
    got_points, got_faces = triangulate.fill(ring)
    assert _area(got_points, got_faces) == pytest.approx(_area(points, faces), rel=1e-12)


@pytest.mark.requires_data("neuprint_cns_neuropil")
def test_the_male_cns_gng_at_z_155_is_filled_by_bermuda_alone(registry, no_napari):
    """Its long section crosses itself once: bermuda puts a point there."""
    import bermuda

    meshset = registry.mesh("neuprint_cns_neuropil")
    loops = MeshSections(meshset).at(2, 155.0)[meshset.names.index("GNG")]
    ring = np.ascontiguousarray(max(loops, key=len)[:-1][:, [0, 1]], np.float32)
    faces, points = bermuda.triangulate_polygons_face([ring])
    assert len(points) > len(ring), "the case is gone"
    got_points, got_faces = triangulate.fill(ring)
    assert _area(got_points, got_faces) == pytest.approx(_area(points, faces), rel=1e-12)
