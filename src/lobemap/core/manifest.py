"""Fetchable data artifacts: manifest, verification, download.

Settled by measurement: the flybrains transform bundles alone are 10.3 GB and
the stains another 2.4 GB, so **fetch, never ship**. What travels in the wheel
is the registry's metadata -- the TOMLs and the nomenclature table, a few tens
of kilobytes. Everything with voxels or vertices in it is fetched once and
cached, after which scenes open offline.

Two artifact kinds, because a Zarr store is a directory:

- `file` -- an `.npz` mesh container, transferred as-is.
- `dir` -- a `.zarr` store, transferred as a zip and unpacked on arrival.

**The checksum is of the transferred bytes**, which for a directory means the
zip. Hashing a directory's contents instead would invite a reader to hash it
differently -- file order, compression level, timestamps -- and get a mismatch
on data that is perfectly fine.

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
import zipfile
from dataclasses import dataclass
from pathlib import Path

CHUNK = 1 << 20
MANIFEST_VERSION = 1


@dataclass(frozen=True)
class Artifact:
    """One fetchable thing, identified by the asset that needs it."""

    asset: str
    path: str                  # relative to the data root
    kind: str                  # "file" or "dir"
    sha256: str                # of the transferred bytes (the zip, for a dir)
    size: int

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
    files = sorted(p for p in src.rglob("*") if p.is_file())
    with zipfile.ZipFile(dst, "w", zipfile.ZIP_DEFLATED, compresslevel=1) as zf:
        for p in files:
            info = zipfile.ZipInfo(str(p.relative_to(src)).replace("\\", "/"),
                                   date_time=(1980, 1, 1, 0, 0, 0))
            info.compress_type = zipfile.ZIP_DEFLATED
            info.create_system = 0
            info.external_attr = 0o644 << 16
            zf.writestr(info, p.read_bytes())
    return dst


def unzip_directory(archive: Path, dst: Path) -> Path:
    dst = Path(dst)
    if dst.exists():
        shutil.rmtree(dst)
    dst.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(archive) as zf:
        zf.extractall(dst)
    return dst


def build(data_root: Path, assets, workdir: Path | None = None,
          progress=None) -> list[Artifact]:
    """Describe every asset file present under `data_root`."""
    data_root = Path(data_root)
    workdir = Path(workdir) if workdir else data_root / ".manifest"
    out: list[Artifact] = []
    for i, asset in enumerate(assets, start=1):
        path = Path(asset.path)
        if not path.exists():
            continue
        rel = path.relative_to(data_root).as_posix()
        if path.is_dir():
            workdir.mkdir(parents=True, exist_ok=True)
            archive = zip_directory(path, workdir / f"{path.name}.zip")
            digest, size = sha256_file(archive)
            archive.unlink()
            kind = "dir"
        else:
            digest, size = sha256_file(path)
            kind = "file"
        out.append(Artifact(asset.id, rel, kind, digest, size))
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
        "# sha256 is of the transferred bytes: for a .zarr store, of its zip.",
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
            "",
        ]
    return "\n".join(lines)


def load(path: Path) -> tuple[list[Artifact], str | None]:
    with Path(path).open("rb") as fh:
        body = tomllib.load(fh)
    arts = [
        Artifact(asset=k, path=v["path"], kind=v.get("kind", "file"),
                 sha256=v["sha256"], size=int(v["size"]))
        for k, v in sorted(body.get("artifacts", {}).items())
    ]
    return arts, body.get("base_url")


@dataclass(frozen=True)
class Status:
    artifact: Artifact
    state: str        # "ok", "missing", "corrupt"
    detail: str = ""


def verify(artifacts, data_root: Path, workdir: Path | None = None,
           progress=None) -> list[Status]:
    """Check what is on disk against the manifest."""
    data_root = Path(data_root)
    workdir = Path(workdir) if workdir else data_root / ".manifest"
    out = []
    for i, art in enumerate(artifacts, start=1):
        target = data_root / art.path
        if not target.exists():
            out.append(Status(art, "missing"))
        else:
            if art.kind == "dir":
                workdir.mkdir(parents=True, exist_ok=True)
                archive = zip_directory(target, workdir / f"{target.name}.zip")
                digest, size = sha256_file(archive)
                archive.unlink()
            else:
                digest, size = sha256_file(target)
            if digest == art.sha256:
                out.append(Status(art, "ok"))
            else:
                out.append(Status(art, "corrupt",
                                  f"sha256 {digest[:12]} != {art.sha256[:12]}, "
                                  f"{size} bytes vs {art.size}"))
        if progress is not None:
            progress(i, len(artifacts), out[-1])
    if workdir.exists() and not any(workdir.iterdir()):
        workdir.rmdir()
    return out


def fetch(artifacts, data_root: Path, base_url: str, workdir: Path | None = None,
          progress=None) -> list[Status]:
    """Download and verify. A failed checksum leaves nothing behind."""
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
                tmp.unlink(missing_ok=True)
                out.append(Status(art, "corrupt",
                                  f"downloaded sha256 {digest[:12]} != "
                                  f"{art.sha256[:12]}"))
            else:
                target = data_root / art.path
                target.parent.mkdir(parents=True, exist_ok=True)
                if art.kind == "dir":
                    unzip_directory(tmp, target)
                    tmp.unlink(missing_ok=True)
                else:
                    tmp.replace(target)
                out.append(Status(art, "ok", f"{size} bytes"))
        except Exception as exc:                    # noqa: BLE001 - reported
            tmp.unlink(missing_ok=True)
            out.append(Status(art, "missing", f"{type(exc).__name__}: {exc}"))
        if progress is not None:
            progress(i, len(artifacts), out[-1])
    if workdir.exists() and not any(workdir.iterdir()):
        workdir.rmdir()
    return out


__all__ = [
    "Artifact",
    "Status",
    "build",
    "dump",
    "fetch",
    "load",
    "sha256_file",
    "unzip_directory",
    "verify",
    "zip_directory",
]
