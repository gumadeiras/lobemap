"""Placing an image of your own: the fits, the moves, and the alignment file.

No data and no window. Each fit is checked by what it must recover: an
exact placement from exact landmarks, the mirror an image taken from behind
needs, and the right refusal when the landmarks cannot determine the fit.
"""

from __future__ import annotations

import json

import numpy as np
import pytest
from scipy.spatial.transform import Rotation

from lobemap.core import placement as pl

SHAPE = (60, 50, 30)
VOXEL = (0.5, 0.6, 2.0)


def _truth(mirror: bool = False, shear: bool = False) -> np.ndarray:
    """Voxel -> space: a turn, a scale, maybe a mirror or a shear, a shift."""
    linear = Rotation.from_euler("xyz", [25, -40, 110], degrees=True).as_matrix() * 1.3
    if mirror:
        linear = linear @ np.diag([-1.0, 1.0, 1.0])
    if shear:
        linear = linear @ np.array([[1.0, 0.2, 0.0], [0.0, 1.0, 0.1], [0.0, 0.0, 0.9]])
    out = np.eye(4)
    out[:3, :3] = linear @ np.diag(VOXEL)
    out[:3, 3] = [310.0, 220.0, 90.0]
    return out


def _landmarks(truth, n: int, seed: int = 0):
    index = np.random.default_rng(seed).uniform(0, np.array(SHAPE) - 1, (n, 3))
    return index, pl.apply(truth, index)


def test_an_affine_fit_recovers_any_affine_placement():
    truth = _truth(mirror=True, shear=True)
    index, target = _landmarks(truth, 7)
    fitted = pl.fit_affine(index, target)
    assert np.allclose(fitted, truth, atol=1e-9)
    assert pl.residuals(fitted, index, target).max() < 1e-9


@pytest.mark.parametrize("mirror", [False, True])
def test_a_similarity_fit_recovers_a_turn_a_scale_and_a_mirror(mirror):
    truth = _truth(mirror=mirror)
    index, target = _landmarks(truth, 4)
    fitted = pl.fit_similarity(index, target, VOXEL)
    assert np.allclose(fitted, truth, atol=1e-9)
    assert np.sign(np.linalg.det(fitted[:3, :3])) == (-1 if mirror else 1)


def test_three_landmarks_fit_a_turn_and_never_a_mirror():
    """Three points are one plane, which its mirror image fits as well."""
    truth = _truth()
    index, target = _landmarks(truth, 3)
    fitted = pl.fit_similarity(index, target, VOXEL)
    assert np.allclose(fitted, truth, atol=1e-9)
    for seed in range(20):
        index, target = _landmarks(_truth(mirror=True), 3, seed=seed)
        assert np.linalg.det(pl.fit_similarity(index, target, VOXEL)[:3, :3]) > 0


def test_noisy_landmarks_fit_to_within_their_noise():
    truth = _truth()
    index, target = _landmarks(truth, 12, seed=3)
    noisy = target + np.random.default_rng(4).normal(0.0, 0.5, target.shape)
    for fitted in (pl.fit_affine(index, noisy), pl.fit_similarity(index, noisy, VOXEL)):
        moved = pl.apply(fitted, index) - target
        assert np.sqrt((moved ** 2).sum(axis=1).mean()) < 1.0


def test_fits_refuse_landmarks_that_cannot_determine_them():
    truth = _truth()
    index, target = _landmarks(truth, 6)
    with pytest.raises(pl.FitError, match="4 landmarks"):
        pl.fit_affine(index[:3], target[:3])
    with pytest.raises(pl.FitError, match="3 landmarks"):
        pl.fit_similarity(index[:2], target[:2], VOXEL)
    flat = index.copy()
    flat[:, 2] = 5.0
    with pytest.raises(pl.FitError, match="one plane"):
        pl.fit_affine(flat, pl.apply(truth, flat))
    line = np.outer(np.arange(4.0), [1.0, 2.0, 3.0])
    with pytest.raises(pl.FitError, match="one line"):
        pl.fit_similarity(line, pl.apply(truth, line), VOXEL)


def test_a_new_voxel_size_keeps_the_middle_and_the_turn():
    truth = _truth()
    moved = pl.with_voxel(truth, SHAPE, VOXEL, (1.0, 1.0, 4.0))
    assert np.allclose(pl.middle(moved, SHAPE), pl.middle(truth, SHAPE))
    # The same image micrometers land the same way: A = P V^-1 is kept.
    assert np.allclose(moved[:3, :3] @ np.diag(1 / np.array([1.0, 1.0, 4.0])),
                       truth[:3, :3] @ np.diag(1 / np.array(VOXEL)))


def test_an_image_placed_at_a_point_has_its_middle_there():
    matrix = pl.placed_at(SHAPE, VOXEL, (10.0, 20.0, 30.0))
    assert np.allclose(pl.middle(matrix, SHAPE), (10.0, 20.0, 30.0))
    assert np.allclose(np.diag(matrix)[:3], VOXEL)


def test_the_alignment_file_keeps_each_space_beside_the_image(tmp_path):
    image = tmp_path / "fly.tif"
    image.write_bytes(b"")
    first = pl.Alignment(_truth(), VOXEL, [pl.Landmark("DA1(L)", (1.0, 2.0, 3.0))])
    second = pl.Alignment(_truth(mirror=True), (1.0, 1.0, 1.0))
    path = pl.write_alignment(image, "GRABE", first)
    pl.write_alignment(image, "FAFB14", second)
    assert path == tmp_path / "fly.tif.lobemap.json"
    got = pl.read_alignment(image, "GRABE")
    assert np.allclose(got.matrix, first.matrix) and got.voxel_um == VOXEL
    assert got.landmarks == first.landmarks
    assert np.allclose(pl.read_alignment(image, "FAFB14").matrix, second.matrix)
    assert pl.read_alignment(image, "JRCFIB2018F") is None
    assert pl.read_alignment(tmp_path / "other.tif", "GRABE") is None


@pytest.mark.parametrize("content", [
    "not json",
    json.dumps([1, 2]),
    json.dumps({"spaces": {"GRABE": {"matrix": [[1, 0], [0, 1]], "voxel_um": [1, 1, 1]}}}),
    json.dumps({"spaces": {"GRABE": {"matrix": np.eye(4).tolist(), "voxel_um": [1, 0, 1]}}}),
    json.dumps({"format": 99, "spaces": {}}),
])
def test_an_unreadable_alignment_file_says_so_and_is_not_overwritten(tmp_path, content):
    image = tmp_path / "fly.tif"
    path = pl.alignment_path(image)
    path.write_text(content)
    with pytest.raises(ValueError, match=path.name):
        pl.read_alignment(image, "GRABE")
    if "GRABE" not in content:
        with pytest.raises(ValueError, match="not overwritten"):
            pl.write_alignment(image, "GRABE", pl.Alignment(np.eye(4), (1.0, 1.0, 1.0)))
        assert path.read_text() == content
