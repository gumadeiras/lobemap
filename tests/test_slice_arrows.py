"""Slice view's corner arrows point where the anatomy lies on the section.

Each arrow is drawn for a pole -- anterior or posterior, dorsal or ventral,
left or right -- and must point, on the canvas, where a step toward that pole
of the specimen is drawn: the specimen's direction carried through the mirror
and the turn the section shows, and through vispy's mapping to the canvas,
flip included. Read from the arrows' own letters as drawn, in every brain and
on every slice axis, unturned, spun, oblique and aligned, with and without the
mirror and the flip. A pole too near the line of sight to read has no arrow,
and every other has one.
"""

from __future__ import annotations

import itertools

import numpy as np
import pytest
import turned_harness as th
from viewer_harness import SPACES, canvas_position, launched, pump, session, switcher

pytestmark = pytest.mark.requires_data
pytest.importorskip("napari")

#: (spin, tilt, turn), and the alignment.
POSES = (((0.0, 0.0, 0.0), False), ((30.0, 0.0, 0.0), False),
         ((0.0, 25.0, -35.0), False), ((0.0, 0.0, 0.0), True), ((20.0, -15.0, 10.0), True))


def _shown_specimen(viewer, sess):
    """(world of a specimen point, the specimen point at the view's middle):
    the scene's mirror, then the turn the section shows."""
    from lobemap.viewer.view import mirror_matrix

    mirror = mirror_matrix(3, sess.mirror_center) if sess.mirrored else np.eye(4)
    turn = sess.turned.shown_turn

    def world(x):
        y = (mirror @ np.r_[np.asarray(x, float), 1.0])[:3]
        return y if turn is None else turn(y)

    middle = np.asarray(viewer.dims.point, float)
    shown = list(viewer.dims.displayed)
    middle[shown] = np.asarray(viewer.scene.camera.center, float)[-2:]
    unturned = middle if turn is None else turn.inverse(middle)
    return world, (np.linalg.inv(mirror) @ np.r_[unturned, 1.0])[:3]


def _check(viewer, sess, what) -> int:
    from lobemap.core.model import anatomical_axes, anatomical_triad
    from lobemap.viewer.axes import _ANATOMY_ATTR, MIN_ARROW, _vispy_axes_overlay

    th.settle_canvas(viewer)
    space = sess.registry.spaces[sess.space]
    overlay = _vispy_axes_overlay(viewer)
    node = getattr(overlay, _ANATOMY_ATTR)
    assert node.visible and not overlay.node.axes.visible, what
    drawn = th.label_directions(node)
    poles = {k: np.asarray(v, float) for k, v in anatomical_axes(space).items()}
    world, x0 = _shown_specimen(viewer, sess)
    zoom = viewer.scene.camera.zoom
    origin = np.asarray(canvas_position(viewer, world(x0)), float)

    def on_screen(label):
        return np.asarray(canvas_position(viewer, world(x0 + 10 * poles[label])), float) - origin

    for label, arrow in drawn.items():
        want = on_screen(label)
        cos = arrow @ want / np.linalg.norm(arrow) / np.linalg.norm(want)
        assert cos > np.cos(np.radians(1.0)), (what, label, np.degrees(np.arccos(cos)))
    # One arrow a pole, for each of the three axes, unless too short to read.
    _matrix, labels = anatomical_triad(space, reflect_axis=sess.reflect_axis())
    for label in labels:
        share = np.linalg.norm(on_screen(label)) / (10 * zoom)
        if abs(share - MIN_ARROW) > 0.01:
            assert (label in drawn) == (share > MIN_ARROW), (what, label, share)
    assert set(drawn) <= set(labels), (what, set(drawn), labels)
    return len(drawn)


@pytest.mark.parametrize("space", SPACES)
def test_each_arrow_points_at_its_pole_on_the_section(monkeypatch, space):
    with launched(monkeypatch, "view", space) as (code, viewer):
        sw, sess = switcher(viewer), session(viewer)
        sw.slice_view.click()
        pump()
        shown = 0
        for index in range(sw.slice.count()):
            sw.slice.setCurrentIndex(index)
            pump()
            for (angles, aligned), mirror, flip in itertools.product(
                    POSES, (False, True), (False, True)):
                sw.align.setChecked(aligned)
                for i, angle in enumerate(("spin", "tilt", "turn")):
                    sw.rotation.box[angle].setValue(angles[i])
                sw.mirror.setChecked(mirror)
                sw.flip.setChecked(flip)
                pump()
                shown += _check(viewer, sess, (sw.slice.currentText(), angles, aligned,
                                               mirror, flip))
            sw.rotation.reset.click()
            sw.align.setChecked(False)
            sw.mirror.setChecked(False)
            sw.flip.setChecked(False)
            pump()
        assert shown >= 2 * 3 * len(POSES) * 4, shown
        # In 3D the triad turns in space again, beside napari's.
        sw.three_d.click()
        pump()
        th.settle_canvas(viewer)
        assert th.assert_triads_point_where_they_say(viewer, sess.registry.spaces[space]) >= 5
