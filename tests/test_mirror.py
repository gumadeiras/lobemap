"""The display mirror reflects the scene without touching the data.

Four things have to hold, and three of them are regressions this file was
written after breaking:

- every layer moves, and the meshes underneath do not;
- each anatomical arrow points where its label says, IN THE MIRRORED VIEW,
  so the triad cannot claim the wrong side;
- no anatomical arrow lands on a world arrow -- and under a mirror the
  world arrows move too, so the sign choice has to be made against where
  they are drawn rather than against +x/+y/+z;
- the surface winding is reversed, so the triangles stay outward-facing
  under a reflection. This does not fix the shading, which still reads as
  lit from inside; see `AtlasSurface._oriented`.
"""

from __future__ import annotations

import numpy as np
import pytest

from lobemap.core.model import anatomical_axes, anatomical_triad
from lobemap.viewer.app import MIRROR_AXIS, load_space

SPACES = ("FAFB14", "JRCFIB2018F", "JRCFIB2022M", "GRABE")


def _reflection():
    w = np.eye(3)
    w[MIRROR_AXIS, MIRROR_AXIS] = -1.0
    return w


def test_each_mirrored_arrow_points_at_the_pole_it_names(registry):
    """The invariant that keeps a mirrored triad honest.

    NOT that the lateral label flips. Both L and R are reachable among
    the proper candidates, so which one is drawn is settled by arrow
    separation, and for the hemibrain it stays R while the ARROW turns
    from -x to +x. What must hold is that label and direction agree.
    """
    world = _reflection()
    for space_id in SPACES:
        space = registry.spaces[space_id]
        frame = anatomical_axes(space)
        matrix, labels = anatomical_triad(space, reflect_axis=MIRROR_AXIS)
        for k, label in enumerate(labels):
            want = world @ np.asarray(frame[label], float)
            assert np.allclose(matrix[:, k], want, atol=1e-9), (
                f"{space_id}: arrow {k} is labeled {label} but does not "
                f"point where {label} appears under the mirror"
            )


def test_a_mirrored_triad_is_still_drawable(registry):
    """Right-handed, or napari cannot draw it at all."""
    for space_id in SPACES:
        matrix, _ = anatomical_triad(
            registry.spaces[space_id], reflect_axis=MIRROR_AXIS
        )
        assert np.linalg.det(matrix) > 0, space_id
        assert np.allclose(matrix.T @ matrix, np.eye(3), atol=1e-9), space_id


def test_mirrored_arrows_avoid_the_reflected_world_arrows(registry):
    """The bug: choosing signs against +x while x is drawn at -x.

    The objective has to use the arrows AS DRAWN. Measured against the
    unreflected axes it picked a set that sat on top of the reflected x
    arrow -- a visible overlap, not a subtle one.
    """
    world = _reflection()
    drawn = [world @ np.eye(3)[j] for j in range(3)]
    for space_id in SPACES:
        matrix, labels = anatomical_triad(
            registry.spaces[space_id], reflect_axis=MIRROR_AXIS
        )
        worst = min(
            min(np.degrees(np.arccos(np.clip(matrix[:, k] @ a, -1.0, 1.0)))
                for a in drawn)
            for k in range(3)
        )
        assert worst > 30.0, (
            f"{space_id}: mirrored triad {''.join(labels)} comes within "
            f"{worst:.1f} deg of a world arrow"
        )


def _signed_volume(vertices, faces):
    """Positive when the winding puts the normals outward."""
    a = vertices[faces[:, 0]]
    b = vertices[faces[:, 1]]
    c = vertices[faces[:, 2]]
    return float(np.einsum("ij,ij->i", a, np.cross(b, c)).sum() / 6.0)


def _oriented_volume(surface):
    """Enclosed volume of a surface layer as the GPU sees it."""
    v = np.asarray(surface.layer.data[0], float)
    f = np.asarray(surface.layer.data[1])
    affine = np.asarray(surface.layer.affine.affine_matrix)
    v = v @ affine[:3, :3].T + affine[:3, -1]
    return _signed_volume(v, f)


@pytest.mark.requires_data
def test_mirroring_reverses_the_surface_winding(registry):
    """Otherwise every triangle faces inward under the reflection."""
    napari = pytest.importorskip("napari")
    viewer = napari.Viewer(show=False)
    try:
        session = load_space(viewer, registry, "GRABE", fit=False)
        surface = next(iter(session.surfaces.values()))

        plain = _oriented_volume(surface)
        assert plain > 0, "unmirrored normals already point inward"

        session.set_mirror(True)
        assert surface.mirrored
        mirrored = _oriented_volume(surface)
        assert mirrored > 0, (
            "the winding was not reversed, so every triangle faces inward "
            "under the reflection"
        )
        assert mirrored == pytest.approx(plain, rel=1e-6)

        session.set_mirror(False)
        assert _oriented_volume(surface) > 0
    finally:
        viewer.close()


@pytest.mark.requires_data
def test_the_winding_survives_a_selection_change(registry):
    """compact() re-uploads from the MeshSet, so it must re-wind too."""
    napari = pytest.importorskip("napari")
    viewer = napari.Viewer(show=False)
    try:
        session = load_space(viewer, registry, "GRABE", fit=False)
        surface = next(iter(session.surfaces.values()))
        session.set_mirror(True)
        surface.set_selection(range(0, surface.meshset.n_compartments, 2))
        surface.compact()
        assert _oriented_volume(surface) > 0, (
            "compaction dropped the mirrored winding"
        )
    finally:
        viewer.close()


@pytest.mark.requires_data
def test_mirror_moves_every_layer_and_keeps_the_data(registry):
    napari = pytest.importorskip("napari")
    viewer = napari.Viewer(show=False)
    try:
        session = load_space(viewer, registry, "GRABE", fit=False)
        layers = session.all_layers()
        assert layers, "no layers to mirror"

        surface = next(iter(session.surfaces.values()))
        vertices = np.array(surface.meshset.compartment(0)[0], copy=True)
        extent_before = viewer.layers.extent.world.copy()

        session.set_mirror(True)
        for layer in layers:
            affine = np.asarray(layer.affine.affine_matrix)
            assert affine[MIRROR_AXIS, MIRROR_AXIS] == pytest.approx(-1.0), (
                f"{layer.name} was not reflected"
            )

        assert np.array_equal(surface.meshset.compartment(0)[0], vertices), (
            "the mirror rewrote the mesh instead of transforming the view"
        )
        # Reflecting about the data's own mid-plane leaves the scene put,
        # rather than throwing it across the origin.
        assert np.allclose(viewer.layers.extent.world, extent_before, atol=1.0)

        session.set_mirror(False)
        for layer in layers:
            affine = np.asarray(layer.affine.affine_matrix)
            assert np.allclose(affine, np.eye(affine.shape[0])), (
                f"{layer.name} kept a transform after unmirroring"
            )
    finally:
        viewer.close()


@pytest.mark.requires_data
def test_toggling_twice_does_not_drift(registry):
    """The reflection plane is measured once, so it cannot creep."""
    napari = pytest.importorskip("napari")
    viewer = napari.Viewer(show=False)
    try:
        session = load_space(viewer, registry, "GRABE", fit=False)
        first = None
        for _ in range(3):
            session.set_mirror(True)
            here = viewer.layers.extent.world.copy()
            if first is None:
                first = here
            assert np.allclose(here, first, atol=1e-6), "mirror drifted"
            session.set_mirror(False)
    finally:
        viewer.close()
