"""The publication's own voxel masks, kept beside the meshes derived from them."""

from __future__ import annotations

import numpy as np
import pytest

from lobemap.core.imagefmt import Volume


def test_the_masks_are_registered_as_labels(registry):
    asset = registry.assets["grabe2015_labels"]
    assert asset.kind == "labels"
    assert asset.space == "GRABE"


@pytest.mark.requires_data
def test_masks_are_not_stored_as_a_pyramid(registry):
    """Averaging two label ids gives a third label, which means nothing."""
    asset = registry.assets["grabe2015_labels"]
    assert asset.path.suffix == ".npz"
    volume = Volume.load(asset.path)
    assert not volume.is_multiscale


@pytest.mark.requires_data
def test_masks_and_meshes_share_a_frame(registry):
    """The meshes are surfaced from these, so they must sit on top of them."""
    volume = registry.volume("grabe2015_labels")
    mesh = registry.mesh("grabe2015_glomeruli")
    lo, hi = volume.bounds_um()
    assert np.all(mesh.vertices.min(0) >= lo - 1.0)
    assert np.all(mesh.vertices.max(0) <= hi + 1.0)
    assert volume.voxel_um == pytest.approx((0.34, 0.34, 0.96))


@pytest.mark.requires_data
def test_every_meshed_glomerulus_has_voxels_behind_it(registry):
    """A mesh with no mask under it would mean the ingest invented one."""
    volume = registry.volume("grabe2015_labels")
    mesh = registry.mesh("grabe2015_glomeruli")
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


@pytest.mark.requires_data
def test_the_masks_are_hidden_but_the_atlas_is_not(registry):
    """The masks segment the same glomeruli the meshes draw."""
    napari = pytest.importorskip("napari")
    from lobemap.viewer.app import build_scene

    viewer = napari.Viewer(ndisplay=3, show=False)
    try:
        surfaces, _ = build_scene(viewer, registry, "GRABE")
        assert surfaces["grabe2015"].layer.visible
        assert not viewer.layers["Glomerulus label volume (Grabe 2015)"].visible
    finally:
        viewer.close()


@pytest.mark.requires_data
def test_labels_become_a_napari_labels_layer(registry):
    napari = pytest.importorskip("napari")
    from lobemap.viewer.app import build_scene

    viewer = napari.Viewer(ndisplay=3, show=False)
    try:
        build_scene(viewer, registry, "GRABE")
        layer = viewer.layers["Glomerulus label volume (Grabe 2015)"]
        assert type(layer).__name__ == "Labels"
        assert layer.metadata["lobemap"]["kind"] == "labels"
    finally:
        viewer.close()
