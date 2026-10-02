"""Per-glomerulus slice labels, and the visibility bug that hid the contours.

Contours never drawing on entry to 2D was invisible in code review: the layers
existed, the refresh ran, and it returned early because nothing had set them
visible. So visibility on a mode switch is tested, not assumed.
"""

from __future__ import annotations

import numpy as np
import pytest

from lobemap.core.meshfmt import MeshSet
from lobemap.viewer import contours as contours_module
from lobemap.viewer.contours import ContourOverlay

napari = pytest.importorskip("napari")


def _two_boxes():
    """Two separated unit cubes, so a plane can cut one, both, or neither."""
    import trimesh

    parts = []
    for name, shift in (("DA1", 0.0), ("DM1", 5.0)):
        box = trimesh.creation.box(extents=(2, 2, 2))
        box.apply_translation((shift, 0, 0))
        parts.append((name, np.asarray(box.vertices, np.float32),
                      np.asarray(box.faces)))
    return MeshSet.from_parts(parts, meta={"units": "um"})


@pytest.fixture
def overlay():
    viewer = napari.Viewer(ndisplay=2, show=False)
    ms = _two_boxes()
    ov = ContourOverlay(viewer, ms, name="test", color="#ff0000", axis=2)
    ov.layer.visible = True
    # install() is what wires the slider to refresh(); without it moving the
    # plane changes nothing and a slider test would pass vacuously.
    contours_module.install(viewer, {"test": ov})
    # An empty Shapes layer leaves dims at its default midpoint, nowhere near
    # the boxes, so the plane has to be put through them explicitly.
    viewer.dims.set_point(2, 0.0)
    yield ov
    viewer.close()


def test_labels_are_off_by_default(overlay):
    """Several atlases in one scene would write each name once per atlas."""
    assert overlay.labels == set()
    overlay.refresh()
    assert all(not s for s in np.atleast_1d(overlay.layer.text.values))


def test_ticking_one_glomerulus_labels_only_that_one(overlay):
    overlay.set_labels([0])
    shown = {str(s) for s in np.atleast_1d(overlay.layer.text.values) if s}
    assert shown == {"DA1"}


def test_set_label_toggles_independently(overlay):
    assert len(overlay.layer.data) == 2, "the plane must cut both boxes"
    overlay.set_label(0, True)
    overlay.set_label(1, True)
    assert {str(s) for s in np.atleast_1d(overlay.layer.text.values) if s} == {
        "DA1", "DM1"}
    overlay.set_label(0, False)
    assert {str(s) for s in np.atleast_1d(overlay.layer.text.values) if s} == {"DM1"}


def test_one_string_per_shape(overlay):
    """napari requires the counts to agree, so text is set after data."""
    overlay.set_labels([0, 1])
    overlay.refresh()
    assert len(np.atleast_1d(overlay.layer.text.values)) == len(overlay.layer.data)


def test_a_name_is_written_once_even_across_several_contours():
    """A concave or multi-body compartment crosses a plane more than once."""
    import trimesh

    viewer = napari.Viewer(ndisplay=2, show=False)
    try:
        # One compartment made of two disjoint bodies, like Bates's VP1l.
        boxes = [trimesh.creation.box(extents=(2, 2, 2)),
                 trimesh.creation.box(extents=(2, 2, 2))]
        boxes[1].apply_translation((6, 0, 0))
        merged = trimesh.util.concatenate(boxes)
        ms = MeshSet.from_parts(
            [("VP1l", np.asarray(merged.vertices, np.float32),
              np.asarray(merged.faces))], meta={"units": "um"})
        ov = ContourOverlay(viewer, ms, name="t", color="#00ff00", axis=2)
        ov.layer.visible = True
        viewer.dims.set_point(2, 0.0)
        ov.set_labels([0])
        paths, owners = ov.contours_at(0.0)
        assert len(paths) > 1, "expected several contours from one compartment"
        strings = ov._label_strings(owners, paths)
        assert sum(1 for s in strings if s) == 1, strings
    finally:
        viewer.close()


def test_labels_survive_moving_the_slider(overlay):
    overlay.set_labels([0, 1])
    for position in (0.0, 0.5, -0.5):
        overlay.viewer.dims.set_point(2, position)
        shown = {str(s) for s in np.atleast_1d(overlay.layer.text.values) if s}
        assert shown == {"DA1", "DM1"}, (position, shown)


# -- the visibility bug -------------------------------------------------


def test_entering_2d_makes_the_contours_visible():
    """They are added to the viewer before the mode switch runs.

    `_add_contours` puts them in `viewer.layers`, so a guard that only set
    visibility when appending left every contour hidden and nothing drew.
    """
    from pathlib import Path

    from lobemap.core.registry import Registry
    from lobemap.viewer.app import build_scene, install_display_mode

    registry = Registry.load(Path(__file__).resolve().parents[1] / "registry")
    viewer = napari.Viewer(ndisplay=2, show=False)
    try:
        surfaces, contours = build_scene(viewer, registry, "JRCFIB2018F")
        install_display_mode(viewer, surfaces, contours, [])
        atlas = contours["neuprint_hemibrain"]
        assert atlas.layer in viewer.layers
        assert atlas.layer.visible, "contours must be visible on entering 2D"
        # Reference geometry starts hidden in 3D, so it stays hidden here.
        shell = contours["neuprint_hemibrain_neuropil"]
        assert not shell.layer.visible
    finally:
        viewer.close()


def test_a_contour_mirrors_its_surface_across_a_mode_switch():
    from pathlib import Path

    from lobemap.core.registry import Registry
    from lobemap.viewer.app import build_scene, install_display_mode

    registry = Registry.load(Path(__file__).resolve().parents[1] / "registry")
    viewer = napari.Viewer(ndisplay=3, show=False)
    try:
        surfaces, contours = build_scene(viewer, registry, "JRCFIB2018F")
        install_display_mode(viewer, surfaces, contours, [])
        surfaces["neuprint_hemibrain_neuropil"].layer.visible = True
        viewer.dims.ndisplay = 2
        assert contours["neuprint_hemibrain_neuropil"].layer.visible
    finally:
        viewer.close()
