"""`lobemap pack` must leave behind exactly what `fetch` will ask for.

`manifest` and `fetch --check` zip a Zarr store to hash it and then delete
the archive, so before this command there was no way to obtain the bytes a
downloader receives. The properties that matter are that the file written
is byte-identical to what the manifest promises, that it is named what
`fetch` will request, and that a manifest which no longer describes the
data is caught here rather than after the upload.
"""

from __future__ import annotations

import subprocess
import sys
import zipfile

import pytest

from lobemap.cli import main
from lobemap.core import manifest as mf


@pytest.fixture
def published(tmp_path):
    """A data root with one store and one plain file, plus its manifest."""
    data = tmp_path / "data"
    store = data / "thing.zarr"
    (store / "0").mkdir(parents=True)
    (store / "0" / "0.0").write_bytes(b"chunk" * 100)
    (store / ".zattrs").write_text('{"a": 1}')
    (data / "small.npz").write_bytes(b"npz-bytes")

    class Asset:
        def __init__(self, id, path):
            self.id, self.path = id, path

    arts = mf.build(data, [Asset("thing", store), Asset("small", data / "small.npz")])
    registry = tmp_path / "registry"
    registry.mkdir()
    (registry / "manifest.toml").write_text(mf.dump(arts), encoding="utf-8")
    return data, registry, {a.asset: a for a in arts}


def _pack(registry, data, *extra):
    return main(["--registry", str(registry), "--data-root", str(data),
                 "pack", *extra])


def test_packed_bytes_are_what_the_manifest_promises(published):
    data, registry, arts = published
    assert _pack(registry, data, "--all") == 0

    for art in arts.values():
        out = data / ".pack" / art.transfer_name
        assert out.exists(), f"{art.transfer_name} was not written"
        digest, size = mf.sha256_file(out)
        assert digest == art.sha256
        assert size == art.size


def test_the_archive_is_named_what_fetch_will_request(published):
    data, registry, arts = published
    _pack(registry, data, "--all")
    # fetch builds f"{base}/{art.transfer_name}"; the store becomes a zip,
    # the plain file keeps its own name.
    assert (data / ".pack" / "thing.zarr.zip").exists()
    assert (data / ".pack" / "small.npz").exists()


def test_the_archive_unpacks_back_to_the_store(published):
    data, registry, _ = published
    _pack(registry, data, "thing")
    with zipfile.ZipFile(data / ".pack" / "thing.zarr.zip") as zf:
        assert set(zf.namelist()) == {"0/0.0", ".zattrs"}


def test_a_stale_manifest_is_caught_before_upload(published):
    """Publishing against a manifest that no longer matches would give
    every downloader a checksum failure on data that is fine."""
    data, registry, _ = published
    (data / "small.npz").write_bytes(b"different-bytes-entirely")
    assert _pack(registry, data, "small") == 1
    # ...and the mismatch is not silently corrected in the output.
    digest, _ = mf.sha256_file(data / ".pack" / "small.npz")
    arts, _ = mf.load(registry / "manifest.toml")
    assert digest != {a.asset: a for a in arts}["small"].sha256


def test_an_absent_artifact_fails_rather_than_packing_nothing(published):
    data, registry, _ = published
    (data / "small.npz").unlink()
    assert _pack(registry, data, "small") == 1
    assert not (data / ".pack" / "small.npz").exists()


def test_rerunning_keeps_the_existing_file(published):
    """Re-zipping 2.4 GB to learn it had not changed would be the whole
    cost of the command for no result."""
    data, registry, _ = published
    _pack(registry, data, "thing")
    out = data / ".pack" / "thing.zarr.zip"
    stamp = out.stat().st_mtime_ns
    assert _pack(registry, data, "thing") == 0
    assert out.stat().st_mtime_ns == stamp

    assert _pack(registry, data, "thing", "--overwrite") == 0
    assert mf.sha256_file(out)[0] == mf.load(registry / "manifest.toml")[0][1].sha256


def test_naming_nothing_lists_instead_of_packing(published, capsys):
    data, registry, _ = published
    assert _pack(registry, data) == 0
    out = capsys.readouterr().out
    assert "thing.zarr.zip" in out and "small.npz" in out
    assert not (data / ".pack").exists()


def test_an_unknown_asset_is_refused(published):
    data, registry, _ = published
    assert _pack(registry, data, "nope") == 2


def test_the_real_command_reports_the_shipped_artifacts(tmp_path):
    """Against the actual registry: listing must not need the stains.

    `--output` points somewhere that does not exist, so its absence
    afterwards says listing wrote nothing -- checking the default location
    could not distinguish that from a directory an earlier run left behind.
    """
    out = tmp_path / "nowhere"
    result = subprocess.run(
        [sys.executable, "-m", "lobemap.cli", "pack", "--output", str(out)],
        capture_output=True, text=True, check=False,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    for name in ("fafb_stain.zarr.zip", "hemibrain_stain.zarr.zip",
                 "malecns_stain.zarr.zip"):
        assert name in result.stdout
    assert not out.exists()
