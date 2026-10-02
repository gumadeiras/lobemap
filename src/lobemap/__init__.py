"""lobemap -- Drosophila antennal lobe glomerular atlases across coordinate spaces."""

from importlib.metadata import PackageNotFoundError, version

#: Read from the installed package metadata, so `pyproject.toml` is the
#: only place a version is written. The two used to be separate strings
#: and drifted: the release workflow checks its tag against pyproject
#: while `lobemap --version` read the one here, so they could disagree
#: without anything failing.
#:
#: The fallback is for a source tree that was never installed, where
#: there is no metadata to read. Everything here runs from the project
#: venv, so it is a guard rather than a path anyone takes.
try:
    __version__ = version("lobemap")
except PackageNotFoundError:            # pragma: no cover
    __version__ = "0+unknown"

__all__ = ["__version__"]
