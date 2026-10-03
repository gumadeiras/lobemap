"""Reference cells that name things must not be split apart.

The cells are the real ones from `glomerulus_ground_truth.csv`.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from lobemap.core import reference

REGISTRY = Path(__file__).resolve().parents[1] / "registry"


@pytest.mark.parametrize(("glomerulus", "column", "want"), [
    # Benton's two sacculus chambers, both kept: sacI is not part of sacII.
    ("VP4", "Sensillum", "sacI; sacII"),
    # DL2v's receptor is Ir75c. The pooled `(subset Ir75c)` from another
    # source must not replace it.
    ("DL2v", "Receptor", "Ir75a; Ir75b; Ir75c"),
    # The neighbor that really is a subset keeps the qualifier.
    ("DL2d", "Receptor", "Ir75a; Ir75b; Ir75c (subset)"),
    # The sensillum, not the neuron: Benton's `ai2`, where the pooled
    # column said `Ai2A (At2A)`. The neuron has its own field.
    ("DC3", "Sensillum", "ai2"),
    ("DC3", "Sensory neuron", "ai2A"),
    # Benton names none for VP1; DoOR's sensillum is the fallback.
    ("VP1", "Sensillum", "sacI"),
    # `+` still expands gene shorthand in a receptor cell.
    ("DL3", "Receptor", "Or65a; Or65b; Or65c"),
])
def test_named_cells_are_not_split_apart(glomerulus, column, want):
    assert reference.load(REGISTRY)[glomerulus][column] == want
