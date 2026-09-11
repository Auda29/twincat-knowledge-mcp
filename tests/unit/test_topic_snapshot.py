from __future__ import annotations

import json
import os
import stat
from datetime import UTC, datetime
from pathlib import Path

import pytest

import twincat_knowledge.corpus.topic_snapshot as snapshot_module
from twincat_knowledge.corpus.manifest import CorpusManifest, InventoryBalance
from twincat_knowledge.corpus.topic_package import build_topic_package
from twincat_knowledge.corpus.topic_snapshot import (
    MAX_STATE_BYTES,
    SnapshotBusy,
    SnapshotError,
    SnapshotNotFound,
    SnapshotReference,
    SnapshotState,
    activate_snapshot,
    load_active_snapshot,
    read_snapshot_state,
    rollback_snapshot,
)
from twincat_knowledge.domain.identity import canonical_topic_id
from twincat_knowledge.domain.models import EntityCounts, SourceSnapshot
from twincat_knowledge.domain.provenance import SourceReference
from twincat_knowledge.domain.topics import Topic


def _package(root: Path, name: str) -> tuple[Path, str, str]:
    source_snapshot = f"source-{name}"
    snapshot_id = f"package-{name}"
    source = SourceSnapshot(
        source_id="synthetic-source",
        snapshot_id=source_snapshot,
        imported_at=datetime(2026, 1, 1, tzinfo=UTC),
        language="en",
        content_hash="a" * 64,
        rights_reference="synthetic-test",
        parser_version="1.0",
    )
    manifest = CorpusManifest(
        package_schema_version="1.0",
        snapshot_id=snapshot_id,
        created_at=datetime(2026, 1, 1, tzinfo=UTC),
        sources=(source,),
        inventory=InventoryBalance(
            documents_total=1,
            documents_imported=1,
            documents_skipped=0,
            documents_failed=0,
        ),
        entity_counts=EntityCounts(topics=1),
    )
    topic = Topic(
        id=canonical_topic_id(
            source.source_id, source.snapshot_id, "en", f"topics/{name}"
        ),
        title=f"Synthetic {name}",
        original_topic_id=f"original-{name}",
        library="synthetic",
        language="en",
        source=SourceReference(
            source_id=source.source_id,
            snapshot_id=source.snapshot_id,
            topic_id=f"original-{name}",
            language="en",
            title=f"Synthetic {name}",
            locator=f"topics/{name}",
            content_hash="b" * 64,
        ),
    )
    result = build_topic_package(root / f"package-{name}", manifest, [topic])
    return result.path, result.manifest_sha256, snapshot_id


def test_activation_switches_inflight_and_rollback_generations(tmp_path: Path) -> None:
    state_dir = tmp_path / "state"
    cache_dir = tmp_path / "cache"
    state_dir.mkdir()
    cache_dir.mkdir()
    package_a, pin_a, snapshot_a = _package(tmp_path, "a")
    package_b, pin_b, snapshot_b = _package(tmp_path, "b")

    active_a = activate_snapshot(
        state_dir, package_a, expected_manifest_sha256=pin_a, cache_dir=cache_dir
    )
    held_a = load_active_snapshot(state_dir, cache_dir=cache_dir)
    active_b = activate_snapshot(
        state_dir, package_b, expected_manifest_sha256=pin_b, cache_dir=cache_dir
    )

    assert active_a.active.snapshot_id == snapshot_a
    assert active_b.active.snapshot_id == snapshot_b
    assert held_a.manifest.corpus_manifest.snapshot_id == snapshot_a
    held_a.close()

    current = load_active_snapshot(state_dir, cache_dir=cache_dir)
    assert current.manifest.corpus_manifest.snapshot_id == snapshot_b
    current.close()

    rolled_back = rollback_snapshot(state_dir, cache_dir=cache_dir)
    assert rolled_back.active.snapshot_id == snapshot_a
    restored = load_active_snapshot(state_dir, cache_dir=cache_dir)
    assert restored.manifest.corpus_manifest.snapshot_id == snapshot_a
    restored.close()


def test_first_activation_restart_and_identical_noop_preserve_previous(
    tmp_path: Path,
) -> None:
    state_dir = tmp_path / "state"
    cache_dir = tmp_path / "cache"
    state_dir.mkdir()
    cache_dir.mkdir()
    package_a, pin_a, snapshot_a = _package(tmp_path, "a")
    package_b, pin_b, snapshot_b = _package(tmp_path, "b")

    first = activate_snapshot(
        state_dir, package_a, expected_manifest_sha256=pin_a, cache_dir=cache_dir
    )
    assert first.format_version == "1.0"
    assert first.active.snapshot_id == snapshot_a
    assert first.previous is None
    activate_snapshot(
        state_dir, package_b, expected_manifest_sha256=pin_b, cache_dir=cache_dir
    )
    before = (state_dir / "active.json").read_bytes()
    repeated = activate_snapshot(
        state_dir, package_b, expected_manifest_sha256=pin_b, cache_dir=cache_dir
    )

    assert repeated.previous is not None
    assert repeated.previous.snapshot_id == snapshot_a
    assert (state_dir / "active.json").read_bytes() == before
    restarted = read_snapshot_state(state_dir)
    assert restarted.active.snapshot_id == snapshot_b
    assert restarted.previous == repeated.previous


def test_invalid_candidate_and_bad_pin_leave_active_bytes_unchanged(
    tmp_path: Path,
) -> None:
    state_dir = tmp_path / "state"
    cache_dir = tmp_path / "cache"
    state_dir.mkdir()
    cache_dir.mkdir()
    package_a, pin_a, _ = _package(tmp_path, "a")
    package_b, pin_b, _ = _package(tmp_path, "b")
    activate_snapshot(
        state_dir, package_a, expected_manifest_sha256=pin_a, cache_dir=cache_dir
    )
    before = (state_dir / "active.json").read_bytes()
    (package_b / "topics.jsonl").write_bytes(b"not-json\n")

    with pytest.raises(SnapshotError):
        activate_snapshot(
            state_dir, package_b, expected_manifest_sha256=pin_b, cache_dir=cache_dir
        )
    with pytest.raises(SnapshotError):
        activate_snapshot(
            state_dir,
            package_b,
            expected_manifest_sha256="A" * 64,
            cache_dir=cache_dir,
        )
    assert (state_dir / "active.json").read_bytes() == before
    assert read_snapshot_state(state_dir).active.snapshot_id == "package-a"


def test_empty_startup_and_rollback_without_previous_are_typed(
    tmp_path: Path,
) -> None:
    state_dir = tmp_path / "state"
    cache_dir = tmp_path / "cache"
    state_dir.mkdir()
    cache_dir.mkdir()
    with pytest.raises(SnapshotNotFound):
        read_snapshot_state(state_dir)
    with pytest.raises(SnapshotNotFound):
        load_active_snapshot(state_dir, cache_dir=cache_dir)
    with pytest.raises(SnapshotNotFound):
        rollback_snapshot(state_dir, cache_dir=cache_dir)

    package_a, pin_a, _ = _package(tmp_path, "a")
    activate_snapshot(
        state_dir, package_a, expected_manifest_sha256=pin_a, cache_dir=cache_dir
    )
    with pytest.raises(SnapshotError):
        rollback_snapshot(state_dir, cache_dir=cache_dir)


def test_malformed_duplicate_oversized_and_unsupported_state_do_not_overwrite(
    tmp_path: Path,
) -> None:
    state_dir = tmp_path / "state"
    cache_dir = tmp_path / "cache"
    state_dir.mkdir()
    cache_dir.mkdir()
    package_a, pin_a, _ = _package(tmp_path, "a")
    activate_snapshot(
        state_dir, package_a, expected_manifest_sha256=pin_a, cache_dir=cache_dir
    )
    old = (state_dir / "active.json").read_bytes()

    for payload in (
        b'{"active": {}, "active": {}}',
        b"{" + b"x" * (MAX_STATE_BYTES + 1) + b"}",
        b'{"format_version":"9.9","active":{},"previous":null}',
        b"not-json",
    ):
        (state_dir / "active.json").write_bytes(payload)
        with pytest.raises(SnapshotError):
            read_snapshot_state(state_dir)
        (state_dir / "active.json").write_bytes(old)

    # A malformed existing pointer is never replaced by activation.
    (state_dir / "active.json").write_bytes(b"{}")
    before = b"{}"
    package_b, pin_b, _ = _package(tmp_path, "b")
    with pytest.raises(SnapshotError):
        activate_snapshot(
            state_dir, package_b, expected_manifest_sha256=pin_b, cache_dir=cache_dir
        )
    assert (state_dir / "active.json").read_bytes() == before


def test_state_models_are_frozen_strict_and_revalidate_constructed_values(
    tmp_path: Path,
) -> None:
    package = (tmp_path / "package").resolve()
    reference = SnapshotReference(
        package_path=package,
        manifest_sha256="a" * 64,
        snapshot_id="snapshot-a",
    )
    with pytest.raises((TypeError, ValueError)):
        reference.snapshot_id = "changed"  # type: ignore[misc]
    bypassed = SnapshotState.model_construct(
        format_version="bad", active=reference, previous=None
    )
    with pytest.raises(SnapshotError):
        # The public read path applies model validation, not just construction.
        (tmp_path / "state").mkdir()
        (tmp_path / "state" / "active.json").write_text(
            json.dumps(bypassed.model_dump(mode="json")), encoding="utf-8"
        )
        read_snapshot_state(tmp_path / "state")


def test_symlink_and_fifo_state_targets_are_rejected_without_cleanup(
    tmp_path: Path,
) -> None:
    state_dir = tmp_path / "state"
    cache_dir = tmp_path / "cache"
    state_dir.mkdir()
    cache_dir.mkdir()
    target = state_dir / "active.json"
    target.symlink_to(tmp_path / "elsewhere")
    with pytest.raises(SnapshotError):
        read_snapshot_state(state_dir)
    target.unlink()
    if hasattr(os, "mkfifo"):
        os.mkfifo(target)
        assert stat.S_ISFIFO(target.lstat().st_mode)
        with pytest.raises(SnapshotError):
            read_snapshot_state(state_dir)


def test_busy_lock_is_failfast_and_preserved(tmp_path: Path) -> None:
    state_dir = tmp_path / "state"
    cache_dir = tmp_path / "cache"
    state_dir.mkdir()
    cache_dir.mkdir()
    package_a, pin_a, _ = _package(tmp_path, "a")
    lock = state_dir / ".active.lock"
    lock.write_bytes(b"operator owns this")
    with pytest.raises(SnapshotBusy):
        activate_snapshot(
            state_dir, package_a, expected_manifest_sha256=pin_a, cache_dir=cache_dir
        )
    assert lock.read_bytes() == b"operator owns this"


def test_source_bytes_and_private_cache_are_unchanged_after_close(
    tmp_path: Path,
) -> None:
    state_dir = tmp_path / "state"
    cache_dir = tmp_path / "cache"
    state_dir.mkdir()
    cache_dir.mkdir()
    package_a, pin_a, _ = _package(tmp_path, "a")
    source_bytes = {
        path: path.read_bytes()
        for path in (
            package_a / "manifest.json",
            package_a / "topics.jsonl",
            package_a / "topics.sqlite",
        )
    }
    activate_snapshot(
        state_dir, package_a, expected_manifest_sha256=pin_a, cache_dir=cache_dir
    )
    loaded = load_active_snapshot(state_dir, cache_dir=cache_dir)
    assert any(cache_dir.iterdir())
    loaded.close()
    assert not any(cache_dir.iterdir())
    assert {path: path.read_bytes() for path in source_bytes} == source_bytes


def test_reference_snapshot_id_mismatch_is_rejected_and_loaded_cache_closes(
    tmp_path: Path,
) -> None:
    state_dir = tmp_path / "state"
    cache_dir = tmp_path / "cache"
    state_dir.mkdir()
    cache_dir.mkdir()
    package_a, pin_a, _ = _package(tmp_path, "a")
    activate_snapshot(
        state_dir, package_a, expected_manifest_sha256=pin_a, cache_dir=cache_dir
    )
    raw = json.loads((state_dir / "active.json").read_text(encoding="utf-8"))
    raw["active"]["snapshot_id"] = "different-snapshot"
    (state_dir / "active.json").write_text(json.dumps(raw), encoding="utf-8")
    with pytest.raises(SnapshotError):
        load_active_snapshot(state_dir, cache_dir=cache_dir)
    assert not any(cache_dir.iterdir())


def test_replace_failure_retains_old_pointer_and_private_temp_cleanup(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    state_dir = tmp_path / "state"
    cache_dir = tmp_path / "cache"
    state_dir.mkdir()
    cache_dir.mkdir()
    package_a, pin_a, _ = _package(tmp_path, "a")
    package_b, pin_b, _ = _package(tmp_path, "b")
    activate_snapshot(
        state_dir, package_a, expected_manifest_sha256=pin_a, cache_dir=cache_dir
    )
    before = (state_dir / "active.json").read_bytes()

    def fail_replace(source: Path, target: Path) -> None:
        del source, target
        raise OSError("synthetic replace failure")

    monkeypatch.setattr(snapshot_module.os, "replace", fail_replace)
    with pytest.raises(SnapshotError):
        activate_snapshot(
            state_dir, package_b, expected_manifest_sha256=pin_b, cache_dir=cache_dir
        )
    assert (state_dir / "active.json").read_bytes() == before
    assert not list(state_dir.glob(".active-*"))
    assert not (state_dir / ".active.lock").exists()


def test_state_fsync_failure_retains_old_pointer_and_cleans_temp(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    state_dir = tmp_path / "state"
    cache_dir = tmp_path / "cache"
    state_dir.mkdir()
    cache_dir.mkdir()
    package_a, pin_a, _ = _package(tmp_path, "a")
    package_b, pin_b, _ = _package(tmp_path, "b")
    activate_snapshot(
        state_dir, package_a, expected_manifest_sha256=pin_a, cache_dir=cache_dir
    )
    before = (state_dir / "active.json").read_bytes()
    real_fsync = snapshot_module.os.fsync
    calls = 0

    def fail_state_fsync(descriptor: int) -> None:
        nonlocal calls
        calls += 1
        if calls == 3:  # JSONL cache, SQLite cache, then state temp.
            raise OSError("synthetic fsync failure")
        real_fsync(descriptor)

    monkeypatch.setattr(snapshot_module.os, "fsync", fail_state_fsync)
    with pytest.raises(SnapshotError):
        activate_snapshot(
            state_dir, package_b, expected_manifest_sha256=pin_b, cache_dir=cache_dir
        )
    assert (state_dir / "active.json").read_bytes() == before
    assert not list(state_dir.glob(".active-*"))
    assert not (state_dir / ".active.lock").exists()


def test_candidate_cancellation_releases_only_own_lock(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    state_dir = tmp_path / "state"
    cache_dir = tmp_path / "cache"
    state_dir.mkdir()
    cache_dir.mkdir()
    package_a, pin_a, _ = _package(tmp_path, "a")

    def cancel(*args: object, **kwargs: object) -> object:
        del args, kwargs
        raise KeyboardInterrupt

    monkeypatch.setattr(snapshot_module, "load_topic_package", cancel)
    with pytest.raises(KeyboardInterrupt):
        activate_snapshot(
            state_dir, package_a, expected_manifest_sha256=pin_a, cache_dir=cache_dir
        )
    assert not (state_dir / ".active.lock").exists()
    assert not (state_dir / "active.json").exists()
    assert not list(state_dir.glob(".active-*"))


def test_state_and_cache_aliases_are_rejected(tmp_path: Path) -> None:
    real_state = tmp_path / "state"
    real_cache = tmp_path / "cache"
    real_state.mkdir()
    real_cache.mkdir()
    state_alias = tmp_path / "state-alias"
    cache_alias = tmp_path / "cache-alias"
    state_alias.symlink_to(real_state, target_is_directory=True)
    cache_alias.symlink_to(real_cache, target_is_directory=True)
    package_a, pin_a, _ = _package(tmp_path, "a")

    with pytest.raises(SnapshotError):
        activate_snapshot(
            state_alias, package_a, expected_manifest_sha256=pin_a, cache_dir=real_cache
        )
    with pytest.raises(SnapshotError):
        activate_snapshot(
            real_state, package_a, expected_manifest_sha256=pin_a, cache_dir=cache_alias
        )


@pytest.mark.parametrize("cancel", [False, True])
def test_lock_fstat_failure_releases_acquired_lock(tmp_path, monkeypatch, cancel):
    state = tmp_path / "state"
    cache = tmp_path / "cache"
    state.mkdir()
    cache.mkdir()
    package, pin, _ = _package(tmp_path, "a")
    real_open, real_fstat = os.open, os.fstat
    acquired = []

    def opening(path, *args, **kwargs):
        fd = real_open(path, *args, **kwargs)
        if Path(path) == state / ".active.lock":
            acquired.append(fd)
        return fd

    def checking(fd):
        if fd in acquired:
            if cancel:
                raise KeyboardInterrupt
            raise OSError("private-path-fstat-failure")
        return real_fstat(fd)

    monkeypatch.setattr(os, "open", opening)
    monkeypatch.setattr(os, "fstat", checking)
    try:
        with pytest.raises(KeyboardInterrupt if cancel else SnapshotError):
            activate_snapshot(
                state, package, expected_manifest_sha256=pin, cache_dir=cache
            )
        assert len(acquired) == 1
        with pytest.raises(OSError):
            real_fstat(acquired[0])
        assert list(state.iterdir()) == []
        assert list(cache.iterdir()) == []
    finally:
        for fd in acquired:
            try:
                os.close(fd)
            except OSError:
                pass


def test_pointer_replacement_before_open_reads_one_complete_generation(
    tmp_path, monkeypatch
):
    state, cache = tmp_path / "state", tmp_path / "cache"
    state.mkdir()
    cache.mkdir()
    package_a, pin_a, _ = _package(tmp_path, "a")
    package_b, pin_b, _ = _package(tmp_path, "longer-b")
    activate_snapshot(state, package_a, expected_manifest_sha256=pin_a, cache_dir=cache)
    pointer = state / "active.json"
    old_bytes = pointer.read_bytes()
    expected = activate_snapshot(
        state, package_b, expected_manifest_sha256=pin_b, cache_dir=cache
    )
    next_bytes = pointer.read_bytes()
    assert len(next_bytes) != len(old_bytes)
    replacement = state / "replacement.json"
    replacement.write_bytes(next_bytes)
    pointer.write_bytes(old_bytes)
    real_open = os.open
    replaced = []

    def opening(path, *args, **kwargs):
        if Path(path) == pointer and not replaced:
            os.replace(replacement, pointer)
            replaced.append(True)
        return real_open(path, *args, **kwargs)

    monkeypatch.setattr(os, "open", opening)
    assert read_snapshot_state(state) == expected
    assert replaced == [True]
    assert pointer.read_bytes() == next_bytes
