"""Where an image of your own sits in a brain's space, and how to fit it there.

An image is placed by one 4x4 matrix, `P`: from its voxel indices, in the
(x, y, z) array order every volume here uses (`core.imagefmt`), to the
space's micrometers. Every move, turn, resize, flip and fit is a change of
that one matrix, so nothing about the image is stored twice and a fit can
replace a hand placement without leaving parts of it behind.

`P = A V`: `V` is the voxel size, diagonal, and `A` maps the image's own
micrometers into the space. A fit to landmarks finds either:

- an **affine** `P` (`fit_affine`), 12 numbers: it also absorbs a wrong or
  unknown voxel size and a stretch, and needs four landmarks that do not lie
  in one plane; or
- a **similarity** `A` (`fit_similarity`), 7 numbers: a move, a turn, one
  scale and, if the landmarks ask for it, a mirror. It trusts the voxel
  size and needs three landmarks not on one line. With few landmarks it is
  the safer fit, as an affine fitted to them stretches to follow their
  errors.

Landmarks are glomeruli: a voxel of the image clicked as a glomerulus's
middle, and that glomerulus's centroid in the brain's atlas.

The placement of an image in a space is kept beside the image, in
`<image file>.lobemap.json` (`read_alignment`, `write_alignment`), one entry
per space, so the same fly can be aligned to several brains.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np

from .atomic import replacing

#: The version of the alignment file's layout.
ALIGNMENT_FORMAT = 1

#: The suffix of the file an image's alignment is kept in.
ALIGNMENT_SUFFIX = ".lobemap.json"

#: How far below the largest a singular value may fall before a set of
#: points counts as lying on a plane (an affine fit) or a line (a similarity).
FLAT = 1e-6


class FitError(ValueError):
    """Landmarks that cannot determine the fit asked for; the message says why."""


def homogeneous(points) -> np.ndarray:
    """(n, 3) points with a column of ones."""
    points = np.asarray(points, float).reshape(-1, 3)
    return np.c_[points, np.ones(len(points))]


def apply(matrix, points) -> np.ndarray:
    """`matrix` (4x4) applied to (n, 3) points."""
    return homogeneous(points) @ np.asarray(matrix, float)[:3].T


def about(point, linear) -> np.ndarray:
    """The 4x4 map applying `linear` (3x3) about `point`, which stays put."""
    out = np.eye(4)
    out[:3, :3] = linear
    out[:3, 3] = np.asarray(point, float) - np.asarray(linear, float) @ np.asarray(point, float)
    return out


def shift(delta) -> np.ndarray:
    """The 4x4 move by `delta`."""
    out = np.eye(4)
    out[:3, 3] = delta
    return out


def corners(shape) -> np.ndarray:
    """The centers of the eight corner voxels of an array of `shape`."""
    return np.array([[(n - 1) * bit for n, bit in zip(shape, bits, strict=True)]
                     for bits in np.ndindex(2, 2, 2)], float)


def middle(matrix, shape) -> np.ndarray:
    """Where the middle of an image of `shape` is placed by `matrix`."""
    return apply(matrix, (np.asarray(shape, float) - 1.0) / 2.0)[0]


def placed_at(shape, voxel_um, center) -> np.ndarray:
    """An image of `shape`, unturned, with its middle at `center`."""
    matrix = np.diag([*(float(v) for v in voxel_um), 1.0])
    return shift(np.asarray(center, float) - middle(matrix, shape)) @ matrix


def with_voxel(matrix, shape, old_voxel, new_voxel) -> np.ndarray:
    """`matrix` for a new voxel size, the image's middle kept where it is.

    `A = P V⁻¹` is kept: the image keeps its turn, scale and place, and only
    its voxels change size.
    """
    old, new = np.diag([*old_voxel, 1.0]), np.diag([*new_voxel, 1.0])
    out = np.asarray(matrix, float) @ np.linalg.inv(old) @ new
    return shift(middle(matrix, shape) - middle(out, shape)) @ out


def _spread(points) -> np.ndarray:
    """Singular values of the points about their mean, largest first."""
    points = np.asarray(points, float)
    return np.linalg.svd(points - points.mean(axis=0), compute_uv=False)


def fit_affine(index, target) -> np.ndarray:
    """The least-squares affine `P` with `P(index) ≈ target`.

    `index` are voxel indices, `target` micrometers in the space, (n, 3)
    each. Four landmarks or more, not all in one plane.
    """
    index, target = np.asarray(index, float), np.asarray(target, float)
    if len(index) < 4:
        raise FitError(f"an affine fit needs 4 landmarks or more; there are {len(index)}")
    spread = _spread(index)
    if spread[2] <= FLAT * spread[0]:
        raise FitError("the landmarks lie in one plane: an affine fit needs some "
                       "above or below it")
    solved = np.linalg.lstsq(homogeneous(index), target, rcond=None)[0]
    out = np.eye(4)
    out[:3] = solved.T
    return out


def fit_similarity(index, target, voxel_um) -> np.ndarray:
    """The least-squares `P = A V` with `A` a similarity and `P(index) ≈ target`.

    Umeyama's solution, with a mirror allowed where the landmarks can show
    one: an image taken from behind the brain is the mirror image of one
    taken from in front, and the fit finds that rather than the nearest
    turn. Landmarks in one plane cannot -- the plane's mirror image fits
    them as well -- so three, or more in one plane, give a turn without a
    mirror, and an image that needs one is flipped by hand first. Three
    landmarks or more, not all on one line.
    """
    index, target = np.asarray(index, float), np.asarray(target, float)
    if len(index) < 3:
        raise FitError(f"a similarity fit needs 3 landmarks or more; there are {len(index)}")
    spread = _spread(index)
    if spread[1] <= FLAT * spread[0]:
        raise FitError("the landmarks lie on one line: the fit needs one off it")
    voxel = np.diag([*(float(v) for v in voxel_um), 1.0])
    source = apply(voxel, index)
    mu_s, mu_t = source.mean(axis=0), target.mean(axis=0)
    s, t = source - mu_s, target - mu_t
    u, sigma, vt = np.linalg.svd(t.T @ s / len(s))
    signs = np.ones(3)
    if spread[2] <= FLAT * spread[0] and np.linalg.det(u @ vt) < 0:
        signs[2] = -1.0
    turn = u @ np.diag(signs) @ vt
    scale = float((sigma * signs).sum() / (s ** 2).sum() * len(s))
    out = np.eye(4)
    out[:3, :3] = scale * turn
    out[:3, 3] = mu_t - scale * turn @ mu_s
    return out @ voxel


def residuals(matrix, index, target) -> np.ndarray:
    """How far, in micrometers, `matrix` puts each landmark from its target."""
    return np.linalg.norm(apply(matrix, index) - np.asarray(target, float), axis=1)


# -- the alignment file --------------------------------------------------------


@dataclass
class Landmark:
    """A glomerulus, and the voxel of the image clicked as its middle."""

    name: str
    index: tuple[float, float, float]


@dataclass
class Alignment:
    """An image's placement in one space: what the alignment file keeps."""

    matrix: np.ndarray
    voxel_um: tuple[float, float, float]
    landmarks: list[Landmark] = field(default_factory=list)

    def to_json(self) -> dict:
        return {
            "matrix": np.asarray(self.matrix, float).tolist(),
            "voxel_um": [float(v) for v in self.voxel_um],
            "landmarks": [{"name": m.name, "index": [float(v) for v in m.index]}
                          for m in self.landmarks],
        }

    @classmethod
    def from_json(cls, entry: dict) -> Alignment:
        matrix = np.asarray(entry["matrix"], float)
        if matrix.shape != (4, 4) or not np.all(np.isfinite(matrix)):
            raise ValueError("matrix is not a finite 4x4 matrix")
        if not np.allclose(matrix[3], (0.0, 0.0, 0.0, 1.0)) or abs(
                np.linalg.det(matrix[:3, :3])) < 1e-12:
            raise ValueError("matrix is not an invertible affine map")
        voxel = tuple(float(v) for v in entry["voxel_um"])
        if len(voxel) != 3 or not all(np.isfinite(v) and v > 0 for v in voxel):
            raise ValueError("voxel_um is not three positive sizes")
        landmarks = [Landmark(str(m["name"]), tuple(float(v) for v in m["index"]))
                     for m in entry.get("landmarks", [])]
        if any(len(m.index) != 3 for m in landmarks):
            raise ValueError("a landmark's index is not three numbers")
        return cls(matrix, voxel, landmarks)


def alignment_path(image: str | Path) -> Path:
    """Where `image`'s alignment is kept: beside it, `<name>.lobemap.json`."""
    image = Path(image)
    return image.with_name(image.name + ALIGNMENT_SUFFIX)


def _read_file(path: Path) -> dict:
    with open(path, encoding="utf-8") as fh:
        content = json.load(fh)
    if not isinstance(content, dict) or not isinstance(content.get("spaces"), dict):
        raise TypeError(f"{path.name} is not a lobemap alignment file")
    if content.get("format", ALIGNMENT_FORMAT) > ALIGNMENT_FORMAT:
        raise ValueError(f"{path.name} was written by a newer lobemap")
    return content


def read_alignment(image: str | Path, space: str) -> Alignment | None:
    """`image`'s alignment to `space`, or None if none is kept.

    Raises ValueError, naming the file, if the file is there but cannot be read.
    """
    path = alignment_path(image)
    if not path.exists():
        return None
    try:
        entry = _read_file(path)["spaces"].get(space)
        return None if entry is None else Alignment.from_json(entry)
    except (OSError, KeyError, TypeError, ValueError) as exc:
        raise ValueError(f"{path.name} could not be read: {exc}") from exc


def write_alignment(image: str | Path, space: str, alignment: Alignment) -> Path:
    """Keep `alignment` as `image`'s alignment to `space`; the other spaces' stay.

    Written whole beside the old file and renamed over it (`atomic`), so a
    failed write leaves the file as it was. Returns the file's path.
    """
    path = alignment_path(image)
    content = {"format": ALIGNMENT_FORMAT, "image": Path(image).name, "spaces": {}}
    if path.exists():
        try:
            content["spaces"] = _read_file(path)["spaces"]
        except (OSError, TypeError, ValueError) as exc:
            raise ValueError(f"{path.name} could not be read, so it was not "
                             f"overwritten: {exc}") from exc
    content["spaces"][space] = alignment.to_json()
    with replacing(path) as staged:
        staged.write_text(json.dumps(content, indent=2) + "\n", encoding="utf-8")
    return path


__all__ = [
    "ALIGNMENT_FORMAT",
    "ALIGNMENT_SUFFIX",
    "Alignment",
    "FitError",
    "Landmark",
    "about",
    "alignment_path",
    "apply",
    "corners",
    "fit_affine",
    "fit_similarity",
    "homogeneous",
    "middle",
    "placed_at",
    "read_alignment",
    "residuals",
    "shift",
    "with_voxel",
    "write_alignment",
]
