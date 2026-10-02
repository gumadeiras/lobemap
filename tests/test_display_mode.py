"""What napari is handed for 2D and for 3D.

Both defaults here are actively wrong for a whole-brain volume, and both fail
silently -- one renders a blurry blob, the other takes five seconds a slice.
Neither raises, so only a test keeps them fixed.
"""

from __future__ import annotations

import numpy as np
import pytest

from lobemap.core.imagefmt import Volume, as_lazy
from lobemap.viewer.app import (
    VIEW3D_MAX_AXIS,
    VIEW3D_MAX_VOXELS,
    level_for_3d,
)


class _FakeLevel:
    def __init__(self, shape):
        self.shape = shape


def test_3d_level_is_the_finest_that_fits_a_texture():
    # The real FAFB pyramid. Level 0 is 4 G voxels and 2686 wide; napari's own
    # choice would be the last entry, at 0.1 M voxels.
    levels = [_FakeLevel(s) for s in [
        (2686, 1332, 1118), (1343, 666, 559), (671, 333, 279),
        (335, 166, 139), (167, 83, 69), (83, 41, 34)]]
    assert level_for_3d(levels) == 1
    chosen = levels[1].shape
    assert np.prod(chosen) <= VIEW3D_MAX_VOXELS
    assert max(chosen) <= VIEW3D_MAX_AXIS
    assert level_for_3d(levels) != len(levels) - 1, "that is napari's bad default"


def test_3d_level_respects_the_texture_axis_limit_not_just_volume():
    """A long thin volume can be under the voxel budget and still untextur-able."""
    levels = [_FakeLevel((4000, 100, 100)), _FakeLevel((2000, 50, 50))]
    assert np.prod(levels[0].shape) < VIEW3D_MAX_VOXELS   # fits by volume
    assert level_for_3d(levels) == 1                      # but not by axis


def test_3d_level_falls_back_to_coarsest_when_nothing_fits():
    levels = [_FakeLevel((9000, 9000, 9000)), _FakeLevel((5000, 5000, 5000))]
    assert level_for_3d(levels) == 1


def test_small_volume_uses_full_resolution_in_3d():
    levels = [_FakeLevel((256, 256, 256)), _FakeLevel((128, 128, 128))]
    assert level_for_3d(levels) == 0


def test_napari_data_is_lazy_for_a_chunked_store(tmp_path):
    """Eager arrays make napari read a whole level per slider step."""
    da = pytest.importorskip("dask.array")
    rng = np.random.default_rng(0)
    data = rng.integers(0, 255, (140, 96, 80)).astype(np.uint8)
    v = Volume(data=data, voxel_um=(0.25,) * 3)
    got = Volume.load(v.save(tmp_path / "v.zarr")).napari_data()
    assert isinstance(got, list) and len(got) > 1
    assert all(isinstance(a, da.Array) for a in got)
    assert np.array_equal(np.asarray(got[0]), data)


def test_lazy_slicing_does_not_read_the_whole_level(tmp_path):
    """The exact expression napari uses: only the displayed axes are bounded."""
    da = pytest.importorskip("dask.array")
    rng = np.random.default_rng(1)
    # Big enough on one axis to earn a pyramid, so napari_data gives a list.
    data = rng.integers(0, 255, (200, 40, 30)).astype(np.uint8)
    v = Volume(data=data, voxel_um=(1.0,) * 3)
    got = Volume.load(v.save(tmp_path / "v.zarr"))
    assert got.is_multiscale
    level0 = got.napari_data()[0]
    # slice(None) on the slider axis -- eager arrays materialise everything here
    view = level0[(slice(None), slice(0, 40), slice(0, 30))]
    assert isinstance(view, da.Array), "must stay lazy"
    assert np.array_equal(np.asarray(view[17]), data[17])


def test_as_lazy_passes_numpy_through_unchanged():
    arr = np.zeros((4, 4, 4), np.uint8)
    assert as_lazy(arr) is arr


