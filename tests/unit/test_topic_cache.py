"""Recovery must never reclaim live readers or unrelated operator data."""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

import pytest

from twincat_knowledge.corpus import topic_cache


def _generation(root: Path, name: str = "abcdefgh") -> Path:
    directory = root / f".topic-package-load-{name}"
    directory.mkdir()
    (directory / ".owner.json").write_text(
        json.dumps({"version": 1, "pid": os.getpid()}), encoding="ascii"
    )
    (directory / "topics.jsonl").write_bytes(b"synthetic topics")
    (directory / "topics.sqlite").write_bytes(b"synthetic index")
    return directory


def test_live_process_and_unknown_status_are_preserved(tmp_path, monkeypatch):
    generation = _generation(tmp_path)
    assert topic_cache.prune_stale_topic_caches(tmp_path) == 0
    monkeypatch.setattr(topic_cache, "_process_running", lambda pid: True)
    assert topic_cache.prune_stale_topic_caches(tmp_path) == 0
    assert (generation / "topics.sqlite").read_bytes() == b"synthetic index"


def test_dead_process_partial_cache_is_collected(tmp_path, monkeypatch):
    generation = _generation(tmp_path)
    (generation / "topics.sqlite").unlink()
    monkeypatch.setattr(topic_cache, "_process_running", lambda pid: False)
    assert topic_cache.prune_stale_topic_caches(tmp_path) == 1
    assert not generation.exists()


@pytest.mark.parametrize(
    "owner", [None, "{}", '{"version":1,"pid":0}', "x" * 129, "invalid json"]
)
def test_unmarked_or_invalid_ownership_is_preserved(tmp_path, monkeypatch, owner):
    generation = _generation(tmp_path)
    marker = generation / ".owner.json"
    if owner is None:
        marker.unlink()
    else:
        marker.write_text(owner, encoding="ascii")
    monkeypatch.setattr(topic_cache, "_process_running", lambda pid: False)
    assert topic_cache.prune_stale_topic_caches(tmp_path) == 0
    assert (generation / "topics.sqlite").exists()


@pytest.mark.parametrize("foreign", ["file", "directory", "link"])
def test_unexpected_entries_and_links_are_preserved(tmp_path, monkeypatch, foreign):
    generation = _generation(tmp_path)
    if foreign == "file":
        (generation / "operator.txt").write_text("keep", encoding="ascii")
    elif foreign == "directory":
        (generation / "topics.jsonl").unlink()
        (generation / "topics.jsonl").mkdir()
    else:
        target = tmp_path / "outside"
        target.write_bytes(b"keep")
        (generation / "topics.jsonl").unlink()
        try:
            (generation / "topics.jsonl").symlink_to(target)
        except OSError:
            pytest.skip("symlink creation is unavailable")
    monkeypatch.setattr(topic_cache, "_process_running", lambda pid: False)
    assert topic_cache.prune_stale_topic_caches(tmp_path) == 0
    assert (generation / "topics.sqlite").read_bytes() == b"synthetic index"


def test_failed_unlink_keeps_marker_for_retry(tmp_path, monkeypatch):
    generation = _generation(tmp_path)
    monkeypatch.setattr(topic_cache, "_process_running", lambda pid: False)
    original = Path.unlink

    def blocked(path, *args, **kwargs):
        if path.name == "topics.sqlite":
            raise PermissionError("synthetic sharing violation")
        return original(path, *args, **kwargs)

    monkeypatch.setattr(Path, "unlink", blocked)
    assert topic_cache.prune_stale_topic_caches(tmp_path) == 0
    assert (generation / ".owner.json").exists()
    monkeypatch.setattr(Path, "unlink", original)
    assert topic_cache.prune_stale_topic_caches(tmp_path) == 1


@pytest.mark.parametrize("redirect", ["root", "generation"])
def test_redirected_directory_never_deletes_target(tmp_path, monkeypatch, redirect):
    target = tmp_path / "outside"
    target.mkdir()
    generation = _generation(target)
    cache = tmp_path / "cache"
    if redirect == "root":
        source, alias = target, cache
    else:
        cache.mkdir()
        source, alias = generation, cache / generation.name
    if sys.platform == "win32":
        import _winapi

        _winapi.CreateJunction(str(source), str(alias))
    else:
        alias.symlink_to(source, target_is_directory=True)
    monkeypatch.setattr(topic_cache, "_process_running", lambda pid: False)
    assert topic_cache.prune_stale_topic_caches(cache) == 0
    assert (generation / "topics.sqlite").read_bytes() == b"synthetic index"


def test_owner_write_failure_cleans_new_directory(tmp_path, monkeypatch):
    original = Path.open

    def blocked(path, *args, **kwargs):
        if path.name == ".owner.json":
            raise OSError("synthetic write failure")
        return original(path, *args, **kwargs)

    monkeypatch.setattr(Path, "open", blocked)
    with pytest.raises(OSError, match="write failure"):
        topic_cache.create_topic_cache(tmp_path)
    assert list(tmp_path.iterdir()) == []
