"""`lobemap check` on the shipped data: it passes, and each mistake fails it.

Every mutation here is made in memory, on a freshly loaded registry, and
each is one the checks at 2e3ae7a passed: a whole space reflected
left-right, a stain flipped on its own, one glomerulus collapsed. Each
test declares the assets it needs with `requires_data`.
"""

from __future__ import annotations

import numpy as np
import pytest

from lobemap.core.imagefmt import Volume, as_lazy
from lobemap.core.registry import Registry
from lobemap.validate import harness as H

SPACE_ASSETS = {
    "FAFB14": ("benton2025_glomeruli", "fafb_neuropil", "fafb_stain"),
    "JRCFIB2018F": ("neuprint_hemibrain_glomeruli", "neuprint_hemibrain_neuropil",
                    "schlegel2021_s11_glomeruli", "schlegel2021_s12_glomeruli",
                    "hemibrain_stain"),
    "JRCFIB2022M": ("neuprint_cns_glomeruli", "neuprint_cns_neuropil", "malecns_stain"),
    "GRABE": ("grabe2015_glomeruli", "grabe2015_labels", "grabe2015_stack"),
}


def needs(space: str):
    return pytest.mark.requires_data(*SPACE_ASSETS[space])


def spaces(*ids: str):
    return [pytest.param(s, marks=needs(s)) for s in ids]


@pytest.fixture
def fresh(registry_root):
    """A registry of its own: the tests below mutate what it holds."""
    return Registry.load(registry_root)


def _flip_volume(reg: Registry, asset_id: str, axis: int) -> None:
    """np.flip along one axis, lazily for a chunked store."""
    import dask.array as da

    v = reg.volume(asset_id)
    data = v.data
    flipped = np.flip(data, axis) if isinstance(data, np.ndarray) else da.flip(as_lazy(data), axis)
    reg._volumes[asset_id] = Volume(flipped, v.voxel_um, v.origin_um, dict(v.meta))


def _flip_space(reg: Registry, space_id: str) -> None:
    """Reflect every mesh and image of a space through one plane."""
    axis = H.lateral_axis(reg.spaces[space_id])
    image = next(a for a in reg.assets_in_space(space_id) if a.kind == "image")
    v = reg.volume(image.id)
    plane = v.origin_um[axis] + (v.shape[axis] - 1) * v.voxel_um[axis] / 2
    for asset in reg.assets_in_space(space_id):
        if asset.kind == "meshset":
            ms = reg.mesh(asset.id)
            verts = ms.vertices.astype(float)
            verts[:, axis] = 2 * plane - verts[:, axis]
            reg._meshes[asset.id] = ms.transformed(verts)
        else:
            _flip_volume(reg, asset.id, axis)


def _failed(checks) -> set[str]:
    return {c.name for c in checks if not c.passed}


@needs("JRCFIB2018F")
def test_compare_pairs_the_hemibrain_rename_chain_by_canonical_name(fresh):
    """hemibrain VC5(R) is VM6: it pairs with S12's VM6, never with S12's VC5."""
    pairs, chk = H.compare_atlases(
        fresh, "neuprint_hemibrain", "schlegel2021_s12", "JRCFIB2018F"
    )
    by_a = {p.a_name: p for p in pairs}
    assert by_a["VC5(R)"].b_name == "VM6"
    assert by_a["VC3l(R)"].b_name == "VC3"
    assert by_a["VC3m(R)"].b_name == "VC5"
    assert all(p.distance_um < 10.0 for p in pairs if p.a_name in ("VC3l(R)", "VC3m(R)", "VC5(R)"))
    assert "0 only in schlegel2021_s12" in chk.detail


@pytest.mark.parametrize("space", spaces(*sorted(SPACE_ASSETS)))
def test_the_shipped_data_passes(fresh, space):
    checks = H.run_checks(fresh, spaces=[space])
    assert checks
    assert not _failed(checks), [str(c) for c in checks if not c.passed]
    names = {c.name.split(" ")[0] for c in checks}
    assert "laterality" in names
    if space in ("JRCFIB2018F", "JRCFIB2022M"):
        assert "chirality" in names
    assert "image" in names


@needs("JRCFIB2018F")
def test_hemibrain_vm2_is_listed_as_known(fresh, registry_root):
    checks = H.geometry_checks(fresh, "JRCFIB2018F", H.known_defects(registry_root))
    size = next(c for c in checks if c.name == "compartment size neuprint_hemibrain")
    assert size.passed
    assert [o.split(" ")[0] for o in size.offenders] == ["VM2(R)"]


@pytest.mark.parametrize("space", spaces("JRCFIB2018F", "JRCFIB2022M"))
def test_a_whole_space_flip_fails(fresh, registry_root, space):
    _flip_space(fresh, space)
    failed = _failed(H.geometry_checks(fresh, space, H.known_defects(registry_root)))
    assert {f"laterality {space}", f"chirality {space}"} <= failed, failed


@pytest.mark.parametrize("space,stain", [
    pytest.param("FAFB14", "fafb_stain", marks=needs("FAFB14")),
    pytest.param("JRCFIB2022M", "malecns_stain", marks=needs("JRCFIB2022M")),
])
def test_a_stain_flipped_alone_fails(fresh, space, stain):
    _flip_volume(fresh, stain, H.lateral_axis(fresh.spaces[space]))
    assert f"image orientation {stain}" in _failed(H.image_checks(fresh, space))


@needs("FAFB14")
def test_a_degenerate_compartment_fails(fresh, registry_root):
    reg = fresh
    ms = reg.mesh("benton2025_glomeruli")
    i = ms.names.index("DA1")
    verts = ms.vertices.astype(float)
    part = slice(int(ms.vertex_offsets[i]), int(ms.vertex_offsets[i + 1]))
    center = verts[part].mean(axis=0)
    verts[part] = center + 0.1 * (verts[part] - center)
    reg._meshes["benton2025_glomeruli"] = ms.transformed(verts)
    checks = H.geometry_checks(reg, "FAFB14", H.known_defects(registry_root))
    assert _failed(checks) == {"compartment size benton2025"}
