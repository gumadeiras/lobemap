"""Curated per-glomerulus annotation: receptors, sensilla, sensory organ.

`registry/reference/glomerulus_ground_truth.csv` is the upstream reference
table. Its cells pool several publications into one string, so the same
receptor arrives spelled several ways at once:

    Or69aA, Or69aB; Or69aA/B; Or69a

which is three sources agreeing, not five receptors. This module turns that
into `Or69aA; Or69aB` -- the distinct things, one separator, no restatement.

The rules, in the order they apply:

1. `(co Ir8a)` is dropped. A co-receptor is not the receptor, and it has its
   own column.
2. `(subset Ir75c)` becomes a term `Ir75c (subset)`. It names a real
   population, so it survives; the qualifier follows the name.
3. Any other parenthetical stays attached to its term. `Ai1A (Ab6A)` is a
   synonym for one sensillum, not two of them.
4. `;` and `/` separate terms everywhere. `,` and `+` separate them only in
   the gene-list columns: in the sensillum and organ columns they belong to
   the name, as in `Sacculus, Chamber III` and `Sacculus, Chambers I + II`.
5. `Or65a+b+c` and `Or69aA/B` are shorthand: a bare suffix inherits the stem
   of the term before it, so those are three and two receptors. `Rh50/Amt`
   and `Gr21a/Gr63a` are not shorthand -- both sides name a gene -- so the
   separator reading wins.
6. A term that is a prefix of another is dropped: `Or69a` says less than
   `Or69aA`, and `ab9` less than `Ab9A`. The `(subset)` form from rule 2 is
   the exception, in reverse: `Ir75c (subset)` says less than `Ir75c`, so
   `Ir75c; Ir75a/b (subset Ir75c)` keeps `Ir75c`.
7. `?` is dropped, and what remains is deduplicated case-insensitively and
   sorted.
"""

from __future__ import annotations

import csv
import re
from pathlib import Path

#: Column in the reference table holding the glomerulus name.
KEY = "canonical_glomerulus"

#: Panel column -> (source column, whether `,` separates terms).
#: Comma splitting is right for gene lists and wrong for `Sacculus,
#: Chamber III`, which is one sensillum with a comma in its name.
FIELDS: dict[str, tuple[str, bool]] = {
    "receptor(s)": ("receptor_consensus", True),
    "sensillum": ("sensillum_consensus", False),
    "ALRN": ("neuron_name_benton_2025", True),
    "organ": ("sensory_organ_consensus", False),
    "co-receptor(s)": ("essential_coreceptor_benton_2025", True),
}

#: Cells that mean "nothing recorded" rather than a value.
_EMPTY = {"", "-", "na", "n/a", "none", "unk", "unknown", "?"}

_PAREN = re.compile(r"\s*\(([^)]*)\)")
_STEM = re.compile(r"^(.*?)([A-Za-z])$")
_LEADING_ALPHA = re.compile(r"^([A-Za-z]+)")


def _pull_parentheticals(text: str) -> tuple[str, list[str]]:
    """Strip `(...)` groups, returning the text and any extra terms."""
    extra: list[str] = []
    keep_spans: list[str] = []
    last = 0
    for m in _PAREN.finditer(text):
        inner = m.group(1).strip()
        low = inner.lower()
        if low.startswith(("co ", "co-")):
            pass                                    # a co-receptor: not this
        elif low.startswith("subset"):
            name = inner.split(None, 1)[1].strip() if " " in inner else ""
            if name:
                extra.append(f"{name} (subset)")
        else:
            continue                                # leave it in place
        keep_spans.append(text[last:m.start()])
        last = m.end()
    keep_spans.append(text[last:])
    return "".join(keep_spans), extra


def _expand(chunk: str, sep: str) -> list[str]:
    """Split on `sep`, expanding shorthand suffixes against the first stem."""
    parts = [p.strip() for p in chunk.split(sep) if p.strip()]
    if len(parts) < 2:
        return parts
    head = parts[0]
    out = [head]
    for part in parts[1:]:
        if re.fullmatch(r"[A-Za-z]", part):
            # `Or69aA/B`: drop the stem's own trailing letter, append this.
            m = _STEM.match(head)
            out.append(f"{m.group(1)}{part}" if m else part)
        elif re.fullmatch(r"\d+[A-Za-z]*", part):
            # `Or47a+33b`: only the alphabetic prefix carries over.
            m = _LEADING_ALPHA.match(head)
            out.append(f"{m.group(1)}{part}" if m else part)
        else:
            out.append(part)                        # two real names
    return out


#: The qualifier rule 2 writes. Lowercase, as the keys it is compared with.
_SUBSET = " (subset)"


def _redundant(term: str, others) -> bool:
    """Whether another term in the cell already says this one (rule 6).

    All lowercase. A prefix says less than what extends it, except that a
    term is never dropped for its own `(subset)` form: the subset is the
    one that says less.
    """
    if term.endswith(_SUBSET) and term[: -len(_SUBSET)] in others:
        return True
    return any(
        other != term and other.startswith(term) and other != term + _SUBSET
        for other in others
    )


def terms(value: str, *, split_commas: bool = True) -> list[str]:
    """The distinct terms in one reference cell, normalized and sorted.

    `split_commas` marks a gene-list column, where `,` and `+` separate
    terms; in a name column they are part of the name.
    """
    if value is None or value.strip().lower() in _EMPTY:
        return []
    text, extra = _pull_parentheticals(value)
    found: list[str] = []
    for chunk in text.split(";"):
        pieces = [chunk]
        if split_commas:
            pieces = [p for c in pieces for p in c.split(",")]
            pieces = [p for c in pieces for p in _expand(c, "+")]
        pieces = [p for c in pieces for p in _expand(c, "/")]
        found.extend(p.replace("?", "").strip() for p in pieces)
    found.extend(extra)
    found = [f for f in found if f and f.lower() not in _EMPTY]

    # Deduplicate case-insensitively, keeping the first spelling seen, then
    # drop anything another term already says.
    seen: dict[str, str] = {}
    for f in found:
        seen.setdefault(f.lower(), f)
    kept = [v for k, v in seen.items() if not _redundant(k, seen)]
    return sorted(kept, key=str.lower)


def normalize(value: str, *, split_commas: bool = True) -> str:
    return "; ".join(terms(value, split_commas=split_commas))


def default_path(registry_root) -> Path:
    return Path(registry_root) / "reference" / "glomerulus_ground_truth.csv"


#: Key in `load`'s output holding the row's Virtual Fly Brain term page.
VFB = "vfb"

#: The term page URL, in the form the old viewer and its term table used.
VFB_TERM_URL = "https://www.virtualflybrain.org/term/{slug}-{term}/"


def vfb_url(vfb_name: str | None, fbbt_id: str | None) -> str:
    """Term page for one FBbt term, or "" when the row names none.

    `antennal lobe glomerulus DA1` and `FBbt_00003932` give
    `.../term/antennal-lobe-glomerulus-da1-fbbt_00003932/`.
    """
    name, term = (vfb_name or "").strip(), (fbbt_id or "").strip()
    if not name or not term:
        return ""
    return VFB_TERM_URL.format(
        slug=name.replace(" ", "-").lower(), term=term.lower()
    )


def _rows(registry_root):
    path = default_path(registry_root)
    if not path.exists():
        return []
    with path.open(encoding="utf-8-sig", newline="") as fh:
        return [row for row in csv.DictReader(fh)
                if (row.get(KEY) or "").strip()]


def load(registry_root) -> dict[str, dict[str, str]]:
    """Glomerulus name -> {panel column: normalized value}.

    Keyed on the name as the table spells it AND on a lowercase form, so an
    atlas naming a glomerulus `DL3` or `dl3` finds the same row. Missing
    file is not an error: the columns simply come back empty.

    Each value also carries two keys that are not columns: `KEY`, the name
    as the table spells it, which is what `lines` is keyed on, and `VFB`,
    the row's term page or "".
    """
    out: dict[str, dict[str, str]] = {}
    for row in _rows(registry_root):
        name = row[KEY].strip()
        props = {
            label: normalize(row.get(src, ""), split_commas=commas)
            for label, (src, commas) in FIELDS.items()
        }
        props[KEY] = name
        props[VFB] = vfb_url(row.get("vfb_name"), row.get("fbbt_id"))
        out[name] = props
        out.setdefault(name.lower(), props)
    return out


#: Columns listing the driver lines that label a glomerulus: the sensory
#: neuron lines, then the projection neuron lines.
LINE_COLUMNS = ("sensory_neuron_lines", "projection_neuron_lines")

#: Presets that are the glomeruli two lines have in common.
INTERSECTIONS = (("Orco-GAL4 & GH146-GAL4", ("Orco-GAL4", "GH146-GAL4")),)


def lines(registry_root) -> dict[str, frozenset[str]]:
    """Driver line -> the glomeruli it labels, by the table's own names.

    The same presets the old viewer offered: one per line named in
    `LINE_COLUMNS`, split on `;` only -- `Gr21a/Gr63a` is one line -- in the
    order the table first names them, then each of `INTERSECTIONS` whose
    lines are both present.
    """
    rows = _rows(registry_root)
    out: dict[str, set[str]] = {}
    for column in LINE_COLUMNS:
        for row in rows:
            for line in (row.get(column) or "").split(";"):
                if line.strip():
                    out.setdefault(line.strip(), set()).add(row[KEY].strip())
    for label, names in INTERSECTIONS:
        sets = [out.get(name, set()) for name in names]
        if all(sets):
            out[label] = set.intersection(*sets)
    return {line: frozenset(names) for line, names in out.items()}


__all__ = [
    "FIELDS",
    "INTERSECTIONS",
    "KEY",
    "LINE_COLUMNS",
    "VFB",
    "default_path",
    "lines",
    "load",
    "normalize",
    "terms",
    "vfb_url",
]
