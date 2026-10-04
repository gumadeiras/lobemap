# Changelog

## Unreleased

### Features

- The viewer opens a coordinate space instead of one atlas. `lobemap view <space>` draws every atlas native to FAFB14, JRCFIB2018F (hemibrain), JRCFIB2022M (male CNS) or GRABE together, over that space's reference image and, in the EM spaces, its neuropil meshes, and `lobemap spaces` lists the spaces and what each opens with.
- Six atlases: Benton 2025 in FAFB14; the neuPrint hemibrain atlas and Schlegel 2021 supplementary files 11 and 12 in JRCFIB2018F; the neuPrint male CNS atlas in JRCFIB2022M; and Grabe 2015, both lobes, in GRABE.
- 3D draws the glomerulus meshes, and 2D draws exact mesh-plane contours that stay sharp at any zoom. 2D opens on a plane that cuts the shown atlas, and a plane you chose is kept when you go to 3D and back.
- The three EM spaces show a virtual neuropil stain, built from predicted presynapse density, as their reference image; GRABE shows its confocal stack. Both are drawn in grayscale whenever they are on disk.
- The **View** dock on the left gathers the controls of the scene: **Brain**, **3D** or **Slice**, **Fit to window**, **Zoom**, **Perspective**, **Sections**, the mirror, the flip and the rotation, each named in plain words. Every control stays in view in both modes; one that works in one mode only is disabled in the other, and its tooltip says so.
- A box or menu in the View dock, or the panel's **Source**, **Sides** and **Driver line** menus, changes under the mouse wheel only once a click or Tab has focused it, so scrolling past one changes nothing. The wheel turns no tab of either column.
- napari's button rows around the layer list stay, in step with the View dock: 2D/3D is **Show**, home is **Fit to window**, roll steps **Sections**, and the camera popup's up/down, zoom and perspective are the dock's flip, **Zoom** and **Perspective**, each following the other.
- Whatever would leave a state no control shows is off and says why: transpose and its Option-click, grid and its settings, ⌘T, ⌘⌥T and ⌘G, the camera popup's left/right and depth menus, and a drag in the roll popup that swaps the two axes on screen.
- **Zoom** shows and sets the camera zoom in screen pixels per micrometer, in 3D and Slice view; **Perspective** sets the 3D field of view from `0° (flat)` to 90°, and hovering, the corner arrows, Fit to window, the rotation and the flip stay right under it.
- The View dock's controls are each as wide as their content, on one 8-pixel grid shared with napari's buttons: one column of labels, one of controls, and even spacing between rows. `Reset rotation` no longer spans the dock.
- lobemap's own layers are locked against deletion: the delete button, ⌘⌫, ⌘⌦ and ⌫ or ⌦ in the layer list pass them by and say why, and layers you add delete as before.
- **Brain** switches brains without restarting the viewer. A successful switch keeps the mode, the angles and the alignment, and clears the mirror and the flip; a switch that fails leaves the open brain as it was, with its checked rows, names, fills, searches, driver lines, open tab, slice and plane, mode, mirror, flip, angles, alignment and camera.
- **Rotate around** turns the view about the screen's **Line of sight**, **Vertical axis** and **Horizontal axis**, 0.1's Z/slice, Y/vertical and X/horizontal, from −180° to 180°, with **Reset rotation**. In 3D the camera turns from the front view; in Slice view a turn about the line of sight turns the section, and a turn about either other axis cuts a true oblique section of the image and the meshes.
- **Align sections to the anatomical axes**, off by default, cuts Slice view square to the brain's anterior–posterior, dorsal–ventral and medial–lateral axes instead of along the image grid.
- The **Glomeruli and neuropils** panel has a **Glomeruli** tab and a **Neuropils** tab. **Source**, at the top of each, chooses which of the brain's atlases of that kind the table shows, cites it underneath, sits in the same place in every brain and never changes what is drawn. A checked row is a drawn glomerulus, in 3D and in Slice view: a brain opens with its primary atlas checked and the other atlases and neuropil sets unchecked, and hiding a layer with napari's eye unchecks its rows.
- Each row is one glomerulus or neuropil with every side the atlas has of it. **Sides**, beside **Source**, chooses which sides its boxes act on: **Both**, the default, **Left** or **Right**, so one side alone can be shown, named or filled; a neuropil across the midline is on either side. A box is ticked when the row is on for every chosen side and half ticked when only some are. Every glomerulus table has the columns `Show`, `Glomerulus`, `Label`, `Fill` and `Receptor`, and every neuropil table `Show`, `Neuropil`, `Label` and `Fill`; a missing value is `—` everywhere. `Label` and `Fill` write the name on the slice, as the table has it and without the side (`DA1`, `MB_PED`), and fill the outline, in Slice view only.
- The `Show`, `Label` and `Fill` headers each have a checkbox that ticks or clears that column on every row the search lists, on the chosen sides, and shows whether all, some or none are ticked. They replace the `All`, `None`, `Matches`, `Invert`, `Names`, `No names`, `Fill` and `No fill` buttons. `Invert` is gone; to show only the rows a search finds, as `Matches` did, clear the `Show` header, search, then tick it. The search looks in the same fields in every table of a kind, and clicking any other column header sorts by it. While a search hides rows, the count under the table says how many it lists as well as how many are shown: `5 listed · 58 of 58 shown`.
- Selecting a row fills a details area of fixed size under the table: its **Sides**, then a glomerulus's standard name, receptor, co-receptor, sensory neuron, sensillum and organ, or a neuropil's full name and **Name from**, where that name comes from, each shown in full; a value the sides do not share is given for each side.
- The **Driver line** menu of a glomerulus table shows only the glomeruli that a sensory or projection neuron line labels, on the chosen sides, including `Orco-GAL4 & GH146-GAL4`, with the same membership as the 0.1 line presets. Its label stays beside it, and it reads `None` while no line is what is shown; it lists the lines only.
- **Sections** chooses which sections Slice view steps through, named by the plane and the anatomical axis the slider steps along, with the angle between that axis and the image grid, for example `Frontal (17.5° off anterior–posterior)`, or `Frontal (anterior–posterior)` when aligned; the image and the outlines move together.
- **Open in Virtual Fly Brain** opens the term page of the selected glomerulus.
- The panel's tabs show whole, with each title in the middle of its tab; napari's dock title bar used to cover their top 6 px. The **View** and **Layer settings** tabs have the same size and look. The panel is on the View dock's 8-pixel grid: its menus and button are as tall as the dock's controls and as wide as their content, its labels share one column, and every column's name starts at the left of its column.
- **Mirror the brain left to right** shows the brain reflected about its mid-plane, for display only, with the glomeruli lit as they are unmirrored. Opening another brain clears it.
- **Flip the picture upside down** turns the picture over on screen after the rotation and the mirror, in 3D and in Slice view, for display only: no slider, plane or layer moves, slice names stay readable, the glomeruli stay lit from outside, Fit to window and trips between 3D and Slice view keep it, and turning it off gives back the view exactly. Opening another brain clears it. Turning it on or off takes about 35 ms in Slice view and 4 ms in 3D, and it adds no time to a slice step or a change of mode.
- In a front view, 0.1's "Mirror horizontal" is **Mirror the brain left to right**, "Mirror vertical" is **Flip the picture upside down**, and both together are a 180° turn about the line of sight.
- Hovering names what is under the cursor in the status bar, in 3D and in Slice view, as `VA3 (left) — Benton 2025` or `AL, antennal lobe (right) — Neuropils (FlyWire)`, and moves nothing in the panel. A click that does not drag selects its row, in its tab and source.
- In 3D the corner shows two axis indicators: napari's array axes `x`, `y` and `z`, and the anatomical axes, each labeled by the pole it points at; a legend says what the letters mean. Slice view shows only the array axes. **Fit to window** fits the brain and, in 3D, turns back to the front view with the rotation applied, also under the mirror; it never moves the slice.
- Each glomerulus keeps one color across the atlases of its space, and each surface keeps one entry in napari's colormap menu, named after its atlas, such as `Benton 2025 colors`, `Male CNS neuPrint colors` or `Hemibrain neuropil colors`: checking rows or switching brains no longer adds a numbered one.
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
- A glomerulus whose identity is in doubt says so wherever the viewer names it: Grabe 2015's `VP2`, whose Amira material is `VP2_*_VM6andVC6` and lies at VM6's position, reads `VP2 (VM6?)`. An atlas declares such doubts in an `[uncertain]` table.
- The README lists known defects in the published data: hemibrain `VM2(R)` is a 14 µm³ fragment, Grabe 2015 has no `VM6`, male CNS `AME(L)` is incomplete, and several hemibrain and male CNS glomeruli have holes or several pieces.
- Glomerulus names are scoped to a space, so switching space can change both the list of glomeruli and their colors. `registry/nomenclature.csv` maps each atlas's published names to its space's vocabulary and takes the place of `glomerulus_name_reconciliation.csv`.
- Slice labels are off until you check a row's `Label` box or the `Label` header's checkbox. The 0.1 viewer labeled every glomerulus in the slice.
- 2D contours are cut for a whole atlas at once and drawn by the canvas under their layer rather than as napari shapes. Once a space is open in 2D, and after the slice axis, the mirror or the filled glomeruli change, a background thread cuts every slider plane inside each shown atlas ahead of time and fills its filled glomeruli, keeping up to 96 MB an atlas, which holds every plane of every shipped atlas with every glomerulus filled. A step to a plane it has reached only draws, and it gives way while you move the slider. A neuropil set, which spans the brain, gets the planes nearest the slice within the same budget.
- A filled contour covers exactly the inside of its outline wherever the outline does not cross or touch itself: a fan from its centroid where that covers it, and elsewhere napari's compiled triangulation, bermuda, checked for overlapping triangles, which drew darker, and given the outline turned until none overlap. No fill covers exactly the inside of an outline that crosses or touches itself, which is filled as napari's Shapes fills it; napari's own triangulation fills any outline bermuda cannot.
- A space opens with only its primary atlas built. Every other atlas and neuropil set is built, and its layers added to napari's layer list, the first time its tab opens.
- `lobemap view` reads the registry once when it has nothing to fetch; it used to read every atlas mesh twice before the window opened.
- A neuropil set that reaches past the rest of its space, as in FAFB14 and the male CNS, waits in napari's layer list as a hidden `Neuropils (FlyWire) · not loaded yet` layer, which becomes its mesh layer when its tab opens, so the sliders and the view span the whole space from the start and opening the tab moves neither the slider grid nor the plane. Switching that layer on opens the set and shows it.
- The meshes of a space's other atlases and neuropil sets are read in the background while the space opens, so opening their tab only builds their layers, and the 2D contour prefetch waits while it does.
- In 3D a virtual stain opens at a coarser pyramid level and switches to the finest level that fits one texture once that level has been read in the background, instead of blocking the window for up to a second on every entry into 3D.
- Entering 3D again draws its first frame in about 0.17 s in every space, from 0.45-0.71 s: a mesh keeps its 3D build through 2D and is built once per entry, and the 3D stain is uploaded to the GPU only when its voxels change, not on every entry. The first entry into 3D still uploads the stain once, about 0.33-0.38 s in the EM spaces.
- The virtual stains are read through a cache of decoded chunks, up to 512 MiB per stain, so a 2D step within the chunks already read decodes nothing, and missing chunks, and the 3D levels, are decoded by several threads.
- The viewer requires napari 0.9 (`>=0.9.2,<0.10`), because its 2D slice, its axis indicators and its window layout use napari internals that other versions may not have; `tests/test_napari_private.py` checks each one.
- Source units are read from the source instead of deduced from a plausible glomerulus size: neuPrint states its voxel grid in the dataset's `:Meta` node, and the OBJ and VTP recipes, whose formats carry no units, declare `source_units`. The size range now only checks the declaration (`core.units.verify_extent`); rebuilding Benton from source reproduces the shipped container exactly.
- `docs/data-sources.md` is written for users: how to get and verify the data, and what is done to it before the viewer opens it — units, mesh repair with per-atlas figures, the dropped `AL-` qualifier, and the male CNS neuropil set cut to the brain.
- The reference table is `registry/reference/glomerulus_ground_truth.csv`, unchanged from 0.1.4, and `registry/reference/README.md` records how it was built. The source data moved from `datasets/` to `registry/sources/`.
- Removed the atlas selector and the viewers it opened: FlyWire glomeruli, Bates Schlegel 2020, the hemibrain surfaces from the hemibrainr export, DoOR 2D, Potter Task 2022, the JRC2018 Unisex ROI viewer, and the BANC and Virtual Fly Brain browsers. Benton 2025 revises Bates 2020 in the same FAFB volume, and Schlegel 2021 S12 has the same hemibrain geometry as the hemibrainr export.
- The two 0.1 mirrors are one anatomical mirror, **Mirror the brain left to right**; 0.1's vertical mirror is that mirror and a 180° turn about the line of sight.
- napari's layers are named in words: `Benton 2025 · 3D`, `Benton 2025 · outlines`, `Neuropils (FlyWire) · 3D`, `Neuropil stain (from synapses)`, `Confocal image (Grabe 2015)` and `Glomerulus label volume (Grabe 2015)`, with colormaps named after their atlas. No id or bracketed tag reaches the user anywhere in the window, which `tests/test_plain_words.py` checks in every brain and mode.
- lobemap's layers are locked against napari's drawing and transform tools, which could move a mesh off its image; a layer you add is not.
- The neuropil full names name every part of the mushroom body as one, for example "mushroom body calyx" and "mushroom body α′ lobe".
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
