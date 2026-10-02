"""Laterality: image side versus the animal's side.

FAFB/FlyWire image data is left-right inverted, and the bridging registrations
do not correct it -- they preserve APPARENT side. Getting this wrong mislabels
which side of the animal a glomerulus belongs to, silently.
"""

from __future__ import annotations

import pytest

from lobemap.core.model import Space, flip_side

MIRRORED = Space("FAFB14", "FAFB14", "nm", "FAFB14", lateral_convention="mirrored")
NORMAL = Space("JRCFIB2018F", "hemibrain", "nm", "JRCFIB2018F")


@pytest.mark.parametrize(
    "value,expect",
    [("L", "R"), ("R", "L"), (None, None), ("both", "both")],
)
def test_flip_side_passes_through_non_lateral_values(value, expect):
    assert flip_side(value) == expect


def test_mirrored_space_swaps_apparent_and_biological():
    assert MIRRORED.is_mirrored
    # A biologically left structure appears on the image right.
    assert MIRRORED.apparent_side("L") == "R"
    assert MIRRORED.biological_side("R") == "L"


def test_biological_space_is_identity():
    assert not NORMAL.is_mirrored
    for side in ("L", "R", None, "both"):
        assert NORMAL.apparent_side(side) == side
        assert NORMAL.biological_side(side) == side


def test_round_trip():
    for space in (MIRRORED, NORMAL):
        for side in ("L", "R"):
            assert space.biological_side(space.apparent_side(side)) == side


def test_bates_is_biologically_left_but_sits_on_image_right():
    """The Bates masks are the fly's LEFT AL.

    The paper calls them right, but predates the discovery that FAFB is
    inverted. They sit on FAFB's image-right, which is why they bridge onto
    hemibrain's AL(R).
    """
    assert MIRRORED.apparent_side("L") == "R"
    assert NORMAL.biological_side("R") == "R"
