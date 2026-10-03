"""A space switch replaces the scene whole, or leaves the old one whole.

Every check reads the objects that outlive a scene -- the layer list, the
dock widgets, the handlers on `viewer.dims`, the canvas and the viewer's
mouse callbacks -- because that is where a partial scene survives.
"""

from __future__ import annotations

import pytest
from viewer_harness import (
    data_root,
    docks,
    handler_counts,
    launched,
    layer_names,
    pump,
    session,
    switch_to,
    switcher,
)

pytestmark = pytest.mark.requires_data
pytest.importorskip("napari")


def _snapshot(viewer):
    return {
        "layers": layer_names(viewer),
        "docks": len(docks(viewer, "Glomeruli and neuropils")),
        "handlers": handler_counts(viewer),
        "space": session(viewer).space,
    }


def _assert_intact(viewer, before, title: str) -> None:
    after = _snapshot(viewer)
    assert after == before, {k: (before[k], after[k]) for k in before
                             if before[k] != after[k]}
    status = switcher(viewer).status.text()
    assert status.startswith(f"Could not open {title}: "), status
    assert status.endswith(". Your view is unchanged."), status
    # And the old scene is still the one being driven: a mode round trip
    # neither re-adds the failed scene's layers nor loses the kept ones.
    viewer.dims.ndisplay = 2
    viewer.dims.ndisplay = 3
    pump()
    assert layer_names(viewer) == before["layers"]


@pytest.mark.requires_data("hemibrain_stain")
def test_a_corrupt_asset_leaves_the_previous_space_intact(monkeypatch, capfd, tmp_path):
    """The hemibrain stain fails to open after its neuropil shell is built."""
    root = tmp_path / "data"
    root.mkdir()
    for path in data_root().iterdir():
        if path.name != "README.md":
            (root / path.name).symlink_to(path.resolve())
    (root / "hemibrain_stain.zarr").unlink()
    (root / "hemibrain_stain.zarr").mkdir()        # present, but no store

    with launched(monkeypatch, "--data-root", str(root), "view", "GRABE") as (
        code, viewer,
    ):
        assert code == 0
        before = _snapshot(viewer)
        capfd.readouterr()
        switch_to(viewer, "JRCFIB2018F")
        _assert_intact(viewer, before, "Hemibrain (female, EM)")
        assert "could not open JRCFIB2018F" in capfd.readouterr().err


def test_a_failure_after_the_hooks_are_installed_leaves_none(monkeypatch, capfd):
    """Contour and picking hooks exist by the time the panel is docked."""
    from lobemap.viewer import app

    with launched(monkeypatch, "view", "GRABE") as (code, viewer):
        assert code == 0
        before = _snapshot(viewer)
        real = app.add_dock
        failures = []

        def refuse_once(viewer, widget, name, *args, **kwargs):
            if name == app.PANEL_TITLE and not failures:
                failures.append(True)
                raise RuntimeError("the dock refused")
            return real(viewer, widget, name, *args, **kwargs)

        monkeypatch.setattr(app, "add_dock", refuse_once)
        capfd.readouterr()
        switch_to(viewer, "FAFB14")
        assert failures, "the injected failure was never reached"
        _assert_intact(viewer, before, "FAFB (female, EM)")
        assert "the dock refused" in capfd.readouterr().err


def test_handlers_stay_flat_across_repeated_switches(monkeypatch):
    """Each load connected another initial-fit handler set to the canvas."""
    with launched(monkeypatch, "view", "GRABE") as (code, viewer):
        assert code == 0
        first = handler_counts(viewer)
        seen = []
        for space in ("FAFB14", "JRCFIB2018F", "GRABE", "JRCFIB2022M", "GRABE"):
            switch_to(viewer, space)
            viewer.dims.ndisplay = 2
            viewer.dims.ndisplay = 3
            pump()
            assert session(viewer).space == space
            seen.append(handler_counts(viewer))
        assert seen[-1] == first, (first, seen[-1])
        assert all(counts == seen[0] for counts in seen), seen
        assert len(docks(viewer, "Glomeruli and neuropils")) == 1


def test_layers_are_named_by_title_and_say_whose_they_are(monkeypatch):
    """A layer's name is its part's title and what it draws; a neuropil
    set's says where its data come from. No id, and no tag in brackets."""
    with launched(monkeypatch, "view", "FAFB14") as (code, viewer):
        assert code == 0
        names = layer_names(viewer)
        assert "Neuropils (FlyWire) · not loaded yet" in names, names
        session(viewer).panel.tab("fafb_neuropil")   # built when its tab opens
        names = layer_names(viewer)
        assert names == sorted([
            "Benton 2025 · 3D", "Benton 2025 · outlines",
            "Neuropils (FlyWire) · 3D", "Neuropils (FlyWire) · outlines",
            *(["Neuropil stain (from synapses)"] if session(viewer).images else []),
        ]), names
