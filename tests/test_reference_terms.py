"""Reference cells that name things must not be split apart.

The cells are the real ones from `glomerulus_ground_truth.csv`.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from lobemap.core import reference

REGISTRY = Path(__file__).resolve().parents[1] / "registry"


@pytest.mark.parametrize(("glomerulus", "column", "want"), [
    # `+` is part of this name: the sensillum is chambers I and II together.
    ("VP4", "sensillum", "Sacculus, Chambers I + II; sacI and sacII"),
    # DL2v's receptor is Ir75c. The pooled `(subset Ir75c)` from another
    # source must not replace it.
    ("DL2v", "receptor(s)", "Ir75a; Ir75b; Ir75c"),
    # The neighbor that really is a subset keeps the qualifier.
    ("DL2d", "receptor(s)", "Ir75a; Ir75b; Ir75c (subset)"),
    # A synonym in parentheses still absorbs the bare spelling.
    ("DC3", "sensillum", "Ai2A (At2A); at2"),
    # `+` still expands gene shorthand in a receptor cell.
    ("DL3", "receptor(s)", "Or65a; Or65b; Or65c"),
])
def test_named_cells_are_not_split_apart(glomerulus, column, want):
    assert reference.load(REGISTRY)[glomerulus][column] == want
