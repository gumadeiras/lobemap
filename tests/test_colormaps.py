"""Display defaults live with the role, not scattered through the viewer."""

from __future__ import annotations

import numpy as np
import pytest

from lobemap.viewer.app import default_colormap


def test_stain_and_template_default_to_gray():
    assert default_colormap("virtual_stain") == "gray"
    assert default_colormap("template_image") == "gray"
    assert default_colormap("anything_else") == "magma"


def test_role_defaults_are_real_napari_colormaps():
    from napari.utils.colormaps import AVAILABLE_COLORMAPS

    for role in ("virtual_stain", "template_image", "other"):
        assert default_colormap(role) in AVAILABLE_COLORMAPS


def _registry_with_two_stains(root):
    """One atlas, so the scene builds, and two stains: one names a colormap."""
    from lobemap.core.imagefmt import Volume
    from lobemap.core.meshfmt import MeshSet
    from lobemap.core.registry import Registry

    (root / "atlases").mkdir(parents=True)
    (root / "spaces.toml").write_text('[S1]\ntitle = "S"\nunits = "um"\n')
    (root / "atlases" / "a1.toml").write_text(
        'id = "a1"\nnative_space = "S1"\nasset = "a1_mesh"\n')
    (root / "assets.toml").write_text(
        '[a1_mesh]\nrole = "glomeruli"\nspace = "S1"\nkind = "meshset"\n'
        'path = "data/a1.npz"\n\n'
        '[plain]\nrole = "virtual_stain"\nspace = "S1"\nkind = "image"\n'
        'path = "data/plain.npz"\n\n'
        '[tinted]\nrole = "virtual_stain"\nspace = "S1"\nkind = "image"\n'
        'path = "data/tinted.npz"\ncolormap = "cyan"\n')
    v = np.array([[0, 0, 0], [4, 0, 0], [0, 4, 0], [0, 0, 4]], np.float64)
    f = np.array([[0, 1, 2], [0, 1, 3], [0, 2, 3], [1, 2, 3]])
    MeshSet.from_parts([("DA1(R)", v, f)], meta={"units": "um"}).save(
        root / "data" / "a1.npz")
    for name in ("plain", "tinted"):
        Volume(np.zeros((4, 4, 4), np.uint8), voxel_um=(1.0, 1.0, 1.0)).save(
            root / "data" / f"{name}.npz")
    return Registry.load(root, data_root=root / "data")


def test_an_asset_colormap_reaches_its_layer(tmp_path):
    """From `assets.toml` to the layer napari draws, through the scene.

    This used to evaluate `asset.colormap or default_colormap(asset.role)`
    in the test itself, which held whatever the viewer did with the field.
    """
    napari = pytest.importorskip("napari")
    from lobemap.viewer.app import build_scene

    registry = _registry_with_two_stains(tmp_path / "registry")
    viewer = napari.Viewer(show=False)
    try:
        build_scene(viewer, registry, "S1")
        assert viewer.layers["tinted"].colormap.name == "cyan"
        assert viewer.layers["plain"].colormap.name == "gray"
    finally:
        viewer.close()
