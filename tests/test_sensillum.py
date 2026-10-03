"""The Sensillum field names a sensillum, never a neuron.

`sensillum_consensus` pooled sensilla with neuron classes, and rule 6 then
kept the longer, neuron one: `ab9` became `Ab9A`. The field now reads
Benton 2025's sensillum, then DoOR's, and neurons stay in "Sensory neuron".
The table on disk is unchanged.
"""

from __future__ import annotations

import csv
import re

from lobemap.core import reference

#: A sensillum followed by a neuron letter: `ab9A`, `At1A`, `ac3IA`, `arB`.
NEURON = re.compile(r"^(?:[Aa][bcit]|[Pp]b|[Aa]r|sac)\d*(?:I{1,3})?[A-D]$")

#: Where the field reads from, in order.
SOURCES = ("sensillum_benton_2025", "sensillum_door")


def _rows(registry_root):
    path = reference.default_path(registry_root)
    with path.open(encoding="utf-8-sig", newline="") as fh:
        return [r for r in csv.DictReader(fh) if r[reference.KEY].strip()]


def _terms(value: str) -> list[str]:
    return [t for t in value.split("; ") if t]


def test_the_pattern_tells_a_neuron_from_a_sensillum():
    assert all(NEURON.match(n) for n in ("ab9A", "At1A", "ac3IA", "ac3IIB", "arB", "pb1A"))
    assert not any(NEURON.match(s) for s in ("ab9", "ac3I", "ac3II", "sacIII-d", "arista", "pb1"))


def test_no_sensillum_is_a_neuron_name(registry_root):
    table = reference.load(registry_root)
    neurons = {t.lower() for props in table.values()
               for t in _terms(props["Sensory neuron"])}
    assert neurons, "no neuron names to compare against"
    for name, props in table.items():
        for term in _terms(props["Sensillum"]):
            assert not NEURON.match(term), (name, term)
            assert term.lower() not in neurons, (name, term)


def test_every_glomerulus_with_a_benton_or_door_sensillum_shows_one(registry_root):
    table = reference.load(registry_root)
    rows = _rows(registry_root)
    sourced = [r for r in rows if any(reference.terms(r[c], split_commas=False)
                                      for c in SOURCES)]
    assert len(sourced) >= 55, len(sourced)
    for row in sourced:
        name = row[reference.KEY].strip()
        first = next(r for r in (row[c] for c in SOURCES)
                     if reference.terms(r, split_commas=False))
        assert table[name]["Sensillum"] == reference.normalize(first, split_commas=False), name


def test_benton_wins_over_door_and_door_fills_its_gaps(registry_root):
    table = reference.load(registry_root)
    # Benton's own split of DoOR's ac3.
    assert table["VC3"]["Sensillum"] == "ac3I; ac3II"
    assert table["D"]["Sensillum"] == "ab9"
    assert table["D"]["Sensory neuron"] == "ab9A"
    # Benton names none for VP1.
    assert table["VP1"]["Sensillum"] == "sacI"
