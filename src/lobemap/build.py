"""Derive a built asset from its source, per `registry/recipes.toml`.

Sources are addressed relative to the registry root: `sources/<dataset>/...`
for what ships, or a URL for what is downloaded. See `registry/sources/`. A
recipe records a digest per downloaded file name, in a `sha256` table or, for a
file whose publisher serves its own checksum, an `md5` table holding that
checksum; a download that does not match is discarded, and one with no digest
recorded is used but reported as not verified.

Every asset under `registry/data/` is derived, which is the justification for
keeping the large ones out of git. That justification was only half true: the
pipelines all existed, but which one to run for which asset, and with what
arguments, lived as prose in `registry/data/README.md`. Nine of the fifteen
assets had no runnable path at all, so "rebuildable" meant "rebuildable by
someone who reads the source and retypes the snippets".

This turns the recipes into data and runs them.

**A rebuild is not byte-identical to the original, and cannot be.** Every
pipeline stamps `retrieved` with the current date, so the file's sha256
differs from the day it was first built. `manifest.toml` therefore verifies
TRANSFER integrity -- that a download arrived intact -- and not
reproducibility. What is reproducible is the `content_hash` each container
computes over its actual content: vertices, faces and names for a MeshSet,
voxels and geometry for a Volume. The build reports it, so a rebuild can be
compared with the asset it replaces.
"""

from __future__ import annotations

import contextlib
import hashlib
import shutil
import tempfile
import tomllib
import urllib.request
from dataclasses import dataclass, field
from pathlib import Path

from .core.atomic import replacing
from .core.manifest import CHUNK, TIMEOUT_S

DEFAULT_RECIPES = "recipes.toml"

#: Downloaded sources are cached here, under the data root, so a second
#: build of the same asset does not re-fetch.
CACHE_DIR = ".build"

#: Pipeline scratch -- a stain's spilled points and float32 grid, 10-25 GB --
#: goes in a per-build directory under this one and is removed when the
#: build ends. A recipe's `workdir` param moves it, to a disk with room.
WORK_DIR = ".stainwork"

_PIPELINES: dict[str, object] = {}


def pipeline(name: str):
    def register(fn):
        _PIPELINES[name] = fn
        return fn
    return register


@dataclass
class Recipe:
    asset: str
    pipeline: str
    source: str | None = None
    url: str | None = None
    #: Several files that belong in one directory, for a loader that takes
    #: the directory rather than a file -- the hemibrain shards.
    urls: list[str] = field(default_factory=list)
    into: str | None = None
    #: Gigabytes of download and hours of compute. `--all` skips these; they
    #: have to be named, so nobody starts one by accident.
    expensive: bool = False
    params: dict = field(default_factory=dict)
    #: sha256 of each downloaded file, keyed by its file name.
    sha256: dict[str, str] = field(default_factory=dict)
    #: md5 of a downloaded file as its publisher serves it -- a Cloud Storage
    #: object's `x-goog-hash` -- so a multi-gigabyte source gets a recorded
    #: checksum without being downloaded to compute one. Used when there is no
    #: sha256 for the file. It detects a changed or damaged file, not one
    #: forged by whoever controls the bucket.
    md5: dict[str, str] = field(default_factory=dict)

    def expected(self, name: str) -> tuple[str, str] | None:
        """The (algorithm, hex digest) a downloaded `name` must match."""
        if name in self.sha256:
            return "sha256", self.sha256[name]
        if name in self.md5:
            return "md5", self.md5[name]
        return None


@dataclass
class BuildResult:
    asset: str
    path: Path
    content_hash: str
    notes: list[str] = field(default_factory=list)


def load_recipes(registry_root) -> dict[str, Recipe]:
    path = Path(registry_root) / DEFAULT_RECIPES
    if not path.exists():
        return {}
    spec = tomllib.loads(path.read_text(encoding="utf-8"))
    out = {}
    for asset, body in spec.items():
        downloads = {Path(u).name for u in [body.get("url"), *body.get("urls", [])] if u}
        for table in ("sha256", "md5"):
            stray = sorted(set(body.get(table, {})) - downloads)
            if stray:
                # A misspelled name would otherwise switch its check off quietly.
                raise ValueError(f"{asset}: {table} names files the recipe does "
                                 f"not download: {', '.join(stray)}")
        out[asset] = Recipe(
            asset=asset,
            pipeline=body["pipeline"],
            source=body.get("source"),
            url=body.get("url"),
            urls=list(body.get("urls", [])),
            into=body.get("into"),
            expensive=bool(body.get("expensive", False)),
            params=dict(body.get("params", {})),
            sha256=dict(body.get("sha256", {})),
            md5=dict(body.get("md5", {})),
        )
    return out


def resolve_source(recipe: Recipe, registry_root: Path, cache: Path,
                   progress=None) -> Path | None:
    """The local file a recipe reads, downloading it first if it is a URL.

    A `source` is relative to the REGISTRY root, so a registry is
    self-contained: point `--registry` or `LOBEMAP_REGISTRY` at a copy
    somewhere else and its recipes still resolve. They used to be relative
    to the repository root and to begin `datasets/`, which meant a recipe
    only worked from inside a checkout laid out exactly one way.
    """
    if recipe.source:
        path = registry_root / recipe.source
        if not path.exists():
            raise FileNotFoundError(
                f"{recipe.asset}: source {recipe.source} is missing from "
                f"{registry_root}. It is expected to ship in the registry."
            )
        return path
    if recipe.urls:
        folder = cache / (recipe.into or recipe.asset)
        for i, url in enumerate(recipe.urls, start=1):
            _fetch_source(recipe, url, folder, progress,
                          label=f"[{i}/{len(recipe.urls)}] {Path(url).name}")
        return folder
    if not recipe.url:
        return None
    return _fetch_source(recipe, recipe.url, cache, progress, label=recipe.url)


def _fetch_source(recipe: Recipe, url: str, folder: Path, progress,
                  label: str) -> Path:
    """The cached copy of `url`, downloaded unless a good one is there.

    A cached copy is checked like a fresh download, and fetched again if
    it fails: the cache is disposable, and a bad one would otherwise be
    trusted forever.
    """
    name = Path(url).name
    target = folder / name
    expected = recipe.expected(name)
    if target.exists() and expected is not None \
            and file_digest(target, expected[0]) != expected[1]:
        target.unlink()
    if not target.exists():
        if progress:
            progress(f"downloading {label}")
        folder.mkdir(parents=True, exist_ok=True)
        _download(url, target, expected)
    if expected is None and progress:
        progress(f"not verified: no checksum recorded for {name}")
    return target


def file_digest(path: Path, algorithm: str) -> str:
    """Hex digest of a file, read in chunks."""
    h = hashlib.new(algorithm)
    with Path(path).open("rb") as fh:
        while block := fh.read(CHUNK):
            h.update(block)
    return h.hexdigest()


def _download(url: str, target: Path,
              expected: tuple[str, str] | None = None) -> None:
    """Fetch to a .part file and rename, so an interrupted download is not
    mistaken for a complete one on the next run. With `expected`, an
    (algorithm, hex digest) pair, a download that does not match is
    discarded and raises."""
    tmp = target.with_suffix(target.suffix + ".part")
    try:
        with urllib.request.urlopen(url, timeout=TIMEOUT_S) as resp, \
                tmp.open("wb") as fh:
            shutil.copyfileobj(resp, fh, 1 << 20)
        if expected is not None:
            algorithm, want = expected
            digest = file_digest(tmp, algorithm)
            if digest != want:
                raise ValueError(f"{url}: downloaded {algorithm} {digest[:12]} != "
                                 f"recorded {want[:12]}")
        tmp.replace(target)
    finally:
        tmp.unlink(missing_ok=True)


# -- pipelines ------------------------------------------------------------
#
# Each takes the resolved source and the recipe's params and returns an
# object with `.save(path)` and `.content_hash()`.


@pipeline("label_volume")
def _label_volume(src, params, **_):
    from .ingest.label_volume import ingest, materials_from_amira

    materials = materials_from_amira(params["materials"])
    return ingest(
        src, materials,
        voxel_um_zyx=tuple(params["voxel_um_zyx"]),
        transpose=tuple(params.get("transpose", (2, 1, 0))),
        mask_sigma_um=params.get("mask_sigma_um", 1.0),
        level=params.get("level", 0.44),
        smooth=params.get("smooth", 0),
    ).meshset


@pipeline("label_masks")
def _label_masks(src, params, **_):
    """The publication's own voxel masks, unmodified.

    Deliberately not a pyramid: averaging neighboring voxels of a label
    volume gives the mean of two ids, which is a third label.
    """
    from .ingest.label_volume import masks_volume, materials_from_amira

    return masks_volume(
        src, materials_from_amira(params["materials"]),
        voxel_um_zyx=tuple(params["voxel_um_zyx"]),
        transpose=tuple(params.get("transpose", (2, 1, 0))),
    )


@pipeline("image_stack")
def _image_stack(src, params, **_):
    from .ingest.image_stack import ingest

    return ingest(
        src, space=params["space"],
        voxel_um_zyx=tuple(params["voxel_um_zyx"]),
        transpose=tuple(params.get("transpose", (2, 1, 0))),
        role=params.get("role", "template_image"),
    ).volume


@pipeline("slicer_vtm")
def _slicer(src, params, **_):
    from .ingest.slicer_vtm import ingest

    return ingest(
        src, source_units=params["source_units"],
        ras_to_lps=params.get("ras_to_lps", True),
    ).meshset


@pipeline("obj_archive")
def _obj_archive(src, params, **_):
    from .ingest.obj_archive import ingest

    return ingest(
        src, source_units=params["source_units"],
        include_side=params.get("include_side", True),
    ).meshset


@pipeline("neuprint_rois")
def _neuprint(src, params, **_):
    from .ingest.neuprint_rois import ingest

    return ingest(
        server=params["server"], dataset=params["dataset"],
        role=params.get("role", "glomeruli"),
    ).meshset


@pipeline("flywire_neuropils")
def _flywire(src, params, progress=None, **_):
    from .ingest.flywire_neuropils import bridge_to_fafb14, ingest

    # This pipeline's callback is (i, total, name, n_vertices), not the
    # single message string every other caller here uses. Adapt rather than
    # forward: passing ours straight through raised
    # "lambda() takes 1 positional argument but 4 were given" after the
    # meshes had already been fetched.
    relay = None
    if progress is not None:
        def relay(i, total, name, n_verts):
            progress(f"[{i}/{total}] {name} ({n_verts} vertices)")

    meshset = ingest(progress=relay).meshset
    if params.get("bridge_to") == "FAFB14":
        if progress:
            progress("bridging FLYWIRE -> FAFB14")
        meshset = bridge_to_fafb14(meshset)
    return meshset


@pipeline("virtual_stain")
def _virtual_stain(src, params, progress=None, workdir=None, **_):
    """Presynapse density, binned and blurred, straight to a Volume.

    Written straight to the registry's `.zarr` store rather than through the
    documented npz-then-`tozarr` two-step: `save_zarr` fills level 0 in
    slabs and builds each pyramid level from the one below, so nothing
    larger than a slab is ever resident and the intermediate npz buys
    nothing.
    """
    import numpy as np

    from .ingest import synapse_buckets as sb
    from .ingest.virtual_stain import build_stain

    loader = {
        "hemibrain": sb.hemibrain_presynapses,
        "malecns": sb.malecns_presynapses,
        "fafb": sb.fafb_presynapses,
    }[params["bucket"]]

    bounds = [float(v) for v in params["bounds"]]
    lo, hi = np.array(bounds[:3]), np.array(bounds[3:])

    def relay(i, n, k):
        if progress:
            progress(f"slab {i}/{n}: {k:,} presynapses")

    def on_stage(label, i, n):
        if progress:
            progress(f"{label}: {i:,}/{n:,}")

    confidence = params.get("confidence", 0.5)
    volume, stats = build_stain(
        loader(src, progress=relay), lo, hi,
        space=params["space"],
        source=f"{params['bucket']} bulk release: {Path(src).name}",
        voxel_um=params.get("voxel", 0.25),
        sigma_um=params.get("sigma", 0.45),
        confidence=None if confidence is False else confidence,
        dtype=np.dtype(params.get("dtype", "uint8")),
        workdir=workdir,
        on_stage=on_stage,
    )
    if progress:
        progress(f"{stats.n_points:,} synapses, {stats.n_outside:,} outside "
                 f"the grid; {np.prod(volume.shape):,} voxels")
    return volume


# -- driver ---------------------------------------------------------------


def _resolve_param_paths(params: dict, registry_root: Path) -> dict:
    """Make `sources/...` params absolute, the way `source` already is.

    `label_volume` takes the Amira material table as a param rather than as
    its source, because the pipeline reads two files. That path was handed
    to `open()` as written, so it resolved against the CURRENT DIRECTORY and
    a build only worked when run from the repository root -- while the CLI
    finds its registry relative to the installed package and otherwise works
    from anywhere.

    The rule is the prefix: a param that begins `sources/` names a file in
    the registry, so it is resolved there. Anything else is passed through,
    because most params are numbers.
    """
    prefix = "sources/"
    return {
        k: str(registry_root / v)
        if isinstance(v, str) and v.startswith(prefix) else v
        for k, v in params.items()
    }


def build_asset(registry, asset_id: str, recipes=None, progress=None,
                overwrite: bool = False) -> BuildResult:
    """Derive one asset and write it where the registry expects it."""
    registry_root = Path(registry.root)
    recipes = recipes if recipes is not None else load_recipes(registry_root)

    if asset_id not in recipes:
        raise KeyError(
            f"no recipe for {asset_id!r}. Recipes are in "
            f"{registry_root / DEFAULT_RECIPES}; the virtual stains are built "
            f"with `lobemap stain` instead."
        )
    if asset_id not in registry.assets:
        raise KeyError(f"{asset_id!r} is not an asset in this registry")

    recipe = recipes[asset_id]
    target = registry.assets[asset_id].path
    if target.exists() and not overwrite:
        raise FileExistsError(
            f"{target} already exists; pass overwrite to replace it"
        )

    params = _resolve_param_paths(recipe.params, registry_root)

    fn = _PIPELINES.get(recipe.pipeline)
    if fn is None:
        raise KeyError(
            f"{asset_id}: unknown pipeline {recipe.pipeline!r}; known: "
            f"{sorted(_PIPELINES)}"
        )

    cache = registry.data_root / CACHE_DIR
    src = resolve_source(recipe, registry_root, cache, progress=progress)
    if progress:
        progress(f"{asset_id}: {recipe.pipeline}")

    default_parent = registry.data_root / WORK_DIR
    parent = Path(params["workdir"]) if params.get("workdir") else default_parent
    parent.mkdir(parents=True, exist_ok=True)
    work = Path(tempfile.mkdtemp(prefix=f"{asset_id}-", dir=parent))
    obj = None
    try:
        obj = fn(src, params, progress=progress, workdir=work)
        # `Volume.save` dispatches on the suffix, so a registry path ending
        # in .zarr writes an OME-Zarr pyramid and anything else writes npz.
        # The recipe does not need to say which. Staged and renamed into
        # place, so a build that stops part-way leaves the asset missing,
        # not partial.
        with replacing(target) as scratch:
            obj.save(scratch)
        digest = obj.content_hash()
    finally:
        obj = None               # a stain's voxels are a memmap inside `work`
        shutil.rmtree(work, ignore_errors=True)
        if parent == default_parent:
            with contextlib.suppress(OSError):
                parent.rmdir()   # only when no other build is using it
    return BuildResult(asset_id, target, digest)


def buildable(registry, recipes=None, include_expensive: bool = True) -> list[str]:
    """Assets this can derive, in registry order."""
    recipes = recipes if recipes is not None else load_recipes(registry.root)
    return [
        a for a in registry.assets
        if a in recipes and (include_expensive or not recipes[a].expensive)
    ]


def missing(registry) -> list[str]:
    """Declared assets whose file is not on disk."""
    return [a for a, asset in registry.assets.items() if not asset.path.exists()]


__all__ = [
    "BuildResult",
    "Recipe",
    "build_asset",
    "buildable",
    "load_recipes",
    "missing",
    "resolve_source",
]
