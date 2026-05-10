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
BENTON_COLUMNS = [
    "glomerulus",
    "receptor_benton_2025",
    "sensillum_benton_2025",
    "neuron_name_benton_2025",
    "essential_coreceptor_benton_2025",
    "key_agonists_benton_2025",
    "sensory_scene_benton_2025",
]
XLSX_NS = {
    "a": "http://schemas.openxmlformats.org/spreadsheetml/2006/main",
    "r": "http://schemas.openxmlformats.org/officeDocument/2006/relationships",
    "rel": "http://schemas.openxmlformats.org/package/2006/relationships",
}

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
    "VM7v (1)": ["VM7v"],
    "VP1": ["VP1d", "VP1l", "VP1m"],
    "VP1+VM6": ["VP1", "VM6"],
}
CANONICAL_NAME_OVERRIDES = {"VM7v (1)"}


def clean(value: object) -> str:
    if value is None or pd.isna(value):
        return ""
    text = str(value).strip()
    return "" if text in {"nan", "NaN", "?", "None"} else text


def combine(values: list[object], *, case_insensitive: bool = False) -> str:
    seen: list[str] = []
    seen_keys: set[str] = set()
    for value in values:
        text = clean(value)
        if not text:
            continue
        for part in re.split(r"\s*;\s*", text):
            part = part.strip()
            key = part.casefold() if case_insensitive else part
            if part and key not in seen_keys:
                seen.append(part)
                seen_keys.add(key)
    return "; ".join(seen)


def combine_sensilla(values: list[object]) -> str:
    return combine(values, case_insensitive=True)


def split_values(value: object) -> list[str]:
    text = clean(value)
    if not text:
        return []
    return [part.strip() for part in re.split(r"\s*;\s*", text) if part.strip()]


def yes_variable(value: object) -> bool:
    return clean(value).lower() in {"yes", "variable"}


def positive_or_yes(value: object) -> bool:
    return clean(value).lower() in {"positive", "yes", "variable"}


def door_receptors(rows: pd.DataFrame) -> list[str]:
    if rows.empty:
        return []
    values = []
    for row in rows.to_dict("records"):
        values.append(clean(row.get("Ors")) or clean(row.get("receptor")))
    return values


def organ_from_sensillum(value: object) -> str:
    text = clean(value).lower()
    if not text:
        return ""
    if text.startswith("pb"):
        return "maxillary palp"
    if text.startswith("arista"):
        return "arista"
    if text.startswith(("ab", "ac", "ai", "at", "sac")):
        return "antenna"
    if "sacculus" in text:
        return "antenna"
    return ""


def organ_from_door_type(value: object) -> str:
    text = clean(value).lower()
    if not text:
        return ""
    if "maxillary palp" in text:
        return "maxillary palp"
    if text.startswith("antennal"):
        return "antenna"
    if "sacculus" in text:
        return "antenna"
    return organ_from_sensillum(text)


def organs_from_values(values: list[object]) -> str:
    organs: list[str] = []
    for value in values:
        for part in split_values(value):
            organ = organ_from_sensillum(part)
            if organ:
                organs.append(organ)
    return combine(organs)


def door_organs(rows: pd.DataFrame) -> str:
    if rows.empty:
        return ""
    organs = []
    for row in rows.to_dict("records"):
        organs.append(organ_from_door_type(row.get("sensillum.type")))
        organs.append(organ_from_sensillum(row.get("sensillum")))
    return combine(organs)


def read_grabe_pn_expression() -> pd.DataFrame:
    path = ROOT / "grabe-2015/data/source/grabe_2015_pn_expression.csv"
    if not path.exists():
        return pd.DataFrame()
    return pd.read_csv(path).fillna("").replace(r"^\s+$", "", regex=True)


def read_grabe_sensory_line_expression() -> pd.DataFrame:
    path = ROOT / "grabe-2015/data/source/grabe_2015_sensory_line_expression.csv"
    if not path.exists():
        return pd.DataFrame()
    return pd.read_csv(path).fillna("").replace(r"^\s+$", "", regex=True)


def column_index(cell_ref: str) -> int:
    letters = "".join(ch for ch in cell_ref if ch.isalpha())
    index = 0
    for letter in letters:
        index = index * 26 + ord(letter.upper()) - ord("A") + 1
    return index - 1


def parse_xlsx_number(text: str) -> object:
    value = float(text)
    return int(value) if value.is_integer() else value


def read_xlsx_first_sheet(path: Path) -> list[list[object]]:
    with ZipFile(path) as archive:
        shared_strings: list[str] = []
        if "xl/sharedStrings.xml" in archive.namelist():
            shared_root = ET.fromstring(archive.read("xl/sharedStrings.xml"))
            for item in shared_root.findall(".//a:si", XLSX_NS):
                shared_strings.append(
                    "".join(node.text or "" for node in item.findall(".//a:t", XLSX_NS))
                )

        workbook = ET.fromstring(archive.read("xl/workbook.xml"))
        sheet = workbook.find(".//a:sheets/a:sheet", XLSX_NS)
        if sheet is None:
            raise ValueError(f"No worksheet found in {path}")
        rel_id = sheet.attrib[f"{{{XLSX_NS['r']}}}id"]

        rels = ET.fromstring(archive.read("xl/_rels/workbook.xml.rels"))
        target = None
        for rel in rels.findall("./rel:Relationship", XLSX_NS):
            if rel.attrib["Id"] == rel_id:
                target = rel.attrib["Target"]
                break
        if target is None:
            raise ValueError(f"No worksheet relationship found in {path}")

        sheet_path = "xl/" + target.lstrip("/")
        sheet_root = ET.fromstring(archive.read(sheet_path))

    rows: list[list[object]] = []
    for row_node in sheet_root.findall(".//a:sheetData/a:row", XLSX_NS):
        row_index = int(row_node.attrib["r"]) - 1
        while len(rows) <= row_index:
            rows.append([])
        row = rows[row_index]
        for cell in row_node.findall("./a:c", XLSX_NS):
            cell_ref = cell.attrib["r"]
            col_index = column_index(cell_ref)
            while len(row) <= col_index:
                row.append("")

            cell_type = cell.attrib.get("t")
            if cell_type == "s":
                value_node = cell.find("./a:v", XLSX_NS)
                value = shared_strings[int(value_node.text)] if value_node is not None else ""
            elif cell_type == "inlineStr":
                value = "".join(node.text or "" for node in cell.findall(".//a:t", XLSX_NS))
            else:
                value_node = cell.find("./a:v", XLSX_NS)
                value = parse_xlsx_number(value_node.text) if value_node is not None else ""
            row[col_index] = value
    return rows


def numeric(value: object) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def cell(row: list[object], index: int) -> object:
    return row[index] if index < len(row) else ""


def read_benton_table() -> pd.DataFrame:
    path = ROOT / "benton-2025/data/source/44319_2025_476_MOESM2_ESM.xlsx"
    if not path.exists():
        return pd.DataFrame(columns=BENTON_COLUMNS)

    rows = []
    for row in read_xlsx_first_sheet(path)[7:]:
        if not numeric(cell(row, 0)):
            continue
        rows.append(
            {
                "glomerulus": clean(cell(row, 3)),
                "receptor_benton_2025": clean(cell(row, 2)),
                "sensillum_benton_2025": clean(cell(row, 1)),
                "neuron_name_benton_2025": clean(cell(row, 6)),
                "essential_coreceptor_benton_2025": clean(cell(row, 15)),
                "key_agonists_benton_2025": clean(cell(row, 17)),
                "sensory_scene_benton_2025": clean(cell(row, 18)),
            }
        )
    return pd.DataFrame(rows, columns=BENTON_COLUMNS).fillna("").replace(
        r"^\s+$", "", regex=True
    )


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
        "benton_2025": set(read_benton_table()["glomerulus"]),
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
    if name in CANONICAL_NAME_OVERRIDES:
        return [value for value in NAME_ALIASES[name] if value in canonical_names]
    if name in canonical_names:
        return [name]
    if name in NAME_ALIASES:
        return [value for value in NAME_ALIASES[name] if value in canonical_names]
    return []


def sensory_lines(row: dict[str, str]) -> str:
    lines: list[str] = []
    if positive_or_yes(row.get("orco_gal4_grabe_2015")):
        lines.append("Orco-GAL4")
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


def mapped_rows(
    table: pd.DataFrame,
    source_column: str,
    canonical: str,
    canonical_names: set[str],
) -> pd.DataFrame:
    if table.empty:
        return table
    mask = [
        canonical in direct_or_alias(str(value), canonical_names)
        for value in table[source_column]
    ]
    return table[mask]


def pn_lines(rows: pd.DataFrame) -> str:
    lines = []
    if not rows.empty and (rows["gh146_gal4"] == "positive").any():
        lines.append("GH146-GAL4")
    if not rows.empty and (rows["chat_gal4"] == "positive").any():
        lines.append("ChAT-GAL4")
    return "; ".join(lines)


def pn_line_source(rows: pd.DataFrame) -> str:
    sources = []
    if not rows.empty and (rows["gh146_gal4"] == "positive").any():
        sources.append("Grabe 2015 Table S1")
    if not rows.empty and (rows["chat_gal4"] == "positive").any():
        sources.append("Grabe 2015 Table S2")
    return "; ".join(sources)


def main() -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)

    sources = source_names()
    canonical_names = sorted(
        (
            set(sources["hemibrain"])
            | set(sources["flywire"])
            | set(sources["grabe_2015"])
            | set(sources["potter_task_2022"])
            | set(sources["benton_2025"])
        )
        - CANONICAL_NAME_OVERRIDES
    )

    door = pd.read_csv(ROOT / "door/data/source/door_mappings.csv").fillna("")
    scenes = pd.read_csv(ROOT / "hemibrain/data/source/odour_scenes.csv").fillna("")
    vfb = pd.read_csv(ROOT / "hemibrain/data/source/vfb_glomerulus_terms.csv").fillna("")
    benton = read_benton_table().fillna("")
    potter = read_potter_table().fillna("")
    grabe_pn = read_grabe_pn_expression()
    grabe_sensory_lines = read_grabe_sensory_line_expression()

    rows: list[dict[str, str]] = []
    for canonical in canonical_names:
        door_rows = door[door["glomerulus"] == canonical]
        scene_rows = scenes[scenes["glomerulus"] == canonical]
        vfb_rows = vfb[vfb["glomerulus"] == canonical]
        benton_rows = mapped_rows(benton, "glomerulus", canonical, set(canonical_names))
        potter_rows = mapped_rows(potter, "Glomerulus", canonical, set(canonical_names))
        pn_rows = mapped_rows(grabe_pn, "glomerulus", canonical, set(canonical_names))
        grabe_sensory_rows = mapped_rows(
            grabe_sensory_lines, "glomerulus", canonical, set(canonical_names)
        )

        row = {
            "canonical_glomerulus": canonical,
            "receptor_consensus": combine(
                list(potter_rows.get("Tuning Receptor(s)", []))
                + list(scene_rows.get("receptor", []))
                + door_receptors(door_rows)
            ),
            "receptor_benton_2025": combine(list(benton_rows.get("receptor_benton_2025", []))),
            "receptor_potter_task_2022": combine(list(potter_rows.get("Tuning Receptor(s)", []))),
            "receptor_odour_scenes": combine(list(scene_rows.get("receptor", []))),
            "receptor_door": combine(door_receptors(door_rows)),
            "sensillum_consensus": combine_sensilla(
                list(potter_rows.get("Sensillum", []))
                + list(scene_rows.get("sensillum", []))
                + list(door_rows.get("sensillum", []))
            ),
            "sensory_organ_consensus": combine(
                [
                    organs_from_values(list(benton_rows.get("sensillum_benton_2025", []))),
                    organs_from_values(list(potter_rows.get("Sensillum", []))),
                    organs_from_values(list(scene_rows.get("sensillum", []))),
                    door_organs(door_rows),
                ]
            ),
            "sensillum_benton_2025": combine_sensilla(
                list(benton_rows.get("sensillum_benton_2025", []))
            ),
            "sensory_organ_benton_2025": organs_from_values(
                list(benton_rows.get("sensillum_benton_2025", []))
            ),
            "sensillum_potter_task_2022": combine_sensilla(list(potter_rows.get("Sensillum", []))),
            "sensillum_odour_scenes": combine_sensilla(list(scene_rows.get("sensillum", []))),
            "sensillum_door": combine_sensilla(list(door_rows.get("sensillum", []))),
            "sensory_organ_door": door_organs(door_rows),
            "neuron_name_benton_2025": combine(
                list(benton_rows.get("neuron_name_benton_2025", []))
            ),
            "essential_coreceptor_benton_2025": combine(
                list(benton_rows.get("essential_coreceptor_benton_2025", []))
            ),
            "co_receptor_door": combine(list(door_rows.get("co.receptor", []))),
            "orco_gal4_grabe_2015": combine(list(grabe_sensory_rows.get("orco_gal4", []))),
            "orco_t2a_qf2": combine(list(potter_rows.get("Orco-T2A-QF2", []))),
            "ir8a_t2a_qf2": combine(list(potter_rows.get("Ir8a-T2A-QF2", []))),
            "ir76b_t2a_qf2": combine(list(potter_rows.get("Ir76b-T2A-QF2", []))),
            "ir25a_t2a_qf2": combine(list(potter_rows.get("Ir25a-T2A-QF2", []))),
            "key_agonists_benton_2025": combine(
                list(benton_rows.get("key_agonists_benton_2025", []))
            ),
            "sensory_scene_benton_2025": combine(
                list(benton_rows.get("sensory_scene_benton_2025", []))
            ),
            "key_ligand": combine(list(scene_rows.get("key_ligand", []))),
            "odour_scene": combine(list(scene_rows.get("odour_scene", []))),
            "valence": combine(list(scene_rows.get("valence", []))),
            "fbbt_id": combine(list(vfb_rows.get("fbbt_id", []))),
            "vfb_name": combine(list(vfb_rows.get("vfb_name", []))),
            "vfb_synonyms": combine(list(vfb_rows.get("synonyms", []))),
            "projection_neuron_lines": pn_lines(pn_rows),
            "projection_neuron_line_source": pn_line_source(pn_rows),
            "gh146_gal4": combine(list(pn_rows.get("gh146_gal4", []))),
            "gh146_pn_female": combine(list(pn_rows.get("gh146_pn_female", []))),
            "gh146_pn_male": combine(list(pn_rows.get("gh146_pn_male", []))),
            "chat_gal4": combine(list(pn_rows.get("chat_gal4", []))),
            "chat_soma_count": combine(list(pn_rows.get("chat_soma_count", []))),
            "chat_adpn": combine(list(pn_rows.get("chat_adpn", []))),
            "chat_lpn": combine(list(pn_rows.get("chat_lpn", []))),
            "chat_vpn": combine(list(pn_rows.get("chat_vpn", []))),
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
