"""Why 3D must keep the identity dims order.

napari applies `dims.order` to an Image but not to a Surface once nothing is
non-displayed, so a permuted order in 3D transposes a volume out from under the
meshes it is supposed to sit behind. Nothing warns; it looks like a
registration failure. The first test pins that napari behavior so we notice if
it ever changes; the rest pin our policy.
"""

from __future__ import annotations

import numpy as np
import pytest

napari = pytest.importorskip("napari")

from lobemap.viewer.app import DIMS_ORDER_XYZ


@pytest.fixture
def viewer():
    v = napari.Viewer(ndisplay=2, show=False)
    yield v
    v.close()


def test_napari_permutes_an_image_but_not_a_surface_in_3d(viewer):
    """The napari asymmetry this module exists to avoid."""
    data = np.arange(4 * 5 * 6, dtype=np.uint8).reshape(4, 5, 6)
    verts = np.array([[0, 0, 0], [3, 0, 0], [0, 4, 0], [0, 0, 5]], float)
    faces = np.array([[0, 1, 2], [0, 1, 3]])
    img = viewer.add_image(data)
    surf = viewer.add_surface((verts, faces, np.zeros(len(verts))))

    viewer.dims.ndisplay = 3
    viewer.dims.order = (2, 1, 0)

    # Image: transposed to match the order.
    assert img._slice.image.raw.shape == (6, 5, 4)
    # Surface: vertex columns untouched, still (x, y, z).
    assert np.array_equal(surf._view_vertices, verts), (
        "napari now permutes Surface vertices in 3D too; if so, "
        "DIMS_ORDER_XYZ could be applied in 3D as well"
    )


def test_3d_uses_the_identity_order(viewer):
    from lobemap.viewer.app import install_display_mode

    viewer.add_image(np.zeros((4, 5, 6), np.uint8))
    install_display_mode(viewer, {}, {}, [])
    viewer.dims.ndisplay = 3
    assert tuple(viewer.dims.order) == (0, 1, 2)


def test_2d_puts_the_slider_on_z(viewer):
    from lobemap.viewer.app import install_display_mode

    viewer.add_image(np.zeros((4, 5, 6), np.uint8))
    install_display_mode(viewer, {}, {}, [])
    viewer.dims.ndisplay = 2
    assert tuple(viewer.dims.order) == DIMS_ORDER_XYZ
    assert viewer.dims.order[0] == 2, "slider axis must be z"


def test_order_survives_a_round_trip(viewer):
    from lobemap.viewer.app import install_display_mode

    viewer.add_image(np.zeros((4, 5, 6), np.uint8))
    install_display_mode(viewer, {}, {}, [])
    for _ in range(3):
        viewer.dims.ndisplay = 3
        assert tuple(viewer.dims.order) == (0, 1, 2)
        viewer.dims.ndisplay = 2
        assert tuple(viewer.dims.order) == DIMS_ORDER_XYZ
