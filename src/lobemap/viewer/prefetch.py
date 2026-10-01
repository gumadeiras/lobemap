"""Cut every slider plane of a shown atlas ahead of time, off the UI thread.

A first visit to a plane cost its exact sections and its outline geometry
on the UI thread, 2-5 ms, and with every compartment filled 1-2 ms more for
the fills. All are pure functions of the meshes and the plane, so once a
space is open in 2D -- and again after the slice axis, the mirror or the
filled compartments change -- a worker thread computes them for every
slider plane inside each shown atlas, nearest the current plane first, into
the overlay's own caches. A step to a plane it has reached only draws; one
it has not reached yet cuts, or fills, that plane itself.

Threading model, after route (c) of the slice-step search:

- One daemon worker, taking one `Plan` at a time, started when a plan is
  submitted and gone once none is left. A plan holds only what it was
  handed on the UI thread: the overlay's `MeshSections` and geometry cache
  (both locked), a copy of the layer's world-to-data transform, and the
  dims grid. It never touches a layer, a viewer or a Qt object, and nothing
  is delivered back: a step reads the caches as before.
- The worker holds the interpreter lock while it runs Python, which slows a
  UI thread that wants it at the same moment. So it gives way: every slice
  step pokes it before napari slices anything
  (`napari_private.before_slicing`), and while the UI thread has worked on
  a slice in the last `QUIET_S`, it waits at its next pause -- between
  planes, and between the stages of a cut.
- A plan is cancelled when its overlay asks for another (a new axis, a
  mirror, other fills), is hidden, or is torn down; it stops at its next
  pause. Nothing it has made is ever wrong: a cache entry is keyed by the
  plane it was cut at, and a fill by its compartment. A plan for other
  fills finds the sections and outlines already cut and builds only the
  fills they lack.
- To make room it evicts only planes that are not its own, the ones an
  earlier axis or mirror left, and stops when that is not enough.
- A plane whose cut raises anything -- a Rust panic in bermuda is a
  BaseException -- is skipped, and the plan goes on to the next; the plan
  keeps the first error. A step onto that plane cuts it on the UI thread,
  where the error is seen. Nothing a plan raises ends the worker.
"""

from __future__ import annotations

import threading
import time
from collections import deque

import numpy as np

#: How long after the UI thread last worked on a slice the worker waits
#: before its next stage.
QUIET_S = 0.03

_last_ui = [0.0]
#: Guards `_PLANS` and `_WORKER`, and is waited on by `settle`.
_LOCK = threading.Condition()
_PLANS: deque = deque()
_WORKER: threading.Thread | None = None


def poke() -> None:
    """The UI thread is working on a slice now. UI thread only."""
    _last_ui[0] = time.perf_counter()


class _Cancelled(Exception):
    """Raised at a pause to stop a cancelled plan mid-plane."""


class Plan:
    """Every slider plane of one overlay along one axis, frozen on the UI thread.

    `to_data` is the layer's world-to-data transform as it is now, called
    exactly as `Layer.world_to_data` calls it, so each position is the one
    `ContourOverlay.slice_position` gives on that step, to the last bit.

    `build(cut, axis, position, pause, fills)` makes a plane's geometry,
    with the fills of the compartments in `fills`; a geometry already in the
    cache gets the fills it lacks from its own `add_fills(fills, pause)`.
    """

    def __init__(self, sections, geometry, build, axis: int, to_data, point,
                 grid: tuple[float, float, int], bounds: tuple[float, float],
                 current: float, fills=frozenset()) -> None:
        self.sections, self.geometry, self.build = sections, geometry, build
        self.fills = frozenset(fills)
        self.axis = int(axis)
        self.to_data = to_data
        self.point = tuple(float(v) for v in point)
        self.grid = grid
        self.bounds = bounds
        self.current = float(current)
        self.cancelled = False
        #: Filled in by the worker, for reports and tests: the planes cut,
        #: the planes whose cut raised, and the first error raised.
        self.planes = 0
        self.skipped = 0
        self.full = False
        self.error: Exception | None = None
        self.started = self.finished = None

    def cancel(self) -> None:
        self.cancelled = True

    def _pause(self) -> None:
        """Where the worker gives way to the UI thread; a cancelled plan stops here."""
        while not self.cancelled:
            idle = time.perf_counter() - _last_ui[0]
            if idle >= QUIET_S:
                return
            time.sleep(min(QUIET_S - idle, 0.01))
        raise _Cancelled

    def positions(self, pause=None) -> list[float]:
        """Data positions of every slider step inside the bounds, nearest first.

        `pause` is called now and then: the worker gives way there.
        """
        start, step, nsteps = self.grid
        lo, hi = self.bounds
        base = list(self.point)
        out = []
        for k in range(nsteps):
            if pause is not None and k % 32 == 31:
                pause()
            base[self.axis] = start + k * step         # as Dims.set_current_step
            position = float(self.to_data(list(np.asarray(base)))[self.axis])
            if lo <= position <= hi:
                out.append(position)
        return sorted(out, key=lambda p: (abs(p - self.current), p))

    def run(self) -> None:
        self.started = time.perf_counter()
        try:
            positions = self.positions(self._pause)
            mine = {(self.axis, p) for p in positions}
            for position in positions:
                self._pause()
                try:
                    kept = self._cut(position, mine)
                except _Cancelled:
                    raise
                except BaseException as exc:  # noqa: BLE001 - a step cuts this plane itself
                    # One bad plane is left to the step that lands on it,
                    # which raises where it can be seen; the rest are cut.
                    # BaseException: a Rust panic in bermuda is one.
                    self.skipped += 1
                    if self.error is None:
                        self.error = exc
                    continue
                if not kept:
                    self.full = True
                    return
                self.planes += 1
        finally:
            self.finished = time.perf_counter()

    def _cut(self, position: float, mine: set) -> bool:
        """Cut one plane into the caches; False if they have no room for it."""
        key = (self.axis, position)
        cut = self.sections.at(self.axis, position, keep=mine, pause=self._pause)
        if cut is None:
            return False
        self._pause()
        kept = self.geometry.get(key)
        if kept is None:
            made = self.build(cut, self.axis, position, self._pause, self.fills)
            return self.geometry.put(key, made, made.nbytes, keep=mine) is not None
        added = kept.add_fills(self.fills, self._pause)
        return not added or self.geometry.grew(key, added, keep=mine)


def _work() -> None:
    global _WORKER
    while True:
        with _LOCK:
            if not _PLANS:
                _WORKER = None
                _LOCK.notify_all()
                return
            plan = _PLANS.popleft()
        try:
            if not plan.cancelled:
                plan.run()
        except _Cancelled:
            pass
        except BaseException as exc:  # noqa: BLE001 - the worker outlives any plan
            plan.error = exc


def submit(plan: Plan) -> None:
    """Queue `plan` for the worker, starting it if none is running. UI thread only."""
    global _WORKER
    with _LOCK:
        _PLANS.append(plan)
        if _WORKER is None:
            _WORKER = threading.Thread(target=_work, name="lobemap-prefetch", daemon=True)
            _WORKER.start()


def busy() -> bool:
    """Whether any plan is queued or running."""
    with _LOCK:
        return _WORKER is not None


def settle(timeout: float = 30.0) -> bool:
    """Wait until every queued plan has run or stopped; True if they have.

    For tests and the benchmark. The viewer never waits.
    """
    with _LOCK:
        return _LOCK.wait_for(lambda: _WORKER is None, timeout)


__all__ = ["QUIET_S", "Plan", "busy", "poke", "settle", "submit"]
