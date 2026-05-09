# BANC

BANC is the Brain And Nerve Cord fly connectome.

lobemap includes BANC as a resource dataset. It links to public BANC browsers and
tracks the left and right olfactory Neuroglancer states from the BANC repository.
It does not include antennal-lobe glomerulus meshes because a public BANC
glomerulus surface atlas was not found.

Run:

```bash
./lobemap --atlas banc
```

Refresh source links and olfactory Neuroglancer state files:

```bash
uv run python banc/scripts/download_banc_resources.py
```

Primary sources:

- BANC wiki: https://github.com/jasper-tms/the-BANC-fly-connectome/wiki
- BANC Neuroglancer states:
  https://github.com/jasper-tms/the-BANC-fly-connectome/tree/main/neuroglancer_states
- BANC data bucket:
  https://console.cloud.google.com/storage/browser/lee-lab_brain-and-nerve-cord-fly-connectome
- BANC Dataverse:
  https://dataverse.harvard.edu/dataset.xhtml?persistentId=doi:10.7910/DVN/8TFGGB
- Phelps JS, et al. Distributed control circuits across a brain-and-cord
  connectome. bioRxiv. 2025. doi:10.1101/2025.07.31.667571.
