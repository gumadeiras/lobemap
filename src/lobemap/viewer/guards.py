"""What napari's layer list may do to lobemap's own layers, and why not.

lobemap's layers are drawn from the atlases and the images: the panel ticks
their rows, and the mirror, the flip and the rotation move them. napari's
layer list can delete, copy and link layers, and none of those can follow:

- **Delete** is refused by napari's lock (`chrome.lock_layers`) on every
  route -- the delete button, ⌘⌫ and ⌘⌦, ⌫ and ⌦ in the layer list -- and
  napari said only that the layers are locked. lobemap says why instead
  (`KEPT`), and the layers you added still delete.
- **Duplicate**, and a **projection** of an image, made a copy that kept
  lobemap's mark, so it was locked and could not be deleted, did not follow
  the mirror, kept a turn that Reset rotation gave back to the original, and
  outlived a switch to another brain. Such a copy is not added, and lobemap
  says why (`NOT_COPIED`). napari's own conversions, splits and merges are
  already off for a locked layer.
- **Link layers** tied an atlas's 3D and outline layers together, and after
  one trip between 3D and Slice view the atlas was drawn in neither. A link
  that takes in one of lobemap's layers is refused (`NOT_LINKED`).

A layer of lobemap's is known by the `lobemap` metadata its maker writes once
napari has added it, so a layer that arrives to be added already marked is a
copy.

Layers you add are yours, and none of this touches them; they are not
mirrored, flipped or turned with the brain.
"""

from __future__ import annotations

import weakref

KEPT = (
    "{names} stay: lobemap's layers are part of the brain shown, drawn from "
    "its atlases and images. To hide one, click its eye, or untick its rows in "
    "the panel."
)
NOT_COPIED = (
    "{names} cannot be copied: a copy of one of lobemap's layers would not "
    "follow the panel, the mirror, the flip or the rotation."
)
NOT_LINKED = (
    "{names} cannot be linked: lobemap shows and hides its own layers as the "
    "panel and the view need, and a link would hide them for good."
)

#: The viewers whose layer list is guarded; see `guard_layers`.
_GUARDED: weakref.WeakSet = weakref.WeakSet()


def ours(layer) -> bool:
    """Whether `layer` is one of lobemap's own."""
    return "lobemap" in getattr(layer, "metadata", {})


def _names(layers) -> str:
    return ", ".join(repr(layer.name) for layer in sorted(layers, key=lambda x: x.name))


def guard_layers(viewer) -> None:
    """Refuse napari's delete, copy and link of lobemap's layers, with a reason;
    once per viewer.

    On the viewer's own layer list: `remove_selected`, `link_layers` and
    `insert` are wrapped on the instance, which napari's actions and keys
    call; `append` inserts through it too.
    """
    if viewer in _GUARDED:
        return
    _GUARDED.add(viewer)
    layers = viewer.layers
    remove_selected, link_layers = layers.remove_selected, layers.link_layers
    insert = layers.insert

    def _remove_selected() -> None:
        from napari.utils.notifications import show_info

        kept = [layer for layer in layers.selection if ours(layer)]
        if not kept:
            remove_selected()
            return
        show_info(KEPT.format(names=_names(kept)))
        if len(kept) == len(layers.selection):
            return
        # The user's layers go as napari deletes them; lobemap's stay, and
        # are what is selected after, as napari leaves a locked layer.
        layers.selection.difference_update(kept)
        remove_selected()
        layers.selection.clear()
        layers.selection.update([layer for layer in kept if layer in layers])

    def _link_layers(chosen=None, attributes=()) -> None:
        from napari.utils.notifications import show_info

        chosen = list(layers if chosen is None else chosen)
        refused = [layers[layer] if isinstance(layer, str) else layer for layer in chosen]
        refused = [layer for layer in refused if ours(layer)]
        if refused:
            show_info(NOT_LINKED.format(names=_names(refused)))
            return
        link_layers(chosen, attributes)

    # A layer the list has held before may come back, as a reorder by slice
    # puts it; a copy is new.
    held = weakref.WeakSet(layers)
    layers.events.inserted.connect(lambda event: held.add(event.value))

    def _insert(index: int, layer) -> None:
        from napari.utils.notifications import show_info

        if ours(layer) and layer not in held:
            show_info(NOT_COPIED.format(names=_names([layer])))
            return
        insert(index, layer)

    layers.remove_selected = _remove_selected
    layers.link_layers = _link_layers
    layers.insert = _insert


__all__ = ["KEPT", "NOT_COPIED", "NOT_LINKED", "guard_layers", "ours"]
