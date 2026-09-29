"""A store on disk is verified by its content, not by zipping it again.

Re-zipping made `fetch --check` depend on the zip's bytes -- the platform
byte in each entry and the zlib build's output -- so a store that was fine
read as corrupt wherever either differed, and each check wrote a temporary
zip of up to 1.1 GB. Downloads are still checked against the published
zip's sha256; that is what pins the bytes on the release.
"""

from __future__ import annotations

import zipfile
import zlib
from dataclasses import replace
from pathlib import Path

import pytest

from lobemap.core import manifest as mf

REGISTRY = Path(__file__).resolve().parents[1] / "registry"


class _Asset:
    def __init__(self, aid, path):
        self.id = aid
        self.path = path


def _tree(root):
    """A data root holding one file artifact and one store."""
    root.mkdir(parents=True, exist_ok=True)
    (root / "mesh.npz").write_bytes(b"vertices and faces" * 100)
    store = root / "stain.zarr"
    (store / "0").mkdir(parents=True)
    (store / ".zattrs").write_text('{"multiscales": []}', encoding="utf-8")
    for i in range(12):
        (store / "0" / f"{i}.0.0").write_bytes(bytes(range(256)) * (30 + i))
    return [_Asset("mesh", root / "mesh.npz"), _Asset("stain", store)]


def _snapshot(folder):
    return sorted((p.relative_to(folder).as_posix(), p.stat().st_size)
                  for p in folder.rglob("*"))


def _no_zips(monkeypatch):
    def refuse(*a, **k):
        raise AssertionError("verification must not build a zip")
    monkeypatch.setattr(zipfile, "ZipFile", refuse)


@pytest.mark.parametrize("platform", ["win32", "darwin", "linux"])
@pytest.mark.parametrize("level", [None, 1, 9])
def test_a_store_verifies_the_same_on_every_platform_and_zlib(tmp_path, monkeypatch,
                                                              platform, level):
    """The published stains are zlib-6 zips made on Windows; a check on any
    other platform or zlib build must still pass, and still catch damage."""
    data = tmp_path / "data"
    arts = mf.build(tmp_path, _tree(data))
    stain = next(a for a in arts if a.kind == "dir")

    monkeypatch.setattr("sys.platform", platform)
    if level is not None:
        real = zlib.compressobj
        monkeypatch.setattr(zlib, "Z_DEFAULT_COMPRESSION", level)
        monkeypatch.setattr(zlib, "compressobj",
                            lambda lvl=level, *a, **k: real(level, *a, **k))
    _no_zips(monkeypatch)

    assert [s.state for s in mf.verify(arts, tmp_path)] == ["ok", "ok"]
    assert mf.tree_digest(data / "stain.zarr") == (stain.tree_sha256, stain.files)

    (data / "stain.zarr" / "0" / "3.0.0").write_bytes(b"different chunk")
    states = {s.artifact.asset: s.state for s in mf.verify(arts, tmp_path)}
    assert states == {"mesh": "ok", "stain": "corrupt"}


def test_verification_writes_nothing(tmp_path):
    arts = mf.build(tmp_path, _tree(tmp_path / "data"))
    before = _snapshot(tmp_path)
    assert all(s.state == "ok" for s in mf.verify(arts, tmp_path))
    assert _snapshot(tmp_path) == before


@pytest.mark.parametrize("change", ["extra", "missing", "renamed"])
def test_a_store_that_gained_lost_or_renamed_a_file_is_corrupt(tmp_path, change):
    data = tmp_path / "data"
    arts = mf.build(tmp_path, _tree(data))
    chunk = data / "stain.zarr" / "0" / "0.0.0"
    if change == "extra":
        (data / "stain.zarr" / "0" / "99.0.0").write_bytes(b"x")
    elif change == "missing":
        chunk.unlink()
    else:
        chunk.rename(chunk.with_name("0.0.1"))
    (status,) = [s for s in mf.verify(arts, tmp_path) if s.artifact.kind == "dir"]
    assert status.state == "corrupt"


def test_the_digest_ignores_how_the_store_was_zipped(tmp_path):
    """Unpacking a zip made at another level gives the same content digest."""
    data = tmp_path / "data"
    _tree(data)
    archive = tmp_path / "level9.zip"
    with zipfile.ZipFile(archive, "w", zipfile.ZIP_DEFLATED, compresslevel=9) as zf:
        for p in sorted((data / "stain.zarr").rglob("*")):
            if p.is_file():
                zf.write(p, p.relative_to(data / "stain.zarr").as_posix())
    out = mf.unzip_directory(archive, tmp_path / "unpacked.zarr")
    assert mf.tree_digest(out) == mf.tree_digest(data / "stain.zarr")


def test_zip_entries_are_deflated_at_the_level_the_code_states(tmp_path):
    """`compresslevel=1` was passed and ignored; the zips were always level 6."""
    _tree(tmp_path / "data")
    src = tmp_path / "data" / "stain.zarr"
    archive = mf.zip_directory(src, tmp_path / "s.zip")
    with zipfile.ZipFile(archive) as zf:
        for info in zf.infolist():
            data = zf.read(info)
            c = zlib.compressobj(mf.ZIP_LEVEL, zlib.DEFLATED, -15)
            assert info.compress_size == len(c.compress(data) + c.flush())


def test_fetch_refuses_a_zip_that_unpacks_to_the_wrong_content(tmp_path):
    src, pub, dst = tmp_path / "src", tmp_path / "pub", tmp_path / "dst"
    arts = mf.build(src, _tree(src))
    pub.mkdir()
    (pub / "mesh.npz").write_bytes((src / "mesh.npz").read_bytes())
    mf.zip_directory(src / "stain.zarr", pub / "stain.zarr.zip")
    lying = [replace(a, tree_sha256="0" * 64) if a.kind == "dir" else a for a in arts]

    results = {s.artifact.asset: s for s in mf.fetch(lying, dst, pub.as_uri())}
    assert results["stain"].state == "corrupt"
    assert "unpacked content" in results["stain"].detail
    assert not (dst / "stain.zarr").exists()
    assert results["mesh"].state == "ok"


def test_fetch_into_an_empty_root_then_verifies(tmp_path):
    src, pub, dst = tmp_path / "src", tmp_path / "pub", tmp_path / "dst"
    arts = mf.build(src, _tree(src))
    pub.mkdir()
    (pub / "mesh.npz").write_bytes((src / "mesh.npz").read_bytes())
    mf.zip_directory(src / "stain.zarr", pub / "stain.zarr.zip")
    assert [s.state for s in mf.fetch(arts, dst, pub.as_uri())] == ["ok", "ok"]
    assert [s.state for s in mf.verify(arts, dst)] == ["ok", "ok"]
    assert _snapshot(dst) == _snapshot(src)


FORMAT_1 = """\
# Fetchable data artifacts. Generated by `lobemap manifest`.
# sha256 is of the transferred bytes: for a .zarr store, of its zip.

version = 1
base_url = "{url}"

[artifacts.mesh]
path = "mesh.npz"
kind = "file"
sha256 = "{mesh_sha}"
size = {mesh_size}

[artifacts.stain]
path = "stain.zarr"
kind = "dir"
sha256 = "{zip_sha}"
size = {zip_size}
"""


def test_a_format_1_manifest_still_loads_fetches_and_says_what_it_cannot_check(tmp_path):
    src, pub, dst = tmp_path / "src", tmp_path / "pub", tmp_path / "dst"
    _tree(src)
    pub.mkdir()
    (pub / "mesh.npz").write_bytes((src / "mesh.npz").read_bytes())
    archive = mf.zip_directory(src / "stain.zarr", pub / "stain.zarr.zip")
    mesh_sha, mesh_size = mf.sha256_file(pub / "mesh.npz")
    zip_sha, zip_size = mf.sha256_file(archive)
    path = tmp_path / "manifest.toml"
    path.write_text(FORMAT_1.format(url=pub.as_uri(), mesh_sha=mesh_sha,
                                    mesh_size=mesh_size, zip_sha=zip_sha,
                                    zip_size=zip_size), encoding="utf-8")

    arts, base_url = mf.load(path)
    assert base_url == pub.as_uri()
    assert all(a.tree_sha256 is None for a in arts)
    assert [s.state for s in mf.fetch(arts, dst, base_url)] == ["ok", "ok"]
    states = {s.artifact.asset: s for s in mf.verify(arts, dst)}
    assert states["mesh"].state == "ok"
    assert states["stain"].state == "unverified"
    assert "lobemap manifest" in states["stain"].detail


def test_a_newer_manifest_format_is_refused(tmp_path):
    path = tmp_path / "manifest.toml"
    path.write_text(f"version = {mf.MANIFEST_VERSION + 1}\n", encoding="utf-8")
    with pytest.raises(ValueError, match="Upgrade lobemap"):
        mf.load(path)


def test_rerecording_an_unchanged_store_keeps_the_published_zip_hash(tmp_path,
                                                                     monkeypatch):
    """Another machine's zlib must not swap the release's hash for its own."""
    assets = _tree(tmp_path / "data")
    arts = mf.build(tmp_path, assets)
    published = [replace(a, sha256="f" * 64, size=123) if a.kind == "dir" else a
                 for a in arts]
    _no_zips(monkeypatch)
    again = {a.asset: a for a in mf.build(tmp_path, assets, previous=published)}
    assert (again["stain"].sha256, again["stain"].size) == ("f" * 64, 123)


def test_rerecording_a_changed_store_zips_it_again(tmp_path):
    assets = _tree(tmp_path / "data")
    arts = mf.build(tmp_path, assets)
    (tmp_path / "data" / "stain.zarr" / "0" / "0.0.0").write_bytes(b"new")
    again = {a.asset: a for a in mf.build(tmp_path, assets, previous=arts)}
    old = {a.asset: a for a in arts}
    assert again["stain"].tree_sha256 != old["stain"].tree_sha256
    assert again["stain"].sha256 != old["stain"].sha256


def test_every_store_in_the_shipped_manifest_has_a_content_digest():
    arts, _ = mf.load(REGISTRY / "manifest.toml")
    stores = [a for a in arts if a.kind == "dir"]
    assert stores
    assert all(a.tree_sha256 and a.files for a in stores)


@pytest.mark.requires_data
def test_the_shipped_stores_verify_by_content_and_write_nothing(monkeypatch):
    from lobemap.core.registry import default_data_root

    arts, _ = mf.load(REGISTRY / "manifest.toml")
    data_root = default_data_root(REGISTRY)
    stores = [a for a in arts if a.kind == "dir"]
    if not all((data_root / a.path).is_dir() for a in stores):
        pytest.skip(f"the virtual stains are not in {data_root}")
    _no_zips(monkeypatch)
    assert [s.state for s in mf.verify(stores, data_root)] == ["ok"] * len(stores)
    assert not (data_root / ".manifest").exists()
