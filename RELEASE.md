# Release

lobemap publishes to PyPI through GitHub Actions Trusted Publishing. No PyPI API token secret is required once the PyPI trusted publisher is configured.

## One-Time Setup

1. Add a trusted publisher for the `lobemap` project in PyPI.
2. Use owner `gumadeiras`, repository `lobemap`, workflow `publish-to-pypi.yml`, and environment `pypi`.
3. In GitHub, create the `pypi` environment and require manual approval.

## Release Flow

1. Update `project.version` in `pyproject.toml`. It is the only version string: `lobemap --version` reads it from the installed package metadata.
2. If any data artifact changed, publish a data release first (see Data Releases), so the manifest in the release commit points at assets that exist.
3. Move the current `CHANGELOG.md` `Unreleased` notes into a new version section with the release date.
4. Add a fresh empty `Unreleased` section at the top of `CHANGELOG.md` for future changes.
5. Run `uv build --out-dir /tmp/lobemap-dist-<version> --clear`.
6. Run `uvx twine check --strict /tmp/lobemap-dist-<version>/*`.
7. Install the wheel into a fresh environment outside the checkout and run `lobemap --version` and `lobemap spaces` from a directory outside the checkout. A source checkout hides missing package data, so this is the only check that sees what a PyPI user gets.
8. Commit the version and changelog changes.
9. Create a GitHub release whose tag is the same version, with or without a leading `v`.
10. Publish the release.
11. Approve the `pypi` deployment.

## Data Releases

The data artifacts are neither tracked in git nor shipped in the wheel. They are assets of a GitHub release tagged `data-v<N>`, and `registry/manifest.toml` records that release as `base_url`, plus the sha256 and size of each artifact. `lobemap fetch` downloads from `base_url` and discards anything that does not match.

1. Rebuild the changed assets with `lobemap build <asset>`; `registry/data/README.md` describes each pipeline.
2. Choose a new tag, `data-v<N+1>`. Never replace the assets of an existing data release: every earlier commit verifies against the hashes it recorded.
3. Run `lobemap manifest --base-url https://github.com/gumadeiras/lobemap/releases/download/data-v<N+1>` to record the new hashes and location.
4. Run `lobemap pack --all`. It writes the upload files to `registry/data/.pack` under the names `fetch` requests, and fails if any file does not match the manifest.
5. Create the release with the packed files: `gh release create data-v<N+1> --repo gumadeiras/lobemap --target <commit> --title data-v<N+1> --latest=false registry/data/.pack/*`. `--latest=false` keeps the package release marked as latest. The PyPI workflow skips tags that start with `data-`, but a release runs the workflow file of its tagged commit, so target a commit that has that guard.
6. Verify from an empty data directory: `LOBEMAP_DATA="$(mktemp -d)" lobemap fetch`, then `lobemap fetch --check` with the same directory.
7. Commit `registry/manifest.toml`.

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

The release workflow skips `data-` tags, checks that the tag matches `pyproject.toml`, builds the wheel and source distribution, checks package metadata, and publishes to PyPI after the `pypi` environment approval.
