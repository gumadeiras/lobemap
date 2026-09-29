"""Which array axis a 2D slice steps along, and which plane it opens on.

A slice is always cut along an ARRAY axis: that is what keeps it square to
the voxel grid of the reference image, and exact mesh sections follow it.
The array axes are not the anatomical ones -- 1 to 6 degrees off for
left-right, 14.7 to 31.6 for the other two -- so each choice is named by the
anatomical axis nearest it, with the angle between them. The same angle is
why no anatomical arrows are drawn over a 2D slice.
"""

from __future__ import annotations

from dataclasses import dataclass
from itertools import permutations

import numpy as np

#: The array axes, as napari names them.
AXIS_LETTERS = ("x", "y", "z")

#: Anatomical axes, keyed by the pole `anatomical_axes` returns for each.
ANATOMY = (("A", "Anterior-Posterior"), ("D", "Dorsal-Ventral"),
           ("R", "Left-Right"))

#: The axis 2D steps along until the user picks another: z, the way a
#: confocal stack is read.
DEFAULT_SLICE_AXIS = 2


@dataclass(frozen=True)
class SliceAxis:
    """One choice of slice: the array axis stepped, and the anatomy nearest.

    `anatomy` and `degrees` are None for a space that declares no anatomy.
    """

    axis: int
    anatomy: str | None = None
    degrees: float | None = None

    @property
    def label(self) -> str:
        letter = AXIS_LETTERS[self.axis]
        if self.anatomy is None:
            return letter
        return f"{self.anatomy} ({letter}, {self.degrees:.1f}° off)"


def slice_axes(space) -> list[SliceAxis]:
    """The three choices for `space`, in anatomical order.

    Each array axis is paired with one anatomical axis, choosing the
    pairing that keeps them closest overall. In every registered space this
    is simply the nearest anatomical axis to each array axis; solving for
    the whole pairing keeps two array axes from ever claiming the same name.
    """
    from ..core.model import anatomical_axes

    frame = anatomical_axes(space) if space is not None else None
    if frame is None:
        return [SliceAxis(axis) for axis in (2, 1, 0)]
    # cosines[i][k]: |cos| between array axis i and anatomical axis k.
    cosines = np.abs(np.array([np.asarray(frame[pole]) for pole, _ in ANATOMY])).T
    best = max(permutations(range(3)),
               key=lambda p: sum(cosines[i][p[i]] for i in range(3)))
    out = []
    for i, k in enumerate(best):
        degrees = float(np.degrees(np.arccos(min(1.0, cosines[i][k]))))
        out.append(SliceAxis(i, ANATOMY[k][1], degrees))
    return sorted(out, key=lambda s: [name for _, name in ANATOMY].index(s.anatomy))


def order_for(axis: int, ndim: int = 3) -> tuple[int, ...]:
    """The `dims.order` that puts the slider on `axis`.

    napari displays the last two entries, rows then columns, so the other
    two go in descending order: stepping z gives (2, 1, 0), y down and x
    across, which is how the stacks here were always read.
    """
    rest = sorted((a for a in range(ndim) if a != axis), reverse=True)
    return (axis, *rest)


def compartment_spans(meshset, axis: int) -> np.ndarray:
    """(K, 2) lowest and highest coordinate of each compartment on `axis`."""
    vertices = np.asarray(meshset.vertices)
    offsets = np.asarray(meshset.vertex_offsets)
    out = np.full((meshset.n_compartments, 2), np.nan)
    for i in range(meshset.n_compartments):
        column = vertices[offsets[i]:offsets[i + 1], axis]
        if len(column):
            out[i] = column.min(), column.max()
    return out


def crosses(spans: np.ndarray, position: float) -> bool:
    """Whether a plane at `position` cuts any of these spans."""
    spans = spans[np.isfinite(spans).all(axis=1)]
    return bool(((spans[:, 0] <= position) & (position <= spans[:, 1])).any())


def busiest_plane(spans: np.ndarray) -> float | None:
    """The position cutting the most spans, nearest the middle on a tie.

    Candidates are the span midpoints: a plane that crosses the most
    compartments always crosses at least one midpoint's worth of them, and
    there are only as many candidates as compartments.
    """
    spans = spans[np.isfinite(spans).all(axis=1)]
    if not len(spans):
        return None
    mids = spans.mean(axis=1)
    counts = ((spans[None, :, 0] <= mids[:, None])
              & (mids[:, None] <= spans[None, :, 1])).sum(axis=1)
    middle = (spans[:, 0].min() + spans[:, 1].max()) / 2.0
    best = max(range(len(mids)),
               key=lambda i: (counts[i], -abs(mids[i] - middle)))
    return float(mids[best])


__all__ = [
    "AXIS_LETTERS",
    "DEFAULT_SLICE_AXIS",
    "SliceAxis",
    "busiest_plane",
    "compartment_spans",
    "crosses",
    "order_for",
    "slice_axes",
]
