"""The display mirror reflects the scene without touching the data.

Four things have to hold, and three of them are regressions this file was
written after breaking:

- every layer moves, and the meshes underneath do not;
- each anatomical arrow points where its label says, IN THE MIRRORED VIEW,
  so the triad cannot claim the wrong side;
- no anatomical arrow lands on a world arrow -- and under a mirror the
  world arrows move too, so the sign choice has to be made against where
  they are drawn rather than against +x/+y/+z;
- the normals vispy shades with stay outward under the mirror, and the
  surface node's transform stays PROPER: the surfaces reflect their own
  vertices instead of riding on `layer.affine`, because a determinant -1
  node transform flips `gl_FrontFacing`, by which vispy's smooth shading
  negates the normal (`AtlasSurface._present`).
"""

from __future__ import annotations

import numpy as np
import pytest
from viewer_harness import node_determinant, shaded_normals, signed_volume

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


@pytest.mark.requires_data
def test_the_shaded_normals_stay_outward_under_a_mirror(registry):
    """Neither the normals nor the facing may invert.

    Read off the node in 3D, the geometry as vispy shades it. What matters
    is that mirroring does not change it, and that the node transform stays
    proper so `gl_FrontFacing` is not flipped underneath it.
    """
    napari = pytest.importorskip("napari")
    viewer = napari.Viewer(show=False, ndisplay=3)
    try:
        session = load_space(viewer, registry, "GRABE", fit=False)
        viewer.dims.ndisplay = 3
        surface = next(iter(session.surfaces.values()))
        volume, outward = shaded_normals(viewer, surface)
        assert volume > 0, "unmirrored geometry is already inside-out"
        assert outward > 0.6, f"unmirrored normals only {outward:.1%} outward"
        assert node_determinant(viewer, surface) > 0

        session.set_mirror(True)
        mirrored_volume, mirrored_outward = shaded_normals(viewer, surface)
        assert mirrored_volume == pytest.approx(volume, rel=1e-4), (
            "the reflected geometry is inside-out: the vertices were "
            "reflected without the winding being reversed")
        assert mirrored_outward == pytest.approx(outward, abs=0.02), (
            f"mirroring moved the normals: {outward:.1%} -> {mirrored_outward:.1%}")
        assert node_determinant(viewer, surface) > 0, (
            "the surface is reflected by its affine, which flips "
            "gl_FrontFacing and lights it from inside")

        session.set_mirror(False)
        assert shaded_normals(viewer, surface)[0] == pytest.approx(volume, rel=1e-4)
    finally:
        viewer.close()


@pytest.mark.requires_data
def test_the_mirror_reflects_vertices_and_reverses_the_winding(registry):
    """Both, together: either one alone inverts the shading."""
    napari = pytest.importorskip("napari")
    viewer = napari.Viewer(show=False)
    try:
        session = load_space(viewer, registry, "GRABE", fit=False)
        surface = next(iter(session.surfaces.values()))
        v0 = np.array(surface.layer.data[0], copy=True)
        f0 = np.array(surface.layer.data[1], copy=True)

        session.set_mirror(True)
        v1 = np.asarray(surface.layer.data[0])
        f1 = np.asarray(surface.layer.data[1])
        assert np.array_equal(f1, f0[:, ::-1]), "the winding was not reversed"
        other = [k for k in range(3) if k != MIRROR_AXIS]
        assert np.allclose(v1[:, other], v0[:, other], atol=1e-4)
        assert np.allclose(v1[:, MIRROR_AXIS] + v0[:, MIRROR_AXIS],
                           2.0 * session.mirror_center, atol=1e-2), (
            "the vertices were not reflected about the measured mid-plane")
        affine = np.asarray(surface.layer.affine.affine_matrix)
        assert np.allclose(affine, np.eye(affine.shape[0])), (
            "the surface carries the mirror on its affine")
    finally:
        viewer.close()


@pytest.mark.requires_data
def test_the_reflection_survives_a_selection_change(registry):
    """compact() re-uploads from the MeshSet, so it must reflect too."""
    napari = pytest.importorskip("napari")
    viewer = napari.Viewer(show=False, ndisplay=3)
    try:
        session = load_space(viewer, registry, "GRABE", fit=False)
        viewer.dims.ndisplay = 3
        surface = next(iter(session.surfaces.values()))
        session.set_mirror(True)
        surface.set_selection(range(0, surface.meshset.n_compartments, 2))
        surface.compact()
        v, f, _ = surface.meshset.select(sorted(surface.selection))
        assert shaded_normals(viewer, surface)[0] == pytest.approx(
            signed_volume(np.asarray(v, float), np.asarray(f)), rel=1e-4), (
            "compaction dropped the reflection or its winding")
        assert np.asarray(surface.layer.data[0])[:, MIRROR_AXIS].mean() == pytest.approx(
            2.0 * session.mirror_center - np.asarray(v, float)[:, MIRROR_AXIS].mean(),
            abs=1e-2)
    finally:
        viewer.close()


@pytest.mark.requires_data
def test_hover_names_the_same_glomerulus_under_the_mirror(registry):
    """A ray through a glomerulus picks it, mirrored or not.

    The view ray comes in the layer's own coordinates, which the mirror
    reflects with the vertices, and the pick tests the MeshSet's: the ray
    has to be reflected back, or hover names the wrong side.
    """
    napari = pytest.importorskip("napari")
    viewer = napari.Viewer(show=False, ndisplay=3)
    try:
        session = load_space(viewer, registry, "GRABE", fit=False)
        viewer.dims.ndisplay = 3
        surface = next(iter(session.surfaces.values()))
        rays = []
        for index in range(0, surface.meshset.n_compartments, 9):
            v, _ = surface.meshset.compartment(index)
            rays.append((np.asarray(v, float).mean(axis=0), np.array([0.3, 0.2, 0.93])))
        plain = [surface.pick(c, d, (0, 1, 2)) for c, d in rays]
        assert sum(hit is not None for hit in plain) >= len(rays) // 2, plain

        session.set_mirror(True)
        center = session.mirror_center
        mirrored = []
        for c, d in rays:
            c, d = c.copy(), d.copy()
            c[MIRROR_AXIS] = 2.0 * center - c[MIRROR_AXIS]
            d[MIRROR_AXIS] = -d[MIRROR_AXIS]
            mirrored.append(surface.pick(c, d, (0, 1, 2)))
        assert mirrored == plain
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
        for layer in session.affine_layers():
            affine = np.asarray(layer.affine.affine_matrix)
            assert affine[MIRROR_AXIS, MIRROR_AXIS] == pytest.approx(-1.0), (
                f"{layer.name} was not reflected"
            )
        for surf in session.surfaces.values():
            assert surf.mirrored, f"{surf.name} was not reflected"

        assert np.array_equal(surface.meshset.compartment(0)[0], vertices), (
            "the mirror rewrote the MeshSet instead of what is uploaded"
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
        for surf in session.surfaces.values():
            assert not surf.mirrored, f"{surf.name} stayed reflected"
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
