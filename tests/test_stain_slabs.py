"""The disk-backed stain must equal the in-RAM one, not merely resemble it.

The halo is the whole risk: too small and every slab seam is darkened by the
Gaussian running off the edge of its block, which looks like faint banding
rather than an error. So these tests force many slabs over a small grid and
compare against the whole-array result.
"""

from __future__ import annotations

import numpy as np
import pytest

from lobemap.core.imagefmt import Volume
from lobemap.ingest import stain_slabs as ss
from lobemap.ingest.virtual_stain import build_stain, build_stain_slabwise


def _points(n=20_000, seed=0):
    rng = np.random.default_rng(seed)
    # Three blobs, so there is real structure across slab seams.
    centers = np.array([[6.0, 5.0, 4.0], [14.0, 9.0, 6.0], [20.0, 4.0, 8.0]])
    pts = np.vstack([c + rng.normal(0, 1.5, (n // 3, 3)) for c in centers])
    return pts


LO, HI = np.array([0.0, 0.0, 0.0]), np.array([26.0, 14.0, 12.0])


def _build(tmp_path, voxel, sigma, budget, dtype=np.uint16):
    pts = _points()
    ref, ref_stats = build_stain(
        iter([pts.copy()]), LO, HI, space="TEST", source="test",
        voxel_um=voxel, sigma_um=sigma, dtype=dtype,
    )
    old = ss.SLAB_BUDGET_BYTES
    ss.SLAB_BUDGET_BYTES = budget
    try:
        got, got_stats = build_stain_slabwise(
            iter([pts.copy()]), LO, HI, space="TEST", source="test",
            workdir=tmp_path / "work", voxel_um=voxel, sigma_um=sigma,
            dtype=dtype,
        )
    finally:
        ss.SLAB_BUDGET_BYTES = old
    return ref, ref_stats, got, got_stats


#: Chosen against the test grid so each gives a DIFFERENT slab width --
#: 5 slabs, 3, 2, then 1. Budgets that all clamp to the 2*halo floor would
#: run the same layout three times and look like thorough coverage.
BUDGETS = [40_000, 6_100_000, 9_800_000, 12_000_000]


def test_budgets_give_distinct_layouts():
    halo = ss.blur_radius_vox(0.9, 0.25) + 1
    shape = (144, 96, 88)
    widths = [ss.slab_width(shape, halo, b) for b in BUDGETS]
    assert len(set(widths)) == len(widths), widths
    assert min(widths) >= 2 * halo


@pytest.mark.parametrize("budget", BUDGETS)
def test_slabwise_matches_whole_array(tmp_path, budget):
    ref, _, got, _ = _build(tmp_path, voxel=0.25, sigma=0.9, budget=budget)
    assert got.shape == ref.shape
    assert np.allclose(got.origin_um, ref.origin_um)
    # uint16 quantisation of the same float32 density: equal, or one count off.
    diff = np.abs(got.data.astype(np.int32) - ref.data.astype(np.int32))
    assert diff.max() <= 1, f"max deviation {diff.max()} at budget {budget}"


def test_slab_count_actually_varies(tmp_path):
    """Guard the guard: a budget so large it makes one slab proves nothing."""
    _, _, _, many = _build(tmp_path / "a", 0.25, 0.9, BUDGETS[0])
    _, _, _, one = _build(tmp_path / "b", 0.25, 0.9, BUDGETS[-1])
    assert "slabwise" in many.notes[0] and "slabwise" in one.notes[0]
    assert many.notes[0] != one.notes[0], many.notes[0]
    assert many.notes[0].startswith("slabwise: 5 slabs")
    assert one.notes[0].startswith("slabwise: 1 slabs")


def test_stats_and_peak_agree(tmp_path):
    ref, ref_stats, got, got_stats = _build(tmp_path, 0.25, 0.9, BUDGETS[0])
    assert got_stats.n_points == ref_stats.n_points
    assert got_stats.n_outside == ref_stats.n_outside
    a = ref.meta["derivation"]["params"]["peak_density"]
    b = got.meta["derivation"]["params"]["peak_density"]
    assert b == pytest.approx(a, rel=1e-5)


def test_halo_covers_the_kernel():
    # scipy's own rule; if this drifts, seams appear rather than an error.
    assert ss.blur_radius_vox(0.9, 0.25) == 14
    assert ss.blur_radius_vox(0.9, 0.5) == 7
    # Slabs must never be narrower than the halo, or read(s-1, s+2) underruns.
    for shape in [(100, 50, 50), (4000, 1578, 1102), (10, 4, 4)]:
        halo = ss.blur_radius_vox(0.9, 0.25) + 1
        assert ss.slab_width(shape, halo) >= min(shape[0], 2 * halo)


def test_large_volume_round_trips_through_a_sidecar(tmp_path):
    data = np.arange(2 * 3 * 4, dtype=np.uint16).reshape(2, 3, 4)
    vol = Volume(data=data, voxel_um=(0.25,) * 3, origin_um=(1.0, 2.0, 3.0))
    path = vol.save(tmp_path / "v.npz", sidecar=True)
    assert (tmp_path / "v.data.npy").exists()
    back = Volume.load(path)
    assert np.array_equal(back.data, data)
    assert back.meta["data_file"] == "v.data.npy"
    # The hash must not depend on how the array was stored.
    assert back.content_hash() == vol.content_hash()
    inline = Volume(data=data, voxel_um=(0.25,) * 3, origin_um=(1.0, 2.0, 3.0))
    inline.save(tmp_path / "w.npz", sidecar=False)
    assert Volume.load(tmp_path / "w.npz").content_hash() == vol.content_hash()


def test_missing_sidecar_is_named(tmp_path):
    vol = Volume(data=np.zeros((2, 2, 2), np.uint16), voxel_um=(1.0,) * 3)
    path = vol.save(tmp_path / "v.npz", sidecar=True)
    (tmp_path / "v.data.npy").unlink()
    with pytest.raises(FileNotFoundError, match="v.data.npy"):
        Volume.load(path)


@pytest.mark.parametrize("dtype", [np.uint8, np.uint16])
def test_slabwise_matches_whole_array_per_dtype(tmp_path, dtype):
    ref, _, got, _ = _build(tmp_path, 0.25, 0.9, BUDGETS[0], dtype=dtype)
    assert got.data.dtype == dtype == ref.data.dtype
    diff = np.abs(got.data.astype(np.int32) - ref.data.astype(np.int32))
    assert diff.max() <= 1


def test_uint8_is_the_default_and_is_recorded(tmp_path):
    vol, _ = build_stain(iter([_points()]), LO, HI, space="TEST",
                         source="test", voxel_um=1.0, sigma_um=0.9)
    assert vol.data.dtype == np.uint8
    params = vol.meta["derivation"]["params"]
    assert params["dtype"] == "uint8"
    # The scale must match the type, or recorded density is wrong by 257x.
    assert params["intensity_scale"] * params["peak_density"] == pytest.approx(255.0)


def test_uint8_preserves_the_contrast_that_matters(tmp_path):
    """8-bit must not flatten the inside/outside ratio the validators check.

    The fixture needs a diffuse component. With bare blobs the "background"
    is nothing but the Gaussian's own skirt -- precisely what 8-bit rounds
    away -- and the ratio then rises about 4%, which says more about the
    fixture than about the format. Real neuropil is everywhere-dense: the
    built stains are 30-40% non-zero with a median at 16% of peak.
    """
    rng = np.random.default_rng(7)
    diffuse = rng.uniform(LO, HI, (60_000, 3))
    pts = np.vstack([_points(), diffuse])
    lo8, _ = build_stain(iter([pts.copy()]), LO, HI, space="T", source="t",
                         voxel_um=0.5, sigma_um=0.9, dtype=np.uint8)
    hi16, _ = build_stain(iter([pts.copy()]), LO, HI, space="T", source="t",
                          voxel_um=0.5, sigma_um=0.9, dtype=np.uint16)
    a = np.asarray(lo8.data, float)
    b = np.asarray(hi16.data, float)
    bright = b > np.percentile(b, 99)
    r8 = a[bright].mean() / max(a[~bright].mean(), 1e-9)
    r16 = b[bright].mean() / max(b[~bright].mean(), 1e-9)
    # 3%: a background at ~1/16 of peak keeps only ~16 of the 256 levels, so
    # a couple of percent is what quantisation costs, not a defect. The
    # authoritative figure is the measured inside/outside on the real stains.
    assert r8 == pytest.approx(r16, rel=0.03), (r8, r16)
