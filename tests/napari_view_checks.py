"""What lobemap reaches of napari's viewer for the status bar, the camera and
its actions. Split out of `test_napari_private`, which imports these tests,
merges `CHECKED` into its own, and runs them with its `viewer` fixture and its
`need` and `reaching`.
"""

from __future__ import annotations

#: Every private name these tests check, and the test that checks it.
CHECKED = {
    "_calc_status_from_cursor": "test_the_status_napari_reckons_for_the_cursor",
    "_view_direction": "test_the_status_napari_reckons_for_the_cursor",
}


def _helpers():
    from test_napari_private import need, reaching

    return need, reaching


def test_the_status_napari_reckons_for_the_cursor(viewer):
    """`napari_private.status_for_cursor`: napari reckons the status bar's
    words for the cursor in `ViewerModel._calc_status_from_cursor`, which its
    status thread and its change of active layer both call through the
    viewer, and reads the cursor's ray from `Cursor._view_direction`."""
    import inspect

    from napari._qt.threads.status_checker import StatusChecker

    from lobemap.viewer.napari_private import status_for_cursor

    need, reaching = _helpers()
    used = "viewer.napari_private.status_for_cursor"
    with reaching("ViewerModel._calc_status_from_cursor and Cursor._view_direction", used):
        reckon = type(viewer)._calc_status_from_cursor
        callers = (inspect.getsource(StatusChecker.calculate_status)
                   + inspect.getsource(type(viewer).update_status_from_cursor))
        direction = viewer.cursor._view_direction
    need(callable(reckon) and not inspect.signature(reckon).parameters.keys() - {"self"},
         "ViewerModel._calc_status_from_cursor(), taking no argument", used)
    need(callers.count("._calc_status_from_cursor()") == 2,
         "StatusChecker.calculate_status and update_status_from_cursor calling "
         "viewer._calc_status_from_cursor()", used)
    need(direction is None or len(direction) == 3, "Cursor._view_direction", used)

    seen = []
    status_for_cursor(viewer, lambda position, ray: seen.append(ray) or "Named")
    viewer.mouse_over_canvas = True
    viewer.update_status_from_cursor()
    need(viewer.status == "Named" and seen,
         "the viewer's own _calc_status_from_cursor, called through the instance", used)
    viewer.mouse_over_canvas = False
