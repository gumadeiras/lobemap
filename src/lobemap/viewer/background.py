"""Work that takes seconds -- reading an image, fetching and bridging a
neuron -- done off the UI thread, its result handed back on it.

A daemon thread, polled from the UI thread, as `images.FineLevel` reads a
3D level: the thread only stores its result, so no Qt object is touched off
the UI thread, and a job still running when the process exits is dropped
rather than waited for.
"""

from __future__ import annotations

import threading


class Job:
    """`work()` in a thread; `done(result)` or `failed(error)` on the UI thread."""

    #: How often the UI thread looks for the result, in milliseconds.
    POLL_MS = 30

    def __init__(self, work, done, failed) -> None:
        from qtpy.QtCore import QTimer

        self._done, self._failed = done, failed
        self._result = None
        self.cancelled = False

        def run() -> None:
            try:
                self._result = ("ok", work())
            except Exception as exc:              # noqa: BLE001 - handed to `failed`
                self._result = ("failed", exc)

        self._timer = QTimer()
        self._timer.setInterval(self.POLL_MS)
        self._timer.timeout.connect(self._poll)
        threading.Thread(target=run, name="lobemap-job", daemon=True).start()
        self._timer.start()

    @property
    def running(self) -> bool:
        return self._timer.isActive()

    def _poll(self) -> None:
        result = self._result
        if result is None:
            return
        self._timer.stop()
        if self.cancelled:
            return
        status, value = result
        (self._done if status == "ok" else self._failed)(value)

    def cancel(self) -> None:
        """Hand nothing back: the tab or its brain is gone."""
        self.cancelled = True
        self._timer.stop()


__all__ = ["Job"]
