"""What a row says, before any widget shows it (`lobemap.viewer.rows`).

A row is one compartment with every side of it. What the sides share is
said once; what they do not is said for each side, so nothing a row per
side used to show is lost.
"""

from __future__ import annotations

from lobemap.core.model import Compartment
from lobemap.viewer import rows as R

ANNOTATION = {
    "DA1": {"Receptor": "Or67d", "Co-receptor": "Orco", "Sensory neuron": "at1A",
            "Sensillum": "at1", "Organ": "antenna", "canonical_glomerulus": "DA1",
            "vfb": "https://example.org/da1"},
    "VC3": {"Receptor": "Or35a", "canonical_glomerulus": "VC3"},
    "VM6": {"Receptor": "Or98b", "canonical_glomerulus": "VM6"},
    "VC5": {"Receptor": "Ir41a", "canonical_glomerulus": "VC5"},
}


def _rows():
    names = ["DA1(R)", "VC3l(R)", "VP2(L)", "XX9", "DA1(L)", "VP2(R)", "VC5(L)", "VC5(R)"]
    comps = [
        Compartment(0, "DA1(R)", "R", ("DA1",), "exact"),
        Compartment(1, "VC3l(R)", "R", ("VC3",), "renamed"),
        Compartment(2, "VP2(L)", "L", ("VP2",), "exact", uncertain="VM6?",
                    uncertain_reason="why left"),
        Compartment(3, "XX9", None, (), "absent"),
        Compartment(4, "DA1(L)", "L", ("DA1",), "exact"),
        Compartment(5, "VP2(R)", "R", ("VP2",), "exact"),
        # The case a rename on one side alone makes: the hemibrain's VC5(R)
        # is VM6, and a VC5(L) beside it would be VC5.
        Compartment(6, "VC5(L)", "L", ("VC5",), "exact"),
        Compartment(7, "VC5(R)", "R", ("VM6",), "renamed"),
    ]
    return {row.name.split(" ")[0]: row for row in R.glomerulus_rows(names, comps, ANNOTATION)}


def test_the_sides_of_a_name_are_one_row_in_mesh_order():
    rows = _rows()
    assert list(rows) == ["DA1", "VC3l", "VP2", "XX9", "VC5"]
    assert [row.key for row in rows.values()] == [0, 1, 2, 3, 4]
    # Left before right, whichever the mesh lists first.
    assert rows["DA1"].indices == (4, 0)
    assert [s.published for s in rows["DA1"].sides] == ["DA1(L)", "DA1(R)"]
    assert rows["VC3l"].indices == (1,)


def test_the_sides_detail_says_which_sides_there_are():
    rows = _rows()
    assert rows["DA1"].details["Sides"] == "Left and right"
    assert rows["VC3l"].details["Sides"] == "Right"
    assert rows["XX9"].details["Sides"] == R.MISSING
    assert tuple(rows["DA1"].details) == R.GLOMERULUS_DETAILS


def test_a_detail_the_sides_share_is_said_once():
    da1 = _rows()["DA1"]
    assert da1.details["Receptor"] == "Or67d"
    assert da1.details["Standard name"] == "DA1"
    assert da1.name == "DA1" and da1.shown_name == "DA1" and da1.name_tip == ""


def test_a_standard_name_one_side_alone_has_is_given_for_each_side():
    """Nothing is lost: each side keeps its own standard name, receptor and note."""
    vc5 = _rows()["VC5"]
    assert vc5.details["Standard name"] == "Left: VC5\nRight: VM6"
    assert vc5.details["Receptor"] == "Left: Ir41a\nRight: Or98b"
    assert vc5.shown_name == "VC5*"
    assert vc5.name_tip == (
        "Right: This atlas calls it VC5; its standard name is VM6 (renamed)."
    )


def test_a_doubt_one_side_alone_has_marks_the_name_and_says_which_side():
    vp2 = _rows()["VP2"]
    assert vp2.name == "VP2 (VM6?)"
    assert vp2.details["Sides"] == "Left (VM6?) and right"
    assert vp2.name_tip == "Left: why left"
    # Each side keeps its own name, which hovering says.
    assert [s.name for s in vp2.sides] == ["VP2 (VM6?)", "VP2"]


def test_a_doubt_every_side_shares_is_in_the_name_and_each_reason_is_kept():
    names = ["VP2(L)", "VP2(R)"]
    comps = [Compartment(i, n, n[-2], ("VP2",), "exact", uncertain="VM6?",
                         uncertain_reason=f"labelled '{n}'")
             for i, n in enumerate(names)]
    (vp2,) = R.glomerulus_rows(names, comps, {})
    assert vp2.name == "VP2 (VM6?)"
    assert vp2.details["Sides"] == "Left and right"
    assert vp2.name_tip == "Left: labelled 'VP2(L)'\n\nRight: labelled 'VP2(R)'"


def test_a_renamed_glomerulus_is_marked_with_its_standard_name():
    vc3l = _rows()["VC3l"]
    assert vc3l.shown_name == "VC3l*"
    assert vc3l.name_tip == "This atlas calls it VC3l; its standard name is VC3 (renamed)."
    assert vc3l.details["Standard name"] == "VC3"
    assert vc3l.details["Receptor"] == "Or35a"


def test_every_detail_is_listed_in_order_and_missing_ones_say_so():
    xx9 = _rows()["XX9"]
    assert tuple(xx9.details) == R.GLOMERULUS_DETAILS
    assert set(xx9.details.values()) == {R.MISSING}
    assert xx9.vfb == "" and xx9.reference_name == ""


def test_the_search_reaches_every_side_and_annotation_but_not_the_side():
    da1 = _rows()["DA1"]
    for needle in ("da1", "DA1(R)", "DA1(L)", "or67d", "orco", "at1a", "at1", "antenna"):
        assert da1.matches(needle), needle
    assert not da1.matches("right") and not da1.matches("left")
    assert da1.matches("")
    assert _rows()["VC5"].matches("VM6"), "one side's standard name"


def test_rows_sort_by_name_naturally():
    keys = sorted(["DA10", "DA9", "DA1"],
                  key=lambda name: R.Row(0, name, ()).sort_key())
    assert keys == ["DA1", "DA9", "DA10"]


def test_hovering_names_the_side_under_the_cursor():
    rows = _rows()
    left, right = rows["DA1"].sides
    assert R.hover_line(left, "Benton 2025") == "DA1 (left) — Benton 2025"
    assert R.hover_line(right, "Benton 2025") == "DA1 (right) — Benton 2025"
    assert R.hover_line(rows["VP2"].side(2), "Grabe 2015") == "VP2 (VM6?, left) — Grabe 2015"
    assert R.hover_line(rows["XX9"].side(3), "Grabe 2015") == "XX9 — Grabe 2015"


def test_a_neuropil_without_a_side_is_on_the_midline():
    full = {"AL": ("antennal lobe", "Ito et al. 2014, Neuron")}
    al, eb, xx = R.neuropil_rows(["AL_L", "EB", "XX(R)", "AL_R"], full)
    assert (al.name, al.indices) == ("AL", (0, 3))
    assert al.details == {"Sides": "Left and right", "Full name": "antennal lobe",
                          "Name from": "Ito et al. 2014, Neuron"}
    assert eb.details["Sides"] == "Midline"
    assert xx.details == {"Sides": "Right", "Full name": R.MISSING, "Name from": R.MISSING}
    assert al.matches("antennal") and al.matches("AL_R") and not al.matches("ito")
    assert R.hover_line(al.side(3), "Neuropils (FlyWire)") == (
        "AL, antennal lobe (right) — Neuropils (FlyWire)")
