"""Time opening a space and switching to another, as the space menu does.

Each run is a fresh process: `Registry.load`, a hidden viewer made as
`viewer.app.run` makes it, `load_space` for the first space (`open`), the
`SpaceSwitcher` docked beside it, and then a switch to each next space by
picking it in the menu (`switch`): the new scene built beside the open one,
the open one torn down, the view settled. The switch is timed around the
menu's own handler, synchronously.

    uv run python benchmarks/space_switch.py [--path FAFB14 GRABE ...]
        [--ndisplay 2] [--rotate SPIN TILT TURN] [--repeat N] [--json out.json]

`--rotate` turns each scene by the angles once it is open, as the switcher
hands a new scene the angles of the one it replaces; the turn is timed
apart. The machine is rarely quiet: use `--repeat` and read the spread.
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
PATH = ("FAFB14", "JRCFIB2018F", "JRCFIB2022M", "GRABE", "FAFB14")


def _settle(app, rounds: int = 3) -> None:
    for _ in range(rounds):
        app.processEvents()


def worker(path, ndisplay: int, rotate) -> dict:
    import napari
    from qtpy.QtWidgets import QApplication

    from lobemap.core.registry import Registry
    from lobemap.viewer.app import load_space
    from lobemap.viewer.switcher import SpaceSwitcher

    registry = Registry.load(REPO / "registry")
    viewer = napari.Viewer(show=False, ndisplay=ndisplay)
    app = QApplication.instance()
    _settle(app)
    out = {"path": list(path), "ndisplay": ndisplay, "rotate": rotate, "switch_ms": [],
           "rotate_ms": []}
    try:
        def load(target, show=()):
            return load_space(viewer, registry, target, show=show, fit=False)

        t0 = time.perf_counter()
        session = load(path[0])
        out["open_ms"] = (time.perf_counter() - t0) * 1e3
        switcher = SpaceSwitcher(viewer, registry, session, load)
        switcher.dock = viewer.window.add_dock_widget(switcher, area="left", name="View",
                                                      tabify=False)
        _settle(app)

        def turn() -> None:
            if rotate is not None:
                t = time.perf_counter()
                switcher.session.set_rotation(*rotate)
                out["rotate_ms"].append((time.perf_counter() - t) * 1e3)
                _settle(app)

        turn()
        for target in path[1:]:
            t0 = time.perf_counter()
            switcher.combo.setCurrentIndex(switcher.combo.findData(target))
            out["switch_ms"].append((time.perf_counter() - t0) * 1e3)
            assert switcher.session.space == target, switcher.status.text()
            _settle(app)
            turn()
        return out
    finally:
        viewer.close()


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    p.add_argument("--path", nargs="+", default=list(PATH))
    p.add_argument("--ndisplay", type=int, default=2, choices=(2, 3))
    p.add_argument("--rotate", nargs=3, type=float, default=None)
    p.add_argument("--repeat", type=int, default=1)
    p.add_argument("--json", default=None)
    p.add_argument("--worker", action="store_true", help=argparse.SUPPRESS)
    args = p.parse_args(argv)
    if args.worker:
        result = worker(args.path, args.ndisplay, args.rotate)
        print("RESULT " + json.dumps(result), flush=True)
        return 0
    extra = ["--rotate", *map(str, args.rotate)] if args.rotate else []
    results = []
    for _ in range(args.repeat):
        cmd = [sys.executable, str(Path(__file__).resolve()), "--worker", "--path",
               *args.path, "--ndisplay", str(args.ndisplay), *extra]
        proc = subprocess.run(cmd, capture_output=True, text=True, env=os.environ.copy(),
                              check=False)
        line = next((ln for ln in proc.stdout.splitlines() if ln.startswith("RESULT ")), None)
        if line is None:
            sys.stderr.write(proc.stdout[-3000:] + proc.stderr[-3000:])
            raise RuntimeError("worker failed")
        result = json.loads(line[len("RESULT "):])
        results.append(result)
        print(f"open {result['open_ms']:.0f} ms | switches "
              + " ".join(f"{s:.0f}" for s in result["switch_ms"]) + " ms"
              + (" | rotate " + " ".join(f"{r:.0f}" for r in result["rotate_ms"]) + " ms"
                 if result["rotate_ms"] else ""), flush=True)
    if args.json:
        Path(args.json).write_text(json.dumps(results, indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
