"""Anatomical names for napari's own axis indicator.

Every space in this project uses different array axes for the same anatomy --
the antero-posterior axis is z in FAFB and the male CNS but y in the
hemibrain -- and each may run either way along them. So "which way is
anterior" is not something a reader can carry between scenes, and without
this the only thing that knew it was the camera.

napari already draws an axis indicator, so the job here is only to name it:
`dims.axis_labels` becomes the anatomy and the overlay is switched on.

Each label is the single pole its own arrow POINTS AT. The indicator draws
one arrow per array axis, always along INCREASING index, and which pole
that reaches differs per space -- FAFB's third axis runs posterior while
the hemibrain's second runs anterior -- so the labels differ too: FAFB
reads R, V, P and the hemibrain L, A, V.

They used to read as a direction of travel, "A->P". That was accurate and
still misread: it looks like the NAME of an axis, and naming the axis
leaves which end is which to be worked out from the arrow. A label that
names one pole cannot be read as an axis name, and cannot contradict the
arrow it sits on, because it is derived from where that arrow goes.

Labeling every arrow `A`, `D`, `L` regardless was considered and is not
possible here: `CanvasAxesOverlay` has no way to reverse an arrow, so on
FAFB's third axis the label would point opposite to the arrow under it --
the same disagreement that got the old Vectors layer removed, below.

napari 0.9 offers two: a SCENE overlay drawn at the world origin, and a
CANVAS overlay anchored in a corner. This uses the canvas one, because the
world origin is not inside the data. Spaces are in the coordinates their
volume was published in, and only some of them start at zero: FAFB's stain
spans x 192-853 um, so an indicator at the origin sits ~190 um outside
everything on screen and the default view simply does not contain it. The
male CNS starts at 37 um and showed part of one. Anchoring to the canvas
makes it independent of where the data happens to sit, and of pan and
zoom.

There used to be a second, world-space `anatomical axes` Vectors layer here
as well, colored per anatomical axis and pointing at each positive pole.
Two indicators for one thing was already redundant, and worse, they
disagreed: because its arrows pointed at the anatomical pole rather than up
the array axis, they ran OPPOSITE to the overlay's in 8 of the 12
space/axis combinations -- in FAFB the overlay's z arrow points posterior
while the layer's A-P arrow pointed anterior. It was removed rather than
reconciled, since the overlay's direction is fixed by construction.

The poles come from `core.model.anatomical_axes`, which documents how the
lateral direction was measured.
"""

from __future__ import annotations

import contextlib

import numpy as np

from ..core.model import (
    anatomical_triad,
)


def axis_labels_for(space) -> tuple[str, ...] | None:
    """The pole each ANATOMICAL arrow points at, in arrow order.

    Chosen with the arrows themselves, to put each as near as it can be
    to its own world basis vector -- see `core.model.anatomical_triad`.
    So these move with the angle, and a space turned far enough reports
    a different set. They name the second triad only; napari's own is
    always x/y/z.
    """
    triad = anatomical_triad(space)
    return None if triad is None else triad[1]


def label_viewer_axes(viewer, space) -> bool:
    """Name the sliders anatomically and show napari's axis overlay.

    The labels are the part that matters and they work in 2D as well as 3D,
    because they are the slider names rather than geometry. They are also
    independent of the overlay: turning the overlay off would not cost them.
    """
    labels = axis_labels_for(space)
    if labels is None:
        return False
    # napari TRUNCATES a label tuple longer than `ndim`, keeping the tail, so
    # on a viewer that is still 2D three labels silently become two and land
    # on the wrong axes -- D->V onto x and A->P onto y. Refuse instead: this
    # runs at the end of `build_scene`, by which point the layers have made
    # the viewer 3D, and a viewer that is not is not one these labels
    # describe.
    if getattr(viewer.dims, "ndim", 3) != len(labels):
        return False
    try:
        viewer.dims.axis_labels = labels
    except Exception:            # noqa: BLE001 - cosmetic, never fatal
        return False
    # The canvas overlay, not the scene one: see the module docstring.
    # napari 0.9 deprecated `viewer.axes`; the pin guarantees this path.
    overlay = viewer.canvas.overlays["axes"]
    with contextlib.suppress(Exception):
        overlay.visible = True
        overlay.labels = True
    return True


def _vispy_axes_overlay(viewer):
    """napari's own axes OVERLAY, or None.

    Reached through the canvas's overlay map rather than rebuilt, because
    the whole point is to keep napari's triad -- its geometry, arrowheads,
    colors, sizing and font -- and change only where it points.
    """
    model = viewer.canvas.overlays["axes"]
    canvas = None
    with contextlib.suppress(Exception):
        canvas = viewer.window._qt_viewer.canvas
    if canvas is None:
        return None
    for vispy in getattr(canvas, "_viewer_overlay_to_visual", {}).get(model, []):
        if getattr(getattr(vispy, "node", None), "axes", None) is not None:
            return vispy
    return None


def _vispy_axes_node(viewer):
    """The triad visual itself."""
    overlay = _vispy_axes_overlay(viewer)
    return None if overlay is None else overlay.node.axes


def _table(*hexes):
    """A vispy color table from hex colors given for x, y, z.

    Reversed, because the visual indexes the table by `ndim - 1 - axis`
    rather than by the axis: entry 0 is the LAST array axis. Doubled to
    six entries, which is the length the visual takes a modulo against.
    """
    rows = []
    for text in hexes:
        h = text.lstrip("#")
        rows.append([int(h[i:i + 2], 16) / 255.0 for i in (0, 2, 4)] + [1.0])
    rows = rows[::-1]
    return rows + rows


#: Okabe-Ito, which stays distinguishable to a color-blind reader. One
#: triple names the voxel grid, the other the anatomy, so the two triads
#: never share a color.
VOXEL_COLORS = _table("#56B4E9", "#CC79A7", "#F0E442")
ANATOMY_COLORS = _table("#D55E00", "#009E73", "#0072B2")

#: napari's triad names the ARRAY axes, which is also what the dimension
#: sliders step, so these are the labels whatever the display mode.
VOXEL_LABELS = ("x", "y", "z")

#: Where the second triad is kept. It hangs off napari's own vispy
#: overlay rather than off the viewer, so it dies with the canvas.
_ANATOMY_ATTR = "_lobemap_anatomy_axes"


def _anatomy_triad(overlay):
    """The second triad, created on first use.

    A second `Axes` parented into the overlay's own ViewBox, so it
    shares the origin, the camera and the corner anchoring with
    napari's -- the two turn together and stay the same size, which is
    the whole reason for putting it there rather than in the scene.
    """
    from napari._vispy.visuals.axes import Axes

    node = getattr(overlay, _ANATOMY_ATTR, None)
    if node is not None and node.parent is overlay.node.scene:
        return node
    node = Axes(font_info=overlay._font_info)
    node._default_color = ANATOMY_COLORS
    node.parent = overlay.node.scene
    setattr(overlay, _ANATOMY_ATTR, node)
    return node


def _reflection_4x4(axis: int, displayed=(0, 1, 2)) -> np.ndarray:
    """A reflection along one ARRAY axis, in vispy's geometry order.

    napari draws arrow k of its triad for array axis `displayed[::-1][k]`,
    along vispy axis k, so the reflection goes on whichever vispy axis
    carries `axis` in the current mode. In 3D that is the reversal of the
    array order; in 2D it is the column axis for x. Taking 3D's answer in
    2D reflected a vispy axis that does not exist there, so the x arrow
    kept pointing the unmirrored way. An axis that is not displayed -- a
    slice stepping along it -- has no arrow to reflect.
    """
    mat = np.eye(4)
    order = list(displayed)[::-1]
    if axis in order:
        k = order.index(axis)
        mat[k, k] = -1.0
    return mat


def apply_axis_mode(viewer, space, mirror_axis: int | None = None) -> str:
    """Two triads in 3D; only napari's own in 2D. Returns what is shown.

    `mirror_axis` is the array axis the scene is being displayed
    reflected along, or None. Both triads are reflected to match, so
    each arrow keeps pointing the way the data under it now runs -- and
    the anatomical labels come from the reflected frame, so the lateral
    one reads R where it read L. Leaving them alone instead would put
    an unmirrored triad over mirrored data, which is the one failure
    this indicator exists to prevent.

    napari's triad is left exactly as it comes: the ARRAY axes, x/y/z,
    cyan/magenta/yellow. The anatomy is a SECOND triad beside it, turned
    onto the measured frame, red/green/blue, labeled A, D and R or L.

    Two rather than one because they are two different facts and both
    are worth having. Turning napari's own onto the anatomy, as an
    earlier version did, left nothing showing where the voxel grid ran
    -- and in 2D it was worse than nothing, because a slice is cut along
    array axes, which are 15-31 degrees off the anatomy in every space
    here, so an anatomical label there claimed an alignment the slice
    does not have.

    So the anatomical triad is hidden in 2D. What stays is napari's,
    naming the axes the slider actually steps.
    """
    from vispy.visuals.transforms import MatrixTransform, NullTransform

    three_d = getattr(viewer.dims, "ndisplay", 3) == 3
    triad = anatomical_triad(space, reflect_axis=mirror_axis)
    show_anatomy = bool(three_d and triad is not None)

    if getattr(viewer.dims, "ndim", 3) == len(VOXEL_LABELS):
        # napari TRUNCATES a longer tuple, keeping the tail, so three
        # labels on a 2D-ndim viewer would land on the wrong axes.
        with contextlib.suppress(Exception):
            viewer.dims.axis_labels = VOXEL_LABELS

    # Switching it on is also what makes napari BUILD the visual: it
    # skips overlays that are not visible and waits on their `visible`
    # event, so nothing below is reachable until this has happened.
    with contextlib.suppress(Exception):
        model = viewer.canvas.overlays["axes"]
        model.visible = True
        model.labels = True

    overlay = _vispy_axes_overlay(viewer)
    if overlay is None:
        return "both" if show_anatomy else "voxel grid"

    with contextlib.suppress(Exception):
        # napari's own, put back the way it comes in case a previous
        # version of this turned or recolored it -- except under a
        # mirror, where it is reflected so its x arrow runs with the
        # displayed voxel grid rather than against it. The labels are
        # axis NAMES and so are unaffected; it is the directions that
        # move.
        overlay.node.axes.transform = (
            NullTransform() if mirror_axis is None
            else MatrixTransform(
                _reflection_4x4(mirror_axis, tuple(viewer.dims.displayed))
            )
        )
        overlay.node.axes._default_color = VOXEL_COLORS
        overlay._on_data_change()

    with contextlib.suppress(Exception):
        node = _anatomy_triad(overlay)
        node.visible = show_anatomy
        if show_anatomy:
            from napari.utils.theme import get_theme

            # Drawn for the array axes in napari's own order, then
            # turned; geometry is in vispy's x,y,z, the REVERSE of the
            # array order the rotation is written in, so conjugate by
            # that reversal, and vispy multiplies row vectors, so
            # transpose.
            node.set_data(axes=(2, 1, 0), reversed_axes=(0, 1, 2),
                          colored=True,
                          bg_color=get_theme(viewer.theme).canvas,
                          dashed=False, arrows=True, text_offset=0.45)
            matrix, labels = triad
            flip = np.eye(3)[::-1]
            mat = np.eye(4)
            mat[:3, :3] = (flip @ matrix @ flip).T
            node.transform = MatrixTransform(mat)
            # Same reversal for the text: arrow k carries array axis
            # `axes[k]`, so the labels follow that order too.
            node.text.text = list(labels)[::-1]
    return "both" if show_anatomy else "voxel grid"


__all__ = [
    "ANATOMY_COLORS",
    "VOXEL_COLORS",
    "VOXEL_LABELS",
    "apply_axis_mode",
    "axis_labels_for",
    "label_viewer_axes",
]
