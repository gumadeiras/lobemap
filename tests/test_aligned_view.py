"""2D aligned to the brain's own planes: the anatomical base view, measured.

With the alignment on, 2D's base view is the anatomical frame nearest the
image grid's: at zero angles the section is perpendicular to the anatomical
axis nearest the slice axis, and the screen's right and up run along the
anatomical axes nearest the grid's. The angles turn from there, as they
turn from the grid's frame without it. Off, at zero, the view is as it was.
"""

from __future__ import annotations

import numpy as np
import pytest
import turned_harness as th
from viewer_harness import pump

napari = pytest.importorskip("napari")


@pytest.fixture
def viewer():
    v = napari.Viewer(show=False, ndisplay=2)
    yield v
    v.close()
    pump()


def _anatomy(registry) -> np.ndarray:
    from lobemap.core.model import anatomical_axes

    frame = anatomical_axes(registry.spaces["GRABE"])
    return np.column_stack([frame["A"], frame["D"], frame["R"]]).astype(float)


def _shown_frame(viewer, contour) -> np.ndarray:
    """Columns: the mesh directions drawn as screen right, up and toward
    the viewer, from napari's canvas mapping through the contour layer."""
    right, up, _focus = th.screen_frame(viewer)
    linear = np.asarray(contour.layer.affine.affine_matrix)[:3, :3]
    out = []
    # Toward the viewer is right x up in the world, which a mirror reflects.
    for world in (right, up, np.cross(right, up)):
        q = np.linalg.solve(linear, world)
        out.append(q if contour.frame is None else contour.frame.matrix[:3, :3].T @ q)
    return np.column_stack(out)


def _nearest_proper(grid, anatomy) -> np.ndarray:
    """Each grid direction's nearest anatomical one, by its own sign."""
    out = np.empty((3, 3))
    for k in range(3):
        cos = anatomy.T @ grid[:, k]
        j = int(np.argmax(np.abs(cos)))
        out[:, k] = np.sign(cos[j]) * anatomy[:, j]
    return out


@pytest.mark.parametrize("axis", [2, 1, 0])
@pytest.mark.parametrize("mirrored", [False, True])
def test_aligned_2d_looks_along_the_anatomy_nearest_the_grid(viewer, registry, axis,
                                                            mirrored):
    from lobemap.viewer.rotation import grid_frame, screen_matrix

    session = th.build(viewer, registry)
    th.settle_canvas(viewer)
    if axis != 2:
        session.set_slice_axis(axis)
    session.set_mirror(mirrored)
    th.through_middle(viewer, axis, session.contours["synthetic"])
    th.settle_canvas(viewer)
    before, pixels = th.state(viewer), th.render(viewer)
    contour = session.contours["synthetic"]
    grid_shown = _shown_frame(viewer, contour)
    # In mesh coordinates: the anatomy as measured, the views reflected.
    anatomy = _anatomy(registry)
    # The unturned view: the grid's axes, mirrored with the scene.
    grid = grid_frame(viewer.dims.order)
    reflect = np.diag([-1.0, 1.0, 1.0]) if mirrored else np.eye(3)
    assert np.allclose(grid_shown, reflect @ grid, atol=1e-6)
    session.set_aligned(True)
    th.settle_canvas(viewer)
    assert session.aligned and contour.frame is not None
    base = _nearest_proper(reflect @ grid, anatomy)
    assert abs(np.linalg.det(base)) == pytest.approx(1.0)
    # Off the grid by its 15-32 degrees, onto the anatomy.
    assert np.allclose(_shown_frame(viewer, contour), base, atol=1e-6)
    offset = np.degrees(np.arccos(np.clip(np.diag(base.T @ (reflect @ grid)), -1, 1)))
    assert 1.0 < offset.max() < 35.0
    from test_oblique_view import _check

    _check(viewer, session)
    # The angles turn from the anatomical base view.
    for angles in ((30, 0, 0), (0, 25, 0), (10, -20, 40)):
        session.set_rotation(*angles)
        th.settle_canvas(viewer)
        want = base @ screen_matrix(angles).T
        assert np.allclose(_shown_frame(viewer, contour), want, atol=1e-6), angles
        _check(viewer, session)
    session.set_rotation(0, 0, 0)
    session.set_aligned(False)
    th.settle_canvas(viewer)
    assert not session.aligned
    assert th.state(viewer) == before
    assert np.array_equal(th.render(viewer), pixels)


def test_the_alignment_leaves_3d_alone(viewer, registry):
    session = th.build(viewer, registry)
    viewer.dims.ndisplay = 3
    th.settle_canvas(viewer)
    before = th.state(viewer)
    session.set_aligned(True)
    assert th.state(viewer) == before
    viewer.dims.ndisplay = 2
    th.settle_canvas(viewer)
    assert session.contours["synthetic"].frame is not None
    viewer.dims.ndisplay = 3
    th.settle_canvas(viewer)
    for layer in session.affine_layers():
        assert np.array_equal(np.asarray(layer.affine.affine_matrix), np.eye(4))
    session.set_aligned(False)
    assert session.turned.at_rest
