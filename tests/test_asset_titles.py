"""Every asset has one plain title, written once in `assets.toml`.

The panel's tabs read it, and so will layer names and hover text: a title
written in three places drifts into three names for one thing.
"""

from __future__ import annotations

import re

import pytest

#: The tab titles Gustavo approved, by the part each tab is keyed on.
APPROVED = {
    "benton2025": "Benton 2025",
    "neuprint_hemibrain": "neuPrint",
    "neuprint_cns": "neuPrint",
    "schlegel2021_s11": "Schlegel (sensory)",
    "schlegel2021_s12": "Schlegel (projection)",
    "grabe2015": "Grabe 2015",
    "fafb_neuropil": "Neuropils",
    "neuprint_hemibrain_neuropil": "Neuropils",
    "neuprint_cns_neuropil": "Neuropils",
}


def test_every_asset_has_a_plain_title_and_one_line_about_it(registry):
    for asset in registry.assets.values():
        assert asset.title, f"{asset.id}: no title"
        assert asset.about, f"{asset.id}: no about line"
        for text in (asset.title, asset.about):
            assert "_" not in text, (asset.id, text)
            assert asset.id not in text, (asset.id, text)
        # A short citation, then what the asset is.
        assert re.match(r"^[A-Z][a-z]+ et al\. \d{4}, [^:]+: \S", asset.about), asset.about


@pytest.mark.parametrize(("name", "title"), sorted(APPROVED.items()))
def test_a_part_reaches_its_title_by_atlas_id_or_asset_id(registry, name, title):
    asset = registry.asset_of(name)
    assert asset is not None, name
    assert asset.title == title


def test_asset_of_names_nothing_for_an_unknown_id(registry):
    assert registry.asset_of("no_such_thing") is None


def test_the_schlegel_tabs_say_how_each_was_defined(registry):
    assert registry.asset_of("schlegel2021_s11").about == (
        "Schlegel et al. 2021, eLife, file 11: glomeruli defined from sensory neurons"
    )
    assert registry.asset_of("schlegel2021_s12").about == (
        "Schlegel et al. 2021, eLife, file 12: glomeruli defined from projection neurons"
    )
