"""What each row of the panel says, before any widget shows it.

One row per compartment of a mesh: a glomerulus of an atlas, or a neuropil
of a reference set. Every tab of a kind builds its rows here, so a column,
a detail and the search mean the same thing in all of them -- which they
did not while each was worked out inside the table: the name kept its side
in two atlases and dropped it in two others, and the search matched columns
the tab had hidden.

Nothing here imports Qt.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from ..core import reference
from ..core.names import parse_roi

#: Shown wherever a value is not recorded, with `MISSING_TIP` as its tooltip.
MISSING = "—"
MISSING_TIP = "Not recorded"

SIDES = {"L": "Left", "R": "Right"}
#: A neuropil with no side suffix is one structure across the midline.
MIDLINE = "Midline"
#: Rows of one name sort left, right, midline, then unrecorded.
_SIDE_ORDER = {"Left": 0, "Right": 1, MIDLINE: 2, MISSING: 3}

#: Written after a glomerulus name the atlas does not share with its space's
#: standard vocabulary: a rename or a split. Its tooltip says which.
RENAMED_MARK = "*"

STANDARD_NAME = "Standard name"
#: The details of a glomerulus, in the order they are listed.
GLOMERULUS_DETAILS = (STANDARD_NAME, *reference.FIELDS)
FULL_NAME = "Full name"
SOURCE = "Source"
#: The details of a neuropil, in the order they are listed.
NEUROPIL_DETAILS = (FULL_NAME, SOURCE)

RECEPTOR = "Receptor"

#: How a relation reads in a sentence; see `core.model.Relation`.
_RELATION_WORDS = {"renamed": "renamed", "split": "split", "merge": "merged"}


def natural_key(text: str):
    """DA10 after DA9, not between DA1 and DA2."""
    return [
        int(part) if part.isdigit() else part.lower()
        for part in re.split(r"(\d+)", text)
    ]


def _value(text: str | None) -> str:
    return (text or "").strip() or MISSING


@dataclass(frozen=True)
class Row:
    """One compartment as the panel shows it."""

    #: The compartment's index in its mesh, which a sorted table's row
    #: number is not.
    index: int
    #: The name as the atlas publishes it, without its side, and with any
    #: doubt about it: `VP2 (VM6?)`.
    name: str
    #: The name exactly as published: `VP2(L)`, `AL_R`.
    published: str
    #: `Left`, `Right`, `Midline` or `MISSING`.
    side: str
    #: Field -> value, in the order of the kind's details; `MISSING` where
    #: nothing is recorded.
    details: dict[str, str] = field(default_factory=dict)
    #: Why this glomerulus's identity is in doubt, or "".
    doubt: str = ""
    #: What the standard name is, when it is not the published one, or "".
    standard_note: str = ""
    #: The reference table's own name for this glomerulus, or "": what the
    #: driver lines are keyed on.
    reference_name: str = ""
    #: Its Virtual Fly Brain term page, or "".
    vfb: str = ""
    #: The lowercase text the search looks in.
    search: tuple[str, ...] = ()

    @property
    def shown_name(self) -> str:
        """The name with the mark that says its standard name differs."""
        return self.name + (RENAMED_MARK if self.standard_note else "")

    @property
    def name_tip(self) -> str:
        return "\n\n".join(t for t in (self.doubt, self.standard_note) if t)

    def sort_key(self):
        """Natural order on the name, then the side."""
        return natural_key(self.name), _SIDE_ORDER.get(self.side, len(_SIDE_ORDER))

    def matches(self, needle: str) -> bool:
        """Whether a search for `needle` keeps this row. Empty keeps all."""
        needle = needle.strip().lower()
        return not needle or any(needle in text for text in self.search)


def _searchable(*values: str) -> tuple[str, ...]:
    return tuple(v.lower() for v in values if v and v != MISSING)


def _joined(annotation, comp, published: str) -> dict:
    """The reference row of a glomerulus: by its standard names, then as
    published. The standard name is what the reference table uses, and it
    is what makes the same glomerulus match across atlases."""
    names = list(comp.canonical) if comp and comp.canonical else []
    names.append(published)
    for n in names:
        hit = annotation.get(n) or annotation.get(n.lower())
        if hit:
            return hit
    return {}


def _standard_note(bare: str, comp) -> str:
    """The sentence for a glomerulus named differently from its space's
    standard vocabulary, or "".

    Compared on the BARE name: `DA1(R)` and `DA1` are one glomerulus written
    two ways. A glomerulus with no standard name is a gap, not a difference.
    """
    if comp is None or not comp.canonical or tuple(comp.canonical) == (bare,):
        return ""
    how = _RELATION_WORDS.get(comp.relation)
    standard = ", ".join(comp.canonical)
    return (f"This atlas calls it {bare}; its standard name is {standard}"
            + (f" ({how})." if how else "."))


def hover_line(row: Row, title: str) -> str:
    """What the status bar says under the cursor: 'VA3 (left) — Benton 2025'.

    A doubt joins the side, 'VP2 (VM6?, left)', and a neuropil gives its
    full name: 'AL, antennal lobe (right) — Neuropils (FlyWire)'.
    """
    name = row.name
    full = row.details.get(FULL_NAME, MISSING)
    if full != MISSING:
        name = f"{name}, {full}"
    if row.side != MISSING:
        side = row.side.lower()
        # A name ends in a parenthesis only with a doubt: its side went.
        name = f"{name[:-1]}, {side})" if name.endswith(")") else f"{name} ({side})"
    return f"{name} — {title}"


def glomerulus_rows(names, compartments, annotation) -> list[Row]:
    """The rows of an atlas tab, one per mesh name, in mesh order.

    `annotation` is `core.reference.load`'s table; a glomerulus it does not
    list shows `MISSING` in each of its fields.
    """
    by_index = {c.local_id: c for c in compartments or ()}
    rows = []
    for index, published in enumerate(names):
        comp = by_index.get(index)
        bare, suffix = parse_roi(published)
        doubt_note = comp.uncertain if comp else ""
        name = f"{bare} ({doubt_note})" if doubt_note else bare
        side = (comp.side if comp else None) or suffix
        props = _joined(annotation, comp, published)
        standard = ", ".join(comp.canonical) if comp and comp.canonical else ""
        details = {STANDARD_NAME: _value(standard)}
        details.update({key: _value(props.get(key)) for key in reference.FIELDS})
        rows.append(Row(
            index=index,
            name=name,
            published=published,
            side=SIDES.get(side, MISSING),
            details=details,
            doubt=comp.uncertain_reason if comp else "",
            standard_note=_standard_note(bare, comp),
            reference_name=props.get(reference.KEY, ""),
            vfb=props.get(reference.VFB, ""),
            search=_searchable(name, published, *details.values()),
        ))
    return rows


def neuropil_rows(names, full_names) -> list[Row]:
    """The rows of a neuropil tab, one per mesh name, in mesh order.

    `full_names` is `core.reference.neuropil_names`'s table: the name
    without its side -> (full name, the source that gives it).
    """
    rows = []
    for index, published in enumerate(names):
        bare, side = parse_roi(published)
        full, source = full_names.get(bare, ("", ""))
        details = {FULL_NAME: _value(full), SOURCE: _value(source)}
        rows.append(Row(
            index=index,
            name=bare,
            published=published,
            side=SIDES.get(side, MIDLINE),
            details=details,
            search=_searchable(bare, published, details[FULL_NAME]),
        ))
    return rows


__all__ = [
    "FULL_NAME",
    "GLOMERULUS_DETAILS",
    "MIDLINE",
    "MISSING",
    "MISSING_TIP",
    "NEUROPIL_DETAILS",
    "RECEPTOR",
    "RENAMED_MARK",
    "SIDES",
    "SOURCE",
    "STANDARD_NAME",
    "Row",
    "glomerulus_rows",
    "hover_line",
    "natural_key",
    "neuropil_rows",
]
