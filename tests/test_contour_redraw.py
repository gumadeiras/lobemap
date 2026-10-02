"""Refreshing a contour layer repeatedly must not mix 2D and 3D vertices.

This is a regression test for a crash that only appeared on the SECOND entry
into 2D, which is why it survived every single-pass check: viewing the FAFB
neuropils in slice mode raised

    ValueError: all the input array dimensions except for the concatenation
    axis must match exactly, but along dimension 1, the array at index 0 has
    size 2 and the array at index 1 has size 3

from `np.vstack` inside napari's `ShapeList._extend_meshes`. The cause was
assigning `layer.data` and then `layer.shape_type`: the `shape_type` setter
re-adds every shape onto a shape list that still holds the previous ones, and
once the layer had been displayed in 2D those carried 2D mesh vertices.
"""

from __future__ import annotations

import numpy as np
import pytest

from lobemap.core.meshfmt import MeshSet
from lobemap.viewer.contours import ContourOverlay


def _cube_at(z0: float) -> tuple[np.ndarray, np.ndarray]:
    """A closed box spanning z in [z0, z0+2], so any plane inside it cuts."""
    import itertools

    v = np.array(list(itertools.product([0.0, 2.0], [0.0, 2.0], [z0, z0 + 2.0])),
                 dtype=np.float32)
    import scipy.spatial

    hull = scipy.spatial.ConvexHull(v.astype(float))
    return v, hull.simplices.astype(np.int32)


def _meshset() -> MeshSet:
    va, fa = _cube_at(0.0)
    vb, fb = _cube_at(1.0)
    return MeshSet(
        vertices=np.vstack([va, vb]),
        faces=np.vstack([fa, fb + len(va)]),
        vertex_offsets=np.array([0, len(va), len(va) + len(vb)]),
        face_offsets=np.array([0, len(fa), len(fa) + len(fb)]),
        names=["a", "b"],
        meta={},
    )


def test_cycling_between_2d_and_3d_keeps_redrawing():
    napari = pytest.importorskip("napari")
    viewer = napari.Viewer(show=False)
    try:
        overlay = ContourOverlay(viewer, _meshset(), "t", "#ff0000")
        # Contours ship hidden -- the display-mode hook reveals them in 2D --
        # and `refresh` is a no-op while hidden, so the test has to do what
        # that hook does or it would pass against a layer drawing nothing.
        overlay.layer.visible = True
        viewer.dims.ndisplay = 2
        viewer.dims.order = (2, 1, 0)
        viewer.dims.set_point(2, 1.5)

        drawn = []
        for _ in range(3):
            viewer.dims.ndisplay = 2
            overlay.refresh()
            drawn.append(len(overlay.layer.data))
            viewer.dims.ndisplay = 3
            overlay.refresh()

        assert all(n > 0 for n in drawn), f"contours stopped being drawn: {drawn}"
        assert len(set(drawn)) == 1, (
            f"the same plane gave different contour counts across cycles: {drawn}"
            " -- shapes are accumulating instead of being replaced"
        )
    finally:
        viewer.close()


def test_refresh_replaces_rather_than_appends():
    """Two refreshes on one plane must leave one set of shapes, not two."""
    napari = pytest.importorskip("napari")
    viewer = napari.Viewer(show=False)
    try:
        overlay = ContourOverlay(viewer, _meshset(), "t", "#ff0000")
        overlay.layer.visible = True
        viewer.dims.ndisplay = 2
        viewer.dims.order = (2, 1, 0)
        viewer.dims.set_point(2, 1.5)
        overlay.refresh()
        once = len(overlay.layer.data)
        overlay.refresh()
        assert len(overlay.layer.data) == once
        assert len(overlay._shape_index) == once
    finally:
        viewer.close()
