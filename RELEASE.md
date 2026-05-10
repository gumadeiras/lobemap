# Release

lobemap publishes to PyPI through GitHub Actions Trusted Publishing. No PyPI API token secret is required once the PyPI trusted publisher is configured.

## One-Time Setup

1. Add a trusted publisher for the `lobemap` project in PyPI.
2. Use owner `gumadeiras`, repository `lobemap`, workflow `publish-to-pypi.yml`, and environment `pypi`.
3. In GitHub, create the `pypi` environment and require manual approval.

## Release Flow

1. Update `project.version` in `pyproject.toml`.
2. Update `__version__` in `__init__.py` to the same version.
3. Move the current `CHANGELOG.md` `Unreleased` notes into a new version section with the release date.
4. Add a fresh empty `Unreleased` section at the top of `CHANGELOG.md` for future changes.
5. Run `uv build --out-dir /tmp/lobemap-dist-<version> --clear`.
6. Run `uvx twine check --strict /tmp/lobemap-dist-<version>/*`.
7. Commit the version and changelog changes.
8. Create a GitHub release whose tag is the same version, with or without a leading `v`.
9. Publish the release.
10. Approve the `pypi` deployment.

## Changelog Rules

- Every release must update `CHANGELOG.md` before the release tag is created.
- `CHANGELOG.md` must always keep an `Unreleased` section at the top for future entries.
- New user-facing changes should be added to `Unreleased` as they land.
- Use user-facing language whenever possible. Describe what changed for people using lobemap, not repository maintenance.
- Use these sections when they apply: `Features`, `Fixes`, and `Changes`.
- Omit empty sections.
- Do not include release chores unless the change affects how users install, publish, or use lobemap.

## Manual Fallback

Use the local PyPI API token only when Trusted Publishing is not available and a release must go out immediately:

```bash
export TWINE_USERNAME=__token__
export TWINE_PASSWORD="$(op read 'op://Personal/PyPI API/password')"
uvx twine upload --non-interactive /tmp/lobemap-dist-<version>/*
```

The release workflow checks that the tag matches `pyproject.toml`, builds the wheel and source distribution, checks package metadata, and publishes to PyPI after the `pypi` environment approval.
