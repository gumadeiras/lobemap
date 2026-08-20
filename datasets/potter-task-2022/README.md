# Potter / Task 2022 AL reference map

Reference material for the chemosensory co-receptor model of the Drosophila
antennal lobe.

Source page:

https://potterlab.johnshopkins.edu/resources/fly-antennal-lobe/

Primary citation:

Task D, Lin C-C, Vulpe A, Afify A, Ballou S, Brbic M, Schlegel P, Raji J,
Jefferis GSXE, Li H, Menuz K, Potter CJ. Chemoreceptor Co-Expression in
Drosophila Olfactory Neurons. eLife. 2022;11:e72599.
doi:10.7554/eLife.72599.

Downloaded source files:

- `data/source/Task-Potter-eLife-Drosophila-Antennal-Lobe-Map-2022.pdf`
- `data/source/Task-Potter-eLife-Drosophila-Antennal-Lobe-Map-2022.eps`
- `data/source/Task-Potter-eLife-Drosophila-Antennal-Lobe-Map-2022.ai.ps`
- `data/source/Task-Potter-Fly-AL-Summary-Table.docx`

These are 2D document/vector reference files, not 3D glomerulus volumes for
napari slicing.

Run the 2D map in napari:

```bash
./lobemap --atlas potter-task-2022
```

The napari view uses the source PDF to create `data/derived/potter_task_2022_map.png`.
That generated preview is tracked so the viewer works from a fresh checkout,
and can be rebuilt from the repo root:

```bash
uv run python scripts/regenerate_visual_data.py
```
