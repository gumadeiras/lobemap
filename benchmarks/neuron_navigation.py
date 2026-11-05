"""Measure navigation with a real neuron, without network or conversion time.

Input is an NPZ with `points` (N, 3), in the chosen brain's micrometers,
and `parents` (N,), with -1 for roots. Normal display thinning is applied.

    uv run python benchmarks/neuron_navigation.py neuron.npz --space FAFB14

Run in a fresh process for each comparison. `--rotate`, `--aligned` and
`--mirror` exercise other slice planes. The hidden viewer uses the real
scene and contour paths. Frame times include OpenGL drawing and framebuffer
readback; they compare workloads, and are not interactive screen FPS.
"""

from __future__ import annotations

import argparse
import json
import os
import tempfile
import time
from pathlib import Path

import numpy as np
import slice_step as bench


def _draw(viewer, app) -> None:
    canvas = viewer.window._qt_viewer.canvas
    canvas.on_draw()
    canvas._scene_canvas.render()
    app.processEvents()


def _slices(viewer, points, app, overlay, steps) -> dict:
    axis = int(viewer.dims.order[0])
    q = points if overlay.frame is None else overlay.frame.apply(points)
    middle = overlay.layer.data_to_world(np.median(q, axis=0))[axis]
    start, _stop, step = viewer.dims.range[axis]
    center = round((middle - start) / step)
    indices = [k for k in range(center - steps // 2, center + steps // 2)
               if 0 <= k < int(viewer.dims.nsteps[axis])]
    assert len(indices) >= 2, "the neuron lies outside the brain's slider range"
    out = {}
    for case in ("fresh", "repeat"):
        ui, frames = [], []
        for k in indices:
            t = time.perf_counter()
            viewer.dims.set_current_step(axis, k)
            ui.append(1000 * (time.perf_counter() - t))
            _draw(viewer, app)
            frames.append(1000 * (time.perf_counter() - t))
        out[case] = {"step_ms": bench._stats(ui), "frame_ms": bench._stats(frames)}
    return out


def _hover(viewer, positions) -> dict:
    callback = next(f.lobemap_words for f in viewer.mouse_move_callbacks
                    if hasattr(f, "lobemap_words"))
    out = {}
    for vector in ((1., 0., 0.), (1., 1., 1.), (.3, .2, .93), (-.8, .6, .4)):
        direction = np.asarray(vector) / np.linalg.norm(vector)
        times = []
        for p in positions:
            t = time.perf_counter()
            callback(p, direction)
            times.append(1000 * (time.perf_counter() - t))
        out[str(vector)] = bench._stats(times)
    return out


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("skeleton", type=Path)
    parser.add_argument("--space", default="FAFB14", choices=bench.SPACES)
    parser.add_argument("--canvas", nargs=2, type=int, default=[1000, 700])
    parser.add_argument("--steps", type=int, default=16)
    parser.add_argument("--rotate", nargs=3, type=float)
    parser.add_argument("--aligned", action="store_true")
    parser.add_argument("--mirror", action="store_true")
    args = parser.parse_args()
    if args.steps < 2:
        parser.error("--steps must be at least 2")
    os.environ["NAPARI_CONFIG"] = str(Path(tempfile.mkdtemp(prefix="lobemap-bench-"))
                                     / "settings.yaml")

    from lobemap.core.neurons import thinned
    from lobemap.viewer import prefetch
    from lobemap.viewer.neurons import KEY, Neuron, build

    with np.load(args.skeleton, allow_pickle=False) as data:
        points, parents = thinned(data["points"], data["parents"])
    positions = points[np.random.default_rng(2).choice(len(points), min(len(points), 16),
                                                     replace=False)]
    bench._CANVAS[0] = args.canvas
    viewer, registry, session, app, _opening = bench._open(
        args.space, 3, bench.REPO / "registry", None)
    result = {"space": args.space, "nodes": len(points)}
    try:
        primary = registry.primary_atlas(args.space).id
        for present in (False, True):
            viewer.dims.ndisplay = 3
            session.set_mirror(False)
            session.set_aligned(False)
            session.set_rotation(0, 0, 0)
            if present:
                session.set_part(KEY, lambda: build(viewer, [
                    Neuron("benchmark", "saved skeleton", points, parents, "#ff4d6d")],
                    session.mirror_args()))
                surface = session.surfaces[KEY]
                deadline = time.perf_counter() + 30
                while surface._pick_job is not None and surface._pick_job.running:
                    assert time.perf_counter() < deadline, "picking index did not finish"
                    bench._settle(app)
                    time.sleep(0.01)
                assert set(surface._picker._trees) == set(surface._picker.large)
                result["triangles"] = len(surface.meshset.faces)
            _draw(viewer, app)
            case = {"hover_ms": _hover(viewer, positions)}
            viewer.dims.ndisplay = 2
            session.set_mirror(args.mirror)
            session.set_aligned(args.aligned)
            if args.rotate:
                session.set_rotation(*args.rotate)
            bench._settle(app)
            _draw(viewer, app)
            if not present:
                assert prefetch.settle(30), "atlas prefetch did not finish"
            overlay = session.contours[KEY if present else primary]
            case["slices"] = _slices(viewer, points, app, overlay, args.steps)
            if present:
                assert prefetch.settle(30), "neuron prefetch did not finish"
                assert overlay._plan.error is None, str(overlay._plan.error)
                case["prefetch_s"] = overlay._plan.finished - overlay._plan.started
                case["cache_mb"] = (overlay.sections.planes.nbytes
                                     + overlay._geometry.nbytes) / 2**20
                case["settled_slices"] = _slices(viewer, points, app, overlay,
                                                  args.steps)
            result["neuron" if present else "baseline"] = case
        print(json.dumps(result, indent=2))
    finally:
        viewer.close()


if __name__ == "__main__":
    main()
