# lobemap

lobemap is a small napari viewer for Drosophila antennal lobe atlases.

It lets you:

- switch between atlases
- slice through 3D volumes
- show and hide glomeruli
- see glomerulus names, receptors, and sensilla
- compare reference maps and tables from different sources

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

## What Is Included

- 3D atlas viewers for Grabe 2015, Bates Schlegel 2020, hemibrain, and FlyWire
- 2D reference viewers for DoOR and Potter Task 2022
- Virtual Fly Brain term lookup
- reference tables for glomerulus names, receptors, sensilla, and direct line labels

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
