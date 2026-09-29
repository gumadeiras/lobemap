"""Fetchable data artifacts: manifest, verification, download.

Settled by measurement: the flybrains transform bundles alone are 10.3 GB and
the stains another 2.4 GB, so **fetch, never ship**. What travels in the wheel
is the registry's metadata -- the TOMLs and the nomenclature table, a few tens
of kilobytes. Everything with voxels or vertices in it is fetched once and
cached, after which scenes open offline.

Two artifact kinds, because a Zarr store is a directory:

- `file` -- an `.npz` mesh container, transferred as-is.
- `dir` -- a `.zarr` store, transferred as a zip and unpacked on arrival.

**A download is checked against the transferred bytes**: `sha256` and `size`
are of the file as published, which for a directory is its zip. That pins
exactly what was uploaded, and it is the only check a download needs.

**A store on disk is checked against its content**, `tree_sha256` (see
`tree_digest`). Checking it by zipping it again made the answer depend on how
the zip came out: the platform byte in every entry, and the zlib build, whose
output at one level differs between builds. So a store that was perfectly
fine read as corrupt wherever either differed, and every check wrote a
temporary zip of up to 1.1 GB. `fetch` checks both: the zip before unpacking
it, the content after.

Format 1 manifests carry no `tree_sha256`. They still load, and still verify
downloads, but a store on disk cannot be checked against one and reports
`unverified` until the manifest is regenerated.

`base_url` points at the GitHub release the artifacts are published as.
`lobemap pack` produces the files to upload; the names it writes are the
names `fetch` requests, so a release's asset list maps one-to-one onto this
manifest. It stays optional: with no URL recorded, `fetch` says so
immediately rather than failing later with a network error.
"""

from __future__ import annotations

import hashlib
import json
import re
import shutil
import tomllib
import unicodedata
import zipfile
from dataclasses import dataclass
from pathlib import Path

from .atomic import replacing

CHUNK = 1 << 20
#: 2 adds `tree_sha256` and `files` to directory artifacts.
MANIFEST_VERSION = 2
#: zlib's default level, which is what the published zips were written at:
#: `ZipFile(compresslevel=1)` never reached them, because an entry written
#: from a `ZipInfo` carries its own level. Stated so the code says what it
#: does; changing it would change every published hash.
ZIP_LEVEL = 6


class ChecksumMismatch(ValueError):
    """Unpacked content that does not match the manifest."""


@dataclass(frozen=True)
class Artifact:
    """One fetchable thing, identified by the asset that needs it."""

    asset: str
    path: str                  # relative to the data root
    kind: str                  # "file" or "dir"
    sha256: str                # of the transferred bytes (the zip, for a dir)
    size: int                  # of the transferred bytes
    tree_sha256: str | None = None   # dir: of the unpacked content
    files: int | None = None         # dir: how many files that covers

    @property
    def transfer_name(self) -> str:
        return f"{self.path}.zip" if self.kind == "dir" else self.path


def sha256_file(path: Path, chunk: int = CHUNK) -> tuple[str, int]:
    h, n = hashlib.sha256(), 0
    with Path(path).open("rb") as fh:
        while block := fh.read(chunk):
            h.update(block)
            n += len(block)
    return h.hexdigest(), n


def _store_files(src: Path) -> list[Path]:
    """Every file in a store, in the order `zip_directory` writes them."""
    return sorted(p for p in Path(src).rglob("*") if p.is_file())


def _member_name(p: Path, src: Path) -> str:
    return str(p.relative_to(src)).replace("\\", "/")


def tree_digest(src: Path) -> tuple[str, int]:
    """sha256 of a store's content, and how many files it covers.

    One line per file -- its sha256, its size, and its name relative to the
    store as a JSON string, with `/` separators and in Unicode NFC -- sorted
    by name and hashed together. The files are the ones `zip_directory`
    packs, so a store and its zip describe the same content. Nothing here
    depends on the platform, a zip or the zlib build, and nothing is written.
    """
    src = Path(src)
    entries = []
    for p in _store_files(src):
        digest, size = sha256_file(p)
        name = unicodedata.normalize("NFC", _member_name(p, src))
        entries.append((name, digest, size))
    h = hashlib.sha256()
    for name, digest, size in sorted(entries):
        h.update(f"{digest} {size} {json.dumps(name, ensure_ascii=False)}\n"
                 .encode())
    return h.hexdigest(), len(entries)


def zip_directory(src: Path, dst: Path) -> Path:
    """Zip a store deterministically enough to re-hash to the same value.

    Entries are sorted and timestamps normalized, so zipping the same store
    twice produces identical bytes. Without that, a rebuild would appear to
    change data that had not changed.

    The creating system is pinned too. `ZipInfo` records 0 (MS-DOS) on
    Windows and 3 (Unix) elsewhere, one byte per entry, so the same store
    hashed differently on each: the published stains, zipped on Windows,
    failed `fetch --check` on macOS and were downloaded again by every
    `fetch`. 0 is the value the published hashes were recorded with.
    """
    src, dst = Path(src), Path(dst)
    dst.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(dst, "w", zipfile.ZIP_DEFLATED) as zf:
        for p in _store_files(src):
            info = zipfile.ZipInfo(_member_name(p, src),
                                   date_time=(1980, 1, 1, 0, 0, 0))
            info.compress_type = zipfile.ZIP_DEFLATED
            info.create_system = 0
            info.external_attr = 0o644 << 16
            zf.writestr(info, p.read_bytes(), compresslevel=ZIP_LEVEL)
    return dst


def unzip_directory(archive: Path, dst: Path, tree_sha256: str | None = None) -> Path:
    """Unpack beside `dst` and rename into place, replacing what is there.

    An interrupted unpack leaves nothing at `dst`. Unpacking in place left
    a store whose metadata had arrived and some of whose chunks had not,
    which opened without error and read zeros. With `tree_sha256`, content
    that does not match is not installed either: `ChecksumMismatch`.
    """
    dst = Path(dst)
    with replacing(dst) as scratch:
        with zipfile.ZipFile(archive) as zf:
            zf.extractall(scratch)
        if tree_sha256 is not None:
            digest, _ = tree_digest(scratch)
            if digest != tree_sha256:
                raise ChecksumMismatch(f"unpacked content sha256 {digest[:12]} "
                                       f"!= {tree_sha256[:12]}")
    return dst


def build(data_root: Path, assets, workdir: Path | None = None,
          progress=None, previous=()) -> list[Artifact]:
    """Describe every asset file present under `data_root`.

    A store's transfer hash is of its zip, which only `pack` and this can
    produce, so a store is zipped here to hash it -- unless `previous`
    already records it with the same content. Then its published zip still
    holds exactly that content, and re-zipping would only swap in whatever
    hash this machine's zlib gives, which the published file may not match.
    """
    data_root = Path(data_root)
    workdir = Path(workdir) if workdir else data_root / ".manifest"
    prior = {a.path: a for a in previous if a.kind == "dir"}
    out: list[Artifact] = []
    for i, asset in enumerate(assets, start=1):
        path = Path(asset.path)
        if not path.exists():
            continue
        rel = path.relative_to(data_root).as_posix()
        if path.is_dir():
            tree, n_files = tree_digest(path)
            old = prior.get(rel)
            if old is not None and old.tree_sha256 == tree:
                digest, size = old.sha256, old.size
            else:
                workdir.mkdir(parents=True, exist_ok=True)
                archive = zip_directory(path, workdir / f"{path.name}.zip")
                digest, size = sha256_file(archive)
                archive.unlink()
            art = Artifact(asset.id, rel, "dir", digest, size, tree, n_files)
        else:
            digest, size = sha256_file(path)
            art = Artifact(asset.id, rel, "file", digest, size)
        out.append(art)
        if progress is not None:
            progress(i, len(assets), asset.id, size)
    if workdir.exists() and not any(workdir.iterdir()):
        workdir.rmdir()
    return sorted(out, key=lambda a: a.path)


def _toml_str(text: str) -> str:
    """A TOML basic string. JSON's escapes are TOML's, except that TOML
    also requires DEL to be escaped."""
    return json.dumps(text, ensure_ascii=False).replace("\x7f", "\\u007f")


def _toml_key(key: str) -> str:
    """Bare when TOML allows it, so ordinary ids read as they always have;
    quoted otherwise, or `a.b` would open a nested table."""
    return key if re.fullmatch(r"[A-Za-z0-9_-]+", key) else _toml_str(key)


def dump(artifacts, base_url: str | None = None) -> str:
    lines = [
        "# Fetchable data artifacts. Generated by `lobemap manifest`.",
        "# sha256 and size are of the transferred bytes: for a .zarr store, of its zip.",
        "# tree_sha256 is of a store's content on disk; `fetch --check` compares it.",
        "",
        f"version = {MANIFEST_VERSION}",
    ]
    if base_url:
        lines.append(f"base_url = {_toml_str(base_url)}")
    else:
        lines += [
            "# base_url is unset: nothing is published yet. Pass --base-url to",
            "# `lobemap manifest`, or `--base-url` to `lobemap fetch`.",
        ]
    lines.append("")
    for a in artifacts:
        lines += [
            f"[artifacts.{_toml_key(a.asset)}]",
            f"path = {_toml_str(a.path)}",
            f"kind = {_toml_str(a.kind)}",
            f"sha256 = {_toml_str(a.sha256)}",
            f"size = {int(a.size)}",
        ]
        if a.tree_sha256 is not None:
            lines.append(f"tree_sha256 = {_toml_str(a.tree_sha256)}")
        if a.files is not None:
            lines.append(f"files = {int(a.files)}")
        lines.append("")
    return "\n".join(lines)


def load(path: Path) -> tuple[list[Artifact], str | None]:
    """Read a manifest of any format up to `MANIFEST_VERSION`."""
    with Path(path).open("rb") as fh:
        body = tomllib.load(fh)
    version = int(body.get("version", 1))
    if version > MANIFEST_VERSION:
        raise ValueError(f"{path} is manifest format {version}; this lobemap "
                         f"reads up to {MANIFEST_VERSION}. Upgrade lobemap.")
    arts = [
        Artifact(asset=k, path=v["path"], kind=v.get("kind", "file"),
                 sha256=v["sha256"], size=int(v["size"]),
                 tree_sha256=v.get("tree_sha256"),
                 files=int(v["files"]) if "files" in v else None)
        for k, v in sorted(body.get("artifacts", {}).items())
    ]
    return arts, body.get("base_url")


@dataclass(frozen=True)
class Status:
    artifact: Artifact
    state: str        # "ok", "missing", "corrupt", "unverified"
    detail: str = ""


def verify(artifacts, data_root: Path, progress=None) -> list[Status]:
    """Check what is on disk against the manifest.

    Read-only: a file is hashed as it is, a store by its content, so the
    answer is the same on every platform and zlib build and nothing is
    written, not even a temporary zip.
    """
    data_root = Path(data_root)
    out = []
    for i, art in enumerate(artifacts, start=1):
        target = data_root / art.path
        if not target.exists():
            status = Status(art, "missing")
        elif art.kind == "dir":
            if not target.is_dir():
                status = Status(art, "corrupt", "not a directory")
            elif art.tree_sha256 is None:
                status = Status(art, "unverified",
                                "the manifest records only this store's zip "
                                "(format 1); regenerate it with `lobemap "
                                "manifest` to check the store on disk")
            else:
                digest, n_files = tree_digest(target)
                status = (Status(art, "ok") if digest == art.tree_sha256 else
                          Status(art, "corrupt",
                                 f"content sha256 {digest[:12]} != "
                                 f"{art.tree_sha256[:12]}, {n_files} files "
                                 f"vs {art.files}"))
        elif not target.is_file():
            status = Status(art, "corrupt", "not a file")
        else:
            digest, size = sha256_file(target)
            status = (Status(art, "ok") if digest == art.sha256 else
                      Status(art, "corrupt",
                             f"sha256 {digest[:12]} != {art.sha256[:12]}, "
                             f"{size} bytes vs {art.size}"))
        out.append(status)
        if progress is not None:
            progress(i, len(artifacts), status)
    return out


def fetch(artifacts, data_root: Path, base_url: str, workdir: Path | None = None,
          progress=None) -> list[Status]:
    """Download and verify. A failed checksum leaves nothing behind.

    A store is checked twice: the zip against `sha256` before it is
    unpacked, and what it unpacks to against `tree_sha256` before that is
    moved into place.
    """
    import urllib.request

    data_root = Path(data_root)
    data_root.mkdir(parents=True, exist_ok=True)
    workdir = Path(workdir) if workdir else data_root / ".manifest"
    workdir.mkdir(parents=True, exist_ok=True)
    base = base_url.rstrip("/")
    out = []
    for i, art in enumerate(artifacts, start=1):
        url = f"{base}/{art.transfer_name}"
        tmp = workdir / f"{Path(art.transfer_name).name}.part"
        try:
            with urllib.request.urlopen(url) as resp, tmp.open("wb") as fh:
                shutil.copyfileobj(resp, fh, CHUNK)
            digest, size = sha256_file(tmp)
            if digest != art.sha256:
                raise ChecksumMismatch(f"downloaded sha256 {digest[:12]} != "
                                       f"{art.sha256[:12]}")
            target = data_root / art.path
            target.parent.mkdir(parents=True, exist_ok=True)
            if art.kind == "dir":
                unzip_directory(tmp, target, tree_sha256=art.tree_sha256)
            else:
                tmp.replace(target)
            out.append(Status(art, "ok", f"{size} bytes"))
        except ChecksumMismatch as exc:
            out.append(Status(art, "corrupt", str(exc)))
        except Exception as exc:                    # noqa: BLE001 - reported
            out.append(Status(art, "missing", f"{type(exc).__name__}: {exc}"))
        finally:
            tmp.unlink(missing_ok=True)
        if progress is not None:
            progress(i, len(artifacts), out[-1])
    if workdir.exists() and not any(workdir.iterdir()):
        workdir.rmdir()
    return out


__all__ = [
    "Artifact",
    "ChecksumMismatch",
    "Status",
    "build",
    "dump",
    "fetch",
    "load",
    "sha256_file",
    "tree_digest",
    "unzip_directory",
    "verify",
    "zip_directory",
]
