# Changelog

## Unreleased

### Features

- The viewer opens a coordinate space instead of one atlas. `lobemap view <space>` draws every atlas native to FAFB14, JRCFIB2018F (hemibrain), JRCFIB2022M (male CNS) or GRABE together, over that space's reference image and, in the EM spaces, its neuropil meshes, and `lobemap spaces` lists the spaces and what each opens with.
- Six atlases: Benton 2025 in FAFB14; the neuPrint hemibrain atlas and Schlegel 2021 supplementary files 11 and 12 in JRCFIB2018F; the neuPrint male CNS atlas in JRCFIB2022M; and Grabe 2015, both lobes, in GRABE.
- 3D draws the glomerulus meshes, and 2D draws exact mesh-plane contours that stay sharp at any zoom. 2D opens on a plane that cuts the shown atlas, and a plane you chose is kept when you go to 3D and back.
- The three EM spaces show a virtual neuropil stain, built from predicted presynapse density, as their reference image; GRABE shows its confocal stack. Both are drawn in grayscale whenever they are on disk.
- The space picker switches spaces without restarting the viewer. A switch that fails leaves the open space as it was, with its checked rows, labels, fills, filters, driver lines, open tab, slice axis and plane, mode, mirror and camera.
- The compartment panel has one tab per atlas, then one per neuropil set. A checked row is a drawn glomerulus, in 3D and in 2D: a space opens with its primary atlas checked and the other atlases and neuropil sets unchecked, and hiding a layer with napari's eye unchecks its rows.
- Each row has `label` and `fill` checkboxes that write the glomerulus's name on the slice and fill its 2D contour. They and their buttons work in 2D only, so they are disabled in 3D.
- The panel buttons `Filtered`, `Invert`, `Show all`, `Show none`, `Label all`, `Label none`, `Fill all` and `Fill none` act on a tab's rows, and each tooltip says which rows. The filter searches every text column, and clicking a column header sorts by it.
- The table shows each glomerulus's side and five columns from the reference table: receptor(s), sensillum, ALRN, organ and co-receptor(s). An atlas whose names differ from its space's vocabulary also gets a canonical column, with each disagreeing name in red.
- The **Driver line** menu of an atlas tab checks the glomeruli that a sensory or projection neuron line labels, including `Orco-GAL4 & GH146-GAL4`, with the same membership as the 0.1 line presets.
- The **Slice along** menu chooses the axis 2D steps along. Each choice is named by the nearest anatomical axis and the angle between them, for example `Anterior-Posterior (z, 17.5° off)`, and the image and the contours move together.
- The **VFB** button opens the Virtual Fly Brain term page of the selected glomerulus.
- The **Mirror** checkbox shows the space reflected left-right, for display only. Known limitation: under the mirror the glomeruli shade as if lit from inside.
- Hovering names the glomerulus under the cursor in the status bar, in 3D and in 2D, and selects its row.
- In 3D the corner shows two axis indicators: napari's array axes `x`, `y` and `z`, and the anatomical axes, each labeled by the pole it points at. 2D shows only the array axes. The home button returns to the space's anatomical view, also under the mirror.
- Each glomerulus keeps one color across the atlases of its space.
- `lobemap view --show NAME` starts an asset, an atlas or a role such as `neuropil` visible in the first scene, and `--ndisplay 2` opens in 2D.
- `lobemap check` tests the data against its own geometry, including laterality, chirality, image orientation, label containment and compartment size, and reports the known defects in `registry/checks.toml` without failing. `check --compare A B SPACE` pairs two atlases by canonical name and biological side, and `lobemap reconcile` pairs them by geometry.
- `lobemap validate` checks the registry, and `lobemap nomenclature` audits the name table against the atlases and changes it only when asked.
- `lobemap build` rebuilds an asset from its source by the recipes in `registry/recipes.toml` and removes its scratch files; `build --list` shows which assets have a recipe. Every download is checked against a checksum its recipe records, and one that does not match is discarded: a sha256 for the small eLife archives, and for the 20 GB of Cloud Storage sources the md5 each object's publisher serves, so recording them downloaded nothing. `stain`, `ingest neuprint`, `bridge`, `repair` and `tozarr` run single steps, and `manifest` and `pack` prepare a data release.
- `python -m lobemap` runs the same command as `lobemap`.

### Changes

- Rewritten around coordinate spaces by David Zimmerman (#1). The 0.1 viewer remains at tag `v0.1.4`.
- `lobemap view [space]` replaces `lobemap --atlas <name>`, and `--atlas` now exits 2 with a message that names the replacement. `lobemap` with no arguments opens FAFB14 instead of Grabe 2015.
- The package no longer ships the data, only the registry metadata. `lobemap fetch` downloads the 14 data artifacts, 2.5 GB, from the `data-v1` release of gumadeiras/lobemap; `fetch --nostains` skips the three virtual stains and takes 76 MB, and `fetch --asset <id>`, repeatable, gets only the named ones.
- `fetch` checks each download against the sha256 recorded in `registry/manifest.toml` and discards a mismatch, and `fetch --check` verifies what is on disk without downloading or writing anything. An interrupted fetch or build never leaves a partial artifact where the real one belongs (a hard kill can leave a hidden staging folder beside it), and a mesh file whose names need pickle is refused, so data from another source cannot run code.
- `lobemap view` downloads every missing artifact except the stains, up to 11 files and 76 MB, before it opens a window, whichever space it opens. It never downloads a stain.
- An installed lobemap keeps its data in the user cache directory (`~/Library/Caches/lobemap/data` on macOS, `~/.cache/lobemap/data` on Linux), and a source checkout keeps it in `registry/data`. `LOBEMAP_DATA` or `--data-root` moves it for every command that reads or writes data, and `LOBEMAP_REGISTRY` or `--registry` names another registry.
- Wrong input fails with one line and no traceback, before any work starts or any window opens: an unknown space, asset or `--show` name exits 2, and a registry directory that does not exist is refused. A space with no data on disk exits 1 and names the `lobemap fetch` command, and a failed download prints its cause.
- A stalled download fails after 30 seconds without data. Once the server has not answered, the remaining downloads are skipped, so an unreachable server costs one timeout rather than one per file.
- `pip install lobemap` installs the viewer only. Rebuilding data and bridging between spaces need the ingest dependencies, about 100 more packages, from `pip install "lobemap[ingest]"`; a checkout's `uv sync` installs them, and `uv sync --no-group ingest` leaves them out.
- Every data asset records its license and the page that states it in `registry/assets.toml`, and the README separates the MIT code license from the data licenses. The neuPrint, Schlegel 2021, hemibrain stain and male CNS stain assets are CC BY 4.0, Benton 2025 is CC0 1.0, the FlyWire-derived FAFB14 neuropils and stain are CC BY-NC 4.0, and the Grabe 2015 assets are reproduced from the paper with no published terms.
- A glomerulus whose identity is in doubt says so wherever the viewer names it: Grabe 2015's `VP2`, whose Amira material is `VP2_*_VM6andVC6` and lies at VM6's position, reads `VP2(L) (VM6?)`. An atlas declares such doubts in an `[uncertain]` table.
- The README lists known defects in the published data: hemibrain `VM2(R)` is a 14 µm³ fragment, Grabe 2015 has no `VM6`, male CNS `AME(L)` is incomplete, and several hemibrain and male CNS glomeruli have holes or several pieces.
- Glomerulus names are scoped to a space, so switching space can change both the list of glomeruli and their colors. `registry/nomenclature.csv` maps each atlas's published names to its space's vocabulary and takes the place of `glomerulus_name_reconciliation.csv`.
- Slice labels are off until you check a row's `label` box or press `Label all`. The 0.1 viewer labeled every glomerulus in the slice.
- 2D contours are cut for a whole atlas at once and drawn by the canvas under their layer rather than as napari shapes. Once a space is open in 2D, and after the slice axis, the mirror or the filled glomeruli change, a background thread cuts every slider plane inside each shown atlas ahead of time and fills its filled glomeruli, keeping up to 96 MB an atlas, which holds every plane of every shipped atlas with every glomerulus filled. A step to a plane it has reached only draws, and it gives way while you move the slider. A neuropil set, which spans the brain, gets the planes nearest the slice within the same budget.
- A filled contour covers exactly the inside of its outline: a fan from its centroid where that covers it, and elsewhere napari's compiled triangulation, bermuda, checked for overlapping triangles, which drew darker, with napari's own triangulation where bermuda overlaps or fails.
- A space opens with only its primary atlas built. Every other atlas and neuropil set is built, and its layers added to napari's layer list, the first time its tab opens.
- A neuropil set that reaches past the rest of its space, as in FAFB14 and the male CNS, waits in napari's layer list as a hidden `<name> (not opened)` layer, which becomes its mesh layer when its tab opens, so the sliders and the view span the whole space from the start and opening the tab moves neither the slider grid nor the plane. Switching that layer on opens the set and shows it.
- Once a space is open, the meshes of its other atlases and neuropil sets are read in the background, pausing while the slider moves, so opening their tab only builds their layers.
- In 3D a virtual stain opens at a coarser pyramid level and switches to the finest level that fits one texture once that level has been read in the background, instead of blocking the window for up to a second on every entry into 3D.
- The virtual stains are read through a cache of decoded chunks, up to 512 MiB per stain, so a 2D step within the chunks already read decodes nothing, and missing chunks, and the 3D levels, are decoded by several threads.
- The viewer requires napari 0.9 (`>=0.9.1,<0.10`), because its 2D slice, its axis indicators and its window layout use napari internals that other versions may not have; `tests/test_napari_private.py` checks each one.
- The reference table is `registry/reference/glomerulus_ground_truth.csv`, unchanged from 0.1.4, and `registry/reference/README.md` records how it was built. The source data moved from `datasets/` to `registry/sources/`.
- Removed the atlas selector and the viewers it opened: FlyWire glomeruli, Bates Schlegel 2020, the hemibrain surfaces from the hemibrainr export, DoOR 2D, Potter Task 2022, the JRC2018 Unisex ROI viewer, and the BANC and Virtual Fly Brain browsers. Benton 2025 revises Bates 2020 in the same FAFB volume, and Schlegel 2021 S12 has the same hemibrain geometry as the hemibrainr export.
- Removed the rotation spinboxes and the separate vertical and horizontal mirrors. Slices follow the voxel grid, and the Slice along menu and the one left-right Mirror replace the View menu and the two mirrors.
- Removed the demo images and video from the README, and `docs/usage.md`.
- Removed the `./lobemap` wrapper, `lobemap.py` and `scripts/`, including `regenerate_visual_data.py`. Run `lobemap`, `uv run lobemap` or `python -m lobemap`, and rebuild data with `lobemap build`.
- Removed ten source folders that nothing here reads (BANC, DoOR, FlyWire, FlyWire Codex, Potter Task 2022, Virtual Fly Brain, the hemibrainr export, the comparative atlases, Edmond FIB-SEM and Laissue 1999), with the per-dataset napari modules and the tracked label-volume caches. Everything removed remains at tag `v0.1.4`.

## 0.1.4 - 2026-08-20

### Fixes

- Corrected GH146-GAL4 status for V, VM5v, VP2, and VP3 from the Grabe source tables.

### Changes

- Moved all dataset files under `datasets/` and kept installed atlas data available without downloads or cache generation.

## 0.1.3 - 2026-05-16

### Changes

- Added driver-line glomerulus presets, including `Orco-GAL4 & GH146-GAL4`, to atlas glomerulus tables.
- Added a `lobemap --version` option for package install checks.

## 0.1.2 - 2026-05-11

### Changes

- Increased Grabe 2015 slice label size to make glomerulus labels easier to read.

## 0.1.1 - 2026-05-10

### Changes

- Switched README demo images to absolute raw GitHub URLs so they render on the PyPI project page.
- Added repeatable PyPI release documentation and GitHub Actions Trusted Publishing workflow.

## 0.1.0 - 2026-05-10

Initial PyPI release.

### Features

- Installable Python package with the `lobemap` command-line entrypoint.
- Napari viewer for Drosophila antennal lobe atlas datasets.
- Atlas selector for Grabe 2015, Bates Schlegel 2020, hemibrain, FlyWire, Benton 2025, JRC2018Unisex, DoOR, Potter Task 2022, Virtual Fly Brain, and BANC resources.
- Tracked runtime source tables, volumes, and derived caches needed by installed viewers.
- Reference table for glomerulus names, receptors, sensilla, ligands, valence, driver lines, VFB IDs, and atlas coverage.
