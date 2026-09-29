"""Downloaded sources are checked against the digest their recipe records.

They were not checked at all: whatever a URL or the build cache held was
built into an asset. A download that does not match is now discarded, and
one with no digest recorded is used but reported as not verified.
"""

from __future__ import annotations

import hashlib

import pytest

from lobemap.build import Recipe, load_recipes, resolve_source


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


@pytest.fixture
def server(tmp_path):
    root = tmp_path / "server"
    root.mkdir()
    (root / "a.zip").write_bytes(b"the published archive")
    (root / "0.shard").write_bytes(b"shard zero")
    (root / "1.shard").write_bytes(b"shard one")
    return root


def _recipe(server, **kw):
    return Recipe(asset="toy", pipeline="obj_archive",
                  url=(server / "a.zip").as_uri(), **kw)


def test_a_download_matching_its_digest_is_used(tmp_path, server):
    recipe = _recipe(server, sha256={"a.zip": _sha(b"the published archive")})
    got = resolve_source(recipe, tmp_path, tmp_path / "cache")
    assert got.read_bytes() == b"the published archive"


def test_a_download_that_does_not_match_is_discarded(tmp_path, server):
    recipe = _recipe(server, sha256={"a.zip": _sha(b"something else")})
    with pytest.raises(ValueError, match="sha256"):
        resolve_source(recipe, tmp_path, tmp_path / "cache")
    assert sorted(p.name for p in (tmp_path / "cache").iterdir()) == []


def test_a_cached_copy_that_fails_its_digest_is_fetched_again(tmp_path, server):
    cache = tmp_path / "cache"
    cache.mkdir()
    (cache / "a.zip").write_bytes(b"tampered")
    recipe = _recipe(server, sha256={"a.zip": _sha(b"the published archive")})
    assert resolve_source(recipe, tmp_path, cache).read_bytes() == \
        b"the published archive"


def test_a_download_with_no_digest_is_reported_unverified(tmp_path, server):
    said = []
    resolve_source(_recipe(server), tmp_path, tmp_path / "cache", progress=said.append)
    assert "not verified: no sha256 recorded for a.zip" in said


def test_every_file_of_a_multi_file_source_is_checked(tmp_path, server):
    recipe = Recipe(asset="toy", pipeline="virtual_stain",
                    urls=[(server / "0.shard").as_uri(), (server / "1.shard").as_uri()],
                    sha256={"0.shard": _sha(b"shard zero"), "1.shard": _sha(b"wrong")})
    with pytest.raises(ValueError, match="1.shard"):
        resolve_source(recipe, tmp_path, tmp_path / "cache")
    assert [p.name for p in (tmp_path / "cache" / "toy").iterdir()] == ["0.shard"]


def test_a_digest_for_a_file_the_recipe_does_not_download_is_rejected(tmp_path):
    (tmp_path / "recipes.toml").write_text(
        '[toy]\npipeline = "obj_archive"\nurl = "https://example.invalid/a.zip"\n'
        '[toy.sha256]\n"a.zp" = "00"\n', encoding="utf-8")
    with pytest.raises(ValueError, match="a.zp"):
        load_recipes(tmp_path)


def test_the_shipped_recipes_load():
    from pathlib import Path

    recipes = load_recipes(Path(__file__).resolve().parents[1] / "registry")
    assert "schlegel2021_s11_glomeruli" in recipes
