"""`lobemap view` must forward its flags to the viewer.

`--show` was parsed and then dropped on the floor: argparse accepted it,
`_show_layers` was written and tested, and the two were never connected, so
the flag silently did nothing. Nothing failed, which is why it survived --
the only way to catch it is to assert on what the CLI actually passes.
"""

from __future__ import annotations

import pytest

from lobemap import cli


@pytest.fixture
def captured(monkeypatch):
    """Intercept `run` so the CLI can be exercised without a GUI."""
    calls: list[dict] = []

    def fake_run(registry_root, space=None, **kwargs):
        calls.append({"registry_root": registry_root, "space": space, **kwargs})

    monkeypatch.setattr("lobemap.viewer.app.run", fake_run)
    return calls


def _view(captured, argv):
    """Run the real CLI, end to end, with only `run` stubbed out."""
    assert cli.main(["view", *argv]) == 0
    assert captured, "cmd_view never reached run()"
    return captured[0]


def test_show_is_forwarded(captured):
    assert _view(captured, ["FAFB14", "--show", "axes"])["show"] == ("axes",)


def test_show_is_repeatable(captured):
    call = _view(captured, ["FAFB14", "--show", "axes",
                            "--show", "fafb_stain"])
    assert call["show"] == ("axes", "fafb_stain")


def test_no_show_means_no_layers_forced(captured):
    assert _view(captured, ["FAFB14"])["show"] == ()


def test_the_other_flags_still_arrive(captured):
    call = _view(captured, ["FAFB14", "--ndisplay", "2"])
    assert call["space"] == "FAFB14"
    assert call["ndisplay"] == 2


def test_cross_space_flags_are_gone(captured):
    """An atlas belongs to one space and is only ever shown there."""
    import pytest as _pytest

    for flag in ("--bridged", "--align-biology"):
        with _pytest.raises(SystemExit):
            cli.main(["view", "FAFB14", flag])
