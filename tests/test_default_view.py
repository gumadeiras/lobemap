"""The camera the GUI opens with, and the atlas it opens with.

Anatomical axes differ between spaces -- hemibrain's antero-posterior axis is
y where FAFB's is z -- so they are declared per space and measured, never
assumed. A camera pointed down the wrong axis still renders something, which
is why this is tested rather than eyeballed.
"""

from __future__ import annotations

import numpy as np
import pytest

from lobemap.core.model import Space, anatomical_axes, axis_vector
from lobemap.core.registry import Registry


@pytest.mark.parametrize(
    ("spec", "expect"),
    [("-z", (0, 0, -1)), ("+y", (0, 1, 0)), ("y", (0, 1, 0)), ("-X", (-1, 0, 0))],
)
def test_axis_vector(spec, expect):
    assert np.allclose(axis_vector(spec), expect)


def test_axis_vector_rejects_nonsense():
    for bad in ("", "-w", "up", "zz"):
        with pytest.raises(ValueError, match="axis reference"):
            axis_vector(bad)


#: Determined twice over, from positional nomenclature and from handedness.
@pytest.mark.requires_data
def test_left_al_lands_on_the_viewers_right_except_in_fafb(registry_root):
    """The handedness convention, which fixes the sign of dorsal.

    Screen right is view x up. Getting that cross product backwards inverts
    dorsal, which renders the brain upside down and looks like a camera bug.
    """
    reg = Registry.load(registry_root)
    cases = {
        "FAFB14": ("fafb_neuropil", "AL_L", "AL_R", -1),
        "JRCFIB2018F": ("neuprint_hemibrain_neuropil", "AL(L)", "AL(R)", +1),
        "JRCFIB2022M": ("neuprint_cns_neuropil", "AL(L)", "AL(R)", +1),
        "GRABE": ("grabe2015_glomeruli", "DA1(L)", "DA1(R)", +1),
    }
    for space_id, (asset, left, right_name, want) in cases.items():
        space = reg.spaces[space_id]
        ms = reg.mesh(asset)

        def centroid(name, ms=ms):
            i = ms.names.index(name)
            a, b = int(ms.vertex_offsets[i]), int(ms.vertex_offsets[i + 1])
            return ms.vertices[a:b].mean(0)

        frame = anatomical_axes(space)
        view, up = -frame["A"], frame["D"]
        screen_right = np.cross(view, up)
        offset = float(np.dot(centroid(left) - centroid(right_name), screen_right))
        assert (offset > 0) == (want > 0), (space_id, offset)


@pytest.mark.requires_data
def test_the_antennal_lobes_lie_anterior_in_fafb(registry_root):
    """A third, independent check on the anterior axis alone.

    The landmark is the union of all 78 neuropils, which is what stands in
    for a brain outline now that the Bates Plotly brain mesh is gone.
    """
    reg = Registry.load(registry_root)
    brain = reg.mesh("fafb_neuropil").vertices
    mid = (brain.min(0) + brain.max(0)) / 2
    al = reg.mesh("benton2025_glomeruli").vertices.mean(0)
    anterior = anatomical_axes(reg.spaces["FAFB14"])["A"]
    assert np.dot(al - mid, anterior) > 0, "ALs must be on the anterior side"


def test_every_space_opens_with_exactly_one_atlas_and_its_image(registry_root):
    """Two atlases stacked at startup is unreadable; that is the whole point.

    This used to read the answer out of a scene preset. There is no preset
    now: the space names its primary atlas, and the image comes along
    because an image is shown whenever it is on disk.
    """
    reg = Registry.load(registry_root)
    expected = {
        "FAFB14": ("benton2025", "fafb_stain"),
        "JRCFIB2018F": ("neuprint_hemibrain", "hemibrain_stain"),
        "JRCFIB2022M": ("neuprint_cns", "malecns_stain"),
        "GRABE": ("grabe2015", "grabe2015_stack"),
    }
    for space_id, (atlas, image) in expected.items():
        primary = reg.primary_atlas(space_id)
        assert primary is not None and primary.id == atlas, space_id
        images = [a.id for a in reg.assets_in_space(space_id)
                  if a.kind == "image"]
        assert images == [image], (space_id, images)


def test_spaces_with_an_atlas_all_declare_a_default(registry_root):
    reg = Registry.load(registry_root)
    for space_id, space in reg.spaces.items():
        if reg.atlases_in_space(space_id):
            assert space.primary_atlas, f"{space_id} has atlases but no primary"


def test_the_other_atlases_of_a_space_are_still_loaded(registry_root):
    """Not shown is not the same as not there.

    JRCFIB2018F is the case the whole design exists for: three
    parcellations of one volume, superposable because they share a space.
    Opening on one of them must not mean the other two are absent.
    """
    reg = Registry.load(registry_root)
    here = {a.id for a in reg.atlases_in_space("JRCFIB2018F")}
    assert here == {"neuprint_hemibrain", "schlegel2021_s11",
                    "schlegel2021_s12"}
    assert reg.primary_atlas("JRCFIB2018F").id == "neuprint_hemibrain"


def test_registry_rejects_an_unknown_primary_atlas(registry_root):
    from lobemap.core.registry import RegistryError

    reg = Registry.load(registry_root, validate=False)
    reg.spaces["FAFB14"] = Space(id="FAFB14", title="x", units="um",
                                 primary_atlas="no_such_atlas")
    with pytest.raises(RegistryError, match="no_such_atlas"):
        reg.validate()


def test_several_atlases_and_no_primary_is_a_registry_error(registry_root):
    """Otherwise the viewer picks one and the choice is invisible."""
    from dataclasses import replace

    from lobemap.core.registry import RegistryError

    reg = Registry.load(registry_root, validate=False)
    reg.spaces["JRCFIB2018F"] = replace(reg.spaces["JRCFIB2018F"],
                                        primary_atlas=None)
    with pytest.raises(RegistryError, match="no primary_atlas"):
        reg.validate()


# -- the camera itself ---------------------------------------------------


@pytest.fixture
def viewer():
    napari = pytest.importorskip("napari")
    v = napari.Viewer(ndisplay=3, show=False)
    yield v
    v.close()


def test_orient_anterior_points_the_camera_down_the_measured_axis(viewer):
    from lobemap.viewer.app import GIMBAL_NUDGE_DEG, orient_anterior

    space = Space(id="S", title="s", units="um",
                  anatomical_rotation_axis=(0.0, 1.0, 0.0),
                  anatomical_rotation_deg=90.0)
    assert orient_anterior(viewer, space) is True
    cam = getattr(viewer, "scene", viewer).camera
    # Camera sits anterior and looks posteriorly, i.e. along +z, less the
    # small yaw that keeps it off the gimbal singularity.
    off = np.degrees(np.arccos(np.clip(
        np.dot(np.asarray(cam.view_direction), (0, 0, 1)), -1, 1)))
    assert off == pytest.approx(GIMBAL_NUDGE_DEG, abs=0.01)
    assert np.dot(np.asarray(cam.up_direction), (0, 1, 0)) > 0.99


def test_an_exactly_axis_aligned_camera_is_flipped_by_napari(viewer):
    """Why `GIMBAL_NUDGE_DEG` exists. Pins the napari behavior.

    At exact gimbal lock napari's vispy round trip -- angles to quaternion and
    back -- cannot recover the third Euler angle and zeroes it, which returns
    a NEGATED up vector. The brain renders upside down with no error. If this
    test starts failing, napari has fixed it and the nudge can go.
    """
    from napari._vispy.camera import (
        napari_angles_to_vispy_quat as forward,
    )
    from napari._vispy.camera import (
        vispy_quat_to_napari_angles as backward,
    )
    from napari.components.camera import Camera

    def round_trip(view, up):
        cam = Camera()
        cam.set_view_direction(view_direction=view, up_direction=up)
        angles = backward(forward(np.array(cam.angles), (False,) * 3),
                          (False,) * 3)
        out = Camera()
        out.angles = tuple(angles)
        return np.asarray(out.up_direction)

    assert np.dot(round_trip((0, 0, 1), (0, 1, 0)), (0, 1, 0)) < -0.99, (
        "napari no longer inverts an axis-aligned camera; drop the nudge"
    )
    eps = np.tan(np.radians(1.0))
    nudged = np.array([eps, 0.0, 1.0])
    nudged /= np.linalg.norm(nudged)
    assert np.dot(round_trip(tuple(nudged), (0, 1, 0)), (0, 1, 0)) > 0.99


def test_the_nudge_survives_the_round_trip_for_every_space(registry_root):
    from napari._vispy.camera import (
        napari_angles_to_vispy_quat as forward,
    )
    from napari._vispy.camera import (
        vispy_quat_to_napari_angles as backward,
    )
    from napari.components.camera import Camera

    from lobemap.viewer.app import orient_anterior

    napari = pytest.importorskip("napari")
    reg = Registry.load(registry_root)
    viewer = napari.Viewer(ndisplay=3, show=False)
    try:
        for space_id, space in reg.spaces.items():
            dorsal = anatomical_axes(space)["D"]
            assert orient_anterior(viewer, space) is True
            cam = getattr(viewer, "scene", viewer).camera
            angles = backward(forward(np.array(cam.angles), (False,) * 3),
                              (False,) * 3)
            after = Camera()
            after.angles = tuple(angles)
            assert np.dot(np.asarray(after.up_direction),
                          dorsal) > 0.99, space_id
    finally:
        viewer.close()


def test_a_space_without_a_rotation_is_left_alone(viewer):
    """A rotation is the only statement of anatomy, and half a frame --
    a view direction with no up -- would face the right way at an
    arbitrary roll, which is worse than not trying."""
    from lobemap.viewer.app import orient_anterior

    before = tuple(getattr(viewer, "scene", viewer).camera.view_direction)
    space = Space(id="S", title="s", units="um")
    assert orient_anterior(viewer, space) is False
    after = tuple(getattr(viewer, "scene", viewer).camera.view_direction)
    assert before == after


def test_orientation_is_skipped_in_2d(viewer):
    from lobemap.viewer.app import orient_anterior

    viewer.dims.ndisplay = 2
    space = Space(id="S", title="s", units="um",
                  anatomical_rotation_axis=(0.0, 1.0, 0.0),
                  anatomical_rotation_deg=90.0)
    assert orient_anterior(viewer, space) is False


def test_fit_view_keeps_the_orientation(viewer):
    """reset_view resets camera angles by default, which would undo it."""
    from lobemap.viewer.app import fit_view, orient_anterior

    viewer.add_image(np.zeros((40, 30, 20), np.uint8))
    space = Space(id="S", title="s", units="um",
                  anatomical_rotation_axis=(0.0, 1.0, 0.0),
                  anatomical_rotation_deg=90.0)
    orient_anterior(viewer, space)
    fit_view(viewer)
    cam = getattr(viewer, "scene", viewer).camera
    assert np.dot(np.asarray(cam.view_direction), (0, 0, 1)) > 0.999
    assert np.dot(np.asarray(cam.up_direction), (0, 1, 0)) > 0.99
    assert cam.zoom > 0


def test_a_space_with_no_atlases_has_no_primary(registry_root):
    """Nothing to open means nothing to open ON, rather than a crash."""
    reg = Registry.load(registry_root, validate=False)
    reg.spaces["EMPTY"] = Space(id="EMPTY", title="empty", units="um")
    assert reg.primary_atlas("EMPTY") is None


def test_the_initial_fit_follows_the_canvas(viewer):
    """Maximizing is asynchronous, so a fit done once lands on the wrong size.

    Measured through the real startup, before and after: FAFB 42% -> 81% of
    the canvas, Grabe 50% -> 96%, hemibrain 57% -> 96%, male CNS -> 97%.
    """
    from lobemap.viewer.app import install_initial_fit

    viewer.add_image(np.zeros((40, 30, 20), np.uint8))
    assert install_initial_fit(viewer) is True
    cam = getattr(viewer, "scene", viewer).camera
    assert cam.zoom > 0


def test_the_initial_fit_watches_napari_canvas_not_the_widget(viewer):
    """`fit_to_view` divides by `viewer.canvas.size`, which lags the widget.

    Watching the Qt widget instead is why FAFB kept its 900x700 zoom while
    other spaces happened to refit correctly.
    """
    import inspect

    from lobemap.viewer.app import install_initial_fit

    source = inspect.getsource(install_initial_fit)
    assert 'getattr(viewer, "canvas", None)' in source
    assert "native" not in source


def test_the_initial_fit_survives_a_viewer_without_a_canvas():
    """Headless runs have no Qt viewer to hang the callback on."""
    from lobemap.viewer.app import install_initial_fit

    class _Dummy:
        class window:
            pass

        def reset_view(self, **_kw):
            self.reset = True

    dummy = _Dummy()
    assert install_initial_fit(dummy) is False
    assert getattr(dummy, "reset", False) is True


# -- the home button -----------------------------------------------------


def _home(viewer):
    viewer.window._qt_viewer.viewerButtons.resetViewButton.click()


@pytest.mark.requires_data
@pytest.mark.parametrize(
    "space_id", ["FAFB14", "JRCFIB2018F", "JRCFIB2022M", "GRABE"]
)
def test_home_looks_down_a_p_with_dorsal_up(registry_root, space_id):
    """`reset_view` sets the camera angles to (0, 0, 0), a view down the
    ARRAY axes. Those are not the anatomical ones, so the home button used
    to leave the brain at an arbitrary attitude."""
    napari = pytest.importorskip("napari")

    from lobemap.viewer.app import load_space

    reg = Registry.load(registry_root)
    try:
        viewer = napari.Viewer(show=False, ndisplay=3)
    except Exception as exc:                        # pragma: no cover
        pytest.skip(f"no Qt display: {exc}")
    try:
        load_space(viewer, reg, space_id, fit=True)
        space = reg.spaces[space_id]
        frame = anatomical_axes(space)
        anterior, dorsal = frame["A"], frame["D"]

        viewer.camera.angles = (17, 42, -63)        # the user rotates
        _home(viewer)

        view = np.asarray(viewer.camera.view_direction)
        up = np.asarray(viewer.camera.up_direction)
        # Looking POSTERIORLY means the view runs against anterior.
        assert float(np.dot(view, anterior)) < -0.99, (space_id, view)
        assert float(np.dot(up, dorsal)) > 0.99, (space_id, up)
    finally:
        viewer.close()


@pytest.mark.requires_data
def test_home_survives_a_scene_switch(registry_root):
    """The wrapper is installed once and re-pointed, not stacked."""
    napari = pytest.importorskip("napari")

    from lobemap.viewer.app import load_space

    reg = Registry.load(registry_root)
    try:
        viewer = napari.Viewer(show=False, ndisplay=3)
    except Exception as exc:                        # pragma: no cover
        pytest.skip(f"no Qt display: {exc}")
    try:
        load_space(viewer, reg, "FAFB14", fit=False)
        first = viewer.__dict__.get("reset_view")
        viewer.layers.clear()
        load_space(viewer, reg, "JRCFIB2018F", fit=False)
        assert viewer.__dict__.get("reset_view") is first, "wrapper stacked"

        viewer.camera.angles = (5, 5, 5)
        _home(viewer)
        anterior = anatomical_axes(reg.spaces["JRCFIB2018F"])["A"]
        view = np.asarray(viewer.camera.view_direction)
        assert float(np.dot(view, anterior)) < -0.99, (
            "home re-oriented to the previous space"
        )
    finally:
        viewer.close()


@pytest.mark.requires_data
def test_a_fit_that_keeps_the_angle_is_not_re_oriented(registry_root):
    """`fit_view` passes `reset_camera_angle=False` on purpose, so it must
    leave whatever the user is looking at alone."""
    napari = pytest.importorskip("napari")

    from lobemap.viewer.app import fit_view, load_space

    reg = Registry.load(registry_root)
    try:
        viewer = napari.Viewer(show=False, ndisplay=3)
    except Exception as exc:                        # pragma: no cover
        pytest.skip(f"no Qt display: {exc}")
    try:
        load_space(viewer, reg, "FAFB14", fit=False)
        viewer.camera.angles = (17, 42, -63)
        fit_view(viewer)
        assert tuple(round(a) for a in viewer.camera.angles) == (17, 42, -63)
    finally:
        viewer.close()
