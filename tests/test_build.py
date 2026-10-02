"""Every asset must have a runnable path to existence.

The gap this guards was not a bug in any pipeline -- they all worked. It was
that knowing WHICH pipeline to run, with which arguments, existed only as
prose in registry/data/README.md, so nine of the fifteen assets could not be
rebuilt by anyone who had not read the source.
"""

from __future__ import annotations

import pathlib

import pytest

from lobemap.build import buildable, load_recipes, missing
from lobemap.core.registry import Registry

#: Buildable like everything else, but flagged `expensive`: ~19 GB of
#: downloads, ~40 GB of scratch and hours of compute, so `--all` skips them
#: and they have to be named.
STAINS = {"fafb_stain", "hemibrain_stain", "malecns_stain"}


@pytest.fixture(scope="module")
def registry():
    return Registry.load("registry", validate=False)


def test_every_asset_is_buildable(registry):
    recipes = load_recipes(registry.root)
    orphans = [a for a in registry.assets if a not in recipes]
    assert not orphans, (
        f"no way to rebuild: {orphans}. Add a recipe to registry/recipes.toml "
        f"or the asset cannot be reproduced by anyone."
    )


def test_recipes_only_name_real_assets(registry):
    unknown = [a for a in load_recipes(registry.root) if a not in registry.assets]
    assert not unknown, f"recipes for assets that do not exist: {unknown}"


def test_local_sources_actually_ship(registry):
    """A recipe pointing at a file that is not there is not runnable.

    Resolved through the same two functions the build uses, rather than by
    joining paths here. A test that did its own joining is what let the
    `materials` param go unnoticed: `source` was resolved against the
    registry and handed to the pipeline absolute, while `materials` was
    passed through as written and opened relative to the current
    directory, so a build worked from the repository root and nowhere
    else.
    """
    from lobemap.build import _resolve_param_paths, resolve_source

    root = registry.root
    for name, recipe in load_recipes(root).items():
        if not recipe.source:
            continue
        src = resolve_source(recipe, root, cache=root / "data" / ".build")
        assert src is not None and src.exists(), f"{name}: {recipe.source}"
        for key, value in _resolve_param_paths(recipe.params, root).items():
            if isinstance(value, str) and ("/" in value or "\\" in value):
                assert pathlib.Path(value).exists(), (
                    f"{name}: param {key}={value} does not ship"
                )


def test_a_source_path_is_relative_to_the_registry(registry):
    """So `--registry` can point at a copy anywhere.

    They used to begin `datasets/` and resolve against the repository
    root, which only worked inside a checkout laid out one way.
    """
    for name, recipe in load_recipes(registry.root).items():
        if recipe.source:
            assert not recipe.source.startswith(("/", "datasets/")), name
            assert ".." not in recipe.source, name


def test_every_recipe_names_a_known_pipeline(registry):
    from lobemap.build import _PIPELINES

    for name, recipe in load_recipes(registry.root).items():
        assert recipe.pipeline in _PIPELINES, (
            f"{name}: unknown pipeline {recipe.pipeline!r}"
        )


def test_the_stains_are_flagged_expensive(registry):
    """`--all` must not start ~19 GB of downloads and hours of compute."""
    recipes = load_recipes(registry.root)
    for stain in STAINS:
        assert recipes[stain].expensive, f"{stain} is not flagged expensive"
    cheap = buildable(registry, recipes, include_expensive=False)
    assert STAINS.isdisjoint(cheap)
    # Named explicitly, they are still buildable.
    assert STAINS <= set(buildable(registry, recipes))


def test_missing_reports_what_is_absent(registry):
    """Whatever is absent must be a declared asset, and be buildable.

    This deliberately does not assert WHICH assets are missing. That depends
    on what the machine happens to have built -- the stains are gitignored,
    so they are present here and absent on a fresh clone -- and a test that
    encodes one of those states fails for the other.
    """
    recipes = load_recipes(registry.root)
    absent = set(missing(registry))
    assert absent <= set(registry.assets)
    assert absent <= set(recipes), (
        f"absent and unbuildable: {sorted(absent - set(recipes))}"
    )


def test_the_no_data_error_names_a_runnable_command(registry):
    """The old message said `lobemap ingest ...`, ellipsis and all."""
    from lobemap.viewer.app import MissingAssets

    # Constructed directly rather than provoked, so the test does not
    # depend on anything actually being absent: with every asset built the
    # list is empty, and it is the ADVICE being checked here.
    text = str(MissingAssets("JRCFIB2018F", registry))
    assert "..." not in text, "the advice still contains a literal ellipsis"
    assert "lobemap build --all" in text
    assert "lobemap fetch" in text
    assert "JRCFIB2018F" in text
