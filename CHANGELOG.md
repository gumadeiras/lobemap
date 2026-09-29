# Changelog

## Unreleased

### Added

- A **Slice along** menu chooses the axis 2D steps along. Each choice is named by the nearest anatomical axis with the angle between them, for example `Anterior-Posterior (z, 17.5° off)`, and the image and the contours move together.
- A **Mirror** checkbox beside the space picker shows the whole space reflected left-right, for display only. Every layer moves -- meshes, reference image, label volume and slice contours -- by a world-space reflection on `layer.affine`, so the data on disk is untouched and nothing downstream sees a different geometry.
- It reflects about array axis 0, which napari names `x`, and about the mid-plane of the data rather than about zero: reflecting about the origin would also throw a space published at x 192-853 um clean off screen. `x` is the left-right axis in all four spaces -- 1.0 deg off in the hemibrain, 1.3 in the male CNS, 3.7 in FAFB14, 5.5 in GRABE -- so this is a left-right mirror, and using the array axis rather than the measured lateral direction is what keeps a 2D slice cutting the voxel grid squarely.
- Both axis triads follow the mirror, so the anatomical one still names the side on screen. `anatomical_triad` takes a `reflect_axis`, and its sign choice is now made against the world arrows AS DRAWN: napari's `x` arrow is reflected too, and measuring against `+x` put an anatomical arrow on top of it. Minimum separation is back to the unmirrored 58.6-75.3 deg. The lateral label does not necessarily swap -- both poles are reachable among the right-handed candidates -- but each arrow always points where its own label says.
- Known limitation: under a mirror the glomeruli still shade as though lit from inside. The surfaces are re-wound so their triangles stay outward-facing, which the tests confirm by signed volume, but that does not change the appearance, so vispy's lighting is not driven by the winding. Unresolved.
- `python -m lobemap` runs the same command as `lobemap`.

### Fixed

- Filling glomeruli in 2D costs about a third more than outlines alone instead of five times more: napari's compiled triangulation, bermuda, is now a dependency.
- `lobemap fetch --check` verifies the published stains on every platform and zlib build, and writes nothing. It checked a Zarr store by zipping it again, which gave a different hash wherever the platform byte or the zlib output differed, so good stores read as corrupt, every `fetch` downloaded the 2.44 GB of stains again, and each check wrote a temporary zip of up to 1.1 GB. A store is now checked by its content, recorded as `tree_sha256` in manifest format 2; downloads are still checked against the published zip's sha256, which is unchanged, and format 1 manifests still load.
- 2D slice steps are about 2 to 5 times faster, and 2.5 to 8 times on a slice visited before: contours are cut for a whole atlas at once and kept per slice, and a step redraws the contour layer once, writing only what changed.
- Switching from 3D to 2D redraws the slice contours at most once instead of three or four times, and opening a space in 3D no longer draws contours it then hides.
- With **Mirror** on and the slider on the left-right axis, 2D shows the contours of the plane on screen instead of none.
- The compartment table's checked rows are what is drawn, in 3D and in 2D. Secondary atlases and reference shells open unchecked instead of reading "N / N shown" while hidden, unticking one row of a hidden atlas no longer shows all the others, the mesh no longer comes back under a 2D slice a moment after a row change, and switching between 2D and 3D no longer restores a stale visibility. Hiding a layer with napari's eye unchecks its rows.
- Ticking one row takes 1-2 ms in 3D instead of 44-218 ms: napari does not skip a `visible` write that changes nothing, and each toggle made several.
- A failed space switch leaves the previous space as it was. The failed scene's layers, a second Compartments panel, and handlers that kept redrawing on every slice step used to stay behind.
- `--show` applies to the first scene only, so switching space after `lobemap view FAFB14 --show fafb_neuropil` no longer fails.
- `--show` accepts an asset id, an atlas id or a role, so `--show neuropil` and `--show schlegel2021_s12` work instead of crashing at launch.
- `lobemap view` checks the space and `--show` before it fetches anything or opens a window: an unknown name exits 2 with one line, a space with nothing on disk exits 1 with the `lobemap fetch` advice, and a download that fails prints its cause.
- `lobemap view --data-root` opens the data it fetched there, not the default data root.
- Loading a space no longer connects another set of view-fit handlers to the canvas each time.
- The FlyWire-derived neuropil layer is labeled `fafb_neuropil [bridged]` again.
- 2D opens on a plane that cuts the shown atlas. FAFB14, the hemibrain and the male CNS opened 2D, and came back from 3D, on a plane with no glomerulus in it; a plane you chose is still kept.
- The mirror reflects napari's `x` arrow in 2D as well as in 3D, a scene opened in 2D faces the anatomy the first time it enters 3D, and under the mirror the home button faces the mirrored anatomy.
- The annotation columns keep names that contain `+`, so VP4's sensillum reads `Sacculus, Chambers I + II` instead of being split into `Chambers I` and `II`, and DL2v's receptors include `Ir75c` again instead of only the pooled `Ir75c (subset)`.
- `lobemap fetch --check` verifies the published stains on macOS and Linux. Hashing a Zarr store re-zips it, and each zip entry recorded the platform that wrote it, so stores published from Windows reported as corrupt elsewhere and every `lobemap fetch` downloaded the 2.44 GB of stains again. The zip now records the same platform everywhere.
- The virtual stains and the GRABE confocal stack render in grayscale rather than magenta. They are reference imagery under colored glomerulus meshes, and a magenta wash tinted everything drawn over it. The GRABE stack carried its own per-asset `display` override, so it needed changing in `assets.toml` too.
- The viewer draws **two axis triads** in 3D, sharing one origin. napari's own names the ARRAY axes — `x`, `y`, `z` — and a second one names the anatomy, `A`, `D` and `R` or `L`, turned onto the measured frame. Two rather than one because they are two different facts: an earlier version turned napari's own onto the anatomy, which left nothing showing where the voxel grid ran.
- In 2D only napari's remains. A slice is cut along array axes, which are 15–31° off the anatomy in every space, so an anatomical arrow over a slice claimed an alignment the slice does not have.
- Which pole each anatomical arrow carries is chosen so that none lands near any arrow of the x/y/z triad — of the 24 right-handed candidates, the one whose closest approach is furthest off. That works only because napari draws the POSITIVE axes alone and cannot reverse an arrow; against ± pairs the nearest distance would be fixed by the anatomy. Every arrow ends up 58.6° or more from its nearest neighbor, against 3.7° under the obvious alternative of pairing each anatomical axis with the array axis nearest it.
- Both triads use Okabe-Ito colors, so the pairing survives color-blind viewing: `x`/`y`/`z` in `#56B4E9`/`#CC79A7`/`#F0E442`, the anatomy in `#D55E00`/`#009E73`/`#0072B2`. The color table is indexed by `ndim - 1 - axis` rather than by the axis, so both lists are written reversed; getting that wrong put the wrong color on every arrow.
- `spaces.toml` takes `anatomical_rotation = { axis, degrees }`, the rotation sending a space's array axes onto (anterior, dorsal, lateral). It is the only statement of a space's anatomy — `anterior` and `dorsal`, which named a signed array axis each, are gone. They were the anatomy before it was measured and afterwards only ever the nearest array axis to it; slicing never read them, so only the camera did, and the camera is better off with the exact directions. The home view therefore moves by 15–18° in the EM spaces and 31° in GRABE.
- Axis-angle rather than a matrix or a pair of vectors, because any axis and any angle name a proper rotation — nothing writable is ill-formed. A pole name is not accepted as an axis: the poles are what the rotation defines, so naming one would be circular.
- The rotations are measured by bridging 20,000 neuropil vertices per space into JRC2018U, whose axes are taken as the anatomical ground truth, and taking the rotation of the best-fit affine by polar decomposition. Anterior ends up 17.5° off the old declared axis in FAFB14, 16.1° in the hemibrain and 14.7° in the male CNS (brain only, no VNC) — one shared tilt, since the three agree with each other far better than any agrees with the template.
- GRABE has no bridging registration, so it is reached through its glomeruli: one affine against each of the hemibrain and male CNS atlases over all glomeruli of both hemispheres (72 and 106), giving 31.74° and 31.98°, 5.21° apart, and a chordal L2 mean on SO(3) putting anterior 31.5° off. FAFB is excluded — its one glomerulus atlas covers a single lobe, and a fit with no midline in it barely constrains left-right. Measured against the targets' *declared* axes it had read 48.72°, carrying their own 15–18° into it.
- The hemibrain and male CNS glomeruli drop neuPrint's `AL-` qualifier, so they read `DA1(R)` like the other four atlases rather than `AL-DA1(R)`. The prefix is stripped at ingest and both mesh containers were regenerated and republished, so the name is gone from the geometry rather than hidden at display time; the regeneration changed nothing else, leaving 77 and 116 compartments with byte-identical vertices.
- Gustavo Madeira Santana is listed again as an author of the package. The rewrite replaced the `authors` field outright; he originated lobemap, holds the copyright in `LICENSE`, and the curated nomenclature tables and the source data under `registry/sources/` are his work.
- Restored `license`, `license-files`, `keywords` and `classifiers`, all dropped by the rewrite. The built wheel declared no license at all while shipping his copyright; it now carries `License-Expression: MIT`. No license *classifier* — PEP 639 forbids one alongside `license`, and setuptools refuses the build.
- The compartments pane opens on an atlas instead of on a neuropil shell, and reference tabs (neuropil, brain) now sit after every atlas rather than before them. The shells are built into the scene first so they draw underneath the glomeruli, and that stacking order was reaching the tab bar. Which atlas opens is the space's declared `primary_atlas`, so the open tab matches the atlas that is drawn; JRCFIB2018F, the only space with several, opens on the neuPrint parcellation.
- The table's `side` column now reports the BIOLOGICAL side, matching every other side label in the catalog. It was converting the asset's declared side to the apparent one, so Benton's glomeruli read `R` in FAFB14 while sitting inside the shell FlyWire names `AL_L` and while their own asset declared `L` — two conventions in one space. All 58 Benton centroids are contained by `AL_L` and none by `AL_R`, so the atlas is the fly's LEFT antennal lobe and now says so.
- `grabe2015_glomeruli` declared `side = "L"` but carries both lobes — 108 meshes, 54 per side, each name already suffixed `(L)` or `(R)`. It declares `both`, so nothing infers a side for an atlas that states one per compartment.
- An installed lobemap carries its registry metadata, so `lobemap spaces`, `validate` and `fetch` work after `pip install lobemap` instead of reporting 0 spaces or no manifest; the data still does not ship in the package.
- Wrong input fails with one line and exit 2 instead of succeeding or printing a traceback: a registry directory that does not exist, and an unknown asset or space given to `fetch`, `pack`, `build`, `repair`, `bridge` or `stain`.
- `--data-root` applies to `manifest`, `spaces`, `nomenclature`, `repair`, `stain` and `ingest neuprint`: `manifest` no longer crashes on it, and `stain` and `ingest neuprint` write their output there instead of always into `registry/data`.
- `lobemap manifest --prune` keeps the recorded `base_url`; it used to write a manifest that `fetch` could not download from.
- A download that stalls fails after 30 seconds without data instead of hanging, and once the server has not answered the remaining downloads are skipped, so `fetch` returns and bare `lobemap` still opens its window.
- A mesh container whose names can only be read through pickle is refused instead of unpickled, so a crafted `.npz` in a data root, the bridge cache or a custom `--base-url` cannot run code. A pickled bridge-cache entry is rebuilt; a trusted legacy file loads with `MeshSet.load(path, allow_legacy_pickle=True)`.
- Rewriting `registry/nomenclature.csv` keeps its LF line endings, so a one-row change is a one-line diff rather than a rewrite of all 477 lines.
- A Zarr pyramid level over an axis of size 3 averages the two voxels its metadata describes, not all three. No published store has such an axis.
- `lobemap bridge` counts the points a transform does not cover, and those points keep their position in micrometers. They were reported as 0 and placed in the source template's units, 1000x off between nm and um spaces; bridged meshes cached before this are rebuilt.
- `lobemap manifest` quotes asset ids, paths and the base URL where TOML needs it, so an id with a dot or a path with a quote no longer writes a manifest that cannot be read back.
- An interrupted `fetch`, `build`, `stain` or bridge-cache write leaves nothing at the artifact's path, and a rewrite keeps the old file until the new one is complete. A Zarr store cut off part-way used to open without error and read zeros, and `fetch` then skipped it as present.
- `lobemap build <stain>` removes its scratch files, 10-25 GB per whole-brain stain, when it finishes or fails. They were left in `.stainwork` under the data root after every build.
- `lobemap build` checks each downloaded source against a `sha256` table in its recipe, discards a download that does not match, fetches a failing cached copy again, and says when a source has no digest recorded. Downloaded sources were never checked.
- Downloads in `lobemap fetch` and `lobemap build` fail after 60 seconds without a response instead of hanging on a stalled connection.

### Changed

- `RELEASE.md` is back, updated for the `src/` layout, with a check of the built wheel outside the checkout and the steps for publishing a `data-v<N>` release.
- The README flags the uneven quality of the neuPrint meshes: several glomeruli in the hemibrain and male CNS atlases have holes or are in multiple pieces, as published.
- The ingest dependencies are published as an extra: `pip install "lobemap[ingest]"` adds what `build`, `stain`, `ingest` and `bridge` need, now including scikit-image, pyarrow and cloud-volume, which arrived only by chance before. `pip install lobemap` stays viewer-only.
- The package metadata carries Gustavo Madeira Santana's email again.

- Spelling throughout the repository is American English. This renames one function, `normalise` to `normalize`, in `core.names` and `core.reference`; the published data files under `registry/sources/` keep their own wording.

- Replaced the viewer with a ground-up rewrite, developed separately and
  merged here. It is organized around coordinate SPACES rather than atlases:
  atlases are bridged into a space via navis-flybrains, so several can be
  compared in one scene. Ships a napari GUI (`lobemap view <space>`), OME-Zarr
  multiscale volumes, exact slice contours, per-glomerulus selection and
  labeling, virtual neuropil stains built from presynapse density, and a
  registry of atlases with canonical nomenclature anchored to Benton 2025.
- The console script is `lobemap`; the package is `src/lobemap`. The rewrite
  was called `glomviewer` while it lived in its own repository.
- Removed the previous `lobemap.py` entry point, the `lobemap` shell wrapper
  and `scripts/`, which the rewrite supersedes. They remain at tag `v0.1.4`,
  as do `docs/usage.md` and the demo media that documented them.
- The published source data the ingested assets are built from is unchanged.
  It moved from `datasets/` to `registry/sources/` later in this same
  unreleased window; see below.
- Version set to 0.2.0.dev0: the two declarations in `pyproject.toml` and
  `__init__.py` disagreed (0.0.0 and 0.1.0.dev0) and both sat below the
  released 0.1.4 on the same PyPI name.
- `lobemap --atlas <name>`, the 0.1.x way to open an atlas, says it was replaced by `lobemap view <space>` instead of failing with "invalid choice"; `lobemap spaces` points at `fetch` for assets that are not on disk; `--registry --help` names the real default.

### Added

- Grabe's `VP1` maps to `VP1` rather than to `VP1d;VP1l;VP1m`. GRABE has one atlas, so its vocabulary is that atlas and there is nothing to reconcile against; the merge was a survivor of the global Benton-anchored vocabulary that per-space vocabularies replaced, and it put three names into GRABE that its own geometry cannot tell apart. Its vocabulary is now 54 names, matching the atlas exactly, as the other two single-atlas spaces already did. The correspondence it recorded is cross-space and belongs to `lobemap reconcile`.
- The `canonical` column appears only on atlases that disagree with their space's vocabulary somewhere, and a disagreeing entry is red. Three of the six atlases carry it: the Schlegel rename chain in hemibrain, the VM6 split in S11, Grabe's VP1 merge. Compared on the bare glomerulus, so a side suffix alone is agreement rather than 77 red rows.
- The filter searches every text column, annotation included, and the placeholder says so — it named only name, canonical and side while already searching the rest.
- The panel buttons sit in two aligned rows — `Filtered`, `Show all`, `Label all`, `Fill all` above `Invert`, `Show none`, `Label none`, `Fill none` — so each column pairs an action with its opposite. `All` and `None` are renamed `Show all` and `Show none`: they were named before `Label` and `Fill` had pairs of their own, and no longer said which of the three they acted on.
- `Fill all` and `Fill none` buttons, beside `Label all` / `Label none`. `Fill all` fills whatever is currently visible, matching how `Label all` behaves.
- The home button ("Reset view to original state") restores the anatomical view: looking down A-P in the posterior direction, dorsal up. `reset_view` sets the camera angles to (0, 0, 0), which is a view down the ARRAY axes — and those are not the anatomical ones, antero-posterior being z in FAFB and y in the hemibrain — so it left the brain at an arbitrary attitude that could only be undone by reopening the scene.
- Axis indicator labels name the single pole each arrow points at — FAFB reads `R, V, P`, the hemibrain `L, A, V` — instead of a direction of travel like `A->P`. The old form was accurate but read like the name of an axis, leaving which end is which to be worked out from the arrow. A pole cannot be read as an axis name, and is derived from where its own arrow goes, so it cannot contradict it.
- A neuropil layer's tab drops the columns that only describe a glomerulus and names its column `neuropil`. It has no compartments behind it, so canonical, side and the five annotation columns were blank while the header claimed the table was about glomeruli. `label` and `fill` stay and still work.
- Table columns size to their widest cell rather than a fixed width, which was truncating the long receptor lists and padding the short ones.
- The glomerulus table sorts. Clicking a header sorts by that column, and it opens sorted by glomerulus name — naturally, so `DA10` follows `DA9` rather than `DA1`.
- A `fill` checkbox per glomerulus, beside `label`, drawing its 2D contour filled rather than as an outline. A napari `path` cannot be filled, so a filled glomerulus is added as a `polygon`; mesh–plane intersections are closed loops, so that is geometrically honest.
- Five annotation columns — `receptor(s)`, `sensillum`, `ALRN`, `organ`, `co-receptor(s)` — from `registry/reference/glomerulus_ground_truth.csv`, joined on the canonical name. Every compartment of every atlas finds a row; receptors are populated for 98% of them.
- `registry/reference/glomerulus_ground_truth.csv`, retained from the upstream `datasets/reference-tables/`.
- `lobemap pack` writes the upload-ready copies of the data artifacts. `manifest` and `fetch --check` zipped a Zarr store to hash it and then deleted the archive, so the bytes a downloader receives could not be obtained; `pack` keeps them, under the names `fetch` requests, and re-hashes each against the manifest.
- `lobemap fetch --nostains`, to skip the virtual stains.

### Changed

- The data is published as release assets and no longer ships in the repository. All fourteen artifacts (2.51 GB) are on the [`data-v1` release](https://github.com/gumadeiras/lobemap/releases/tag/data-v1), and `base_url` in the committed manifest points at them. The eleven small assets used to be tracked; splitting the rule by size left two answers to where the data lives, for the 76 MB it saved.
- `lobemap fetch` gets every artifact, including the three virtual stains. `--nostains` skips them, which is 76 MB instead of 2.5 GB; every space still opens, the three EM spaces just without their reference image. Holding them back by default made the obvious command the one that left three of the four spaces looking incomplete for no stated reason.
- `lobemap view` fetches missing required artifacts before opening a scene. Nothing runs on `uv sync`, so this is the first opportunity a fresh clone has to get its data.
- The "no data for this space" report leads with `lobemap fetch` rather than `lobemap build`.
- Reference images are visible whenever they are on disk. They were created hidden and turned back on by each default scene preset, so the default only governed a scene that did not name its own image — `hemibrain_three_ways` opened with the stain off, which nobody had chosen. A preset can still turn one off. The Grabe label volume stays off: it is a segmentation of the glomeruli the meshes already draw.

- Removed the scene concept. `registry/scenes.toml`, `Scene`, `LayerSpec`, `lobemap scenes` and `lobemap view --scene` are gone; a space is the unit the viewer opens. A scene was never a different view of the data — `build_scene` takes a space and loads every atlas native to it, and the preset was applied afterwards and set nothing but `.visible`, so two scenes on one space held identical layers. `spaces.toml` gains `primary_atlas`, replacing `default_scene`, and the rest follows from an asset's role. `lobemap spaces` now reports what each space opens with. The one preset not reproduced is `hemibrain_three_ways`, which is two clicks in the compartment panel.

- `lobemap` with no arguments opens the viewer on FAFB, rather than exiting with a usage message. `lobemap view` also takes the default.
- Removed the JRC2018U space. It held no atlas, so there was nothing to open in it, and it appeared in `lobemap spaces` as though there were.
- Removed ten unused folders from `datasets/`: banc, comparative-atlases, door, edmond-fibsem, flywire, flywire-codex, laissue-1999, potter-task-2022, reference-tables and vfb. No recipe or module read any of them. `docs/data-sources.md` is rewritten around the six atlases the viewer actually opens, and covers only those; source folders kept without being used are described in `registry/sources/`, beside the files.
- `datasets/` is gone. The five remaining folders are `registry/sources/<dataset>/`, with the redundant `data/source/` level flattened away, and the registry is now self-contained: a recipe's `source` and its path-valued params resolve against the registry root rather than the repository root, so `--registry` can point anywhere. The per-dataset napari modules and the 256-cube label caches were not carried over — they belong to the viewer this one replaced and are at tag `v0.1.4`, which holds the whole original tree.
- Removed the `hemibrain/` source folder. Its `hemibrainr` surface export is Schlegel 2021 supplementary file 12 again: the same 58 names and vertex counts, with centroids matching to 0.0013 µm. neuPrint's `VC3l`/`VC3m`/`VC5` are the older names for S12's `VC3`/`VC5`/`VM6`, not a finer subdivision. Three annotation tables went with it — receptor, ligand and valence per glomerulus, and Virtual Fly Brain FBbt terms — which were not redundant, only unused. All of it is at tag `v0.1.4`.
- `--data-root` is honoured by `validate`, `check`, `reconcile`, `bridge` and `build`, which all built a registry without it. It mattered most in `build`, which resolved its target against the default root, so building into a scratch data root overwrote the real asset.

### Fixes

- Showing a glomerulus in 2D no longer switches its mesh on underneath the slice. `AtlasSurface.refresh` turns its layer on whenever something is selected — right in 3D — and the display-mode hook only fires on an `ndisplay` change, so nothing put the mesh back. Showing now draws whichever layer the current mode can read: contours in 2D, meshes in 3D. This also fixes the other half, that showing in 2D left the contours off.
- Filling a neuropil contour no longer raises `could not convert string to float`. A layer's color is not always a sequence of numbers — the neuropil shells are the hex string `#9aa0a6`, and indexing that yields `#`. Color specs now go through napari's own parser, so names, hex and arrays all work.
- `lobemap view` no longer prints a `crash log: ...` line on every launch, and no longer leaves an empty log behind. faulthandler is still armed — a native vispy/Qt/driver fault would otherwise kill python with no trace — but it now reports only when something was written, deletes its file on a clean exit, and sweeps empties left by runs that were killed rather than exited. Measured before the change: 54 empty files out of 55 launches, against one real report. A log still held open by a live viewer cannot be unlinked, so those are skipped.
- The anatomical axis indicator is drawn as a canvas overlay rather than a scene one, so it is visible in the default view of every space. A scene overlay sits at the world origin, which is not inside the data: FAFB spans x 192-853 um, so its indicator was ~190 um off-screen, and the male CNS showed part of one.
- Removed three `*_stain.progress.log` files committed by accident.
- A data release no longer starts a PyPI workflow run. It fired on every published release and failed at the tag check, mailing a failure for a release that was never meant to build a package.
- `lobemap check --compare` pairs atlases by canonical name, so hemibrain `VC5(R)` is compared with Schlegel S12 `VM6`, not with S12 `VC5`, and `VC3l`/`VC3m` pair with `VC3`/`VC5`.
- `check --compare` and `reconcile` mirror an atlas bridged between a mirrored and a biological space, so its sides agree biologically, and refuse a source space without a mirror registration.
- `lobemap check` fails when a space is reflected left-right, when a stain is flipped on its own, and when one compartment collapses: new laterality, chirality, image orientation, label containment and compartment size checks.
- Mesh repair measures volume change about each mesh's center, so the logged change no longer depends on where the mesh sits.

### Changes

- Every data asset records its license and the page that states it, and the README separates the MIT code license from the data licenses.
- The FAFB stain cites Yu et al. 2025 for the Princeton synapse table, and its recipe records no confidence threshold, which is what the build applies.
- The README and `docs/data-sources.md` disclose three defects in the published data: hemibrain `VM2(R)`, Grabe's missing `VM6` and male CNS `AME(L)`.
- `registry/checks.toml` lists known defects that `lobemap check` reports without failing.
- `registry/reference/README.md` records how the reference table was built at `v0.1.4` and how to rebuild it.

### Notes

- Data under `registry/data/` is gitignored and fetched; `registry/manifest.toml` records what belongs there and each file's sha256. See `registry/data/README.md` for how each asset is rebuilt from source.

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
