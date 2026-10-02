"""Normalizing the pooled reference cells.

Each cell in `glomerulus_ground_truth.csv` merges several publications, so
one receptor can arrive spelled three ways in one string. The cases here
are taken from the real table, not invented.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from lobemap.core import reference

REGISTRY = Path(__file__).resolve().parents[1] / "registry"


@pytest.mark.parametrize(("raw", "want"), [
    # The two worked examples.
    ("Or69aA, Or69aB; Or69aA/B; Or69a", "Or69aA; Or69aB"),
    ("Ir75b; Ir75a/b (subset Ir75c) (co Ir8a)", "Ir75a; Ir75b; Ir75c (subset)"),
    # `+` shorthand shares the stem; three receptors, not one.
    ("Or65a, Or65b, Or65c; Or65a+b+c", "Or65a; Or65b; Or65c"),
    # A bare numeric suffix inherits only the alphabetic prefix.
    ("Or47a, Or33b; Or47a; Or47a+33b", "Or33b; Or47a"),
    # `/` between two full gene names separates rather than expands.
    ("Rh50/Amt", "Amt; Rh50"),
    ("Gr21a, Gr63a; Gr21a/Gr63a; Gr21a+Gr63a", "Gr21a; Gr63a"),
    # A co-receptor is not the receptor.
    ("Ir31a; Ir31a (co Ir8a)", "Ir31a"),
    ("Ir92a; Ir92a (co Ir25a+Ir76b)", "Ir92a"),
    # Case differences are one receptor.
    ("Or35a; OR35a", "Or35a"),
    # A prefix says less than what extends it.
    ("Gr28b.d, Ir93a; Gr28b, (co Ir25a)", "Gr28b.d; Ir93a"),
    ("Or46a; Or46aA", "Or46aA"),
    # Nothing recorded stays nothing.
    ("", ""), ("-", ""), ("UNK", ""),
])
def test_receptor_cells(raw, want):
    assert reference.normalize(raw, split_commas=True) == want


@pytest.mark.parametrize(("raw", "want"), [
    # The comma belongs to the name here, so it must not split.
    ("Sacculus, Chamber III; sacIII", "Sacculus, Chamber III; sacIII"),
    ("Sacculus, Chamber I; sacI", "Sacculus, Chamber I; sacI"),
    # A bare sensillum is a prefix of its neuron class.
    ("Ab9A; ab9", "Ab9A"),
    # A parenthetical that is not a co-receptor is a synonym: keep it.
    ("Ai1A (Ab6A); ab6", "ab6; Ai1A (Ab6A)"),
])
def test_sensillum_cells(raw, want):
    assert reference.normalize(raw, split_commas=False) == want


def test_the_shipped_table_loads_and_covers_the_atlases():
    from lobemap.core.registry import Registry

    assert reference.default_path(REGISTRY).exists(), "reference table missing"
    table = reference.load(REGISTRY)
    assert len(table) >= 62, len(table)

    reg = Registry.load(REGISTRY, validate=False)
    for atlas in reg.atlases.values():
        if not atlas.compartments:
            continue
        missed = [
            c.published_name for c in atlas.compartments
            if not any(table.get(k) or table.get(k.lower())
                       for k in (list(c.canonical) + [c.published_name]))
        ]
        # Every atlas carries non-olfactory or split compartments the
        # reference table does not list; most should still join.
        matched = len(atlas.compartments) - len(missed)
        assert matched >= 0.5 * len(atlas.compartments), (
            f"{atlas.id}: only {matched}/{len(atlas.compartments)} joined; "
            f"missed e.g. {missed[:6]}"
        )
