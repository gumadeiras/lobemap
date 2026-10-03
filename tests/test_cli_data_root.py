"""`--data-root` is where every command reads and writes asset files.

`LOBEMAP_DATA` always worked, because the registry reads it; `--data-root`
reached only the commands that passed it on. `manifest` crashed, `spaces`,
`nomenclature` and `repair` read the default root instead, and `stain` and
`ingest neuprint` wrote into `<registry>/data` whatever was asked.

Each test here keeps the files in a data root outside the registry and
leaves `<registry>/data` present but empty, so a command that falls back
to the default finds nothing there.
"""

from __future__ import annotations

import numpy as np
import pytest

from lobemap.cli import main
from lobemap.core.meshfmt import MeshSet
from lobemap.core.names import Nomenclature


def _meshset() -> MeshSet:
    v = np.array([[0, 0, 0], [1, 0, 0], [0, 1, 0], [0, 0, 1]], dtype=np.float64)
    f = np.array([[0, 1, 2], [0, 1, 3], [0, 2, 3], [1, 2, 3]])
    parts = [(f"G{i}(R)", v + (i * 10.0, 0, 0), f) for i in range(3)]
    return MeshSet.from_parts(parts, meta={"units": "um"})


@pytest.fixture
def split(tmp_path, monkeypatch):
    """A registry whose one atlas mesh is in a separate data root."""
    monkeypatch.delenv("LOBEMAP_DATA", raising=False)
    reg = tmp_path / "registry"
    (reg / "atlases").mkdir(parents=True)
    (reg / "data").mkdir()
    (reg / "spaces.toml").write_text('[S1]\ntitle = "S"\nunits = "um"\n')
    (reg / "assets.toml").write_text(
        '[a1_mesh]\nrole = "glomeruli"\nspace = "S1"\n'
        'kind = "meshset"\npath = "data/a1.npz"\n'
    )
    (reg / "atlases" / "a1.toml").write_text(
        'id = "a1"\ntitle = "A1"\nnative_space = "S1"\nasset = "a1_mesh"\n'
    )
    ms = _meshset()
    nom = Nomenclature()
    nom.add_missing("a1", list(ms.names))
    nom.save(reg / "nomenclature.csv")
    data = tmp_path / "elsewhere"
    ms.save(data / "a1.npz")
    return reg, data


def _run(split, *argv):
    reg, data = split
    return main(["--registry", str(reg), "--data-root", str(data), *argv])


def _untouched(reg) -> None:
    assert not any((reg / "data").iterdir()), "wrote into <registry>/data"


def test_manifest_describes_the_data_root(split):
    reg, _ = split
    assert _run(split, "manifest") == 0
    text = (reg / "manifest.toml").read_text()
    assert '[artifacts.a1_mesh]\npath = "a1.npz"' in text


def test_spaces_counts_what_is_in_the_data_root(split, capsys):
    assert _run(split, "spaces") == 0
    assert "1/1 assets built" in capsys.readouterr().out


def test_nomenclature_audits_the_data_root(split, capsys):
    assert _run(split, "nomenclature") == 0
    out = capsys.readouterr().out
    assert "a1                     3 compartments" in out
    assert "not built" not in out


def test_repair_reads_the_data_root(split, capsys):
    assert _run(split, "repair", "--dry-run") == 0
    assert capsys.readouterr().out.startswith("a1_mesh: ")


def test_stain_writes_into_the_data_root(split, tmp_path):
    """A FAFB bulk table of a few points, binned into a tiny grid."""
    pytest.importorskip("pyarrow")
    pytest.importorskip("flybrains")
    reg, data = split
    table = tmp_path / "synapses.csv"
    # The reader works out the units from the extent, so the points span
    # the FAFB14 brain in nanometers; two of them land in the grid.
    table.write_text("pre_x,pre_y,pre_z\n0,0,0\n1000,1000,1000\n2000,1500,1000\n"
                     "661486,322979,269198\n")
    assert _run(split, "stain", "--space", "S1", "--asset-id", "tiny_stain",
                "--bucket", "fafb", "--path", str(table),
                "--bounds", "0", "0", "0", "4", "4", "4", "--voxel", "1") == 0
    assert (data / "tiny_stain.npz").exists()
    assert (data / "tiny_stain.progress.log").exists()
    _untouched(reg)


def test_stain_removes_only_its_own_scratch(split, tmp_path):
    """`--workdir` may name a directory with other files in it; they stay."""
    pytest.importorskip("pyarrow")
    pytest.importorskip("flybrains")
    from lobemap.core.imagefmt import Volume

    reg, data = split
    table = tmp_path / "synapses.csv"
    table.write_text("pre_x,pre_y,pre_z\n1000,1000,1000\n2000,1500,1000\n"
                     "661486,322979,269198\n")
    work = tmp_path / "work"
    work.mkdir()
    (work / "keep.txt").write_text("not scratch")
    assert _run(split, "stain", "--space", "S1", "--asset-id", "tiny_stain",
                "--bucket", "fafb", "--path", str(table), "--workdir", str(work),
                "--bounds", "0", "0", "0", "4", "4", "4", "--voxel", "1") == 0
    assert sorted(p.name for p in work.iterdir()) == ["keep.txt"]
    # The Princeton FAFB table has no score column, so no filter was applied.
    meta = Volume.load(data / "tiny_stain.npz").meta
    assert meta.get("confidence_threshold") is None, meta


def test_ingest_neuprint_writes_into_the_data_root(split, monkeypatch):
    """neuPrint itself is replaced: this is about where the result goes."""
    from lobemap.ingest import neuprint_rois

    def fake_ingest(**_):
        return neuprint_rois.IngestResult(
            meshset=_meshset(), skipped=[], scale_to_um=1.0, source_units="um")

    monkeypatch.setattr(neuprint_rois, "ingest", fake_ingest)
    reg, data = split
    assert _run(split, "ingest", "neuprint", "--asset-id", "n1", "--token", "t",
                "--no-repair") == 0
    assert (data / "n1.npz").exists()
    _untouched(reg)
