"""Fetching data must be verifiable, and must fail closed.

A checksum that is only checked after the file is in place is not a checksum.
These tests drive the real download path over `file://` URLs, so the failure
modes are exercised rather than described.
"""

from __future__ import annotations

import shutil

import pytest

from lobemap.core import manifest as mf


class _Asset:
    def __init__(self, aid, path):
        self.id = aid
        self.path = path


def _tree(root):
    """A data root holding one file artifact and one directory artifact."""
    root.mkdir(parents=True, exist_ok=True)
    f = root / "mesh.npz"
    f.write_bytes(b"vertices and faces" * 100)
    d = root / "stain.zarr"
    (d / "0").mkdir(parents=True)
    (d / ".zattrs").write_text('{"multiscales": []}', encoding="utf-8")
    (d / "0" / "0.0.0").write_bytes(b"chunk bytes" * 50)
    return [_Asset("mesh", f), _Asset("stain", d)]


def test_build_records_both_kinds(tmp_path):
    arts = mf.build(tmp_path, _tree(tmp_path / "data"))
    assert {a.asset for a in arts} == {"mesh", "stain"}
    kinds = {a.asset: a.kind for a in arts}
    assert kinds == {"mesh": "file", "stain": "dir"}
    assert all(len(a.sha256) == 64 and a.size > 0 for a in arts)


def test_zipping_a_store_twice_gives_identical_bytes(tmp_path):
    """Or every rebuild would look like changed data."""
    _tree(tmp_path / "data")
    src = tmp_path / "data" / "stain.zarr"
    a = mf.zip_directory(src, tmp_path / "a.zip")
    b = mf.zip_directory(src, tmp_path / "b.zip")
    assert a.read_bytes() == b.read_bytes()
    assert mf.sha256_file(a)[0] == mf.sha256_file(b)[0]


def test_manifest_round_trips_through_toml(tmp_path):
    arts = mf.build(tmp_path, _tree(tmp_path / "data"))
    path = tmp_path / "manifest.toml"
    path.write_text(mf.dump(arts, "https://example.invalid/v1"), encoding="utf-8")
    back, base = mf.load(path)
    assert base == "https://example.invalid/v1"
    assert back == arts


def test_no_base_url_is_recorded_when_none_is_known(tmp_path):
    arts = mf.build(tmp_path, _tree(tmp_path / "data"))
    text = mf.dump(arts, None)
    assert "base_url =" not in text
    path = tmp_path / "m.toml"
    path.write_text(text, encoding="utf-8")
    assert mf.load(path)[1] is None


def test_verify_reports_ok_missing_and_corrupt(tmp_path):
    data = tmp_path / "data"
    arts = mf.build(tmp_path, _tree(data))
    assert all(s.state == "ok" for s in mf.verify(arts, tmp_path))

    (data / "mesh.npz").write_bytes(b"tampered")
    shutil.rmtree(data / "stain.zarr")
    states = {s.artifact.asset: s.state for s in mf.verify(arts, tmp_path)}
    assert states == {"mesh": "corrupt", "stain": "missing"}


def test_a_changed_chunk_inside_a_store_is_detected(tmp_path):
    """The whole point of hashing the zip rather than the directory entry."""
    data = tmp_path / "data"
    arts = mf.build(tmp_path, _tree(data))
    (data / "stain.zarr" / "0" / "0.0.0").write_bytes(b"different chunk bytes")
    states = {s.artifact.asset: s.state for s in mf.verify(arts, tmp_path)}
    assert states["stain"] == "corrupt"


def test_fetch_downloads_and_unpacks_both_kinds(tmp_path):
    src = tmp_path / "src" / "x"
    arts = mf.build(src, _tree(src))
    # Publish: lay the transfer files out as a server would.
    pub = tmp_path / "pub"
    pub.mkdir()
    shutil.copy(src / "mesh.npz", pub / "mesh.npz")
    mf.zip_directory(src / "stain.zarr", pub / "stain.zarr.zip")

    dst = tmp_path / "dst"
    results = mf.fetch(arts, dst, pub.as_uri())
    assert [s.state for s in results] == ["ok", "ok"]
    assert (dst / "mesh.npz").read_bytes() == (src / "mesh.npz").read_bytes()
    assert (dst / "stain.zarr" / ".zattrs").exists()
    assert (dst / "stain.zarr" / "0" / "0.0.0").exists()
    assert all(s.state == "ok" for s in mf.verify(arts, dst))


def test_fetch_refuses_a_bad_checksum_and_leaves_nothing(tmp_path):
    src = tmp_path / "src" / "x"
    arts = mf.build(src, _tree(src))
    pub = tmp_path / "pub"
    pub.mkdir()
    (pub / "mesh.npz").write_bytes(b"not what was promised")
    mf.zip_directory(src / "stain.zarr", pub / "stain.zarr.zip")

    dst = tmp_path / "dst"
    results = {s.artifact.asset: s for s in mf.fetch(arts, dst, pub.as_uri())}
    assert results["mesh"].state == "corrupt"
    assert "sha256" in results["mesh"].detail
    assert not (dst / "mesh.npz").exists(), "a bad download must not be kept"
    assert results["stain"].state == "ok", "one bad artifact must not block others"


def test_fetch_reports_a_missing_url_without_raising(tmp_path):
    arts = mf.build(tmp_path, _tree(tmp_path / "data"))
    dst = tmp_path / "dst"
    results = mf.fetch(arts, dst, (tmp_path / "nothing-here").as_uri())
    assert all(s.state == "missing" for s in results)
    assert all(s.detail for s in results)


def test_transfer_name_appends_zip_only_for_directories():
    f = mf.Artifact("a", "m.npz", "file", "0" * 64, 1)
    d = mf.Artifact("b", "s.zarr", "dir", "0" * 64, 1)
    assert f.transfer_name == "m.npz"
    assert d.transfer_name == "s.zarr.zip"


def test_shipped_manifest_matches_what_is_on_disk():
    """The committed manifest must describe the real registry."""
    from pathlib import Path

    from lobemap.core.registry import Registry, default_data_root

    root = Path(__file__).resolve().parents[1] / "registry"
    path = root / "manifest.toml"
    if not path.exists():
        pytest.skip("no manifest committed")
    arts, _ = mf.load(path)
    reg = Registry.load(root, validate=False)
    present = {a.id for a in reg.assets.values() if a.path.exists()}
    listed = {a.asset for a in arts}
    assert listed <= set(reg.assets), f"manifest names unknown assets: {listed - set(reg.assets)}"
    assert present <= listed, f"present but unlisted: {present - listed}"
    _ = default_data_root(root)
