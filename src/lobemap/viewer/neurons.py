"""Your neurons in a scene: tubes in 3D, and their exact sections in Slice view.

All the neurons of a brain are one part of its scene (`yours`), as an
atlas is: one compartment per neuron, a Surface layer of tubes along their
skeletons (`core.neurons.tube`), and contours that draw, on each plane,
where the tubes cross it. Showing or hiding a neuron is selecting its
compartment, so its eye, picking and hover work as an atlas's do: "720575…
— Your neurons".

The contours are not cut from the tube mesh. `sections.MeshSections` took
125-165 ms a plane for one large local neuron's 330,000-820,000 triangles,
where a slice step takes 2-4 ms. A tube's section by a plane is known from
its skeleton alone: where an edge crosses the plane, the cylinder around it
cuts an ellipse, its short axis the tube's radius and its long axis along
the edge's direction in the plane, as long as the radius over the cosine of
the edge's angle to the plane's normal, but no longer than the edge's own
reach in the plane (`SkeletonSections`). So the outlines are the tubes'.
"""

from __future__ import annotations

import threading
from dataclasses import dataclass

import numpy as np

from ..core.meshfmt import MeshSet
from ..core.neurons import TUBE_RADIUS_UM, tube
from .sections import SECTION_CACHE_BYTES, PlaneCache, plane_key

#: The scene's key for your neurons: no part of a space is named so.
KEY = "your neurons"

#: The title their layers and their hover text name them by.
TITLE = "Your neurons"

#: A neuron's colors, in the order neurons are added; distinct from the
#: atlas outline colors (`parts.ATLAS_CONTOUR_COLORS`) and from gray.
COLORS = ("#ff4d6d", "#00e5ff", "#ffd60a", "#7cff6b", "#c77dff", "#ff9f1c",
          "#4cc9f0", "#f72585")

#: Points around each section of a tube.
SECTION_POINTS = 12


@dataclass
class Neuron:
    """One neuron of yours, in the open brain's micrometers."""

    name: str
    #: Where it came from, in words: "FlyWire, release 783".
    source: str
    points: np.ndarray
    parents: np.ndarray
    color: str
    visible: bool = True


class SkeletonSections:
    """The sections of tubes around skeletons by a plane: an ellipse where an
    edge crosses it. What `contours.ContourOverlay` reads, as it reads
    `sections.MeshSections`; safe from any thread.
    """

    def __init__(self, skeletons, radius: float = TUBE_RADIUS_UM,
                 max_bytes: int = SECTION_CACHE_BYTES) -> None:
        #: (points, parents) of each compartment.
        self.skeletons = [(np.asarray(p, np.float64), np.asarray(q, np.int64))
                          for p, q in skeletons]
        self.radius = float(radius)
        self.planes = PlaneCache(max_bytes)
        self._frame = (None, None)
        self._lock = threading.Lock()

    def at(self, axis: int, position: float, keep=None, pause=None,
           frame=None) -> dict[int, list[np.ndarray]] | None:
        """Compartment index -> closed polylines on the plane x[axis] = position,
        or in `frame` the plane q[axis] = position, in q."""
        key = plane_key(axis, position, frame)
        hit = self.planes.get(key)
        if hit is not None:
            return hit
        out = {}
        for index, (points, parents) in enumerate(self._points(frame)):
            loops = _crossings(points, parents, int(axis), float(position), self.radius)
            if len(loops):
                out[index] = list(loops)
        return self.planes.put(key, out, sum(loop.nbytes for v in out.values() for loop in v),
                               keep=keep)

    def _points(self, frame) -> list:
        """Each skeleton's (points, parents), in `frame` if given."""
        if frame is None:
            return self.skeletons
        with self._lock:
            if self._frame[0] != frame.key:
                self._frame = (frame.key, [(frame.apply(p), q) for p, q in self.skeletons])
            return self._frame[1]

    def drop_frames(self) -> None:
        """Forget every plane cut in a frame."""
        with self._lock:
            self._frame = (None, None)
        self.planes.drop(lambda key: len(key) > 2)


def _crossings(points, parents, axis: int, position: float, radius: float) -> np.ndarray:
    """(edges crossing, SECTION_POINTS + 1, 3): each crossing's ellipse, closed."""
    child = np.flatnonzero(parents >= 0)
    a, b = points[child], points[parents[child]]
    crossing = (a[:, axis] < position) != (b[:, axis] < position)
    a, b = a[crossing], b[crossing]
    if not len(a):
        return np.zeros((0, SECTION_POINTS + 1, 3))
    along = b - a
    t = (position - a[:, axis]) / along[:, axis]
    center = a + t[:, None] * along
    center[:, axis] = position
    length = np.linalg.norm(along, axis=1)
    unit = along / length[:, None]
    cosine = np.abs(unit[:, axis])
    flat = unit.copy()
    flat[:, axis] = 0.0
    sine = np.linalg.norm(flat, axis=1)
    # The long axis along the edge's direction in the plane; an edge square
    # to the plane has none, and any direction in the plane will do.
    other = [d for d in range(3) if d != axis]
    major = np.zeros_like(flat)
    major[:, other[0]] = 1.0
    tilted = sine > 1e-9
    major[tilted] = flat[tilted] / sine[tilted, None]
    normal = np.zeros(3)
    normal[axis] = 1.0
    minor = np.cross(normal, major)
    reach = np.minimum(radius / np.maximum(cosine, 1e-9), radius + 0.5 * length * sine)
    theta = 2.0 * np.pi * np.arange(SECTION_POINTS + 1) / SECTION_POINTS
    theta[-1] = 0.0                             # closed: the first point again
    loops = (center[:, None]
             + np.cos(theta)[None, :, None] * (reach[:, None] * major)[:, None]
             + np.sin(theta)[None, :, None] * (radius * minor)[:, None])
    loops[:, :, axis] = position
    return loops


def build(viewer, neurons: list[Neuron], mirror):
    """The surface and contours of `neurons`, or None if there are none.

    `mirror` is the scene's (axis, center) while reflected (`yours.mirror_args`).
    Each neuron is shown as its `visible` says.
    """
    from napari.utils.colormaps.standardize_color import transform_color

    from .contours import ContourOverlay
    from .layers import AtlasSurface
    from .yours import leave_out

    if not neurons:
        return None
    leave_out(viewer)
    parts = [(n.name, *tube(n.points, n.parents)) for n in neurons]
    meshset = MeshSet.from_parts(parts, meta={"space": "yours", "units": "um"})
    colors = np.array([transform_color(n.color)[0] for n in neurons], float)
    names = [n.name for n in neurons]
    shown = {i for i, n in enumerate(neurons) if n.visible}
    surface = AtlasSurface(viewer, meshset, name=TITLE, selection=sorted(shown),
                           colors=colors, opacity=1.0, blending="translucent",
                           display_names=names, visible=False, mirror=mirror,
                           colormap_name="Your neuron colors")
    surface.layer.metadata["lobemap"].update(id=KEY, yours=TITLE)
    contour = ContourOverlay(
        viewer, meshset, name=TITLE, color=neurons[0].color, selection=shown,
        width=0.1, colors=colors, display_names=names,
        sections=SkeletonSections([(n.points, n.parents) for n in neurons]))
    contour.layer.metadata["lobemap"]["yours"] = TITLE
    contour.filled = set(range(len(neurons)))
    return surface, contour


__all__ = ["COLORS", "KEY", "SECTION_POINTS", "TITLE", "Neuron", "SkeletonSections",
           "build"]
