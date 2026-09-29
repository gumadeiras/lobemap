"""The command line: how it starts, and how it answers wrong input."""

from __future__ import annotations

import subprocess
import sys
import tomllib
from pathlib import Path

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
