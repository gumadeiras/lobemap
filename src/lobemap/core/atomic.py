"""Write beside the destination, then rename into place.

An artifact counts as present when its path exists: `fetch` skips what is on
disk, `build` refuses to overwrite it and the viewer opens it. So a write
that stops part-way must leave nothing at the destination. A partial Zarr
store is the worst case, because its metadata is written first: it opens
without error and reads zeros wherever a chunk is missing.

`replacing(target)` yields a path with the target's own name inside a hidden
staging directory beside it. The name is the real one because writers derive
things from it -- `Volume.save` its format and its sidecar's name, and the
Zarr writer its default title. The directory is beside the target so that
the final rename stays on one filesystem. Only a body that returns moves the
result into place, with anything the writer put next to it moved first, so
the target never exists without its sidecar. On any exception, including
KeyboardInterrupt, the staging directory is removed. A hard kill can leave
one behind; it is hidden and never has the target's name.
"""

from __future__ import annotations

import os
import secrets
import shutil
import tempfile
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path


@contextmanager
def replacing(target: str | Path) -> Iterator[Path]:
    """Yield where to write `target`; install it only if the body returns."""
    target = Path(target)
    target.parent.mkdir(parents=True, exist_ok=True)
    stage = Path(tempfile.mkdtemp(prefix=f".{target.name}.partial-",
                                  dir=target.parent))
    try:
        written = stage / target.name
        yield written
        if not os.path.lexists(written):
            raise FileNotFoundError(f"nothing was written for {target}")
        for extra in sorted(p for p in stage.iterdir() if p.name != target.name):
            _install(extra, target.parent / extra.name)
        _install(written, target)
    finally:
        shutil.rmtree(stage, ignore_errors=True)


def _install(src: Path, dst: Path) -> None:
    """Rename `src` onto `dst`, replacing whatever is there.

    A file over a file is one atomic rename. A directory cannot be renamed
    over a non-empty one, so the old one is moved aside first and removed
    after; in between, `dst` is briefly absent, which reads as missing
    rather than as partial. A symlink at `dst` is replaced, never followed.
    """
    if not os.path.lexists(dst) or (src.is_file() and not dst.is_dir()):
        os.replace(src, dst)
        return
    old = dst.with_name(f".{dst.name}.old-{secrets.token_hex(4)}")
    os.replace(dst, old)
    try:
        os.replace(src, dst)
    except BaseException:
        os.replace(old, dst)
        raise
    if old.is_dir() and not old.is_symlink():
        shutil.rmtree(old, ignore_errors=True)
    else:
        old.unlink(missing_ok=True)


__all__ = ["replacing"]
