"""The publication's own voxel masks, kept beside the meshes derived from them."""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest

from lobemap.core.imagefmt import Volume
from lobemap.core.registry import Registry

REGISTRY = Path(__file__).resolve().parents[1] / "registry"


@pytest.fixture(scope="module")
def reg():
    return Registry.load(REGISTRY)


def test_the_masks_are_registered_as_labels(reg):
    asset = reg.assets["grabe2015_labels"]
    assert asset.kind == "labels"
    assert asset.space == "GRABE"


def test_masks_are_not_stored_as_a_pyramid(reg):
    """Averaging two label ids gives a third label, which means nothing."""
    asset = reg.assets["grabe2015_labels"]
    assert asset.path.suffix == ".npz"
    volume = Volume.load(asset.path)
    assert not volume.is_multiscale


def test_masks_and_meshes_share_a_frame(reg):
    """The meshes are surfaced from these, so they must sit on top of them."""
    volume = reg.volume("grabe2015_labels")
    mesh = reg.mesh("grabe2015_glomeruli")
    lo, hi = volume.bounds_um()
    assert np.all(mesh.vertices.min(0) >= lo - 1.0)
    assert np.all(mesh.vertices.max(0) <= hi + 1.0)
    assert volume.voxel_um == pytest.approx((0.34, 0.34, 0.96))


def test_every_meshed_glomerulus_has_voxels_behind_it(reg):
    """A mesh with no mask under it would mean the ingest invented one."""
    volume = reg.volume("grabe2015_labels")
    mesh = reg.mesh("grabe2015_glomeruli")
    data = np.asarray(volume.data)
    present = set(np.unique(data).tolist()) - {0}
    assert len(present) >= mesh.n_compartments
    # Each mesh centroid should land on a non-zero voxel.
    misses = []
    for i in range(mesh.n_compartments):
        v, _f = mesh.compartment(i)
        centroid = v.mean(0)
        idx = volume.world_to_index(centroid[None, :])[0]
        outside = np.any(idx < 0) or np.any(idx >= np.array(volume.shape))
        if outside or data[tuple(idx)] == 0:
            misses.append(mesh.names[i])
    # A concave glomerulus can have its centroid outside itself, so allow a
    # few, but not many.
    assert len(misses) <= 5, misses


def test_the_masks_are_hidden_but_the_atlas_is_not(reg):
    """The masks segment the same glomeruli the meshes draw."""
    napari = pytest.importorskip("napari")
    from lobemap.viewer.app import build_scene

    viewer = napari.Viewer(ndisplay=3, show=False)
    try:
        surfaces, _ = build_scene(viewer, reg, "GRABE")
        assert surfaces["grabe2015"].layer.visible
        assert not viewer.layers["grabe2015_labels"].visible
    finally:
        viewer.close()


def test_labels_become_a_napari_labels_layer(reg):
    napari = pytest.importorskip("napari")
    from lobemap.viewer.app import build_scene

    viewer = napari.Viewer(ndisplay=3, show=False)
    try:
        build_scene(viewer, reg, "GRABE")
        layer = viewer.layers["grabe2015_labels"]
        assert type(layer).__name__ == "Labels"
        assert layer.metadata["lobemap"]["kind"] == "labels"
    finally:
        viewer.close()
