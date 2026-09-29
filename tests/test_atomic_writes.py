"""An interrupted write must leave nothing that passes as the artifact.

Presence is existence here: `fetch` skips what is on disk, `build` refuses to
overwrite it, and the viewer opens it. A Zarr store cut off part-way used to
open without error and read zeros for every chunk it had not reached.
"""

from __future__ import annotations

import zipfile

import numpy as np
import pytest

from lobemap import build as B
from lobemap.core import manifest as mf
from lobemap.core import zarrfmt
from lobemap.core.atomic import replacing
from lobemap.core.imagefmt import Volume
from lobemap.core.meshfmt import MeshSet
from lobemap.core.registry import Registry


class Interrupted(Exception):
    pass


def _meshset(offset=0.0):
    v = np.array([[0, 0, 0], [1, 0, 0], [0, 1, 0]], np.float32) + offset
    return MeshSet.from_parts([("DA1(R)", v, np.array([[0, 1, 2]]))])


def _volume(value=7, shape=(96, 64, 64)):
    return Volume(data=np.full(shape, value, np.uint8), voxel_um=(1.0,) * 3,
                  origin_um=(0.0,) * 3, meta={"source": "test"})


def _leftovers(folder, keep):
    return sorted(p.name for p in folder.iterdir() if p.name not in keep)


def test_an_interrupted_mesh_save_keeps_the_old_file(tmp_path, monkeypatch):
    path = _meshset().save(tmp_path / "m.npz")
    before = path.read_bytes()

    def partial(fh, **arrays):
        fh.write(b"PK\x03\x04 half a zip")
        raise Interrupted

    monkeypatch.setattr(np, "savez_compressed", partial)
    with pytest.raises(Interrupted):
        _meshset(offset=5.0).save(path)
    assert path.read_bytes() == before
    assert _leftovers(tmp_path, {"m.npz"}) == []


def test_an_interrupted_zarr_write_leaves_no_store(tmp_path, monkeypatch):
    monkeypatch.setattr(zarrfmt, "downsample",
                        lambda *a, **k: (_ for _ in ()).throw(Interrupted()))
    with pytest.raises(Interrupted):
        _volume().save(tmp_path / "s.zarr", chunks=(16, 16, 16), min_extent=32)
    assert not (tmp_path / "s.zarr").exists()
    assert _leftovers(tmp_path, set()) == []


def test_an_interrupted_zarr_rewrite_keeps_the_old_store(tmp_path, monkeypatch):
    path = _volume(value=7).save(tmp_path / "s.zarr", chunks=(16, 16, 16),
                                 min_extent=32)
    monkeypatch.setattr(zarrfmt, "downsample",
                        lambda *a, **k: (_ for _ in ()).throw(Interrupted()))
    with pytest.raises(Interrupted):
        _volume(value=99).save(path, chunks=(16, 16, 16), min_extent=32)
    back = Volume.load(path)
    assert all((np.asarray(a) == 7).all() for a in back.levels)
    assert _leftovers(tmp_path, {"s.zarr"}) == []


def test_a_completed_zarr_rewrite_replaces_the_store(tmp_path):
    path = _volume(value=7).save(tmp_path / "s.zarr", chunks=(16, 16, 16),
                                 min_extent=32)
    _volume(value=99, shape=(64, 64, 64)).save(path, chunks=(16, 16, 16),
                                               min_extent=32)
    back = Volume.load(path)
    assert back.shape == (64, 64, 64)
    assert all((np.asarray(a) == 99).all() for a in back.levels)
    assert _leftovers(tmp_path, {"s.zarr"}) == []


def test_an_interrupted_unpack_during_fetch_leaves_no_store(tmp_path, monkeypatch):
    src, pub, dst = tmp_path / "src", tmp_path / "pub", tmp_path / "dst"
    store = _volume().save(src / "s.zarr", chunks=(16, 16, 16), min_extent=32)

    class Asset:
        id, path = "s", store

    arts = mf.build(src, [Asset()])
    pub.mkdir()
    mf.zip_directory(store, pub / "s.zarr.zip")

    real = zipfile.ZipFile.extractall

    def cut_short(self, path=None, members=None, pwd=None):
        names = self.namelist()
        real(self, path, names[: len(names) - 3], pwd)   # metadata arrives
        raise OSError("connection reset")

    monkeypatch.setattr(zipfile.ZipFile, "extractall", cut_short)
    (status,) = mf.fetch(arts, dst, pub.as_uri())
    assert status.state == "missing"
    assert not (dst / "s.zarr").exists()
    assert _leftovers(dst, set()) == []


def test_an_interrupted_build_leaves_the_asset_missing(tmp_path, monkeypatch):
    (tmp_path / "spaces.toml").write_text('[X]\ntitle = "x"\nunits = "um"\n',
                                          encoding="utf-8")
    (tmp_path / "assets.toml").write_text(
        '[toy]\nrole = "glomeruli"\nspace = "X"\npath = "data/toy.npz"\n',
        encoding="utf-8")
    reg = Registry.load(tmp_path, validate=False, data_root=tmp_path / "data")

    class HalfWritten:
        def save(self, path):
            path.write_bytes(b"PK\x03\x04 half a zip")
            raise Interrupted

    monkeypatch.setitem(B._PIPELINES, "half", lambda src, params, **_: HalfWritten())
    recipes = {"toy": B.Recipe(asset="toy", pipeline="half")}
    with pytest.raises(Interrupted):
        B.build_asset(reg, "toy", recipes=recipes)
    assert B.missing(reg) == ["toy"]
    assert _leftovers(tmp_path / "data", set()) == []


def test_a_sidecar_is_installed_with_its_volume(tmp_path):
    """The staged path has the real name, so a sidecar is named for it."""
    target = tmp_path / "v.npz"
    with replacing(target) as scratch:
        _volume(shape=(8, 8, 8)).save(scratch, sidecar=True)
    back = Volume.load(target)
    assert back.meta["data_file"] == "v.data.npy"
    assert (np.asarray(back.data) == 7).all()
    assert _leftovers(tmp_path, {"v.npz", "v.data.npy"}) == []


def test_a_symlinked_target_is_replaced_not_written_through(tmp_path):
    """A data root may link to a shared, read-only copy; never write into it."""
    shared = tmp_path / "shared.npz"
    _meshset().save(shared)
    before = shared.read_bytes()
    link = tmp_path / "root" / "m.npz"
    link.parent.mkdir()
    link.symlink_to(shared)
    _meshset(offset=5.0).save(link)
    assert not link.is_symlink()
    assert shared.read_bytes() == before
    assert MeshSet.load(link).vertices[0, 0] == 5.0
