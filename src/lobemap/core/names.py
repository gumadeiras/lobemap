"""Nomenclature and cross-atlas correspondence.

This is the load-bearing component: superimposing
atlases is meaningless without an assertion that this VA1v is that VA1v, and the
atlases genuinely disagree on nomenclature.

Correspondence is many-to-many. A single nullable foreign key would silently
mangle exactly the interesting cases (Schlegel S11 splits VM6 three ways
into two).
"""

from __future__ import annotations

import csv
import re
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path

from .model import Relation

#: Trailing laterality, either parenthesised "(R)" or suffixed "_R".
_SIDE_RE = re.compile(r"(?:\((?P<paren>[LR])\)|_(?P<under>[LR]))$")
#: Leading compartment prefix, e.g. "AL-" in "AL-DA1".
_PREFIX_RE = re.compile(r"^AL[-_](?=.)")


def parse_roi(roi: str) -> tuple[str, str | None]:
    """Split a neuPrint-style ROI name into (glomerulus, side).

    The side suffix is stripped FIRST. Doing it the other way round breaks
    "AL_L", where a greedy "AL_" prefix leaves "L" as the name.

    >>> parse_roi("AL-DA1(R)")
    ('DA1', 'R')
    >>> parse_roi("AL-DC3")
    ('DC3', None)
    >>> parse_roi("AL_L")
    ('AL', 'L')
    >>> parse_roi("AL(L)")
    ('AL', 'L')
    """
    text = roi.strip()
    side: str | None = None
    m = _SIDE_RE.search(text)
    if m:
        side = m.group("paren") or m.group("under")
        text = text[: m.start()]
    return _PREFIX_RE.sub("", text).strip() or text.strip(), side


#: Curated tables annotate names in prose: lobemap writes "VM6l*(new)",
#: "VM6m (new)" and "VM6v (VM6)" for the three-way split of VM6. Strip the
#: annotation without losing the name.
_ANNOTATION_RE = re.compile(r"[\s*].*$|\((?![LR]\)).*$")


def clean_reference_name(value: str) -> str:
    """Strip curated-table annotations, keeping any (L)/(R) laterality."""
    return _ANNOTATION_RE.sub("", value.strip()).strip()


def normalize(name: str) -> str:
    """Canonical comparison key: case- and separator-insensitive."""
    return re.sub(r"[\s_\-]+", "", name).upper()


@dataclass(frozen=True)
class Correspondence:
    atlas: str
    published_name: str
    canonical: tuple[str, ...]
    relation: Relation = "exact"


@dataclass(frozen=True)
class AtlasAudit:
    """How one atlas's published names compare with what is recorded."""

    atlas: str
    #: Published by the atlas, with no row in the table.
    missing: tuple[str, ...] = ()
    #: Recorded, but the atlas no longer publishes that name.
    stale: tuple[str, ...] = ()
    #: Rows whose relation is not a plain identity. These are the hand-made
    #: part of the table and cannot be re-derived from the atlases: the
    #: Schlegel rename chain and Grabe's VP1 merge live here.
    curated: tuple[Correspondence, ...] = ()

    @property
    def clean(self) -> bool:
        return not self.missing and not self.stale


def audit_atlas(nomenclature, atlas: str, published_names) -> AtlasAudit:
    """Compare recorded correspondences against what an atlas publishes.

    This reports; it does not decide. A mechanical derivation can only ever
    produce identity relations -- published `AL-DA1(R)` maps to `DA1` -- so
    regenerating the table from the atlases silently replaces every curated
    merge, split and rename with an identity, and the information is simply
    gone. Only the differences are actionable, and only some of them
    automatically.
    """
    recorded = {c.published_name: c for c in nomenclature.for_atlas(atlas)}
    names = list(published_names)
    missing = tuple(n for n in names if n not in recorded)
    stale = tuple(sorted(set(recorded) - set(names)))
    curated = tuple(
        c for c in recorded.values() if c.relation != "exact"
    )
    return AtlasAudit(atlas, missing, stale, curated)


class Nomenclature:
    """The canonical glomerulus set plus per-atlas correspondences."""

    def __init__(
        self,
        canonical: list[str] | None = None,
        correspondences: list[Correspondence] | None = None,
    ) -> None:
        self.canonical: list[str] = list(canonical or [])
        self._by_norm = {normalize(c): c for c in self.canonical}
        self._corr: dict[str, list[Correspondence]] = defaultdict(list)
        for c in correspondences or []:
            self._corr[c.atlas].append(c)

    # -- lookup ----------------------------------------------------------

    def resolve(self, atlas: str, published_name: str) -> Correspondence | None:
        for c in self._corr.get(atlas, ()):
            if c.published_name == published_name:
                return c
        # Fall back to an identity match against the canonical set.
        hit = self._by_norm.get(normalize(published_name))
        if hit is not None:
            return Correspondence(atlas, published_name, (hit,), "exact")
        return None

    def atlases(self) -> list[str]:
        return sorted(self._corr)

    def for_atlas(self, atlas: str) -> list[Correspondence]:
        return list(self._corr.get(atlas, ()))

    def is_canonical(self, name: str) -> bool:
        return normalize(name) in self._by_norm

    # -- derivation ------------------------------------------------------

    def add_missing(self, atlas: str, published_names) -> list[str]:
        """Record only the names that have no row yet, as identities.

        The only way to extend the table. There was also an
        `add_from_atlas` that assumed it was building from nothing and
        emitted an identity row for every name it was given, including over
        a curated merge. It is gone: on an empty table this does the same
        thing, and on a populated one it does the right thing.
        """
        recorded = {c.published_name for c in self._corr.get(atlas, ())}
        added = []
        for name in published_names:
            if name in recorded:
                continue
            glom, _side = parse_roi(name)
            key = normalize(glom)
            if key not in self._by_norm:
                self._by_norm[key] = glom
                self.canonical.append(glom)
            self._corr[atlas].append(
                Correspondence(atlas, name, (self._by_norm[key],), "exact")
            )
            added.append(name)
        self.canonical.sort()
        return added

    def drop(self, atlas: str, published_names) -> int:
        """Remove rows for names an atlas no longer publishes."""
        gone = set(published_names)
        keep = [c for c in self._corr.get(atlas, ()) if c.published_name not in gone]
        removed = len(self._corr.get(atlas, ())) - len(keep)
        self._corr[atlas] = keep
        return removed

    # -- cross-check -----------------------------------------------------

    def cross_check(self, reference_names: list[str]) -> dict[str, list[str]]:
        """Compare against a curated list (e.g. lobemap's tables).

        Returns {'only_here': [...], 'only_reference': [...]}. Per the plan,
        disagreements are findings to resolve, never silently overwritten.
        """
        ref = {normalize(n): n for n in reference_names}
        only_here = [self._by_norm[k] for k in self._by_norm if k not in ref]
        only_ref = [ref[k] for k in ref if k not in self._by_norm]
        return {
            "only_here": sorted(only_here),
            "only_reference": sorted(only_ref),
        }

    # -- io --------------------------------------------------------------

    def save(self, path: str | Path) -> Path:
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        rows = [
            {
                "atlas": c.atlas,
                "published_name": c.published_name,
                "canonical": ";".join(c.canonical),
                "relation": c.relation,
            }
            for atlas in sorted(self._corr)
            for c in self._corr[atlas]
        ]
        with path.open("w", newline="", encoding="utf-8") as fh:
            w = csv.DictWriter(
                fh, fieldnames=["atlas", "published_name", "canonical", "relation"]
            )
            w.writeheader()
            w.writerows(rows)
        return path

    @classmethod
    def load(cls, path: str | Path) -> Nomenclature:
        path = Path(path)
        if not path.exists():
            return cls()
        corr: list[Correspondence] = []
        canonical: set[str] = set()
        with path.open(newline="", encoding="utf-8") as fh:
            for row in csv.DictReader(fh):
                names = tuple(
                    n for n in (row.get("canonical") or "").split(";") if n
                )
                canonical.update(names)
                corr.append(
                    Correspondence(
                        atlas=row["atlas"],
                        published_name=row["published_name"],
                        canonical=names,
                        relation=row.get("relation") or "exact",  # type: ignore[arg-type]
                    )
                )
        return cls(sorted(canonical), corr)
