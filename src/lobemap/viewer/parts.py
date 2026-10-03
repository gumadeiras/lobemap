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
from .layers import GLOMERULUS_COLORS, NEUROPIL_COLORS, AtlasSurface, canonical_colors
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


def part_title(registry: Registry, part: ScenePart) -> str:
    """The plain title a part's layers are named by, from its asset.

    The title the panel's tab shows, and the project the data come from
    when the title does not say: "Benton 2025", "Neuropils (FlyWire)".
    """
    asset = registry.asset_of(part.name) or part.asset
    title = asset.title or part.name
    return f"{title} ({asset.origin})" if asset.origin else title


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
                 meshset=None, layer=None, mirror=None) -> AtlasSurface:
    """The Surface layer of one part, every compartment selected and resident.

    Made hidden: `AtlasSurface.sync` shows it in the mode that draws it.
    `meshset` is the part's mesh if it has been read already, `layer` a
    stand-in to take over rather than add a layer, and `mirror` the view's
    (axis, center) if it is reflected (`AtlasSurface`).
    """
    if meshset is None:
        meshset = registry.mesh(part.asset.id)
    title = part_title(registry, part)
    if part.reference:
        # Additive, not translucent: a translucent shell writes depth and so
        # hides the very glomeruli it is meant to give context to.
        surface = AtlasSurface(
            viewer, meshset, name=title, opacity=0.35, blending="additive",
            shading="none", visible=False, layer=layer, mirror=mirror,
            colormap_name=NEUROPIL_COLORS,
        )
    else:
        atlas = part.atlas
        surface = AtlasSurface(
            viewer, meshset, name=title, colormap_name=GLOMERULUS_COLORS,
            # The SPACE's vocabulary, not a global one: a glomerulus is
            # one color across the atlases it can be compared with, which
            # is exactly the atlases sharing its space.
            colors=canonical_colors(atlas.compartments, registry.vocabulary(space)),
            display_names=[c.label for c in atlas.compartments] or None,
            visible=False, layer=layer, mirror=mirror,
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
    "part_title",
    "scene_parts",
]
