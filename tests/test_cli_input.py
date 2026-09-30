"""The command line: how it starts, and how it answers wrong input."""

from __future__ import annotations

import subprocess
import sys
import tomllib
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]


def _lobemap(*args, cwd=None, env=None):
    return subprocess.run([sys.executable, "-m", "lobemap", *args], cwd=cwd,
                          env=env, capture_output=True, text=True, check=False,
                          timeout=300)


def test_python_m_lobemap_is_the_lobemap_command(tmp_path):
    version = tomllib.loads((ROOT / "pyproject.toml").read_text())["project"]["version"]
    r = _lobemap("--version", cwd=tmp_path)
    assert r.returncode == 0, r.stderr
    assert r.stdout.strip() == f"lobemap {version}"


# -- wrong input: one line on stderr, exit 2, no traceback -----------------

REGISTRY = ROOT / "registry"


def _refused(capsys, argv, expect: str, code: int = 2) -> None:
    from lobemap.cli import main

    assert main(argv) == code
    out, err = capsys.readouterr()
    assert expect in err
    assert len(err.strip().splitlines()) == 1, err
    assert "Traceback" not in err


@pytest.mark.parametrize("command", [
    ["spaces"], ["nomenclature"], ["build", "--all"], ["repair", "--dry-run"],
    ["manifest"], ["bridge", "benton2025_glomeruli", "--to", "JRCFIB2018F"],
    ["fetch"], ["fetch", "--check"], ["pack", "--all"],
    ["ingest", "neuprint", "--asset-id", "x", "--token", "t"],
])
def test_a_missing_registry_is_refused(capsys, tmp_path, monkeypatch, command):
    """It used to load as an empty registry, and each of these exited 0.

    `fetch` and `pack` said to run `manifest`, which refuses the same
    registry; `ingest neuprint` did its neuPrint work first and then wrote
    into a registry directory it created.
    """
    from lobemap.ingest import neuprint_rois

    def not_reached(**_):
        raise AssertionError("neuPrint was queried for a missing registry")

    monkeypatch.setattr(neuprint_rois, "ingest", not_reached)
    missing = tmp_path / "no-registry"
    _refused(capsys, ["--registry", str(missing), *command],
             f"no registry at {missing}")
    assert not missing.exists()


def test_validate_reports_a_missing_registry(capsys, tmp_path):
    """`validate` has its own exit code for a bad registry, and keeps it."""
    missing = tmp_path / "no-registry"
    _refused(capsys, ["--registry", str(missing), "validate"],
             f"no registry at {missing}", code=1)


def test_the_installed_command_prints_one_line(tmp_path):
    r = _lobemap("--registry", str(tmp_path / "nope"), "spaces", cwd=tmp_path)
    assert r.returncode == 2
    assert r.stderr.strip() == (f"lobemap: no registry at {tmp_path / 'nope'}: "
                                f"it has no spaces.toml")


@pytest.mark.parametrize("command, expect", [
    (["fetch", "--asset", "benton2025_glomeruIi"], "unknown asset benton2025_glomeruIi"),
    (["fetch", "--check", "--asset", "nope"], "unknown asset nope"),
    (["pack", "nope"], "unknown asset nope"),
    (["build", "nope"], "unknown asset nope"),
    (["repair", "--dry-run", "nope"], "unknown asset nope"),
    (["bridge", "nope", "--to", "FAFB14"], "unknown asset nope"),
    (["bridge", "benton2025_glomeruli", "--to", "NOPE"], "unknown space NOPE"),
    (["stain", "--space", "NOPE", "--asset-id", "x", "--token", "t"],
     "unknown space NOPE"),
    (["stain", "--space", "FAFB14", "--asset-id", "x", "--token", "t",
      "--bounds-from", "nope"], "unknown asset nope"),
    (["check", "--compare", "neuprint_hemibrain", "schlegel2021_s12", "NOPE"],
     "unknown space NOPE"),
    (["check", "--compare", "nope", "schlegel2021_s12", "JRCFIB2018F"],
     "unknown atlas nope"),
    (["reconcile", "nope", "neuprint_cns"], "unknown atlas nope"),
    (["reconcile", "grabe2015", "benton2025", "--space", "NOPE"], "unknown space NOPE"),
])
def test_an_unknown_name_is_refused_before_any_work(capsys, tmp_path, monkeypatch,
                                                    command, expect):
    """No data is needed: every name is checked before anything is read."""
    from lobemap.validate import harness

    def not_reached(*_, **__):
        raise AssertionError("the checks ran before the names were checked")

    monkeypatch.setattr(harness, "run_checks", not_reached)
    empty = tmp_path / "data"
    empty.mkdir()
    _refused(capsys, ["--registry", str(REGISTRY), "--data-root", str(empty),
                      *command], expect)
    assert not any(empty.iterdir()), "wrote into the data root"


def test_the_old_atlas_flag_says_what_replaced_it(capsys):
    """0.1.x took `--atlas`; argparse alone answered "invalid choice"."""
    _refused(capsys, ["--atlas", "grabe-2015"], "--atlas was removed in 0.2.0")
    _refused(capsys, ["--atlas=hemibrain"], "`lobemap spaces` lists them")


def test_spaces_points_at_fetch_for_what_is_missing(capsys, tmp_path):
    from lobemap.cli import main

    assert main(["--registry", str(REGISTRY), "--data-root", str(tmp_path),
                 "spaces"]) == 0
    assert "`lobemap fetch` downloads them" in capsys.readouterr().out


def test_an_empty_audit_is_not_a_match(capsys, tmp_path):
    """`nomenclature` over no data said "the table matches" and exited 0."""
    _refused(capsys, ["--registry", str(REGISTRY), "--data-root", str(tmp_path),
                      "nomenclature"], "NOTHING WAS AUDITED", code=1)


@pytest.mark.parametrize("error, expect", [
    ("legacy", "pickle"),
    ("bridge", "cannot bridge GRABE -> FAFB14"),
    ("ingest", "pip install 'lobemap[ingest]'"),
])
def test_known_refusals_print_one_line(capsys, monkeypatch, error, expect):
    """A legacy mesh file, a refused bridge and a missing ingest dependency
    each ended in a traceback."""
    from lobemap import cli
    from lobemap.core.meshfmt import LegacyContainerError
    from lobemap.core.resolve import CannotBridge

    def fail(args):
        if error == "legacy":
            raise LegacyContainerError("m.npz: names only as pickle; reading them would run pickle")
        if error == "bridge":
            raise CannotBridge("cannot bridge GRABE -> FAFB14: source is an island")
        raise ModuleNotFoundError("No module named 'navis'", name="navis")

    monkeypatch.setattr(cli, "cmd_spaces", fail)
    _refused(capsys, ["spaces"], expect)


def test_an_unrelated_missing_module_is_not_hidden(monkeypatch):
    from lobemap import cli

    def fail(args):
        raise ModuleNotFoundError("No module named 'nosuchthing'", name="nosuchthing")

    monkeypatch.setattr(cli, "cmd_spaces", fail)
    with pytest.raises(ModuleNotFoundError):
        cli.main(["spaces"])
