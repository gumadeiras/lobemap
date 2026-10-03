"""Turning the view in the real spaces, as `lobemap view` opens them.

The rules are proven on synthetic data in `test_turned_view.py`; here each
space is opened with its own meshes and images and checked for what can go
wrong only with real data: the contours against trimesh on a real atlas,
the image and contours sharing one placement, Home and the triads in 3D,
rest given back to the bit, a switch, and a scene torn down while turned.
"""

from __future__ import annotations

import numpy as np
import pytest
import turned_harness as th
from viewer_harness import SPACES, launched, pump, session, switch_to

napari = pytest.importorskip("napari")

pytestmark = pytest.mark.requires_data


def _open(registry, space, ndisplay):
    from lobemap.viewer.app import load_space

    viewer = napari.Viewer(show=False, ndisplay=ndisplay)
    sess = load_space(viewer, registry, space, fit=False)
    th.settle_canvas(viewer)
    return viewer, sess


def _center_on_the_atlas(viewer, sess) -> None:
    """Center the 2D view on the primary atlas, on a slider plane through it:
    the pivot a turn keeps, so the turned plane cuts the atlas."""
    name = sess.registry.primary_atlas(sess.space).id
    surface, contour = sess.surfaces[name], sess.contours[name]
    # The largest compartment's center: every plane through it cuts it.
    largest = int(np.argmax(np.diff(surface.meshset.vertex_offsets)))
    # Through the contour layer, which carries the mirror. At rest.
    middle = np.asarray(contour.layer.data_to_world(surface.meshset.centroid(largest)),
                        float)
    axis = int(viewer.dims.order[0])
    start, _stop, step = viewer.dims.range[axis]
    viewer.dims.set_current_step(axis, round((middle[axis] - start) / step))
    center = list(viewer.scene.camera.center)
    center[-2:] = middle[list(viewer.dims.displayed)]
    viewer.scene.camera.center = tuple(center)
    th.settle_canvas(viewer)


def _contour_vs_trimesh(viewer, sess, to_mesh=None, tol_um=2e-4) -> int:
    """Every loop of the primary atlas against trimesh; the count compared."""
    name = sess.registry.primary_atlas(sess.space).id
    contour = sess.contours[name]
    axis = int(viewer.dims.order[0])
    shown = list(viewer.dims.displayed)
    world = np.zeros((3, 3))
    world[:, axis] = float(viewer.dims.point[axis])
    world[1, shown[0]] += 10.0
    world[2, shown[1]] += 10.0
    plane = np.array([contour.layer.world_to_data(w) for w in world], float)
    if to_mesh is not None:
        plane = to_mesh(plane)
    normal = np.cross(plane[1] - plane[0], plane[2] - plane[0])
    by_owner: dict[int, list] = {}
    for owner, loop in th.loops_in_mesh(contour, to_mesh):
        by_owner.setdefault(owner, []).append(loop)
    for owner, drawn in by_owner.items():
        want = th.trimesh_loops(contour.meshset, owner, plane[0], normal)
        assert want and th.hausdorff(drawn, want) <= tol_um, (sess.space, owner)
    return len(by_owner)


@pytest.mark.parametrize("space", SPACES)
def test_a_spun_section_in_every_space(registry, space):
    """Exact contours, the images placed with them, and rest to the bit."""
    viewer, sess = _open(registry, space, 2)
    try:
        before, pixels = th.state(viewer), th.render(viewer)
        for mirrored in (False, True):
            sess.set_mirror(mirrored)
            for spin in (37.0, 90.0, 180.0):
                sess.set_rotation(spin, 0, 0)
                th.settle_canvas(viewer)
                assert _contour_vs_trimesh(viewer, sess) > 0
                name = sess.registry.primary_atlas(space).id
                contour = sess.contours[name]
                m = contour.meshset.vertices[:: max(1, len(contour.meshset.vertices) // 50)]
                for image in sess.images:
                    got = np.array([image.world_to_data(contour.layer.data_to_world(p))
                                    for p in m])
                    want = (np.asarray(m, float) - np.asarray(image.translate)) / np.asarray(
                        image.scale)
                    assert np.allclose(got, want, atol=1e-6), (space, image.name)
            sess.set_rotation(0, 0, 0)
        sess.set_mirror(False)
        th.settle_canvas(viewer)
        assert th.state(viewer) == before
        assert np.array_equal(th.render(viewer), pixels)
    finally:
        viewer.close()
        pump()


@pytest.mark.parametrize("space", SPACES)
def test_3d_faces_home_turned_in_every_space(registry, space):
    from lobemap.core.model import anatomical_axes
    from lobemap.viewer.rotation import turned_view

    viewer, sess = _open(registry, space, 3)
    try:
        camera = viewer.scene.camera
        frame = anatomical_axes(registry.spaces[space])
        view0, up0 = -np.asarray(frame["A"]), np.asarray(frame["D"])
        placed = [np.asarray(layer.affine.affine_matrix) for layer in viewer.layers]
        before = th.state(viewer)
        for angles in ((37, 0, 0), (0, 37, 0), (15, -60, 120)):
            sess.set_rotation(*angles)
            v, u = turned_view(view0, up0, angles)
            assert np.allclose(camera.view_direction, v, atol=1e-6)
            assert np.allclose(camera.up_direction, u, atol=1e-6)
            assert all(np.array_equal(p, layer.affine.affine_matrix)
                       for p, layer in zip(placed, viewer.layers, strict=True))
        sess.set_rotation(0, 0, 0)
        assert th.state(viewer) == before
    finally:
        viewer.close()
        pump()


def test_a_turn_is_set_right_after_a_switch_and_torn_down_with_its_scene(monkeypatch):
    """The switcher hands the new scene the old one's angles; nothing of a
    scene torn down while turned stays behind."""
    from napari.components.layerlist import LayerList
    from viewer_harness import handler_counts

    from lobemap.viewer import rotation

    with launched(monkeypatch, "view", "GRABE", "--ndisplay", "2") as (code, viewer):
        assert code == 0
        old = session(viewer)
        th.settle_canvas(viewer)
        counts = handler_counts(viewer)
        old.set_rotation(30, 0, 0)
        assert rotation.owner(viewer) is old.turned
        for target, ndisplay in (("JRCFIB2018F", 2), ("GRABE", 3), ("FAFB14", 2)):
            viewer.dims.ndisplay = ndisplay
            switch_to(viewer, target)
            new = session(viewer)
            assert new is not old and new.space == target
            assert type(viewer.layers) is LayerList
            assert rotation.owner(viewer) is new.turned
            new.set_rotation(*old.rotation)
            th.settle_canvas(viewer)
            assert new.rotation == (30.0, 0.0, 0.0)
            if ndisplay == 2:
                assert _contour_vs_trimesh(viewer, new) > 0
            old = new
        old.set_rotation(0, 0, 0)
        viewer.dims.ndisplay = 2
        assert handler_counts(viewer) == counts


# -- across the grid ---------------------------------------------------------

#: The stain or stack each space shows, for the texel checks.
IMAGES = {"FAFB14": "fafb_stain", "JRCFIB2018F": "hemibrain_stain",
          "JRCFIB2022M": "malecns_stain", "GRABE": "grabe2015_stack"}


def _texels_against_the_source(viewer, sess, layer, registry, n=400) -> int:
    """napari's texels of a turned image against the image's own voxels,
    sampled here at each texel's specimen point; the number compared.

    Each texel's world point comes from napari's own transforms; its
    specimen point from the contour layer's transform and frame; the value
    from the volume as the registry reads it, trilinearly (nearest voxel for
    labels), on the voxel centers of the pyramid level of the image's at
    or below the texel's spacing (`core.zarrfmt`).
    """
    from scipy.ndimage import map_coordinates

    from lobemap.core.zarrfmt import pyramid_levels

    contour = next(iter(sess.contours.values()))
    raw = np.asarray(layer._slice.image.raw, float)
    if raw.size == 0:
        return 0
    tile = layer._transforms["tile2data"]
    dims = viewer.dims
    axis, shown = int(dims.order[0]), list(dims.displayed)
    plane = np.round(np.asarray(layer.world_to_data(dims.point), float)[axis])
    rng = np.random.default_rng(7)
    rows = rng.integers(0, raw.shape[0], n)
    cols = rng.integers(0, raw.shape[1], n)
    full = np.zeros((n, 3))
    full[:, shown[0]], full[:, shown[1]] = rows, cols
    data = np.asarray(tile(full), float)
    data[:, axis] = plane
    world = np.array([layer.data_to_world(d) for d in data])
    q = np.array([contour.layer.world_to_data(w) for w in world])
    m = contour.frame.inverse(q)
    asset = layer.metadata["lobemap"]["asset"]
    volume = registry.volume(asset)
    labels = layer.metadata["lobemap"]["kind"] == "labels"
    levels = list(volume.levels) if volume.is_multiscale else [np.asarray(volume.data)]
    voxel = (m - np.asarray(volume.origin_um)) / np.asarray(volume.voxel_um)
    shapes = np.array(layer.level_shapes, float)
    # The level's nominal spacing, a power of the square root of two; its
    # shape is rounded up, so the ratio of shapes is a hair under it.
    ratio = (shapes[0] / shapes[layer.data_level])[shown].max() if layer.multiscale else 1.0
    spacing = np.sqrt(2.0) ** np.round(np.log(ratio) / np.log(np.sqrt(2.0)))
    factors = [np.asarray(f, float) for _s, f in pyramid_levels(levels[0].shape)][:len(levels)]
    use = max(i for i, f in enumerate(factors) if f[shown].max() <= spacing * (1 + 1e-9))
    f = factors[use]
    at = ((voxel - (f - 1.0) / 2.0) / f).T
    source = levels[use]
    lo = np.maximum(np.floor(at.min(axis=1)).astype(int) - 1, 0)
    hi = np.minimum(np.ceil(at.max(axis=1)).astype(int) + 2, source.shape)
    box = np.asarray(source[tuple(slice(a, b) for a, b in zip(lo, hi, strict=True))], float)
    want = map_coordinates(box, at - lo[:, None], order=0 if labels else 1, mode="constant",
                           cval=0, prefilter=False)
    got = raw[rows, cols]
    inside = np.all((at >= 1) & (at <= np.asarray(source.shape)[:, None] - 2), axis=0)
    assert inside.sum() > n // 4
    tol = 0.0 if labels else 0.5 + 1e-6            # rounded to the data's integers
    assert np.abs(got[inside] - np.round(want[inside], 6)).max() <= tol, asset
    return int(inside.sum())


@pytest.mark.parametrize("space", SPACES)
def test_an_oblique_section_in_every_space(registry, space):
    """Exact contours, the image sampled where each texel is drawn, no
    warning, and rest to the bit, with and without the mirror."""
    import warnings

    viewer, sess = _open(registry, space, 2)
    try:
        _center_on_the_atlas(viewer, sess)
        before, pixels = th.state(viewer), th.render(viewer)
        rest_view = (viewer.dims.point, tuple(viewer.scene.camera.center))
        with warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter("always")
            for mirrored in (False, True):
                sess.set_mirror(mirrored)
                _center_on_the_atlas(viewer, sess)
                for angles in ((0, 37, 0), (20, 37, 15), (90, 0, 180)):
                    sess.set_rotation(*angles)
                    th.settle_canvas(viewer)
                    contour = next(iter(sess.contours.values()))
                    assert contour.frame is not None
                    assert _contour_vs_trimesh(viewer, sess, th.to_mesh(contour)) > 0
                    for layer in sess.images:
                        if layer.visible and layer.metadata["lobemap"]["asset"] == IMAGES[space]:
                            assert _texels_against_the_source(viewer, sess, layer, registry)
                sess.set_rotation(0, 0, 0)
            sess.set_mirror(False)
        viewer.dims.point, viewer.scene.camera.center = rest_view
        noise = [w for w in caught if issubclass(w.category, (RuntimeWarning, UserWarning))
                 and "lobemap" not in str(w.filename)]
        assert not noise, [str(w.message)[:80] for w in noise]
        th.settle_canvas(viewer)
        assert th.state(viewer) == before
        assert np.array_equal(th.render(viewer), pixels)
    finally:
        viewer.close()
        pump()


def test_a_part_built_while_turned_is_cut_on_the_turned_plane(registry):
    viewer, sess = _open(registry, "FAFB14", 2)
    try:
        _center_on_the_atlas(viewer, sess)
        sess.set_rotation(20, 37, 15)
        th.settle_canvas(viewer)
        surface, contour = sess.realize("fafb_neuropil")
        surface.show_all()
        th.settle_canvas(viewer)
        assert contour.frame is not None
        assert contour.frame.key == sess.contours["benton2025"].frame.key
        origin, normal = th.plane_in_mesh(viewer, contour)
        drawn: dict[int, list] = {}
        for owner, loop in th.loops_in_mesh(contour, th.to_mesh(contour)):
            drawn.setdefault(owner, []).append(loop)
        assert drawn
        for owner, loops in drawn.items():
            want = th.trimesh_loops(contour.meshset, owner, origin, normal)
            assert th.hausdorff(loops, want) <= 2e-4, owner
    finally:
        viewer.close()
        pump()


def test_a_label_volume_shown_while_turned_shows_the_turned_plane(registry):
    viewer, sess = _open(registry, "GRABE", 2)
    try:
        _center_on_the_atlas(viewer, sess)
        labels = next(layer for layer in sess.images
                      if layer.metadata["lobemap"]["kind"] == "labels")
        assert not labels.visible
        sess.set_rotation(0, 37, 0)
        th.settle_canvas(viewer)
        labels.visible = True
        th.settle_canvas(viewer)
        assert _texels_against_the_source(viewer, sess, labels, registry)
        assert len(viewer.layers) == len(sess.all_layers())
    finally:
        viewer.close()
        pump()


@pytest.mark.parametrize("space", SPACES)
def test_aligned_sections_in_every_space(registry, space):
    """At zero angles the aligned section is perpendicular to the anatomical
    axis nearest each slice axis -- 15 to 32 degrees off it -- exact, and
    the alignment off gives back the view."""
    from lobemap.core.model import anatomical_axes
    from lobemap.viewer.slicing import slice_axes

    viewer, sess = _open(registry, space, 2)
    try:
        frame = anatomical_axes(registry.spaces[space])
        names = {"Anterior-Posterior": "A", "Dorsal-Ventral": "D", "Left-Right": "R"}
        for choice in slice_axes(registry.spaces[space]):
            sess.set_slice_axis(choice.axis)
            _center_on_the_atlas(viewer, sess)
            before = th.state(viewer)
            sess.set_aligned(True)
            th.settle_canvas(viewer)
            contour = sess.contours[registry.primary_atlas(space).id]
            _origin, normal = th.plane_in_mesh(viewer, contour)
            pole = np.asarray(frame[names[choice.anatomy]], float)
            cos = abs(normal @ pole) / np.linalg.norm(normal)
            assert cos == pytest.approx(1.0, abs=1e-9), (choice.label, cos)
            grid = np.eye(3)[choice.axis]
            off = np.degrees(np.arccos(abs(normal @ grid) / np.linalg.norm(normal)))
            assert off == pytest.approx(choice.degrees, abs=0.05), choice.label
            assert _contour_vs_trimesh(viewer, sess, th.to_mesh(contour)) > 0
            for layer in sess.images:
                if layer.visible and layer.metadata["lobemap"]["asset"] == IMAGES[space]:
                    assert _texels_against_the_source(viewer, sess, layer, registry)
            sess.set_aligned(False)
            th.settle_canvas(viewer)
            assert th.state(viewer) == before
    finally:
        viewer.close()
        pump()


def test_rest_puts_back_every_hidden_slider(registry):
    """The repro of the in-plane prototype's hidden-slider bug: slice along
    y, then along x, spin, rest, and along y again lands on the same plane."""
    viewer, sess = _open(registry, "JRCFIB2018F", 2)
    try:
        sess.set_slice_axis(1)
        plane = viewer.dims.point[1]
        sess.set_slice_axis(0)
        before = tuple(viewer.dims.point), tuple(tuple(r) for r in viewer.dims.range)
        for spin in [*range(1, 91), 30]:
            sess.set_rotation(float(spin), 0, 0)
        sess.set_rotation(0, 0, 0)
        assert (tuple(viewer.dims.point), tuple(tuple(r) for r in viewer.dims.range)) == before
        sess.set_slice_axis(1)
        assert viewer.dims.point[1] == plane
    finally:
        viewer.close()
        pump()
