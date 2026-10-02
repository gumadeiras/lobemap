"""The meshes a space shows, and the layers each one is drawn in.

`scene_parts` lists them, `contour_styles` gives each its outline's color
and width, and `make_surface` and `make_contour` build its Surface layer and
its slice contours. `scene.build_scene` and `scene.SceneSession.realize` put
them in the viewer.
"""

from __future__ import annotations

from dataclasses import dataclass

from ..core.registry import Registry
from .contours import ContourOverlay
from .layers import AtlasSurface, canonical_colors
from .request import REFERENCE_ROLES

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


@dataclass(frozen=True)
class ScenePart:
    """One mesh a space shows: a neuropil or brain shell, or an atlas."""

    #: The scene's key for it: the asset id of a shell, the atlas id.
    name: str
    asset: object
    #: None for reference geometry.
    atlas: object = None

    @property
    def reference(self) -> bool:
        return self.atlas is None


def scene_parts(registry: Registry, space: str) -> list[ScenePart]:
    """Every mesh `space` shows that is on disk, reference geometry first."""
    parts = [ScenePart(asset.id, asset)
             for asset in registry.assets_in_space(space)
             if asset.role in REFERENCE_ROLES and asset.path.exists()]
    for atlas in registry.atlases_in_space(space):
        asset = registry.assets.get(atlas.asset)
        if asset is not None and asset.path.exists():
            parts.append(ScenePart(atlas.id, asset, atlas))
    return parts


def contour_styles(parts) -> dict[str, tuple[str, float]]:
    """Each part's contour color and width, by its place in the scene.

    Assigned over every part, built or not, so an atlas built on first use
    gets the color it would have had.
    """
    palette = iter(ATLAS_CONTOUR_COLORS * 4)
    return {
        part.name: (REFERENCE_CONTOUR_COLOR, REFERENCE_CONTOUR_WIDTH)
        if part.reference else (next(palette), 0.35)
        for part in parts
    }


def make_surface(viewer, registry: Registry, space: str, part: ScenePart,
                 meshset=None, layer=None) -> AtlasSurface:
    """The Surface layer of one part, every compartment selected and resident.

    Made hidden: `AtlasSurface.sync` shows it in the mode that draws it.
    `meshset` is the part's mesh if it has been read already, and `layer`
    a stand-in to take over rather than add a layer (`AtlasSurface`).
    """
    if meshset is None:
        meshset = registry.mesh(part.asset.id)
    if part.reference:
        # Additive, not translucent: a translucent shell writes depth and so
        # hides the very glomeruli it is meant to give context to.
        surface = AtlasSurface(
            viewer, meshset, name=part.asset.id + _tag(meshset), opacity=0.35,
            blending="additive", shading="none", visible=False, layer=layer,
        )
    else:
        atlas = part.atlas
        surface = AtlasSurface(
            viewer, meshset, name=(atlas.title or atlas.id) + _tag(meshset),
            # The SPACE's vocabulary, not a global one: a glomerulus is
            # one color across the atlases it can be compared with, which
            # is exactly the atlases sharing its space.
            colors=canonical_colors(atlas.compartments, registry.vocabulary(space)),
            display_names=[c.label for c in atlas.compartments] or None,
            visible=False, layer=layer,
        )
    surface.layer.metadata["lobemap"].update(
        id=part.name, asset=part.asset.id, role=part.asset.role
    )
    return surface


def make_contour(viewer, surface: AtlasSurface, style, reference: bool) -> ContourOverlay:
    """The slice contours of one surface, hidden until its display mode shows them."""
    color, width = style
    return ContourOverlay(
        viewer,
        surface.meshset,
        name=surface.name,
        color=color,
        width=width,
        selection=set(surface.selection),
        # The atlas palette, so an outline and its label match the mesh.
        # Reference shells stay a single gray: they are context, and
        # coloring each neuropil would compete with the glomeruli.
        colors=None if reference else surface.colors,
        display_names=surface.display_names,
    )


__all__ = [
    "ATLAS_CONTOUR_COLORS",
    "REFERENCE_CONTOUR_COLOR",
    "REFERENCE_CONTOUR_WIDTH",
    "ScenePart",
    "contour_styles",
    "make_contour",
    "make_surface",
    "scene_parts",
]
