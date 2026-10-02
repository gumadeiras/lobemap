"""Declarative registry: TOML on disk -> model objects, with validation.

Each validator here corresponds to a bug that is otherwise invisible at
runtime -- a mesh drawn confidently in the wrong place, or a compartment
silently dropped.

Compartments are NOT hand-written in TOML. They come from the mesh container's
own name list, so `published_name` stays authoritative from the source and a
60-glomerulus atlas needs no hand maintenance.
"""

from __future__ import annotations

import tomllib
from dataclasses import replace
from pathlib import Path

from .imagefmt import Volume
from .meshfmt import MeshSet
from .model import (
    Asset,
    Atlas,
    Compartment,
    Derivation,
    Provenance,
    Space,
    rotation_axis_vector,
)
from .names import Nomenclature, parse_roi


def default_data_root(root: Path) -> Path:
    """Where asset files live.

    The metadata (TOMLs, nomenclature) is small and ships with the package;
    the data is gigabytes and is fetched. In a source checkout they sit
    together, so `registry/data` wins when it exists. Installed from a wheel
    there is no such directory and the data belongs in a user cache, which is
    also the only writable location `lobemap fetch` can rely on.
    """
    import os

    override = os.environ.get("LOBEMAP_DATA")
    if override:
        return Path(override)
    local = Path(root) / "data"
    if local.exists():
        return local
    from platformdirs import user_cache_dir

    return Path(user_cache_dir("lobemap")) / "data"


#: The atlas whose published names ARE the canonical vocabulary. Every other
#: atlas maps onto it. Chosen because Benton 2025 is the current revision and
#: carries the post-Schlegel-2021 naming; recorded here rather than left
#: implicit so `validate` can catch the vocabulary drifting away from it.
#: No single atlas defines the vocabulary any more; see `Registry.vocabulary`.
#: Retained as documentation of where FAFB's names come from.
FAFB_NOMENCLATURE_SOURCE = "benton2025"


def _rot(body):
    """The `anatomical_rotation` table, with a vector axis made hashable."""
    table = body.get("anatomical_rotation") or {}
    axis = table.get("axis")
    if axis is not None and not isinstance(axis, str):
        try:
            axis = tuple(float(v) for v in axis)
        except (TypeError, ValueError):
            pass                 # let `validate` report it
    return {"axis": axis, "degrees": table.get("degrees")}


class RegistryError(ValueError):
    """A registry inconsistency. Always names the offending record."""


def _read_toml(path: Path) -> dict:
    with path.open("rb") as fh:
        return tomllib.load(fh)


class Registry:
    def __init__(self, root: str | Path, data_root: str | Path | None = None) -> None:
        self.root = Path(root)
        self.data_root = (
            Path(data_root) if data_root is not None
            else default_data_root(self.root)
        )
        self.spaces: dict[str, Space] = {}
        self.assets: dict[str, Asset] = {}
        self.atlases: dict[str, Atlas] = {}
        self.names = Nomenclature()
        self._meshes: dict[str, MeshSet] = {}
        self._volumes: dict[str, Volume] = {}

    # -- loading ---------------------------------------------------------

    def asset_path(self, rel: str | Path) -> Path:
        """Resolve a registry-relative path, splitting data from metadata."""
        text = str(rel).replace("\\", "/")
        prefix = "data/"
        if text.startswith(prefix):
            return self.data_root / text[len(prefix):]
        return self.root / text

    @classmethod
    def load(cls, root: str | Path, validate: bool = True,
             data_root: str | Path | None = None) -> Registry:
        r = cls(root, data_root=data_root)
        r._load_spaces()
        r._load_assets()
        r.names = Nomenclature.load(r.root / "nomenclature.csv")
        r._load_atlases()
        if validate:
            r.validate()
        return r

    def _load_spaces(self) -> None:
        path = self.root / "spaces.toml"
        if not path.exists():
            return
        for sid, body in _read_toml(path).items():
            tmpl = body.get("flybrains_template") or None
            self.spaces[sid] = Space(
                id=sid,
                title=body.get("title", sid),
                units=body.get("units", "um"),
                flybrains_template=tmpl,
                lateral_convention=body.get("lateral_convention", "biological"),
                anatomical_rotation_axis=_rot(body).get("axis"),
                anatomical_rotation_deg=_rot(body).get("degrees"),
                primary_atlas=body.get("primary_atlas"),
                notes=body.get("notes", ""),
            )

    def _load_assets(self) -> None:
        path = self.root / "assets.toml"
        if not path.exists():
            return
        for aid, body in _read_toml(path).items():
            src = body.get("source", {})
            deriv = None
            if "derivation" in src:
                d = src["derivation"]
                deriv = Derivation(
                    recipe=d.get("recipe", "unknown"),
                    inputs=tuple(d.get("inputs", ())),
                    params=d.get("params", {}),
                    tool_versions=d.get("tool_versions", {}),
                )
            self.assets[aid] = Asset(
                id=aid,
                role=body["role"],
                space=body["space"],
                kind=body.get("kind", "meshset"),
                path=self.asset_path(body["path"]),
                side=body.get("side"),
                colormap=body.get("colormap"),
                display=dict(body.get("display", {})),
                source=Provenance(
                    doi=src.get("doi"),
                    url=src.get("url"),
                    license=src.get("license"),
                    checksum=src.get("checksum"),
                    derivation=deriv,
                ),
            )

    def _load_atlases(self) -> None:
        d = self.root / "atlases"
        if not d.is_dir():
            return
        for path in sorted(d.glob("*.toml")):
            body = _read_toml(path)
            aid = body.get("id", path.stem)
            atlas = Atlas(
                id=aid,
                title=body.get("title", aid),
                native_space=body["native_space"],
                asset=body["asset"],
                citation=body.get("citation", ""),
                doi=body.get("doi", ""),
                parent=body.get("parent") or None,
            )
            self.atlases[aid] = replace(
                atlas, compartments=self._compartments_for(atlas)
            )

    def _compartments_for(self, atlas: Atlas) -> tuple[Compartment, ...]:
        """Derive compartments from the mesh container's own name list."""
        asset = self.assets.get(atlas.asset)
        if asset is None or asset.kind != "meshset" or not asset.path.exists():
            return ()
        ms = self.mesh(atlas.asset)
        # Laterality may be declared on the asset rather than in each name,
        # and BOTH sources are biological. A side suffix is biological
        # wherever it comes from -- FlyWire's neuropil annotations are the
        # post-correction ones, so `AL_L` really is the left lobe -- and
        # `Asset.side` is documented as biological too. Converting the asset
        # default to apparent, as an earlier version did, made FAFB mix the
        # two conventions in one space: Benton's glomeruli reported side R
        # while sitting inside the shell named `AL_L`.
        default_side = asset.side if asset.side in ("L", "R") else None
        out: list[Compartment] = []
        for i, name in enumerate(ms.names):
            _glom, side = parse_roi(name)
            side = side or default_side
            corr = self.names.resolve(atlas.id, name)
            out.append(
                Compartment(
                    local_id=i,
                    published_name=name,
                    side=side,
                    canonical=corr.canonical if corr else (),
                    relation=corr.relation if corr else "absent",
                )
            )
        return tuple(out)

    # -- access ----------------------------------------------------------

    def mesh(self, asset_id: str) -> MeshSet:
        if asset_id not in self._meshes:
            asset = self.assets[asset_id]
            self._meshes[asset_id] = MeshSet.load(asset.path)
        return self._meshes[asset_id]

    def volume(self, asset_id: str) -> Volume:
        if asset_id not in self._volumes:
            asset = self.assets[asset_id]
            if asset.kind not in ("image", "labels"):
                raise ValueError(
                    f"asset {asset_id!r} is {asset.kind}, not an image or labels"
                )
            self._volumes[asset_id] = Volume.load(asset.path)
        return self._volumes[asset_id]

    def atlases_in_space(self, space: str) -> list[Atlas]:
        return [a for a in self.atlases.values() if a.native_space == space]

    def primary_atlas(self, space: str) -> Atlas | None:
        """The atlas a space opens with, or None if it has none at all.

        Declared in `spaces.toml`, because with several atlases it is a
        curatorial choice rather than something to derive -- JRCFIB2018F
        has three and opens on the neuPrint one. Undeclared, the single
        atlas of a one-atlas space is unambiguous, and beyond that the
        first in registry order keeps the viewer deterministic while
        `validate` reports the omission.
        """
        here = self.atlases_in_space(space)
        if not here:
            return None
        declared = self.spaces[space].primary_atlas if space in self.spaces else None
        if declared:
            for atlas in here:
                if atlas.id == declared:
                    return atlas
        return here[0]

    def assets_in_space(self, space: str, role: str | None = None) -> list[Asset]:
        return [
            a
            for a in self.assets.values()
            if a.space == space and (role is None or a.role == role)
        ]

    # -- validation ------------------------------------------------------

    def vocabulary(self, space_id: str) -> list[str]:
        """The glomerulus names defined in one space, in a stable order.

        There is no longer a single canonical vocabulary across the registry.
        An atlas belongs to exactly one space and is only ever shown there,
        so names only have to agree WITHIN a space -- which is the only
        place two atlases can be superimposed.

        That is more than tidiness. A single global vocabulary had to pick a
        winner and restate every other atlas in its terms, which is awkward
        precisely where the communities disagree: the Schlegel 2021 rename
        chain (VC3l to VC3, VC3m to VC5, VC5 to VM6) meant the hemibrain
        atlases were described in FAFB's names. Per space, each uses its own.

        In practice only the hemibrain has several atlases to reconcile.
        Every other space has one, and its vocabulary is that atlas's names
        with prefixes and sides stripped.
        """
        names: set[str] = set()
        for atlas in self.atlases_in_space(space_id):
            for compartment in atlas.compartments:
                names.update(compartment.canonical)
        return sorted(names)

    def validate(self, strict_templates: bool = False) -> list[str]:
        """Raise on structural errors; return non-fatal warnings.

        `strict_templates` additionally requires each non-island space to name
        a template flybrains actually knows -- off by default so the registry
        stays loadable without the ingest dependencies installed.
        """
        problems: list[str] = []
        warnings: list[str] = []

        for a in self.assets.values():
            if a.space not in self.spaces:
                problems.append(f"asset {a.id!r}: unknown space {a.space!r}")
            if not a.path.exists():
                warnings.append(f"asset {a.id!r}: missing file {a.path}")

        for at in self.atlases.values():
            if at.native_space not in self.spaces:
                problems.append(
                    f"atlas {at.id!r}: unknown native_space {at.native_space!r}"
                )
            if at.asset not in self.assets:
                problems.append(f"atlas {at.id!r}: unknown asset {at.asset!r}")
            elif self.assets[at.asset].space != at.native_space:
                problems.append(
                    f"atlas {at.id!r}: asset {at.asset!r} is in space "
                    f"{self.assets[at.asset].space!r}, not {at.native_space!r}"
                )
            if at.parent and at.parent not in self.atlases:
                problems.append(f"atlas {at.id!r}: unknown parent {at.parent!r}")

            seen: set[str] = set()
            for c in at.compartments:
                if c.published_name in seen:
                    problems.append(
                        f"atlas {at.id!r}: duplicate published_name "
                        f"{c.published_name!r}"
                    )
                seen.add(c.published_name)
                if c.relation == "absent" and not c.canonical:
                    warnings.append(
                        f"atlas {at.id!r}: {c.published_name!r} has no canonical name"
                    )

        # No global vocabulary to validate against one atlas. Each space has
        # its own, derived from the atlases native to it.
        for space_id in self.spaces:
            if self.atlases_in_space(space_id) and not self.vocabulary(space_id):
                warnings.append(
                    f"space {space_id!r} has atlases but no glomerulus names; "
                    f"check nomenclature.csv"
                )

        for s in self.spaces.values():
            axis = s.anatomical_rotation_axis
            degrees = s.anatomical_rotation_deg
            if (axis is None) != (degrees is None):
                problems.append(
                    f"space {s.id!r}: anatomical_rotation needs both axis "
                    f"and degrees -- an axis with no angle names no rotation"
                )
            elif axis is not None:
                if rotation_axis_vector(s) is None:
                    problems.append(
                        f"space {s.id!r}: anatomical_rotation axis {axis!r} "
                        f"is not a signed array axis or a non-zero vector"
                    )
                try:
                    float(degrees)
                except (TypeError, ValueError):
                    problems.append(
                        f"space {s.id!r}: anatomical_rotation degrees "
                        f"{degrees!r} is not a number"
                    )
            elif self.atlases_in_space(s.id):
                warnings.append(
                    f"space {s.id!r} declares no anatomical_rotation, so the "
                    f"viewer cannot orient it or name its axes"
                )
            here = [a.id for a in self.atlases_in_space(s.id)]
            if s.primary_atlas and s.primary_atlas not in here:
                problems.append(
                    f"space {s.id!r}: primary_atlas {s.primary_atlas!r} is "
                    f"not one of its atlases ({', '.join(here) or 'none'})"
                )
            # Silence here would mean picking one arbitrarily and opening
            # with a different atlas than the curator intended.
            if not s.primary_atlas and len(here) > 1:
                problems.append(
                    f"space {s.id!r}: {len(here)} atlases and no "
                    f"primary_atlas, so which one opens is arbitrary"
                )

        if strict_templates:
            from . import spaces as sp

            if sp.available():
                for s in self.spaces.values():
                    if s.flybrains_template and not sp.template_exists(
                        s.flybrains_template
                    ):
                        problems.append(
                            f"space {s.id!r}: flybrains has no template "
                            f"{s.flybrains_template!r}"
                        )

        if problems:
            raise RegistryError(
                "registry validation failed:\n  - " + "\n  - ".join(problems)
            )
        return warnings
