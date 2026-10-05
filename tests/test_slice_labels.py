"""Per-glomerulus slice labels, and the visibility bug that hid the contours.

Contours never drawing on entry to 2D was invisible in code review: the layers
existed, the refresh ran, and it returned early because nothing had set them
visible. So visibility on a mode switch is tested, not assumed.
"""

from __future__ import annotations

import numpy as np
import pytest
from viewer_harness import assert_renders_loops, contour_loops, rendered_labels

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
    # The slider on z, x-y on screen, as the viewer slices by default.
    viewer.dims.order = (2, 0, 1)
    # A layer that holds no shapes leaves dims at its default midpoint,
    # nowhere near the boxes, so the plane has to be put through them.
    viewer.dims.set_point(2, 0.0)
    yield ov
    viewer.close()


def _shown(overlay) -> set[str]:
    """The names the text visual writes on the slice."""
    return {text for text, _pos, _rgba in rendered_labels(overlay)}


def test_labels_are_off_by_default(overlay):
    """Several atlases in one scene would write each name once per atlas."""
    assert overlay.labels == set()
    overlay.refresh()
    assert _shown(overlay) == set()


def test_ticking_one_glomerulus_labels_only_that_one(overlay):
    overlay.set_labels([0])
    assert _shown(overlay) == {"DA1"}


def test_set_label_toggles_independently(overlay):
    assert len(contour_loops(overlay)) == 2, "the plane must cut both boxes"
    overlay.set_label(0, True)
    overlay.set_label(1, True)
    assert _shown(overlay) == {"DA1", "DM1"}
    overlay.set_label(0, False)
    assert _shown(overlay) == {"DM1"}


def test_a_label_sits_on_its_own_section(overlay):
    """Each name is drawn at the center of its box's section, in its color."""
    overlay.set_labels([0, 1])
    assert_renders_loops(overlay)
    # vispy x-y are napari's displayed axes reversed: y, then x.
    at = {text: pos for text, pos, _rgba in rendered_labels(overlay)}
    np.testing.assert_allclose(at["DA1"], (0.0, 0.0), atol=0.3)
    np.testing.assert_allclose(at["DM1"], (0.0, 5.0), atol=0.3)


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
        assert _shown(overlay) == {"DA1", "DM1"}, position
        assert_renders_loops(overlay)


# -- the visibility bug -------------------------------------------------


@pytest.mark.requires_data
def test_entering_2d_makes_the_contours_visible(registry):
    """They are added to the viewer before the mode switch runs.

    `_add_contours` puts them in `viewer.layers`, so a guard that only set
    visibility when appending left every contour hidden and nothing drew.
    """
    from lobemap.viewer.app import build_scene, install_display_mode

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


@pytest.mark.requires_data
def test_a_contour_mirrors_its_surface_across_a_mode_switch(registry):
    from lobemap.viewer.app import build_scene, install_display_mode

    viewer = napari.Viewer(ndisplay=3, show=False)
    try:
        surfaces, contours = build_scene(viewer, registry, "JRCFIB2018F")
        install_display_mode(viewer, surfaces, contours, [])
        surfaces["neuprint_hemibrain_neuropil"].layer.visible = True
        viewer.dims.ndisplay = 2
        assert contours["neuprint_hemibrain_neuropil"].layer.visible
    finally:
        viewer.close()


@pytest.mark.requires_data
@pytest.mark.parametrize("space", ["JRCFIB2018F", "FAFB14"])
def test_the_slice_writes_each_name_as_its_row_shows_it(monkeypatch, space):
    """Every glomerulus and neuropil named on the slice, as a reader ticks
    Label, is written as the table's name column has it: `DA1`, not
    `DA1(R)`; `MB_PED`, not `MB_PED_L`. The side is where the name is."""
    import re

    from viewer_harness import launched, pump, session, tick_all

    from lobemap.viewer.panel import LABEL_COL, NAME_COL
    from lobemap.viewer.rows import RENAMED_MARK

    with launched(monkeypatch, "view", space, "--ndisplay", "2") as (code, viewer):
        assert code == 0
        sess = session(viewer)
        checked = 0
        for name in list(sess.parts):
            tab = sess.panel.tab(name)
            contour = sess.contours[name]
            tick_all(tab)
            tick_all(tab, LABEL_COL)
            pump(300)
            written = sorted(text for text, _pos, _rgba in rendered_labels(contour))
            cut = {owner for owner, _loop in contour_loops(contour)}
            want = sorted({tab.table.item(tab.table_row(i), NAME_COL).text().rstrip(RENAMED_MARK)
                           for i in cut if i in contour.labels})
            assert written and sorted(set(written)) == want, (name, written[:6], want[:6])
            assert not [t for t in written if re.search(r"\([LR]\)|_[LR]$", t)], name
            checked += len(written)
        assert checked > 40, checked
