"""Source units, declared rather than deduced.

Every mesh ingest has to turn source coordinates into micrometers, and
the factor used to be recovered by measurement: try nm, um and 8 nm
voxels in turn and keep whichever made a glomerulus come out an anatomically
plausible size. That reads as careful and is not. It infers a property of
the FILE from a property of the ANIMAL, so a dataset whose compartments
happened to fall outside the expected range would be rejected as
unreadable, and one that was wrong by a factor the range happened to admit
would be accepted silently. It also had to be kept in step with anatomy:
widening the neuropil range to admit the optic lobes widened what counted
as a believable unit.

So the factor comes from the source instead:

- neuPrint states it. The `:Meta` node carries `voxelSize` and
  `voxelUnits`, and its ROI meshes are in voxels, so the two give the
  scale exactly -- `[8, 8, 8]` nanometers for both the hemibrain and the
  male CNS, hence 0.008 um per unit.
- OBJ and VTP state nothing. There is no units field in either format, so
  for those the recipe declares `source_units` and cites where it comes
  from. A declaration in `recipes.toml` is reviewable and wrong in one
  obvious place; a guess is wrong invisibly.

The plausibility range survives as a CHECK, in `verify_extent`. Having
decided the scale from the source, it is worth confirming the result is
not absurd -- but a failure there now means the declaration disagrees with
the data, which is a thing to go and look at, rather than an instruction
to try another factor.
"""

from __future__ import annotations

import re

import numpy as np

#: Micrometers per unit, for the unit names a source may state.
UNIT_TO_UM = {
    "um": 1.0,
    "micrometer": 1.0,
    "micrometers": 1.0,
    "micron": 1.0,
    "microns": 1.0,
    "nm": 1e-3,
    "nanometer": 1e-3,
    "nanometers": 1e-3,
}

#: Voxel-indexed coordinates: `px8nm` is an index into an 8 nm grid.
_VOXEL_RE = re.compile(r"^px(?P<size>[0-9]+(?:\.[0-9]+)?)(?P<unit>[a-z]+)$")


def scale_to_um(source_units: str) -> float:
    """Micrometers per source unit, for a declared unit name.

    Accepts a physical unit (`nm`, `um`) or a voxel pitch written as
    `px<size><unit>`, so `px8nm` is one index step on an 8 nm grid.
    """
    name = str(source_units).strip().lower()
    if name in UNIT_TO_UM:
        return UNIT_TO_UM[name]
    m = _VOXEL_RE.match(name)
    if m is not None:
        unit = m.group("unit")
        if unit in UNIT_TO_UM:
            return float(m.group("size")) * UNIT_TO_UM[unit]
    raise ValueError(
        f"unknown source_units {source_units!r}; expected one of "
        f"{sorted(UNIT_TO_UM)} or a voxel pitch like 'px8nm'"
    )


def voxel_units_name(voxel_size, voxel_units: str) -> str:
    """The `px<size><unit>` name for a source that states its voxel grid.

    `voxel_size` may be a scalar or a per-axis sequence; an anisotropic
    grid raises, because one scalar factor cannot describe it and
    silently taking the first axis would skew the geometry.
    """
    sizes = np.atleast_1d(np.asarray(voxel_size, dtype=float)).ravel()
    if not len(sizes):
        raise ValueError("source states no voxel size")
    if not np.allclose(sizes, sizes[0]):
        raise ValueError(
            f"anisotropic voxel grid {sizes.tolist()}: one scale factor "
            "cannot describe it, so the ingest needs a per-axis scale"
        )
    name = str(voxel_units).strip().lower()
    if name not in UNIT_TO_UM:
        raise ValueError(f"source states unknown voxelUnits {voxel_units!r}")
    size = sizes[0]
    text = f"{size:g}"
    return f"px{text}{name_to_symbol(name)}"


def name_to_symbol(name: str) -> str:
    """`nanometers` -> `nm`, so a derived unit name is readable."""
    if name.startswith("nano"):
        return "nm"
    if name.startswith("micro") or name in ("um",):
        return "um"
    return name


def verify_extent(
    extents, scale: float, expect: tuple[float, float], source_units: str,
    what: str = "compartment",
) -> float:
    """Confirm the declared scale yields plausible sizes. Returns the median.

    Raises if it does not. This is a check on the DECLARATION, not a way
    of choosing one: the median extent is used so a single odd compartment
    cannot swing it.
    """
    lo, hi = expect
    typical = float(np.median(np.asarray(extents, dtype=float))) * scale
    if not lo <= typical <= hi:
        raise ValueError(
            f"declared source_units {source_units!r} (x{scale:g} -> um) give "
            f"a median {what} extent of {typical:.4g} um, outside the "
            f"expected {lo}-{hi} um. Either the declaration is wrong or the "
            f"source is not what it was when this was written."
        )
    return typical


__all__ = [
    "UNIT_TO_UM",
    "name_to_symbol",
    "scale_to_um",
    "verify_extent",
    "voxel_units_name",
]
