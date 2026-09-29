"""The anatomical frame, checked against the anatomy rather than asserted.

Which array axis points anterior differs between spaces, and the sign differs
too, so these are facts about data that have to be measured. A sign error
here is invisible -- the triad looks just as convincing pointing the wrong
way -- which is why this file measures instead of restating the constants.
"""

from __future__ import annotations

import re

import numpy as np
import pytest

from lobemap.core.model import anatomical_axes
from lobemap.core.registry import Registry
from lobemap.viewer.axes import axis_labels_for, label_viewer_axes


def _strip(name: str) -> str:
    return re.sub(r"^AL-", "", re.sub(r"\(.\)$", "", name))


def _group_centroid(meshset, keep):
    picked = [
        meshset.compartment(i)[0].mean(0)
        for i, name in enumerate(meshset.names)
        if keep(_strip(name))
    ]
    return np.mean(picked, axis=0) if picked else None


@pytest.mark.requires_data
@pytest.mark.parametrize(
    "space,atlas",
    [
        ("FAFB14", "benton2025"),
        ("JRCFIB2018F", "neuprint_hemibrain"),
        ("JRCFIB2022M", "neuprint_cns"),
        ("GRABE", "grabe2015"),
    ],
)
def test_frame_agrees_with_positional_nomenclature(registry, space, atlas):
    """D* must sit dorsal of V*, and *A anterior of *P, in every space.

    Glomerulus names encode position -- first letter D/V, second A/P or M/L --
    so the names are an independent witness to the geometry.
    """
    frame = anatomical_axes(registry.spaces[space])
    assert frame is not None, f"{space} declares no axes"
    entry = next(a for a in registry.atlases_in_space(space) if a.id == atlas)
    meshset = registry.mesh(entry.asset)

    dorsal_group = _group_centroid(meshset, lambda n: n.startswith("D"))
    ventral_group = _group_centroid(meshset, lambda n: n.startswith("V"))
    anterior_group = _group_centroid(meshset, lambda n: len(n) > 1 and n[1] == "A")
    posterior_group = _group_centroid(meshset, lambda n: len(n) > 1 and n[1] == "P")

    for a, b, pole, what in (
        (dorsal_group, ventral_group, "D", "D* vs V*"),
        (anterior_group, posterior_group, "A", "*A vs *P"),
    ):
        assert a is not None and b is not None, f"{atlas}: no {what} groups"
        direction = a - b
        direction = direction / np.linalg.norm(direction)
        agreement = float(np.dot(direction, frame[pole]))
        assert agreement > 0.5, (
            f"{space}/{atlas}: {what} points {agreement:+.2f} along {pole}; "
            f"the {pole} axis looks inverted"
        )


@pytest.mark.requires_data
def test_lateral_points_at_the_biological_right_in_fafb(registry):
    """A mirrored space MUST flip the lateral axis.

    FAFB is the one space where apparent and biological sides come apart.
    Both kinds of label in it are biological: FlyWire's neuropil names are
    post-correction, so `AL_L` really is the left lobe, and the Benton asset
    declares side L for the glomeruli sitting inside it.

    So the R arrow has to run from `AL(L)` toward `AL(R)`. Unnegated,
    cross(anterior, dorsal) runs the other way, and FAFB is precisely where
    that could not be caught by comparing two lobes of one atlas, because
    its atlases cover only one.
    """
    frame = anatomical_axes(registry.spaces["FAFB14"])
    assert registry.spaces["FAFB14"].is_mirrored, "fixture assumption changed"
    meshset = registry.mesh("fafb_neuropil")
    centroid = {}
    # By side rather than by exact string: the shell has been sourced from
    # FlyWire ("AL_L") and from the male CNS ("AL(L)"), and the test is
    # about laterality, not spelling.
    def al_for(side: str) -> str:
        """The whole-AL shell for one side, whatever the naming style.

        FlyWire writes `AL_L`, neuPrint writes `AL(L)`. Matching the stem
        and the side separately covers both; an earlier version partitioned
        on "(" alone, which silently matched neither for `AL_L`.
        """
        for name in meshset.names:
            m = re.fullmatch(r"(?P<stem>.+?)[_(](?P<side>[LR])\)?", name)
            if m and m["stem"] == "AL" and m["side"] == side:
                return name
        raise AssertionError(f"no AL for side {side} in {meshset.names[:6]}...")

    for side in ("L", "R"):
        verts, _faces = meshset.compartment(meshset.names.index(al_for(side)))
        centroid[side] = verts.mean(0)
    biological_right = centroid["R"] - centroid["L"]
    biological_right /= np.linalg.norm(biological_right)
    assert float(np.dot(biological_right, frame["R"])) > 0.9


@pytest.mark.requires_data
@pytest.mark.parametrize(
    "space,atlas",
    [
        ("JRCFIB2018F", "neuprint_hemibrain"),
        ("JRCFIB2022M", "neuprint_cns"),
        ("GRABE", "grabe2015"),
    ],
)
def test_lateral_points_at_declared_right_where_sides_are_biological(
    registry, space, atlas
):
    """In an unmirrored space the declared sides ARE the biological ones."""
    assert not registry.spaces[space].is_mirrored
    frame = anatomical_axes(registry.spaces[space])
    entry = next(a for a in registry.atlases_in_space(space) if a.id == atlas)
    meshset = registry.mesh(entry.asset)
    sides: dict[str, list] = {"L": [], "R": []}
    for i, compartment in enumerate(entry.compartments):
        if compartment.side in sides:
            sides[compartment.side].append(meshset.compartment(i)[0].mean(0))
    assert sides["L"] and sides["R"], f"{atlas} has no L/R pair"
    direction = np.mean(sides["R"], axis=0) - np.mean(sides["L"], axis=0)
    direction /= np.linalg.norm(direction)
    assert float(np.dot(direction, frame["R"])) > 0.9


def test_a_space_without_a_rotation_gets_no_frame():
    """Built here rather than taken from the registry.

    This used to borrow JRC2018U, which declared no axes because nothing
    was ever shown in it. That space has been removed, and the behavior
    under test is about a Space with no rotation rather than about
    any particular one.
    """
    from lobemap.core.model import Space

    space = Space(id="NOAXES", title="no axes", units="um")
    assert anatomical_axes(space) is None
    assert axis_labels_for(space) is None


def test_axis_labels_name_every_array_axis(registry):
    """One pole per array axis, and all three axes covered once each.

    A label is a single pole -- `P`, not `A-P` or `A->P` -- so what
    identifies the axis is which pair the pole belongs to.
    """
    pair_of = {"A": "AP", "P": "AP", "D": "DV", "V": "DV",
               "L": "LR", "R": "LR"}
    for space_id in ("FAFB14", "JRCFIB2018F", "JRCFIB2022M", "GRABE"):
        labels = axis_labels_for(registry.spaces[space_id])
        assert labels is not None and len(labels) == 3
        assert "?" not in "".join(labels), f"{space_id}: unnamed axis in {labels}"
        for label in labels:
            assert label in pair_of, (
                f"{space_id}: {label!r} is not a single anatomical pole"
            )
        assert {pair_of[x] for x in labels} == {"AP", "DV", "LR"}, (
            f"{space_id}: {labels} does not cover all three axes once each"
        )


def test_each_label_names_the_pole_its_own_arrow_reaches(registry):
    """The contract the whole triad rests on.

    napari draws each arrow along INCREASING index and offers no way to
    reverse one, so a label naming a pole its arrow does not reach would
    contradict the arrow beneath it -- which is what got an older
    world-space Vectors layer removed.
    """
    import numpy as np

    from lobemap.core.model import anatomical_axes, anatomical_triad

    for space_id in ("FAFB14", "JRCFIB2018F", "JRCFIB2022M", "GRABE"):
        space = registry.spaces[space_id]
        matrix, labels = anatomical_triad(space)
        frame = anatomical_axes(space)
        for arrow, pole in enumerate(labels):
            assert np.allclose(matrix[:, arrow], frame[pole], atol=1e-12), (
                space_id, arrow, pole
            )


def test_no_anatomical_arrow_lands_near_a_world_arrow(registry):
    """The point of the choice: the two triads share an origin, so an
    anatomical arrow close to one of napari's collides with it.

    The world arrows are the POSITIVE axes only -- napari draws each
    along increasing index and cannot reverse one -- which is why the
    sign of each pole is worth choosing. Against plus-and-minus axes
    the nearest distance would be fixed by the anatomy and no labeling
    could improve it.
    """
    import numpy as np

    from lobemap.core.model import anatomical_triad

    for space_id in ("FAFB14", "JRCFIB2018F", "JRCFIB2022M", "GRABE"):
        matrix, _labels = anatomical_triad(registry.spaces[space_id])
        # the nearest positive axis to a column is its largest component
        nearest = [np.degrees(np.arccos(np.clip(np.max(matrix[:, k]), -1, 1)))
                   for k in range(3)]
        assert min(nearest) > 45.0, (space_id, np.round(nearest, 1))


def test_the_triad_maximizes_that_separation(registry):
    """Checked against brute force over all 48 signed permutations: the
    chosen one must be a right-handed candidate whose closest approach
    to a world arrow is as far off as any candidate achieves."""
    import itertools

    import numpy as np

    from lobemap.core.model import anatomical_axes, anatomical_triad

    for space_id in ("FAFB14", "JRCFIB2018F", "JRCFIB2022M", "GRABE"):
        matrix, _labels = anatomical_triad(registry.spaces[space_id])
        assert np.isclose(np.linalg.det(matrix), 1.0, atol=1e-12), space_id
        frame = anatomical_axes(registry.spaces[space_id])
        vectors = [frame["A"], frame["D"], frame["R"]]

        def closest(M):
            return max(float(np.max(M[:, k])) for k in range(3))

        best = min(
            closest(M) for M in (
                np.column_stack([signs[k] * vectors[order[k]] for k in range(3)])
                for order in itertools.permutations(range(3))
                for signs in itertools.product((1, -1), repeat=3))
            if np.linalg.det(M) > 0
        )
        assert np.isclose(closest(matrix), best, atol=1e-12), space_id


def test_the_anatomical_labels_differ_between_spaces(registry):
    """They name the second triad's arrows, and which pole each arrow
    carries is chosen per space to sit nearest its own world axis. So
    they move with the space, and with the angle.

    They were briefly fixed at (A, D, R/L), when ONE triad carried both
    the anatomy and the grid; there, a label that moved with the angle
    was a bug. With two triads the choice is what keeps them apart.
    """
    labels = {s: axis_labels_for(registry.spaces[s])
              for s in ("FAFB14", "JRCFIB2018F", "JRCFIB2022M", "GRABE")}
    assert labels["FAFB14"] == ("A", "D", "L"), labels["FAFB14"]
    assert labels["JRCFIB2018F"] == ("P", "R", "D"), labels["JRCFIB2018F"]
    assert len(set(labels.values())) > 1, labels
    # each names one pole of each anatomical axis, never two of one
    for space_id, trio in labels.items():
        axes = {"A": "AP", "P": "AP", "D": "DV", "V": "DV",
                "R": "LR", "L": "LR"}
        assert {axes[p] for p in trio} == {"AP", "DV", "LR"}, (space_id, trio)


@pytest.mark.requires_data
def test_no_axes_layer_is_created(registry):
    """The anatomy is named on napari's own overlay, not drawn as a layer.

    A second, world-space triad used to be added here. It duplicated the
    overlay, and because its arrows pointed at the anatomical pole rather
    than up the array axis they ran OPPOSITE to the overlay's in 8 of the 12
    space/axis combinations -- in FAFB the overlay's z arrow points posterior
    while the layer's A-P arrow pointed anterior.
    """
    napari = pytest.importorskip("napari")
    from lobemap.viewer.app import build_scene

    viewer = napari.Viewer(show=False)
    try:
        build_scene(viewer, registry, "GRABE")
        stray = [
            layer.name for layer in viewer.layers
            if layer.metadata.get("lobemap", {}).get("kind") == "axes"
            or "anatomical axes" in layer.name
        ]
        assert not stray, f"an axes layer came back: {stray}"
    finally:
        viewer.close()


@pytest.mark.requires_data
@pytest.mark.parametrize("space_id",
                         ["FAFB14", "JRCFIB2018F", "JRCFIB2022M", "GRABE"])
def test_napari_own_triad_always_names_the_array_axes(registry, space_id):
    """It is left exactly as it comes, in both display modes.

    The anatomy is a second triad beside it. Turning napari's own onto
    the anatomy, as an earlier version did, left nothing showing where
    the voxel grid ran -- and the sliders, which step array axes, ended
    up with anatomical names.
    """
    napari = pytest.importorskip("napari")

    from lobemap.viewer.app import load_space
    from lobemap.viewer.axes import VOXEL_LABELS

    viewer = napari.Viewer(show=False, ndisplay=3)
    try:
        load_space(viewer, registry, space_id)
        for mode in (3, 2, 3):
            viewer.dims.ndisplay = mode
            assert tuple(viewer.dims.axis_labels) == VOXEL_LABELS, mode
        overlay = viewer.canvas.overlays["axes"]
        assert overlay.visible is True
        assert overlay.labels is True
    finally:
        viewer.close()


@pytest.mark.requires_data
def test_the_indicator_is_anchored_to_the_canvas_not_the_data(registry):
    """Otherwise it is off-screen in the spaces that do not start at zero.

    napari 0.9 has two axis indicators: a scene overlay at the world
    origin and a canvas overlay in a corner. A space is in whatever
    coordinates its volume was published in, and only some begin at zero
    -- FAFB's data spans x 192-853 um, so an indicator at the origin lies
    ~190 um outside everything the default view contains, and was simply
    invisible. The male CNS starts at 37 um and showed part of one.
    """
    napari = pytest.importorskip("napari")
    from lobemap.viewer.app import build_scene

    viewer = napari.Viewer(show=False)
    try:
        build_scene(viewer, registry, "FAFB14")
        assert viewer.canvas.overlays["axes"].visible is True
        # And only one of them, or the canvas gets two sets of arrows.
        assert viewer.scene.overlays["axes"].visible is False
        # The property that makes it immune: a canvas anchor.
        assert viewer.canvas.overlays["axes"].position is not None
    finally:
        viewer.close()


def test_a_space_without_axes_leaves_the_labels_alone(registry):
    """No axes declared means no claim about orientation, not a wrong one."""
    napari = pytest.importorskip("napari")

    viewer = napari.Viewer(ndisplay=3, show=False)
    try:
        from lobemap.core.model import Space

        before = tuple(viewer.dims.axis_labels)
        space = Space(id="NOAXES", title="no axes", units="um")
        assert label_viewer_axes(viewer, space) is False
        assert tuple(viewer.dims.axis_labels) == before
    finally:
        viewer.close()


def test_labels_are_refused_rather_than_truncated(registry):
    """Three labels onto a 2D viewer must not silently become two.

    napari keeps the TAIL of an over-long label tuple, so D->V would land on
    x and A->P on y -- a confident, wrong answer in place of no answer.
    """
    napari = pytest.importorskip("napari")

    viewer = napari.Viewer(show=False)      # no layers: dims.ndim == 2
    try:
        assert viewer.dims.ndim == 2, "fixture assumption changed"
        before = tuple(viewer.dims.axis_labels)
        assert label_viewer_axes(viewer, registry.spaces["FAFB14"]) is False
        assert tuple(viewer.dims.axis_labels) == before
    finally:
        viewer.close()


# -- GRABE: anatomy that is not axis-aligned -------------------------------
#
# Measured against Benton, the hemibrain and the male CNS, both lobes of
# each, GRABE's anterior and dorsal sit ~49 deg off its array axes. The
# overlay draws one arrow per ARRAY axis, so labeling them cannot say
# that: the label would name a pole its own arrow never reaches. napari's
# own visual is rotated instead, which keeps the indicator identical to
# the one the other three spaces show and moves only where it points.


# -- the declared rotation -------------------------------------------------
#
# It sends the array axes onto (A, D, lateral) and is the only statement
# of a space's anatomy. What is worth pinning is the contract -- any
# axis and angle give a proper frame, the labels never move -- and not
# the four angles that happen to be declared today.


@pytest.mark.parametrize("axis", ["+x", "-z", (0.3, -0.5, 0.81), (1.0, 1.0, 1.0)])
@pytest.mark.parametrize("degrees", [0.0, 37.0, -120.0, 180.0])
def test_any_axis_and_angle_give_a_proper_rotation(registry, axis, degrees):
    """Why the schema is axis-angle and not a matrix or a vector pair."""
    import dataclasses

    import numpy as np

    from lobemap.core.model import anatomical_rotation_matrix

    space = dataclasses.replace(registry.spaces["GRABE"],
                                anatomical_rotation_axis=axis,
                                anatomical_rotation_deg=degrees)
    frame = anatomical_axes(space)
    M = anatomical_rotation_matrix(space)
    assert np.allclose(M.T @ M, np.eye(3), atol=1e-12)
    assert np.isclose(np.linalg.det(M), 1.0, atol=1e-12)
    for pole, opposite in (("A", "P"), ("D", "V"), ("R", "L")):
        assert np.allclose(frame[pole], -frame[opposite], atol=1e-12)


def test_a_pole_name_is_not_an_axis(registry):
    """It would be circular: the poles are what the rotation defines.
    The earlier RELATIVE schema did take one, and GRABE used R."""
    import dataclasses

    from lobemap.core.model import rotation_axis_vector

    space = dataclasses.replace(registry.spaces["GRABE"],
                                anatomical_rotation_axis="R")
    with pytest.raises(ValueError):
        rotation_axis_vector(space)


def test_an_axis_without_an_angle_is_rejected(registry_root):
    """Half a declaration names no rotation, and ignoring it would leave
    the arrows on the array axes while the registry claimed otherwise."""
    import dataclasses

    from lobemap.core.registry import RegistryError

    reg = Registry.load(registry_root)
    reg.spaces["GRABE"] = dataclasses.replace(
        reg.spaces["GRABE"], anatomical_rotation_deg=None
    )
    with pytest.raises(RegistryError, match="anatomical_rotation"):
        reg.validate()


@pytest.mark.requires_data
def test_the_anatomy_gets_a_second_triad_shown_only_in_3d(registry):
    """Two triads sharing one origin in 3D; napari's alone in 2D.

    A slice is cut along ARRAY axes, which are 15-31 degrees off the
    anatomy in every space here, so an anatomical arrow drawn over a
    slice would claim an alignment the slice does not have.

    It is a vispy visual inside napari's own overlay, not a layer, so it
    shares the origin, the camera and the corner anchoring -- and does
    not appear in the layer list. See `test_no_axes_layer_is_created`.
    """
    napari = pytest.importorskip("napari")
    import numpy as np

    from lobemap.core.model import anatomical_axes
    from lobemap.viewer.app import load_space
    from lobemap.viewer.axes import (
        _ANATOMY_ATTR,
        _vispy_axes_overlay,
        axis_labels_for,
    )

    viewer = napari.Viewer(show=False, ndisplay=3)
    try:
        load_space(viewer, registry, "GRABE")
        overlay = _vispy_axes_overlay(viewer)
        if overlay is None:
            pytest.skip("no vispy canvas")
        node = getattr(overlay, _ANATOMY_ATTR, None)
        assert node is not None, "no anatomical triad was created"
        assert node.visible is True
        assert node.parent is overlay.node.scene, "not in napari's own view box"

        # napari's own is untouched: not turned, not recolored
        assert getattr(overlay.node.axes.transform, "matrix", None) is None

        # the second one carries the anatomy
        labels = axis_labels_for(registry.spaces["GRABE"])
        assert list(node.text.text) == list(labels)[::-1]
        frame = anatomical_axes(registry.spaces["GRABE"])
        flip = np.eye(3)[::-1]
        recovered = flip @ np.asarray(node.transform.matrix)[:3, :3].T @ flip
        for i, pole in enumerate(labels):
            assert np.allclose(recovered[:, i], frame[pole], atol=1e-9), pole

        viewer.dims.ndisplay = 2
        assert node.visible is False
        viewer.dims.ndisplay = 3
        assert node.visible is True
    finally:
        viewer.close()
