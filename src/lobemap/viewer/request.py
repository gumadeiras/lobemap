"""What a `view` request may name, checked before any window opens.

A space must exist and have something on disk, and every `--show` name must
be something in it: an asset id, an atlas id, or a role. Failing any of
these is a one-line error rather than a traceback behind an empty window.
"""

from __future__ import annotations

#: Roles drawn as context under the atlases rather than as atlases.
REFERENCE_ROLES = ("neuropil", "brain")


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


class ViewRequestError(ValueError):
    """A `view` request that names something the registry does not have.

    Raised before any window opens, with a one-line message, so a typo is
    reported as a typo rather than as a traceback from inside a scene.
    """


def loadable_spaces(registry) -> list[str]:
    """Spaces with at least one ingested atlas or reference meshset."""
    out = []
    for space_id in registry.spaces:
        meshes = [registry.assets.get(atlas.asset)
                  for atlas in registry.atlases_in_space(space_id)]
        meshes += [asset for asset in registry.assets_in_space(space_id)
                   if asset.role in REFERENCE_ROLES]
        if any(asset is not None and asset.path.exists() for asset in meshes):
            out.append(space_id)
    return out


def show_targets(registry, space: str) -> dict[str, set[str]]:
    """What `--show` accepts in `space`, and the asset ids each name turns on.

    An asset id, an atlas id, or a role such as `neuropil` or
    `virtual_stain`, which turns on every asset of that role in the space.
    """
    out: dict[str, set[str]] = {}
    for asset in registry.assets_in_space(space):
        out.setdefault(asset.id, set()).add(asset.id)
        out.setdefault(asset.role, set()).add(asset.id)
    for atlas in registry.atlases_in_space(space):
        out.setdefault(atlas.id, set()).add(atlas.asset)
    return out


def check_request(registry, space, show=(), on_disk: bool = False) -> None:
    """Refuse a request that cannot open, before any window does.

    With `on_disk`, also require the data: a space with nothing built raises
    `MissingAssets`, and a `--show` whose assets are all absent says so.
    """
    if space not in registry.spaces:
        known = ", ".join(sorted(registry.spaces)) or "none"
        raise ViewRequestError(f"unknown space {space!r}; known spaces: {known}")
    targets = show_targets(registry, space)
    for want in show:
        if want not in targets:
            raise ViewRequestError(
                f"--show {want!r} names nothing in {space}; "
                f"use one of: {', '.join(sorted(targets))}"
            )
    if not on_disk:
        return
    if space not in loadable_spaces(registry):
        raise MissingAssets(space, registry)
    for want in show:
        ids = sorted(targets[want])
        if not any(registry.assets[a].path.exists() for a in ids):
            raise ViewRequestError(
                f"--show {want!r}: {', '.join(ids)} not on disk; "
                f"`lobemap fetch` gets it"
            )


__all__ = [
    "REFERENCE_ROLES",
    "MissingAssets",
    "ViewRequestError",
    "check_request",
    "loadable_spaces",
    "show_targets",
]
