# lobemap

Tools and resources for working with Drosophila antennal lobe atlases.

## Napari Viewer

Run the main atlas viewer:

```bash
./lobemap
```

Use the atlas selector in the napari dock to switch between available atlases.
The selected atlas loads as soon as the dropdown changes.

The dropdown shows datasets that can be opened directly in napari. Grabe,
Bates Schlegel, Hemibrain, and FlyWire are sliceable 3D atlases. DoOR and
Potter Task 2022 are 2D reference maps. The other folders are documents,
metadata, or download records.

## Data

All source data needed by the viewers lives in `data/source/` folders and should
be tracked in git when redistribution is allowed. Paper PDFs are local-only and
ignored by git; their source links live in `paper_pdf_sources.csv`. Generated
cache files live in `data/derived/` and should not be tracked. Rebuild them with:

```bash
uv run python scripts/regenerate_visual_data.py
```

## Grabe 2015 atlas

The Grabe in vivo antennal lobe atlas lives in `grabe-2015/`.

## Bates Schlegel 2020 atlas

The Bates/Schlegel Current Biology supplemental web atlas lives in
`bates-schlegel-2020/`.

## hemibrain / FlyWire atlas

Natverse hemibrain and FlyWire antennal-lobe glomerulus surfaces live in
separate folders:

- `hemibrain/`
- `flywire/`

Run:

```bash
./lobemap --atlas hemibrain
./lobemap --atlas flywire
```

Coordinate validation tables are tracked under `hemibrain/data/validation/` and
`flywire/data/validation/`. They include source axis mappings and rendered
label extents.

## Reference resources

- `flywire-codex/`: FlyWire v783 release metadata and proofread root IDs.
- `benton-2025/`: review resource for the Drosophila olfactory system.
- `potter-task-2022/`: chemosensory co-receptor AL reference map and source
  files.
- `vfb/`: Virtual Fly Brain glomerulus term references.
- `reference-tables/`: cross-dataset glomerulus metadata and name
  reconciliation tables.
- `edmond-fibsem/`: DA2/DL5 focused FIB-SEM dataset metadata.
- `laissue-1999/`: historical 3D AL reconstruction paper.
- `comparative-atlases/`: comparative species atlas references.
