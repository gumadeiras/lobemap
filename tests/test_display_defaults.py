"""Per-layer display defaults, and color keyed on the glomerulus.

Color by file position is the failure these guard: it makes the same
glomerulus a different color in each atlas, which is unreadable in a viewer
built to superpose them, and nothing errors.
"""

from __future__ import annotations

import numpy as np
import pytest

from lobemap.core.model import Compartment
from lobemap.viewer.app import (
    BASE_DISPLAY,
    ROLE_DISPLAY,
    display_for,
)
from lobemap.viewer.layers import canonical_colors, categorical_colors

ORDER = ["DA1", "DA2", "VC3", "VC5", "VM6", "VP1d", "VP1l", "VP1m"]


def _c(name, canonical, relation="exact"):
    return Compartment(local_id=0, published_name=name, side="R",
                       canonical=tuple(canonical), relation=relation)


def test_the_same_glomerulus_gets_the_same_color_in_every_atlas():
    a = canonical_colors([_c("DA1", ["DA1"]), _c("DA2", ["DA2"])], ORDER)
    # A different atlas, different order, different names for the same thing.
    b = canonical_colors([_c("AL-DA2(R)", ["DA2"]), _c("AL-DA1(R)", ["DA1"])], ORDER)
    assert np.allclose(a[0], b[1]), "DA1 must match across atlases"
    assert np.allclose(a[1], b[0]), "DA2 must match across atlases"
    assert not np.allclose(a[0], a[1]), "distinct glomeruli must differ"


def test_a_rename_shares_color_with_its_canonical():
    """Bates VC3l is canonical VC3; it must look like Benton's VC3."""
    old = canonical_colors([_c("VC3l", ["VC3"], "renamed")], ORDER)
    new = canonical_colors([_c("VC3", ["VC3"])], ORDER)
    assert np.allclose(old[0], new[0])


def test_the_parts_of_a_split_share_one_color():
    """VM6l/VM6m/VM6v are one glomerulus resolved three ways."""
    cols = canonical_colors(
        [_c(n, ["VM6"], "split") for n in ("VM6l", "VM6m", "VM6v")], ORDER)
    assert all(np.allclose(cols[0], c) for c in cols)


def test_a_merge_takes_its_first_canonical():
    merged = canonical_colors([_c("VP1", ["VP1d", "VP1l", "VP1m"], "merge")], ORDER)
    first = canonical_colors([_c("VP1d", ["VP1d"])], ORDER)
    assert np.allclose(merged[0], first[0])


def test_color_does_not_depend_on_how_many_compartments_an_atlas_has():
    """Adding an atlas must never recolor an existing one."""
    one = canonical_colors([_c("VM6", ["VM6"])], ORDER)
    many = canonical_colors([_c(n, [n]) for n in ORDER], ORDER)
    assert np.allclose(one[0], many[ORDER.index("VM6")])


def test_an_unknown_canonical_falls_back_without_raising():
    cols = canonical_colors([_c("Mystery", ["NotInVocabulary"])], ORDER)
    assert cols.shape == (1, 4)
    assert np.allclose(cols[0], (0.6, 0.6, 0.6, 1.0))


def test_empty_vocabulary_does_not_divide_by_zero():
    cols = canonical_colors([_c("X", ["X"])], [])
    assert cols.shape == (1, 4)


def test_categorical_colors_are_still_distinct():
    cols = categorical_colors(58)
    assert len({tuple(np.round(c, 3)) for c in cols}) == 58


# -- image display defaults ---------------------------------------------


def test_stain_defaults():
    spec = display_for("virtual_stain")
    assert spec["colormap"] == "gray"
    assert spec["gamma"] == 0.7
    assert spec["rendering"] == "attenuated_mip"
    assert spec["attenuation"] == 0.1
    assert spec["blending"] == "translucent_no_depth"


def test_a_role_override_does_not_lose_the_base_defaults():
    spec = display_for("template_image")
    assert spec["colormap"] == "gray"
    assert spec["blending"] == BASE_DISPLAY["blending"]


def test_an_asset_colormap_wins_over_the_role():
    spec = display_for("virtual_stain", colormap="cyan")
    assert spec["colormap"] == "cyan"
    assert spec["gamma"] == 0.7, "overriding color must not drop gamma"


def test_napari_accepts_every_default_we_pass():
    """These are keyword arguments to add_image; a typo is a runtime error."""
    napari = pytest.importorskip("napari")

    viewer = napari.Viewer(show=False)
    try:
        for role in (*ROLE_DISPLAY, "something_else"):
            spec = display_for(role)
            layer = viewer.add_image(
                np.zeros((4, 4, 4), np.uint8), name=role, **spec)
            assert layer.colormap.name == spec["colormap"]
            assert layer.gamma == pytest.approx(spec.get("gamma", 1.0))
            if "attenuation" in spec:
                assert layer.attenuation == pytest.approx(spec["attenuation"])
            assert layer.rendering == spec["rendering"]
    finally:
        viewer.close()
