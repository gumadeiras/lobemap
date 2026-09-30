"""The `lobemap check` suite, run against a loaded registry.

Kept apart from the CLI so the same suite can be run on a registry whose
data was altered in memory -- which is how the tests prove each check fails
on the mistake it is there to catch.
"""

from __future__ import annotations

import tomllib
from pathlib import Path

import numpy as np

from ..core.meshfmt import MeshSet
from ..core.model import anatomical_axes
from ..core.resolve import CannotBridge
from . import geometry as g
from . import images as gi
from . import laterality as gl


def known_defects(root: str | Path) -> dict[str, dict[str, str]]:
    """atlas id -> {published name: reason}, from registry/checks.toml."""
    path = Path(root) / "checks.toml"
    if not path.exists():
        return {}
    with path.open("rb") as fh:
        body = tomllib.load(fh)
    return {
        atlas: {name: str(entry.get("reason", "")) for name, entry in names.items()}
        for atlas, names in body.get("known_defects", {}).items()
    }


def lateral_axis(space) -> int | None:
    """The array axis closest to a space's left-right axis, if it declares one."""
    frame = anatomical_axes(space)
    if frame is None:
        return None
    return int(np.argmax(np.abs(np.asarray(frame["R"], dtype=float))))


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
        raise CannotBridge(
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


def _present(reg, space: str, role: str | None = None, kind: str | None = None):
    return [
        a for a in reg.assets_in_space(space, role=role)
        if a.path.exists() and (kind is None or a.kind == kind)
    ]


def geometry_checks(reg, space_id: str, known: dict) -> list[g.Check]:
    checks: list[g.Check] = []
    space = reg.spaces[space_id]
    shells = _present(reg, space_id, role="neuropil")
    labels = _present(reg, space_id, kind="labels")
    sets: list[tuple[str, MeshSet]] = []

    for atlas in reg.atlases_in_space(space_id):
        try:
            ms = reg.mesh(atlas.asset)
        except (FileNotFoundError, KeyError):
            continue
        sets.append((atlas.id, ms))
        checks.append(g.check_scale(ms, label=atlas.id))
        checks.append(
            g.check_compartment_sizes(ms, label=atlas.id, known=known.get(atlas.id))
        )
        if shells:
            # Sides here only PAIR a glomerulus with its shell, so both must
            # use the same convention -- and biological is the one assets and
            # source names record. Converting only the glomerulus side to
            # apparent, as an earlier version did, pairs Bates with the wrong
            # lobe in FAFB: its asset says biological L, the FlyWire shells
            # are named AL_L/AL_R biologically, and flipping one side of the
            # comparison breaks the match.
            checks.append(
                g.check_containment(
                    ms,
                    reg.mesh(shells[0].id),
                    glom_side=reg.assets[atlas.asset].side,
                    shell_side=shells[0].side,
                )
            )
        for asset in labels:
            chk = gi.check_label_containment(ms, reg.volume(asset.id))
            if chk is not None:
                checks.append(chk)

    for asset in shells:
        sets.append((asset.id, reg.mesh(asset.id)))
    chk = gl.check_lateral_sides(space, sets)
    if chk is not None:
        checks.append(chk)

    primary = reg.primary_atlas(space_id)
    if primary is not None and shells and reg.assets[primary.asset].path.exists():
        chk = gl.check_chirality(
            space,
            reg.mesh(primary.asset),
            reg.mesh(shells[0].id),
            canonical=canonical_names(primary),
            glom_side=_side(reg, primary),
        )
        if chk is not None:
            checks.append(chk)
    return checks


def image_checks(reg, space_id: str) -> list[g.Check]:
    """Are the images where they claim to be, and the right way round?"""
    from ..core.resolve import resolve

    checks: list[g.Check] = []
    axis = lateral_axis(reg.spaces[space_id])
    for asset in reg.assets_in_space(space_id):
        if asset.kind != "image" or not asset.path.exists():
            continue
        volume = reg.volume(asset.id)
        peers = reg.atlases_in_space(asset.space)
        ms = None
        label = asset.id
        if peers:
            ms = reg.mesh(peers[0].asset)
        else:
            # An image in a space with no native atlas would otherwise go
            # unchecked entirely, so bridge one in and hold it to the same
            # standard. No shipped asset reaches this today -- it was written
            # for JRC2018U's nc82 template, which has since been dropped --
            # but the alternative is that the next such image is silently
            # never validated. Apparent sides are what an overlay needs, so
            # there is no biological alignment here.
            for candidate in reg.atlases.values():
                src = reg.spaces.get(candidate.native_space)
                if src is None or src.is_island:
                    continue
                try:
                    ms = resolve(reg, candidate.asset, asset.space)
                except Exception:  # noqa: BLE001, S112 - try the next atlas
                    continue
                label = f"{asset.id} (vs bridged {candidate.id})"
                break
        if ms is not None:
            checks.append(gi.check_image_covers_mesh(volume, ms, label))
            checks.append(gi.check_image_brightness_at_mesh(volume, ms, label))

        shells = _present(reg, asset.space, role="neuropil")
        samples = None
        if shells:
            samples = gi.shell_samples(volume, reg.mesh(shells[0].id))
            checks.append(
                gi.check_image_inside_shell(
                    volume, reg.mesh(shells[0].id), asset.id, samples=samples
                )
            )
        elif ms is not None:
            # No shell, as in GRABE: the glomeruli are the geometry to fit.
            samples = gi.shell_samples(volume, ms)
        if samples is not None and axis is not None:
            checks.append(gi.check_image_orientation(volume, samples, axis, asset.id))
    return checks


def run_checks(reg, spaces=None) -> list[g.Check]:
    """Every validation check for the given spaces (default: all)."""
    known = known_defects(reg.root)
    checks: list[g.Check] = []
    for space_id in spaces or reg.spaces:
        checks += geometry_checks(reg, space_id, known)
        checks += image_checks(reg, space_id)
    return checks
