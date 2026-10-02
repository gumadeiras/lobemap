"""NGFF geometry and the pyramid reducer.

The failure these guard against is silent: a coarse level offset by half a
voxel, or dimmed by subsampling, looks like bad registration or a bad stain
rather than a storage bug.
"""

from __future__ import annotations

from itertools import pairwise

import numpy as np
import pytest

from lobemap.core import zarrfmt as zf


def test_pyramid_halves_until_small():
    shapes = zf.pyramid_shapes((2818, 1578, 1102))
    assert shapes[0] == (2818, 1578, 1102)
    assert all(max(s) > zf.MIN_LEVEL_EXTENT for s in shapes[:-1])
    assert max(shapes[-1]) <= zf.MIN_LEVEL_EXTENT
    for a, b in pairwise(shapes):
        assert b == tuple(n // 2 for n in a)


def test_pyramid_terminates_on_tiny_and_degenerate_input():
    assert zf.pyramid_shapes((4, 4, 4)) == [(4, 4, 4)]
    assert zf.pyramid_shapes((1, 1, 1)) == [(1, 1, 1)]


def test_thin_axes_stop_halving_while_others_continue():
    """A size-1 axis cannot be halved; a uniform 2^L factor would crash."""
    levels = zf.pyramid_levels((300, 1, 1))
    assert [s for s, _ in levels] == [(300, 1, 1), (150, 1, 1), (75, 1, 1)]
    assert [f for _, f in levels] == [(1, 1, 1), (2, 1, 1), (4, 1, 1)]
    # and the reducer must agree with the shapes the pyramid declares
    src = np.ones((300, 1, 1), np.uint8)
    for (shape, _f), step in zip(levels[1:], [(2, 1, 1), (2, 1, 1)]):
        dst = np.zeros(shape, np.uint8)
        zf.downsample(src, dst, step)
        assert (dst == 1).all()
        src = dst


def test_every_declared_level_is_reachable_by_the_reducer(tmp_path):
    """The shapes and the reducer must never disagree, for any input."""
    for shape in [(2818, 1578, 1102), (513, 514, 119), (300, 1, 1), (9, 300, 2)]:
        levels = zf.pyramid_levels(shape)
        for (a, fa), (b, fb) in pairwise(levels):
            step = tuple(y // x for x, y in zip(fa, fb))
            assert all(s in (1, 2) for s in step)
            assert b == tuple(n // s for n, s in zip(a, step))


def test_level_transform_keeps_voxel_centers_aligned():
    voxel, origin = (0.25, 0.25, 0.25), (10.0, 20.0, 30.0)
    for level in range(5):
        span = 2 ** level
        scale, translation = zf.level_transform((span,) * 3, voxel, origin)
        assert scale == pytest.approx([0.25 * span] * 3)
        # Level L voxel 0 spans original voxels 0..2^L-1, so its center sits
        # at the midpoint of that span -- not at the origin.
        assert translation[0] == pytest.approx(10.0 + 0.25 * (span - 1) / 2)
    assert zf.level_transform((1, 1, 1), voxel, origin)[1] == pytest.approx(list(origin))


def test_level_transform_handles_anisotropic_factors():
    scale, translation = zf.level_transform((4, 4, 1), (0.2, 0.2, 1.0),
                                            (0.0, 0.0, 5.0))
    assert scale == pytest.approx([0.8, 0.8, 1.0])
    # The un-halved axis must not be shifted at all.
    assert translation == pytest.approx([0.3, 0.3, 5.0])


def test_metadata_is_ngff_shaped():
    levels = zf.pyramid_levels((256, 256, 256))
    m = zf.multiscale_metadata(levels, (0.5,) * 3, (0.0,) * 3, "stain")
    shapes = levels
    assert m["version"] == "0.4"
    assert [a["name"] for a in m["axes"]] == ["x", "y", "z"]
    assert all(a["type"] == "space" for a in m["axes"])
    assert all(a["unit"] == "micrometer" for a in m["axes"])
    assert len(m["datasets"]) == len(shapes)
    for i, d in enumerate(m["datasets"]):
        assert d["path"] == str(i)
        kinds = [t["type"] for t in d["coordinateTransformations"]]
        assert kinds == ["scale", "translation"], "NGFF requires this order"


def test_downsample_is_a_mean_not_a_subsample():
    rng = np.random.default_rng(0)
    src = rng.integers(0, 255, (8, 6, 4)).astype(np.uint8)
    dst = np.zeros((4, 3, 2), np.uint8)
    zf.downsample_half(src, dst, block_planes=2)
    for i in range(4):
        for j in range(3):
            for k in range(2):
                block = src[2*i:2*i+2, 2*j:2*j+2, 2*k:2*k+2].astype(float)
                assert dst[i, j, k] == pytest.approx(np.rint(block.mean()), abs=1)
    # A subsample would equal src[::2, ::2, ::2]; a mean generally does not.
    assert not np.array_equal(dst, src[::2, ::2, ::2])


def test_downsample_preserves_mean_intensity():
    """Coarse levels must not be dimmer -- that is what subsampling gets wrong."""
    rng = np.random.default_rng(1)
    src = (rng.gamma(2.0, 20.0, (32, 32, 32)).clip(0, 255)).astype(np.uint8)
    dst = np.zeros((16, 16, 16), np.uint8)
    zf.downsample_half(src, dst)
    assert dst.mean() == pytest.approx(src.mean(), rel=0.02)


def test_downsample_drops_an_odd_trailing_plane():
    src = np.ones((7, 5, 3), np.uint8)
    dst = np.zeros((3, 2, 1), np.uint8)
    zf.downsample_half(src, dst)          # must not raise on the ragged edge
    assert (dst == 1).all()


def test_downsample_step_of_one_passes_an_axis_through():
    src = np.arange(8 * 4 * 2, dtype=np.uint8).reshape(8, 4, 2)
    dst = np.zeros((4, 4, 2), np.uint8)
    zf.downsample(src, dst, (2, 1, 1))
    assert dst[0, 3, 1] == pytest.approx(
        np.rint(src[0:2, 3, 1].astype(float).mean()), abs=1)


def test_downsample_block_size_does_not_change_the_result():
    rng = np.random.default_rng(2)
    src = rng.integers(0, 255, (32, 8, 8)).astype(np.uint8)
    out = []
    for bp in (1, 3, 8, 64):
        dst = np.zeros((16, 4, 4), np.uint8)
        zf.downsample_half(src, dst, block_planes=bp)
        out.append(dst.copy())
    for d in out[1:]:
        assert np.array_equal(d, out[0])


# -- round trip through a real store ------------------------------------


def _volume(shape=(140, 96, 80), seed=0):
    from lobemap.core.imagefmt import Volume

    rng = np.random.default_rng(seed)
    data = rng.gamma(2.0, 20.0, shape).clip(0, 255).astype(np.uint8)
    return Volume(data=data, voxel_um=(0.25, 0.25, 0.5),
                  origin_um=(5.0, -6.0, 7.5),
                  meta={"source": "test", "role": "virtual_stain"})


def test_zarr_round_trip_is_lossless_and_keeps_geometry(tmp_path):
    from lobemap.core.imagefmt import Volume

    v = _volume()
    path = v.save(tmp_path / "v.zarr")
    back = Volume.load(path)
    assert np.array_equal(np.asarray(back.data), v.data)
    assert back.voxel_um == pytest.approx(v.voxel_um)
    assert back.origin_um == pytest.approx(v.origin_um)
    assert back.meta["source"] == "test"
    assert back.is_multiscale and len(back.levels) > 1


def test_geometry_survives_without_our_own_attributes(tmp_path):
    """A store stays correct even if only the NGFF metadata is trusted."""
    import json

    from lobemap.core.imagefmt import Volume

    v = _volume()
    path = v.save(tmp_path / "v.zarr")
    attrs = json.loads((path / ".zattrs").read_text(encoding="utf-8"))
    del attrs["lobemap"]
    (path / ".zattrs").write_text(json.dumps(attrs), encoding="utf-8")
    back = Volume.load(path)
    assert back.voxel_um == pytest.approx(v.voxel_um)
    assert back.origin_um == pytest.approx(v.origin_um)
    assert back.meta == {}


def test_sample_matches_numpy_on_a_zarr_backed_volume(tmp_path):
    """zarr has no fancy indexing; sample() must route through vindex."""
    from lobemap.core.imagefmt import Volume

    v = _volume()
    path = v.save(tmp_path / "v.zarr")
    back = Volume.load(path)
    rng = np.random.default_rng(3)
    pts = rng.uniform(np.array(v.origin_um) - 3,
                      np.array(v.origin_um) + v.extent_um + 3, (4000, 3))
    assert np.array_equal(back.sample(pts), v.sample(pts))


def test_pyramid_levels_are_aligned_in_world_space(tmp_path):
    """Each level must describe the same physical box, to within its voxel."""
    import json

    from lobemap.core.imagefmt import Volume

    v = _volume()
    path = v.save(tmp_path / "v.zarr")
    ds = json.loads((path / ".zattrs").read_text(encoding="utf-8"))
    ds = ds["multiscales"][0]["datasets"]
    back = Volume.load(path)
    lo0 = np.array(v.origin_um) - 0.5 * np.array(v.voxel_um)
    hi0 = lo0 + v.extent_um
    for d, arr in zip(ds, back.levels):
        scale = np.array(d["coordinateTransformations"][0]["scale"])
        trans = np.array(d["coordinateTransformations"][1]["translation"])
        lo = trans - 0.5 * scale
        hi = lo + np.array(arr.shape) * scale
        assert lo == pytest.approx(lo0, abs=1e-9)
        assert hi == pytest.approx(hi0, abs=np.max(scale))


def test_napari_data_is_the_pyramid_only_when_multiscale(tmp_path):
    from lobemap.core.imagefmt import Volume

    big = _volume().save(tmp_path / "big.zarr")
    assert isinstance(Volume.load(big).napari_data(), list)
    small = _volume(shape=(8, 8, 8)).save(tmp_path / "small.zarr")
    got = Volume.load(small)
    assert not got.is_multiscale
    assert not isinstance(got.napari_data(), list)


def test_npz_storage_keys_do_not_leak_into_a_zarr_store(tmp_path):
    """`data_file` names the npz format's sidecar; a zarr store has none."""
    from lobemap.core.imagefmt import Volume

    v = _volume(shape=(60, 40, 40))
    npz = v.save(tmp_path / "v.npz", sidecar=True)
    staged = Volume.load(npz)
    assert staged.meta["data_file"] == "v.data.npy"
    back = Volume.load(staged.save(tmp_path / "v.zarr"))
    assert "data_file" not in back.meta
