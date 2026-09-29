"""A stain build must clean up after itself.

The disk-backed builder spills its points and a float32 grid to a work
directory: 10-25 GB per whole-brain stain. `lobemap build <stain>` left both
files behind every time, in `.stainwork` under the data root.

These run the real `virtual_stain` pipeline on a small grid, forced down the
disk-backed path, with the synapse download replaced by generated points.
"""

from __future__ import annotations

import numpy as np
import pytest

from lobemap import build as B
from lobemap.core import zarrfmt
from lobemap.core.registry import Registry
from lobemap.ingest import stain_slabs, synapse_buckets, virtual_stain


class Interrupted(Exception):
    pass


@pytest.fixture
def stain_registry(tmp_path, monkeypatch):
    root = tmp_path / "registry"
    (root / "sources").mkdir(parents=True)
    (root / "sources" / "points.bin").write_bytes(b"stand-in for a bulk release")
    (root / "assets.toml").write_text(
        '[toy_stain]\nrole = "virtual_stain"\nspace = "TOY"\nkind = "image"\n'
        'path = "data/toy_stain.zarr"\n', encoding="utf-8")

    def presynapses(src, progress=None):
        rng = np.random.default_rng(0)
        for _ in range(3):
            yield rng.uniform(0, 1, size=(2000, 3)) * [150, 40, 40]

    monkeypatch.setattr(synapse_buckets, "hemibrain_presynapses", presynapses)
    monkeypatch.setattr(virtual_stain, "SLABWISE_THRESHOLD_VOXELS", 1000)
    monkeypatch.setattr(stain_slabs, "SLAB_BUDGET_BYTES", 200_000)
    return Registry.load(root, validate=False, data_root=tmp_path / "data")


def _recipes(**params):
    base = {"bucket": "hemibrain", "space": "TOY", "voxel": 1.0, "sigma": 1.0,
            "bounds": [0, 0, 0, 150, 40, 40], "confidence": False}
    return {"toy_stain": B.Recipe(asset="toy_stain", pipeline="virtual_stain",
                                  source="sources/points.bin",
                                  params={**base, **params})}


def _everything_under(folder):
    return sorted(p.relative_to(folder).as_posix() for p in folder.rglob("*"))


def test_a_stain_build_leaves_only_the_store(stain_registry):
    reg = stain_registry
    result = B.build_asset(reg, "toy_stain", recipes=_recipes())
    target = reg.assets["toy_stain"].path
    assert result.path == target
    outside = [p for p in _everything_under(reg.data_root)
               if not p.startswith(target.name)]
    assert outside == [], f"scratch left behind: {outside}"
    assert reg.volume("toy_stain").shape == (160, 50, 50)


def test_an_interrupted_stain_build_leaves_nothing(stain_registry, monkeypatch):
    reg = stain_registry
    monkeypatch.setattr(zarrfmt, "downsample",
                        lambda *a, **k: (_ for _ in ()).throw(Interrupted()))
    with pytest.raises(Interrupted):
        B.build_asset(reg, "toy_stain", recipes=_recipes())
    assert B.missing(reg) == ["toy_stain"]
    assert _everything_under(reg.data_root) == []


def test_a_recipe_workdir_replaces_the_default_and_is_emptied_but_kept(stain_registry, tmp_path):
    scratch = tmp_path / "big-disk"
    scratch.mkdir()
    B.build_asset(stain_registry, "toy_stain", recipes=_recipes(workdir=str(scratch)))
    assert scratch.is_dir()
    assert _everything_under(scratch) == []
    assert not (stain_registry.data_root / B.WORK_DIR).exists()
