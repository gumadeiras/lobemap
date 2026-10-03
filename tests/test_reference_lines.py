"""The driver-line presets and the VFB links, from the reference table.

The preset counts are what `main`'s `scripts/ui_helpers.load_glomerulus_line_presets`
returns for the same table (commit effde7e), so the restored filter selects
the same glomeruli the old one did.
"""

from __future__ import annotations

from pathlib import Path

from lobemap.core import reference

REGISTRY = Path(__file__).resolve().parents[1] / "registry"


#: `main`'s preset sizes for the same table, in its combo order.
MAIN_PRESETS = {
    "Orco-GAL4": 39,
    "Orco-T2A-QF2": 46,
    "Ir8a-T2A-QF2": 19,
    "Ir76b-T2A-QF2": 17,
    "Ir25a-T2A-QF2": 55,
    "Gr21a/Gr63a": 1,
    "GH146-GAL4": 39,
    "ChAT-GAL4": 38,
    "Orco-GAL4 & GH146-GAL4": 32,
}


def test_the_driver_line_presets_match_main():
    got = reference.lines(REGISTRY)
    assert list(got) == list(MAIN_PRESETS)
    assert {line: len(names) for line, names in got.items()} == MAIN_PRESETS


def test_the_intersection_preset_is_the_glomeruli_both_lines_label():
    got = reference.lines(REGISTRY)
    both = got["Orco-GAL4 & GH146-GAL4"]
    assert both == got["Orco-GAL4"] & got["GH146-GAL4"]
    assert {"DA1", "DL3", "VA1d", "VM7v"} <= both
    # Orco-GAL4 labels DA3 and VC3, and GH146-GAL4 labels neither.
    assert not both & {"DA3", "VC3", "VL2a"}


def test_the_vfb_link_has_the_form_main_used():
    table = reference.load(REGISTRY)
    assert table["DA1"][reference.VFB] == (
        "https://www.virtualflybrain.org/term/"
        "antennal-lobe-glomerulus-da1-fbbt_00003932/"
    )
    # Mixed case in the name is lowered, as main did.
    assert table["VM7d"][reference.VFB].endswith(
        "/antennal-lobe-glomerulus-vm7d-fbbt_00110028/"
    )
    # A row with no FBbt term has no link rather than a broken one.
    assert table["VM6m (new)"][reference.VFB] == ""
