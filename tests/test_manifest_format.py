"""The manifest file itself: what `dump` writes, `load` must read back.

The manifest is generated, then committed and read on every `fetch`, so a
record `dump` cannot round-trip is a manifest that breaks for everyone.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from lobemap.core import manifest as mf

SHIPPED = Path(__file__).resolve().parents[1] / "registry" / "manifest.toml"


def _round_trip(tmp_path, arts, base_url=None):
    path = tmp_path / "manifest.toml"
    path.write_text(mf.dump(arts, base_url), encoding="utf-8")
    return mf.load(path)


@pytest.mark.parametrize("asset", ["flywire.v783", "with space", 'q"uote', "ünï"])
def test_an_asset_id_toml_would_split_or_reject_round_trips(tmp_path, asset):
    """A dotted id used to open a nested table, and `load` then failed."""
    arts = [mf.Artifact(asset, "a.npz", "file", "a" * 64, 10),
            mf.Artifact("plain", "b.npz", "file", "b" * 64, 5)]
    back, _ = _round_trip(tmp_path, arts)
    assert sorted(back, key=lambda a: a.asset) == sorted(arts, key=lambda a: a.asset)


@pytest.mark.parametrize("text", ['odd "name".npz', "back\\slash.npz", "tab\t.npz",
                                  "del\x7f.npz", "µm.npz"])
def test_a_path_or_url_with_characters_toml_escapes_round_trips(tmp_path, text):
    arts = [mf.Artifact("a", text, "file", "a" * 64, 10)]
    back, base = _round_trip(tmp_path, arts, f"https://example.invalid/{text}")
    assert back == arts
    assert base == f"https://example.invalid/{text}"


def test_the_shipped_manifest_is_what_dump_writes_for_it():
    """Quoting only where needed: the committed file reads as it always did."""
    arts, base_url = mf.load(SHIPPED)
    assert mf.dump(arts, base_url) == SHIPPED.read_text(encoding="utf-8")
