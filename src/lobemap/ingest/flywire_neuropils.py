"""FlyWire neuropil meshes, bridged into FAFB14.

`fafbseg.flywire.get_neuropil_volumes` serves 78 named neuropils -- AL_L,
AL_R, AME_L, ... -- originally built for JFRC2 and transformed by the fafbseg
authors into FlyWire (FAFB14.1) space. **There is no whole-brain entry**, so a
brain outline here is the union of the neuropils rather than a separate mesh;
that is also why every neuropil is kept as its own compartment instead of
being merged into one shell. It costs nothing and makes each one toggleable.

FlyWire space is FAFB v14.1, so the meshes need the FLYWIRE -> FAFB14 bridge.
It routes FLYWIRE -> FLYWIREraw -> FAFB14raw -> FAFB14 with **no warps** --
two affines and the dedicated offset field -- but that field covers only the
imaged volume and returns NaN outside it. Those vertices keep their input
coordinates, and the count is recorded in the Derivation, because a silently
dropped vertex destroys a mesh while a sub-micron uncorrected one does not.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime

import numpy as np

from ..core.meshfmt import MeshSet

#: FlyWire volumes are served in nanometers.
SOURCE_SCALE_TO_UM = 1e-3


@dataclass
class NeuropilIngestResult:
    meshset: MeshSet
    skipped: list[str]
    repair: object | None = None


def available() -> list[str]:
    """Every neuropil name fafbseg will serve."""
    from fafbseg import flywire

    return [str(n) for n in flywire.get_neuropil_volumes(None)]


def ingest(
    names: list[str] | None = None,
    repair: bool = True,
    progress=None,
) -> NeuropilIngestResult:
    """Fetch neuropil meshes and return them as a MeshSet in micrometers.

    `names=None` takes all of them. The result is still in FlyWire space;
    bridging is a separate step so the fetch can be cached and re-bridged
    without another download.
    """
    from fafbseg import flywire

    from ..core.meshrepair import repair_meshset

    wanted = [str(n) for n in (names if names is not None else available())]
    parts: list[tuple[str, np.ndarray, np.ndarray]] = []
    skipped: list[str] = []
    for i, name in enumerate(wanted, start=1):
        try:
            volume = flywire.get_neuropil_volumes(name)
        except Exception as exc:  # noqa: BLE001 - one bad name must not stop it
            skipped.append(f"{name}: {type(exc).__name__}: {exc}")
            continue
        verts = np.asarray(volume.vertices, dtype=np.float64) * SOURCE_SCALE_TO_UM
        faces = np.asarray(volume.faces)
        if len(verts) < 4 or len(faces) < 4:
            skipped.append(f"{name}: degenerate ({len(verts)} verts)")
            continue
        parts.append((name, verts.astype(np.float32), faces))
        if progress is not None:
            progress(i, len(wanted), name, len(verts))

    if not parts:
        raise ValueError("no neuropil volumes were fetched")

    ms = MeshSet.from_parts(
        parts,
        meta={
            "source": "fafbseg.get_neuropil_volumes",
            "source_units": "nm",
            "scale_to_um": SOURCE_SCALE_TO_UM,
            "units": "um",
            "role": "neuropil",
            "source_space": "FLYWIRE",
            "n_requested": len(wanted),
            "n_skipped": len(skipped),
            "retrieved": datetime.now(UTC).date().isoformat(),
        },
    )
    report = None
    if repair:
        ms, report = repair_meshset(ms)
    return NeuropilIngestResult(ms, skipped, report)


def bridge_to_fafb14(meshset: MeshSet) -> MeshSet:
    """FLYWIRE -> FAFB14, recording what the transform did."""
    from ..core.resolve import resolve_meshset

    return resolve_meshset(
        meshset,
        source_space="FLYWIRE",
        target_space="FAFB14",
        source_template="FLYWIRE",
        target_template="FAFB14",
    )


__all__ = ["NeuropilIngestResult", "available", "bridge_to_fafb14", "ingest"]
