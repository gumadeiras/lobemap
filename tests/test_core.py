"""Offline tests for the core model, mesh container, names and registry.

Nothing here touches the network or needs navis/flybrains. Fixtures are two or
three compartments, not whole atlases.
"""

from __future__ import annotations

import numpy as np
import pytest

from lobemap.core.meshfmt import MeshSet
from lobemap.core.names import Nomenclature, normalize, parse_roi
from lobemap.core.registry import Registry, RegistryError


def tetra(offset=(0.0, 0.0, 0.0)):
    v = np.array(
        [[0, 0, 0], [1, 0, 0], [0, 1, 0], [0, 0, 1]], dtype=np.float64
    ) + np.asarray(offset)
    f = np.array([[0, 1, 2], [0, 1, 3], [0, 2, 3], [1, 2, 3]])
    return v, f


def sample_meshset(n=3):
    parts = []
    for i in range(n):
        v, f = tetra((i * 10.0, 0, 0))
        parts.append((f"AL-G{i}(R)", v, f))
    return MeshSet.from_parts(parts, meta={"units": "um"})


# -- MeshSet ------------------------------------------------------------


def test_offsets_and_slicing():
    ms = sample_meshset()
    assert ms.n_compartments == 3
    assert len(ms.vertices) == 12
    assert len(ms.faces) == 12
    for i in range(3):
        v, f = ms.compartment(i)
        assert len(v) == 4 and len(f) == 4
        # Faces must be re-based to local indices.
        assert f.min() == 0 and f.max() == 3
        assert np.allclose(v[:, 0].min(), i * 10.0)


def test_select_values_are_exact_compartment_indices():
    """Every triangle's vertices share one value, so picking is unambiguous."""
    ms = sample_meshset()
    v, f, vals = ms.select([0, 2])
    assert set(np.unique(vals)) == {0.0, 2.0}
    for tri in f:
        assert len(set(vals[tri])) == 1, "a triangle spans two compartments"
    assert f.max() < len(v)


def test_select_empty():
    ms = sample_meshset()
    v, f, vals = ms.select([])
    assert len(v) == len(f) == len(vals) == 0


def test_roundtrip(tmp_path):
    ms = sample_meshset()
    p = ms.save(tmp_path / "x.npz")
    back = MeshSet.load(p)
    assert back.names == ms.names
    assert np.array_equal(back.vertices, ms.vertices)
    assert np.array_equal(back.faces, ms.faces)
    assert back.content_hash() == ms.content_hash()
    assert back.meta["content_hash"] == ms.content_hash()


def test_content_hash_changes_with_geometry():
    a = sample_meshset()
    b = a.transformed(a.vertices + 1.0)
    assert a.content_hash() != b.content_hash()
    assert b.names == a.names
    assert np.array_equal(b.faces, a.faces)


def test_bad_offsets_rejected():
    ms = sample_meshset()
    with pytest.raises(ValueError):
        MeshSet(ms.vertices, ms.faces, ms.vertex_offsets[:-1],
                ms.face_offsets, ms.names, {})


def test_out_of_range_faces_rejected():
    v, f = tetra()
    with pytest.raises(ValueError, match="out of range"):
        MeshSet.from_parts([("bad", v, f + 10)])


def test_transformed_shape_guard():
    ms = sample_meshset()
    with pytest.raises(ValueError):
        ms.transformed(ms.vertices[:-1])


# -- names --------------------------------------------------------------


@pytest.mark.parametrize(
    "roi,expect",
    [
        ("AL-DA1(R)", ("DA1", "R")),
        ("AL-DC3", ("DC3", None)),          # hemibrain's side-less ROI
        ("AL_L", ("AL", "L")),              # flywire-fafb underscore naming
        ("AL(L)", ("AL", "L")),
        ("AL-VM7d(L)", ("VM7d", "L")),
    ],
)
def test_parse_roi(roi, expect):
    assert parse_roi(roi) == expect


def test_normalize():
    assert normalize("VA1v") == normalize("va1v") == "VA1V"
    assert normalize("DL2 d") == normalize("DL2_d") == "DL2D"


def test_add_missing_and_resolve():
    n = Nomenclature()
    added = n.add_missing("a1", ["AL-DA1(R)", "AL-DA1(L)", "AL-VA1v(R)"])
    # add_missing keys on the PUBLISHED name, so both sides get a row; the
    # canonical set still gains DA1 only once.
    assert added == ["AL-DA1(R)", "AL-DA1(L)", "AL-VA1v(R)"]
    assert sorted(n.canonical) == ["DA1", "VA1v"]
    c = n.resolve("a1", "AL-DA1(L)")
    assert c is not None and c.canonical == ("DA1",)


def test_cross_check_reports_both_directions():
    n = Nomenclature()
    n.add_missing("a1", ["AL-DA1(R)", "AL-VA1v(R)"])
    out = n.cross_check(["DA1", "DM6"])
    assert out["only_here"] == ["VA1v"]
    assert out["only_reference"] == ["DM6"]


def test_nomenclature_roundtrip(tmp_path):
    n = Nomenclature()
    n.add_missing("a1", ["AL-DA1(R)"])
    p = n.save(tmp_path / "nom.csv")
    back = Nomenclature.load(p)
    assert back.resolve("a1", "AL-DA1(R)").canonical == ("DA1",)


# -- registry -----------------------------------------------------------


@pytest.fixture(autouse=True)
def _ignore_ambient_data_root(monkeypatch):
    """Keep a developer's own LOBEMAP_DATA out of the tmp registries below.

    `default_data_root` honours LOBEMAP_DATA before it looks for a local
    `data/`, which is right for a real checkout and wrong for a registry
    built in tmp_path: the override wins, the fixture meshes are not found,
    and the atlas derives zero compartments. The failure then reports a
    compartment count and says nothing about the environment, and does not
    reproduce for anyone who has not set the variable.

    Scoped to this module rather than a global conftest on purpose. Other
    tests read the real registry, and pointing that at data kept outside the
    checkout is exactly what the variable is for -- clearing it everywhere
    broke seven of them.
    """
    monkeypatch.delenv("LOBEMAP_DATA", raising=False)
    monkeypatch.delenv("LOBEMAP_REGISTRY", raising=False)


def write_registry(tmp_path, *, space="S1", asset_space="S1", with_mesh=True):
    (tmp_path / "atlases").mkdir(parents=True, exist_ok=True)
    (tmp_path / "spaces.toml").write_text(
        f'[{space}]\ntitle = "S"\nunits = "um"\nflybrains_template = "FAFB14"\n'
    )
    (tmp_path / "assets.toml").write_text(
        f'[a1_mesh]\nrole = "glomeruli"\nspace = "{asset_space}"\n'
        'kind = "meshset"\npath = "data/a1.npz"\n'
    )
    (tmp_path / "atlases" / "a1.toml").write_text(
        f'id = "a1"\ntitle = "A1"\nnative_space = "{space}"\nasset = "a1_mesh"\n'
    )
    if with_mesh:
        sample_meshset().save(tmp_path / "data" / "a1.npz")
    return tmp_path


def test_registry_loads_and_derives_compartments(tmp_path):
    root = write_registry(tmp_path)
    reg = Registry.load(root)
    assert set(reg.spaces) == {"S1"}
    atlas = reg.atlases["a1"]
    assert len(atlas.compartments) == 3
    # published_name comes from the mesh container, not from TOML
    assert atlas.compartments[0].published_name == "AL-G0(R)"
    assert atlas.compartments[0].side == "R"
    assert reg.atlases_in_space("S1") == [atlas]


def test_registry_rejects_unknown_space(tmp_path):
    root = write_registry(tmp_path, asset_space="NOPE")
    with pytest.raises(RegistryError, match="unknown space"):
        Registry.load(root)


def test_registry_rejects_space_mismatch(tmp_path):
    root = write_registry(tmp_path)
    (root / "spaces.toml").write_text(
        '[S1]\nunits = "um"\n[S2]\nunits = "um"\n'
    )
    (root / "atlases" / "a1.toml").write_text(
        'id = "a1"\nnative_space = "S2"\nasset = "a1_mesh"\n'
    )
    with pytest.raises(RegistryError, match="is in space"):
        Registry.load(root)


def test_registry_rejects_unknown_parent(tmp_path):
    root = write_registry(tmp_path)
    (root / "atlases" / "a1.toml").write_text(
        'id = "a1"\nnative_space = "S1"\nasset = "a1_mesh"\nparent = "ghost"\n'
    )
    with pytest.raises(RegistryError, match="unknown parent"):
        Registry.load(root)


def test_missing_mesh_is_a_warning_not_an_error(tmp_path):
    root = write_registry(tmp_path, with_mesh=False)
    reg = Registry.load(root)
    warnings = reg.validate()
    assert any("missing file" in w for w in warnings)
    assert reg.atlases["a1"].compartments == ()


def test_island_detection(tmp_path):
    root = write_registry(tmp_path)
    (root / "spaces.toml").write_text(
        '[S1]\nunits = "um"\nflybrains_template = "FAFB14"\n'
        '[GRABE]\nunits = "um"\n'
    )
    reg = Registry.load(root)
    assert reg.spaces["GRABE"].is_island
    assert not reg.spaces["S1"].is_island
