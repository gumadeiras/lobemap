# JRC2018Unisex

The unbiased whole-brain template of the JRC 2018 set, with Virtual Fly Brain's
ROI label volumes:

Bogovic JA, et al. An unbiased template of the Drosophila brain and ventral
nerve cord. *bioRxiv*, 2019. doi:10.1101/376384

- VFB JRC 2018 templates and ROIs: https://www.virtualflybrain.org/reports/JRC2018
- VFB template concepts: https://www.virtualflybrain.org/docs/concepts/templates/

**Nothing in the registry reads this.** A `JRC2018U` space existed and was
removed: no atlas was native to it, so there was nothing to open there, and it
appeared in `lobemap spaces` beside four spaces that work. Kept because it is
the standard light-microscopy target space — anything warped between LM and EM
would go through it — and because it carries a real nc82 channel, which is what
the virtual stains approximate.

## What is here

- `vfb/VFB_*.nrrd` — per-ROI label volumes and the template channel, at
  0.519 × 0.519 × 1.0 µm with diagonal `space directions`.
- `jrc2018unisex_roi_labels.npz` — the ROI volumes composed into one label
  array.
- `jrc2018unisex_rois.csv` — the ROI names behind those label values.
