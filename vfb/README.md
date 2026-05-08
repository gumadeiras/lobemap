# VFB

Virtual Fly Brain reference terms for antennal-lobe glomeruli.

Run:

```bash
./lobemap --atlas vfb
```

The viewer shows the tracked `data/source/vfb_glomerulus_terms.csv` table as a
searchable napari reference panel with term names, FBbt IDs, definitions,
synonyms, and VFB links.

Refresh the source table:

```bash
uv run python vfb/scripts/download_fbbt_glomerulus_terms.py
```
