"""Command line interface."""

from __future__ import annotations

import argparse
import contextlib
import os
import sys
from pathlib import Path

from . import __version__

DEFAULT_REGISTRY = Path(__file__).resolve().parents[2] / "registry"

#: The space `lobemap` and `lobemap view` open when none is named. FAFB is
#: the whole adult brain at synaptic resolution and the space the
#: nomenclature is anchored in, so it is the least surprising thing to see
#: first. `lobemap spaces` lists the others.
DEFAULT_SPACE = "FAFB14"


def _registry_root(args) -> Path:
    return Path(args.registry or os.environ.get("LOBEMAP_REGISTRY") or DEFAULT_REGISTRY)


def _data_root(args, root: Path) -> Path:
    from .core.registry import default_data_root

    override = getattr(args, "data_root", None)
    return Path(override) if override else default_data_root(root)


def _optional_assets(root: Path) -> set[str]:
    """Assets nobody should start downloading without asking for them.

    The same three the `build --all` rule holds back, and for the same
    reason at the other end of the pipe: the virtual stains are 2.4 GB of
    the 2.5 GB total. They are also reference imagery that starts hidden,
    so every scene opens without them -- `build_scene` only fails when it
    can find no SURFACES. Skipping them by default is the difference
    between a 76 MB first run and a 2.5 GB one.
    """
    from .build import load_recipes

    try:
        recipes = load_recipes(root)
    except (FileNotFoundError, KeyError):
        return set()
    return {name for name, r in recipes.items() if r.expensive}


def _autofetch(root: Path, data_root: Path) -> None:
    """Fetch the required artifacts before opening a scene.

    Nothing runs on `uv sync`, so a fresh clone reaches the viewer with no
    data at all. Rather than meeting a new user with instructions, fetch
    what a scene cannot open without -- the meshes and the Grabe stack, 76
    MB -- and leave the stains to be asked for. Silent when there is
    nothing to do, and never fatal: a failure here should still let the
    viewer start and report what it is missing in its own terms.
    """
    from .core import manifest as mf

    path = root / "manifest.toml"
    if not path.exists():
        return
    try:
        arts, base_url = mf.load(path)
    except Exception:                               # noqa: BLE001 - advisory
        return
    if not base_url:
        return
    optional = _optional_assets(root)
    absent = [a for a in arts
              if a.asset not in optional and not (data_root / a.path).exists()]
    if not absent:
        return
    total = sum(a.size for a in absent) / 1e6
    print(f"fetching {len(absent)} missing artifact(s), {total:.0f} MB")

    def progress(i, n, status):
        mark = {"ok": "OK  ", "missing": "MISS", "corrupt": "BAD "}[status.state]
        print(f"  [{i}/{n}] {mark} {status.artifact.asset}", flush=True)

    with contextlib.suppress(Exception):
        results = mf.fetch(absent, data_root, base_url, progress=progress)
        failed = [s for s in results if s.state != "ok"]
        if failed:
            print(f"  {len(failed)} could not be fetched; the viewer will "
                  f"say what is missing", file=sys.stderr)


def cmd_manifest(args) -> int:
    """Record sha256 and size for every data artifact on disk."""
    from .core import manifest as mf
    from .core.registry import Registry

    root = _registry_root(args)
    reg = Registry.load(root, validate=False)
    data_root = _data_root(args, root)
    assets = [a for a in reg.assets.values() if a.path.exists()]

    def progress(i, n, asset_id, size):
        print(f"  [{i}/{len(assets)}] {asset_id:26s} {size / 1e6:9.1f} MB", flush=True)

    arts = mf.build(data_root, assets, progress=progress)

    # Artifacts that are not on disk KEEP their existing record unless the
    # caller asks otherwise. `build` only describes files it can see, so a
    # plain regenerate on a machine missing some assets silently dropped
    # their checksums -- and those checksums are the only way to verify a
    # later download. With the three stains absent this would have discarded
    # exactly the records that cannot be recomputed without ~19 GB and hours
    # of work.
    out = Path(args.output) if args.output else root / "manifest.toml"
    dropped = []
    if out.exists() and not args.prune:
        previous, prev_base = mf.load(out)
        fresh = {a.path for a in arts}
        # Only for paths the registry STILL declares. Keeping every
        # unregenerated record instead would preserve orphans: renaming
        # grabe2015_stack from .zarr to .npz left the old .zarr record
        # sitting beside the new one, and the manifest claimed 16 artifacts
        # for a registry of 15.
        declared = {
            a.path.relative_to(data_root).as_posix()
            for a in reg.assets.values()
        }
        kept = [a for a in previous
                if a.path not in fresh and a.path in declared]
        orphans = [a.path for a in previous
                   if a.path not in fresh and a.path not in declared]
        for path in orphans:
            print(f"  dropping orphaned record: {path}")
        if kept:
            print(f"  keeping {len(kept)} record(s) for artifacts not on disk:")
            for a in kept:
                print(f"    {a.path}")
        arts = arts + kept
        arts.sort(key=lambda a: a.path)
        if args.base_url is None:
            args.base_url = prev_base
    elif args.prune:
        dropped = ["(pruned records for absent artifacts)"]
    out.write_text(mf.dump(arts, args.base_url), encoding="utf-8")
    for line in dropped:
        print(f"  {line}")
    total = sum(a.size for a in arts)
    print(f"  {len(arts)} artifacts, {total / 1e9:.2f} GB transferred size")
    print(f"  written: {out}")
    if not args.base_url:
        print("  note: no base_url recorded; pass one here or to `fetch`")
    return 0


def cmd_fetch(args) -> int:
    """Download missing data artifacts, or verify what is already here."""
    from .core import manifest as mf

    root = _registry_root(args)
    data_root = _data_root(args, root)
    path = Path(args.manifest) if args.manifest else root / "manifest.toml"
    if not path.exists():
        print(f"no manifest at {path}; run `lobemap manifest` first",
              file=sys.stderr)
        return 2
    arts, base_url = mf.load(path)
    base_url = args.base_url or base_url

    # Everything, unless told otherwise. `fetch` used to hold the stains
    # back and need `--all` to include them, which made the obvious command
    # the one that left the reference image out of three of the four
    # spaces: a scene opened without its backdrop and nothing said why.
    # Asking for less is the rarer case, so it is the one that needs a flag.
    optional = _optional_assets(root)
    if args.asset:
        wanted = [a for a in arts if a.asset in set(args.asset)]
    elif args.nostains:
        wanted = [a for a in arts if a.asset not in optional]
        held = [a.asset for a in arts if a.asset in optional]
        if held:
            print(f"skipping {len(held)} virtual stain(s): "
                  f"{', '.join(held)}")
            print("  fetch them later with `lobemap fetch`, or by name.")
    else:
        wanted = list(arts)
    print(f"manifest: {len(arts)} artifacts, {len(wanted)} selected")
    print(f"data root: {data_root}")

    def progress(i, n, status):
        mark = {"ok": "OK  ", "missing": "MISS", "corrupt": "BAD "}[status.state]
        detail = f"  {status.detail}" if status.detail else ""
        print(f"  [{i}/{n}] {mark} {status.artifact.asset:28.28s} "
              f"{status.artifact.path:34.34s}{detail}", flush=True)

    statuses = mf.verify(wanted, data_root, progress=progress)
    bad = [s for s in statuses if s.state != "ok"]
    if args.check:
        print(f"  {len(statuses) - len(bad)}/{len(statuses)} verified")
        return 1 if bad else 0
    if not bad:
        print("  everything present and verified; nothing to fetch")
        return 0
    if not base_url:
        print("  no base_url recorded in the manifest. Pass --base-url, "
              "or record one with `lobemap manifest --base-url`.",
          file=sys.stderr)
        return 2
    print(f"  fetching {len(bad)} artifact(s) from {base_url}")
    results = mf.fetch([s.artifact for s in bad], data_root, base_url,
                       progress=progress)
    failed = [s for s in results if s.state != "ok"]
    print(f"  {len(results) - len(failed)}/{len(results)} fetched")
    return 1 if failed else 0


def cmd_pack(args) -> int:
    """Write the transfer files to a directory, ready to upload.

    `manifest` and `fetch --check` both zip a Zarr store in order to hash
    it and then delete the archive. That is right for checking and useless
    for publishing: the exact bytes a downloader will receive get produced
    and thrown away, leaving nothing to upload. This writes the same
    archives and keeps them, under the exact names `fetch` will ask for --
    `<asset>.zarr.zip` for a store, the file itself otherwise -- so the
    output directory maps one-to-one onto a set of release assets.

    Everything written is hashed and compared to the manifest, because the
    manifest is what `fetch` verifies against. Publishing a file that does
    not match it hands every downloader a checksum failure on data that is
    perfectly good, so a mismatch fails here instead.
    """
    import shutil

    from .core import manifest as mf

    root = _registry_root(args)
    data_root = _data_root(args, root)
    path = Path(args.manifest) if args.manifest else root / "manifest.toml"
    if not path.exists():
        print(f"no manifest at {path}; run `lobemap manifest` first",
              file=sys.stderr)
        return 2
    arts, base_url = mf.load(path)
    by_asset = {a.asset: a for a in arts}

    if args.all:
        wanted = list(arts)
    elif args.asset:
        unknown = [a for a in args.asset if a not in by_asset]
        if unknown:
            print(f"not in the manifest: {', '.join(unknown)}", file=sys.stderr)
            print(f"known: {', '.join(sorted(by_asset))}", file=sys.stderr)
            return 2
        wanted = [by_asset[a] for a in args.asset]
    else:
        print(f"name the assets to pack, or --all. In {path.name}:")
        wid = max((len(a.asset) for a in arts), default=0)
        for a in arts:
            here = "" if (data_root / a.path).exists() else "   (not on disk)"
            print(f"  {a.asset:{wid}s}  {a.transfer_name:32s} "
                  f"{a.size / 1e6:9.1f} MB{here}")
        return 0

    out_dir = Path(args.output) if args.output else data_root / ".pack"
    out_dir.mkdir(parents=True, exist_ok=True)
    total = sum(a.size for a in wanted)
    wid = max(len(a.asset) for a in wanted)
    print(f"packing {len(wanted)} artifact(s), {total / 1e9:.2f} GB "
          f"-> {out_dir}")

    failures: list[str] = []
    written: list[Path] = []
    for i, art in enumerate(wanted, start=1):
        source = data_root / art.path
        target = out_dir / art.transfer_name
        label = f"  [{i}/{len(wanted)}] {art.asset:{wid}s}"
        if not source.exists():
            print(f"{label} MISSING   {art.path} is not on disk")
            failures.append(art.asset)
            continue
        if target.exists() and not args.overwrite:
            digest, size = mf.sha256_file(target)
            state = "kept" if digest == art.sha256 else "STALE"
        else:
            # Deterministic: sorted entries and pinned timestamps, so the
            # archive re-hashes to the value `manifest` recorded.
            if art.kind == "dir":
                mf.zip_directory(source, target)
            else:
                shutil.copyfile(source, target)
            digest, size = mf.sha256_file(target)
            state = "ok" if digest == art.sha256 else "MISMATCH"
        print(f"{label}  {state:9s} {art.transfer_name:32s} "
              f"{size / 1e6:9.1f} MB", flush=True)
        if state in ("MISMATCH", "STALE"):
            print(f"      sha256 {digest[:12]} != manifest {art.sha256[:12]}")
            failures.append(art.asset)
        else:
            written.append(target)

    if failures:
        print()
        print(f"{len(failures)} artifact(s) do not match the manifest: "
              f"{', '.join(failures)}", file=sys.stderr)
        print("The manifest is what `fetch` verifies against, so publishing "
              "these would fail for everyone who downloads them. Re-record "
              "it with `lobemap manifest`, then pack again.", file=sys.stderr)
        return 1

    print()
    print(f"{len(written)} file(s) ready in {out_dir}")
    print("Upload them under these exact names -- `fetch` requests "
          "<base_url>/<name> -- then record where they went:")
    print("  lobemap manifest --base-url "
          "https://github.com/<owner>/<repo>/releases/download/<tag>")
    if base_url:
        print(f"  (the manifest currently records {base_url})")
    return 0


def cmd_ingest_neuprint(args) -> int:
    from .core.registry import Registry
    from .ingest import neuprint_rois

    token = args.token or os.environ.get("NEUPRINT_APPLICATION_CREDENTIALS")
    if not token:
        print(
            "No neuPrint token. Set NEUPRINT_APPLICATION_CREDENTIALS or pass "
            "--token. Get one from https://<server>/account",
            file=sys.stderr,
        )
        return 2

    result = neuprint_rois.ingest(
        server=args.server,
        dataset=args.dataset,
        token=token,
        role=args.role,
        repair=not args.no_repair,
    )
    ms = result.meshset
    root = _registry_root(args)
    out = root / "data" / f"{args.asset_id}.npz"
    ms.save(out)

    print(f"{args.dataset}  role={args.role}")
    print(f"  compartments : {ms.n_compartments}")
    print(f"  vertices     : {len(ms.vertices):,}  faces: {len(ms.faces):,}")
    print(f"  source units : {result.source_units} (x{result.scale_to_um:g} -> um)")
    print(f"  extent (um)  : {ms.extent_um().round(1)}")
    print(f"  content hash : {ms.content_hash()}")
    if result.skipped:
        print(f"  skipped      : {len(result.skipped)}")
        for s in result.skipped[:5]:
            print(f"    - {s}")
    if result.repair is not None:
        r = result.repair
        print(f"  watertight   : {r.summary()}")
        for name, pct in sorted(
            r.large_changes.items(), key=lambda kv: -abs(kv[1])
        )[:5]:
            print(f"    !! {name} volume changed {pct:+.1f}% during repair")
    print(f"  written      : {out}")

    # Register the derived names so the registry can resolve canonicals.
    nom_path = root / "nomenclature.csv"
    from .core.names import Nomenclature

    nom = Nomenclature.load(nom_path)
    if args.atlas_id and args.role == "glomeruli":
        # `add_missing` skips names already recorded, so a curated merge or
        # rename is left exactly as it is. This used to filter by hand and
        # call the build-from-nothing path, which was correct only for as
        # long as the filter was remembered.
        added = nom.add_missing(args.atlas_id, list(ms.names))
        if added:
            nom.save(nom_path)
            print(f"  nomenclature : +{len(added)} entries -> {nom_path}")
    _ = Registry  # registry is re-read lazily by other commands
    return 0


def cmd_stain(args) -> int:
    """Build a virtual neuropil stain from predicted presynapse locations."""
    import shutil
    import time

    import numpy as np

    from .core.registry import Registry
    from .ingest.synapse_sources import neuprint_client, neuprint_presynapses
    from .ingest.virtual_stain import build_stain, effective_sigma_um
    from .validate import images as gi

    token = args.token or os.environ.get("NEUPRINT_APPLICATION_CREDENTIALS")
    if not token and not args.bucket:
        print("No neuPrint token; set NEUPRINT_APPLICATION_CREDENTIALS.", file=sys.stderr)
        return 2

    root = _registry_root(args)
    reg = Registry.load(root, validate=False)

    # Bounds come from geometry we hold, never from an aggregate query: an
    # unfiltered min/max over the synapse table times out server-side.
    if args.bounds:
        vals = [float(v) for v in args.bounds]
        lo, hi = np.array(vals[:3]), np.array(vals[3:])
        where = "explicit --bounds"
    elif args.bounds_from:
        ref = reg.mesh(args.bounds_from)
        lo, hi = ref.vertices.min(0), ref.vertices.max(0)
        where = f"mesh {args.bounds_from}"
    else:
        import flybrains

        template = getattr(flybrains, reg.spaces[args.space].flybrains_template)
        box = np.asarray(template.boundingbox, dtype=float).reshape(3, 2)
        scale = 1e-3 if "nano" in str(template.units).lower() else 1.0
        lo, hi = box[:, 0] * scale, box[:, 1] * scale
        where = f"{template.label} bounding box"
    print(f"bounds from {where}: {np.round(lo, 1)} .. {np.round(hi, 1)} um")

    start = time.time()

    # Progress also goes to a file. stdout can be block-buffered through a
    # wrapper shell, which on a multi-hour job is indistinguishable from a
    # hang -- and cost one needlessly killed run.
    log_path = root / "data" / f"{args.asset_id}.progress.log"
    log_path.parent.mkdir(parents=True, exist_ok=True)
    seen = {"n": 0}

    def progress(i, n, k):
        seen["n"] += k
        line = (f"  slab {i}/{n}: {k:,} presynapses, {seen['n']:,} total "
                f"({time.time() - start:.0f}s)")
        print(line, flush=True)
        with log_path.open("a", encoding="utf-8") as fh:
            fh.write(line + "\n")

    if args.bucket:
        # The published bulk releases: complete, and far faster than neuPrint.
        from .ingest import synapse_buckets as sb

        loader = {
            "hemibrain": sb.hemibrain_presynapses,
            "malecns": sb.malecns_presynapses,
            "fafb": sb.fafb_presynapses,
        }[args.bucket]
        batches = loader(args.path, progress=progress)
        source = f"{args.bucket} bulk release: {Path(args.path).name}"
        confidence = args.confidence if args.bucket != "hemibrain" else None
    else:
        client = neuprint_client(args.server, args.dataset, token)
        batches = neuprint_presynapses(
            client,
            lo,
            hi,
            rois=args.roi or None,
            confidence=args.confidence,
            n_slabs=args.slabs,
            progress=progress,
        )
        source = f"neuprint {args.server} {args.dataset}"
        confidence = args.confidence

    def on_stage(label, i, n):
        line = f"  {label}: {i:,}/{n:,} ({time.time() - start:.0f}s)"
        print(line, flush=True)
        with log_path.open("a", encoding="utf-8") as fh:
            fh.write(line + "\n")

    workdir = Path(args.workdir) if args.workdir else root / "data" / ".stainwork"
    volume, stats = build_stain(
        batches, lo, hi, space=args.space, source=source,
        voxel_um=args.voxel, sigma_um=args.sigma, confidence=confidence,
        dtype=np.dtype(args.dtype), workdir=workdir, on_stage=on_stage,
    )
    out = root / "data" / f"{args.asset_id}.npz"
    volume.save(out)

    print(f"  synapses     : {stats.n_points:,} ({stats.n_outside:,} outside grid)")
    print(f"  grid         : {volume.shape} = {np.prod(volume.shape):,} voxels "
          f"({volume.data.dtype})")
    print(f"  sigma        : {args.sigma * 1000:.0f} nm nominal, "
          f"{effective_sigma_um(args.sigma, args.voxel) * 1000:.0f} nm after binning")
    written = out.stat().st_size
    side = out.with_suffix(".data.npy")
    if side.exists():
        written += side.stat().st_size
        print(f"  written      : {out.name} + {side.name} "
              f"({written / 1e9:.2f} GB, memory-mapped on load)")
    else:
        print(f"  written      : {out} ({written / 1e6:.0f} MB)")
    for note in stats.notes:
        print(f"  {note}")
    print(f"  elapsed      : {time.time() - start:.0f}s")

    # Re-read from disk before validating. For a slabwise build `volume.data`
    # is still mapped into the working directory, so checking it would test the
    # scratch copy and then fail to delete it; this checks what was shipped.
    from .core.imagefmt import Volume

    volume = Volume.load(out)
    shells = [
        a for a in reg.assets_in_space(args.space, role="neuropil") if a.path.exists()
    ]
    if shells:
        print(gi.check_image_inside_shell(volume, reg.mesh(shells[0].id), args.asset_id))

    # Tens of GB of scratch: a cache, not a result. Dropped only once nothing
    # maps it any more.
    del volume
    if workdir.exists() and not args.keep_workdir:
        shutil.rmtree(workdir, ignore_errors=True)
        if workdir.exists():
            print(f"  note         : {workdir} still holds scratch files")
    return 0


def cmd_tozarr(args) -> int:
    """Rewrite a volume as an OME-Zarr group with a multiscale pyramid."""
    import shutil
    import time

    from .core.imagefmt import Volume
    from .core.zarrfmt import pyramid_levels

    src = Path(args.input)
    dst = Path(args.output) if args.output else src.with_suffix(".zarr")
    if dst.exists() and not args.force:
        print(f"{dst} exists; pass --force to replace it", file=sys.stderr)
        return 2

    start = time.time()
    volume = Volume.load(src)
    levels = pyramid_levels(volume.shape, args.min_extent)
    print(f"  source       : {src} {volume.data.dtype} {volume.shape}")
    print("  levels       : " + ", ".join(
        "x".join(str(n) for n in s) for s, _f in levels))
    if dst.exists():
        shutil.rmtree(dst)
    volume.save(dst, chunks=(args.chunk,) * 3, min_extent=args.min_extent)

    back = Volume.load(dst)
    before = _tree_size(src) + _tree_size(src.with_suffix(".data.npy"))
    after = _tree_size(dst)
    print(f"  written      : {dst} ({after / 1e9:.2f} GB, "
          f"was {before / 1e9:.2f} GB, {after / max(before, 1):.0%})")
    print(f"  levels on disk: {len(back.levels)}  multiscale={back.is_multiscale}")
    print(f"  geometry     : voxel {back.voxel_um} origin {back.origin_um}")
    print(f"  elapsed      : {time.time() - start:.0f}s")
    return 0


def _tree_size(path: Path) -> int:
    if not path.exists():
        return 0
    if path.is_file():
        return path.stat().st_size
    return sum(p.stat().st_size for p in path.rglob("*") if p.is_file())


def cmd_validate(args) -> int:
    from .core.registry import Registry, RegistryError

    try:
        root = _registry_root(args)
        reg = Registry.load(root, data_root=_data_root(args, root))
        warnings = reg.validate(strict_templates=args.strict)
    except RegistryError as exc:
        print(exc, file=sys.stderr)
        return 1
    print(
        f"ok: {len(reg.spaces)} spaces, {len(reg.assets)} assets, "
        f"{len(reg.atlases)} atlases"
    )
    for a in reg.atlases.values():
        print(f"  {a.id:<22} {a.native_space:<14} {len(a.compartments):>3} compartments")
    if warnings:
        print(f"\n{len(warnings)} warning(s):")
        for w in warnings[:20]:
            print(f"  - {w}")
    return 0


def cmd_spaces(args) -> int:
    from .core import spaces as sp
    from .core.registry import Registry

    reg = Registry.load(_registry_root(args), validate=False)
    have = sp.available()
    print(f"flybrains available: {have}")
    # The `ok` column is about the flybrains TEMPLATE, not about data on
    # disk, and on an empty install every space still read "ok, 2 atlas(es)"
    # -- a readiness claim the install could not honour. The data column
    # says what is actually there.
    absent_total = 0
    for s in reg.spaces.values():
        n_at = len(reg.atlases_in_space(s.id))
        tmpl = s.flybrains_template or "-- island --"
        ok = "" if not have or s.is_island else (
            " ok" if sp.template_exists(s.flybrains_template) else " MISSING"
        )
        assets = list(reg.assets_in_space(s.id))
        here = sum(1 for a in assets if a.path.exists())
        absent_total += len(assets) - here
        data = f"{here}/{len(assets)} assets built" if assets else "no assets"
        print(f"  {s.id:<14} {s.units:<3} {tmpl:<16}{ok}  "
              f"{n_at} atlas(es)  {data}")
        # What `lobemap view <space>` will actually put on screen. This is
        # what the separate `scenes` listing used to say, back when a named
        # preset sat between a space and its layers.
        primary = reg.primary_atlas(s.id)
        if primary is None:
            continue
        others = [a.id for a in reg.atlases_in_space(s.id) if a.id != primary.id]
        opens = [primary.id]
        for asset in assets:
            if asset.kind == "image":
                opens.append(asset.id
                             if asset.path.exists()
                             else f"{asset.id} (not fetched)")
        line = f"opens with: {', '.join(opens)}"
        if others:
            line += f"; also loaded: {', '.join(others)}"
        print(f"  {'':<14} {'':<3} {'':<16}  {line}")
    if absent_total:
        print()
        print(f"{absent_total} declared asset(s) are not on disk. "
              f"`lobemap build --list` shows which can be rebuilt.")
    return 0


def cmd_check(args) -> int:
    """Run the geometry validation harness."""
    from .core.registry import Registry
    from .core.resolve import resolve
    from .validate import geometry as g
    from .validate import images as gi

    root = _registry_root(args)
    reg = Registry.load(root, data_root=_data_root(args, root))
    checks = []

    for atlas in reg.atlases.values():
        try:
            ms = reg.mesh(atlas.asset)
        except (FileNotFoundError, KeyError):
            continue
        checks.append(g.check_scale(ms, label=atlas.id))
        npl = [
            a for a in reg.assets_in_space(atlas.native_space, role="neuropil")
            if a.path.exists()
        ]
        if npl:
            # Sides here only PAIR a glomerulus with its shell, so both must
            # use the same convention -- and biological is the one assets and
            # source names record. Converting only the glomerulus side to
            # apparent, as an earlier version did, pairs Bates with the wrong
            # lobe in FAFB: its asset says biological L, the FlyWire shells
            # are named AL_L/AL_R biologically, and flipping one side of the
            # comparison breaks the match.
            glom_asset = reg.assets[atlas.asset]
            checks.append(
                g.check_containment(
                    ms,
                    reg.mesh(npl[0].id),
                    glom_side=glom_asset.side,
                    shell_side=npl[0].side,
                )
            )

    # Image assets: are they actually where they claim to be?
    for asset in reg.assets.values():
        if asset.kind != "image" or not asset.path.exists():
            continue
        volume = reg.volume(asset.id)
        peers = reg.atlases_in_space(asset.space)
        ms = None
        label = asset.id
        if peers:
            ms = reg.mesh(peers[0].asset)
        else:
            # An image in a space with no native atlas would otherwise go
            # unchecked entirely, so bridge one in and hold it to the same
            # standard. No shipped asset reaches this today -- it was written
            # for JRC2018U's nc82 template, which has since been dropped --
            # but the alternative is that the next such image is silently
            # never validated.
            for candidate in reg.atlases.values():
                src = reg.spaces.get(candidate.native_space)
                if src is None or src.is_island:
                    continue
                try:
                    ms = resolve(reg, candidate.asset, asset.space)
                except Exception:  # noqa: BLE001, S112 - try the next atlas
                    continue
                label = f"{asset.id} (vs bridged {candidate.id})"
                break
        if ms is not None:
            checks.append(gi.check_image_covers_mesh(volume, ms, label))
            checks.append(gi.check_image_brightness_at_mesh(volume, ms, label))
        shells = [
            a for a in reg.assets_in_space(asset.space, role="neuropil")
            if a.path.exists()
        ]
        if shells:
            checks.append(
                gi.check_image_inside_shell(volume, reg.mesh(shells[0].id), asset.id)
            )

    if args.roundtrip:
        src, via = args.roundtrip
        for atlas in reg.atlases.values():
            if reg.spaces[atlas.native_space].flybrains_template != src:
                continue
            checks.append(g.check_roundtrip(reg.mesh(atlas.asset), src, via))

    if args.compare:
        a_id, b_id, space = args.compare
        a = reg.mesh(reg.atlases[a_id].asset)
        b_atlas = reg.atlases[b_id]
        b = (
            reg.mesh(b_atlas.asset)
            if b_atlas.native_space == space
            else resolve(reg, b_atlas.asset, space)
        )
        a_side = reg.assets[reg.atlases[a_id].asset].side
        b_side = reg.assets[b_atlas.asset].side
        pairs, chk = g.correspondence_report(
            a,
            b,
            a_id,
            b_id,
            a_side=a_side if a_side in ("L", "R") else None,
            b_side=b_side if b_side in ("L", "R") else None,
        )
        checks.append(chk)
        worst = sorted(pairs, key=lambda p: -p.distance_um)[:10]
        print()
        print(f"worst-separated shared compartments ({b_id} -> {space}):")
        for pr in worst:
            print(f"    {pr.canonical:<8} {pr.a_name:<14} vs {pr.b_name:<14} "
                  f"{pr.distance_um:6.1f} um")

    print()
    for c in checks:
        print(c)
    failed = [c for c in checks if not c.passed]
    print()
    print(f"{len(checks) - len(failed)}/{len(checks)} checks passed")
    if not checks:
        # "0/0 checks passed" with exit 0 is how an empty install reported
        # itself: a validation command succeeding because it validated
        # nothing. Every check needs an asset on disk, so no assets means no
        # checks, and that is a failure to report rather than a pass.
        from .build import missing

        absent = missing(reg)
        print()
        print(f"NOTHING WAS CHECKED: {len(absent)} of {len(reg.assets)} "
              f"declared assets are not on disk, so no check could run.")
        print("Fetch them with `lobemap fetch`, or rebuild them from "
              "source with `lobemap build --all`.")
        return 1
    return 1 if failed else 0


def cmd_nomenclature(args) -> int:
    """Audit the nomenclature table against the atlases. Read-only by default.

    This used to re-derive the whole table and save it, which was destructive
    in a way nothing reported. A mechanical derivation can only emit identity
    relations, so every curated merge, split and rename was replaced by an
    identity and the information was gone. Grabe's `VP1(L)` is recorded as a
    merge onto VP1d;VP1l;VP1m; a regeneration flattened it to an exact match
    on `VP1`, across eight rows, and printed a cheerful summary.

    So: report differences and change nothing unless asked. `--add-missing`
    adds rows for published names that have none, the one case a machine can
    decide; `--prune-stale` removes rows for names an atlas no longer
    publishes. Neither alters an existing row.

    Reported PER SPACE. There is no global canonical set: an atlas is only
    shown in its own space, so names only have to agree there.
    """
    import csv as _csv

    from .core.names import (
        Nomenclature,
        audit_atlas,
        clean_reference_name,
        normalize,
        parse_roi,
    )
    from .core.registry import Registry

    root = _registry_root(args)
    reg = Registry.load(root, validate=False)
    path = root / "nomenclature.csv"
    nom = Nomenclature.load(path)

    audits: dict[str, list] = {}
    unreadable: list[str] = []
    for space_id in reg.spaces:
        for atlas in reg.atlases_in_space(space_id):
            try:
                ms = reg.mesh(atlas.asset)
            except (FileNotFoundError, KeyError):
                unreadable.append(atlas.id)
                continue
            audits.setdefault(space_id, []).append(
                (atlas, audit_atlas(nom, atlas.id, list(ms.names)))
            )

    problems = 0
    for space_id, entries in audits.items():
        print(f"{space_id}  ({len(reg.vocabulary(space_id))} names)")
        for atlas, a in entries:
            bits = [f"{len(atlas.compartments)} compartments"]
            if a.curated:
                bits.append(f"{len(a.curated)} curated")
            if a.missing:
                bits.append(f"{len(a.missing)} MISSING")
            if a.stale:
                bits.append(f"{len(a.stale)} STALE")
            print(f"  {a.atlas:<22} {', '.join(bits)}")
            for name in a.missing:
                print(f"      missing: {name}")
                problems += 1
            for name in a.stale:
                print(f"      stale:   {name}")
                problems += 1
            for c in a.curated:
                print(f"      curated: {c.published_name} -> "
                      f"{';'.join(c.canonical)} ({c.relation})")
        print()

    if unreadable:
        print(f"not built, so not audited: {', '.join(sorted(unreadable))}")
        print()

    if args.add_missing or args.prune_stale:
        changed = 0
        for entries in audits.values():
            for atlas, a in entries:
                names = list(reg.mesh(atlas.asset).names)
                if args.add_missing and a.missing:
                    changed += len(nom.add_missing(a.atlas, names))
                if args.prune_stale and a.stale:
                    changed += nom.drop(a.atlas, a.stale)
        if changed:
            nom.save(path)
            print(f"wrote {changed} change(s) -> {path}")
        else:
            print("nothing to change")
        return 0

    if problems:
        print(f"{problems} difference(s). Nothing was written: re-deriving "
              f"the table would replace curated relations with identities.")
        print("Apply the mechanical part with --add-missing / --prune-stale.")
        return 1

    print("the table matches the atlases")

    if args.cross_check:
        ref: list[str] = []
        with open(args.cross_check, newline="", encoding="utf-8-sig") as fh:
            for row in _csv.DictReader(fh):
                value = row.get(args.column)
                if value:
                    ref.append(parse_roi(clean_reference_name(value))[0])
        result = nom.cross_check(ref)
        print()
        print(f"cross-check against {Path(args.cross_check).name} "
              f"[{args.column}]: {len({normalize(r) for r in ref})} names")
        if result["only_reference"]:
            print(f"  in reference but in NO atlas "
                  f"({len(result['only_reference'])}): "
                  f"{', '.join(result['only_reference'])}")
        if result["only_here"]:
            print(f"  in atlases but not in reference "
                  f"({len(result['only_here'])}): "
                  f"{', '.join(result['only_here'])}")
        if not result["only_reference"] and not result["only_here"]:
            print("  fully consistent")
    return 0


def cmd_reconcile(args) -> int:
    """Pair two atlases by geometry and report name disagreements."""
    from .core.registry import Registry
    from .core.resolve import resolve
    from .validate.reconcile import format_report, reconcile

    root = _registry_root(args)
    reg = Registry.load(root, data_root=_data_root(args, root))
    a_atlas, b_atlas = reg.atlases[args.a], reg.atlases[args.b]
    space = args.space or a_atlas.native_space
    a = (reg.mesh(a_atlas.asset) if a_atlas.native_space == space
         else resolve(reg, a_atlas.asset, space))
    b = (reg.mesh(b_atlas.asset) if b_atlas.native_space == space
         else resolve(reg, b_atlas.asset, space))
    matches, ua, ub = reconcile(
        a, b, max_distance_um=args.max_distance,
        ambiguity_ratio=args.ambiguity_ratio,
    )
    print(format_report(matches, ua, ub, args.a, args.b))
    return 0


def cmd_bridge(args) -> int:
    """Bridge an asset into another space and cache the result."""
    import time

    from .core.registry import Registry
    from .core.resolve import cache_root, resolve

    root = _registry_root(args)
    reg = Registry.load(root, data_root=_data_root(args, root))
    t0 = time.perf_counter()
    out = resolve(
        reg, args.asset, args.to, mirror=args.mirror, use_cache=not args.no_cache
    )
    dt = time.perf_counter() - t0
    d = out.meta.get("derivation", {}).get("params", {})
    print(f"{args.asset} -> {args.to}{' (mirrored)' if args.mirror else ''}")
    print(f"  route        : {' -> '.join(d.get('path', ['?']))}")
    print(f"  transforms   : {', '.join(d.get('classes', [])) or 'none'}")
    print(f"  warps        : {d.get('n_warps', '?')}  "
          f"needs binary: {d.get('needs_binary', '?')}")
    print(f"  extent (um)  : {out.extent_um().round(1)}")
    print(f"  non-finite   : {d.get('n_nonfinite', 0)}")
    print(f"  elapsed      : {dt:.1f}s")
    print(f"  cache        : {cache_root()}")
    return 0


def cmd_repair(args) -> int:
    """Make stored meshes watertight, in place."""
    from .core.meshfmt import MeshSet
    from .core.meshrepair import repair_meshset
    from .core.registry import Registry

    reg = Registry.load(_registry_root(args), validate=False)
    targets = args.assets or [
        a.id for a in reg.assets.values()
        if a.kind == "meshset" and a.path.exists()
    ]
    rc = 0
    for aid in targets:
        asset = reg.assets[aid]
        ms = MeshSet.load(asset.path)
        fixed, rep = repair_meshset(ms)
        print(f"{aid}: {rep.summary()}")
        if rep.method:
            counts = {}
            for m in rep.method.values():
                counts[m] = counts.get(m, 0) + 1
            print(f"    methods: {counts}")
        for name, pct in sorted(
            rep.large_changes.items(), key=lambda kv: -abs(kv[1])
        ):
            print(f"    !! {name} volume changed {pct:+.1f}% -- inspect")
        if rep.still_open:
            print(f"    still open: {', '.join(rep.still_open[:6])}")
            rc = 1
        if rep.failed:
            print(f"    failed: {rep.failed[:3]}")
            rc = 1
        if not args.dry_run and (rep.repaired or rep.failed):
            fixed.save(asset.path)
            print(f"    written {asset.path.name} "
                  f"(hash {ms.content_hash()} -> {fixed.content_hash()})")
    return rc


def cmd_build(args) -> int:
    """Derive built assets from their sources, per registry/recipes.toml."""
    from .build import build_asset, buildable, load_recipes, missing
    from .core.registry import Registry

    root = _registry_root(args)
    reg = Registry.load(root, data_root=_data_root(args, root))
    recipes = load_recipes(reg.root)
    known = buildable(reg, recipes)

    if args.list:
        absent = set(missing(reg))
        print(f"{len(known)} assets have a recipe:")
        for a in known:
            cost = "  EXPENSIVE" if recipes[a].expensive else ""
            print(f"  {'MISSING' if a in absent else 'present'}  {a}{cost}")
        no_recipe = [a for a in reg.assets if a not in recipes]
        if no_recipe:
            print()
            print("No recipe:")
            for a in no_recipe:
                print(f"  {a}")
        return 0

    if args.all:
        # Expensive recipes are excluded unless asked for by name: nobody
        # should start ~19 GB of downloads and hours of compute by typing
        # `--all`.
        cheap = buildable(reg, recipes, include_expensive=False)
        wanted = cheap if args.overwrite else [
            a for a in cheap if a in set(missing(reg))
        ]
        skipped = [a for a in known if a not in cheap]
        if skipped:
            print(f"skipping {len(skipped)} expensive recipe(s): "
                  f"{', '.join(skipped)}")
            print("build them by name when you want them.")
    else:
        wanted = list(args.asset or ())
    if not wanted:
        print("nothing to build; --list shows what has a recipe")
        return 0

    failures = []
    for i, asset in enumerate(wanted, start=1):
        print(f"[{i}/{len(wanted)}] {asset}")
        try:
            result = build_asset(
                reg, asset, recipes=recipes, overwrite=args.overwrite,
                progress=lambda m: print(f"    {m}"),
            )
        except Exception as exc:                      # noqa: BLE001 - reported
            print(f"    FAILED  {type(exc).__name__}: {exc}")
            failures.append(asset)
            continue
        print(f"    wrote {result.path}  content_hash={result.content_hash}")

    print()
    print(f"{len(wanted) - len(failures)}/{len(wanted)} built")
    if failures:
        print(f"failed: {', '.join(failures)}")
    return 1 if failures else 0


def _install_crash_log() -> None:
    """Arm faulthandler for a native crash, and say nothing if none comes.

    A GUI crash here is native -- vispy, Qt or the GPU driver -- so Python
    dies on a signal with an empty log and nothing to go on. faulthandler
    turns that into a stack trace, and it must write to its OWN unbuffered
    file: sending it to stderr lost the one crash it was added for, because
    the process died partway through the write. `all_threads` matters
    because the fault came from a worker thread, not the main one.

    What changed is the noise. It used to announce the path on every
    launch and leave the file behind, so an ordinary run printed a line
    about a crash that had not happened and dropped an empty file in the
    temp directory -- 54 of them out of 55 launches here, against a single
    real report. The net is worth keeping; the commentary is not. So: warn
    only when something was actually written, and clean up when nothing
    was.

    A crash never reaches `atexit`, which is exactly why the report
    survives one.
    """
    import atexit
    import faulthandler
    import glob
    import tempfile

    explicit = os.environ.get("LOBEMAP_CRASH_LOG")
    tmp = Path(tempfile.gettempdir())
    path = Path(explicit) if explicit else tmp / f"lobemap-crash-{os.getpid()}.log"

    # Sweep empties left by runs that were killed rather than exited --
    # force-quitting the window skips atexit too. A log still held open by
    # a live viewer cannot be unlinked on Windows, so those skip themselves.
    if not explicit:
        for old in glob.glob(str(tmp / "lobemap-crash-*.log")):
            with contextlib.suppress(OSError):
                if os.path.getsize(old) == 0:
                    os.unlink(old)

    try:
        # Held open for the life of the process on purpose: faulthandler
        # writes from a signal handler, so it must not be closed early.
        handle = open(path, "wb", buffering=0)  # noqa: SIM115
    except OSError:
        return
    faulthandler.enable(file=handle, all_threads=True)
    if explicit:
        # Asked for by name, so the caller wants to know where it is.
        print(f"crash log: {path}", flush=True)

    def _finish() -> None:
        with contextlib.suppress(Exception):
            faulthandler.disable()
            handle.close()
            size = path.stat().st_size if path.exists() else 0
            if size:
                print(f"a crash report was written to {path}", file=sys.stderr)
            elif not explicit:
                path.unlink()

    atexit.register(_finish)


def cmd_view(args) -> int:
    _install_crash_log()

    # A fresh clone has no data: nothing runs on `uv sync`, so this is the
    # first opportunity to get it.
    root = _registry_root(args)
    _autofetch(root, _data_root(args, root))

    from .viewer.app import run

    run(
        root,
        args.space,
        ndisplay=args.ndisplay,
        # `--show` was parsed and then never forwarded, so it silently did
        # nothing: layers start hidden, and asking for one by name was the
        # documented way to see it.
        show=tuple(args.show or ()),
    )
    return 0


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="lobemap")
    p.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    p.add_argument("--registry", help="registry directory (default: ./registry)")
    p.add_argument("--data-root", default=None,
                   help="where asset files live (default: <registry>/data in a "
                        "checkout, else the user cache directory)")
    sub = p.add_subparsers(dest="cmd", required=True)

    mn = sub.add_parser("manifest", help="record checksums for fetchable data")
    mn.add_argument("--base-url", default=None,
                    help="where the artifacts will be published")
    mn.add_argument("--output", default=None, help="default: <registry>/manifest.toml")
    mn.add_argument("--prune", action="store_true",
                    help="drop records for artifacts not on disk instead of "
                         "keeping them")
    mn.set_defaults(func=cmd_manifest)

    ft = sub.add_parser("fetch", help="download or verify data artifacts")
    ft.add_argument("--manifest", default=None)
    ft.add_argument("--base-url", default=None, help="overrides the manifest's")
    ft.add_argument("--asset", action="append", help="only this asset; repeatable")
    ft.add_argument("--nostains", action="store_true",
                    help="skip the three virtual stains, which are 2.4 GB of "
                         "the 2.5 GB total; everything else is 76 MB")
    ft.add_argument("--check", action="store_true",
                    help="verify what is present and exit; download nothing")
    ft.set_defaults(func=cmd_fetch)

    pk = sub.add_parser("pack",
                        help="write upload-ready copies of the data artifacts")
    pk.add_argument("asset", nargs="*",
                    help="asset ids; omit to list what is available")
    pk.add_argument("--all", action="store_true",
                    help="pack every artifact in the manifest")
    pk.add_argument("--manifest", default=None)
    pk.add_argument("--output", default=None,
                    help="where to write them (default: <data root>/.pack)")
    pk.add_argument("--overwrite", action="store_true",
                    help="re-create files that are already there")
    pk.set_defaults(func=cmd_pack)

    bd = sub.add_parser("build", help="derive built assets from their sources")
    bd.add_argument("asset", nargs="*", help="asset ids; omit with --all")
    bd.add_argument("--all", action="store_true",
                    help="build every asset with a recipe that is missing")
    bd.add_argument("--list", action="store_true",
                    help="show which assets have a recipe, and their state")
    bd.add_argument("--overwrite", action="store_true",
                    help="rebuild even if the file is already there")
    bd.set_defaults(func=cmd_build)

    v = sub.add_parser("view", help="open a coordinate space")
    v.add_argument("space", nargs="?", default=DEFAULT_SPACE,
                   help=f"space id; `lobemap spaces` lists them "
                        f"(default: {DEFAULT_SPACE})")
    v.add_argument("--ndisplay", type=int, default=3, choices=(2, 3))
    v.add_argument("--show", action="append", metavar="LAYER",
                   help="start this layer visible; an asset id or a role "
                        "such as virtual_stain. Repeatable.")
    v.set_defaults(func=cmd_view)

    val = sub.add_parser("validate", help="load and check the registry")
    val.add_argument("--strict", action="store_true",
                     help="also require flybrains to know every template")
    val.set_defaults(func=cmd_validate)

    sp_ = sub.add_parser("spaces", help="list spaces and their bridging status")
    sp_.set_defaults(func=cmd_spaces)

    chk = sub.add_parser("check", help="run the geometry validation harness")
    chk.add_argument("--roundtrip", nargs=2, metavar=("SRC", "VIA"),
                     help="e.g. --roundtrip JRCFIB2018F FAFB14")
    chk.add_argument("--compare", nargs=3, metavar=("A", "B", "SPACE"),
                     help="bridge atlas B into SPACE and compare against atlas A")
    chk.set_defaults(func=cmd_check)

    nm = sub.add_parser("nomenclature",
                        help="audit the nomenclature table against the atlases")
    nm.add_argument("--add-missing", action="store_true",
                    help="add rows for published names that have none; "
                         "existing rows are never touched")
    nm.add_argument("--prune-stale", action="store_true",
                    help="remove rows for names an atlas no longer publishes")
    nm.add_argument("--cross-check", help="CSV of curated names to compare against")
    nm.add_argument("--column", default="canonical_glomerulus",
                    help="column in the cross-check CSV holding the name")
    nm.set_defaults(func=cmd_nomenclature)

    rc = sub.add_parser("reconcile",
                        help="pair two atlases by geometry, compare names")
    rc.add_argument("a")
    rc.add_argument("b")
    rc.add_argument("--space", help="space to compare in (default: A's native)")
    rc.add_argument("--max-distance", type=float, default=5.0)
    rc.add_argument("--ambiguity-ratio", type=float, default=0.5,
                    help="match must be this much closer than the runner-up")
    rc.set_defaults(func=cmd_reconcile)

    br = sub.add_parser("bridge", help="bridge an asset into another space")
    br.add_argument("asset")
    br.add_argument("--to", required=True, help="target space id")
    br.add_argument("--mirror", action="store_true")
    br.add_argument("--no-cache", action="store_true")
    br.set_defaults(func=cmd_bridge)

    tz = sub.add_parser("tozarr", help="rewrite a volume as multiscale OME-Zarr")
    tz.add_argument("input", help="an .npz volume (its .data.npy is picked up)")
    tz.add_argument("output", nargs="?", default=None,
                    help="destination .zarr (default: alongside the input)")
    tz.add_argument("--chunk", type=int, default=64,
                    help="cubic chunk edge; 64 keeps a uint8 chunk at 256 KB")
    tz.add_argument("--min-extent", type=int, default=128,
                    help="stop halving once the largest axis is this small")
    tz.add_argument("--force", action="store_true")
    tz.set_defaults(func=cmd_tozarr)

    st = sub.add_parser("stain", help="build a virtual neuropil stain")
    st.add_argument("--space", required=True)
    st.add_argument("--asset-id", required=True)
    st.add_argument("--server", default="neuprint.janelia.org")
    st.add_argument("--dataset", default="hemibrain:v1.2.1")
    st.add_argument("--roi", action="append",
                    help="restrict to these ROIs (repeatable); omit for whole brain")
    st.add_argument("--bounds-from", help="mesh asset id to take bounds from")
    st.add_argument("--bounds", nargs=6, metavar=("X0","Y0","Z0","X1","Y1","Z1"),
                    help="explicit grid bounds in um; points outside are dropped, "
                         "which is how the male CNS is cropped to brain")
    st.add_argument("--confidence", type=float, default=0.5)
    st.add_argument("--voxel", type=float, default=0.5,
                    help="bin size in um; halving it doubles the grid in each "
                         "axis and multiplies its size by 8")
    st.add_argument("--sigma", type=float, default=0.9,
                    help="point-spread width in um; this, not --voxel, sets "
                         "the stain's actual resolution")
    st.add_argument("--dtype", choices=("uint8", "uint16"), default="uint8",
                    help="stored sample type; uint8 matches the confocal "
                         "stacks this emulates and halves the file")
    st.add_argument("--workdir", default=None,
                    help="scratch space for grids too large for RAM "
                         "(default: <registry>/data/.stainwork)")
    st.add_argument("--keep-workdir", action="store_true",
                    help="do not delete the scratch space afterwards")
    st.add_argument("--slabs", type=int, default=24)
    st.add_argument("--bucket", choices=("hemibrain", "malecns", "fafb"),
                    help="read presynapses from a bulk release instead of neuPrint")
    st.add_argument("--path", help="shard directory or table file for --bucket")
    st.add_argument("--token")
    st.set_defaults(func=cmd_stain)

    rp = sub.add_parser("repair", help="make stored meshes watertight")
    rp.add_argument("assets", nargs="*", help="asset ids (default: all meshsets)")
    rp.add_argument("--dry-run", action="store_true")
    rp.set_defaults(func=cmd_repair)

    ing = sub.add_parser("ingest", help="build canonical assets from sources")
    ingsub = ing.add_subparsers(dest="source", required=True)
    np_ = ingsub.add_parser("neuprint", help="AL ROI meshes from neuPrint")
    np_.add_argument("--server", default="neuprint.janelia.org")
    np_.add_argument("--dataset", default="hemibrain:v1.2.1")
    np_.add_argument("--role", default="glomeruli",
                     choices=("glomeruli", "neuropil"))
    np_.add_argument("--asset-id", required=True)
    np_.add_argument("--atlas-id", help="register names under this atlas id")
    np_.add_argument("--no-repair", action="store_true",
                     help="skip watertight repair (not recommended)")
    np_.add_argument("--token")
    np_.set_defaults(func=cmd_ingest_neuprint)


    # Bare `lobemap` opens the viewer. argparse would otherwise exit 2 with
    # a usage message, which is the right answer for a mistyped command and
    # the wrong one for the command a GUI application is mostly used for.
    # An explicit argv of [] is left alone: a caller passing an empty list
    # means it, whereas None means "read sys.argv".
    if argv is None and len(sys.argv) == 1:
        argv = ["view"]
    args = p.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
