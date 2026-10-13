"""Where each layer of a scene goes in napari's layer list, which is the
order napari draws them in.

`scene_ranks` gives each layer of a scene its place, and `stack` puts them
there, under every layer the user added.
"""

from __future__ import annotations


def scene_ranks(parts: dict, primary, surfaces: dict, contours: dict, images,
                standins=None, placed=()) -> dict[int, tuple]:
    """Each layer's place in a scene's stack, by `id`: higher is drawn later,
    over the lower, and listed higher in the layer list.

    Bottom first: the brain maps -- the stain or the confocal image, then
    the label volume, which under the confocal image could not be seen --
    then your images, over the maps they are compared with; then each
    neuropil set, then your neurons, then each glomerulus atlas, the primary
    one on top. Each part's outlines sit right over its 3D layer, so the two
    are one entry in the list: 2D draws the one and 3D the other. A stand-in
    (`deferred`) holds the place of the 3D layer it becomes. `primary` is
    the primary atlas's scene key, or None. A surface that is no part of the
    space is yours: your neurons (`yours`). `placed` are your images
    (`placed.PlacedImage`).

    Your neurons are under the glomeruli, drawn first, so a neurite inside
    a glomerulus shows through it: drawn after, it failed the depth test
    against the glomerulus's front face.
    """
    shells = [name for name, part in parts.items() if part.reference]
    atlases = sorted((name for name, part in parts.items() if not part.reference),
                     key=lambda name: name != primary)
    place = {}
    for group, names in ((1, shells), (3, atlases)):
        for i, name in enumerate(names):
            place[name] = (group, len(names) - i)       # the first listed on top
    for name in surfaces:
        place.setdefault(name, (2, 0))
    yours = {id(layer) for image in placed for layer in image.layers}
    maps = sorted((layer for layer in images if id(layer) not in yours),
                  key=lambda layer: layer.metadata.get("lobemap", {}).get("kind") == "labels")
    ranks = {id(layer): (0, i, 0) for i, layer in enumerate(maps)}
    for k, image in enumerate(placed):
        for j, layer in enumerate(image.layers):
            ranks[id(layer)] = (0, len(maps) + k, j)
    for name, surface in surfaces.items():
        ranks[id(surface.layer)] = (*place[name], 0)
    for name, overlay in contours.items():
        ranks[id(overlay.layer)] = (*place[name], 1)
    for name, layer in (standins or {}).items():
        ranks[id(layer)] = (*place[name], 0)
    return ranks


def stack(viewer, ranks: dict[int, tuple]) -> None:
    """Put a scene's layers in the order of their `ranks`, under every other
    layer: one the user added stays on top, where napari put it.

    Beside the scene a switch replaces, the new one goes under it until it
    is gone. napari redraws the stack once, after the last move, as its own
    `move_multiple` has it do; that method is not used because its plan of
    moves lost track of the indices for some orders, and moved past the end.
    """
    layers = viewer.layers
    ours = sorted((layer for layer in layers if id(layer) in ranks),
                  key=lambda layer: ranks[id(layer)])
    if [layers.index(layer) for layer in ours] == list(range(len(ours))):
        return
    with layers.events.reordered.blocker():
        for place, layer in enumerate(ours):
            layers.move(layers.index(layer), place)
    layers.events.reordered(value=layers)


__all__ = ["scene_ranks", "stack"]
