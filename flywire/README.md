# FlyWire

FlyWire antennal-lobe glomerulus surfaces exported from `hemibrainr`.

Run:

```bash
./lobemap --atlas flywire
```

Source data used by the viewer lives in `data/source/` and should be tracked in
git. Fast cache files are written to `data/derived/` and ignored by git.

Rebuild cache files from the repo root:

```bash
uv run python scripts/regenerate_visual_data.py
```

Primary source:

Schlegel P, et al. `hemibrainr`: code for working with FlyWire and hemibrain
data.
