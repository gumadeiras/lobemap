"""A voxel mask must be the same color as the mesh of the same glomerulus.

The masks and the meshes are two renderings of one segmentation, so a
mismatch is not a cosmetic issue -- it makes the two layers unreadable
against each other, which is the only reason to show them together.
"""

from __future__ import annotations

import numpy as np
import pytest

from lobemap.core.registry import Registry
from lobemap.ingest.label_volume import label_names


@pytest.fixture(scope="module")
def registry():
    return Registry.load("registry")


def test_the_volume_carries_its_own_value_to_name_map(registry):
    """The mapping must ship with the data, not be re-derived from source."""
    volume = registry.volume("grabe2015_labels")
    names = volume.meta.get("label_names")
    assert names, "grabe2015_labels has no label_names in its metadata"
    present = set(np.unique(np.asarray(volume.data)).tolist()) - {0}
    missing = sorted(present - {int(k) for k in names})
    assert not missing, f"voxel values with no name: {missing}"


def test_label_names_drops_non_glomerulus_materials():
    got = label_names({1: "Exterior", 2: "DA1_left", 3: "VA1d_right", 4: "D"})
    assert got == {2: "DA1(L)", 3: "VA1d(R)", 4: "D"}


def test_mask_colors_equal_mesh_colors(registry):
    napari = pytest.importorskip("napari")
    from lobemap.viewer.app import build_scene

    viewer = napari.Viewer(show=False)
    try:
        surfaces, _contours = build_scene(viewer, registry, "GRABE")
        layer = viewer.layers["grabe2015_labels"]
        surface = surfaces["grabe2015"]
        color_dict = layer.colormap.color_dict

        names = layer.metadata["lobemap"]["label_names"]
        checked = 0
        for value, name in names.items():
            if name not in surface.meshset.names:
                continue
            mesh = np.asarray(
                surface.colors[surface.meshset.names.index(name)], dtype=float
            )
            assert value in color_dict, f"{name} (value {value}) is uncolored"
            np.testing.assert_allclose(
                np.asarray(color_dict[value], dtype=float), mesh, atol=1e-6,
                err_msg=f"{name} differs between its mask and its mesh",
            )
            checked += 1
        assert checked > 100, f"only {checked} glomeruli compared"
    finally:
        viewer.close()


def test_an_unnamed_value_is_transparent_not_miscolored():
    """A value with no name must vanish, not borrow another's color."""
    from lobemap.viewer.layers import direct_label_colormap

    cmap = direct_label_colormap({3: (1.0, 0.0, 0.0, 1.0)})
    assert tuple(cmap.color_dict[None]) == (0.0, 0.0, 0.0, 0.0)
