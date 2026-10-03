"""What a row says, before any widget shows it (`lobemap.viewer.rows`)."""

from __future__ import annotations

from lobemap.core.model import Compartment
from lobemap.viewer import rows as R

ANNOTATION = {
    "DA1": {"Receptor": "Or67d", "Co-receptor": "Orco", "Sensory neuron": "at1A",
            "Sensillum": "at1", "Organ": "antenna", "canonical_glomerulus": "DA1",
            "vfb": "https://example.org/da1"},
    "VC3": {"Receptor": "Or35a", "canonical_glomerulus": "VC3"},
}


def _rows():
    names = ["DA1(R)", "VC3l(R)", "VP2(L)", "XX9"]
    comps = [
        Compartment(0, "DA1(R)", "R", ("DA1",), "exact"),
        Compartment(1, "VC3l(R)", "R", ("VC3",), "renamed"),
        Compartment(2, "VP2(L)", "L", ("VP2",), "exact", uncertain="VM6?",
                    uncertain_reason="why"),
        Compartment(3, "XX9", None, (), "absent"),
    ]
    return R.glomerulus_rows(names, comps, ANNOTATION)


def test_a_glomerulus_row_drops_the_side_and_keeps_the_doubt():
    da1, vc3l, vp2, xx9 = _rows()
    assert (da1.name, da1.published, da1.side) == ("DA1", "DA1(R)", "Right")
    assert (vp2.name, vp2.side, vp2.name_tip) == ("VP2 (VM6?)", "Left", "why")
    assert xx9.side == R.MISSING


def test_a_renamed_glomerulus_is_marked_with_its_standard_name():
    _da1, vc3l, *_ = _rows()
    assert vc3l.shown_name == "VC3l*"
    assert vc3l.standard_note == (
        "This atlas calls it VC3l; its standard name is VC3 (renamed)."
    )
    assert vc3l.details["Receptor"] == "Or35a"


def test_every_detail_is_listed_in_order_and_missing_ones_say_so():
    *_, xx9 = _rows()
    assert tuple(xx9.details) == R.GLOMERULUS_DETAILS
    assert set(xx9.details.values()) == {R.MISSING}
    assert xx9.vfb == "" and xx9.reference_name == ""


def test_the_search_reaches_names_and_annotation_but_not_the_side():
    da1, *_ = _rows()
    for needle in ("da1", "DA1(R)", "or67d", "orco", "at1a", "at1", "antenna"):
        assert da1.matches(needle), needle
    assert not da1.matches("right")
    assert da1.matches("")


def test_rows_sort_by_name_naturally_then_by_side():
    keys = sorted([("DA10", "Left"), ("DA9", "Right"), ("DA9", "Left")],
                  key=lambda nk: R.Row(0, nk[0], nk[0], nk[1]).sort_key())
    assert keys == [("DA9", "Left"), ("DA9", "Right"), ("DA10", "Left")]


def test_a_neuropil_without_a_side_is_on_the_midline():
    full = {"AL": ("antennal lobe", "Ito et al. 2014, Neuron")}
    al, eb, xx = R.neuropil_rows(["AL_L", "EB", "XX(R)"], full)
    assert (al.name, al.side, al.details["Full name"]) == ("AL", "Left", "antennal lobe")
    assert (eb.name, eb.side) == ("EB", "Midline")
    assert xx.details == {"Full name": R.MISSING, "Source": R.MISSING}
    assert al.matches("antennal") and not al.matches("ito")
