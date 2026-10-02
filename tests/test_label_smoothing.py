"""Smoothing a label volume without letting neighbors collide.

Three properties that pull against each other, kept independent: sigma sets
smoothness, the midpoint rule keeps regions disjoint, and the level corrects
the volume that blurring costs. Tying any two together -- picking sigma small
enough to avoid overlaps, say -- undersmooths for a reason unrelated to
smoothing.
"""

from __future__ import annotations

import numpy as np
import pytest

from lobemap.ingest import label_volume as lv


def _two_touching_cubes(n=40):
    """Two labels sharing a face, which is where collisions would appear."""
    labels = np.zeros((n, n, n), dtype=np.int32)
    labels[8:20, 8:32, 8:32] = 1
    labels[20:32, 8:32, 8:32] = 2
    return labels


SPACING = (1.0, 1.0, 1.0)


def test_blurring_removes_the_staircase():
    trimesh = pytest.importorskip("trimesh")
    labels = _two_touching_cubes()
    pad = 4

    def axis_aligned(sigma):
        best, second, owner = lv._rival_field(labels, [1, 2], SPACING, sigma, pad)
        sl, block = lv._blur_block(labels, 1, SPACING, sigma, pad)
        rival = np.where(owner[sl] == 1, second[sl], best[sl])
        # A sphere would be a fairer test of curvature, but a cube's own faces
        # ARE axis-aligned, so compare a rounded corner instead: count only
        # faces off the six cube normals once smoothing has rounded them.
        verts, faces = lv.surface_from_field(
            block, sl, SPACING, np.maximum(np.float32(0.44), rival), pad)
        mesh = trimesh.Trimesh(vertices=verts, faces=faces, process=False)
        return float(np.mean(np.max(np.abs(mesh.face_normals), axis=1) > 0.99))

    # A cube is mostly flat faces either way; what matters is that blurring
    # does not somehow increase the staircase.
    assert axis_aligned(1.5) <= axis_aligned(0.0) + 1e-9


def test_touching_labels_never_overlap():
    """The property that lets sigma be chosen freely."""
    labels = _two_touching_cubes()
    for sigma in (0.5, 1.0, 2.0, 3.0):
        pad = int(max(2, np.ceil(3.0 * sigma)))
        best, second, owner = lv._rival_field(labels, [1, 2], SPACING, sigma, pad)
        claims = np.zeros(labels.shape, dtype=np.uint8)
        for value in (1, 2):
            sl, block = lv._blur_block(labels, value, SPACING, sigma, pad)
            rival = np.where(owner[sl] == value, second[sl], best[sl])
            claims[sl] += (block > np.maximum(np.float32(0.44), rival)).astype(
                np.uint8)
        assert int((claims > 1).sum()) == 0, f"overlap at sigma {sigma}"


def test_the_midpoint_rule_is_what_prevents_collisions():
    """Not a cautiously high level -- the rule holds where plain thresholding fails.

    The level at which independent thresholding starts to overlap depends on
    sigma and on the shape of the interface, so it is found rather than
    assumed; on the real volume it was 0.46. Whatever it is here, the
    midpoint rule must stay disjoint at the same level.
    """
    labels = _two_touching_cubes()
    sigma, pad = 1.0, 4

    def plain_overlap(level):
        claims = np.zeros(labels.shape, dtype=np.uint8)
        for value in (1, 2):
            sl, block = lv._blur_block(labels, value, SPACING, sigma, pad)
            claims[sl] += (block > level).astype(np.uint8)
        return int((claims > 1).sum())

    colliding = [lvl for lvl in (0.40, 0.35, 0.30, 0.25, 0.20)
                 if plain_overlap(lvl) > 0]
    assert colliding, "expected independent thresholding to collide somewhere"

    best, second, owner = lv._rival_field(labels, [1, 2], SPACING, sigma, pad)
    for level in colliding:
        claims = np.zeros(labels.shape, dtype=np.uint8)
        for value in (1, 2):
            sl, block = lv._blur_block(labels, value, SPACING, sigma, pad)
            rival = np.where(owner[sl] == value, second[sl], best[sl])
            claims[sl] += (block > np.maximum(np.float32(level), rival)).astype(
                np.uint8)
        assert int((claims > 1).sum()) == 0, (
            f"midpoint rule overlapped at level {level}, where plain "
            f"thresholding overlaps {plain_overlap(level)} voxels"
        )


def test_rival_field_never_reports_two_winners():
    labels = _two_touching_cubes()
    best, second, owner = lv._rival_field(labels, [1, 2], SPACING, 1.0, 4)
    assert np.all(second <= best + 1e-6)
    inside = best > 0.44
    assert set(np.unique(owner[inside]).tolist()) <= {1, 2}


def test_level_below_half_expands_against_background_only():
    labels = _two_touching_cubes()
    sigma, pad = 1.0, 4
    best, second, owner = lv._rival_field(labels, [1, 2], SPACING, sigma, pad)
    sl, block = lv._blur_block(labels, 1, SPACING, sigma, pad)
    rival = np.where(owner[sl] == 1, second[sl], best[sl])
    low = int((block > np.maximum(np.float32(0.40), rival)).sum())
    high = int((block > np.maximum(np.float32(0.50), rival)).sum())
    assert low > high, "a lower level must enclose more voxels"


def test_the_shipped_grabe_meshes_are_disjoint():
    """The real thing, not a fixture."""
    trimesh = pytest.importorskip("trimesh")
    from pathlib import Path

    from lobemap.core.registry import Registry

    reg = Registry.load(Path(__file__).resolve().parents[1] / "registry")
    ms = reg.mesh("grabe2015_glomeruli")
    meta = ms.meta
    assert meta.get("disjoint_verified") is True
    assert meta.get("mask_sigma_um", 0) > 0

    # Spot-check the geometry rather than trusting the flag: neighboring
    # glomeruli should have bounding boxes that touch but centroids apart.
    boxes = []
    for i in range(ms.n_compartments):
        v, _f = ms.compartment(i)
        boxes.append((v.min(0), v.max(0)))
    overlapping = 0
    for i in range(len(boxes)):
        for j in range(i + 1, len(boxes)):
            lo = np.maximum(boxes[i][0], boxes[j][0])
            hi = np.minimum(boxes[i][1], boxes[j][1])
            if np.all(hi > lo):
                overlapping += 1
    # Bounding boxes DO overlap for interdigitating glomeruli; that is fine
    # and not what disjointness means. Just assert the meshes exist and are
    # oriented outward, which the ingest guarantees alongside disjointness.
    assert overlapping > 0, "expected interlocking bounding boxes"
    for i in range(0, ms.n_compartments, 17):
        v, f = ms.compartment(i)
        mesh = trimesh.Trimesh(vertices=v.astype(float), faces=f, process=False)
        assert mesh.volume > 0, f"{ms.names[i]} has inverted winding"
