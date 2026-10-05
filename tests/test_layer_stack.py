"""The layer stack: glomeruli over neuropils over the brain maps, translucent.

Top first in the layer list: each glomerulus atlas, the primary one first,
then each neuropil set, each with its outlines right over its 3D layer,
then the brain maps -- the label volume over the stain or confocal image.
A layer the user adds stays on top. The order is read off the layer list
at open, as each deferred part arrives, over 2D and 3D trips, after a brain
switch and after a failed one, in every brain.

No layer of lobemap's is additive, and what is drawn proves it: a
glomerulus is laid over the stain and the shells, never hidden by them nor
added to them. Rendered over black and over white, a layer set shows how
much of each pixel it covers; the full scene must be that set's own color
plus the rest of its pixel's share of what is drawn under it, but for the
rounding of each layer to a byte.
"""

from __future__ import annotations

import numpy as np
import pytest
import turned_harness as th
from viewer_harness import SPACES, launched, pump, session, switch_to, tick_all

pytestmark = pytest.mark.requires_data
pytest.importorskip("napari")

#: How far a composite may be off what the layers under it predict, in
#: levels of a byte: each layer is written to the 8-bit framebuffer before
#: the next is laid over it.
ROUNDING = 4
#: The share of a glomerulus's pixel that must be its own color.
GLOMERULUS_COVER = 0.75
#: The share of the stain that must show through the shells, on average
#: over the brain, with every neuropil of the brain shown.
STAIN_THROUGH = 0.5
TRANSLUCENT = {"translucent", "translucent_no_depth"}
#: Each brain's own image, which the pixel tests draw under the rest: the
#: EM brains' stains are not core data.
MAPS = {"FAFB14": "fafb_stain", "JRCFIB2018F": "hemibrain_stain",
        "JRCFIB2022M": "malecns_stain", "GRABE": "grabe2015_stack"}
WITH_MAPS = [pytest.param(space, marks=pytest.mark.requires_data(MAPS[space]))
             for space in SPACES]


def _kind(layer) -> str | None:
    return layer.metadata.get("lobemap", {}).get("kind")


def _expected(sess) -> list:
    """The scene's layers top first, as the stack should hold them."""
    primary = sess.registry.primary_atlas(sess.space).id
    atlases = [primary] + [name for name, part in sess.parts.items()
                           if not part.reference and name != primary]
    shells = [name for name, part in sess.parts.items() if part.reference]
    standins = sess.deferred.standins if sess.deferred is not None else {}
    out = []
    for name in atlases + shells:
        if name in sess.contours:
            out.append(sess.contours[name].layer)
        if name in sess.surfaces:
            out.append(sess.surfaces[name].layer)
        elif name in standins:
            out.append(standins[name])
    out += [layer for layer in sess.images if _kind(layer) == "labels"]
    out += [layer for layer in sess.images if _kind(layer) == "image"]
    return out


def _assert_stacked(viewer, mine, when: str) -> None:
    """The scene's layers at the bottom of the list in their order, and the
    user's layer over them all."""
    sess = session(viewer)
    want = _expected(sess)
    top_first = list(viewer.layers)[::-1]
    assert top_first[0] is mine, (when, [layer.name for layer in top_first])
    got = [layer for layer in top_first if layer is not mine]
    assert [layer.name for layer in got] == [layer.name for layer in want], when
    assert all(a is b for a, b in zip(got, want, strict=True)), when


def _realize_all(viewer, mine) -> None:
    """Open every deferred part's table, as choosing its source does, and
    check the stack after each arrives."""
    sess = session(viewer)
    for name in list(sess.pending):
        assert sess.panel.tab(name) is not None, name
        pump()
        _assert_stacked(viewer, mine, f"{sess.space}: {name} arrived")


def _assert_translucent(viewer) -> None:
    sess = session(viewer)
    ours = [layer for layer in viewer.layers if "lobemap" in layer.metadata]
    assert ours
    for layer in ours:
        assert layer.blending in TRANSLUCENT, (layer.name, layer.blending)
    # Drawn without depth, so none hides a glomerulus inside it.
    for layer in sess.images:
        assert layer.blending == "translucent_no_depth", layer.name
    for name, part in sess.parts.items():
        if part.reference and name in sess.surfaces:
            assert sess.surfaces[name].layer.blending == "translucent_no_depth", name


def test_stack_puts_a_scene_in_order_from_any_order():
    """Every order of nine layers, a sample of them, with the user's layer
    anywhere: the scene's at the bottom in rank order and the user's on
    top. napari's `move_multiple` lost track of its indices for some."""
    import napari

    from lobemap.viewer.scene import stack

    rng = np.random.default_rng(0)
    viewer = napari.Viewer(show=False)
    try:
        ours = [viewer.add_points(np.zeros((1, 2)), name=str(i)) for i in range(9)]
        mine = viewer.add_points(np.zeros((1, 2)), name="mine")
        ranks = {id(layer): (i // 3, i % 3) for i, layer in enumerate(ours)}
        for _ in range(40):
            order = list(rng.permutation(len(viewer.layers)))
            for place, i in enumerate(order):
                viewer.layers.move(viewer.layers.index([*ours, mine][i]), place)
            stack(viewer, ranks)
            assert list(viewer.layers) == [*ours, mine]
    finally:
        viewer.close()


def test_glomeruli_lie_over_neuropils_over_the_brain_maps(monkeypatch):
    """At open, as each deferred part arrives, over 2D and 3D trips, after
    each brain switch and after a failed one, in all four brains; a layer
    the user added stays on top throughout. No layer of lobemap's is
    additive once every part is built."""
    from lobemap.core.registry import Registry

    with launched(monkeypatch, "view", SPACES[0]) as (code, viewer):
        assert code == 0
        mine = viewer.add_points(np.zeros((1, 3)), name="mine")
        pump()
        for space in SPACES:
            if space != SPACES[0]:
                switch_to(viewer, space)
                pump()
            assert session(viewer).space == space
            _assert_stacked(viewer, mine, f"{space}: open")
            viewer.dims.ndisplay = 2
            pump()
            _assert_stacked(viewer, mine, f"{space}: into 2D")
            _realize_all(viewer, mine)
            viewer.dims.ndisplay = 3
            pump()
            _assert_stacked(viewer, mine, f"{space}: back in 3D")
            _assert_translucent(viewer)

        # A switch that fails part-way gives back the scene, in its order.
        before = [layer.name for layer in viewer.layers]
        real = Registry.mesh

        def mesh(self, asset_id):
            if asset_id == "neuprint_hemibrain_glomeruli":
                raise OSError("unreadable")
            return real(self, asset_id)

        monkeypatch.setattr(Registry, "mesh", mesh)
        switch_to(viewer, "JRCFIB2018F")
        assert session(viewer).space == SPACES[-1]
        assert [layer.name for layer in viewer.layers] == before
        _assert_stacked(viewer, mine, "after a failed switch")


@pytest.mark.requires_data("fafb_stain")
def test_lobemap_keeps_the_blending_the_user_chose(monkeypatch):
    """A blending set in the layer settings survives 2D and 3D trips, the
    mirror, the flip, a turn, and the part being built: a stand-in's is
    the built layer's."""
    from viewer_harness import switcher

    with launched(monkeypatch, "view", "FAFB14") as (code, viewer):
        assert code == 0
        sess, sw = session(viewer), switcher(viewer)
        primary = sess.registry.primary_atlas("FAFB14").id
        (shell,) = [name for name, part in sess.parts.items() if part.reference]
        standin = sess.deferred.standins[shell]
        chosen = {sess.images[0]: "additive", sess.surfaces[primary].layer: "opaque",
                  sess.contours[primary].layer: "minimum", standin: "additive"}
        for layer, blending in chosen.items():
            layer.blending = blending
        standin.opacity = 0.5
        for step in (lambda: setattr(viewer.dims, "ndisplay", 2),
                     lambda: sw.mirror.setChecked(True),
                     lambda: sw.flip.setChecked(True),
                     lambda: sw.rotation.box["turn"].setValue(20.0),
                     lambda: setattr(viewer.dims, "ndisplay", 3),
                     lambda: sess.panel.tab(shell)):
            step()
            pump()
            for layer, blending in chosen.items():
                assert layer.blending == blending, (layer.name, blending)
        assert sess.surfaces[shell].layer is standin
        assert standin.opacity == 0.5


# -- what is drawn -------------------------------------------------------


def _shown_as(viewer, layers, on, background=None) -> np.ndarray:
    """Render with only `on` of `layers` drawn, the rest at opacity 0, over
    the canvas's own color or `background`. Each layer keeps its data and
    visibility, so nothing is sliced or rebuilt in between."""
    kept = {layer: layer.opacity for layer in layers}
    try:
        for layer in layers:
            if layer not in on:
                layer.opacity = 0.0
        if background is not None:
            viewer.canvas.background_color_override = background
        return th.picture(viewer).astype(float)
    finally:
        for layer, opacity in kept.items():
            layer.opacity = opacity
        viewer.canvas.background_color_override = None


def _cover(viewer, top, layers) -> tuple[np.ndarray, np.ndarray]:
    """What `top` alone draws over black, and the share of each pixel it
    leaves to what is under it: rendered over black and over white."""
    black = _shown_as(viewer, layers, top)
    white = _shown_as(viewer, layers, top, "white")
    through = (white - black) / 255.0
    # Equal in every channel, but for the rounding of each layer laid on:
    # a layer set covers a pixel, not a color.
    assert np.abs(through - through.mean(-1, keepdims=True)).max() <= ROUNDING / 255.0
    return black, through.mean(-1)


def _layered(viewer, top, under) -> dict:
    """`top` alone (`_cover`), `under` alone, and both, as rendered."""
    layers = top + under
    own, through = _cover(viewer, top, layers)
    return {"own": own, "through": through, "below": _shown_as(viewer, layers, under),
            "full": _shown_as(viewer, layers, layers)}


def _assert_laid_over(shots: dict, where: str) -> np.ndarray:
    """Every pixel the top layers draw is their own color laid over what is
    drawn under them there, neither hidden by it nor added to it. The
    pixels they draw."""
    own, through, below, full = (shots[k] for k in ("own", "through", "below", "full"))
    drawn = through < 0.98
    assert drawn.sum() > 2000, (where, int(drawn.sum()))
    laid = own + through[..., None] * below
    off = np.abs(full - laid).max(-1)[drawn]
    assert np.percentile(off, 99.5) <= ROUNDING, (where, np.percentile(off, [50, 99, 99.5]))
    # Not added: where what is under is bright, a sum would be far brighter.
    bright = drawn & (below.max(-1) > 60)
    assert bright.sum() > 500, (where, int(bright.sum()))
    added = np.clip(own + below, 0, 255)
    assert np.median(np.abs(full - added).max(-1)[bright]) > 4 * ROUNDING, where
    return drawn


@pytest.mark.parametrize("space", WITH_MAPS)
def test_in_3d_each_glomerulus_is_laid_over_the_stain_and_the_shells(monkeypatch, space):
    """Every neuropil of the brain shown with its stain or confocal image
    and the primary atlas: each glomerulus pixel is the glomerulus's color,
    three quarters of it or more, over what the stain and shells draw there;
    and the stain still shows through the shells. A shell that wrote its
    depth would hide glomeruli, and this would catch it."""
    with launched(monkeypatch, "view", space) as (code, viewer):
        assert code == 0
        th.settle_canvas(viewer)
        sess = session(viewer)
        shells = []
        for name, part in list(sess.parts.items()):
            if part.reference:
                tick_all(sess.panel.tab(name))
                shells.append(sess.surfaces[name].layer)
        pump()
        glomeruli = [sess.surfaces[sess.registry.primary_atlas(space).id].layer]
        maps = [layer for layer in sess.images if layer.visible]
        assert maps and glomeruli[0].visible
        layers = glomeruli + shells + maps
        shots = _layered(viewer, glomeruli, shells + maps)
        drawn = _assert_laid_over(shots, space)
        assert (1 - shots["through"][drawn]).min() >= GLOMERULUS_COVER - 2 / 255.0, space
        if shells:
            _own, through = _cover(viewer, shells, layers)
            brain = _shown_as(viewer, layers, maps).sum(-1) > 30
            assert through[brain].mean() >= STAIN_THROUGH, (space, through[brain].mean())
        # The measure catches a stain, or a shell, that writes its depth.
        for layer in shells + maps:
            layer.blending = "translucent"
        shots["full"] = _shown_as(viewer, layers, layers)
        with pytest.raises(AssertionError):
            _assert_laid_over(shots, space)


@pytest.mark.parametrize("space", WITH_MAPS)
def test_in_2d_outlines_and_fills_are_laid_over_the_stain(monkeypatch, space):
    """In Slice view, the primary atlas's outlines and fills and every
    neuropil's outline are their own color laid over the stain."""
    from lobemap.viewer.panel import FILL_COL

    with launched(monkeypatch, "view", space, "--ndisplay", "2") as (code, viewer):
        assert code == 0
        th.settle_canvas(viewer)
        sess = session(viewer)
        primary = sess.registry.primary_atlas(space).id
        tick_all(sess.panel.tab(primary), FILL_COL)
        for name, part in list(sess.parts.items()):
            if part.reference:
                tick_all(sess.panel.tab(name))
        pump()
        outlines = [overlay.layer for overlay in sess.contours.values()
                    if overlay.layer.visible]
        maps = [layer for layer in sess.images if layer.visible]
        assert maps and sess.contours[primary].layer in outlines
        _assert_laid_over(_layered(viewer, outlines, maps), space)
