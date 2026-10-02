"""The display mirror reflects the scene without touching the data.

Four things have to hold, and three of them are regressions this file was
written after breaking:

- every layer moves, and the meshes underneath do not;
- each anatomical arrow points where its label says, IN THE MIRRORED VIEW,
  so the triad cannot claim the wrong side;
- no anatomical arrow lands on a world arrow -- and under a mirror the
  world arrows move too, so the sign choice has to be made against where
  they are drawn rather than against +x/+y/+z;
- the normals vispy actually shades with stay outward-facing under the
  mirror, and the vispy node transform stays PROPER. That is the whole
  reason the meshes reflect their own vertices instead of riding on
  `layer.affine`: a determinant -1 node transform flips
  `gl_FrontFacing`, which vispy's smooth shading negates the normal by.
"""

from __future__ import annotations

import numpy as np
import pytest

from lobemap.core.model import anatomical_axes, anatomical_triad
from lobemap.core.registry import Registry
from lobemap.viewer.app import MIRROR_AXIS, load_space

SPACES = ("FAFB14", "JRCFIB2018F", "JRCFIB2022M", "GRABE")


@pytest.fixture(scope="module")
def registry():
    return Registry.load("registry")


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


def _shaded_normals(viewer, surface):
    """(signed volume, share outward) of the geometry as vispy shades it.

    Read off the vispy node rather than the napari layer, because the two
    differ: napari reverses the winding on upload, and in 2D the node
    holds a flat slice of the surface instead of the surface. Both of
    those made an earlier version of this measurement meaningless.
    """
    node = viewer.window._qt_viewer.canvas.layer_to_visual[surface.layer].node
    md = node.mesh_data
    v = np.asarray(md.get_vertices(), float)
    f = np.asarray(md.get_faces())
    n = np.asarray(md.get_vertex_normals(), float)

    a, b, c = v[f[:, 0]], v[f[:, 1]], v[f[:, 2]]
    volume = float(np.einsum("ij,ij->i", a, np.cross(b, c)).sum() / 6.0)

    values = np.asarray(surface.layer.data[2])
    if len(values) != len(v):          # node not in step with the layer
        return volume, float("nan")
    live = np.linalg.norm(n, axis=1) > 1e-12
    first = values == values[0]
    m = live & first
    centre = v[m].mean(axis=0)
    outward = float(np.mean(np.einsum("ij,ij->i", n[m], v[m] - centre) > 0))
    return volume, outward


def _node_determinant(viewer, surface):
    """Determinant of the surface's visual->scene transform.

    Negative means napari is reflecting the geometry for us, which
    reverses the rasterized winding and inverts the shading.
    """
    node = viewer.window._qt_viewer.canvas.layer_to_visual[surface.layer].node
    tr = node.transforms.get_transform("visual", "scene")
    origin = np.asarray(tr.map(np.zeros((3, 3))))[:, :3]
    linear = np.asarray(tr.map(np.eye(3)))[:, :3] - origin
    return float(np.linalg.det(linear))


def test_the_shaded_normals_stay_outward_under_a_mirror(registry):
    """Neither the normals nor the facing may invert.

    The glomeruli are not convex, so 76.8% outward rather than 100% is
    what correct looks like here; what matters is that mirroring does
    not change it, and that the node transform stays proper so
    `gl_FrontFacing` is not flipped underneath it.
    """
    napari = pytest.importorskip("napari")
    viewer = napari.Viewer(show=False)
    try:
        # 3D, or the node holds a planar slice whose volume is zero and
        # whose normals say nothing about the surface.
        viewer.dims.ndisplay = 3
        session = load_space(viewer, registry, "GRABE", fit=False)
        viewer.dims.ndisplay = 3
        surface = next(iter(session.surfaces.values()))

        volume, outward = _shaded_normals(viewer, surface)
        assert volume > 0, "unmirrored geometry is already inside-out"
        assert outward > 0.6, f"unmirrored normals only {outward:.1%} outward"
        assert _node_determinant(viewer, surface) > 0

        session.set_mirror(True)
        mirrored_volume, mirrored_outward = _shaded_normals(viewer, surface)
        assert mirrored_volume == pytest.approx(volume, rel=1e-4), (
            "the reflected geometry is inside-out: the vertices were "
            "reflected without the winding being reversed"
        )
        assert mirrored_outward == pytest.approx(outward, abs=0.02), (
            f"mirroring moved the normals: {outward:.1%} -> "
            f"{mirrored_outward:.1%}"
        )
        assert _node_determinant(viewer, surface) > 0, (
            "the surface is being reflected by its affine, which flips "
            "gl_FrontFacing and inverts the shading"
        )
    finally:
        viewer.close()


def test_the_mirror_reflects_vertices_and_reverses_the_winding(registry):
    """Both, together. Either one alone inverts the shading."""
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
        # One axis negated about the mid-plane, the others untouched.
        other = [k for k in range(3) if k != MIRROR_AXIS]
        assert np.allclose(v1[:, other], v0[:, other], atol=1e-4)
        assert np.allclose(
            v1[:, MIRROR_AXIS] + v0[:, MIRROR_AXIS],
            2.0 * session.mirror_center, atol=1e-2
        ), "the vertices were not reflected about the measured mid-plane"

        # And the surface itself carries no affine, or the shading inverts.
        affine = np.asarray(surface.layer.affine.affine_matrix)
        assert np.allclose(affine, np.eye(affine.shape[0]))
    finally:
        viewer.close()


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
            assert surf._mirror is not None, f"{surf.name} was not reflected"

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
            assert surf._mirror is None
    finally:
        viewer.close()


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


def test_switching_space_clears_the_mirror(registry):
    """A reflected scene must not arrive without being asked for.

    The mirror says which side you are looking at, so carrying it into
    the next space silently is the one piece of state here that could
    make left read as right.
    """
    napari = pytest.importorskip("napari")
    pytest.importorskip("qtpy")
    from lobemap.viewer.switcher import SpaceSwitcher

    viewer = napari.Viewer(show=False)
    try:
        session = load_space(viewer, registry, "GRABE", fit=False)
        switcher = SpaceSwitcher(
            viewer, registry, session,
            lambda space: load_space(viewer, registry, space, fit=False),
        )
        switcher.mirror.setChecked(True)
        assert switcher.session.mirrored

        index = switcher.combo.findData("JRCFIB2022M")
        assert index >= 0
        switcher.combo.setCurrentIndex(index)

        assert switcher.session.space == "JRCFIB2022M"
        assert not switcher.mirror.isChecked(), "the checkbox stayed on"
        assert not switcher.session.mirrored, "the new scene came up mirrored"
        for surface in switcher.session.surfaces.values():
            assert surface._mirror is None
    finally:
        switcher.session.teardown()
        viewer.close()
