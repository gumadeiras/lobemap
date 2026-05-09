#!/usr/bin/env python3
from __future__ import annotations

import csv
import json
from pathlib import Path
from urllib.request import urlopen


WORK_DIR = Path(__file__).resolve().parents[1]
SOURCE_DIR = WORK_DIR / "data/source"
STATE_DIR = SOURCE_DIR / "neuroglancer_states/2026a"
REPO_RAW = "https://raw.githubusercontent.com/jasper-tms/the-BANC-fly-connectome/main"

RESOURCES = [
    {
        "name": "BANC wiki",
        "type": "project page",
        "source": "GitHub wiki",
        "url": "https://github.com/jasper-tms/the-BANC-fly-connectome/wiki",
        "local_file": "",
        "description": "Main BANC project page with data links.",
    },
    {
        "name": "BANC Codex",
        "type": "connectome browser",
        "source": "FlyWire Codex",
        "url": "https://codex.flywire.ai/banc",
        "local_file": "",
        "description": "Browser for public BANC connectome data.",
    },
    {
        "name": "BANC Neuroglancer",
        "type": "viewer",
        "source": "BANC Neuroglancer",
        "url": "https://ng.banc.community/view",
        "local_file": "",
        "description": "Public Neuroglancer view for BANC EM images and segmentation.",
    },
    {
        "name": "BANC data bucket",
        "type": "data files",
        "source": "Google Cloud Storage",
        "url": "https://console.cloud.google.com/storage/browser/lee-lab_brain-and-nerve-cord-fly-connectome",
        "local_file": "",
        "description": "Public bucket for released BANC files.",
    },
    {
        "name": "BANC Dataverse",
        "type": "preprint files",
        "source": "Harvard Dataverse",
        "url": "https://dataverse.harvard.edu/dataset.xhtml?persistentId=doi:10.7910/DVN/8TFGGB",
        "local_file": "",
        "description": "Preprint-related files and metadata.",
    },
    {
        "name": "BANC preprint",
        "type": "paper",
        "source": "bioRxiv",
        "url": "https://www.biorxiv.org/content/10.1101/2025.07.31.667571",
        "local_file": "",
        "description": "Distributed control circuits across a brain-and-cord connectome.",
    },
]

STATES = {
    "Left olfactory": "2026a/left-olfactory",
    "Right olfactory": "2026a/right-olfactory",
}


def download_text(url: str) -> str:
    with urlopen(url, timeout=30) as response:
        return response.read().decode("utf-8")


def write_csv(path: Path, rows: list[dict[str, object]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]), lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)


def state_summary(name: str, state_path: str) -> dict[str, object]:
    raw_url = f"{REPO_RAW}/neuroglancer_states/{state_path}.json"
    text = download_text(raw_url)
    local_file = Path("neuroglancer_states") / f"{state_path}.json"
    output_path = SOURCE_DIR / local_file
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(text, encoding="utf-8")

    state = json.loads(text)
    static_layer = next(
        layer for layer in state.get("layers", []) if layer.get("name") == "BANC static"
    )
    return {
        "name": name,
        "short_url": f"https://ng.banc.community/{state_path}",
        "raw_url": raw_url,
        "local_file": str(local_file),
        "layers": len(state.get("layers", [])),
        "static_segments": len(static_layer.get("segments", [])),
        "position": json.dumps(state.get("position", [])),
        "selected_layer": state.get("selectedLayer", {}).get("layer", ""),
    }


def main() -> None:
    state_rows = [state_summary(name, path) for name, path in STATES.items()]
    resource_rows = [
        *RESOURCES,
        *[
            {
                "name": f"{row['name']} state",
                "type": "neuroglancer state",
                "source": "GitHub neuroglancer state",
                "url": row["short_url"],
                "local_file": row["local_file"],
                "description": f"{row['name']} BANC Neuroglancer state.",
            }
            for row in state_rows
        ],
    ]
    write_csv(SOURCE_DIR / "banc_resources.csv", resource_rows)
    write_csv(SOURCE_DIR / "banc_neuroglancer_states.csv", state_rows)
    print("BANC resources downloaded")


if __name__ == "__main__":
    main()
