"""Registry-level validation: atlases brought into one space and compared."""

from __future__ import annotations

from ..core.meshfmt import MeshSet
from . import geometry as g


def canonical_names(atlas) -> dict[str, tuple[str, ...]]:
    return {c.published_name: tuple(c.canonical) for c in atlas.compartments}


def _side(reg, atlas) -> str | None:
    side = reg.assets[atlas.asset].side
    return side if side in ("L", "R") else None


def atlas_in_space(reg, atlas_id: str, space: str) -> MeshSet:
    """An atlas's meshes in `space`, bridged so that sides agree biologically.

    The bridging registrations preserve APPARENT side (see spaces.toml), so
    comparing a mirrored space with a biological one without a mirror puts
    FAFB's left lobe on the hemibrain's right one, and a side-keyed
    comparison then pairs it with the wrong lobe or with nothing.

    The mirror is applied in the source space, so the source must have a
    mirror registration; without one navis falls back to a bounding-box
    reflection, which is not a midline mirror. That case is refused rather
    than measured.
    """
    from ..core import spaces as sp
    from ..core.resolve import resolve

    atlas = reg.atlases[atlas_id]
    if atlas.native_space == space:
        return reg.mesh(atlas.asset)
    src, dst = reg.spaces[atlas.native_space], reg.spaces[space]
    if (
        src.lateral_convention != dst.lateral_convention
        and not sp.has_mirror_registration(src.flybrains_template)
    ):
        raise ValueError(
            f"{atlas_id} cannot be aligned biologically into {space}: "
            f"{src.flybrains_template} has no mirror registration, so the "
            f"mirror would be a bounding-box reflection. Compare in "
            f"{atlas.native_space} instead."
        )
    return resolve(reg, atlas.asset, space, align_biology=True)


def compare_atlases(reg, a_id: str, b_id: str, space: str):
    """Correspondence between two atlases in `space`, by canonical name."""
    a_atlas, b_atlas = reg.atlases[a_id], reg.atlases[b_id]
    return g.correspondence_report(
        atlas_in_space(reg, a_id, space),
        atlas_in_space(reg, b_id, space),
        a_id,
        b_id,
        a_side=_side(reg, a_atlas),
        b_side=_side(reg, b_atlas),
        a_canonical=canonical_names(a_atlas),
        b_canonical=canonical_names(b_atlas),
    )
