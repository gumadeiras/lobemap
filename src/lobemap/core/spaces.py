"""Adapter over navis-flybrains.

flybrains and navis are ingest-time dependencies, not runtime ones, so
they are imported lazily: opening a scene must work without them.

Routing policy, from the measurements in design section 3: take navis's route.
The registry weights warps at 1.0 and affines/aliases at 0-0.1, so the shortest
weighted path is the one with the fewest warps -- an accuracy heuristic. Only
override to dodge an external-binary transform when the alternative TIES on warp
count.
"""

from __future__ import annotations

import functools
from typing import Any

import numpy as np

#: Transform classes that actually deform, and so compound interpolation error.
WARP_CLASSES = {"h5reg", "cmtk", "elastix", "thinplate", "moving_least_squares"}

#: Transform classes needing an external binary on PATH.
BINARY_CLASSES = {"cmtk", "elastix"}


class TransformsUnavailable(RuntimeError):
    """navis/flybrains not installed, or the bundles are not downloaded."""


@functools.lru_cache(maxsize=1)
def _registry() -> Any:
    try:
        import flybrains  # noqa: F401  -- the import is what registers transforms
        from navis.transforms import registry
    except ImportError as exc:  # pragma: no cover - depends on env
        raise TransformsUnavailable(
            "navis/flybrains are ingest-time dependencies; install the "
            "'ingest' dependency group"
        ) from exc
    return registry


def available() -> bool:
    try:
        _registry()
    except TransformsUnavailable:
        return False
    return True


def template_exists(name: str | None) -> bool:
    if not name:
        return False
    try:
        import flybrains
    except ImportError:  # pragma: no cover - depends on env
        return False
    t = getattr(flybrains, name, None)
    return t is not None and hasattr(t, "label")


def _classes(transforms: list[Any]) -> list[str]:
    return [type(t).__module__.split(".")[-1] for t in transforms]


def describe_path(source: str, target: str, avoid: str | None = None) -> dict:
    """Resolve a bridging path and report what it costs."""
    reg = _registry()
    path, transforms = reg.find_bridging_path(source, target, avoid=avoid)
    classes = _classes(transforms)
    return {
        "path": list(path),
        "classes": classes,
        "n_warps": sum(c in WARP_CLASSES for c in classes),
        "needs_binary": any(c in BINARY_CLASSES for c in classes),
    }


def cmtk_available() -> bool:
    """Are the CMTK binaries on PATH? navis resolves this once at import."""
    try:
        from navis.transforms import cmtk
    except ImportError:  # pragma: no cover - depends on env
        return False
    return bool(getattr(cmtk, "_cmtkbin", None))


def choose_path(source: str, target: str, allow_binary: bool | None = None) -> dict:
    """Pick the route.

    Default (`allow_binary=None`) takes navis's own choice when the required
    binaries are present, because its weighting minimizes WARPS and is
    therefore an accuracy heuristic -- overriding it can make results worse.

    When a binary-dependent edge is unusable, fall back to a binary-free route.
    If that route ties on warp count the substitution is free (measured: it
    ties for hemibrain <-> male CNS). If it costs extra warps we still take it,
    since the alternative is no result at all, but mark it `degraded` so the
    provenance records the loss.
    """
    if allow_binary is None:
        allow_binary = cmtk_available()

    best = describe_path(source, target)
    best["overridden"] = False
    best["degraded"] = False
    if allow_binary or not best["needs_binary"]:
        return best

    try:
        alt = describe_path(source, target, avoid="CMTK")
    except Exception:  # noqa: BLE001 - no binary-free route exists at all
        best["degraded"] = True
        return best
    if alt["needs_binary"]:
        best["degraded"] = True
        return best
    alt["overridden"] = True
    alt["degraded"] = alt["n_warps"] > best["n_warps"]
    alt["extra_warps"] = alt["n_warps"] - best["n_warps"]
    return alt


def bridge(
    points_um: np.ndarray,
    source: str,
    target: str,
    allow_binary: bool | None = None,
) -> tuple[np.ndarray, dict]:
    """Transform (n, 3) points between template spaces.

    Points go in and come out in the *native units of each template*, so the
    caller is responsible for unit handling; see resolve.py.
    """
    import navis

    info = choose_path(source, target, allow_binary=allow_binary)
    pts = np.asarray(points_um, dtype=np.float64)
    kwargs = {"verbose": False, "affine_fallback": True}
    if info.get("overridden"):
        # navis picks the route itself, so steer it by excluding the edge.
        kwargs["avoid"] = "CMTK"
    out = np.asarray(
        navis.xform_brain(pts, source=source, target=target, **kwargs),
        dtype=np.float64,
    )

    # Dense offset fields cover only the imaged volume and return NaN outside
    # it -- the FlyWire<->FAFB field does this for a handful of vertices on a
    # neuropil shell. A NaN vertex destroys a mesh, so those points keep their
    # input coordinates. That is defensible only because the transform being
    # skipped is sub-micron here; the count and fraction are recorded so a
    # large one is visible rather than absorbed.
    bad = ~np.isfinite(out).all(axis=1)
    info["n_nonfinite_filled"] = int(bad.sum())
    info["frac_nonfinite_filled"] = float(bad.mean()) if len(bad) else 0.0
    if bad.any():
        out[bad] = pts[bad]

    # navis may route differently from describe_path -- importing fafbseg
    # registers extra edges -- so record what was actually available.
    return out, info


def has_mirror_registration(template: str) -> bool:
    """True if an explicit mirror registration exists for this template.

    When False, navis.mirror_brain still succeeds -- it falls back to a
    reflection derived from the template bounding box. That is fine for a
    symmetric whole-brain template and WRONG for a half-brain like hemibrain,
    where it is not a midline mirror. It returns plausible, confident, wrong
    geometry rather than raising, which is why resolve() mirrors before
    bridging and the validation harness asserts the ordering.
    """
    reg = _registry()
    s = reg.summary()
    if not len(s) or "type" not in s.columns:
        return False
    return template in set(s[s["type"] == "mirror"]["source"].astype(str))


def mirror(points: np.ndarray, template: str) -> np.ndarray:
    import navis

    return np.asarray(
        navis.mirror_brain(np.asarray(points, dtype=np.float64), template=template),
        dtype=np.float64,
    )


def tool_versions() -> dict[str, str]:
    """Versions that must invalidate a cache when they change."""
    out: dict[str, str] = {}
    for mod in ("navis", "flybrains"):
        try:
            out[mod] = __import__(mod).__version__
        except Exception:  # noqa: BLE001 - absent is a valid answer
            out[mod] = "absent"
    from .. import __version__

    out["lobemap"] = __version__
    return out
