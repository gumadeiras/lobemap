"""The wheel carries what an installed lobemap needs, and no data.

A source checkout hides missing package data: the registry sits beside the
code, so every command works there even when the wheel ships none of it.
The first 0.2.0 build did exactly that, and an installed `lobemap validate`
reported `ok: 0 spaces`. So this builds the wheel from this tree, unpacks
it, and runs it from a directory outside the checkout.

The build runs setuptools in-process from the project environment rather
than through an isolated frontend, so it needs no network.
"""

from __future__ import annotations

import email
import os
import re
import shutil
import subprocess
import sys
import tomllib
import zipfile
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
REGISTRY = ROOT / "registry"
#: Everything under these is data, gigabytes of it, fetched rather than shipped.
DATA_DIRS = ("data", "sources")


def _metadata_files() -> set[str]:
    """The registry files the code reads, relative to the registry root."""
    return {
        p.relative_to(REGISTRY).as_posix()
        for p in REGISTRY.rglob("*")
        if p.is_file() and p.suffix in (".toml", ".csv")
        and p.relative_to(REGISTRY).parts[0] not in DATA_DIRS
    }


@pytest.fixture(scope="module")
def wheel(tmp_path_factory) -> Path:
    setuptools = pytest.importorskip("setuptools")
    if int(setuptools.__version__.split(".")[0]) < 77:
        pytest.skip("pyproject.toml needs setuptools>=77")

    tree = tmp_path_factory.mktemp("tree")
    for name in ("pyproject.toml", "README.md", "LICENSE"):
        shutil.copy2(ROOT / name, tree / name)
    junk = shutil.ignore_patterns("__pycache__", "*.egg-info")
    shutil.copytree(ROOT / "src", tree / "src", ignore=junk)
    shutil.copytree(REGISTRY, tree / "registry",
                    ignore=shutil.ignore_patterns(*DATA_DIRS))
    # Stand-ins for the data, with the same suffixes as the metadata, so a
    # glob that reached into either directory would pick them up.
    for rel in ("data/README.md", "data/stub.npz", "data/stub.toml",
                "sources/README.md", "sources/set/stub.csv"):
        path = tree / "registry" / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("stub\n", encoding="utf-8")

    out = tmp_path_factory.mktemp("dist")
    build = "import sys; from setuptools import build_meta as b; b.build_wheel(sys.argv[1])"
    subprocess.run([sys.executable, "-c", build, str(out)],
                   cwd=tree, check=True, capture_output=True, text=True)
    (whl,) = out.glob("lobemap-*.whl")
    return whl


def test_wheel_ships_every_subpackage(wheel):
    names = set(zipfile.ZipFile(wheel).namelist())
    packages = {
        p.parent.relative_to(ROOT / "src").as_posix()
        for p in (ROOT / "src").rglob("__init__.py")
    }
    missing = {p for p in packages if f"{p}/__init__.py" not in names}
    assert not missing, f"not in the wheel: {sorted(missing)}"


def test_wheel_ships_the_registry_metadata_and_no_data(wheel):
    names = set(zipfile.ZipFile(wheel).namelist())
    shipped = {n.removeprefix("lobemap/registry/") for n in names
               if n.startswith("lobemap/registry/")}
    expected = _metadata_files()
    assert {"spaces.toml", "assets.toml", "manifest.toml", "recipes.toml",
            "nomenclature.csv"} <= expected
    assert shipped == expected
    assert not [n for n in names if n.split("/")[:3] in (
        ["lobemap", "registry", "data"], ["lobemap", "registry", "sources"])]


def _requirement_names(requires) -> set[str]:
    return {re.split(r"[\s<>=!~;\[]", r, maxsplit=1)[0].lower() for r in requires}


def test_wheel_keeps_the_ingest_stack_an_extra(wheel):
    """`pip install lobemap` is the viewer; `lobemap[ingest]` adds the rest.

    The ingest stack used to be a uv dependency group, which is never
    published, so a pip user had no way to ask for it at all.
    """
    whl = zipfile.ZipFile(wheel)
    (path,) = [n for n in whl.namelist() if n.endswith(".dist-info/METADATA")]
    meta = email.message_from_bytes(whl.read(path))
    requires = meta.get_all("Requires-Dist")
    base = _requirement_names(r for r in requires if "extra ==" not in r)
    ingest = _requirement_names(r for r in requires if 'extra == "ingest"' in r)
    assert "ingest" in meta.get_all("Provides-Extra")
    assert {"navis", "flybrains", "fafbseg", "neuprint-python", "pyvista",
            "scikit-image", "pyarrow", "cloud-volume"} <= ingest
    assert not base & ingest
    assert "fromweb1@gumadeiras.com" in meta["Author-email"]


def _run_installed(wheel, tmp_path, *args):
    """Run lobemap from the unpacked wheel, from outside the checkout.

    The unpacked wheel goes first on PYTHONPATH, ahead of the editable
    install, so this is the code and metadata a pip user gets. No data:
    LOBEMAP_DATA is an empty directory.
    """
    site = tmp_path / "site"
    if not site.exists():
        zipfile.ZipFile(wheel).extractall(site)
    data = tmp_path / "data"
    data.mkdir(exist_ok=True)
    env = dict(os.environ, PYTHONPATH=str(site), LOBEMAP_DATA=str(data))
    env.pop("LOBEMAP_REGISTRY", None)
    work = tmp_path / "elsewhere"
    work.mkdir(exist_ok=True)
    return subprocess.run([sys.executable, "-m", "lobemap", *args], cwd=work,
                          env=env, capture_output=True, text=True, check=False,
                          timeout=300)


def _toml(rel: str) -> dict:
    return tomllib.loads((REGISTRY / rel).read_text(encoding="utf-8"))


def test_installed_wheel_finds_its_registry(wheel, tmp_path):
    spaces = _toml("spaces.toml")
    n_assets = len(_toml("assets.toml"))
    n_atlases = len(list((REGISTRY / "atlases").glob("*.toml")))
    n_artifacts = len(_toml("manifest.toml")["artifacts"])

    r = _run_installed(wheel, tmp_path, "--version")
    assert r.returncode == 0, r.stderr
    assert r.stdout.strip() == f"lobemap {_version()}"

    r = _run_installed(wheel, tmp_path, "validate")
    assert r.returncode == 0, r.stderr
    assert r.stdout.startswith(
        f"ok: {len(spaces)} spaces, {n_assets} assets, {n_atlases} atlases"
    ), r.stdout

    r = _run_installed(wheel, tmp_path, "spaces")
    assert r.returncode == 0, r.stderr
    for space in spaces:
        assert f"  {space} " in r.stdout

    # The manifest ships too. With no data on disk every artifact is
    # missing, where before this was "no manifest" and exit 2.
    r = _run_installed(wheel, tmp_path, "fetch", "--check")
    assert r.returncode == 1, r.stderr
    assert f"0/{n_artifacts} verified" in r.stdout
    assert f"data root: {tmp_path / 'data'}" in r.stdout


def _version() -> str:
    return tomllib.loads((ROOT / "pyproject.toml").read_text())["project"]["version"]
