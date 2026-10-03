"""Every data asset says what license it is under, and where that is stated."""

from __future__ import annotations

import tomllib
from pathlib import Path

import pytest

REGISTRY = Path(__file__).resolve().parents[1] / "registry"


def _assets() -> dict:
    with (REGISTRY / "assets.toml").open("rb") as fh:
        return tomllib.load(fh)


@pytest.mark.parametrize("asset_id", sorted(_assets()))
def test_every_asset_has_a_license_and_its_source(asset_id):
    source = _assets()[asset_id].get("source", {})
    assert source.get("license"), f"{asset_id}: no license"
    assert str(source.get("license_url", "")).startswith("https://"), (
        f"{asset_id}: no page stating the license"
    )
    assert source.get("url"), f"{asset_id}: no source URL"


def test_flywire_data_is_non_commercial():
    """FlyWire's public release is CC BY-NC 4.0 (flywire.ai/guidelines)."""
    assets = _assets()
    for asset_id in ("fafb_neuropil", "fafb_stain"):
        assert assets[asset_id]["source"]["license"] == "CC BY-NC 4.0", asset_id
