"""The crash handler should be silent until there is a crash.

`lobemap view` arms faulthandler so that a native vispy/Qt/driver fault
leaves a stack trace instead of killing python with an empty log. It used
to announce the path on every launch and leave the file behind, so an
ordinary run printed a line about a crash that had not happened and
dropped an empty file in the temp directory. Measured on one machine: 54
empty files out of 55 launches, against a single real report.

Driven through subprocesses, because all of the behavior is at exit.
"""

from __future__ import annotations

import subprocess
import sys
import textwrap

PRELUDE = textwrap.dedent(
    """
    import sys, os
    sys.path.insert(0, r"{src}")
    from lobemap.cli import _install_crash_log
    _install_crash_log()
    """
)


def run_child(body: str, tmp_path, env_extra=None):
    import os
    from pathlib import Path

    src = str(Path(__file__).resolve().parents[1] / "src")
    script = tmp_path / "child.py"
    script.write_text(PRELUDE.format(src=src) + textwrap.dedent(body),
                      encoding="utf-8")
    env = dict(os.environ)
    env["TMPDIR"] = env["TEMP"] = env["TMP"] = str(tmp_path)
    env.pop("LOBEMAP_CRASH_LOG", None)
    env.update(env_extra or {})
    return subprocess.run([sys.executable, str(script)], capture_output=True,
                          text=True, env=env, check=False)


def logs_in(tmp_path):
    return sorted(p for p in tmp_path.glob("lobemap-crash-*.log"))


def test_a_clean_run_says_nothing_and_leaves_nothing(tmp_path):
    r = run_child("print('ran')", tmp_path)
    assert r.returncode == 0, r.stderr
    assert "crash log" not in r.stdout.lower()
    assert "crash" not in r.stderr.lower()
    assert logs_in(tmp_path) == [], "an empty crash log was left behind"


WRITE_BODY = chr(10).join([
    "import glob, os",
    "p = glob.glob(os.path.join(os.environ['TMP'], 'lobemap-crash-*.log'))[0]",
    "open(p, 'ab').write(b'pretend fault')",
])


def test_a_written_report_is_kept_and_announced(tmp_path):
    """If faulthandler actually wrote, the file must survive the exit."""
    r = run_child(WRITE_BODY, tmp_path)
    assert r.returncode == 0, r.stderr
    kept = logs_in(tmp_path)
    assert len(kept) == 1, kept
    assert kept[0].read_bytes(), "a non-empty report was deleted"
    assert "crash report was written" in r.stderr


def test_an_explicit_path_is_honoured_and_announced(tmp_path):
    target = tmp_path / "mine.log"
    r = run_child("print('ran')", tmp_path,
                  env_extra={"LOBEMAP_CRASH_LOG": str(target)})
    assert r.returncode == 0, r.stderr
    assert str(target) in r.stdout
    # Asked for by name, so it is kept even though nothing was written.
    assert target.exists()


def test_stale_empties_from_killed_runs_are_swept(tmp_path):
    """Force-quitting the window skips atexit, so empties accumulate."""
    stale = [tmp_path / f"lobemap-crash-{n}.log" for n in (111, 222)]
    for s in stale:
        s.write_bytes(b"")
    real = tmp_path / "lobemap-crash-333.log"
    real.write_bytes(b"Windows fatal exception: access violation\n")

    r = run_child("print('ran')", tmp_path)
    assert r.returncode == 0, r.stderr
    assert not any(s.exists() for s in stale), "empties were not swept"
    assert real.exists(), "a real report must never be swept"
