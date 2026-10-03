"""`manifest --prune` drops records for absent artifacts, and nothing else.

It used to read the previous manifest only on the path that keeps
records, so pruning also dropped `base_url`: the next `fetch` had nowhere
to download from.
"""

from __future__ import annotations

import pytest

from lobemap.cli import main
from lobemap.core import manifest as mf

URL = "https://example.org/releases/download/data-v9"


@pytest.fixture
def published(tmp_path):
    reg = tmp_path / "registry"
    reg.mkdir()
    (reg / "spaces.toml").write_text('[S1]\ntitle = "S"\nunits = "um"\n')
    (reg / "assets.toml").write_text(
        '[kept]\nrole = "glomeruli"\nspace = "S1"\npath = "data/kept.npz"\n\n'
        '[gone]\nrole = "neuropil"\nspace = "S1"\npath = "data/gone.npz"\n'
    )
    data = tmp_path / "data"
    data.mkdir()
    (data / "kept.npz").write_bytes(b"kept" * 10)
    (data / "gone.npz").write_bytes(b"gone" * 10)
    argv = ["--registry", str(reg), "--data-root", str(data), "manifest"]
    assert main([*argv, "--base-url", URL]) == 0
    (data / "gone.npz").unlink()
    return reg, argv


def test_prune_keeps_base_url_and_drops_the_absent_record(published):
    reg, argv = published
    assert main([*argv, "--prune"]) == 0
    arts, base_url = mf.load(reg / "manifest.toml")
    assert base_url == URL
    assert [a.asset for a in arts] == ["kept"]


def test_without_prune_the_absent_record_stays(published):
    reg, argv = published
    assert main(argv) == 0
    arts, base_url = mf.load(reg / "manifest.toml")
    assert base_url == URL
    assert sorted(a.asset for a in arts) == ["gone", "kept"]
