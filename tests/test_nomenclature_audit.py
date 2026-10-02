"""`lobemap nomenclature` must not destroy hand-made correspondences.

It used to re-derive the whole table from the atlases and save it. A
mechanical derivation can only emit identity relations -- published
`AL-DA1(R)` maps to `DA1` -- so every curated merge, split and rename was
replaced by an identity, and the information was gone with no warning. The
file carries six such rows: the Schlegel 2021 rename chain and the VM6
three-way split, both in JRCFIB2018F, where three atlases share one
vocabulary and it has to reconcile them.
"""

from __future__ import annotations

import csv
import pathlib
import subprocess
import sys

import pytest

from lobemap.core.names import Correspondence, Nomenclature, audit_atlas
from lobemap.core.registry import Registry

REGISTRY = "registry"


@pytest.fixture(scope="module")
def registry():
    return Registry.load(REGISTRY, validate=False)


def _curated() -> Nomenclature:
    return Nomenclature(
        canonical=["VP1d", "VP1l", "VP1m", "VC3"],
        correspondences=[
            Correspondence("a", "VP1(L)", ("VP1d", "VP1l", "VP1m"), "merge"),
            Correspondence("a", "VC3l(R)", ("VC3",), "renamed"),
            Correspondence("a", "GONE(L)", ("GONE",), "exact"),
        ],
    )


def test_audit_separates_missing_stale_and_curated():
    nom = _curated()
    a = audit_atlas(nom, "a", ["VP1(L)", "VC3l(R)", "NEW(L)"])
    assert a.missing == ("NEW(L)",)
    assert a.stale == ("GONE(L)",)
    assert {c.relation for c in a.curated} == {"merge", "renamed"}
    assert not a.clean


def test_a_table_that_matches_is_clean():
    nom = _curated()
    a = audit_atlas(nom, "a", ["VP1(L)", "VC3l(R)", "GONE(L)"])
    assert a.clean and not a.missing and not a.stale


def test_add_missing_leaves_curated_rows_alone():
    """The whole point: adding a row must not rewrite its neighbors."""
    nom = _curated()
    added = nom.add_missing("a", ["VP1(L)", "VC3l(R)", "NEW(L)"])
    assert added == ["NEW(L)"]

    rows = {c.published_name: c for c in nom.for_atlas("a")}
    assert rows["VP1(L)"].canonical == ("VP1d", "VP1l", "VP1m")
    assert rows["VP1(L)"].relation == "merge"
    assert rows["VC3l(R)"].relation == "renamed"
    assert rows["NEW(L)"].relation == "exact"


def test_drop_removes_only_the_named_rows():
    nom = _curated()
    assert nom.drop("a", ["GONE(L)"]) == 1
    assert {c.published_name for c in nom.for_atlas("a")} == {"VP1(L)", "VC3l(R)"}


def test_running_the_command_writes_nothing(tmp_path):
    """The real registry, the real command, and the file must not move."""
    source = pathlib.Path(REGISTRY) / "nomenclature.csv"
    before = source.read_bytes()
    (tmp_path / "before.csv").write_bytes(before)

    result = subprocess.run(
        [sys.executable, "-m", "lobemap.cli", "nomenclature"],
        capture_output=True, text=True, check=False,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert source.read_bytes() == before, (
        "nomenclature rewrote the table without being asked"
    )


def test_a_single_atlas_space_has_nothing_to_reconcile():
    """Its vocabulary IS its atlas, so every mapping is the identity.

    Grabe's `VP1` used to map onto `VP1d;VP1l;VP1m` -- three names its own
    geometry cannot tell apart, inherited from the global Benton-anchored
    vocabulary that per-space vocabularies replaced. The other two
    single-atlas spaces never had such a row.
    """
    from lobemap.core.names import parse_roi

    reg = Registry.load(REGISTRY, validate=False)
    for space in reg.spaces:
        atlases = reg.atlases_in_space(space)
        if len(atlases) != 1:
            continue
        published = {
            parse_roi(c.published_name)[0] for c in atlases[0].compartments
        }
        assert set(reg.vocabulary(space)) == published, (
            f"{space}: vocabulary and atlas disagree with no second atlas "
            f"to reconcile against"
        )


def test_the_curated_relations_are_still_in_the_shipped_table():
    """A regression guard on the data, not the code.

    If these ever come back as `exact`, something regenerated the table.
    """
    path = pathlib.Path(REGISTRY) / "nomenclature.csv"
    with path.open(encoding="utf-8") as fh:
        rows = list(csv.DictReader(fh))
    by_relation: dict[str, int] = {}
    for row in rows:
        by_relation[row["relation"]] = by_relation.get(row["relation"], 0) + 1
    assert by_relation.get("renamed") == 3, by_relation
    assert by_relation.get("split") == 3, by_relation
    assert by_relation.get("merge") is None, by_relation

    # Whatever the relation, naming several canonicals must mean a merge.
    for row in rows:
        if ";" in row["canonical"]:
            assert row["relation"] == "merge", row
