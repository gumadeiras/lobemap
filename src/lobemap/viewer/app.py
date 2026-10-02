"""Scene assembly and the napari application entry point."""

from __future__ import annotations

import contextlib

import numpy as np

from ..core.registry import Registry
from .axes import apply_axis_mode
from .contours import ContourOverlay
from .contours import install as install_contours
from .layers import AtlasSurface, canonical_colors, match_label_colors

#: Distinct flat colors for contour overlays, one per atlas, so two atlases
#: superimposed in slice view are told apart by color rather than by shape.
ATLAS_CONTOUR_COLORS = [
    "#ff7f0e", "#1f77b4", "#2ca02c", "#d62728",
    "#9467bd", "#17becf", "#e377c2", "#bcbd22",
]

#: Reference geometry -- neuropil shells, whole brains -- gets a contour too,
#: muted and thin. Without one it has no representation in 2D at all: its
#: Surface is pulled from the layer list there, so an AL outline that was
#: perfectly visible in 3D simply vanished.
REFERENCE_CONTOUR_COLOR = "#9aa0a6"
REFERENCE_CONTOUR_WIDTH = 0.2


def _tag(meshset) -> str:
    """Mark bridged, degraded and mirrored layers in their name.

    Only ingest-time bridging reaches this now: an asset transformed into
    the space it is declared in, such as the FlyWire neuropils bridged
    FLYWIRE -> FAFB14. The viewer no longer bridges atlases across spaces.
    """
    params = meshset.meta.get("derivation", {}).get("params", {})
    if not params:
        return ""
    bits = ["bridged"]
    if params.get("degraded"):
        bits.append("DEGRADED")
    if params.get("mirror"):
        bits.append("mirrored")
    return " [" + ", ".join(bits) + "]"


class MissingAssets(RuntimeError):
    """Nothing in this space is built yet, said usefully.

    This used to be a bare RuntimeError telling the reader to run
    `lobemap ingest ...`, with the ellipsis literal. `ingest` has subcommands
    for two pipelines only, so for most assets that was not a command anyone
    could run, and it arrived at the end of a twenty-line traceback. The
    first thing a new user saw was a crash whose advice did not work.
    """

    def __init__(self, space: str, registry) -> None:
        self.space = space
        self.assets = [
            a for a in registry.assets_in_space(space) if not a.path.exists()
        ]
        super().__init__(self._message(registry))

    def _message(self, registry) -> str:
        from ..build import load_recipes

        recipes = load_recipes(registry.root)
        large = [a.id for a in self.assets
                 if a.id in recipes and recipes[a.id].expensive]
        lines = [
            (f"No data for space {self.space!r}: {len(self.assets)} of its "
             f"assets are not on disk."),
            "",
        ]
        lines += [f"  {asset.id}" for asset in self.assets]
        # Fetch first. Building these takes anywhere from a neuPrint round
        # trip to ~19 GB of synapse downloads and hours of compute, and the
        # same bytes are a download away.
        lines += ["", "Fetch them:", "", "  lobemap fetch"]
        if large:
            lines += [
                "",
                (f"{len(large)} of those is a virtual stain. `fetch` gets "
                 f"them, but they are 2.4 GB"),
                "together; `lobemap fetch --nostains` skips them.",
            ]
        lines += ["", "Or rebuild from source:", "", "  lobemap build --all"]
        return chr(10).join(lines)


def build_scene(
    viewer,
    registry: Registry,
    space: str,
) -> tuple[dict[str, AtlasSurface], dict[str, ContourOverlay]]:
    """Add every atlas native to `space`, plus that space's reference meshes.

    An atlas belongs to exactly one space and is only ever shown there. The
    viewer used to be able to bridge atlases in from other spaces, which made
    a scene's contents span vocabularies: each space names its glomeruli in
    its own terms, so a bridged atlas arrived with names the host space does
    not define, and the panel and the color palette had to reconcile them
    through a single global vocabulary. Dropping it is what lets nomenclature
    be per-space.

    Bridging survives where it is about DATA rather than display -- ingest
    puts an asset into its declared space, and `lobemap bridge` and
    `lobemap reconcile` still compare across spaces on the command line.
    """
    if space not in registry.spaces:
        raise KeyError(f"unknown space {space!r}; known: {sorted(registry.spaces)}")

    surfaces: dict[str, AtlasSurface] = {}

    # Reference geometry first, so it sits underneath and starts hidden.
    for asset in registry.assets_in_space(space):
        if asset.role not in ("neuropil", "brain"):
            continue
        try:
            meshset = registry.mesh(asset.id)
        except (FileNotFoundError, KeyError):
            continue
        # Additive, not translucent: a translucent shell writes depth and so
        # hides the very glomeruli it is meant to give context to.
        surface = AtlasSurface(
            viewer, meshset, name=asset.id, opacity=0.35, blending="additive"
        )
        surface.layer.visible = False
        surface.layer.shading = "none"
        surfaces[asset.id] = surface

    _add_images(viewer, registry, space)

    vocabulary = registry.vocabulary(space)
    for atlas in registry.atlases_in_space(space):
        try:
            meshset = registry.mesh(atlas.asset)
        except (FileNotFoundError, KeyError):
            continue
        surfaces[atlas.id] = AtlasSurface(
            viewer, meshset, name=atlas.title or atlas.id,
            # The SPACE's vocabulary, not a global one: a glomerulus is
            # one color across the atlases it can be compared with, which
            # is exactly the atlases sharing its space.
            colors=canonical_colors(atlas.compartments, vocabulary),
        )

    if not surfaces:
        raise MissingAssets(space, registry)

    # After the atlases, because the colors are read out of their Surface
    # layers rather than recomputed.
    for layer in viewer.layers:
        if layer.metadata.get("lobemap", {}).get("kind") == "labels":
            match_label_colors(layer, list(surfaces.values()))

    contours = (
        _add_contours(viewer, registry, surfaces) if USE_SLICE_CONTOURS else {}
    )

    show_primary_atlas(registry, space, surfaces, contours)

    # Anatomical names for the dimension sliders and napari's own axis
    # overlay. No layer of our own: see `viewer/axes.py`. It shows the
    # anatomy in 3D and the voxel grid in 2D, and is kept up to date by
    # `install_display_mode`, whose handlers a scene switch disconnects
    # -- connecting here instead leaked one per switch.
    apply_axis_mode(viewer, registry.spaces[space])

    return surfaces, contours


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

#: Slice x-y and step through z, the way a confocal stack is read. Volume axes
#: are (x, y, z) to match the mesh columns, and napari would otherwise display
#: the last two -- y-z -- and put the slider on x.
#:
#: **2D only.** In 3D napari applies `dims.order` to an Image but NOT to a
#: Surface: `surface/_slice.py` returns `self.data[0]` unpermuted as soon as
#: nothing is non-displayed, while `_scalar_field/_slice.py` always does
#: `np.transpose(data, order)`. A non-identity order in 3D therefore transposes
#: the stain out from under the meshes, with no warning -- it just looks like a
#: registration failure. So 3D keeps the identity order, where the two agree.
DIMS_ORDER_XYZ = (2, 1, 0)


#: A face-on view is exactly axis-aligned, which is a gimbal-lock singularity
#: for the Euler angles napari stores its camera in. Its vispy round trip --
#: angles to quaternion and back -- cannot recover the third angle there and
#: zeroes it, which comes back as a NEGATED up vector: the brain renders
#: upside down. Turning the camera a fraction of a degree off axis makes the
#: decomposition unique and the roll survives. One degree across a 700 um
#: brain is about 12 um of depth difference edge to edge, invisible, and it
#: is a yaw about the dorsal axis so it reads as "very slightly turned"
#: rather than tilted. `tests/test_default_view.py` pins the napari behavior
#: so this can be dropped if it is ever fixed upstream.
GIMBAL_NUDGE_DEG = 1.0


def orient_anterior(viewer, space, nudge_deg: float = GIMBAL_NUDGE_DEG) -> bool:
    """Face the anterior surface of the brain, dorsal up. True if applied.

    Uses the space's MEASURED anatomy, so the view really is down the
    antero-posterior axis rather than down the nearest array axis to it
    -- which differs by 15-18 degrees in the EM volumes and 31 in GRABE.

    Needs the whole frame. A view direction alone leaves the roll free,
    so a camera built from anterior without dorsal would face the right
    way at an arbitrary tilt -- worse than an obvious default, because
    it looks deliberate. A space with no rotation declared is left
    alone.
    """
    import numpy as np

    from ..core.model import anatomical_axes

    frame = anatomical_axes(space)
    if viewer.dims.ndisplay != 3 or frame is None:
        return False
    anterior, dorsal = frame["A"], frame["D"]

    # Yaw the camera slightly about the dorsal axis, off the singularity.
    view = -anterior
    if nudge_deg:
        # right-handed camera basis (right, up, -view): right = view x up.
        right = np.cross(view, dorsal)
        theta = np.radians(nudge_deg)
        view = view * np.cos(theta) + right * np.sin(theta)
        view /= np.linalg.norm(view)

    # napari 0.9 moved the camera; keep working on either.
    camera = getattr(viewer, "scene", viewer).camera
    camera.set_view_direction(
        view_direction=tuple(view), up_direction=tuple(dorsal)
    )
    # Up is what the round trip destroys, so that is what is checked.
    return bool(np.dot(np.asarray(camera.up_direction), dorsal) > 0.99)


def maximize(viewer) -> bool:
    """Open filling the screen. True if the request was made.

    napari exposes no public API for this, so it goes through the Qt window,
    and it is allowed to fail: headless runs and the tests have no window
    manager, and a viewer that cannot be maximized is still a usable viewer.

    Two quirks, both of which produce a window that *reports* itself
    maximized at 933x700:

    - Called before the event loop turns, `showMaximized` sets the window
      state without the window manager ever resizing anything. So it is also
      deferred with a zero-delay timer.
    - Once that state is set, a second `showMaximized` is a no-op, because Qt
      believes the window is already maximized. `showNormal` first clears the
      state so the next call actually takes effect.
    """
    window = getattr(getattr(viewer, "window", None), "_qt_window", None)
    if window is None:
        return False

    def _apply():
        window.showNormal()
        window.showMaximized()

    try:
        _apply()
        from qtpy.QtCore import QTimer

        QTimer.singleShot(0, _apply)
    except Exception:            # noqa: BLE001 - cosmetic, never fatal
        return False
    return True


def fit_view(viewer, margin: float = 0.02) -> None:
    """Fill the canvas with the data, without disturbing the orientation.

    `reset_view` resets the camera angles by default, which would undo
    `orient_anterior`.
    """
    try:
        viewer.reset_view(margin=margin, reset_camera_angle=False)
    except TypeError:                     # older napari: neither keyword
        viewer.reset_view()


def install_home_orientation(viewer, space) -> bool:
    """Make the home button restore the anatomical view, not napari's.

    `ViewerModel.reset_view` sets the camera angles to (0, 0, 0) before
    fitting, which is a view down the ARRAY axes. Those are not the
    anatomical ones -- antero-posterior is z in FAFB and y in the
    hemibrain -- so "Reset view to original state" left the brain at an
    arbitrary attitude, and the orientation `orient_anterior` sets at
    load could not be got back without reopening the scene.

    Wrapped on the viewer INSTANCE rather than on `ViewerModel`: the class
    is shared by every viewer in the process, including the ones tests
    make. The viewer is a pydantic model and refuses unknown attributes,
    so the assignment goes through `object.__setattr__`; a bound method
    found in the instance dict still wins over the class, which is what
    makes the button -- verified -- go through this.

    Re-orienting only when napari reset the angles, so `fit_view`, which
    asks it not to, keeps preserving whatever the user is looking at.
    """
    existing = viewer.__dict__.get("reset_view")
    if getattr(existing, "_lobemap_home", False):
        # A scene switch: same wrapper, new space.
        existing._lobemap_space = space
        return True

    original = type(viewer).reset_view.__get__(viewer)

    def reset(*args, **kwargs):
        original(*args, **kwargs)
        if kwargs.get("reset_camera_angle", True):
            orient_anterior(viewer, reset._lobemap_space)

    reset._lobemap_home = True
    reset._lobemap_space = space
    try:
        object.__setattr__(viewer, "reset_view", reset)
    except Exception:                       # noqa: BLE001 - cosmetic
        return False
    return True


def install_initial_fit(viewer, margin: float = 0.02) -> bool:
    """Keep refitting until the window settles, then stop at the first touch.

    Maximizing is asynchronous, and the canvas can still report a zero width
    while the layout resolves, so *when* the usable size appears varies from
    run to run. A single fit, or a one-shot on the first resize, therefore
    lands on the right size only sometimes: measured across two spaces, Grabe
    refitted correctly and FAFB never refitted at all, keeping the zoom it
    had at 900x700.

    Refitting on every resize until the user does something removes the
    timing from the question. After the first click, scroll or keypress the
    view is theirs and this stops touching it.
    """
    canvas = getattr(getattr(viewer.window, "_qt_viewer", None), "canvas", None)
    events = getattr(canvas, "events", None)
    if events is None:
        fit_view(viewer, margin)
        return False

    state = {"touched": False, "size": None}

    def _size():
        # napari's OWN canvas size, not the Qt widget's. `fit_to_view` divides
        # by `viewer.canvas.size`, and that model value is updated after the
        # resize callbacks run -- so the widget can already read 987x944 while
        # a fit still computes against 900x700. Watching the widget is how
        # FAFB kept its startup zoom while Grabe happened to refit correctly.
        got = getattr(getattr(viewer, "canvas", None), "size", None)
        return tuple(got) if got is not None else None

    def _refit(event=None):
        # Driven by draws, not only by resize: the resize arrives while
        # napari's own canvas size is still stale, so a fit done there is
        # computed against the old size and no second resize comes to correct
        # it -- which is how FAFB kept the zoom it had at 900x700. Refitting
        # whenever the size CHANGES converges on the settled size and costs
        # nothing once it stops moving.
        if state["touched"]:
            return
        now = _size()
        if now is None or min(now) <= 0 or now == state["size"]:
            return
        state["size"] = now
        fit_view(viewer, margin)

    def _release(event=None):
        state["touched"] = True

    fit_view(viewer, margin)
    connected = False
    for name in ("resize", "draw"):
        with contextlib.suppress(Exception):
            getattr(events, name).connect(_refit)
            connected = True
    for name in ("mouse_press", "mouse_wheel", "key_press"):
        with contextlib.suppress(Exception):
            getattr(events, name).connect(_release)
    return connected


def level_for_3d(levels, max_voxels=VIEW3D_MAX_VOXELS, max_axis=VIEW3D_MAX_AXIS):
    """Finest pyramid level that will render as a single 3D texture."""
    import numpy as np

    for i, arr in enumerate(levels):
        shape = tuple(arr.shape)
        if np.prod(shape, dtype=np.int64) <= max_voxels and max(shape) <= max_axis:
            return i
    return len(levels) - 1


def default_colormap(role: str) -> str:
    return ROLE_COLORMAP.get(role, DEFAULT_COLORMAP)


def show_primary_atlas(registry: Registry, space: str, surfaces,
                       contours=None) -> None:
    """Draw the space's primary atlas and switch its siblings off.

    Every atlas native to the space is loaded -- that is what makes them
    superposable -- but two glomerular parcellations drawn on top of each
    other are unreadable, so one opens.

    This has to be callable a second time, AFTER `install_display_mode`.
    That hook applies itself once on installation, and in 2D its first act
    is to hide every surface; it then remembers each surface's visibility
    to decide which contours to show. Set once at creation, the primary
    atlas was already hidden by the time the hook looked, so it recorded
    False and 2D opened with no contours at all -- an empty canvas but for
    the stain. The old scene preset re-asserted visibility here for the
    same reason.
    """
    primary = registry.primary_atlas(space)
    for name, surface in surfaces.items():
        if name not in registry.atlases:
            continue            # a reference meshset: left as built
        on = primary is not None and name == primary.id
        surface.layer.visible = on
        if contours and name in contours:
            contours[name].layer.visible = on


def _add_images(viewer, registry: Registry, space: str) -> list:
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


#: Whether the display mode DETACHES layers it cannot draw, or merely hides
#: them. Detaching is what keeps the layer list showing only what is usable
#: in the current mode, which is the point of the feature.
#:
#: It also causes a hard crash. Removing a Surface layer from `viewer.layers`
#: while the Layer object stays alive leaves a stale GL resource behind, and
#: a later `layers.clear()` -- which is what a scene switch does -- paints
#: against it:
#:
#:   OSError: exception: access violation reading 0x34
#:     vispy/gloo/gl/_gl2.py in glDrawArrays
#:
#: Only 2D is affected, because that is the mode in which SURFACES are the
#: detached ones; detaching Shapes in 3D is harmless. It scales with how many
#: surfaces were detached: GRABE has one and survives, JRCFIB2018F has four
#: and faults on the second switch.
#:
#: So it is OFF. A layer list that hides what the current mode cannot draw
#: is worth less than a viewer that does not take the process down: with
#: detaching on, switching scenes in 2D faults every run; with it off, every
#: combination tested survives. Unusable layers are still hidden, so the
#: canvas shows the same thing either way -- what changes is that they stay
#: listed, grayed out, instead of disappearing.
#:
#: Set True to get the original behavior back, and do not switch scenes
#: while in 2D.
DETACH_UNUSABLE_LAYERS = False

#: Whether 2D gets its own exact mesh-plane contour layers, or just shows
#: the Surface layers sliced by napari.
#:
#: Contours exist because nested semi-transparent surfaces stop being
#: readable past two atlases, and because napari's Surface returns no value
#: under the cursor in 2D, so they are also what makes a sliced glomerulus
#: clickable and what carries the per-glomerulus slice labels.
#:
#: On, and two layers per atlas is accepted as the cost.
#:
#: The hope was that showing the Surface layers in 2D would make the Shapes
#: layers unnecessary. It does not: napari slices a Surface by drawing the
#: triangles that straddle the plane, so what appears is their projected
#: footprint -- wide where the surface runs tangent to the slice, absent
#: where it runs perpendicular. A boundary mesh has no interior, so nothing
#: can fill it either. Drawing the exact contours FILLED did give a true
#: cross-section, but it still needed the Shapes layer, so it bought nothing
#: over the outlines and lost their even weight.
#:
#: So: outlines, and a Shapes layer beside every Surface layer.
USE_SLICE_CONTOURS = True


#: The array axis a mirror reflects along.
#:
#: napari names the axes x/y/z in array order (`viewer.axes.VOXEL_LABELS`),
#: so this is x -- and x is the left-right axis in all four spaces, 1.0 deg
#: off in the hemibrain, 1.3 in the male CNS, 3.7 in FAFB14 and 5.5 in
#: GRABE. So the mirror is a left-right flip and not an arbitrary one,
#: though it is about the ARRAY axis rather than the measured lateral
#: direction: exactly so a 2D slice keeps cutting the voxel grid squarely.
MIRROR_AXIS = 0


def mirror_center(layers, axis: int = MIRROR_AXIS) -> float:
    """Mid-point of `layers` along one axis, in world micrometers.

    Reflecting about zero would be a reflection too: it would also throw
    the scene to the far side of the origin, which for spaces published
    at x 192-853 um means off screen. So the mid-plane of the data is
    what it reflects about, and the scene stays where it was.

    Read once while nothing is mirrored, because `extent.world` already
    includes each layer's affine -- measuring it again with the mirror on
    would give back the same number only by luck, and any error in it
    doubles on the next toggle.
    """
    lo: list[float] = []
    hi: list[float] = []
    for layer in layers:
        with contextlib.suppress(Exception):
            extent = layer.extent.world
            a, b = float(extent[0][axis]), float(extent[1][axis])
            if np.isfinite(a) and np.isfinite(b):
                lo.append(a)
                hi.append(b)
    if not lo:
        return 0.0
    return (min(lo) + max(hi)) / 2.0


def mirror_matrix(ndim: int, center: float, axis: int = MIRROR_AXIS):
    """The (ndim+1, ndim+1) world reflection x -> 2c - x."""
    m = np.eye(ndim + 1)
    m[axis, axis] = -1.0
    m[axis, -1] = 2.0 * center
    return m


def apply_mirror(layers, on: bool, center: float,
                 axis: int = MIRROR_AXIS) -> None:
    """Reflect layers that carry no normals, or put them back.

    Set on `layer.affine`, which napari applies in WORLD space after the
    layer's own scale and translate. That is what lets one matrix serve
    images in voxels and contours in micrometers alike: each keeps the
    scale and translate that place it, and the reflection composes on
    top rather than replacing it.

    NOT for the surfaces. napari loads the affine into the vispy node
    transform, and a determinant -1 transform there inverts the shading;
    `AtlasSurface._present` explains it and reflects their vertices
    instead. Images, labels and contour outlines have no normals, so for
    them the cheap route is also the correct one.

    Layers currently detached by the display mode are included. They are
    the same objects when re-appended, so the affine travels with them
    and a 2D/3D switch cannot lose the mirror.
    """
    for layer in layers:
        ndim = int(getattr(layer, "ndim", 3) or 3)
        with contextlib.suppress(Exception):
            layer.affine = (
                mirror_matrix(ndim, center, axis) if on else np.eye(ndim + 1)
            )


def install_display_mode(viewer, surfaces, contours, images=(),
                         detach: bool | None = None, space=None,
                         mirror_axis=None) -> list[tuple]:
    """Show only what the current `ndisplay` can actually use.

    Returns (event, handler) pairs, so a scene switch can disconnect them;
    see `contours.install`.

    Three things switch together on 2D/3D:

    - **Meshes in 3D, contours in 2D.** Both are removed from the layer list
      rather than merely hidden, so the list holds only what is usable. The
      layer objects are kept, so contrast, color and selection survive the
      round trip.
    - **Images pin a pyramid level in 3D.** napari's automatic choice there is
      the coarsest level; `level_for_3d` picks the finest one that fits in a
      texture. In 2D the lock is released so zoom-driven selection works.
    - **`dims.order` is permuted only in 2D**, to put the slider on z. In 3D
      it must stay the identity, because napari permutes an Image by it and a
      Surface not at all (see `DIMS_ORDER_XYZ`).
    """
    detaching = DETACH_UNUSABLE_LAYERS if detach is None else detach
    surf_layers = [s.layer for s in surfaces.values()]
    cont_layers = [c.layer for c in contours.values()]

    # Each contour mirrors its own surface, so 2D shows what 3D was showing
    # instead of a fixed set. Keyed by name, which both dicts share.
    paired = {
        contours[name].layer: surfaces[name].layer
        for name in contours
        if name in surfaces
    }
    was_visible: dict[int, bool] = {}

    def _apply(event=None) -> None:
        three_d = viewer.dims.ndisplay == 3
        ndim = viewer.dims.ndim
        # The triad shows the anatomy in 3D and the voxel grid in 2D,
        # and this is already the hook that fires on a mode change and
        # is torn down with the scene.
        if space is not None:
            # A callable, not a value: the mirror is toggled long after
            # this hook is installed, and the triads have to follow it.
            axis = mirror_axis() if callable(mirror_axis) else mirror_axis
            apply_axis_mode(viewer, space, mirror_axis=axis)
        # Identity in 3D, or the stain transposes away from the meshes.
        want_order = (
            tuple(range(ndim)) if three_d or ndim != 3 else DIMS_ORDER_XYZ
        )
        if tuple(viewer.dims.order) != want_order:
            viewer.dims.order = want_order
        for layer in images:
            info = layer.metadata.get("lobemap", {})
            if "level_3d" not in info:
                continue            # labels carry no pyramid to pin
            layer.locked_data_level = info["level_3d"] if three_d else None
        if not cont_layers:
            # Nothing to swap to: the meshes are what 2D shows as well, so
            # the layer list stays put and only `dims.order` changes.
            return
        show = surf_layers if three_d else cont_layers
        hide = cont_layers if three_d else surf_layers
        # The wrong-mode layers go off, unconditionally and every time.
        # Whatever the user did to them since the last switch, a mesh cannot
        # be read in 2D and a contour cannot be read in 3D.
        for layer in hide:
            if layer in viewer.layers:
                was_visible[id(layer)] = layer.visible
                if detaching:
                    viewer.layers.remove(layer)
                else:
                    layer.visible = False
        for layer in show:
            if layer not in viewer.layers:
                viewer.layers.append(layer)
            # Outside the append guard on purpose. `_add_contours` has already
            # put the contour layers in the viewer, so on the first call they
            # need no adding -- and skipping the assignment left every one of
            # them hidden, which made slice contours silently never draw.
            twin = paired.get(layer)
            if twin is not None:
                # Inherit from the surface this contour stands in for, falling
                # back to what the contour itself last had.
                layer.visible = was_visible.get(
                    id(twin), was_visible.get(id(layer), twin.visible)
                )
            else:
                layer.visible = was_visible.get(id(layer), layer.visible)
        if not three_d:
            for overlay in contours.values():
                overlay.refresh()

    viewer.dims.events.ndisplay.connect(_apply)
    _apply()
    return [(viewer.dims.events.ndisplay, _apply)]


def _add_contours(viewer, registry, surfaces) -> dict[str, ContourOverlay]:
    """One contour overlay per surface, including the reference geometry."""
    overlays: dict[str, ContourOverlay] = {}
    palette = iter(ATLAS_CONTOUR_COLORS * 4)
    for name, surface in surfaces.items():
        reference = name in registry.assets
        overlays[name] = ContourOverlay(
            viewer,
            surface.meshset,
            name=surface.name,
            color=REFERENCE_CONTOUR_COLOR if reference else next(palette),
            width=REFERENCE_CONTOUR_WIDTH if reference else 0.35,
            selection=set(surface.selection),
            # The atlas palette, so an outline and its label match the mesh.
            # Reference shells stay a single gray: they are context, and
            # coloring each neuropil would compete with the glomeruli.
            colors=None if reference else surface.colors,
        )
    # The overlays carry their own event handlers, so a scene switch can
    # disconnect them without build_scene having to hand them back.
    handlers = install_contours(viewer, overlays)
    for overlay in overlays.values():
        overlay.handlers = handlers
    return overlays


def install_picking(viewer, surfaces, contours, panel=None) -> None:
    """Identify the glomerulus under the cursor, in 3D and in 2D.

    Surface._get_value_3d does ray-triangle intersection and returns the
    barycentric-interpolated vertex value; because compartments are disjoint
    meshes every triangle's vertices share one index, so that value IS the
    compartment index. In 2D Surface._get_value returns None, so the contour
    Shapes layer covers that case.
    """
    by_layer = {s.layer: (name, s) for name, s in surfaces.items()}
    contour_by_layer = {c.layer: (name, c) for name, c in contours.items()}

    def _on_move(layer, event):
        value = layer.get_value(
            event.position,
            view_direction=getattr(event, "view_direction", None),
            dims_displayed=getattr(event, "dims_displayed", None),
            world=True,
        )
        if isinstance(value, tuple):
            value = value[0]
        if value is None:
            return

        if layer in by_layer:
            name, surface = by_layer[layer]
            label = surface.name_at_value(value)
            index = round(float(value)) if label else None
        elif layer in contour_by_layer:
            name, overlay = contour_by_layer[layer]
            label = overlay.name_at_shape(int(value))
            index = (
                overlay.meshset.names.index(label) if label else None
            )
        else:
            return

        if label:
            viewer.status = f"{name}: {label}"
            if panel is not None and index is not None:
                panel.highlight(name, index)

    for surface in surfaces.values():
        surface.layer.mouse_move_callbacks.append(_on_move)
    for overlay in contours.values():
        overlay.layer.mouse_move_callbacks.append(_on_move)


class SceneSession:
    """One loaded space, and everything needed to unload it again.

    Switching space inside a live viewer is not just `layers.clear()`. The
    display-mode and contour hooks are bound to `viewer.dims.events`, which
    outlives any scene: left connected, they keep firing against surfaces
    whose layers have been removed, so the second scene ends up driven partly
    by the first. The compartment panel is a dock widget and has to be taken
    out of the window rather than dropped on the floor.

    So a session records exactly what it created, and `teardown` undoes it in
    reverse. Rebuilding in place is what makes the switch cheap: the process,
    the Qt window and the GPU context all survive, and only the data is
    swapped.
    """

    def __init__(self, viewer, registry, space):
        self.viewer = viewer
        self.registry = registry
        self.space = space
        self.surfaces: dict = {}
        self.contours: dict = {}
        self.images: list = []
        self.panel = None
        self.dock = None
        self.handlers: list[tuple] = []
        #: Display-only left-right reflection. Held per session, so
        #: switching space rebuilds unmirrored and the control re-asserts
        #: itself rather than the state surviving invisibly.
        self.mirrored = False
        #: The plane it reflects about, measured once while unmirrored.
        self.mirror_center = 0.0

    def all_layers(self) -> list:
        """Every layer this session owns, detached ones included."""
        out = [s.layer for s in self.surfaces.values()]
        out += self.affine_layers()
        return out

    def affine_layers(self) -> list:
        """Those the mirror moves by `affine`: everything without normals.

        The surfaces are absent on purpose -- they reflect their own
        vertices; see `AtlasSurface._present`.
        """
        out = [c.layer for c in self.contours.values()]
        out += [layer for layer in self.images if layer not in out]
        return out

    def set_mirror(self, on: bool) -> None:
        """Show the space reflected, or stop.

        The triads are re-derived rather than left alone: a mirror
        reverses handedness, so an unmirrored anatomical triad over
        mirrored data would name the wrong side, which is the single
        error this project has had to correct most often.
        """
        self.mirrored = bool(on)
        # Two routes on purpose: the meshes reflect their own vertices so
        # that the node transform stays proper and the shading holds, and
        # everything without normals rides on `affine`.
        for surface in self.surfaces.values():
            with contextlib.suppress(Exception):
                surface.set_mirror(
                    MIRROR_AXIS if self.mirrored else None, self.mirror_center
                )
        apply_mirror(self.affine_layers(), self.mirrored, self.mirror_center)
        space = self.registry.spaces.get(self.space)
        if space is not None:
            apply_axis_mode(
                self.viewer, space,
                mirror_axis=MIRROR_AXIS if self.mirrored else None,
            )
        for overlay in self.contours.values():
            with contextlib.suppress(Exception):
                overlay.refresh()

    def teardown(self) -> None:
        for event, handler in self.handlers:
            with contextlib.suppress(Exception):
                event.disconnect(handler)
        self.handlers = []
        for overlay in self.contours.values():
            for event, handler in getattr(overlay, "handlers", ()) or ():
                with contextlib.suppress(Exception):
                    event.disconnect(handler)
        # LAYERS FIRST, then the dock. The other order crashes the process.
        #
        # Removing a dock widget relays out the window, which resizes the
        # canvas and schedules a repaint. Dropping the layers after that has
        # been scheduled frees their GL resources underneath it, and the
        # next paint reads freed memory:
        #
        #   OSError: exception: access violation reading 0x34
        #     vispy/gloo/gl/_gl2.py in glDrawArrays
        #
        # It is 2D-only in practice, because in 3D the surfaces are the
        # layers being drawn and they are removed cleanly; in 2D the Shapes
        # contours are live at the moment the relayout lands. Clearing
        # first means the repaint has nothing stale to draw.
        #
        # This is the fault that went unexplained for several sessions: it
        # looked like a GRABE rendering bug because GRABE was the scene open
        # at the time, and it has no Python frame of its own to point at.
        # Confirmed by bisection -- dock-then-clear faults every run,
        # clear-then-dock survives, in both spaces tested.
        with contextlib.suppress(Exception):
            self.viewer.layers.clear()
        if self.dock is not None:
            with contextlib.suppress(Exception):
                self.viewer.window.remove_dock_widget(self.dock)
            # Removing it undocks it but leaves it a child of the window, so
            # one QDockWidget accumulated per scene switch.
            with contextlib.suppress(Exception):
                self.dock.deleteLater()
        self.dock = self.panel = None
        self.surfaces, self.contours, self.images = {}, {}, []


def load_space(
    viewer,
    registry: Registry,
    space: str,
    show: tuple[str, ...] = (),
    fit: bool = True,
) -> SceneSession:
    """Build a scene into a viewer that may already hold one.

    Ordering is load-bearing: `--show` runs AFTER the display-mode hook,
    which adds and removes layers and restores remembered visibility, so
    running it first would let the hook overwrite what was just asked for.
    """
    session = SceneSession(viewer, registry, space)
    surfaces, contours = build_scene(viewer, registry, space)
    session.surfaces, session.contours = surfaces, contours

    from .panel import CompartmentPanel

    panel = CompartmentPanel(viewer, surfaces, registry=registry,
                             contours=contours, space=space)
    session.panel = panel
    session.dock = viewer.window.add_dock_widget(
        panel, area="right", name="Compartments"
    )
    install_picking(viewer, surfaces, contours, panel=panel)

    session.images = [
        layer for layer in viewer.layers
        if layer.metadata.get("lobemap", {}).get("kind") in ("image", "labels")
    ]
    # Before any mirror is applied, so the plane is the data's own.
    session.mirror_center = mirror_center(
        [s.layer for s in surfaces.values()] + list(session.images)
    )
    session.handlers = install_display_mode(
        viewer, surfaces, contours, session.images,
        space=registry.spaces[space],
        mirror_axis=lambda: MIRROR_AXIS if session.mirrored else None,
    ) or []
    enforce_display_mode = session.handlers[0][1] if session.handlers else None

    # Again, now that the display-mode hook has run and consumed the
    # visibility it found. See `show_primary_atlas`.
    show_primary_atlas(registry, space, surfaces, contours)
    if show:
        _show_layers(viewer, show)

    # AFTER --show, which sets visibility without knowing the display mode:
    # naming an atlas would otherwise turn its mesh on while the viewer is
    # in 2D, where it cannot be read.
    if enforce_display_mode is not None:
        enforce_display_mode()

    orient_anterior(viewer, registry.spaces[space])
    install_home_orientation(viewer, registry.spaces[space])
    if fit:
        install_initial_fit(viewer)
    return session


def run(
    registry_root,
    space: str | None = None,
    ndisplay: int = 3,
    show: tuple[str, ...] = (),
) -> None:
    import napari

    registry = Registry.load(registry_root)
    if space is None:
        raise ValueError("need a space")

    viewer = napari.Viewer(title=f"lobemap - {space}", ndisplay=ndisplay)

    def _load(target: str):
        session = load_space(viewer, registry, target, show=show)
        viewer.title = f"lobemap - {session.space}"
        return session

    session = _load(space)

    from .switcher import SpaceSwitcher

    switcher = SpaceSwitcher(viewer, registry, session, _load)
    # Added ONCE and never torn down, unlike the compartment panel: it is the
    # control that does the switching, so it cannot be owned by the scene it
    # replaces.
    #
    # Right, not left, and added AFTER the compartment panel so Qt splits the
    # area with this underneath it -- the two are the scene's controls and
    # belong together, away from napari's own layer list on the left.
    switcher.dock = viewer.window.add_dock_widget(
        switcher, area="right", name="Space", tabify=False
    )
    switcher.settle()

    maximize(viewer)
    # Maximizing is asynchronous, so the fit follows the canvas rather than
    # running once and hoping. `load_space` already installed one; this is
    # after the dock widgets, which change the canvas size.
    install_initial_fit(viewer)
    napari.run()


def _show_layers(viewer, wanted) -> None:
    """Turn on layers named on the command line, by id or by role.

    Reference images are visible already; what this is for is the layers
    that are not -- the neuropil shells, the Grabe label volume -- and
    anything a scene preset deliberately turned off.
    """
    names = {layer.name for layer in viewer.layers}
    for want in wanted:
        hits = [
            layer for layer in viewer.layers
            if layer.name == want
            or layer.metadata.get("lobemap", {}).get("role") == want
        ]
        if not hits:
            raise KeyError(
                f"nothing called {want!r} in this scene; layers: {sorted(names)}"
            )
        for layer in hits:
            layer.visible = True


__all__ = [
    "BASE_DISPLAY",
    "GIMBAL_NUDGE_DEG",
    "ROLE_DISPLAY",
    "MissingAssets",
    "SceneSession",
    "build_scene",
    "display_for",
    "fit_view",
    "install_display_mode",
    "install_home_orientation",
    "install_initial_fit",
    "install_picking",
    "level_for_3d",
    "load_space",
    "maximize",
    "orient_anterior",
    "run",
    "show_primary_atlas",
]
