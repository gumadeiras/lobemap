# Grabe Data

`source/` contains atlas files used by the napari viewer.

`derived/` contains files generated from source data. These files are ignored by
git. Rebuild them from the repo root with:

```bash
uv run python scripts/regenerate_visual_data.py
```
