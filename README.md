# lobemap

lobemap is a small napari viewer for Drosophila antennal lobe atlases.

<video src="docs/images/demo.mp4" controls width="100%"></video>

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
