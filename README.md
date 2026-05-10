# lobemap

lobemap is a small napari viewer for Drosophila antennal lobe atlases.

https://github.com/user-attachments/assets/2b9711c9-3246-49c4-946b-a29fad0fce52

https://github.com/user-attachments/assets/d83978bd-f2de-48fe-9f0d-6aff19e3b663

It lets you:

- switch between atlases
- slice through 3D volumes
- show and hide glomeruli
- see glomerulus names, receptors, and sensilla
- compare reference maps and tables from different sources

## Reference Table

The [reference table](reference-tables/glomerulus_ground_truth.csv) is a
cross-dataset index for glomeruli, receptors, sensilla, ligands, valence,
driver lines, VFB IDs, and atlas coverage.

| Glomerulus | Receptors | Sensillum | Key ligand | Valence | Lines |
| --- | --- | --- | --- | --- | --- |
| D | Or69aA, Or69aB | Ab9A | linalool | aversive | GH146-GAL4; ChAT-GAL4 |
| DA1 | Or67d | At1A | cis-vaccenyl acetate | mating/aggression | GH146-GAL4; ChAT-GAL4 |
| DA2 | Or56a, Or33a | Ab4B | geosmin | aversive | GH146-GAL4; ChAT-GAL4 |

[Open the full table](reference-tables/glomerulus_ground_truth.csv) or the
[name reconciliation table](reference-tables/glomerulus_name_reconciliation.csv).

## Requirements

- `uv`
- A desktop environment that can open napari / Qt windows

Python and package dependencies are managed by `uv` from `pyproject.toml`.

## Start

```bash
uv sync
./lobemap
```

Choose an atlas from the dropdown in napari.

You can also open one atlas directly:

```bash
./lobemap --atlas flywire
```

## Generated Data

Some viewers use derived cache files under `data/derived/` for fast startup and
slicing. They are not tracked in git. Rebuild all generated visual data with:

```bash
uv run python scripts/regenerate_visual_data.py
```

The rebuild script uses the tracked source files and needs `pdftoppm` to render
the Potter Task 2022 PDF preview.

## What Is Included

- 3D atlas viewers for Grabe 2015, Bates Schlegel 2020, hemibrain, FlyWire,
  JRC2018Unisex, and Benton 2025
- 2D reference viewers for DoOR and Potter Task 2022
- Virtual Fly Brain and BANC resource lookup
- reference tables for glomerulus names, receptors, sensilla, and direct line labels

## Demo

![Grabe 2015 atlas in lobemap](docs/images/demo-grabe-2015.png)

![Bates Schlegel 2020 atlas in lobemap](docs/images/demo-bates-schlegel-2020.png)

![Hemibrain atlas in lobemap](docs/images/demo-hemibrain.png)

![DoOR 2D map in lobemap](docs/images/demo-door-2d.png)

## Data And Credit

This repo combines source data from several papers and public resources. Source
files are kept in `data/source/` folders when they can be shared. Paper PDFs are
not tracked in git.

See [docs/data-sources.md](docs/data-sources.md) for the source list and links.

## More

- [How to use lobemap](docs/usage.md)
- [Data sources](docs/data-sources.md)
- [Reference tables](reference-tables/README.md)

## License

Code in this repo is released under the MIT License. Data files keep the rights
and citation requirements of their original sources.
