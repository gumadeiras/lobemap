# Data Sources

lobemap is a viewer and reference table built from public atlas resources. This
page lists where the tracked data came from.

Paper PDFs are not tracked in git. Their links are listed in
[`paper_pdf_sources.csv`](../paper_pdf_sources.csv).

## Grabe 2015

Folder: [`grabe-2015/`](../grabe-2015/)

Used for the in vivo 3D antennal lobe atlas, image stack, label volume, OBJ
exports, and supplemental PN expression tables.

Main sources:

- Grabe V, Strutz A, Baschwitz A, Hansson BS, Sachse S. A digital in vivo 3D
  atlas of the antennal lobe of Drosophila melanogaster. Journal of Comparative
  Neurology. 2015. doi:10.1002/cne.23697.
- Grabe V, Baschwitz A, Dweck HKM, Lavista-Llanos S, Hansson BS, Sachse S.
  Elucidating the Neuronal Architecture of Olfactory Glomeruli in the Drosophila
  Antennal Lobe. Cell Reports. 2016. doi:10.1016/j.celrep.2016.08.063.

Tracked source files include the atlas stack, label stack, Amira labels, OBJ
archive, and extracted supplemental table images.

## Bates Schlegel 2020

Folder: [`bates-schlegel-2020/`](../bates-schlegel-2020/)

Used for the Bates Schlegel web atlas and fast napari slicing cache.

Source:

- Bates AS, Schlegel P, et al. Complete Connectomic Reconstruction of Olfactory
  Projection Neurons in the Fly Brain. Current Biology. 2020.
  doi:10.1016/j.cub.2020.06.042.

## hemibrain

Folder: [`hemibrain/`](../hemibrain/)

Used for antennal lobe glomerulus meshes.

Source:

- `hemibrainr`, from the flyconnectome project.

## FlyWire

Folder: [`flywire/`](../flywire/)

Used for FlyWire glomerulus meshes and both antennal lobe neuropil meshes.

Sources:

- FlyWire glomerulus mesh, for the annotated-side glomerulus surfaces.
- FlyWire source neuron meshes, for sensory-neuron, projection-neuron, and
  local-neuron shapes used to rebuild the other side.
- `flywire_annotations`, for neuron class, cell type, glomerulus, and side
  annotations.
- `fafbseg`, for source neuron meshes and `AL_L` and `AL_R` neuropil meshes.
- `hemibrainr`, for receptor, odor-scene, and valence summary tables used as
  metadata.
- FlyWire Codex / FlyWire v783, for coordinate conventions and release
  metadata.
- Dorkenwald S, et al. Neuronal wiring diagram of an adult brain. Nature. 2024.

The tracked glomerulus mesh files include surfaces for both FlyWire antennal
lobes. The tracked neuropil meshes are source meshes for both `AL_L` and
`AL_R`.

## DoOR

Folder: [`door/`](../door/)

Used for odor response tables, receptor mapping, sensilla, and the 2D DoOR
glomerulus map.

Source:

- Munch D, Galizia CG. DoOR 2.0: Comprehensive mapping of Drosophila
  melanogaster odorant responses. Scientific Reports. 2016.
  doi:10.1038/srep21841.

## Potter Task 2022

Folder: [`potter-task-2022/`](../potter-task-2022/)

Used for the 2D antennal lobe map and chemosensory receptor summary table.

Sources:

- Potter lab fly antennal lobe resource page:
  https://potterlab.johnshopkins.edu/resources/fly-antennal-lobe/
- Task D, Lin C-C, Vulpe A, Afify A, Ballou S, Brbic M, Schlegel P, Raji J,
  Jefferis GSXE, Li H, Menuz K, Potter CJ. Chemoreceptor Co-Expression in
  Drosophila Olfactory Neurons. eLife. 2022. doi:10.7554/eLife.72599.

## Virtual Fly Brain

Folder: [`vfb/`](../vfb/)

Used for glomerulus names, FBbt IDs, definitions, synonyms, and VFB links.

Source:

- Virtual Fly Brain: https://www.virtualflybrain.org/

## FlyWire Codex

Folder: [`flywire-codex/`](../flywire-codex/)

Used for FlyWire v783 release metadata and proofread root IDs.

Source:

- FlyWire Whole-brain Connectome Connectivity Data. Zenodo.
  doi:10.5281/zenodo.10676866.

## Other Reference Resources

These folders hold paper links, metadata, or reference notes:

- [`benton-2025/`](../benton-2025/)
- [`comparative-atlases/`](../comparative-atlases/)
- [`edmond-fibsem/`](../edmond-fibsem/)
- [`laissue-1999/`](../laissue-1999/)

Large paper PDFs are local-only and ignored by git unless the file is a small
source data file that can be shared.
