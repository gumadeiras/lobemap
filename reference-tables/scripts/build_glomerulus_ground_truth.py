#!/usr/bin/env python3
from __future__ import annotations

import csv
import re
from pathlib import Path
from zipfile import ZipFile
import xml.etree.ElementTree as ET

import pandas as pd


ROOT = Path(__file__).resolve().parents[2]
OUT_DIR = ROOT / "reference-tables"
GROUND_TRUTH_CSV = OUT_DIR / "glomerulus_ground_truth.csv"
NAME_RECONCILIATION_CSV = OUT_DIR / "glomerulus_name_reconciliation.csv"

NON_GLOMERULUS = {"", "?", "Corners", "compartment", "Exterior"}
NAME_ALIASES = {
    "DA4": ["DA4l", "DA4m"],
    "DL2": ["DL2d", "DL2v"],
    "DL2d/v": ["DL2d", "DL2v"],
    "DL2d/v+VC3": ["DL2d", "DL2v", "VC3"],
    "DM5+DM3": ["DM5", "DM3"],
    "DP1": ["DP1l", "DP1m"],
    "VA1": ["VA1d", "VA1v"],
    "VA7": ["VA7l", "VA7m"],
    "VL1+DP1l+VC5": ["VL1", "DP1l", "VC5"],
    "VL1+VM1+VL2p": ["VL1", "VM1", "VL2p"],
    "VL2": ["VL2a", "VL2p"],
    "VM5": ["VM5d", "VM5v"],
    "VM7": ["VM7d", "VM7v"],
    "VP1": ["VP1d", "VP1l", "VP1m"],
}


def clean(value: object) -> str:
    if value is None or pd.isna(value):
        return ""
    text = str(value).strip()
    return "" if text in {"nan", "NaN", "?", "None"} else text


def combine(values: list[object]) -> str:
    seen: list[str] = []
    for value in values:
        text = clean(value)
        if not text:
            continue
        for part in re.split(r"\s*;\s*", text):
            part = part.strip()
            if part and part not in seen:
                seen.append(part)
    return "; ".join(seen)


def yes_variable(value: object) -> bool:
    return clean(value).lower() in {"yes", "variable"}


def door_receptors(rows: pd.DataFrame) -> list[str]:
    if rows.empty:
        return []
    values = []
    for row in rows.to_dict("records"):
        values.append(clean(row.get("Ors")) or clean(row.get("receptor")))
    return values


def read_potter_table() -> pd.DataFrame:
    path = (
        ROOT
        / "potter-task-2022/data/source/Task-Potter-Fly-AL-Summary-Table.docx"
    )
    ns = {"w": "http://schemas.openxmlformats.org/wordprocessingml/2006/main"}
    with ZipFile(path) as archive:
        root = ET.fromstring(archive.read("word/document.xml"))
    table = root.find(".//w:tbl", ns)
    if table is None:
        raise ValueError(f"No table found in {path}")

    rows: list[list[str]] = []
    for table_row in table.findall("./w:tr", ns):
        row: list[str] = []
        for cell in table_row.findall("./w:tc", ns):
            text = "".join(node.text or "" for node in cell.findall(".//w:t", ns))
            row.append(text.strip())
        rows.append(row)
    return pd.DataFrame(rows[1:], columns=rows[0])


def source_names() -> dict[str, set[str]]:
    sources = {
        "grabe_2015": set(
            pd.read_csv(ROOT / "grabe-2015/data/derived/al_atlas_materials.csv")[
                "short_name"
            ]
        ),
        "hemibrain": set(
            pd.read_csv(ROOT / "hemibrain/data/source/hemibrain_al_microns_materials.csv")[
                "name"
            ]
        ),
        "flywire": set(
            pd.read_csv(ROOT / "flywire/data/source/flywire_al_materials.csv")["name"]
        ),
        "door_map": set(
            pd.read_csv(ROOT / "door/data/source/door_al_map_glomeruli.csv")[
                "glomerulus"
            ]
        ),
        "door_mappings": set(
            pd.read_csv(ROOT / "door/data/source/door_mappings.csv")["glomerulus"]
        ),
        "potter_task_2022": set(read_potter_table()["Glomerulus"]),
        "bates_schlegel_2020": set(
            pd.read_csv(ROOT / "hemibrain/data/source/hemibrain_al_microns_materials.csv")[
                "name"
            ]
        ),
    }
    return {
        key: {clean(value) for value in values if clean(value) not in NON_GLOMERULUS}
        for key, values in sources.items()
    }


def direct_or_alias(source_name: str, canonical_names: set[str]) -> list[str]:
    name = clean(source_name)
    if not name or name in NON_GLOMERULUS:
        return []
    if name in canonical_names:
        return [name]
    if name in NAME_ALIASES:
        return [value for value in NAME_ALIASES[name] if value in canonical_names]
    return []


def sensory_lines(row: dict[str, str]) -> str:
    lines: list[str] = []
    if yes_variable(row.get("orco_t2a_qf2")):
        lines.append("Orco-T2A-QF2")
    if yes_variable(row.get("ir8a_t2a_qf2")):
        lines.append("Ir8a-T2A-QF2")
    if yes_variable(row.get("ir76b_t2a_qf2")):
        lines.append("Ir76b-T2A-QF2")
    if yes_variable(row.get("ir25a_t2a_qf2")):
        lines.append("Ir25a-T2A-QF2")

    receptor = row.get("receptor_consensus", "")
    if "Gr21a" in receptor or "Gr63a" in receptor:
        lines.append("Gr21a/Gr63a")
    return "; ".join(dict.fromkeys(lines))


def source_flags(
    canonical: str, sources: dict[str, set[str]], canonical_names: set[str]
) -> dict[str, str]:
    flags: dict[str, str] = {}
    for source, names in sources.items():
        if canonical in names:
            flags[f"present_{source}"] = "direct"
            continue
        aliases = [
            name
            for name in names
            if canonical in direct_or_alias(name, canonical_names)
        ]
        flags[f"present_{source}"] = "alias:" + ";".join(sorted(aliases)) if aliases else ""
    return flags


def main() -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)

    sources = source_names()
    canonical_names = sorted(
        set(sources["hemibrain"])
        | set(sources["flywire"])
        | set(sources["grabe_2015"])
        | set(sources["potter_task_2022"])
    )

    door = pd.read_csv(ROOT / "door/data/source/door_mappings.csv").fillna("")
    scenes = pd.read_csv(ROOT / "hemibrain/data/source/odour_scenes.csv").fillna("")
    vfb = pd.read_csv(ROOT / "hemibrain/data/source/vfb_glomerulus_terms.csv").fillna("")
    potter = read_potter_table().fillna("")

    rows: list[dict[str, str]] = []
    for canonical in canonical_names:
        door_rows = door[door["glomerulus"] == canonical]
        scene_rows = scenes[scenes["glomerulus"] == canonical]
        vfb_rows = vfb[vfb["glomerulus"] == canonical]
        potter_rows = potter[potter["Glomerulus"] == canonical]

        row = {
            "canonical_glomerulus": canonical,
            "receptor_consensus": combine(
                list(potter_rows.get("Tuning Receptor(s)", []))
                + list(scene_rows.get("receptor", []))
                + door_receptors(door_rows)
            ),
            "receptor_potter_task_2022": combine(list(potter_rows.get("Tuning Receptor(s)", []))),
            "receptor_odour_scenes": combine(list(scene_rows.get("receptor", []))),
            "receptor_door": combine(door_receptors(door_rows)),
            "sensillum_consensus": combine(
                list(potter_rows.get("Sensillum", []))
                + list(scene_rows.get("sensillum", []))
                + list(door_rows.get("sensillum", []))
            ),
            "sensillum_potter_task_2022": combine(list(potter_rows.get("Sensillum", []))),
            "sensillum_odour_scenes": combine(list(scene_rows.get("sensillum", []))),
            "sensillum_door": combine(list(door_rows.get("sensillum", []))),
            "co_receptor_door": combine(list(door_rows.get("co.receptor", []))),
            "orco_t2a_qf2": combine(list(potter_rows.get("Orco-T2A-QF2", []))),
            "ir8a_t2a_qf2": combine(list(potter_rows.get("Ir8a-T2A-QF2", []))),
            "ir76b_t2a_qf2": combine(list(potter_rows.get("Ir76b-T2A-QF2", []))),
            "ir25a_t2a_qf2": combine(list(potter_rows.get("Ir25a-T2A-QF2", []))),
            "key_ligand": combine(list(scene_rows.get("key_ligand", []))),
            "odour_scene": combine(list(scene_rows.get("odour_scene", []))),
            "valence": combine(list(scene_rows.get("valence", []))),
            "fbbt_id": combine(list(vfb_rows.get("fbbt_id", []))),
            "vfb_name": combine(list(vfb_rows.get("vfb_name", []))),
            "vfb_synonyms": combine(list(vfb_rows.get("synonyms", []))),
            "projection_neuron_lines": "",
            "projection_neuron_line_source": "",
        }
        row["sensory_neuron_lines"] = sensory_lines(row)
        row.update(source_flags(canonical, sources, set(canonical_names)))
        rows.append(row)

    ground_truth = pd.DataFrame(rows)
    ground_truth.to_csv(GROUND_TRUTH_CSV, index=False, quoting=csv.QUOTE_MINIMAL)

    reconciliation_rows: list[dict[str, str]] = []
    all_source_names = sorted(set().union(*sources.values()))
    canonical_set = set(canonical_names)
    for source_name in all_source_names:
        mapped = direct_or_alias(source_name, canonical_set)
        reconciliation_rows.append(
            {
                "source_name": source_name,
                "canonical_glomerulus": "; ".join(mapped),
                "status": "direct" if mapped == [source_name] else ("alias" if mapped else "needs_review"),
                "source_datasets": "; ".join(
                    source for source, names in sources.items() if source_name in names
                ),
            }
        )
    pd.DataFrame(reconciliation_rows).to_csv(
        NAME_RECONCILIATION_CSV,
        index=False,
        quoting=csv.QUOTE_MINIMAL,
    )


if __name__ == "__main__":
    main()
