# lobemap

A [napari](https://napari.org) viewer for *Drosophila* antennal lobe
(AL) glomerular atlases.

Several groups have published glomerular parcellations of the AL, each
from a different volume and each using its own names. lobemap puts them
in one viewer so they can be looked at side by side: as 3D meshes, or as
exact cross-sections on a slice through the underlying image.

The viewer opens a **coordinate space** — FAFB, the hemibrain, the male
CNS, or the Grabe light-microscopy template. A space holds every atlas
native to it at once, together with that space's neuropil geometry and
reference image, so the parcellations of one volume can be drawn over each
other.

## Installing

Python 3.11 or 3.12. From PyPI:

```bash
pip install lobemap
lobemap fetch
```

`fetch` downloads the data, which is published separately rather than shipped in the package. An installed lobemap keeps it in the user cache directory (`~/Library/Caches/lobemap/data` on macOS, `~/.cache/lobemap/data` on Linux); `fetch` prints the location. Set `LOBEMAP_DATA`, or pass `--data-root`, to keep it somewhere else.

From a source checkout, with [uv](https://docs.astral.sh/uv/), from the repository root:

```bash
uv sync
uv run lobemap fetch
```

A checkout keeps its data in `registry/data`.

Viewing needs nothing more. Rebuilding data from source (`build`, `stain`, `ingest`) and moving geometry between spaces (`bridge`) need about 100 more packages, which `pip install "lobemap[ingest]"` adds. A checkout's `uv sync` installs them too; `uv sync --no-group ingest` leaves them out.

A full `fetch` is 2.5 GB and gets everything: the atlases, the neuropil sets, the
Grabe confocal stack, and the three virtual stains described under
[Data](#data) below. The stains are 2.4 GB of that, so if you would
rather not wait for them:

```bash
uv run lobemap fetch --nostains
```

leaves them out and takes 76 MB. Every space still opens; the three EM
spaces just open without their reference image, and running the full
`fetch` later fills them in.

## Quick start

```bash
uv run lobemap
```

That opens FAFB. To list the spaces and what each will put on screen:

```bash
uv run lobemap spaces
```

```bash
uv run lobemap view JRCFIB2018F
```

`lobemap --help` lists the rest, including tools for checking the data
against its own geometry (`check`), comparing atlases (`reconcile`) and
moving geometry between spaces (`bridge`).

`lobemap` is installed into the project's virtual environment, so `uv run`
is the simplest way to reach it. Activating the environment
(`.venv/Scripts/Activate.ps1` on Windows, `source .venv/bin/activate`
elsewhere) lets you drop the prefix. The commands work from any directory: a checkout reads its own `registry/`, and a package installed from PyPI carries a copy of the registry metadata. `--registry` or `LOBEMAP_REGISTRY` points at a different one.

## What is included

| space | atlas | glomeruli |
|---|---|---|
| FAFB14 (FlyWire) | [Benton 2025](https://doi.org/10.1038/s44319-025-00476-8) (Dataset EV2) | 58 |
| JRCFIB2018F (hemibrain) | neuPrint [hemibrain](https://doi.org/10.7554/eLife.57443) | 58 + 19 |
| JRCFIB2018F | [Schlegel 2021](https://doi.org/10.7554/eLife.66018) S11, from receptor neurons | 59 |
| JRCFIB2018F | [Schlegel 2021](https://doi.org/10.7554/eLife.66018) S12, from projection neurons | 58 |
| JRCFIB2022M (male CNS) | neuPrint [male CNS](https://doi.org/10.1016/j.cell.2026.08.015) | 58 + 58 |
| GRABE | [Grabe 2015](https://doi.org/10.1002/cne.23697) | 54 + 54 |

Which one to reach for depends on what you are comparing against:

- **GRABE** is the only atlas built from an intact, living brain, imaged
  in vivo rather than dissected and fixed. Its glomerular shapes and the
  geometry of its reference stack (`elav-nSyb::DsRed`, not nc82) are
  therefore the closest match to in vivo imaging data. It is also the
  oldest of the six and predates revisions to the fine structure of a few
  glomeruli.
- **FAFB14** (FlyWire) is a complete female brain, dissected and
  chemically fixed. Benton 2025
  ([based on Bates 2020](https://doi.org/10.1016/j.cub.2020.06.042))
  annotates its left AL comprehensively and to current nomenclature; the
  right AL is unannotated.
- **JRCFIB2018F** (hemibrain) is a dissected, fixed female. Three
  independent annotations cover its right AL, and one of them also
  covers a subset of the left. The right AL is partially truncated even
  so: some of its 58 glomeruli extend past the imaged volume. All of the
  hemibrain atlases have a few glomeruli with holes or multiple connected
  components.
- **JRCFIB2022M** (male CNS) has complete, current annotations for both
  hemispheres, though the meshes are of variable quality, with several
  glomeruli having holes or multiple pieces. The JRCFIB2022M specimen is
  male rather than female, which may subtly affect the shape of a few
  glomeruli, and is dissected and fixed like the other EM volumes.

Each space also carries its brain neuropils and one reference image. For
Grabe, which is light microscopy, that is its own confocal stack. For the
three EM spaces it is a **virtual neuropil stain**: the density of
predicted presynapses, binned and blurred into something that reads like an
nc82 antibody stain, computed natively in each volume rather than warped in
from light microscopy.

Glomerulus names are scoped to a space, so switching space may change both
the list of glomeruli and their colors.

## Data

None of the data is committed. All fourteen artifacts are published as
release assets — 2.51 GB, of which the three virtual stains are 2.44 GB.
`registry/manifest.toml` records where they are fetched from and the
sha256 of every one, and `lobemap fetch` checks each download against
it; a file that does not match is discarded rather than kept. Naming an
asset fetches just that one:

```bash
uv run lobemap fetch --asset hemibrain_stain
```

`lobemap view` fetches anything a scene needs and cannot find, so the
explicit `fetch` above is a convenience rather than a requirement. It
never fetches a stain, though: after `fetch --nostains` the EM spaces
open without a backdrop until you ask for one. A stain that *is* on disk
is always shown.

You can also rebuild from source instead of downloading:

```bash
uv run lobemap build --list
```

```bash
uv run lobemap build hemibrain_stain
```

Each stain needs several gigabytes downloaded from the published synapse
releases, about 40 GB of scratch space, and a long run, so `build --all`
skips them and they have to be asked for by name. Everything else is
derived from sources that either ship in `registry/sources/` or are downloaded
automatically; `registry/recipes.toml` records exactly how.

A rebuilt asset is not byte-identical to the original — every pipeline
stamps the date it ran — but its *content* hash is, and the build prints it.
`lobemap pack` writes the upload-ready copies if you are republishing.

## In the viewer

- **3D** draws the meshes. **2D** draws exact mesh–plane contours, computed
  by intersection rather than rasterized, so they stay sharp at any zoom.
- Each glomerulus keeps one color across the atlases of its space, in 3D,
  in 2D and on its slice label.
- The right-hand panel has a tab per atlas: a checkbox to show each
  glomerulus, and a second to write its name on the slice.
- The control at the bottom right switches between spaces without
  restarting.
- A space with several atlases opens on one of them — `primary_atlas` in
  `registry/spaces.toml` — with the rest loaded and switched off. The
  panel's tabs turn the others on.
- A space's reference image — the virtual stain, or the Grabe confocal
  channel — is shown in grayscale whenever it has been fetched. `--show`
  turns on a layer that is off, by asset id or by role, for example
  `--show neuropil`.
- In 3D the corner carries two axis indicators: one for the array axes,
  labeled `x`, `y`, `z`, and one for the anatomical axes. Each
  anatomical arrow is labeled with the pole it points at, one from each
  of `A`/`P`, `D`/`V` and `R`/`L`. The labels differ between spaces:
  which pole of each axis is picked so that no anatomical arrow overlaps
  an `x`/`y`/`z` one.
- In 2D only the array indicator is shown, since a slice is cut along
  array axes rather than anatomical ones.

Both the mesh and contour layers stay in the layer list in either mode; the
one the current mode cannot draw is simply switched off.

## Documentation

- [docs/data-sources.md](docs/data-sources.md) — where each dataset came from
