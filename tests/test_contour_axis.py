"""Contours must cut the plane the slider is actually on."""

from __future__ import annotations

import numpy as np

from lobemap.core.meshfmt import MeshSet
from lobemap.viewer.contours import ContourOverlay


class _Dims:
    def __init__(self, order):
        self.order = order


class _Viewer:
    def __init__(self, order):
        self.dims = _Dims(order)


def _meshset():
    v = np.array([[0, 0, 0], [1, 0, 0], [0, 1, 0], [0, 0, 1]], np.float32)
    f = np.array([[0, 1, 2], [0, 1, 3], [0, 2, 3], [1, 2, 3]], np.int32)
    return MeshSet(vertices=v, faces=f, vertex_offsets=np.array([0, 4]),
                   face_offsets=np.array([0, 4]), names=["a"], meta={})


def test_axis_follows_the_viewer_dims_order():
    ms = _meshset()
    o = ContourOverlay.__new__(ContourOverlay)
    o.viewer, o._axis = _Viewer((2, 1, 0)), None
    o.meshset, o.name = ms, "t"
    assert o.axis == 2, "displaying x-y means the slider is on z"
    o.viewer.dims.order = (0, 1, 2)
    assert o.axis == 0, "it must track the order, not be read once"


def test_an_explicit_axis_still_wins():
    o = ContourOverlay.__new__(ContourOverlay)
    o.viewer, o._axis = _Viewer((2, 1, 0)), 1
    assert o.axis == 1
