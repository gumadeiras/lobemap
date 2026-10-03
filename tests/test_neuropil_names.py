"""Every neuropil the viewer lists has a cited full name.

`registry/reference/neuropil_names.csv` maps each neuropil set's names to
one full name from a primary source; its README cites them. A name with
no source is shown as "—" and must be listed in `UNSOURCED` here, so a set
cannot gain a neuropil the table silently does not name.
"""

from __future__ import annotations

import csv

import pytest

from lobemap.core import reference
from lobemap.core.names import parse_roi

NEUROPIL_SETS = ("fafb_neuropil", "neuprint_hemibrain_neuropil", "neuprint_cns_neuropil")

#: Names no primary source gives a full name for. None, today.
UNSOURCED: frozenset[str] = frozenset()

#: The sources the README cites, as the table writes them.
CITED = {"Ito et al. 2014, Neuron", "Scheffer et al. 2020, eLife",
         "Schlegel et al. 2024, Nature"}


def _table_rows(registry_root):
    with reference.neuropil_path(registry_root).open(encoding="utf-8", newline="") as fh:
        return list(csv.DictReader(fh))


def test_every_row_names_a_cited_source(registry_root):
    rows = _table_rows(registry_root)
    assert rows
    names = [r["name"] for r in rows]
    assert len(names) == len(set(names)), "a name has two rows"
    readme = (registry_root / "reference" / "README.md").read_text(encoding="utf-8")
    for row in rows:
        assert row["full_name"].strip(), row
        assert row["source"] in CITED, row
        # Keyed without the side, which the viewer strips before it looks.
        assert parse_roi(row["name"])[1] is None, row
    for source in CITED:
        assert source.split(",")[0].split(" et al.")[0] in readme, source


def test_one_structure_has_one_full_name_however_it_is_spelled(registry_root):
    names = reference.neuropil_names(registry_root)
    assert names["MB_PED"][0] == names["PED"][0] == "mushroom body pedunculus"
    assert names["MB_CA"][0] == names["CA"][0] == "mushroom body calyx"
    # Every part of the mushroom body says so, its lobes with Ito's primes.
    assert names["a'L"][0] == "mushroom body \u03b1\u2032 lobe"
    assert names["SPS"][0] == "superior posterior slope"
    assert names["AL"] == ("antennal lobe", "Ito et al. 2014, Neuron")


@pytest.mark.requires_data(*NEUROPIL_SETS)
@pytest.mark.parametrize("asset", NEUROPIL_SETS)
def test_every_neuropil_in_every_set_resolves(registry, asset):
    names = reference.neuropil_names(registry.root)
    published = registry.mesh(asset).names
    missing = sorted({parse_roi(n)[0] for n in published} - set(names) - UNSOURCED)
    assert not missing, f"{asset}: no cited full name for {missing}"
    assert not UNSOURCED & set(names), "an unsourced name now has a row"
