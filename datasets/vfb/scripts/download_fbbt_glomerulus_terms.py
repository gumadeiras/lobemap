#!/usr/bin/env python3
from __future__ import annotations

import csv
import urllib.request
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SOURCE_DIR = ROOT / "data" / "source"
FBBT_OBO_URL = "https://purl.obolibrary.org/obo/fbbt.obo"


def parse_glomerulus_terms(text: str) -> list[dict[str, str]]:
    rows = []
    for block in text.split("\n[Term]\n"):
        if "name: antennal lobe glomerulus" not in block:
            continue

        term_id = ""
        name = ""
        definition = ""
        synonyms = []
        obsolete = False
        for line in block.splitlines():
            if line.startswith("id: "):
                term_id = line[4:].replace(":", "_")
            elif line.startswith("name: "):
                name = line[6:]
            elif line.startswith("def: "):
                definition = line[5:]
            elif line.startswith("synonym: "):
                synonyms.append(line[9:])
            elif line == "is_obsolete: true":
                obsolete = True

        if obsolete or not name.startswith("antennal lobe glomerulus"):
            continue

        glomerulus = name.removeprefix("antennal lobe glomerulus").strip()
        if not glomerulus:
            continue
        rows.append(
            {
                "glomerulus": glomerulus,
                "fbbt_id": term_id,
                "vfb_name": name,
                "definition": definition,
                "synonyms": " | ".join(synonyms),
                "vfb_url": (
                    "https://www.virtualflybrain.org/term/"
                    f"{name.replace(' ', '-').lower()}-{term_id.lower()}/"
                ),
            }
        )

    return sorted(rows, key=lambda row: row["glomerulus"])


def main() -> None:
    SOURCE_DIR.mkdir(parents=True, exist_ok=True)
    with urllib.request.urlopen(FBBT_OBO_URL, timeout=60) as response:
        text = response.read().decode("utf-8", errors="replace")

    rows = parse_glomerulus_terms(text)
    output = SOURCE_DIR / "vfb_glomerulus_terms.csv"
    with output.open("w", newline="") as f:
        writer = csv.DictWriter(
            f,
            fieldnames=[
                "glomerulus",
                "fbbt_id",
                "vfb_name",
                "definition",
                "synonyms",
                "vfb_url",
            ],
        )
        writer.writeheader()
        writer.writerows(rows)


if __name__ == "__main__":
    main()
