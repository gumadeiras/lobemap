"""Image and label layers: the reference imagery under the meshes.

The LM template, the virtual synapse stains and the Grabe label volume, with
the display defaults each role needs and the pyramid level 3D pins.
"""

from __future__ import annotations

import numpy as np

#: Per-role display defaults for image layers.
#:
#: Magenta for the stain because it reads as a fluorescence channel against
#: the gray template and the colored surfaces, and because additive blending
#: composites it cleanly over them.
#:
#: `gamma` below 1 lifts the dim end, which a synapse-density map needs: the
#: distribution is long-tailed, so a linear ramp leaves most of the neuropil
#: near black while a few bright spots hold the top of the range.
#:
#: `attenuation` only does anything under `attenuated_mip`, where it fades
#: contributions by depth. Plain MIP through a whole brain is a flat wash of
#: whichever voxel happens to be brightest along each ray; attenuation
#: restores the sense of depth that makes the structure legible.
ROLE_DISPLAY = {
    "template_image": {"colormap": "gray"},
    "virtual_stain": {
        # Gray, not a hue. These are reference imagery under colored
        # glomeruli, and a magenta wash tinted every mesh drawn over it.
        "colormap": "gray",
        "gamma": 0.7,
        "rendering": "attenuated_mip",
        "attenuation": 0.1,
    },
}
DEFAULT_DISPLAY = {"colormap": "magma"}

#: Applied to every image layer unless a role overrides it.
BASE_DISPLAY = {
    "colormap": "magma",
    "blending": "additive",
    "rendering": "attenuated_mip",
}


def display_for(role: str, colormap: str | None = None,
                overrides=None) -> dict:
    """napari keyword arguments for an image layer of this role."""
    out = dict(BASE_DISPLAY)
    out.update(ROLE_DISPLAY.get(role, DEFAULT_DISPLAY))
    out.update(dict(overrides or {}))
    if colormap:
        out["colormap"] = colormap
    return out


ROLE_COLORMAP = {role: spec["colormap"] for role, spec in ROLE_DISPLAY.items()}
DEFAULT_COLORMAP = DEFAULT_DISPLAY["colormap"]

#: In 3D napari renders ONE multiscale level and, left to itself, picks the
#: coarsest -- 83x41x34 for the FAFB stain, which is unreadable. These bound
#: the level it is pinned to instead. 700 M voxels is just above the ~537 M of
#: a 2048x2048x128 confocal stack, which renders comfortably; 2048 is the 3D
#: texture limit a GPU is allowed to impose, and level 0 exceeds it at 2818.
VIEW3D_MAX_VOXELS = 700_000_000
VIEW3D_MAX_AXIS = 2048


def level_for_3d(levels, max_voxels=VIEW3D_MAX_VOXELS, max_axis=VIEW3D_MAX_AXIS):
    """Finest pyramid level that will render as a single 3D texture."""
    for i, arr in enumerate(levels):
        shape = tuple(arr.shape)
        if np.prod(shape, dtype=np.int64) <= max_voxels and max(shape) <= max_axis:
            return i
    return len(levels) - 1


def default_colormap(role: str) -> str:
    return ROLE_COLORMAP.get(role, DEFAULT_COLORMAP)


def add_images(viewer, registry, space: str) -> list:
    """Reference images: the LM template, and the virtual synapse stain.

    scale and translate come from the Volume itself, so the image sits in the
    same micrometer world as the meshes. Getting either wrong yields a
    plausible picture that is simply in the wrong place, which is why the
    stain has its own alignment validator.
    """
    layers = []
    for asset in registry.assets_in_space(space):
        if asset.kind not in ("image", "labels") or not asset.path.exists():
            continue
        volume = registry.volume(asset.id)

        if asset.kind == "labels":
            # A segmentation, not an intensity image: napari colors it by id
            # and picks values rather than interpolating them, so none of the
            # colormap/gamma/rendering defaults apply.
            layer = viewer.add_labels(
                np.asarray(volume.data),
                name=asset.id,
                # Off, unlike the images above: this is a segmentation of
                # the same glomeruli the meshes already draw, so showing
                # both by default draws each one twice.
                visible=False,
                opacity=0.6,
                **volume.napari_kwargs(),
            )
            layer.metadata["lobemap"] = {
                "kind": "labels",
                "role": asset.role,
                # Written at ingest: voxel value -> the name the matching
                # mesh carries, which is what lets the two be colored alike.
                "label_names": {
                    int(k): v
                    for k, v in (volume.meta.get("label_names") or {}).items()
                },
            }
            layers.append(layer)
            continue

        data = volume.napari_data()
        layer = viewer.add_image(
            data,
            multiscale=volume.is_multiscale,
            name=asset.id,
            # Visible if it is here at all. These are backdrops -- the
            # confocal channel, the synapse-density stain -- and a scene
            # reads as incomplete without one. They used to be created
            # hidden and turned on again by every default scene preset,
            # so the default only ever applied to a scene that forgot to
            # mention its own image: `hemibrain_three_ways` opened with
            # the stain off for no reason anyone chose. A preset that
            # wants one off can still say `visible = false`.
            #
            # Nothing here is conditional on the asset being built: this
            # loop skips what is not on disk, so an absent stain is an
            # absent layer rather than an invisible one.
            visible=True,
            **display_for(asset.role, asset.colormap, asset.display),
            **volume.napari_kwargs(),
        )
        layer.metadata["lobemap"] = {
            "kind": "image",
            "role": asset.role,
            "level_3d": level_for_3d(data) if volume.is_multiscale else 0,
        }
        layers.append(layer)
    return layers


__all__ = [
    "BASE_DISPLAY",
    "DEFAULT_COLORMAP",
    "ROLE_DISPLAY",
    "VIEW3D_MAX_AXIS",
    "VIEW3D_MAX_VOXELS",
    "add_images",
    "default_colormap",
    "display_for",
    "level_for_3d",
]
