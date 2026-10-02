"""Source units are declared, and the declaration is checked.

The point of `core.units` is that no ingest decides its scale factor by
measuring the result. These tests pin the conversions, and pin that a
wrong declaration is refused loudly rather than absorbed.
"""

from __future__ import annotations

import numpy as np
import pytest

from lobemap.core.units import (
    scale_to_um,
    verify_extent,
    voxel_units_name,
)


@pytest.mark.parametrize(
    ("declared", "expect"),
    [
        ("um", 1.0),
        ("nm", 1e-3),
        ("nanometers", 1e-3),
        ("micrometers", 1.0),
        ("px8nm", 8e-3),
        ("px4nm", 4e-3),
        ("PX8NM", 8e-3),
        (" nm ", 1e-3),
    ],
)
def test_declared_units_convert(declared, expect):
    assert scale_to_um(declared) == pytest.approx(expect)


def test_an_unknown_unit_is_refused():
    with pytest.raises(ValueError, match="unknown source_units"):
        scale_to_um("furlongs")


def test_neuprint_metadata_gives_the_grid_exactly():
    """What both datasets' :Meta node reports, and what it has to mean."""
    assert voxel_units_name([8, 8, 8], "nanometers") == "px8nm"
    assert scale_to_um(voxel_units_name([8, 8, 8], "nanometers")) == 8e-3
    # a scalar is as good as a triple
    assert voxel_units_name(8, "nanometers") == "px8nm"


def test_an_anisotropic_grid_is_refused():
    """One scalar cannot describe it, and taking axis 0 would skew."""
    with pytest.raises(ValueError, match="anisotropic"):
        voxel_units_name([4, 4, 40], "nanometers")


def test_verify_extent_accepts_a_correct_declaration():
    # 8 nm voxels, compartments ~2500 units across -> 20 um
    extents = np.array([2400, 2500, 2600], dtype=float)
    typical = verify_extent(extents, 8e-3, (4.0, 45.0), "px8nm")
    assert typical == pytest.approx(20.0)


def test_verify_extent_rejects_a_wrong_declaration():
    """The same geometry called nm is 1000x too small, and must not pass."""
    extents = np.array([2400, 2500, 2600], dtype=float)
    with pytest.raises(ValueError, match="outside the expected"):
        verify_extent(extents, 1e-3, (4.0, 45.0), "nm")


SHIPPED = (
    "benton2025_glomeruli",
    "neuprint_hemibrain_glomeruli",
    "neuprint_cns_glomeruli",
    "schlegel2021_s11_glomeruli",
    "schlegel2021_s12_glomeruli",
)


@pytest.mark.requires_data(*SHIPPED)
def test_the_shipped_containers_record_a_declared_scale(registry):
    """Every mesh container states the units it was built from."""
    from lobemap.core.meshfmt import MeshSet

    for name in SHIPPED:
        meta = MeshSet.load(registry.assets[name].path).meta
        units = meta.get("source_units")
        assert units, f"{name} records no source units"
        assert meta["scale_to_um"] == pytest.approx(scale_to_um(units)), (
            f"{name}: stored scale {meta['scale_to_um']} does not match its "
            f"own declared units {units!r}"
        )
        assert meta.get("units") == "um"
