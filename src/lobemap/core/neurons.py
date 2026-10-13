"""Neurons of your own: skeletons from FlyWire or an SWC file, placed in a space.

A neuron comes from a FlyWire root ID, a FlyWire Codex link to one, or an SWC
file, and is a skeleton: points and, for each, its parent. Its points are
in the coordinates of where it came from -- FlyWire's are FAFB v14.1 in
nanometers -- and are brought into the open brain as atlas geometry is
(`resolve.resolve_points`): through navis's bridging registrations, in
micrometers, and mirrored on the way where the two spaces disagree about
laterality, so a neuron of the fly's left lobe lands in the left lobe. An
island space -- Grabe 2015 -- takes only neurons already in its own
coordinates.

FlyWire and the bridges need the ingest extra (`pip install "lobemap[ingest]"`):
fafbseg to fetch a skeleton, navis and flybrains to bridge it. An SWC file
in the open brain's own coordinates needs neither.

For drawing, a skeleton is thinned to a point every `SPACING_UM` along each
unbranched run, keeping every branch point, end and root (`thinned`), and
drawn as a tube of `TUBE_RADIUS_UM` (`tube`). FlyWire's skeletons have a
point about every half micrometer, so a large local neuron was 68,000
points and 820,000 triangles.
"""

from __future__ import annotations

import re
import urllib.parse
from dataclasses import dataclass
from pathlib import Path

import numpy as np

#: The FlyWire release a bare root ID is read from: the public one.
FLYWIRE_VERSION = 783

#: The coordinates of FlyWire's skeletons: FAFB v14.1, nanometers. FAFB and
#: FlyWire are both left-right mirrored relative to the animal
#: (`registry/spaces.toml`).
FLYWIRE_TEMPLATE = "FLYWIRE"
FLYWIRE_LATERAL = "mirrored"

#: Distance between the points a drawn skeleton keeps along a run, in um.
SPACING_UM = 1.0

#: The drawn tube's radius, in um, and the sides of its cross-section.
TUBE_RADIUS_UM = 0.4
TUBE_SIDES = 6

#: SWC units by the names the viewer offers.
SWC_UNITS = {"nanometers": "nm", "micrometers": "um", "8 nm voxels": "px8nm"}

_DIGITS = re.compile(r"^\d{15,20}$")

#: Said when FlyWire or a bridge is asked for without the ingest extra.
NEEDS_INGEST = ('{what} needs lobemap\'s extra packages: pip install "lobemap[ingest]", '
                "or uv sync in a checkout")


#: Said when navis has no route between two brains: the hemibrain is reached
#: only through Janelia's registrations, which flybrains downloads on request.
NO_BRIDGE = ("This computer does not have the files that link other brains to {target}. "
             "To download them, run python -c \"import flybrains; "
             "flybrains.download_jrc_transforms()\" once. They take several GB.")


class NeuronError(ValueError):
    """A neuron that cannot be read or placed; the message says why."""


@dataclass(frozen=True)
class NeuronSpec:
    """Where a neuron comes from: a FlyWire root ID and release, or a file."""

    root_id: int | None = None
    version: int = FLYWIRE_VERSION
    path: Path | None = None

    @property
    def name(self) -> str:
        return str(self.root_id) if self.root_id is not None else self.path.stem


def parse_spec(text: str) -> NeuronSpec:
    """A root ID, a FlyWire Codex link, or the path of an SWC file."""
    text = str(text).strip()
    if _DIGITS.match(text):
        return NeuronSpec(root_id=int(text))
    if text.lower().startswith(("http://", "https://")):
        url = urllib.parse.urlparse(text)
        query = urllib.parse.parse_qs(url.query)
        dataset = query.get("dataset", ["fafb"])[0].lower()
        if dataset not in ("fafb", "flywire"):
            raise NeuronError(f"the link is to the {dataset} dataset; lobemap reads "
                              "FlyWire (FAFB) neurons")
        root = query.get("root_id") or query.get("cell_names_or_id")
        if not root or not _DIGITS.match(root[0].strip()):
            raise NeuronError("the link names no root ID (root_id=...)")
        version = query.get("data_version", [str(FLYWIRE_VERSION)])[0]
        if not version.isdigit():
            raise NeuronError(f"the link's data_version is not a number: {version}")
        return NeuronSpec(root_id=int(root[0].strip()), version=int(version))
    path = Path(text).expanduser()
    if path.suffix.lower() != ".swc":
        raise NeuronError(f"{text!r} is not a FlyWire root ID, a FlyWire Codex link "
                          "or an SWC file")
    if not path.is_file():
        raise NeuronError(f"{path} is not a file")
    return NeuronSpec(path=path)


def read_swc(path: str | Path) -> tuple[np.ndarray, np.ndarray]:
    """(points in the file's units, parent index or -1) from an SWC file."""
    path = Path(path)
    rows = []
    try:
        with open(path, encoding="utf-8", errors="replace") as fh:
            for line in fh:
                line = line.split("#", 1)[0].strip()
                if line:
                    rows.append(line.split()[:7])
    except OSError as exc:
        raise NeuronError(f"{path.name} could not be read: {exc}") from exc
    try:
        table = np.array(rows, dtype=float).reshape(-1, 7)
    except ValueError as exc:
        raise NeuronError(f"{path.name} is not an SWC file: each line needs seven "
                          "numbers") from exc
    if not len(table):
        raise NeuronError(f"{path.name} has no points")
    ids, parent_ids = table[:, 0].astype(np.int64), table[:, 6].astype(np.int64)
    return table[:, 2:5], _parents(ids, parent_ids, path.name)


def _parents(ids: np.ndarray, parent_ids: np.ndarray, what: str) -> np.ndarray:
    """Each node's parent as an index, -1 for a root."""
    order = np.argsort(ids)
    if len(np.unique(ids)) != len(ids):
        raise NeuronError(f"{what}: some node IDs are repeated")
    root = parent_ids < 0
    where = np.searchsorted(ids[order], parent_ids)
    where = np.minimum(where, len(ids) - 1)
    found = ids[order][where] == parent_ids
    if not np.all(found | root):
        raise NeuronError(f"{what}: some nodes name a parent that is not there")
    return np.where(root, -1, order[where]).astype(np.int64)


def fetch_flywire(root_id: int, version: int = FLYWIRE_VERSION) -> tuple[np.ndarray, np.ndarray]:
    """(points in nanometers, parent index or -1) of a FlyWire neuron's skeleton."""
    try:
        import warnings

        import navis
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            from fafbseg import flywire
    except ImportError as exc:
        raise NeuronError(NEEDS_INGEST.format(what="Reading a FlyWire neuron")) from exc
    try:
        skeleton = navis.NeuronList(flywire.get_skeletons(int(root_id), dataset=int(version),
                                                          progress=False))
    except Exception as exc:
        raise NeuronError(f"FlyWire has no skeleton of {root_id} in release {version}, "
                          f"or could not be reached: {exc}") from exc
    if not len(skeleton):
        raise NeuronError(f"FlyWire has no skeleton of {root_id} in release {version}")
    nodes = skeleton[0].nodes
    points = nodes[["x", "y", "z"]].to_numpy(float)
    return points, _parents(nodes.node_id.to_numpy(np.int64),
                            nodes.parent_id.to_numpy(np.int64), str(root_id))


def into_space(points_um: np.ndarray, template: str | None, lateral: str | None,
               space) -> np.ndarray:
    """Points in micrometers of `template` brought into `space`, in micrometers.

    `template` None means the points are in `space`'s own coordinates. A
    neuron lands on the side of the animal it is on: mirrored where the two
    disagree about laterality (`resolve.resolve`'s `align_biology`).
    """
    if template is None or (template == space.flybrains_template
                            and lateral == space.lateral_convention):
        return np.asarray(points_um, float)
    if space.is_island:
        raise NeuronError(f"{space.title or space.id} has no link to other brains, so it can "
                          "show only SWC files in its own coordinates")
    try:
        from .resolve import resolve_points

        if template == FLYWIRE_TEMPLATE:
            _register_flywire()
        out, _record = resolve_points(points_um, template, space.flybrains_template,
                                      mirror=lateral != space.lateral_convention)
    except ImportError as exc:
        raise NeuronError(NEEDS_INGEST.format(what="Bridging a neuron")) from exc
    except Exception as exc:
        if "No bridging path" in str(exc):
            raise NeuronError(NO_BRIDGE.format(target=space.title or space.id)) from exc
        raise NeuronError(f"the neuron could not be bridged from {template} to "
                          f"{space.flybrains_template}: {exc}") from exc
    return out


def load(spec: NeuronSpec, space, template: str | None = None, lateral: str | None = None,
         units: str = "nm") -> tuple[np.ndarray, np.ndarray, str]:
    """(points, parents, where from in words) of a neuron, thinned, in `space`.

    A FlyWire neuron is in FlyWire's coordinates; an SWC file is in
    `template`'s -- None for `space`'s own -- with `lateral` its laterality,
    in `units` (`core.units.scale_to_um`).
    """
    from .units import scale_to_um

    if spec.root_id is not None:
        points, parents = fetch_flywire(spec.root_id, spec.version)
        points_um = points * 1e-3
        template, lateral = FLYWIRE_TEMPLATE, FLYWIRE_LATERAL
        source = f"FlyWire, release {spec.version}"
    else:
        points, parents = read_swc(spec.path)
        points_um = points * scale_to_um(units)
        source = spec.path.name
    placed = into_space(points_um, template, lateral, space)
    return (*thinned(placed, parents), source)


def _register_flywire() -> None:
    """Give navis fafbseg's FlyWire registrations.

    They are registered on import. Without them navis bridged FlyWire to
    FAFB14 through the male CNS, two thin-plate warps, where fafbseg's own
    route is two affines and an offset field, with no warp.
    """
    import warnings

    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        import fafbseg  # noqa: F401


def _order(parents: np.ndarray) -> np.ndarray:
    """Node indices with each parent before its children."""
    children: dict[int, list[int]] = {}
    for child, parent in enumerate(parents.tolist()):
        children.setdefault(parent, []).append(child)
    out, stack = [], list(reversed(children.get(-1, [])))
    while stack:
        node = stack.pop()
        out.append(node)
        stack.extend(reversed(children.get(node, [])))
    if len(out) != len(parents):
        raise NeuronError("the skeleton has a loop: some nodes are their own ancestors")
    return np.asarray(out, np.int64)


def thinned(points: np.ndarray, parents: np.ndarray,
            spacing: float = SPACING_UM) -> tuple[np.ndarray, np.ndarray]:
    """The skeleton with a point every `spacing` along each unbranched run.

    Every root, branch point and end is kept, and each point kept is joined
    to its nearest kept ancestor, so the tree is the same tree.
    """
    points, parents = np.asarray(points, float), np.asarray(parents, np.int64)
    n = len(points)
    count = np.bincount(parents[parents >= 0], minlength=n)
    fixed = (parents < 0) | (count != 1)
    step = np.zeros(n)
    has = parents >= 0
    step[has] = np.linalg.norm(points[has] - points[parents[has]], axis=1)
    # Python lists: a walk of 68,000 points indexing arrays took a second.
    keep, run, up = [False] * n, [0.0] * n, [-1] * n
    parent_of, fixed, step = parents.tolist(), fixed.tolist(), step.tolist()
    for node in _order(parents).tolist():
        parent = parent_of[node]
        if parent < 0:
            keep[node] = True
            continue
        up[node] = parent if keep[parent] else up[parent]
        run[node] = step[node] + (0.0 if keep[parent] else run[parent])
        keep[node] = fixed[node] or run[node] >= spacing
    keep, up = np.asarray(keep), np.asarray(up, np.int64)
    index = np.cumsum(keep) - 1
    kept = np.flatnonzero(keep)
    new_parents = np.where(up[kept] >= 0, index[np.maximum(up[kept], 0)], -1)
    return points[kept], new_parents.astype(np.int64)


def tube(points: np.ndarray, parents: np.ndarray, radius: float = TUBE_RADIUS_UM,
         sides: int = TUBE_SIDES) -> tuple[np.ndarray, np.ndarray]:
    """(vertices, faces) of a tube along every edge, wound outward.

    A prism per edge, open at its ends: at a bend two prisms overlap or
    leave a sliver, under half a radius, which is not seen at this size.
    """
    points, parents = np.asarray(points, float), np.asarray(parents, np.int64)
    child = np.flatnonzero(parents >= 0)
    a, b = points[child], points[parents[child]]
    along = b - a
    length = np.linalg.norm(along, axis=1)
    a, b, along = a[length > 0], b[length > 0], along[length > 0] / length[length > 0, None]
    if not len(a):
        return np.zeros((0, 3), np.float32), np.zeros((0, 3), np.int32)
    helper = np.where(np.abs(along[:, :1]) < 0.9, [[1.0, 0.0, 0.0]], [[0.0, 1.0, 0.0]])
    e1 = np.cross(along, helper)
    e1 /= np.linalg.norm(e1, axis=1, keepdims=True)
    e2 = np.cross(along, e1)
    theta = 2.0 * np.pi * np.arange(sides) / sides
    ring = radius * (np.cos(theta)[None, :, None] * e1[:, None]
                     + np.sin(theta)[None, :, None] * e2[:, None])
    vertices = np.concatenate([a[:, None] + ring, b[:, None] + ring], axis=1)
    k = np.arange(sides)
    nxt = (k + 1) % sides
    # Per edge: ring a is 0..sides-1, ring b is sides..2 sides-1.
    one = np.concatenate([np.stack([k, nxt, sides + k], axis=1),
                          np.stack([nxt, sides + nxt, sides + k], axis=1)])
    base = (np.arange(len(a)) * 2 * sides)[:, None, None]
    faces = (one[None] + base).reshape(-1, 3)
    return vertices.reshape(-1, 3).astype(np.float32), faces.astype(np.int32)


__all__ = [
    "FLYWIRE_LATERAL",
    "FLYWIRE_TEMPLATE",
    "FLYWIRE_VERSION",
    "NEEDS_INGEST",
    "NO_BRIDGE",
    "SPACING_UM",
    "SWC_UNITS",
    "TUBE_RADIUS_UM",
    "TUBE_SIDES",
    "NeuronError",
    "NeuronSpec",
    "fetch_flywire",
    "into_space",
    "load",
    "parse_spec",
    "read_swc",
    "thinned",
    "tube",
]
