"""A closed window takes its scene with it.

A closed window's scene stayed alive: a global of lobemap's kept every
window's viewer (`buttons.take_action`), napari kept a window closed by its
own button, and Qt held each scene's widgets, colormap entries and all,
until its event loop turned. So the tests of one process -- CI runs them in
one -- piled up every brain they opened, and a window opened after another
closed numbered its colormap entries, "Benton 2025 colors (2)".

Each test uses a real window the way a user does, closes it, lets Qt delete
what the close left to it, collects, and then finds nothing of any scene
the window showed: weak references to every part of it, and the threads.
"""

from __future__ import annotations

import gc
import re
import threading
import weakref

import pytest
from viewer_harness import (
    SPACES,
    clear_all,
    click,
    hover,
    launched,
    pump,
    session,
    switch_to,
    switcher,
    tick_all,
)

pytestmark = pytest.mark.requires_data
pytest.importorskip("napari")

#: lobemap's reader pools: every window of the process shares them.
POOLS = ("lobemap-chunks", "lobemap-resample")


def _probe(probes: dict, sess) -> None:
    """A weak reference to every part of the scene `sess` shows."""
    tag = sess.space
    probes[f"{tag} session"] = weakref.ref(sess)
    for name, surface in sess.surfaces.items():
        probes[f"{tag} {name} surface"] = weakref.ref(surface)
        probes[f"{tag} {name} 3D layer"] = weakref.ref(surface.layer)
    for name, contour in sess.contours.items():
        probes[f"{tag} {name} contours"] = weakref.ref(contour)
        probes[f"{tag} {name} outline layer"] = weakref.ref(contour.layer)
    probes[f"{tag} panel"] = weakref.ref(sess.panel)
    for name, tab in sess.panel.tabs.items():
        probes[f"{tag} {name} tab"] = weakref.ref(tab)
    for layer in sess.images:
        probes[f"{tag} {layer.name} image"] = weakref.ref(layer)
    if sess.deferred is not None:
        probes[f"{tag} deferred parts"] = weakref.ref(sess.deferred)


def _use(viewer, spaces) -> dict:
    """In each of `spaces`, opened in turn: every part built, its rows ticked
    and cleared by the header checkboxes and every Sides choice, 2D and 3D
    and back, the view turned oblique, mirrored and flipped, a hover and a
    click in each mode. Returns the probes of every scene shown."""
    sw = switcher(viewer)
    probes: dict = {}
    for k, space in enumerate(spaces):
        if k:
            switch_to(viewer, space)
        sess = session(viewer)
        for name in list(sess.parts):
            tab = sess.panel.open(name)             # a deferred part is built
            if tab is not None:
                tick_all(tab)
                clear_all(tab)
                tick_all(tab)
        for page in sess.panel.pages.values():
            for i in (*range(page.sides_menu.count()), 0):
                page.sides_menu.setCurrentIndex(i)
        primary = sess.surfaces[sess.registry.primary_atlas(space).id]
        inside = primary.meshset.centroid(min(primary.selection))
        for ndisplay in (2, 3, 2):
            viewer.dims.ndisplay = ndisplay
            pump()
        sw.rotation.box["tilt"].setValue(25.0)
        sw.rotation.box["spin"].setValue(15.0)
        sw.mirror.setChecked(True)
        sw.flip.setChecked(True)
        pump(100)
        for ndisplay in (2, 3):
            viewer.dims.ndisplay = ndisplay
            hover(viewer, inside)
            click(viewer, inside)
        sw.mirror.setChecked(False)
        sw.flip.setChecked(False)
        sw.rotation.reset.click()
        pump(100)
        _probe(probes, sess)
    return probes


def _lobemap_threads(before) -> list[threading.Thread]:
    """lobemap's threads started since `before`, but for the shared pools,
    once each has had a moment to finish what it was told to stop."""
    from lobemap.viewer import prefetch

    prefetch.settle(10)
    started = [t for t in threading.enumerate() if t not in before
               and t.name.startswith("lobemap") and not t.name.startswith(POOLS)]
    for thread in started:
        thread.join(10)
    return [t for t in started if t.is_alive()]


@pytest.mark.parametrize("how", ["viewer.close", "the window's close"])
def test_a_closed_window_leaves_nothing_of_its_scenes(monkeypatch, how):
    """Closed by `viewer.close`, through every brain; or by the window's own
    close -- its close button, File > Close Window -- which used to close no
    viewer at all, through two."""
    before = set(threading.enumerate())
    with launched(monkeypatch, "view", SPACES[0]) as (code, viewer):
        assert code == 0
        probes = _use(viewer, SPACES if how == "viewer.close" else SPACES[::3])
        probes["viewer"] = weakref.ref(viewer)
        probes["View dock"] = weakref.ref(switcher(viewer))
        if how == "viewer.close":
            viewer.close()
        else:
            # As napari's close button and File > Close Window do once the
            # user has confirmed; the harness closes the viewer again after.
            viewer.window._qt_window.close()
            assert not viewer.layers, "the window's close left the viewer open"
        del viewer
    # Qt deletes the closed window's widgets as its event loop turns, and
    # PyQt the handlers they held as it turns again.
    pump()
    gc.collect()
    alive = sorted(name for name, ref in probes.items() if ref() is not None)
    assert not alive, alive
    assert not _lobemap_threads(before)


def test_a_window_opened_after_one_closed_numbers_no_colormap(monkeypatch):
    """A second window takes the colormap entries the first gave back as it
    closed, though Qt has not deleted the first's widgets yet and nothing
    has been collected."""
    gc.collect()                    # what earlier tests left uncollected

    def names() -> set[str]:
        sess = session(viewer)
        for name in list(sess.parts):
            sess.panel.tab(name)
        return {surface.layer.colormap.name for surface in sess.surfaces.values()}

    with launched(monkeypatch, "view", SPACES[0]) as (code, viewer):
        assert code == 0
        first = names()
    with launched(monkeypatch, "view", SPACES[0]) as (code, viewer):
        assert code == 0
        second = names()
    assert not [n for n in first if re.search(r"\(\d+\)$", n)], first
    assert second == first
