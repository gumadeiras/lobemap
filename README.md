# lobemap

lobemap shows the published maps of the *Drosophila* antennal lobe side by side, in one viewer.

The antennal lobe is the first olfactory center of the fly brain. It is made of small, round compartments called *glomeruli* (one: *glomerulus*). Several groups have published a *glomerular atlas*: a 3D shape and a name for each glomerulus. The atlases come from different brains, and each one uses its own names. lobemap puts these atlases in one window, so you can compare them in 3D or one section at a time. It is built on the [napari](https://napari.org) image viewer.

## Demo

![Colored glomeruli of an antennal lobe atlas, turning in 3D](https://raw.githubusercontent.com/gumadeiras/lobemap/main/docs/images/turntable.gif)

*The glomeruli of one atlas in 3D. Each glomerulus has its own color.*

![A section through the antennal lobe, with the outline, fill and name of each glomerulus on the image](https://raw.githubusercontent.com/gumadeiras/lobemap/main/docs/images/slice-outlines.png)

*Slice view: each glomerulus is an exact outline on the image, with an optional fill and name.*

![The hemibrain in 3D, with its neuropil stain, its neuropils, and the panel that lists the glomeruli](https://raw.githubusercontent.com/gumadeiras/lobemap/main/docs/images/hemibrain-3d.png)

*The hemibrain in 3D, with its stain and neuropils. The panel on the right lists the glomeruli.*

## Install

lobemap needs Python 3.11 or 3.12.

```bash
pip install lobemap
lobemap fetch
```

The first command installs the viewer. The second downloads the data, 2.5 GB, into your user cache folder, and prints where it put it. [Data](https://github.com/gumadeiras/lobemap/blob/main/docs/data.md#where-the-data-goes) explains how to keep it somewhere else.

To download only 76 MB, use `lobemap fetch --nostains`. All four brains still open, but the three electron microscopy (EM) brains open without their background image. Run `lobemap fetch` later to add it.

## Quick start

List the brains and what each one shows:

```bash
lobemap spaces
```

Open one brain, here the hemibrain:

```bash
lobemap view JRCFIB2018F
```

`lobemap` alone opens FAFB. If the data is not on your computer yet, `lobemap view` first downloads the 76 MB it needs.

The window shows the **View** controls on the left, the brain in the middle, and the **Brain regions** panel on the right. Things to try first:

- **Turn the brain.** In 3D, drag the brain with the mouse. To set exact angles, use **Rotate around**.
- **Look at sections.** Set **Show** to **Slice**, then move the slider under the image. Each glomerulus is an outline on the image. Tick its `Label` or `Fill` box to name or fill it. In **Rotate around**, a turn about the **Vertical axis** or the **Horizontal axis** cuts an *oblique section*: a section at an angle to the image's own planes.
- **Show or hide glomeruli.** In **Brain regions**, tick or clear the `Show` box of each glomerulus. Search by name or receptor, or choose a **Driver line** to show only the glomeruli that a GAL4 or QF2 line labels. Click a glomerulus to see its receptor, sensillum and other details.
- **Compare atlases.** The hemibrain has three atlases of the same lobe. Choose one in **Source**, then tick its glomeruli. All the atlases you tick are drawn together, and a glomerulus has the same color in each. To see an atlas of another brain, choose that brain in **Brain**.
- **Mirror or flip.** **Mirror the brain left to right** helps you compare a left lobe with a right one. **Flip the picture upside down** turns the picture over. Both change the display only, not the data.

## What's inside

Each atlas was drawn in one brain volume. lobemap calls that volume a *coordinate space*: all its atlases share the same coordinates, so they line up and can be drawn over each other. The viewer calls a space a *brain*, and commands name it by its id.

| Brain | Id | Atlas | Glomeruli |
|---|---|---|---|
| FAFB: a whole female brain, EM | `FAFB14` | [Benton et al. 2025](https://doi.org/10.1038/s44319-025-00476-8) | 58, left lobe |
| Hemibrain: part of a female brain, EM | `JRCFIB2018F` | neuPrint hemibrain, [Scheffer et al. 2020](https://doi.org/10.7554/eLife.57443) | 58 right, 19 left |
| | | [Schlegel et al. 2021](https://doi.org/10.7554/eLife.66018), from sensory neurons | 59, right lobe |
| | | [Schlegel et al. 2021](https://doi.org/10.7554/eLife.66018), from projection neurons | 58, right lobe |
| Male CNS: a male brain and nerve cord, EM | `JRCFIB2022M` | neuPrint male CNS, [Berg et al. 2026](https://doi.org/10.1016/j.cell.2026.08.015) | 58 per lobe |
| Grabe 2015: a living brain, light microscopy | `GRABE` | [Grabe et al. 2015](https://doi.org/10.1002/cne.23697) | 54 per lobe |

The three EM brains also show their *neuropils*, the named regions of the brain, and a *virtual neuropil stain*: an image made from synapse positions that looks like an nc82 antibody stain. Grabe 2015 shows its own confocal image.

[The brains and atlases](https://github.com/gumadeiras/lobemap/blob/main/docs/atlases.md) says which atlas fits which comparison, and lists known gaps in the published data.

## Learn more

- [Using the viewer](https://github.com/gumadeiras/lobemap/blob/main/docs/viewer.md): every control, the panel, the layers, and speed.
- [The brains and atlases](https://github.com/gumadeiras/lobemap/blob/main/docs/atlases.md): what each atlas is, which one to use, and known gaps in the data.
- [Data](https://github.com/gumadeiras/lobemap/blob/main/docs/data.md): download, storage, checks, rebuilding from source, and data licenses.
- [Data sources](https://github.com/gumadeiras/lobemap/blob/main/docs/data-sources.md): where each dataset came from, and what lobemap does to it.
- [Commands](https://github.com/gumadeiras/lobemap/blob/main/docs/cli.md): every `lobemap` command and option.
- [Upgrading from 0.1](https://github.com/gumadeiras/lobemap/blob/main/docs/upgrading.md): what changed, and what was removed.
- [Development](https://github.com/gumadeiras/lobemap/blob/main/docs/development.md): work from the source code, run the tests, and release.
- [Changelog](https://github.com/gumadeiras/lobemap/blob/main/CHANGELOG.md): what changed in each version.

## Data licenses and citation

If you use an atlas, cite the paper it came from. [Data sources](https://github.com/gumadeiras/lobemap/blob/main/docs/data-sources.md) gives the citations.

The lobemap code is under the [MIT License](https://github.com/gumadeiras/lobemap/blob/main/LICENSE). The data is not: each dataset keeps the license of its source.

- **CC BY 4.0:** the neuPrint hemibrain and male CNS data, Schlegel 2021, and the hemibrain and male CNS stains.
- **CC0 1.0:** the Benton 2025 atlas.
- **CC BY-NC 4.0, no commercial use:** the FAFB neuropils and stain, from FlyWire.
- **No published terms:** the Grabe 2015 files. The rights stay with the authors and the publisher.

[Data licenses](https://github.com/gumadeiras/lobemap/blob/main/docs/data.md#data-licenses) has the full table.

## Authors

Gustavo Madeira Santana created lobemap and its 0.1 viewer, and assembled the source data and the reference table it builds on. David Zimmerman rewrote it around coordinate spaces for 0.2.
