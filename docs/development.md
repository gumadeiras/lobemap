# Development

This page explains how to work on lobemap from a source checkout: set it up, run it, test it, time it, lint it, and release it.

## Set up

lobemap needs Python 3.11 or 3.12, and uses [uv](https://docs.astral.sh/uv/). From the repository root:

```bash
uv sync
uv run lobemap fetch
```

A checkout keeps its data in `registry/data`. [Data](data.md) explains the download, and `uv run lobemap fetch --nostains` gets everything but the three virtual stains, 76 MB.

`uv sync` installs two dependency groups by default:

- `dev`: pytest, pytest-xdist, ruff, and setuptools for the wheel test;
- `ingest`: the extra dependencies for rebuilding data and bridging between spaces, about 100 packages. It is the same set as `pip install "lobemap[ingest]"`.

To leave the ingest dependencies out, pass `--no-group ingest` to both `uv sync` and `uv run`, as in `uv run --no-group ingest lobemap`.

## Run lobemap from the checkout

`lobemap` is installed into the project's virtual environment, so `uv run` is the simplest way to reach it:

```bash
uv run lobemap
uv run lobemap spaces
uv run lobemap view JRCFIB2018F
```

`uv run lobemap` opens FAFB, after fetching the 76 MB of core data if it is not on disk yet.

To drop the `uv run` prefix, activate the environment:

| system | command |
|---|---|
| macOS and Linux | `source .venv/bin/activate` |
| Windows | `.venv/Scripts/Activate.ps1` |

The commands work from any directory. A checkout reads its own `registry/`. [Commands](cli.md) lists every command.

## Tests

The tests live in `tests/` and run with pytest.

### Run the tests

To run one test file:

```bash
uv run pytest tests/test_mirror.py
```

To run the whole suite, run the files in parallel, one worker per core:

```bash
uv run pytest -n auto --dist loadfile
```

`-n auto` comes from pytest-xdist. `--dist loadfile` keeps each test file in one worker, in order. The whole suite in one process (`uv run pytest`) works too, but it is much slower: the suite opens real viewer windows across all four brains.

The viewer tests open napari windows that are not shown. They still need a display with OpenGL.

### Tests and data

A test that reads fetched data carries the `requires_data` marker:

```python
@pytest.mark.requires_data                   # the core data
@pytest.mark.requires_data("fafb_stain")     # exactly these assets
```

- Bare, the marker asks for the *core data*: every asset that `lobemap view` fetches by itself. That is every asset but the virtual stains, and `lobemap fetch --nostains` gets it.
- With arguments, the marker asks for exactly those assets, by their id in `registry/assets.toml`. The stain tests need the full `lobemap fetch`.

A test whose data is not on disk is skipped, and the reason names the missing ids. So `LOBEMAP_DATA` pointing at an empty directory skips them all. An id that the registry does not declare stops the run instead, so a typo cannot retire a test quietly. A fixture that needs the core data requests the `core_data` fixture, because fixtures cannot carry marks. `tests/conftest.py` explains the details.

### No network

The tests never reach the network. Python's sockets are guarded for the whole session. Any connection to an address that is not loopback is refused, and fails the test that tried it.

The tests also use a napari settings file of their own, so they do not change the settings of your own napari.

## Benchmarks

The benchmarks need the data on disk. Each one runs its measurements in fresh processes.

```bash
uv run python benchmarks/slice_step.py
uv run python benchmarks/space_switch.py
uv run python benchmarks/neuron_navigation.py neuron.npz --space FAFB14
```

- `slice_step.py` times 2D slice steps, row toggles, scene loads and switches between 2D and 3D. `--rotate SPIN TILT TURN`, `--aligned` and `--flip` time a turned, aligned or flipped scene.
- `space_switch.py` times opening a space and switching to another, as the **Brain** menu does.
- `neuron_navigation.py` compares 3D hover and consecutive slice steps before and after adding a saved neuron. Its NPZ input has `points` in the chosen brain's micrometers and `parents` with -1 for roots. It applies normal display thinning, waits for the picking index, and measures slices with prefetch active and finished. `--rotate`, `--aligned` and `--mirror` exercise other slice planes. Frame times include drawing and framebuffer readback; they are workload comparisons, not screen frame rates. Repeat the command in fresh processes to check the spread.

`--help` lists the options of each, and the docstring at the top of each file explains what it measures. The machine is rarely quiet, so repeat the measurements and read the spread. `slice_step.py` and `space_switch.py` accept `--repeat`.

### Picking index lifecycle

Each surface owns a `MeshPicker` for its immutable `MeshSet`. When the surface is first shown in 3D, including through napari's layer eye, compartments with at least 16,384 faces are indexed by a background `Job`. The job reads mesh arrays only; its result is installed on the UI thread. Picking uses full triangle scans until the index is ready, or if preparation fails. Index queries are serialized because the underlying library does not support simultaneous reads of one index.

The index is reused across selection changes, hiding, mirroring, and 2D/3D switches. Scene teardown or part replacement calls `AtlasSurface.stop()`: it cancels preparation and blocks result delivery. An active native compartment build finishes, then its result is discarded and no later compartment build starts. The shared `Job.cancel()` contract remains result-delivery cancellation; `MeshPicker.cancel()` supplies the cooperative stop between builds.

## Lint

```bash
uv run ruff check src tests benchmarks
```

The ruff settings are in `pyproject.toml`. CI does not run ruff.

## Continuous integration

`.github/workflows/test.yml` runs on every pull request and on every push to `main`:

1. `uv sync --locked`.
2. `uv run lobemap fetch --nostains`. A fetch that fails fails the job, so the data tests cannot skip quietly.
3. The tests, in parallel: `uv run pytest -q -rs -n auto --dist loadfile --durations=25`. `--durations=25` lists the slowest tests. `LP_NUM_THREADS=1` gives each worker one software render thread, so the workers do not compete for the same cores.
4. A wheel build. The wheel is installed into a fresh environment outside the checkout, and `lobemap --version`, `lobemap spaces` and `lobemap validate` run from there.

The tests run on Linux under Xvfb, a virtual display, because the viewer tests need OpenGL.

`.github/workflows/publish-to-pypi.yml` publishes the package to PyPI when a GitHub release is published. It skips the data releases, whose tags start with `data-`.

## Changelog and release

Add each user-visible change to `CHANGELOG.md`, under `## Unreleased`. [RELEASE.md](../RELEASE.md) has the release checklist, the data release steps, and the changelog rules.
