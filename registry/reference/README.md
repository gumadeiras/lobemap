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
