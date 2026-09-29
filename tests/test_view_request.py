"""What `lobemap view` accepts, refuses, and opens -- through the real CLI.

Each case runs `lobemap.cli.main` end to end with the window hidden and the
event loop stubbed, then reads the viewer it built. A refusal must come as
one line and a nonzero exit before any window exists.
"""

from __future__ import annotations

import pytest
from viewer_harness import (
    data_root,
    dead_network,
    drawn,
    launched,
    pump,
    session,
    switch_to,
    switcher,
)

pytestmark = pytest.mark.requires_data
pytest.importorskip("napari")


def _one_line(text: str) -> str:
    lines = [line for line in text.splitlines() if line.strip()]
    assert len(lines) == 1, lines
    assert "Traceback" not in text
    return lines[0]


@pytest.mark.parametrize(("argv", "needle"), [
    (["view", "NOPE"], "unknown space 'NOPE'"),
    (["view", "GRABE", "--show", "nope"], "--show 'nope' names nothing in GRABE"),
    # Real names, but not of this space.
    (["view", "GRABE", "--show", "fafb_stain"], "--show 'fafb_stain'"),
])
def test_a_bad_request_is_one_line_and_opens_no_window(monkeypatch, capsys, argv,
                                                       needle):
    with launched(monkeypatch, *argv) as (code, viewer):
        assert viewer is None, "a window opened for a request that cannot load"
    assert code == 2
    err = capsys.readouterr().err
    assert needle in _one_line(err), err


@pytest.mark.parametrize(("space", "name", "shown"), [
    ("FAFB14", "neuropil", "fafb_neuropil"),                 # a role
    ("FAFB14", "fafb_neuropil", "fafb_neuropil"),            # an asset id
    ("JRCFIB2018F", "schlegel2021_s12", "schlegel2021_s12"),  # an atlas id
    ("JRCFIB2018F", "schlegel2021_s12_glomeruli", "schlegel2021_s12"),
])
@pytest.mark.parametrize("ndisplay", ["3", "2"])
def test_show_accepts_asset_ids_atlas_ids_and_roles(monkeypatch, space, name,
                                                     shown, ndisplay):
    with launched(monkeypatch, "view", space, "--ndisplay", ndisplay,
                  "--show", name) as (code, viewer):
        assert code == 0
        pump(300)
        sess = session(viewer)
        surface = sess.surfaces[shown]
        everything = set(range(surface.meshset.n_compartments))
        assert surface.selection == everything
        tab = sess.panel.tabs[shown]
        assert tab.count.text() == f"{len(everything)} / {len(everything)} shown"
        if ndisplay == "3":
            assert drawn(surface) == everything
        else:
            contour = sess.contours[shown]
            assert contour.layer.visible and not surface.layer.visible


def test_show_turns_on_a_label_volume(monkeypatch):
    with launched(monkeypatch, "view", "GRABE", "--show", "grabe2015_labels") as (
        code, viewer,
    ):
        assert code == 0
        assert viewer.layers["grabe2015_labels"].visible


def test_show_applies_to_the_first_scene_only(monkeypatch):
    """The startup `--show` was re-applied to every later space and broke it."""
    with launched(monkeypatch, "view", "FAFB14", "--show", "fafb_neuropil") as (
        code, viewer,
    ):
        assert code == 0
        switch_to(viewer, "GRABE")
        assert switcher(viewer).status.text() == ""
        assert session(viewer).space == "GRABE"
        assert viewer.title == "lobemap - GRABE"

        switch_to(viewer, "FAFB14")
        sess = session(viewer)
        assert sess.space == "FAFB14"
        # FAFB14 again, but chosen in the menu: its own defaults, shell off.
        assert sess.surfaces["fafb_neuropil"].selection == set()
        assert not sess.surfaces["fafb_neuropil"].layer.visible


def test_missing_data_is_reported_before_a_window(monkeypatch, capsys, tmp_path):
    """No data and no network: the reason and the fix, no traceback."""
    dead_network(monkeypatch)
    with launched(monkeypatch, "--data-root", str(tmp_path), "view", "GRABE") as (
        code, viewer,
    ):
        assert viewer is None
    assert code == 1
    out = capsys.readouterr()
    assert "Traceback" not in out.out + out.err
    assert "No data for space 'GRABE'" in out.err
    assert "lobemap fetch" in out.err
    # The download failure is said with its cause, not only as "MISS".
    miss = [line for line in out.out.splitlines() if "MISS" in line]
    assert miss and all(": " in line.split("MISS", 1)[1] for line in miss), miss


def _link_space(tmp_path, *names):
    root = tmp_path / "data"
    root.mkdir()
    for name in names:
        (root / name).symlink_to((data_root() / name).resolve())
    return root


def test_view_reads_the_data_root_it_was_given(monkeypatch, capsys, tmp_path):
    """`--data-root` was fetched into and then ignored: the scene came from
    the default root. A root holding only GRABE must open only GRABE."""
    dead_network(monkeypatch)
    root = _link_space(tmp_path, "grabe2015_glomeruli.npz",
                       "grabe2015_labels.npz", "grabe2015_stack.npz")

    with launched(monkeypatch, "--data-root", str(root), "view", "FAFB14") as (
        code, viewer,
    ):
        assert viewer is None
    assert code == 1
    assert "No data for space 'FAFB14'" in capsys.readouterr().err

    with launched(monkeypatch, "--data-root", str(root), "view", "GRABE") as (
        code, viewer,
    ):
        assert code == 0
        assert session(viewer).registry.data_root == root
        combo = switcher(viewer).combo
        assert [combo.itemData(i) for i in range(combo.count())] == ["GRABE"]
