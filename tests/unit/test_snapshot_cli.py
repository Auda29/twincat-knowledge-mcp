from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from pathlib import Path

import pytest

from twincat_knowledge.cli import main
from twincat_knowledge.config import ConfigError, load_snapshot_settings
from twincat_knowledge.corpus.manifest import CorpusManifest, InventoryBalance
from twincat_knowledge.corpus.topic_package import build_topic_package
from twincat_knowledge.domain.identity import canonical_topic_id
from twincat_knowledge.domain.models import EntityCounts, SourceSnapshot
from twincat_knowledge.domain.provenance import SourceReference
from twincat_knowledge.domain.topics import Topic


def _package(root: Path, name: str) -> tuple[Path, str, str]:
    source = SourceSnapshot(
        source_id="synthetic-source",
        snapshot_id=f"source-{name}",
        imported_at=datetime(2026, 1, 1, tzinfo=UTC),
        language="en",
        content_hash="a" * 64,
        rights_reference="synthetic-test",
        parser_version="1.0",
    )
    manifest = CorpusManifest(
        package_schema_version="1.0",
        snapshot_id=f"package-{name}",
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
        id=canonical_topic_id("synthetic-source", source.snapshot_id, "en", name),
        title=f"Synthetic {name}",
        original_topic_id=name,
        library="synthetic",
        language="en",
        source=SourceReference(
            source_id=source.source_id,
            snapshot_id=source.snapshot_id,
            topic_id=name,
            language="en",
            title=f"Synthetic {name}",
            locator=name,
            content_hash="b" * 64,
        ),
    )
    built = build_topic_package(root / f"package-{name}", manifest, [topic])
    return built.path, built.manifest_sha256, manifest.snapshot_id


def _activate_args(
    package: Path, pin: str, state: Path, cache: Path, *extra: str
) -> list[str]:
    return [
        "corpus",
        "activate",
        str(package),
        "--expected-manifest-sha256",
        pin,
        "--state-dir",
        str(state),
        "--cache-dir",
        str(cache),
        *extra,
    ]


def test_public_cli_switches_snapshots_lists_state_and_rolls_back(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    state, cache = tmp_path / "state", tmp_path / "cache"
    state.mkdir()
    cache.mkdir()
    package_a, pin_a, snapshot_a = _package(tmp_path, "a")
    package_b, pin_b, snapshot_b = _package(tmp_path, "b")

    assert main(_activate_args(package_a, pin_a, state, cache, "--json")) == 0
    assert json.loads(capsys.readouterr().out)["active"]["snapshot_id"] == snapshot_a
    assert main(_activate_args(package_b, pin_b, state, cache, "--json")) == 0
    second = json.loads(capsys.readouterr().out)
    assert second["active"]["snapshot_id"] == snapshot_b
    assert second["previous"]["snapshot_id"] == snapshot_a

    assert main(["corpus", "list", "--state-dir", str(state), "--json"]) == 0
    listed = json.loads(capsys.readouterr().out)
    assert listed["status"] == "not_ready"
    assert listed["active"]["snapshot_id"] == snapshot_b
    assert listed["previous"]["snapshot_id"] == snapshot_a
    assert str(tmp_path) not in json.dumps(listed)

    assert (
        main(
            [
                "corpus",
                "rollback",
                "--state-dir",
                str(state),
                "--cache-dir",
                str(cache),
                "--json",
            ]
        )
        == 0
    )
    rolled = json.loads(capsys.readouterr().out)
    assert rolled["active"]["snapshot_id"] == snapshot_a

    assert main(["corpus", "list", "--state-dir", str(state)]) == 0
    text = capsys.readouterr().out
    assert "Snapshot state: not_ready" in text
    assert "state-only/unverified" in text


def test_list_missing_selection_is_scoped_not_available(tmp_path: Path, capsys) -> None:
    state = tmp_path / "state"
    state.mkdir()

    assert main(["corpus", "list", "--state-dir", str(state), "--json"]) == 0
    report = json.loads(capsys.readouterr().out)
    assert report["status"] == "not_available"
    assert report["scope"] == "selected_snapshot_state"
    assert report["active"] is None
    assert "ready" not in report["limitations"][0].lower()


def test_snapshot_operation_failures_are_fixed_and_do_not_leak_paths(
    tmp_path: Path, capsys
) -> None:
    state, cache = tmp_path / "state", tmp_path / "cache"
    state.mkdir()
    cache.mkdir()
    package, pin, _ = _package(tmp_path, "a")

    assert main(_activate_args(package, "0" * 64, state, cache, "--json")) == 1
    output = capsys.readouterr()
    report = json.loads(output.out)
    assert report["status"] == "error"
    assert "re-read state before retrying" in report["message"]
    assert str(tmp_path) not in output.out + output.err
    assert output.err == ""


def test_snapshot_config_priority_and_config_relative_paths(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    config_dir = tmp_path / "operator"
    config_dir.mkdir()
    (config_dir / "state").mkdir()
    (config_dir / "cache").mkdir()
    config = config_dir / "config.toml"
    config.write_text('[paths]\nstate = "state"\ncache = "cache"\n', encoding="utf-8")

    settings = load_snapshot_settings(config_path=config)
    assert settings.state_dir == (config_dir / "state").resolve()
    assert settings.cache_dir == (config_dir / "cache").resolve()

    monkeypatch.setenv("TCK_STATE_DIR", "env-state")
    monkeypatch.setenv("TCK_CACHE_DIR", "env-cache")
    settings = load_snapshot_settings(config_path=config)
    assert settings.state_dir == (Path.cwd() / "env-state").resolve()
    assert settings.cache_dir == (Path.cwd() / "env-cache").resolve()
    settings = load_snapshot_settings(
        config_path=config,
        state_dir=tmp_path / "flag-state",
        cache_dir=tmp_path / "flag-cache",
    )
    assert settings.state_dir == (tmp_path / "flag-state").resolve()
    settings = load_snapshot_settings(
        state_dir=tmp_path / "flag-state",
        cache_dir=tmp_path / "flag-cache",
        environ={"TCK_STATE_DIR": "\x00ignored", "TCK_CACHE_DIR": "\x00ignored"},
    )
    assert settings.cache_dir == (tmp_path / "flag-cache").resolve()


def test_snapshot_config_is_required_only_for_missing_settings(tmp_path: Path) -> None:
    with pytest.raises(ConfigError):
        load_snapshot_settings()
    malformed = tmp_path / "bad.toml"
    malformed.write_text("[paths\n", encoding="utf-8")
    with pytest.raises(ConfigError):
        load_snapshot_settings(
            config_path=malformed,
            state_dir=tmp_path / "state",
            cache_dir=tmp_path / "cache",
        )


def test_list_keeps_state_only_status_when_selected_package_disappears(
    tmp_path: Path, capsys
) -> None:
    state, cache = tmp_path / "state", tmp_path / "cache"
    state.mkdir()
    cache.mkdir()
    package, pin, _ = _package(tmp_path, "selected")
    assert main(_activate_args(package, pin, state, cache, "--json")) == 0
    capsys.readouterr()
    for child in package.iterdir():
        child.unlink()
    package.rmdir()

    assert main(["corpus", "list", "--state-dir", str(state), "--json"]) == 0
    report = json.loads(capsys.readouterr().out)
    assert report["status"] == "not_ready"
    assert report["active"]["availability"] == "state_only_unverified"


def test_mutation_requires_exact_state_readback(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys
) -> None:
    from twincat_knowledge.corpus import topic_snapshot

    state, cache = tmp_path / "state", tmp_path / "cache"
    state.mkdir()
    cache.mkdir()
    package_a, pin_a, _ = _package(tmp_path, "readback-a")
    package_b, pin_b, _ = _package(tmp_path, "readback-b")
    assert main(_activate_args(package_a, pin_a, state, cache)) == 0
    capsys.readouterr()
    real_activate = topic_snapshot.activate_snapshot

    def returns_old_state(*args, **kwargs):
        real_activate(*args, **kwargs)
        return topic_snapshot.read_snapshot_state(state).model_copy(
            update={"active": topic_snapshot.read_snapshot_state(state).previous}
        )

    monkeypatch.setattr(topic_snapshot, "activate_snapshot", returns_old_state)
    assert main(_activate_args(package_b, pin_b, state, cache, "--json")) == 1
    output = capsys.readouterr()
    assert json.loads(output.out)["status"] == "error"
    assert "Snapshot state" not in output.out
    assert "re-read state before retrying" in output.out


def test_cancellation_is_not_converted_to_operation_error(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from twincat_knowledge.corpus import topic_snapshot

    class Cancelled(BaseException):
        pass

    state, cache = tmp_path / "state", tmp_path / "cache"
    state.mkdir()
    cache.mkdir()
    package, pin, _ = _package(tmp_path, "cancel")

    def cancel(*args, **kwargs):
        raise Cancelled

    monkeypatch.setattr(topic_snapshot, "activate_snapshot", cancel)
    with pytest.raises(Cancelled):
        main(_activate_args(package, pin, state, cache))


def test_manifest_pin_is_computed_only_for_fixture_setup(tmp_path: Path) -> None:
    package, pin, _ = _package(tmp_path, "pin")
    assert pin == hashlib.sha256((package / "manifest.json").read_bytes()).hexdigest()
