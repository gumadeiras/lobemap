# lobemap

A [napari](https://napari.org) viewer for *Drosophila* antennal lobe
(AL) glomerular atlases.

Several groups have published glomerular parcellations of the AL, each
from a different volume and each using its own names. lobemap puts them
in one viewer so they can be looked at side by side: as 3D meshes, or as
exact cross-sections on a slice through the underlying image.

The viewer opens a **coordinate space** — FAFB, the hemibrain, the male
CNS, or the Grabe light-microscopy template. A space holds every atlas
native to it at once, together with its reference image and, in the three
EM spaces, its neuropil geometry, so the parcellations of one volume can be
drawn over each other.

## Installing

Python 3.11 or 3.12. From PyPI:

```bash
pip install lobemap
lobemap fetch
```

`fetch` downloads the data, which is published separately rather than shipped in the package. An installed lobemap keeps it in the user cache directory (`~/Library/Caches/lobemap/data` on macOS, `~/.cache/lobemap/data` on Linux); `fetch` prints the location. Set `LOBEMAP_DATA`, or pass `--data-root`, to keep it somewhere else.

Upgrading from 0.1: the data no longer ships in the package, and `lobemap view <space>` replaces `lobemap --atlas <name>`. [CHANGELOG.md](CHANGELOG.md) lists what changed and what was removed.

From a source checkout, with [uv](https://docs.astral.sh/uv/), from the repository root:

```bash
uv sync
uv run lobemap fetch
```

A checkout keeps its data in `registry/data`.

Viewing needs nothing more. Rebuilding data from source (`build`, `stain`, `ingest`) and moving geometry between spaces (`bridge`, and `check` or `reconcile` on an atlas outside its own space) need about 100 more packages, which `pip install "lobemap[ingest]"` adds. In a checkout, `uv sync` and `uv run` install them too, because the `ingest` group is a default; pass `--no-group ingest` to both to leave them out, as in `uv run --no-group ingest lobemap`.

A full `fetch` is 2.5 GB and gets everything: the atlases, the neuropil sets, the Grabe confocal stack and label volume, and the three virtual stains described under [Data](#data) below. The stains are 2.4 GB of that, so if you would rather not wait for them:

```bash
uv run lobemap fetch --nostains
```

leaves them out and takes 76 MB. Every space still opens; the three EM spaces just open without their reference image, and running the full `fetch` later fills them in.

## Quick start

```bash
uv run lobemap
```

That opens FAFB, after fetching the 76 MB of core data if it is not on disk yet. To list the spaces and what each will put on screen:

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
| FAFB14 | [Benton 2025](https://doi.org/10.1038/s44319-025-00476-8) (Dataset EV2) | 58 |
| JRCFIB2018F (hemibrain) | neuPrint [hemibrain](https://doi.org/10.7554/eLife.57443) | 58 + 19 |
| JRCFIB2018F | [Schlegel 2021](https://doi.org/10.7554/eLife.66018) S11, from receptor neurons | 59 |
| JRCFIB2018F | [Schlegel 2021](https://doi.org/10.7554/eLife.66018) S12, from projection neurons | 58 |
| JRCFIB2022M (male CNS) | neuPrint [male CNS](https://doi.org/10.1016/j.cell.2026.08.015) | 58 + 58 |
| GRABE | [Grabe 2015](https://doi.org/10.1002/cne.23697) | 54 + 54 |

Three gaps in the published data are worth knowing before comparing atlases:

- The neuPrint hemibrain `VM2(R)` is counted above but is effectively missing: it is a 14 µm³ fragment, where VM2 is 1,342–3,259 µm³ in every other atlas that has one. Schlegel S12 has a complete VM2 in the same volume. `lobemap check` lists it as a known defect ([`registry/checks.toml`](registry/checks.toml)).
- Grabe 2015 has no `VM6`. Its Amira material table names VM6 on both sides, but the published label volume ("sure ones" only) has no voxels for either, so 54 glomeruli per side are meshed rather than 55. The same table names the material lobemap reads as `VP2` `VP2_left_VM6andVC6` and `VP2_right_VM6andVC6`, and in affine fits to the male CNS and to Schlegel S12 it lies at VM6's position rather than VP2's. So Grabe's `VP2` may be VM6: the viewer names it `VP2 (VM6?)` in the table, with each side's reason in its tooltip, and `VP2(L) (VM6?)` and `VP2(R) (VM6?)` on the slice, while `registry/nomenclature.csv` still maps it to VP2.
- In the male CNS neuropil set, `AME(L)` is about a quarter of the volume of `AME(R)` (4,172 against 16,608 µm³) after the watertight repair. Treat it as incomplete; the source mesh is not kept, so it is not known whether the ROI or the repair lost the rest.

Which one to reach for depends on what you are comparing against:

- **GRABE** is the only atlas built from an intact, living brain, imaged
  in vivo rather than dissected and fixed. Its glomerular shapes and the
  geometry of its reference stack (`elav-nSyb::DsRed`, not nc82) are
  therefore the closest match to in vivo imaging data. It is also the
  oldest of the six and predates revisions to the fine structure of a few
  glomeruli.
- **FAFB14** (the FAFB volume, which FlyWire also reconstructs) is a complete female brain, dissected and
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

Each space also carries one reference image, and each EM space its brain
neuropils. For Grabe, which is light microscopy and has no neuropil meshes,
the image is its own confocal stack. For the
three EM spaces it is a **virtual neuropil stain**: the density of
predicted presynapses, binned and blurred into something that reads like an
nc82 antibody stain, computed natively in each volume rather than warped in
from light microscopy.

Glomerulus names are scoped to a space, so switching space may change both
the list of glomeruli and their colors.

## Data

The data the viewer opens is not committed. Its fourteen artifacts are published as assets of the [`data-v1` release](https://github.com/gumadeiras/lobemap/releases/tag/data-v1) — 2.51 GB, of which the three virtual stains are 2.44 GB. What the repository does commit is the published source data some of them are built from, about 220 MB under [`registry/sources/`](registry/sources/README.md), and the registry metadata. Only the metadata ships in the package.

`registry/manifest.toml` records where the artifacts are fetched from and the sha256 of every one, and `lobemap fetch` checks each download against it; a file that does not match is discarded rather than kept. `lobemap fetch --check` verifies what is on disk without downloading anything. Naming an asset fetches just that one:

```bash
uv run lobemap fetch --asset hemibrain_stain
```

`lobemap view` fetches before it opens a window: every missing artifact except the stains, up to 11 files and 76 MB, whichever space you open. So the explicit `fetch` above is a convenience rather than a requirement. It never fetches a stain, though: after `fetch --nostains` the EM spaces open without a reference image until you fetch one. A stain that *is* on disk is always shown.

You can also rebuild from source instead of downloading:

```bash
uv run lobemap build --list
```

```bash
uv run lobemap build hemibrain_stain
```

Each stain needs several gigabytes downloaded from the published synapse releases, about 40 GB of scratch space, and a long run, so `build --all` skips them and they have to be asked for by name. Everything else is derived from sources that either ship in `registry/sources/` or are downloaded by the build; the neuPrint assets need a neuPrint token in `NEUPRINT_APPLICATION_CREDENTIALS`, and `fafb_neuropil` needs FlyWire access. `registry/recipes.toml` records exactly how each asset is built, and [`registry/data/README.md`](registry/data/README.md) describes each pipeline.

A rebuilt asset is not byte-identical to the original — every pipeline stamps the date it ran — so compare its *content* hash, which the build prints, instead. `lobemap pack` writes the upload-ready copies if you are republishing.

## Data licenses

The MIT License in [LICENSE](LICENSE) covers the lobemap code. It does not cover the data. Each data asset keeps the license of its source, recorded per asset in [`registry/assets.toml`](registry/assets.toml) as `source.license`, with the page that states it as `source.license_url`:

| assets | license | stated at |
|---|---|---|
| `neuprint_hemibrain_glomeruli`, `neuprint_hemibrain_neuropil`, `hemibrain_stain` | CC BY 4.0 | [Janelia FlyEM hemibrain](https://www.janelia.org/project-team/flyem/hemibrain) |
| `neuprint_cns_glomeruli`, `neuprint_cns_neuropil`, `malecns_stain` | CC BY 4.0 | [male CNS downloads](https://male-cns.janelia.org/download/) |
| `schlegel2021_s11_glomeruli`, `schlegel2021_s12_glomeruli` | CC BY 4.0 | [Schlegel et al. 2021, eLife](https://elifesciences.org/articles/66018) |
| `benton2025_glomeruli` | CC0 1.0 (the article itself is CC BY 4.0) | [Benton et al. 2025, EMBO Reports](https://europepmc.org/article/PMC/PMC12187929) |
| `fafb_neuropil`, `fafb_stain` | CC BY-NC 4.0: attribution, no commercial use | [FlyWire guidelines](https://flywire.ai/guidelines) |
| `grabe2015_glomeruli`, `grabe2015_labels`, `grabe2015_stack` | none published | [Grabe et al. 2015](https://doi.org/10.1002/cne.23697), [atlas page](https://www.ice.mpg.de/232714/vivo-3d-atlas) |

The Grabe 2015 assets are built from files reproduced from the paper and its in vivo atlas: the confocal stack, and the Amira label volume with its material table. Neither the journal nor the atlas page publishes terms for them, and lobemap grants none: the rights stay with the authors and the publisher.

The tracked source files under `registry/sources/` keep the terms of the same sources: Benton's Dataset EV1 and EV2 are CC0 1.0 and its figure panels CC BY 4.0; the Grabe files are reproduced from the paper as above, except the Grabe 2016 supplemental tables (`s1.png`, `s1_cont.png`, `s2.png`), which are [CC BY-NC-ND 4.0](https://doi.org/10.1016/j.celrep.2016.08.063); the Bates 2020 atlas figure is CC BY 4.0; and the JRC2018 Unisex template and ROI volumes from Virtual Fly Brain are [CC BY-NC-SA 4.0](https://www.virtualflybrain.org/reports/JRC2018). [`registry/reference/glomerulus_ground_truth.csv`](registry/reference/README.md) compiles values from published tables, and each value keeps the terms of its source.

CC BY and CC BY-NC require attribution, so cite the paper behind each atlas you use; [docs/data-sources.md](docs/data-sources.md) has the citations. CC BY-NC data, which includes everything in FAFB14 except the Benton atlas, may not be used commercially.

## In the viewer

The window has three columns. On the left, the **View** dock, tabbed with napari's **Layer settings**, sits above napari's **Layers** list, with napari's two rows of buttons above and below the list. The canvas is in the middle. On the right, **Glomeruli and neuropils** has a **Glomeruli** tab and a **Neuropils** tab, each with a source menu over its table. The docks have no close button; the Window menu shows a hidden one again.

### The View dock

- **Brain** opens another brain without restarting: FAFB (female, EM), Hemibrain (female, EM), Male CNS (EM) or Grabe 2015 (live, light microscopy). Its tooltip spells out the abbreviations and names the template the brain is shown in. Only brains with data on disk are listed.
- **Show** switches between **3D**, which draws the meshes, and **Slice**, which draws one section at a time: the image, and exact mesh–plane outlines that stay sharp at any zoom. **Fit to window** fits the brain to the window; in 3D it also turns back to the front view, dorsal side up, with the rotation applied. It never moves the slice or the angles.
- **Zoom** is how large the brain is drawn, in screen pixels per micrometer of the brain: napari's own zoom factor, the number its camera popup shows. Scrolling, Fit to window and the popup change it, and typing a number zooms to it, in 3D and in Slice view.
- **Perspective** is the 3D camera's field of view, from `0° (flat)`, the default, with no perspective, to 90°, the strongest. It works in 3D only; in Slice view it is disabled and says so. Hovering, the corner arrows, Fit to window, the rotation and the flip are the same under perspective.
- **Sections** chooses which sections the slider steps through. Each choice is named by its plane and the anatomical axis the slider steps along across it — frontal sections along anterior–posterior, horizontal along dorsal–ventral, sagittal along medial–lateral — and by the angle between that axis and the image grid the sections follow, for example `Frontal (17.5° off anterior–posterior)` in FAFB. **Align sections to the anatomical axes**, off by default, cuts the sections square to those three axes instead, and the menu then reads `Frontal (anterior–posterior)`. Both work in Slice view only; in 3D they are disabled and say so.
- **Mirror the brain left to right** shows the brain as its mirror image about its mid-plane, to compare a left lobe with a right one. It is for display only: the data do not change, and the corner arrows follow it.
- **Flip the picture upside down** turns the picture over on screen, top to bottom about the middle of the view, after the rotation and the mirror, in 3D and in Slice view. It is for display only: no slider, plane or layer moves, the corner arrows follow, names on the slice stay readable, the surfaces stay lit from outside, and turning it off gives back the view exactly. With the mirror, a front view is turned 180°. Its only cost is the click: about 35 ms in Slice view and 4 ms in 3D. A slice step and a change between 3D and Slice view take as long upside down as upright.
- **Rotate around** turns the view by three angles, from −180° to 180°, about the axes of the screen:
  - **Line of sight**: positive turns the picture counterclockwise.
  - **Vertical axis**: positive moves the near side to your right.
  - **Horizontal axis**: positive brings the top toward you.

  The rows are named by the screen's axes, not by x, y and z, which are the image's own axes and differ from the screen's once the slice axis changes. In 3D the camera turns from the front view, and no layer moves. Dragging still turns the camera freely and leaves the angles as they are; a new angle, or Fit to window, puts the camera back at the front view turned by the angles. In Slice view, a turn about the line of sight turns the section in the screen plane. A turn about the vertical or horizontal axis cuts a true oblique section: the image is resampled on the turned plane and the outlines are exact sections of the meshes on it, the slider steps along your line of sight and reads `depth`, and napari's x/y/z arrows are hidden, since no image axis is on screen. **Reset rotation** gives back exactly the unturned view.
- In 3D the corner shows two sets of arrows: napari's, for the image's own axes `x`, `y` and `z`, and the anatomy's, each labeled with the pole it points at, one of `A`/`P`, `D`/`V` and `L`/`R`. The legend under the controls says what the letters mean. In Slice view only napari's arrows are shown.

0.1's controls map onto these as follows, for a frontal view:

| 0.1 | now |
|---|---|
| Z/slice | Rotate around **Line of sight** |
| Y/vertical | Rotate around **Vertical axis** |
| X/horizontal | Rotate around **Horizontal axis** |
| Mirror horizontal | **Mirror the brain left to right** |
| Mirror vertical | **Flip the picture upside down** |
| both mirrors, Benton's 0.1 default | both, which is a 180° turn: the same as **Line of sight** 180° |

### napari's buttons

napari's buttons are where napari puts them, and each one either works in step with the View dock or is off and says why in its tooltip.

- Under the layer list: **console**; **2D/3D**, the same as **Show**; **roll**, which steps to the next **Sections** choice and is off in 3D, as Sections is; **transpose** and **grid**, both off; and **home**, the same as **Fit to window**, rotation and flip kept. Each pair follows the viewer, so using one updates the other.
- A right-click on **2D/3D** opens napari's camera popup. Its up/down menu is **Flip the picture upside down**, its zoom is **Zoom**, and in 3D its perspective is **Perspective**; each shows the other's change. Its angle sliders turn the camera as dragging does: the **Rotate around** boxes keep their values, and Fit to window goes back to them. Its left/right menu, and in 3D its depth menu, are off, because either would show the brain mirrored with no control to say so: use **Mirror the brain left to right**, or flip the picture and turn it 180° about the line of sight.
- A right-click on **roll** lists the axes in the order the slice uses. Dragging an axis to the top slices along it, as **Sections** does; a drag that swaps the two axes on screen is undone, and a message says why.
- **Transpose** would show the brain mirrored across the picture's diagonal and **grid** would draw the outlines apart from their image, with nothing in the View dock to show either, so both are off, with their right-click settings. So are their keys: ⌘T, ⌘⌥T (napari's turn of every layer by 90°, also Option-click on transpose) and ⌘G show a message and do nothing.
- Over the layer list: **new points**, **new shapes** and **new labels** layers, which are yours to draw in, and **delete**. lobemap's own layers carry napari's lock: delete, ⌘⌫ and ⌘⌦ on the canvas, and ⌫ and ⌦ in the layer list pass them by and say they are locked, and they stay locked if unlocked from the layer menu. Layers you add delete as usual.

### Switching brains

A switch that succeeds keeps the mode, the angles, the alignment and the perspective, which mean the same on screen in every brain, and the section plane by its anatomy: frontal stays frontal, whichever image axis that is in the new brain. It clears the mirror and the flip, so a brain never opens reflected or upside down. Each brain opens its own tables, with its primary atlas checked.

A switch that fails says why under the controls and leaves the brain you had exactly as it was: its checked rows, names, fills, searches, driver lines, open tab and sources, its slice and plane, the mode, the mirror, the flip, the angles, the alignment and the camera.

### The tables

- The panel has two tabs, **Glomeruli** and **Neuropils**; GRABE has Glomeruli only. **Source**, at the top of each tab, chooses which of the brain's atlases of that kind the table shows, with its citation under the menu: neuPrint, Schlegel (sensory) or Schlegel (projection) in the hemibrain, Benton 2025 in FAFB, neuPrint in the male CNS and Grabe 2015 in GRABE; for the neuropils, FlyWire in FAFB and neuPrint in the hemibrain and the male CNS. The menu and its citation sit in the same place in every brain, with one source or three. Choosing a source shows its table and never changes what is drawn; each source keeps its own checked rows, search and driver line.
- Each row is one glomerulus or neuropil with every side the atlas has of it, so its boxes act on every side at once. Glomerulus tables have the columns `Show`, `Glomerulus`, `Label`, `Fill` and `Receptor`; neuropil tables have `Show`, `Neuropil`, `Label` and `Fill`. A missing value shows `—` everywhere.
- A checked row is a drawn compartment, every side of it, in 3D and in Slice view. A brain opens with its primary atlas checked and everything else unchecked, and hiding a layer with napari's eye unchecks its rows. `Label` writes the name on the slice and `Fill` fills its outline; they and the **On slice** buttons work in Slice view only, so in 3D they are disabled and the row's label reads **Slice view only**.
- The **Show** buttons `All`, `None`, `Matches` and `Invert` act on the rows of the table shown; `Matches` keeps the rows the search leaves. The **On slice** buttons are `Names`, `No names`, `Fill` and `No fill`. The search looks in the name of each side, as published too, and in the receptor, sensillum, organ and the other details of the table's kind; clicking a column header sorts by it.
- **Driver line** checks the glomeruli that a GAL4 or QF2 line labels, from the `sensory_neuron_lines` and `projection_neuron_lines` columns of `registry/reference/glomerulus_ground_truth.csv`. `Orco-GAL4 & GH146-GAL4` checks the glomeruli that both lines label.
- Selecting a row fills the details under the table: first **Sides**, `Left`, `Right`, `Left and right` or `Midline`; then for a glomerulus its standard name, receptor, co-receptor, sensory neuron, sensillum and organ, with **Open in Virtual Fly Brain**, and for a neuropil its full name and the source of that name. A value the sides do not share is given for each side, a line each, as `Left: …` and `Right: …`, and a doubt that only some sides have is written after those sides in **Sides**; the name's tooltip gives each side's reason. The details area keeps its size, with room for the longest value in the table, so selecting another row changes only the text.
- Hovering in the canvas names what is under the cursor in the status bar, for example `VA3 (left) — Benton 2025` or `AL, antennal lobe (right) — Neuropils (FlyWire)`, on its mesh in 3D and inside its outline in Slice view. Hovering moves nothing in the panel. A click that does not drag opens the row's tab, chooses its source, selects the row and fills the details; a drag turns or pans the view.
- Only the primary atlas is built when a brain opens. The others are read in the background and are built, and join napari's layer list, the first time their table is shown: chosen in **Source**, or, for the neuropils, when their tab opens. A neuropil set that reaches past the rest of its brain waits in the layer list as a hidden `Neuropils (FlyWire) · not loaded yet` layer, so the sliders and the view are the same before and after it is built.

### Layers

Each layer is named by its atlas and what it draws: `Benton 2025 · 3D` for the meshes and `Benton 2025 · outlines` for the sections. A neuropil set also says where its data come from, as in `Neuropils (FlyWire) · 3D` and `Neuropils (neuPrint) · 3D`. The images are `Neuropil stain (from synapses)`, `Confocal image (Grabe 2015)` and, off by default, `Glomerulus label volume (Grabe 2015)`. The meshes use the colormaps `Glomerulus colors` and `Neuropil colors`. Both the mesh and the outline layer stay in the list in either mode; the one the mode cannot draw is switched off. lobemap's layers are locked against napari's drawing and transform tools, which would move a mesh off its image, and against deletion; a layer you add yourself is not.

Each glomerulus keeps one color across the atlases of its brain, in 3D, on the slice and on its name.

A brain's reference image, the virtual stain or the Grabe confocal image, is shown in grayscale whenever it has been fetched. In 3D a virtual stain first shows a coarser level of its pyramid and sharpens, usually within a second, once the finest level that fits one GPU texture has been read in the background; later visits to 3D show that level at once. `--show` turns on something that starts off, in the first brain only: an asset id (`lobemap view FAFB14 --show fafb_neuropil`), an atlas id (`lobemap view JRCFIB2018F --show schlegel2021_s12`) or a role (`--show neuropil`). A name the brain does not have, or an unknown space, is refused with one line before any window opens. `--ndisplay 2` opens in Slice view.

### Speed while turned

At 0° nothing of the rotation runs. Once turned, a repeat step of the slider in Slice view takes 2–4 ms in every brain. The first visit to an oblique plane takes 5–24 ms, and about 40 ms in the hemibrain at a compound angle. Setting an oblique angle takes 55–215 ms. While turned, the hemibrain peaks at about 2.3 GB of memory, against 1.15 GB unturned.

## Documentation

- [docs/data-sources.md](docs/data-sources.md) — where each dataset came from
- [registry/data/README.md](registry/data/README.md) — how each data asset is rebuilt
- [registry/sources/README.md](registry/sources/README.md) — the source data in the repository
- [registry/reference/README.md](registry/reference/README.md) — the reference table and how it was built
- [CHANGELOG.md](CHANGELOG.md) — what changed since 0.1.4, including what was removed

lobemap 0.1, with its atlas selector, DoOR and Potter maps, and BANC and Virtual Fly Brain browsers, remains at tag [`v0.1.4`](https://github.com/gumadeiras/lobemap/tree/v0.1.4).

## Authors

Gustavo Madeira Santana created lobemap and its 0.1 viewer, and assembled the source data and the reference table it builds on. David Zimmerman rewrote it around coordinate spaces for 0.2.
