"""napari's layer list cannot copy or link lobemap's layers, and says why.

Each action goes through napari's own command, as its layer menu and command
palette run it. What is checked is the viewer: which layers exist, what each
atlas draws in 3D and in Slice view, and what lobemap says.
"""

from __future__ import annotations

import pytest
from chrome_harness import told
from viewer_harness import assert_rows_match_drawing, launched, pump, session, switcher

pytestmark = pytest.mark.requires_data
pytest.importorskip("napari")

SPACE = "GRABE"


@pytest.fixture
def opened(monkeypatch):
    with launched(monkeypatch, "view", SPACE) as (code, viewer):
        assert code == 0
        yield viewer


def _run(command: str) -> None:
    from napari._app_model import get_app_model

    get_app_model().commands.execute_command(command).result()
    pump(50)


def test_a_copy_of_lobemaps_layer_is_refused_and_a_users_is_made(opened):
    """A Duplicate of the stain kept lobemap's mark: locked, it could not be
    deleted, did not follow the mirror, kept a turn Reset rotation gave back
    to the original, and outlived a switch. A projection kept the mark too."""
    from lobemap.viewer.guards import NOT_COPIED

    viewer = opened
    sw, sess = switcher(viewer), session(viewer)
    sw.slice_view.click()
    sw.rotation.box["spin"].setValue(30.0)
    pump()
    ours = list(viewer.layers)
    stain = next(layer for layer in sess.images if layer.visible)
    for command in ("napari.layer.duplicate", "napari.layer.project_max"):
        viewer.layers.selection.active = stain
        with told() as said:
            _run(command)
        assert list(viewer.layers) == ours, command
        assert said == [NOT_COPIED.format(names=repr(f"{stain.name} copy"))] or (
            command != "napari.layer.duplicate" and len(said) == 1
            and said[0].startswith(repr(stain.name)[:-1])), (command, said)
    mine = viewer.add_points(ndim=3)
    viewer.layers.selection.active = mine
    _run("napari.layer.duplicate")
    copies = [layer for layer in viewer.layers if layer.name == f"{mine.name} copy"]
    assert len(copies) == 1 and not copies[0].locked
    sw.rotation.reset.click()
    pump()
    assert_rows_match_drawing(sess)


def test_linking_lobemaps_layers_is_refused(opened):
    """Linked, an atlas's 3D and outline layers were drawn in neither mode
    after one trip, while the panel still said every row was shown."""
    from napari.layers.utils._link_layers import get_linked_layers

    from lobemap.viewer.guards import NOT_LINKED

    viewer = opened
    sess = session(viewer)
    name = sess.registry.primary_atlas(SPACE).id
    surface, contour = sess.surfaces[name], sess.contours[name]
    viewer.layers.selection.clear()
    viewer.layers.selection.update({surface.layer, contour.layer})
    with told() as said:
        _run("napari.layer.link_selected_layers")
    assert not get_linked_layers(surface.layer) and not get_linked_layers(contour.layer)
    assert len(said) == 1 and said[0].startswith(NOT_LINKED.split("{names}")[0]), said
    for ndisplay in (2, 3, 2):
        viewer.dims.ndisplay = ndisplay
        pump(300)
        assert_rows_match_drawing(sess)
    # The user's own still link.
    a, b = viewer.add_points(ndim=3), viewer.add_points(ndim=3)
    viewer.layers.selection.clear()
    viewer.layers.selection.update({a, b})
    _run("napari.layer.link_selected_layers")
    assert b in get_linked_layers(a)
