# Reference table

`glomerulus_ground_truth.csv` has one row per canonical glomerulus (62 rows, 49 columns): receptors, sensilla, odour scenes, valence, driver-line expression, Virtual Fly Brain terms, and which datasets contain the glomerulus. The viewer joins its annotation columns to the compartment panel by glomerulus name (`lobemap.core.reference`).

## The table is frozen

This file is byte-identical to `datasets/reference-tables/glomerulus_ground_truth.csv` at tag [`v0.1.4`](https://github.com/gumadeiras/lobemap/tree/v0.1.4/datasets/reference-tables). It was built there by `datasets/reference-tables/scripts/build_glomerulus_ground_truth.py` from source tables that this tree no longer carries, so nothing here regenerates it and it must not be edited by hand. A change to its content means changing the builder or its inputs at `v0.1.4` and copying the result here.

## What it was built from

The builder read these files, all under `datasets/` at `v0.1.4`:

| columns | source file | publication |
|---|---|---|
| `receptor_benton_2025`, `sensillum_benton_2025`, `sensory_organ_benton_2025`, `neuron_name_benton_2025`, `essential_coreceptor_benton_2025`, `key_agonists_benton_2025`, `sensory_scene_benton_2025` | `benton-2025/data/source/44319_2025_476_MOESM2_ESM.xlsx` (Dataset EV1) | Benton et al. 2025, doi:10.1038/s44319-025-00476-8 |
| `receptor_potter_task_2022`, `sensillum_potter_task_2022`, `orco_t2a_qf2`, `ir8a_t2a_qf2`, `ir76b_t2a_qf2`, `ir25a_t2a_qf2` | `potter-task-2022/data/source/Task-Potter-Fly-AL-Summary-Table.docx` | Task et al. 2022, doi:10.7554/eLife.72599 |
| `receptor_door`, `sensillum_door`, `sensory_organ_door`, `co_receptor_door` | `door/data/source/door_mappings.csv` | Münch and Galizia 2016, doi:10.1038/srep21841 |
| `orco_gal4_grabe_2015` | `grabe-2015/data/source/grabe_2015_sensory_line_expression.csv` (Table 1) | Grabe et al. 2015, doi:10.1002/cne.23697 |
| `gh146_gal4`, `gh146_pn_female`, `gh146_pn_male`, `chat_gal4`, `chat_soma_count`, `chat_adpn`, `chat_lpn`, `chat_vpn`, `projection_neuron_lines`, `projection_neuron_line_source` | `grabe-2015/data/source/grabe_2015_pn_expression.csv` | Grabe et al. 2015 Table 1 (GH146-GAL4); Grabe et al. 2016 Tables S1 and S2, doi:10.1016/j.celrep.2016.08.063 |
| `receptor_odour_scenes`, `sensillum_odour_scenes`, `key_ligand`, `odour_scene`, `valence` | `hemibrain/data/source/odour_scenes.csv` | the `odour_scenes` table of `hemibrainr` 0.5.0 |
| `fbbt_id`, `vfb_name`, `vfb_synonyms` | `hemibrain/data/source/vfb_glomerulus_terms.csv` | [Virtual Fly Brain](https://www.virtualflybrain.org/) |
| `present_*` | the glomerulus list of each dataset folder, including `grabe-2015/data/derived/al_atlas_materials.csv` and the Bates 2020 interactive atlas | as above |

The `*_consensus` and `sensory_neuron_lines` columns are merged by the builder from the source-specific ones, and `projection_neuron_lines` summarizes the Grabe line columns. `datasets/reference-tables/README.md` at `v0.1.4` describes the merge rules.

## Rebuilding

From a checkout of the tag, not from this tree:

```bash
git worktree add ../lobemap-v0.1.4 v0.1.4
cd ../lobemap-v0.1.4
uv sync
uv run python datasets/reference-tables/scripts/build_glomerulus_ground_truth.py
cmp datasets/reference-tables/glomerulus_ground_truth.csv <this repository>/registry/reference/glomerulus_ground_truth.csv
```

On 2026-09-29 the unmodified builder reproduced this file byte for byte (pandas 3.0.6, numpy 2.5.3).

## Terms

The table compiles values from the publications above, and each value keeps the terms of its source. The MIT License of the code does not cover it; see "Data licenses" in the top-level README.

# Neuropil names

`neuropil_names.csv` gives the full name of every neuropil in the three neuropil sets (`fafb_neuropil`, `neuprint_hemibrain_neuropil`, `neuprint_cns_neuropil`), keyed on the name each set uses without its side suffix: FlyWire's `AL_L` and neuPrint's `AL(R)` are both `AL`. Where the two spell one structure differently, both spellings have a row with the same full name: FlyWire's `MB_PED` and neuPrint's `PED` are both "mushroom body pedunculus". The viewer shows the full name and its source in the details of a neuropil tab (`lobemap.core.reference.neuropil_names`). Unlike the table above, this one is written by hand, and every name in it is taken from a primary source:

| names | source | where |
|---|---|---|
| all but `AB` and `OCG` | Ito K, Shinomiya K, Ito M, Armstrong JD, Boyan G, Hartenstein V, et al. (2014) A systematic nomenclature for the insect brain. Neuron 81(4):755–765, doi:[10.1016/j.neuron.2013.12.017](https://doi.org/10.1016/j.neuron.2013.12.017) | Supplemental Information (Document S1): Table S2 for the neuropils, Table S3 for `GA` and the mushroom body lobes (`a'L`, `aL`, `b'L`, `bL`, `gL`). `AVLP` and `PVLP`, which Table S2 abbreviates as "anterior VLP" and "posterior VLP", are written out as in its Appendix. |
| `AB` | Scheffer LK, Xu CS, Januszewski M, et al. (2020) A connectome and analysis of the adult Drosophila central brain. eLife 9:e57443, doi:[10.7554/eLife.57443](https://doi.org/10.7554/eLife.57443) | Table 1, "Asymmetrical body", under the central complex. Ito et al. 2014 names no such neuropil. |
| `OCG` | Schlegel P, Yin Y, Bates AS, et al. (2024) Whole-brain annotation and multi-connectome cell typing of Drosophila. Nature 634:139–152, doi:[10.1038/s41586-024-07686-5](https://doi.org/10.1038/s41586-024-07686-5) | Fig. 1b legend, "OCG, ocellar ganglion". Ito et al. 2014 does not list it. |

Which dataset name is which structure was checked against the datasets' own lists: Table 1 of Scheffer et al. 2020 for the neuPrint names (`CA`, `PED` and the lobes `a'L` "alpha prime lobe" to `gL` "gamma lobe"), and Extended Data Fig. 1 of Dorkenwald S, et al. (2024) Neuronal wiring diagram of an adult brain, Nature 634:124–138, doi:[10.1038/s41586-024-07558-y](https://doi.org/10.1038/s41586-024-07558-y) for the FlyWire names (`MB_CA` calyx, `MB_PED` pedunculus, `MB_VL` vertical lobe, `MB_ML` medial lobe, `OCG`). Every part of the mushroom body is named as one, "mushroom body calyx", as Ito's Table 1 nests it under the mushroom body, and the lobe names keep Ito's Greek letters, with U+2032 for the prime. `AB` is lowercased to match the rest; nothing else is reworded.

Every neuropil in the three sets has a row; `tests/test_neuropil_names.py` checks that, and lists any name that is added to a set without one.
