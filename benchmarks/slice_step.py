"""Time 2D slice steps, row toggles, scene loads and mode switches.

Everything is measured in a hidden napari viewer on the path `lobemap view`
takes: `Registry.load`, then `viewer.app.load_space` into a viewer created the
way `viewer.app.run` creates it, except with `show=False`. One slice step is
one synchronous `viewer.dims.set_current_step(axis, k)` call; Qt events are
processed between calls and not timed.

Run it with:

    uv run python benchmarks/slice_step.py

Each space and mode runs in a fresh subprocess, so every load is cold and no
cache carries over from one mode to the next. Modes:

- `primary`: the scene as it opens -- the space's primary atlas and its
  images. Also times row toggles in the compartment table.
- `labelfill`: the same, with every shown compartment labeled and filled.
- `switch`: opens in 3D, times the load, then counts contour rebuilds on
  each 2D/3D switch. A rebuild is one call to `ContourOverlay.contours_at`,
  which every redraw of a visible contour layer makes.
- `benton`: the old Benton 2025 viewer from `main`, for comparison. Needs
  `--benton-root`, a directory holding an export of `main` (for example
  `git archive effde7e | tar -x -C <dir>`).

Planes are `--planes` evenly spaced positions strictly inside the primary
atlas's extent along the slider axis, snapped to slider steps. Each worker
sweeps them twice: the first sweep visits each plane for the first time, the
second repeats the same planes in the same order.

Parts of a step:

- `--hide contours`, `--hide image` or both hides every contour layer, the
  reference images, or both, before the sweeps, which isolates the other
  part (both hidden is napari's own floor for a step). Hiding
  a layer makes napari re-pick each image's pyramid level for the canvas, so
  the level the full scene had is put back afterwards: both runs slice the
  same level.
- Every step also records `loaded`: the time from the call until every
  visible layer reports its new slice loaded, processing Qt events meanwhile.
  With synchronous slicing, which is what the viewer does, that is the call
  itself. `--async` switches on napari's asynchronous slicing for the
  benchmark's viewer (the viewer itself does not), for measuring a route
  that moves slicing off the main thread: `loaded` is then when the new
  plane is actually in the layer, and `ui` adds the main-thread time napari
  spends applying the result, which the call does not include.
- Each worker reports the pyramid levels its images were sliced at, and its
  resident memory at the end. A hidden canvas never draws, and drawing is
  when napari picks a multiscale image's level for the canvas, so the level
  is whatever the last draw before the sweeps picked -- in JRCFIB2018F one
  from before the camera's last fit. `--draw` runs napari's draw hook once
  the scene is open, as a shown window does on its next frame, so each level
  follows napari's rule for the benchmark's canvas.

The viewer cuts every slider plane of a shown atlas ahead of time, in a
worker thread (`viewer.prefetch`), from the moment a space opens in 2D. By
default the first sweep starts right after the load, while that runs, and
each result says whether it still was; `--wait-prefetch` starts the sweeps
once it has finished and reports how long it took.

The machine is rarely quiet, so use `--repeat` and read the spread, not one
number. `--no-bermuda` hides napari's compiled triangulation backend, which
reproduces an environment without it.
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
SPACES = ("FAFB14", "JRCFIB2018F", "JRCFIB2022M", "GRABE")
MODES = ("primary", "labelfill", "switch")


# -- measurement helpers -------------------------------------------------


def _stats(values_ms) -> dict:
    import numpy as np

    arr = np.asarray(values_ms, dtype=float)
    if not len(arr):
        return {"n": 0}
    return {
        "n": len(arr),
        "median": float(np.median(arr)),
        "p95": float(np.percentile(arr, 95)),
        "max": float(arr.max()),
    }


def _app():
    from qtpy.QtWidgets import QApplication

    return QApplication.instance()


def _settle(app, rounds: int = 3) -> None:
    for _ in range(rounds):
        app.processEvents()


def _step_indices(viewer, axis: int, lo: float, hi: float, n: int) -> list[int]:
    """`n` slider steps strictly inside [lo, hi] (world units)."""
    import numpy as np

    start, _stop, step = viewer.dims.range[axis]
    inside = np.linspace(lo, hi, n + 2)[1:-1]
    ks = sorted({round((x - start) / step) for x in inside})
    nsteps = int(viewer.dims.nsteps[axis])
    return [k for k in ks if 0 <= k < nsteps]


#: Main-thread milliseconds napari has spent applying asynchronous slice
#: results; see `_count_ready`.
_READY_MS = [0.0]


def _count_ready() -> None:
    """Time `QtViewer._on_slice_ready` on the main thread, where it runs.

    It is wrapped to hop to the main thread, so the timer goes inside that
    wrapper. Must run before the viewer exists: the viewer connects the
    wrapped method when it is built.
    """
    from napari._qt.qt_viewer import QtViewer
    from superqt.utils import ensure_main_thread

    inner = QtViewer._on_slice_ready.__wrapped__

    def timed(self, event):
        t0 = time.perf_counter()
        try:
            return inner(self, event)
        finally:
            _READY_MS[0] += (time.perf_counter() - t0) * 1e3

    QtViewer._on_slice_ready = ensure_main_thread(timed)


def _images(viewer) -> list:
    return [layer for layer in viewer.layers
            if layer.metadata.get("lobemap", {}).get("kind") == "image"]


def _wait_loaded(viewer, app, timeout_s: float = 10.0) -> None:
    deadline = time.perf_counter() + timeout_s
    while not all(layer.loaded for layer in viewer.layers if layer.visible):
        if time.perf_counter() > deadline:
            raise TimeoutError("a layer never finished slicing")
        app.processEvents()


def _sweeps(viewer, axis, ks, app, shapes_of=None) -> dict:
    """Two timed passes over the same planes."""
    out = {}
    images = _images(viewer)
    for name in ("first", "repeat"):
        times, loaded, ui, shapes, levels = [], [], [], [], set()
        for k in ks:
            ready0 = _READY_MS[0]
            t0 = time.perf_counter()
            viewer.dims.set_current_step(axis, k)
            t1 = time.perf_counter()
            _wait_loaded(viewer, app)
            t2 = time.perf_counter()
            times.append((t1 - t0) * 1e3)
            loaded.append((t2 - t0) * 1e3)
            _settle(app, 1)
            ui.append(times[-1] + _READY_MS[0] - ready0)
            levels.update((layer.name, int(layer.data_level)) for layer in images
                          if layer.visible)
            if shapes_of is not None:
                shapes.append(shapes_of())
        out[name] = _stats(times)
        out[name]["raw"] = times
        out[name]["loaded"] = {**_stats(loaded), "raw": loaded}
        out[name]["ui"] = {**_stats(ui), "raw": ui}
        out[name]["levels"] = sorted(levels)
        if shapes:
            out[name]["shapes"] = shapes
    return out


def _hide(viewer, session, parts, app) -> None:
    """Hide the contours and/or the images, keeping each image's level."""
    if not parts:
        return
    images = _images(viewer)
    kept = [(layer, layer._data_level, layer.corner_pixels.copy()) for layer in images
            if layer.multiscale]
    if "contours" in parts:
        for overlay in session.contours.values():
            overlay.layer.visible = False
    if "image" in parts:
        for layer in images:
            layer.visible = False
    for layer, level, corners in kept:
        if layer.visible and layer._data_level != level:
            layer._data_level = level
            layer.corner_pixels = corners
            layer.refresh(extent=False, thumbnail=False)
    _settle(app)


def _rss_mb() -> float:
    import psutil

    return psutil.Process().memory_info().rss / 2**20


def _backend() -> dict:
    info = {"bermuda": "bermuda" in sys.modules and sys.modules["bermuda"] is not None}
    try:
        from napari.utils.triangulation_backend import get_backend

        info["triangulation"] = str(get_backend())
    except Exception:  # noqa: BLE001 - older napari
        info["triangulation"] = "unknown"
    return info


# -- workers -------------------------------------------------------------


def _open(space: str, ndisplay: int, registry_root, data_root, asynchronous=False):
    import napari

    from lobemap.core.registry import Registry
    from lobemap.viewer.app import load_space

    t0 = time.perf_counter()
    registry = Registry.load(registry_root, data_root=data_root)
    registry_s = time.perf_counter() - t0
    _count_ready()
    viewer = napari.Viewer(show=False, ndisplay=ndisplay)
    if asynchronous:
        # napari's own switch, `settings.experimental.async_`, is saved to
        # the user's settings; this is the same switch on one viewer.
        viewer._layer_slicer._force_sync = False
    app = _app()
    _settle(app)
    t0 = time.perf_counter()
    session = load_space(viewer, registry, space)
    load_s = time.perf_counter() - t0
    _settle(app)
    return viewer, registry, session, app, {"registry_s": registry_s, "load_s": load_s}


def _primary_planes(viewer, registry, session, space, n):
    primary = registry.primary_atlas(space).id
    surface = session.surfaces[primary]
    axis = int(viewer.dims.order[0])
    extent = surface.layer.extent.world
    lo, hi = float(extent[0][axis]), float(extent[1][axis])
    return primary, axis, _step_indices(viewer, axis, lo, hi, n)


def _row_toggles(session, primary, app, count: int = 10) -> dict:
    """Uncheck, then recheck, `count` rows through the table's own items."""
    from qtpy.QtCore import Qt

    tab = session.panel.tabs[primary]
    rows = tab.table.rowCount()
    picks = sorted({int(i * (rows - 1) / max(count - 1, 1)) for i in range(count)})
    times = []
    for row in picks:
        item = tab.table.item(row, 0)
        for state in (Qt.Unchecked, Qt.Checked):
            t0 = time.perf_counter()
            item.setCheckState(state)
            times.append((time.perf_counter() - t0) * 1e3)
            _settle(app)
    out = _stats(times)
    out["raw"] = times
    return out


def _prefetch_state(overlay, wait: bool) -> dict:
    """Whether the contour prefetch is still running as the sweeps start.

    With `wait`, the sweeps start once it has finished, and its time is
    reported: the worker's own, from its start to its end.
    """
    try:
        from lobemap.viewer import prefetch
    except ImportError:              # a viewer from before the prefetch
        return {"prefetch": None}
    waited = prefetch.settle(120) if wait else None
    plan = getattr(overlay, "_plan", None)
    done = plan is not None and plan.finished is not None
    return {"prefetch": {
        "waited": waited, "running_at_start": prefetch.busy(),
        "s": (plan.finished - plan.started) if done else None,
        "planes": getattr(plan, "planes", None), "full": getattr(plan, "full", None),
    }}


def work_steps(space, mode, planes, registry_root, data_root, hide=None,
               asynchronous=False, draw=False, wait_prefetch=False) -> dict:
    viewer, registry, session, app, load = _open(space, 2, registry_root, data_root,
                                                 asynchronous)
    try:
        primary, axis, ks = _primary_planes(viewer, registry, session, space, planes)
        overlay = session.contours[primary]
        if mode == "labelfill":
            overlay.set_labels(set(overlay.selection))
            overlay.set_fills(set(overlay.selection))
            _settle(app)
        if draw:
            viewer.window._qt_viewer.canvas.on_draw()
            _settle(app)
        _hide(viewer, session, hide, app)
        state = _prefetch_state(overlay, wait_prefetch)
        result = {
            "space": space, "mode": mode, "axis": axis, "planes": len(ks),
            "hide": hide, "async": asynchronous, "draw": draw,
            **load, **_backend(), **state,
            "sweeps": _sweeps(viewer, axis, ks, app,
                              shapes_of=lambda: len(overlay.paths)),
        }
        if mode == "primary" and not hide:
            result["toggle"] = _row_toggles(session, primary, app)
        result["rss_mb"] = _rss_mb()
        return result
    finally:
        viewer.close()


def work_switch(space, cycles, registry_root, data_root) -> dict:
    from lobemap.viewer import contours as contours_module

    counts = {"rebuild": 0, "refresh": 0}
    cls = contours_module.ContourOverlay
    original_at, original_refresh = cls.contours_at, cls.refresh

    def counted_at(self, position):
        counts["rebuild"] += 1
        return original_at(self, position)

    def counted_refresh(self):
        counts["refresh"] += 1
        return original_refresh(self)

    cls.contours_at, cls.refresh = counted_at, counted_refresh
    try:
        viewer, _registry, _session, app, load = _open(
            space, 3, registry_root, data_root)
        try:
            switches = []
            for _ in range(cycles):
                for target in (2, 3):
                    counts["rebuild"] = counts["refresh"] = 0
                    t0 = time.perf_counter()
                    viewer.dims.ndisplay = target
                    dt = (time.perf_counter() - t0) * 1e3
                    _settle(app)
                    switches.append({"to": target, "ms": dt, **counts})
            return {"space": space, "mode": "switch", **load, **_backend(),
                    "switches": switches, "rss_mb": _rss_mb()}
        finally:
            viewer.close()
    finally:
        cls.contours_at, cls.refresh = original_at, original_refresh


def work_benton(root: Path, planes: int) -> dict:
    import napari
    import numpy as np

    work_dir = root / "datasets" / "benton-2025"
    sys.path[:0] = [str(work_dir), str(root / "scripts")]
    import benton_2025_napari

    viewer = napari.Viewer(show=False)
    app = _app()
    _settle(app)
    try:
        t0 = time.perf_counter()
        benton_2025_napari.load_atlas(viewer)
        load_s = time.perf_counter() - t0
        _settle(app)
        labels = next(layer for layer in viewer.layers
                      if layer.name == "glomerulus labels")
        axis = int(viewer.dims.order[0])
        occupied = np.flatnonzero(
            np.any(np.asarray(labels.data) != 0,
                   axis=tuple(i for i in range(labels.ndim) if i != axis)))
        lo = float(labels.data_to_world(_at(labels.ndim, axis, occupied.min()))[axis])
        hi = float(labels.data_to_world(_at(labels.ndim, axis, occupied.max()))[axis])
        ks = _step_indices(viewer, axis, lo, hi, planes)
        return {"space": "benton-main", "mode": "labels", "axis": axis,
                "planes": len(ks), "load_s": load_s, **_backend(),
                "sweeps": _sweeps(viewer, axis, ks, app)}
    finally:
        viewer.close()


def _at(ndim, axis, value):
    point = [0.0] * ndim
    point[axis] = float(value)
    return point


# -- driver --------------------------------------------------------------


def _worker_main(args) -> int:
    if args.no_bermuda:
        # An import that fails, exactly as when the package is absent.
        sys.modules["bermuda"] = None
    registry_root = Path(args.registry)
    if args.mode == "benton":
        result = work_benton(Path(args.benton_root), args.planes)
    elif args.mode == "switch":
        result = work_switch(args.space, args.cycles, registry_root, args.data_root)
    else:
        result = work_steps(args.space, args.mode, args.planes,
                            registry_root, args.data_root, args.hide, args.asynchronous,
                            args.draw, args.wait_prefetch)
    print("RESULT " + json.dumps(result), flush=True)
    return 0


def _run_worker(argv: list[str]) -> dict:
    cmd = [sys.executable, str(Path(__file__).resolve()), "--worker", *argv]
    proc = subprocess.run(cmd, capture_output=True, text=True, env=os.environ.copy(),
                          check=False)
    for line in proc.stdout.splitlines():
        if line.startswith("RESULT "):
            return json.loads(line[len("RESULT "):])
    sys.stderr.write(proc.stdout[-4000:] + proc.stderr[-4000:])
    raise RuntimeError(f"worker failed ({proc.returncode}): {' '.join(argv)}")


def _fmt(s: dict) -> str:
    if not s or not s.get("n"):
        return "-"
    return f"{s['median']:.1f} / {s['p95']:.1f}"


def _summary(results: list[dict]) -> str:
    lines = [
        ("| space | mode | planes | first sweep ms (median / p95) | repeat sweep ms "
         "(median / p95) | shapes/plane | cold load s | row toggle ms (median / p95) "
         "| first ui / loaded ms | repeat ui / loaded ms | levels | RSS MB |"),
        "|---|---|---|---|---|---|---|---|---|---|---|---|",
    ]
    for r in results:
        if r["mode"] == "switch":
            continue
        sweeps = r["sweeps"]
        shapes = sweeps["first"].get("shapes")
        shape_txt = f"{sorted(shapes)[len(shapes) // 2]}" if shapes else "-"
        mode = r["mode"] + "".join(f" -{part}" for part in r.get("hide") or ()) + (
            " async" if r.get("async") else "") + (" draw" if r.get("draw") else "")
        levels = ",".join(f"{lvl}" for _, lvl in sweeps["first"].get("levels", []))
        lines.append(
            f"| {r['space']} | {mode} | {r['planes']} | {_fmt(sweeps['first'])} | "
            f"{_fmt(sweeps['repeat'])} | {shape_txt} | {r['load_s']:.2f} | "
            f"{_fmt(r.get('toggle', {}))} | "
            f"{_fmt(sweeps['first'].get('ui', {}))} ; {_fmt(sweeps['first'].get('loaded', {}))} | "
            f"{_fmt(sweeps['repeat'].get('ui', {}))} ; {_fmt(sweeps['repeat'].get('loaded', {}))} | "
            f"{levels or '-'} | {r.get('rss_mb', 0):.0f} |"
        )
    switch = [r for r in results if r["mode"] == "switch"]
    if switch:
        lines += ["", "| space | 3D load s | per switch: to, ms, rebuilds, refresh calls |",
                  "|---|---|---|"]
        for r in switch:
            steps = "; ".join(
                f"{s['to']}D {s['ms']:.0f} ms {s['rebuild']}/{s['refresh']}"
                for s in r["switches"])
            lines.append(f"| {r['space']} | {r['load_s']:.2f} | {steps} |")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    p.add_argument("--spaces", nargs="+", default=list(SPACES))
    p.add_argument("--modes", nargs="+", default=list(MODES),
                   choices=(*MODES, "benton"))
    p.add_argument("--planes", type=int, default=24,
                   help="planes per sweep (default 24)")
    p.add_argument("--cycles", type=int, default=3,
                   help="2D/3D round trips in the switch mode (default 3)")
    p.add_argument("--repeat", type=int, default=1,
                   help="fresh processes per space and mode (default 1)")
    p.add_argument("--registry", default=str(REPO / "registry"))
    p.add_argument("--data-root", default=None)
    p.add_argument("--benton-root", default=None,
                   help="an export of main, for the benton mode")
    p.add_argument("--no-bermuda", action="store_true",
                   help="hide napari's compiled triangulation backend")
    p.add_argument("--hide", nargs="+", choices=("contours", "image"), default=None,
                   help="hide the contours and/or the reference images before the sweeps")
    p.add_argument("--async", dest="asynchronous", action="store_true",
                   help="slice with napari's asynchronous slicing (the viewer does not)")
    p.add_argument("--draw", action="store_true",
                   help="let napari pick image levels for the canvas before the sweeps")
    p.add_argument("--wait-prefetch", action="store_true",
                   help="start the sweeps once the contour prefetch has finished")
    p.add_argument("--json", default=None, help="write every result here")
    p.add_argument("--worker", action="store_true", help=argparse.SUPPRESS)
    p.add_argument("--mode", default=None, help=argparse.SUPPRESS)
    p.add_argument("--space", default=None, help=argparse.SUPPRESS)
    args = p.parse_args(argv)

    if args.worker:
        return _worker_main(args)

    common = ["--planes", str(args.planes), "--cycles", str(args.cycles),
              "--registry", args.registry]
    if args.data_root:
        common += ["--data-root", args.data_root]
    if args.no_bermuda:
        common.append("--no-bermuda")
    if args.hide:
        common += ["--hide", *args.hide]
    if args.asynchronous:
        common.append("--async")
    if args.draw:
        common.append("--draw")
    if args.wait_prefetch:
        common.append("--wait-prefetch")
    jobs = []
    for mode in args.modes:
        if mode == "benton":
            if not args.benton_root:
                p.error("--modes benton needs --benton-root")
            jobs.append(["--mode", "benton", "--benton-root", args.benton_root])
            continue
        jobs += [["--mode", mode, "--space", space] for space in args.spaces]
    results = []
    for _ in range(args.repeat):
        for job in jobs:
            result = _run_worker(job + common)
            results.append(result)
            print(_summary([result]).splitlines()[-1], flush=True)
    print()
    print(_summary(results))
    if args.json:
        Path(args.json).write_text(json.dumps(results, indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
