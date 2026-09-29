"""Normalizing the pooled reference cells.

Each cell in `glomerulus_ground_truth.csv` merges several publications, so
one receptor can arrive spelled three ways in one string. The cases here
are taken from the real table, not invented.
"""

from __future__ import annotations

import pytest

from lobemap.core import reference


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


def test_the_shipped_table_loads(registry_root):
    assert reference.default_path(registry_root).exists(), "reference table missing"
    table = reference.load(registry_root)
    assert len(table) >= 62, len(table)


@pytest.mark.requires_data
def test_every_compartment_of_every_atlas_joins_the_table(registry_root, registry):
    """All of them, which is what the shipped table achieves.

    The bar used to be half, on the theory that every atlas carries
    compartments the table does not list. None does: all 476 compartments
    of the six atlases join, so a half-empty annotation column would have
    passed.
    """
    table = reference.load(registry_root)
    assert registry.atlases
    for atlas in registry.atlases.values():
        assert atlas.compartments, f"{atlas.id} has no compartments"
        missed = [
            c.published_name for c in atlas.compartments
            if not any(table.get(k) or table.get(k.lower())
                       for k in (list(c.canonical) + [c.published_name]))
        ]
        assert not missed, (
            f"{atlas.id}: {len(missed)}/{len(atlas.compartments)} "
            f"compartments have no reference row: {missed[:6]}"
        )
