"""Bridge geometry between coordinate spaces, with caching.

The correctness core. Everything here is invisible when it works and produces
confident, wrong pictures when it doesn't, which is why the validation harness
in lobemap.validate lands alongside it.

Two rules, both from measurement:

1. **Mirror before bridge.** navis.mirror_brain succeeds on every template,
   falling back to a bounding-box reflection where no registration exists. For
   a half-brain like hemibrain that is not a midline mirror -- it returns
   plausible wrong geometry rather than raising. So mirroring happens in the
   source space, which is chosen to be one where mirroring is meaningful.

2. **Storage is micrometers; navis wants template-native units.** Every
   conversion is explicit and asserted, because nm/um slips are the most likely
   way to be silently 1000x off.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path

import numpy as np
from platformdirs import user_cache_dir

from . import spaces as sp
from .meshfmt import LegacyContainerError, MeshSet

#: 2: points a bridge does not cover are kept in micrometers. Version 1
#: kept them in the source template's units, 1000x off from nm to um.
CACHE_VERSION = 2


def cache_root() -> Path:
    return Path(user_cache_dir("lobemap")) / "bridged"


class CannotBridge(ValueError):
    """A request to move geometry between spaces that cannot be honored.

    Raised for an island space and for a biological alignment with no
    mirror registration; the message says why and what to do instead.
    """


@dataclass(frozen=True)
class ResolveKey:
    source_hash: str
    source_space: str
    target_space: str
    mirror: bool
    path: tuple[str, ...]
    tool_versions: tuple[tuple[str, str], ...]

    def digest(self) -> str:
        blob = json.dumps(
            {
                "v": CACHE_VERSION,
                "src": self.source_hash,
                "from": self.source_space,
                "to": self.target_space,
                "mirror": self.mirror,
                "path": list(self.path),
                "tools": dict(self.tool_versions),
            },
            sort_keys=True,
        )
        return hashlib.sha256(blob.encode()).hexdigest()[:24]


def template_scale_to_um(template: str) -> float:
    """Multiplier taking that template's native units into micrometers."""
    import flybrains

    t = getattr(flybrains, template, None)
    if t is None:
        raise KeyError(f"flybrains has no template {template!r}")
    units = t.units
    units = str(units[0] if isinstance(units, (list, tuple)) else units).lower()
    if "nano" in units:
        return 1e-3
    if "micro" in units or "micron" in units:
        return 1.0
    raise ValueError(f"{template}: unhandled template units {units!r}")


def resolve_points(
    points_um: np.ndarray,
    source_template: str,
    target_template: str,
    mirror: bool = False,
    allow_binary: bool | None = None,
) -> tuple[np.ndarray, dict]:
    """Transform (n, 3) points in micrometers between two templates.

    Returns the transformed points, also in micrometers, plus a record of what
    was done -- suitable for a Derivation.
    """
    src_scale = template_scale_to_um(source_template)
    pts = np.asarray(points_um, dtype=np.float64) / src_scale  # um -> native

    record: dict = {
        "source_template": source_template,
        "target_template": target_template,
        "mirror": mirror,
        "source_scale_to_um": src_scale,
    }

    if mirror:
        # In the SOURCE space, before bridging. See module docstring.
        record["mirror_registered"] = sp.has_mirror_registration(source_template)
        pts = sp.mirror(pts, source_template)
    before_um = pts * src_scale

    if source_template == target_template:
        record["path"] = [source_template]
        record["classes"] = []
        record["n_warps"] = 0
        record["needs_binary"] = False
        out_scale = src_scale
    else:
        pts, info = sp.bridge(
            pts, source_template, target_template, allow_binary=allow_binary
        )
        record.update(info)
        out_scale = template_scale_to_um(target_template)

    record["target_scale_to_um"] = out_scale
    out = np.asarray(pts, dtype=np.float64) * out_scale  # native -> um

    # A point the transform does not cover comes back NaN, and a NaN vertex
    # destroys a mesh, so it keeps its position from before the bridge --
    # converted to um like everything else. That is defensible only because
    # the transform skipped is sub-micron where this happens; the count is
    # recorded so a large one is visible rather than absorbed.
    bad = ~np.isfinite(out).all(axis=1)
    record["n_nonfinite"] = int(bad.sum())
    record["frac_nonfinite"] = float(bad.mean()) if len(bad) else 0.0
    if bad.any():
        out[bad] = before_um[bad]
    return out, record


def resolve_meshset(
    meshset: MeshSet,
    source_space: str,
    target_space: str,
    source_template: str,
    target_template: str,
    mirror: bool = False,
    allow_binary: bool | None = None,
    use_cache: bool = True,
) -> MeshSet:
    """Bridge a whole MeshSet, caching on content plus the resolved route."""
    if source_template == target_template and not mirror:
        return meshset

    versions = sp.tool_versions()
    # The route is part of the key, so a flybrains release that reroutes
    # invalidates the cache even if versions were somehow unchanged.
    try:
        route = tuple(
            sp.choose_path(
                source_template, target_template, allow_binary=allow_binary
            )["path"]
        )
    except Exception:  # noqa: BLE001 - keyed as unknown; resolve will raise
        route = ("?",)

    key = ResolveKey(
        source_hash=meshset.content_hash(),
        source_space=source_space,
        target_space=target_space,
        mirror=mirror,
        path=route,
        tool_versions=tuple(sorted(versions.items())),
    )
    cached = cache_root() / f"{key.digest()}.npz"
    if use_cache and cached.exists():
        try:
            return MeshSet.load(cached)
        except LegacyContainerError:
            pass                 # a pickled entry is never read; rebuild it

    out, record = resolve_points(
        meshset.vertices.astype(np.float64),
        source_template,
        target_template,
        mirror=mirror,
        allow_binary=allow_binary,
    )
    record["tool_versions"] = versions

    result = meshset.transformed(
        out,
        meta={
            "space": target_space,
            "units": "um",
            "derivation": {
                "recipe": "bridge" + ("+mirror" if mirror else ""),
                "inputs": [meshset.meta.get("dataset", source_space)],
                "params": record,
                "tool_versions": versions,
            },
            "source_space": source_space,
        },
    )
    if use_cache:
        result.save(cached)
    return result


def resolve(
    registry,
    asset_id: str,
    target_space: str,
    mirror: bool = False,
    allow_binary: bool | None = None,
    use_cache: bool = True,
    align_biology: bool = False,
) -> MeshSet:
    """Registry-level entry point: bring `asset_id` into `target_space`.

    `align_biology=True` adds a mirror when the source and target spaces
    disagree about laterality. The bridging registrations preserve APPARENT
    side: FlyWire's AL_L -- biologically left -- lands on hemibrain's AL(R).
    That is right for overlaying anatomy as imaged, and wrong for asking
    whether two atlases agree about the *same* side of the animal. Verified by
    measurement, see registry/spaces.toml.
    """
    asset = registry.assets[asset_id]
    src = registry.spaces[asset.space]
    dst = registry.spaces[target_space]
    if align_biology and src.lateral_convention != dst.lateral_convention:
        mirror = not mirror
    if src.is_island or dst.is_island:
        raise CannotBridge(
            f"cannot bridge {asset.space} -> {target_space}: "
            f"{'source' if src.is_island else 'target'} is an island"
        )
    return resolve_meshset(
        registry.mesh(asset_id),
        source_space=asset.space,
        target_space=target_space,
        source_template=src.flybrains_template,
        target_template=dst.flybrains_template,
        mirror=mirror,
        allow_binary=allow_binary,
        use_cache=use_cache,
    )
