"""Glomerulus names are defined per SPACE, not once for the registry.

An atlas belongs to exactly one space and is only ever shown there, so two
atlases can be superimposed only if they share a space. Names therefore only
have to agree within a space, and each space keeps its own vocabulary.

The single global vocabulary this replaces had to pick one atlas as the
authority and restate every other atlas in its terms -- awkward exactly
where the communities disagree, as in the Schlegel 2021 rename chain.
"""

from __future__ import annotations

import pytest

from lobemap.core.registry import Registry


@pytest.fixture(scope="module")
def registry():
    return Registry.load("registry", validate=False)


def test_each_space_with_atlases_has_a_vocabulary(registry):
    for space_id in registry.spaces:
        atlases = registry.atlases_in_space(space_id)
        vocabulary = registry.vocabulary(space_id)
        if atlases:
            assert vocabulary, f"{space_id} has atlases but names nothing"
        else:
            assert vocabulary == [], f"{space_id} has no atlases but has names"


def test_a_vocabulary_covers_its_own_atlases_only(registry):
    """A space's names come from its atlases and nowhere else."""
    for space_id in registry.spaces:
        expected = set()
        for atlas in registry.atlases_in_space(space_id):
            for compartment in atlas.compartments:
                expected.update(compartment.canonical)
        assert set(registry.vocabulary(space_id)) == expected


def test_vocabularies_are_independent(registry):
    """Spaces may disagree, and that is the point.

    GRABE resolves 56 names where FAFB resolves 58. Under one global
    vocabulary that difference had to be reconciled; now it simply is not.
    """
    sizes = {s: len(registry.vocabulary(s)) for s in registry.spaces}
    populated = {s: n for s, n in sizes.items() if n}
    assert len(populated) >= 3, sizes
    assert len(set(populated.values())) > 1, (
        f"every space resolves the same number of names ({sizes}); this test "
        f"is meant to show they are independent"
    )


def test_the_vocabulary_is_stable(registry):
    """Color is assigned by position, so the order cannot wobble."""
    for space_id in registry.spaces:
        first = registry.vocabulary(space_id)
        assert first == registry.vocabulary(space_id)
        assert first == sorted(first)


def test_hemibrain_is_the_only_space_needing_reconciliation(registry):
    """One atlas per space everywhere else, so nothing to reconcile there."""
    several = [
        s for s in registry.spaces if len(registry.atlases_in_space(s)) > 1
    ]
    assert several == ["JRCFIB2018F"], (
        f"spaces with several atlases: {several}. If this changed, the "
        f"vocabulary for the new one has to be checked by hand."
    )


def test_bates_is_gone(registry):
    """Superseded by Benton 2025, which revises the same meshes."""
    assert "bates2020" not in registry.atlases
    assert "bates2020_glomeruli" not in registry.assets
    assert not (registry.data_root / "bates2020_glomeruli.npz").exists()
