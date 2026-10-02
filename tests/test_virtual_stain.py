"""Virtual stain: the binned-KDE machinery, offline and synthetic."""

from __future__ import annotations

import numpy as np
import pytest

from lobemap.core.imagefmt import Volume
from lobemap.ingest.virtual_stain import (
    StainAccumulator,
    build_stain,
    effective_sigma_um,
    grid_for_bounds,
)

pytest.importorskip("scipy")


def test_effective_sigma_matches_the_binning_correction():
    """Binning convolves the Gaussian with a voxel-wide box.

    sqrt(sigma^2 + h^2/12): 900 nm at 500 nm voxels -> 912 nm, a 1.3%
    inflation. The measured pipeline reports exactly this.
    """
    assert effective_sigma_um(0.9, 0.5) == pytest.approx(0.9115, abs=1e-4)
    # A vanishing voxel recovers the nominal bandwidth.
    assert effective_sigma_um(0.9, 1e-9) == pytest.approx(0.9, abs=1e-6)
    # A coarser grid inflates it more.
    assert effective_sigma_um(0.9, 2.0) > effective_sigma_um(0.9, 0.5)


def test_accumulator_counts_into_the_right_voxel():
    acc = StainAccumulator(origin_um=np.zeros(3), voxel_um=1.0, shape=(4, 4, 4))
    acc.add(np.array([[0.5, 0.5, 0.5], [2.2, 1.1, 3.9], [2.2, 1.1, 3.9]]))
    assert acc.counts[0, 0, 0] == 1
    assert acc.counts[2, 1, 3] == 2
    assert acc.counts.sum() == 3
    assert acc.stats.n_points == 3
    assert acc.stats.n_outside == 0


def test_accumulator_counts_points_outside_rather_than_dropping_silently():
    acc = StainAccumulator(origin_um=np.zeros(3), voxel_um=1.0, shape=(2, 2, 2))
    acc.add(np.array([[0.5, 0.5, 0.5], [99.0, 0.0, 0.0], [-5.0, 0.0, 0.0]]))
    assert acc.counts.sum() == 1
    assert acc.stats.n_outside == 2


def test_accumulator_is_additive_across_batches():
    """Streaming must give the same answer as one big batch."""
    rng = np.random.default_rng(0)
    pts = rng.uniform(0, 8, size=(5000, 3))
    one = StainAccumulator(np.zeros(3), 1.0, (8, 8, 8))
    one.add(pts)
    many = StainAccumulator(np.zeros(3), 1.0, (8, 8, 8))
    for chunk in np.array_split(pts, 7):
        many.add(chunk)
    assert np.array_equal(one.counts, many.counts)


def test_blur_spreads_a_point_to_the_expected_width():
    acc = StainAccumulator(np.zeros(3), 0.5, (41, 41, 41))
    acc.add(np.array([[10.25, 10.25, 10.25]]))  # center voxel
    blurred = acc.blurred(sigma_um=0.9)
    peak = np.unravel_index(blurred.argmax(), blurred.shape)
    assert peak == (20, 20, 20)
    # Second moment along one axis recovers sigma, within binning error.
    profile = blurred.sum(axis=(1, 2))
    x = (np.arange(len(profile)) - 20) * 0.5
    sigma = np.sqrt((profile * x**2).sum() / profile.sum())
    assert sigma == pytest.approx(effective_sigma_um(0.9, 0.5), rel=0.1)


def test_grid_covers_bounds_with_padding():
    origin, shape = grid_for_bounds([0, 0, 0], [10, 20, 30], voxel_um=0.5, pad_um=5.0)
    assert np.allclose(origin, [-5, -5, -5])
    extent = np.asarray(shape) * 0.5
    assert np.all(origin + extent >= np.array([10, 20, 30]) + 5.0 - 1e-9)


def test_build_stain_records_its_recipe_and_places_the_volume():
    rng = np.random.default_rng(1)
    blob = rng.normal(loc=[20, 20, 20], scale=1.5, size=(4000, 3))
    volume, stats = build_stain(
        iter([blob]), [10, 10, 10], [30, 30, 30],
        space="TEST", source="synthetic", confidence=0.5,
    )
    assert isinstance(volume, Volume)
    assert stats.n_points == 4000
    params = volume.meta["derivation"]["params"]
    assert params["synapse_type"] == "pre"
    assert params["confidence_threshold"] == 0.5
    assert params["sigma_um"] == 0.9
    assert params["effective_sigma_um"] == pytest.approx(0.9115, abs=1e-4)
    assert params["n_synapses"] == 4000
    # The brightest voxel must sit at the blob, in world coordinates.
    peak = np.unravel_index(volume.data.argmax(), volume.shape)
    world = np.asarray(volume.origin_um) + np.asarray(peak) * 0.5
    assert np.allclose(world, [20, 20, 20], atol=1.5)


def test_stain_sampling_round_trips_through_world_coordinates():
    rng = np.random.default_rng(2)
    blob = rng.normal(loc=[20, 20, 20], scale=1.0, size=(3000, 3))
    volume, _ = build_stain(
        iter([blob]), [10, 10, 10], [30, 30, 30], space="TEST", source="synthetic"
    )
    at_blob = volume.sample(np.array([[20.0, 20.0, 20.0]]))[0]
    far = volume.sample(np.array([[12.0, 12.0, 12.0]]))[0]
    assert at_blob > 10 * max(far, 1.0)
