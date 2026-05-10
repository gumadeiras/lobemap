# Reference Tables

Cross-dataset tables for glomerulus names and receptor metadata.

Files:

- `glomerulus_ground_truth.csv`: one row per canonical glomerulus with
  receptors, sensilla, odor scenes, valence, direct line labels, VFB IDs, and
  dataset presence flags.
- `glomerulus_name_reconciliation.csv`: source names mapped to canonical
  glomerulus names, including combined or legacy labels.

`glomerulus_ground_truth.csv` columns: `canonical_glomerulus`,
`receptor_consensus`, `receptor_benton_2025`,
`receptor_potter_task_2022`, `receptor_odour_scenes`, `receptor_door`,
`sensillum_consensus`, `sensory_organ_consensus`, `sensillum_benton_2025`,
`sensory_organ_benton_2025`, `sensillum_potter_task_2022`,
`sensillum_odour_scenes`, `sensillum_door`, `sensory_organ_door`,
`neuron_name_benton_2025`, `essential_coreceptor_benton_2025`,
`co_receptor_door`, `orco_gal4_grabe_2015`, `orco_t2a_qf2`,
`ir8a_t2a_qf2`, `ir76b_t2a_qf2`, `ir25a_t2a_qf2`,
`key_agonists_benton_2025`, `sensory_scene_benton_2025`, `key_ligand`,
`odour_scene`, `valence`, `fbbt_id`, `vfb_name`, `vfb_synonyms`,
`projection_neuron_lines`, `projection_neuron_line_source`, `gh146_gal4`,
`gh146_pn_female`, `gh146_pn_male`, `chat_gal4`, `chat_soma_count`,
`chat_adpn`, `chat_lpn`, `chat_vpn`, `sensory_neuron_lines`,
`present_grabe_2015`, `present_hemibrain`, `present_flywire`,
`present_door_map`, `present_door_mappings`, `present_potter_task_2022`,
`present_benton_2025`, `present_bates_schlegel_2020`.

Rebuild from source files:

```bash
uv run python reference-tables/scripts/build_glomerulus_ground_truth.py
```

Notes:

- Sensory line columns come from Grabe 2015 Table 1 and the Potter/Task 2022
  summary table. `sensory_neuron_lines` summarizes receptor-line columns such
  as `orco_gal4_grabe_2015`, `orco_t2a_qf2`, and the Ir T2A-QF2 lines.
- Benton 2025 columns come from Dataset EV1 and are kept as source-specific
  receptor, co-receptor, sensillum, neuron-name, agonist, and sensory-scene
  metadata.
- Sensory-organ columns classify sensilla as `antenna`, `maxillary palp`, or
  `arista` from Benton sensillum prefixes and DoOR sensillum types.
- Projection-neuron line columns use the Grabe 2015 supplemental tables. GH146
  comes from Table S1, and ChAT comes from Table S2.
- Valence and odor-scene columns come from the Bates/Schlegel source table.
- VFB identifiers come from the local VFB export.
- Projection-neuron line columns are left blank unless a source directly maps
  that line to a glomerulus. Broad line labels are not filled into every row.
