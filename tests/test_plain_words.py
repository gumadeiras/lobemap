"""No identifier reaches the user: every string, in every brain and mode.

Each of the four brains is read as it opens, then with every tab built and
every row shown, in 3D and in 2D, and turned across the image grid by the
View dock's angle boxes -- window title, docks, tabs, menus, buttons,
headers, cells, details, tooltips, napari's layer names, colormaps and
sliders, napari's button rows and the popups they open, the status bar and
what hovering says (`ui_strings`). A string
fails if it holds snake_case, an asset or atlas id, a bracketed tag or an
abbreviation nothing spells out. Biology names from the registry, a quoted
source label and the template names the Dataset menu gives are allowed,
and so is what napari shows of its own.
"""

from __future__ import annotations

import re

import pytest
import ui_strings as U
from viewer_harness import SPACES, launched, pump, session, switcher

pytestmark = pytest.mark.requires_data
napari = pytest.importorskip("napari")


@pytest.fixture(scope="module")
def allowed(registry):
    found = U.Allowed.from_registry(registry)
    viewer = napari.Viewer(show=False)
    try:
        found.napari = U.napari_baseline(viewer)
    finally:
        viewer.close()
        pump()
    return found


def test_the_check_tells_code_from_words(allowed):
    words = [
        "VA3 (left) — Benton 2025", "AL, antennal lobe (right) — Neuropils (FlyWire)",
        "Orco-GAL4 & GH146-GAL4 (12)", "MB_PED, Left", "Neuropil stain (from synapses)",
        "Grabe 2015 labels this region 'VP2_left_VM6andVC6'.", "Male CNS (EM)",
        ("FAFB (full adult fly brain): female, electron microscopy. "
         "Shown in the FAFB14 template."), "Glomerulus colors (3)",
    ]
    for text in words:
        assert U.why_code(text, allowed) == "", text
    code = {
        "benton2025: VA3": "id benton2025",
        "fafb_neuropil [bridged]": "id fafb_neuropil",
        "Benton 2025 [contours]": "bracketed tag",
        "receptor_consensus": "snake_case",
        "ROI under the cursor": "unexplained abbreviation ROI",
        "lobemap - GRABE": "unexplained abbreviation GRABE",
    }
    for text, why in code.items():
        assert U.why_code(text, allowed) == why, text


def test_no_string_in_any_brain_or_mode_reads_as_code(monkeypatch, allowed, registry):
    seen: dict[str, set] = {}
    with launched(monkeypatch, "view", SPACES[0]) as (code, viewer):
        assert code == 0
        for space, state, shown in U.walk(viewer, SPACES):
            for item in shown:
                seen.setdefault(item, set()).add((space, state))
        # Each explained abbreviation is spelled out where it appears: in the
        # Dataset menu's tooltip of every brain whose title carries it.
        menu = switcher(viewer).combo
        for i in range(menu.count()):
            for word, spelled in U.EXPLAINED.items():
                if re.search(rf"\b{word}\b", menu.itemText(i)):
                    assert spelled in menu.itemData(i, 3), (menu.itemText(i), word)
    kinds = {item.where.split(" / ")[-1] for item in seen}
    for kind in ("window title", "dock title", "tab", "menu item", "menu item tooltip",
                 "button", "column header", "cell", "cell tooltip", "label",
                 "layer name", "colormap", "slider label", "hover"):
        assert kind in kinds, kind
    assert any(item.text == "depth" for item in seen), "no oblique slider read"
    # The restored buttons, their popups and the new controls were read, in
    # every brain, in each mode they show in.
    from lobemap.viewer import buttons, camera_rows

    shown_in: dict[str, set] = {}
    for item, where in seen.items():
        shown_in.setdefault(item.text, set()).update(where)
    both = ("2d_default", "3d_default")
    expected = {
        buttons.TRANSPOSE_OFF: both, buttons.GRID_OFF: both, buttons.DELETE_TIP: both,
        buttons.ROLL_TIP: ("2d_default",), buttons.ROLL_3D: ("3d_default",),
        buttons.ROLL_POPUP_TIP: ("2d_default",), buttons.VERTICAL_TIP: both,
        buttons.HORIZONTAL_OFF: both, buttons.DEPTH_OFF: ("3d_default",),
        camera_rows.ZOOM_TIP: both, camera_rows.PERSPECTIVE_TIP: both,
        camera_rows.ZOOM_UNIT.strip(): both, camera_rows.FLAT: both,
        camera_rows.THREE_D_ONLY: ("2d_default",), camera_rows.ZOOM: both,
        camera_rows.PERSPECTIVE: both,
    }
    for text, states in expected.items():
        for space in SPACES:
            for state in states:
                assert (space, state) in shown_in.get(text, set()), (text, space, state)
    bad = [(item.where, item.text, why, min(seen[item]))
           for item, why in U.problems(seen, allowed)]
    assert not bad, "\n".join(map(repr, bad[:40]))


def test_a_planted_identifier_is_caught(monkeypatch, allowed):
    with launched(monkeypatch, "view", "GRABE") as (code, viewer):
        assert code == 0
        sess = session(viewer)
        assert not U.problems(U.collect(viewer), allowed)
        sess.surfaces["grabe2015"].layer.name = "grabe2015 [contours]"
        sess.panel.setTabToolTip(0, "Every row of schlegel2021_s11")
        switcher(viewer).status.setText("ROI not loaded")
        viewer.status = "VP2_left_VM6andVC6 under the cursor"
        pump()
        caught = {(item.where, item.text): why
                  for item, why in U.problems(U.collect(viewer), allowed)}
        assert caught == {
            ("layer name", "grabe2015 [contours]"): "id grabe2015",
            ("Glomeruli and neuropils / tab tooltip", "Every row of schlegel2021_s11"):
                "id schlegel2021_s11",
            ("View / label", "ROI not loaded"): "unexplained abbreviation ROI",
            ("status bar status", "VP2_left_VM6andVC6 under the cursor"): "snake_case",
        }, caught


def test_every_message_reads_as_words(allowed, registry):
    """The status lines a switch or a tab can show, for every brain and tab,
    and every reason they give, which the walk above never meets."""
    from lobemap.viewer import buttons, chrome, panel
    from lobemap.viewer import switcher as dock

    for text in (dock.SWAPPED, chrome.STAYS_LOCKED, *buttons.OFF_KEYS.values()):
        assert U.why_code(text, allowed) == "", text
    reasons = [dock.plain_reason(exc) for exc in (
        FileNotFoundError(), MemoryError(), PermissionError(), ValueError())]
    for space in registry.spaces.values():
        title = space.title or space.id
        texts = [dock.OPENING.format(title=title), dock.UNFITTED.format(title=title),
                 dock.UNTURNED.format(title=title), dock.brain_tip(space)]
        texts += [dock.FAILED.format(title=title, reason=r) for r in reasons]
        for text in texts:
            assert U.why_code(text, allowed) == "", text
    for asset in registry.assets.values():
        for exc in (FileNotFoundError(), OSError(), MemoryError(), ValueError()):
            title = asset.origin or asset.title      # as the source menu names it
            text = f"{title} could not be opened: {panel.plain_reason(exc)}"
            assert U.why_code(text, allowed) == "", text
