"""`lobemap check` on the shipped data. Skipped when it is not on disk."""

from __future__ import annotations

from pathlib import Path

import pytest

from lobemap.core.registry import Registry
from lobemap.validate import harness as H

REGISTRY = Path(__file__).resolve().parents[1] / "registry"


def _registry() -> Registry:
    return Registry.load(REGISTRY)


def _have(*asset_ids: str) -> bool:
    reg = Registry.load(REGISTRY, validate=False)
    return all(a in reg.assets and reg.assets[a].path.exists() for a in asset_ids)


def needs(*asset_ids: str):
    return pytest.mark.skipif(
        not _have(*asset_ids), reason="published data not on disk (lobemap fetch)"
    )


SPACE_ASSETS = {
    "FAFB14": ("benton2025_glomeruli", "fafb_neuropil", "fafb_stain"),
    "JRCFIB2018F": ("neuprint_hemibrain_glomeruli", "neuprint_hemibrain_neuropil",
                    "schlegel2021_s11_glomeruli", "schlegel2021_s12_glomeruli",
                    "hemibrain_stain"),
    "JRCFIB2022M": ("neuprint_cns_glomeruli", "neuprint_cns_neuropil", "malecns_stain"),
    "GRABE": ("grabe2015_glomeruli", "grabe2015_labels", "grabe2015_stack"),
}


@needs(*SPACE_ASSETS["JRCFIB2018F"])
def test_compare_pairs_the_hemibrain_rename_chain_by_canonical_name():
    """hemibrain VC5(R) is VM6: it pairs with S12's VM6, never with S12's VC5."""
    pairs, chk = H.compare_atlases(
        _registry(), "neuprint_hemibrain", "schlegel2021_s12", "JRCFIB2018F"
    )
    by_a = {p.a_name: p for p in pairs}
    assert by_a["VC5(R)"].b_name == "VM6"
    assert by_a["VC3l(R)"].b_name == "VC3"
    assert by_a["VC3m(R)"].b_name == "VC5"
    assert all(p.distance_um < 10.0 for p in pairs if p.a_name in ("VC3l(R)", "VC3m(R)", "VC5(R)"))
    assert "0 only in schlegel2021_s12" in chk.detail
