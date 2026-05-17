# AGENTS.md

## Repo Rules

- Keep markdown prose and list items on natural lines; do not add artificial hard wraps just to satisfy a line length.
- Preserve existing data files and generated caches unless a task explicitly requires regenerating them.
- Use `uv run` for Python commands in this repo.
- Run `uv run python -m compileall <changed python files>` after Python edits when no narrower test exists.

## Changelog

- Update `CHANGELOG.md` for user-visible behavior, CLI changes, packaging changes, data-source changes, and release-process changes.
- Add new entries under `## Unreleased` unless preparing a release.
- Keep changelog bullets concise and single-line when practical.

## Release

- Do not publish or create a release without explicit approval.
- Follow `RELEASE.md` for the release checklist.
- Before release, bump `pyproject.toml` version, move relevant `CHANGELOG.md` entries from `Unreleased` into a dated version section, and verify the package from a clean build.
- PyPI publishing is handled by `.github/workflows/publish-to-pypi.yml` on published GitHub releases.
- Release tags must match `pyproject.toml` version exactly, either `<version>` or `v<version>`.
