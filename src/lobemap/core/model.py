"""Core data model.

Reference geometry is not a separate class -- it is an Asset with a different
`role`. That is what keeps this small.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path
from typing import Any, Literal

Units = Literal["nm", "um", "px"]

Role = Literal[
    "glomeruli",
    "neuropil",
    "brain",
    "template_image",
    "virtual_stain",
    "map_2d",
]

Kind = Literal["meshset", "mesh", "image", "labels"]

Side = Literal["L", "R"]

#: How a space's image laterality relates to the animal's.
#:
#: "biological": image left is the fly's right, the normal frontal-view
#: convention. Hemibrain, male CNS and the JRC2018 templates.
#:
#: "mirrored": the image data is left-right inverted, so image left is the
#: fly's LEFT. FAFB and FlyWire. Verified by measurement: FlyWire's AL_L --
#: whose annotation is the modern, post-correction one -- bridges onto
#: hemibrain AL(R) at 4.6 um versus 94.3 um to AL(L). The bridging
#: registrations therefore preserve APPARENT side, not biological side.
LateralConvention = Literal["biological", "mirrored"]

#: Signed axis references, as a rotation axis may be given:
#: "-z" means the negative z direction.
_AXIS_INDEX = {"x": 0, "y": 1, "z": 2}


def axis_vector(spec: str):
    """Turn a signed axis reference like "-z" into a unit vector."""
    import numpy as np

    text = spec.strip().lower()
    sign = -1.0 if text.startswith("-") else 1.0
    letter = text.lstrip("+-")
    if letter not in _AXIS_INDEX:
        raise ValueError(f"not an axis reference: {spec!r}")
    out = np.zeros(3)
    out[_AXIS_INDEX[letter]] = sign
    return out


def anatomical_axes(space):
    """Pole -> unit vector, in this space's array coordinates, or None.

    None when the space declares no rotation, which is the only way to
    declare anatomy here.

    R points at the BIOLOGICAL right. The declared rotation's third
    column is the pole a right-handed triad can show, which is LEFT in
    a mirrored space, so the two differ by a sign there -- and getting
    it wrong is silent, since nothing about a single lobe looks wrong
    on its own.
    """

    rot = anatomical_rotation_matrix(space)
    if rot is None:
        return None
    a, d, lat = rot[:, 0], rot[:, 1], rot[:, 2]
    r = -lat if space.is_mirrored else lat
    return {"A": a, "P": -a, "D": d, "V": -d, "R": r, "L": -r}


#: The three axes, as (positive pole, negative pole, label).
AXIS_POLES = (("A", "P", "A-P"), ("D", "V", "D-V"), ("R", "L", "L-R"))


def rotation_axis_vector(space):
    """Unit vector for a space's declared rotation axis, or None.

    A signed array axis ("+x") or a raw vector, both in ARRAY
    coordinates. Not a pole name: the poles are what this rotation
    defines, so naming one would be circular.
    """
    import numpy as np

    spec = space.anatomical_rotation_axis
    if spec is None:
        return None
    if isinstance(spec, str):
        return axis_vector(spec)
    v = np.asarray(spec, dtype=float)
    n = float(np.linalg.norm(v))
    return None if n == 0 else v / n


def anatomical_rotation_matrix(space):
    """The declared rotation as a matrix, or None if none is declared.

    Its columns are the anterior, dorsal and lateral directions, so this
    is also exactly what the axis triad needs: arrow i is drawn along
    +e_i and lands on column i, the pole `axis_labels_for` writes on it.
    """
    import numpy as np

    axis = rotation_axis_vector(space)
    if axis is None or space.anatomical_rotation_deg is None:
        return None
    t = np.radians(float(space.anatomical_rotation_deg))
    K = np.array([[0.0, -axis[2], axis[1]],
                  [axis[2], 0.0, -axis[0]],
                  [-axis[1], axis[0], 0.0]])
    return np.eye(3) + np.sin(t) * K + (1.0 - np.cos(t)) * (K @ K)


def anatomical_triad(space, reflect_axis: int | None = None):
    """(matrix, labels) for the anatomical triad, or None.

    `reflect_axis` mirrors the frame along one array axis before
    choosing, for a viewer showing the space reflected. That flips the
    handedness of the anatomy, so the arrangement a right-handed triad
    can draw changes with it and one label comes back the opposite pole
    -- R for L, most visibly. Passing it is how a mirrored view stays
    honest about which side is which; without it the triad would name
    the unmirrored anatomy over mirrored data.

    The columns are the three anatomical directions and the labels name
    the pole each one points at, so arrow k reaches the pole written on
    it.

    The SIGN of each pole is what keeps the triad clear of the fixed
    x/y/z one it is drawn beside: of the 24 proper candidates, the one
    whose closest approach to a world arrow is furthest away.

    Which arrow carries which axis is NOT that, and cannot be. The
    objective is the worst column of a per-column quantity, so permuting
    the columns leaves it exactly unchanged -- all three permutations of
    a given sign set tie. The assignment falls to the tie-break below,
    which takes the one sitting closest to the array axes.

    The world arrows are only the POSITIVE directions -- napari draws
    each along increasing index and cannot reverse one -- which is what
    makes the sign choice bite. Against a full set of plus-and-minus
    axes the distance to the nearest would be fixed by the anatomy and
    nothing here could improve it; against three positive arrows,
    flipping A to P swings an arrow from 17 degrees off +z to 162.

    Two earlier objectives were worse. Nearest-to-its-own-axis put the
    two triads almost on top of each other. Furthest-from-its-own-axis
    maximized a SUM, so it bought two near-reversals by leaving a third
    arrow 17 degrees from its counterpart -- and neither looked at the
    other two world arrows at all.

    Right-handed by construction -- improper candidates are skipped --
    so the triad is one a rotation can actually draw.
    """
    import itertools

    import numpy as np

    frame = anatomical_axes(space)
    if frame is None:
        return None
    poles = [("A", "P"), ("D", "V"), ("R", "L")]
    vectors = [np.asarray(frame[p[0]], float) for p in poles]
    # The reflection the view is under, which two separate things need:
    # where each anatomical pole APPEARS, and where the world arrows it is
    # keeping clear of now point. Identity when nothing is mirrored.
    world = np.eye(3)
    if reflect_axis is not None:
        world[reflect_axis, reflect_axis] = -1.0
        # The labels still mean the same anatomy; only the directions move.
        vectors = [world @ v for v in vectors]

    best = None
    for order in itertools.permutations(range(3)):
        for signs in itertools.product((1, -1), repeat=3):
            cols = [signs[k] * vectors[order[k]] for k in range(3)]
            M = np.column_stack(cols)
            if np.linalg.det(M) < 0:
                continue                 # a reflection; not drawable
            # Closest approach to ANY world arrow, which is the worst
            # over columns of the best over the three positive axes.
            # cos is decreasing in angle, so the largest component is
            # the nearest arrow and we want that as small as possible.
            # Against the arrows AS DRAWN. napari's triad is reflected
            # under a mirror too, so its x arrow points -x there, and
            # measuring against +x would pick a sign set that lands on
            # top of it -- which is exactly what it did.
            #
            # Arrow j points along `world @ e_j`, so a column c meets it
            # at c . (world @ e_j) = (world @ c)[j], making the whole
            # cosine table `world @ M`.
            seen = world @ M
            closest = float(np.max(seen))
            # The three permutations of a sign set always tie on
            # `closest`, so the trace is what actually settles which
            # arrow carries which axis: the assignment nearest the
            # array axes, which is also stable across edits.
            score = (-closest, float(np.trace(seen)))
            if best is None or score > best[0]:
                names = tuple(poles[order[k]][0 if signs[k] > 0 else 1]
                              for k in range(3))
                best = (score, M, names)
    return None if best is None else (best[1], best[2])


def lateral_pole(space) -> str:
    """Which lateral pole a right-handed triad can show here."""
    return "L" if space.is_mirrored else "R"


def flip_side(side):
    """Swap L and R. Anything else -- None, "both" -- passes through."""
    if side == "L":
        return "R"
    if side == "R":
        return "L"
    return side

#: How an atlas's compartment relates to the canonical vocabulary of its
#: space (`Registry.vocabulary`; there is no registry-wide one). Read from the
#: atlas's point of view:
#:
#:   exact    one compartment, one canonical name, same name
#:   renamed  one compartment, one canonical name, different name
#:            (hemibrain VC3l is canonical VC3 -- Schlegel et al. 2021)
#:   split    several compartments share ONE canonical name, because this
#:            atlas resolves a structure the vocabulary does not
#:            (Schlegel S11's VM6l, VM6m, VM6v are all canonical VM6)
#:   merge    ONE compartment carries several canonical names, because this
#:            atlas does not resolve a structure the vocabulary does. No
#:            shipped row uses it: Grabe's VP1 was one until GRABE got its own
#:            vocabulary, where VP1 is simply exact.
#:   absent   no correspondence
Relation = Literal["exact", "split", "merge", "renamed", "absent"]

#: Conversion into the internal working unit (micrometers).
TO_UM: Mapping[str, float] = {"nm": 1e-3, "um": 1.0}


@dataclass(frozen=True)
class Space:
    """A coordinate frame, with units.

    `flybrains_template` is None for an island -- a space with no bridging
    registrations to anything else (Grabe).
    """

    id: str
    title: str
    units: Units
    flybrains_template: str | None = None
    lateral_convention: LateralConvention = "biological"
    #: The anatomy of this space, and the only thing that states it:
    #: the rotation carrying the ARRAY axes onto (anterior, dorsal,
    #: lateral), as an axis in array coordinates and an angle in
    #: degrees. +x goes to anterior, +y to dorsal, +z to the lateral
    #: pole -- RIGHT in an ordinary space, LEFT in a mirrored one.
    #:
    #: Which lateral pole is not a choice. napari draws its three arrows
    #: along +x, +y, +z -- right-handed -- and the viewer can only turn
    #: them. det[A, D, R] is +1 and det[A, D, L] is -1, so an ordinary
    #: space can only be shown as (A, D, R); a mirrored one has array
    #: space reflected, which inverts both, so it can only be (A, D, L).
    #:
    #: There used to be `anterior` and `dorsal` as well, naming a signed
    #: array axis each. They were the anatomy before it was measured,
    #: and afterwards they were only ever the NEAREST array axis to it
    #: -- a second, coarser answer to a question this already answers
    #: exactly. Slicing never read them (see `DIMS_ORDER_XYZ`), so only
    #: the camera did, and it is better off with the exact directions.
    #:
    #: Axis-angle rather than a matrix, because any axis and any angle
    #: name a proper rotation: nothing writable here is ill-formed.
    anatomical_rotation_axis: str | tuple[float, float, float] | None = None
    anatomical_rotation_deg: float | None = None
    #: Which of this space's atlases is shown when it opens. The others
    #: are loaded and listed, just switched off: a space holds every atlas
    #: native to it, and two glomerular parcellations drawn on top of each
    #: other are unreadable. Optional when the space has only one.
    primary_atlas: str | None = None
    notes: str = ""

    @property
    def is_island(self) -> bool:
        return self.flybrains_template is None

    @property
    def is_mirrored(self) -> bool:
        """True if image laterality is inverted relative to the animal."""
        return self.lateral_convention == "mirrored"

    def apparent_side(self, biological: Side | None) -> Side | None:
        """Which side of the IMAGE a biologically-`biological` structure sits on."""
        return flip_side(biological) if self.is_mirrored else biological

    def biological_side(self, apparent: Side | None) -> Side | None:
        """Which side of the ANIMAL an image-`apparent` structure belongs to."""
        return flip_side(apparent) if self.is_mirrored else apparent


@dataclass(frozen=True)
class Derivation:
    """How a computed asset was produced.

    Without this, a stale cache is undetectable after a dependency upgrade.
    `params` carries the resolved transform path for bridged assets -- not a
    hand-specified one, since navis chooses the route.
    """

    recipe: str
    inputs: tuple[str, ...] = ()
    params: Mapping[str, Any] = field(default_factory=dict)
    tool_versions: Mapping[str, str] = field(default_factory=dict)


@dataclass(frozen=True)
class Provenance:
    doi: str | None = None
    url: str | None = None
    retrieved: date | None = None
    license: str | None = None
    checksum: str | None = None
    derivation: Derivation | None = None


@dataclass(frozen=True)
class Asset:
    """Any geometry or image, atlas or reference alike."""

    id: str
    role: Role
    space: str
    kind: Kind
    path: Path
    side: Side | Literal["both"] | None = None
    #: Display colormap. None takes the role's default; see
    #: `lobemap.viewer.app.default_colormap`.
    colormap: str | None = None
    #: Any other napari image-layer keywords, overriding the role's defaults.
    #: Grabe's confocal channel is a `template_image` -- it is real microscopy,
    #: not a synthesised stain, and relabeling its role to get the look would
    #: be a lie about provenance -- but it should still be displayed like the
    #: stains, so it carries the override rather than the wrong role.
    display: Mapping[str, Any] = field(default_factory=dict)
    source: Provenance = field(default_factory=Provenance)


@dataclass(frozen=True)
class Compartment:
    """One glomerulus within one atlas.

    `published_name` is immutable and authoritative; `canonical` may hold zero,
    one or several names, because correspondence is not one-to-one -- several
    Schlegel S11 compartments share VM6, and a merge would give one
    compartment several names. See `Relation`.
    """

    local_id: int
    published_name: str
    side: Side | None = None
    canonical: tuple[str, ...] = ()
    relation: Relation = "exact"
    color: tuple[float, float, float, float] | None = None
    #: A short note shown after the name when its identity is in doubt, such
    #: as "VM6?", and why. Declared per atlas; see `Atlas.uncertain`. The
    #: published name and the correspondence stay as they are: the doubt is
    #: shown to the reader, not resolved.
    uncertain: str = ""
    uncertain_reason: str = ""

    @property
    def label(self) -> str:
        """The name to show a reader, with any doubt about it."""
        if self.uncertain:
            return f"{self.published_name} ({self.uncertain})"
        return self.published_name


@dataclass(frozen=True)
class Atlas:
    id: str
    title: str
    native_space: str
    asset: str
    citation: str = ""
    doi: str = ""
    parent: str | None = None
    compartments: tuple[Compartment, ...] = ()
    #: (published name, note, reason) for each compartment whose identity is
    #: uncertain, from the atlas TOML's `[uncertain]` table.
    uncertain: tuple[tuple[str, str, str], ...] = ()

    def by_name(self, name: str) -> Compartment | None:
        for c in self.compartments:
            if c.published_name == name:
                return c
        return None


# `Scene` and `LayerSpec` used to live here: a named set of layers, each
# with its own `visible`, `mirror` and `style`. They were removed because a
# scene was never a different view of the data. `build_scene` takes a SPACE
# and loads every atlas native to it; the scene was applied afterwards and
# set nothing but `.visible`, so two scenes on one space held identical
# layers and differed only in which boxes started ticked. `mirror` and
# `style` were never used by any scene in the registry.
#
# What remains of the idea is `Space.primary_atlas` plus visibility keyed on
# an asset's ROLE, which reproduced every scene the registry had except
# `hemibrain_three_ways` -- two clicks in the compartment panel.
