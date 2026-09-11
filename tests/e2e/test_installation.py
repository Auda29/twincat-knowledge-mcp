from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
import sys
import tomllib
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]


def _venv_python(venv: Path) -> Path:
    if os.name == "nt":
        return venv / "Scripts" / "python.exe"
    return venv / "bin" / "python"


def _venv_console_script(venv: Path, name: str) -> Path:
    candidates = (
        (venv / "Scripts" / f"{name}.exe", venv / "Scripts" / name)
        if os.name == "nt"
        else (venv / "bin" / name,)
    )
    for candidate in candidates:
        if candidate.is_file():
            return candidate
    pytest.fail(f"installed console entry point was not found: {name}")


def _console_command(python: Path, script: Path) -> list[Path]:
    # The test workspace can be mounted noexec on POSIX.  Running the
    # generated entry-point script through its venv interpreter still proves
    # the installed console entry point without depending on that mount flag.
    return [script] if os.name == "nt" else [python, script]


def _run(
    args: list[str | Path], *, cwd: Path, env: dict[str, str], timeout: float
) -> subprocess.CompletedProcess[str]:
    try:
        return subprocess.run(
            [str(arg) for arg in args],
            cwd=cwd,
            env=env,
            capture_output=True,
            text=True,
            check=False,
            timeout=timeout,
        )
    except subprocess.TimeoutExpired as exc:
        pytest.fail(f"subprocess timed out after {timeout:g}s: {args}: {exc}")


@pytest.mark.parametrize(
    "build_flags", [("--wheel",), ("--sdist",)], ids=["wheel", "sdist-wheel"]
)
def test_wheel_installs_without_source_checkout(
    tmp_path: Path, build_flags: tuple[str, ...]
) -> None:
    uv = shutil.which("uv")
    if uv is None:
        pytest.fail("uv is required for the wheel installation proof")

    dist = tmp_path / "dist"
    venv = tmp_path / "venv"
    foreign_cwd = tmp_path / "foreign-cwd"
    operator_dir = tmp_path / "operator"
    dist.mkdir()
    foreign_cwd.mkdir()
    operator_dir.mkdir()

    env = {key: value for key, value in os.environ.items() if key != "PYTHONPATH"}
    build = _run(
        [uv, "build", *build_flags, "--out-dir", dist],
        cwd=ROOT,
        env=env,
        timeout=180,
    )
    assert build.returncode == 0, build.stdout + build.stderr

    artifact_pattern = "*.whl" if build_flags == ("--wheel",) else "*.tar.gz"
    artifacts = sorted(dist.glob(artifact_pattern))
    assert len(artifacts) == 1

    create_venv = _run(
        [uv, "venv", "--python", sys.executable, venv],
        cwd=tmp_path,
        env=env,
        timeout=120,
    )
    assert create_venv.returncode == 0, create_venv.stdout + create_venv.stderr

    python = _venv_python(venv)
    install = _run(
        [uv, "pip", "install", "--no-cache", "--python", python, artifacts[0]],
        cwd=foreign_cwd,
        env=env,
        timeout=180,
    )
    assert install.returncode == 0, install.stdout + install.stderr
    assert python.is_file()

    artifact_origin = _run(
        [
            python,
            "-I",
            "-c",
            "import importlib.metadata, json; "
            "d = importlib.metadata.distribution('twincat-knowledge'); "
            "print(json.loads(d.read_text('direct_url.json'))['url'])",
        ],
        cwd=foreign_cwd,
        env=env,
        timeout=30,
    )
    assert artifact_origin.returncode == 0, artifact_origin.stderr
    expected_suffix = ".whl" if build_flags == ("--wheel",) else ".tar.gz"
    assert artifact_origin.stdout.strip().endswith(expected_suffix)

    model_import = _run(
        [
            python,
            "-I",
            "-c",
            "from twincat_knowledge.corpus import CorpusManifest; "
            "from twincat_knowledge.domain import SourceReference; "
            "r = SourceReference(source_id='synthetic', snapshot_id='synthetic', "
            "language='en', canonical_url=None, locator='topic.html', "
            "content_hash='a'*64); "
            "assert SourceReference.model_validate_json(r.model_dump_json()) == r",
        ],
        cwd=foreign_cwd,
        env=env,
        timeout=30,
    )
    assert model_import.returncode == 0, model_import.stdout + model_import.stderr

    console_script = _venv_console_script(venv, "twincat-knowledge")
    version = _run(
        [*_console_command(python, console_script), "--version"],
        cwd=foreign_cwd,
        env=env,
        timeout=30,
    )
    assert version.returncode == 0, version.stderr
    assert version.stdout.strip() == "twincat-knowledge 0.1.0"
    assert version.stderr == ""

    # Exercise the new reader through the installed console entry point, not checkout.
    from zipfile import ZipFile

    source = operator_dir / "synthetic.mshc"
    with ZipFile(source, "w") as archive:
        archive.writestr(
            "sample/1033/1.html",
            "<html><head><title>Synthetic</title></head><body><article>"
            "<pre>A<br/> B</pre></article></body></html>",
        )
    inspection = _run(
        [
            *_console_command(python, console_script),
            "inspect-infosys",
            "--source",
            source,
            "--library",
            "sample",
            "--language",
            "en",
            "--title",
            "Synthetic",
        ],
        cwd=foreign_cwd,
        env=env,
        timeout=30,
    )
    assert inspection.returncode == 0, inspection.stderr
    inspected = json.loads(inspection.stdout)
    assert inspected["total"] == 1
    assert inspected["topics"][0]["section_counts"]["code"] == 1
    assert inspected["topics"][0]["locator"] == "sample/1033/1.html"
    assert str(operator_dir) not in inspection.stdout
    assert inspection.stderr == ""

    normalization = _run(
        [
            python,
            "-I",
            "-c",
            "import hashlib, sys; "
            "from datetime import datetime, timezone; "
            "from pathlib import Path; "
            "import twincat_knowledge.ingest.normalize as module; "
            "from twincat_knowledge.ingest.infosys import read_infosys; "
            "from twincat_knowledge.domain.models import SourceSnapshot; "
            "from twincat_knowledge.domain.topics import Topic; "
            "assert Path(module.__file__).is_relative_to(Path(sys.prefix)); "
            "p = Path(sys.argv[1]); "
            "snapshot = SourceSnapshot(source_id='fixture', snapshot_id='v1', "
            "imported_at=datetime(2026, 1, 1, tzinfo=timezone.utc), "
            "language='en', content_hash=hashlib.sha256(p.read_bytes()).hexdigest(), "
            "rights_reference='original synthetic test fixture', "
            "parser_version='test'); "
            "raw = read_infosys(p, source_id='fixture', snapshot_id='v1'); "
            "topics = module.normalize_infosys(raw, (snapshot,)); "
            "assert len(topics) == 1; "
            "t = topics[0]; "
            "assert t.title == 'Synthetic'; "
            "assert t.source.locator == 'sample/1033/1.html'; "
            "assert t.source.content_hash == raw[0].source.content_hash; "
            "assert t.sections[0].code == raw[0].sections[0].code; "
            "assert t.sections[0].source.section_id == t.sections[0].id; "
            "assert t.sections[0].source.snapshot_id == 'v1'; "
            "assert Topic.model_validate_json(t.model_dump_json()) == t; "
            "assert snapshot.applicability == 'unknown'; "
            "import twincat_knowledge.corpus.topic_export as export; "
            "assert Path(export.__file__).is_relative_to(Path(sys.prefix)); "
            "jsonl = p.with_name('installed-topics.jsonl'); "
            "summary = export.write_topic_export(jsonl, topics); "
            "assert summary.count == len(topics); "
            "assert summary.bytes == jsonl.stat().st_size; "
            "assert summary.sha256 == hashlib.sha256(jsonl.read_bytes()).hexdigest(); "
            "reloaded = export.read_topic_export(jsonl); "
            "assert reloaded == topics; "
            "topics = reloaded; "
            "import twincat_knowledge.corpus.topic_validation as validation; "
            "import twincat_knowledge.domain.identity as identity; "
            "from twincat_knowledge.corpus.manifest import "
            "CorpusManifest, InventoryBalance; "
            "from twincat_knowledge.domain.models import EntityCounts; "
            "assert Path(validation.__file__).is_relative_to(Path(sys.prefix)); "
            "assert Path(identity.__file__).is_relative_to(Path(sys.prefix)); "
            "manifest = CorpusManifest(package_schema_version='1.0', "
            "snapshot_id='package-generation', created_at=snapshot.imported_at, "
            "sources=(snapshot,), inventory=InventoryBalance(documents_total=1, "
            "documents_imported=1, documents_skipped=0, documents_failed=0), "
            "entity_counts=EntityCounts(topics=1, sections=len(t.sections))); "
            "validated = validation.validate_topic_corpus(manifest, iter(topics)); "
            "assert validated.topic_count == 1; "
            "assert validated.section_count == len(t.sections); "
            "assert dict(validated.language_counts) == {'en': 1}; "
            "import twincat_knowledge.corpus.topic_package as packages; "
            "assert Path(packages.__file__).is_relative_to(Path(sys.prefix)); "
            "built = packages.build_topic_package("
            "p.with_name('installed-package'), manifest, iter(topics)); "
            "descriptor_bytes = built.manifest_path.read_bytes(); "
            "assert len(descriptor_bytes) == built.manifest_bytes; "
            "assert hashlib.sha256(descriptor_bytes).hexdigest() "
            "== built.manifest_sha256; "
            "assert packages.TopicPackageManifest.model_validate_json("
            "descriptor_bytes) == built.manifest; "
            "assert all((built.path / f.filename).stat().st_size == f.bytes "
            "and hashlib.sha256((built.path / f.filename).read_bytes()).hexdigest() "
            "== f.sha256 for f in built.manifest.files); "
            "assert export.read_topic_export(built.path / 'topics.jsonl') == topics; "
            "import twincat_knowledge.corpus.topic_package_load as loader; "
            "assert Path(loader.__file__).is_relative_to(Path(sys.prefix)); "
            "cache = p.with_name('installed-package-cache'); cache.mkdir(); "
            "loaded = loader.load_topic_package(built.path, "
            "expected_manifest_sha256=built.manifest_sha256, cache_dir=cache); "
            "assert loaded.manifest == built.manifest; "
            "assert loaded.summary.topic_count == 1; "
            "assert loaded.index.get_topic(t.id) == t; "
            "assert loaded.index.search('Synthetic', language='en', "
            "library='sample', source_snapshot_id='v1') == (t,); "
            "import json; "
            "import twincat_knowledge.services.topic_queries as queries; "
            "import twincat_knowledge.services.query_contracts as contracts; "
            "import twincat_knowledge.services.query_cursor as cursors; "
            "assert all(Path(m.__file__).is_relative_to(Path(sys.prefix)) "
            "for m in (queries, contracts, cursors)); "
            "service = queries.TopicQueryService(loaded); "
            "found = service.search(contracts.SearchInput(query='Synthetic')); "
            "assert found.status == 'ok' and len(found.data.items) == 1; "
            "assert found.data.items[0].id == t.id; "
            "assert found.sources[0].applicability == 'unknown'; "
            "detail = service.get_topic(contracts.GetTopicInput(topic_id=t.id)); "
            "assert detail.status == 'ok' and detail.data.complete; "
            "assert detail.data.sections[0].text == t.sections[0].text; "
            "status = service.get_corpus_status(contracts.CorpusStatusInput()); "
            "assert status.status == 'ok' and status.data.topic_count == 1; "
            "assert status.data.package_snapshot_id == 'package-generation'; "
            "assert service.search(contracts.SearchInput(query='Synthetic', "
            "filters=contracts.QueryFilters(snapshot_id='v1'))).status "
            "== 'not_found'; "
            "invalid = service.get_topic(contracts.GetTopicInput.model_construct("
            "topic_id=t.id, limit=0)); assert invalid.status == 'error'; "
            "assert queries.TopicQueryService(None).get_corpus_status("
            "contracts.CorpusStatusInput()).status == 'not_available'; "
            "assert all(len(json.dumps(r.model_dump(mode='json'), "
            "ensure_ascii=True, sort_keys=True, "
            "separators=(',', ':')).encode('ascii')) "
            "<= queries.MAX_DOMAIN_RESPONSE_BYTES for r in (found, detail, status)); "
            "loaded.close(); loaded.close(); "
            "assert service.search(contracts.SearchInput(query='Synthetic'))"
            ".status == 'error'; "
            "assert list(cache.iterdir()) == []; "
            "assert all(hashlib.sha256((built.path / f.filename).read_bytes())"
            ".hexdigest() == f.sha256 for f in built.manifest.files); "
            "assert built.manifest_path.read_bytes() == descriptor_bytes; "
            "import twincat_knowledge.corpus.topic_snapshot as snapshots; "
            "assert Path(snapshots.__file__).is_relative_to(Path(sys.prefix)); "
            "state = p.with_name('installed-snapshot-state'); state.mkdir(); "
            "snapshots.activate_snapshot(state, built.path, "
            "expected_manifest_sha256=built.manifest_sha256, cache_dir=cache); "
            "held = snapshots.load_active_snapshot(state, cache_dir=cache); "
            "snapshot_b = snapshot.model_copy(update={'snapshot_id': 'v2'}); "
            "raw_b = read_infosys(p, source_id='fixture', snapshot_id='v2'); "
            "topics_b = module.normalize_infosys(raw_b, (snapshot_b,)); "
            "manifest_b = manifest.model_copy(update={"
            "'snapshot_id': 'package-next', 'sources': (snapshot_b,)}); "
            "built_b = packages.build_topic_package("
            "p.with_name('installed-package-next'), manifest_b, iter(topics_b)); "
            "snapshots.activate_snapshot(state, built_b.path, "
            "expected_manifest_sha256=built_b.manifest_sha256, cache_dir=cache); "
            "current = snapshots.load_active_snapshot(state, cache_dir=cache); "
            "assert current.index.get_topic(topics_b[0].id) == topics_b[0]; "
            "assert current.index.get_topic(t.id) is None; "
            "assert held.index.get_topic(t.id) == t; "
            "assert held.index.get_topic(topics_b[0].id) is None; "
            "current.close(); "
            "snapshots.rollback_snapshot(state, cache_dir=cache); "
            "restored = snapshots.load_active_snapshot(state, cache_dir=cache); "
            "assert restored.index.get_topic(t.id) == t; restored.close(); "
            "held.close(); assert list(cache.iterdir()) == []; "
            "assert snapshots.read_snapshot_state(state).active.manifest_sha256 "
            "== built.manifest_sha256; "
            "assert built.manifest_path.read_bytes() == descriptor_bytes; "
            "assert all(hashlib.sha256((pkg.path / f.filename).read_bytes())"
            ".hexdigest() == f.sha256 for pkg in (built, built_b) "
            "for f in pkg.manifest.files); "
            "import twincat_knowledge.corpus.topic_index as storage; "
            "assert Path(storage.__file__).is_relative_to(Path(sys.prefix)); "
            "db = p.with_name('installed-topic-index.sqlite'); "
            "assert storage.create_topic_index(db, topics) == 1; "
            "before = hashlib.sha256(db.read_bytes()).hexdigest(); "
            "index = storage.TopicIndex(db); "
            "assert index.get_topic(t.id) == t; "
            "assert index.search('Synthetic', language='en', "
            "library='sample', source_snapshot_id='v1') == (t,); "
            "index.__exit__(None, None, None); "
            "assert hashlib.sha256(db.read_bytes()).hexdigest() == before; "
            "print('installed normalization verified')",
            source,
        ],
        cwd=foreign_cwd,
        env=env,
        timeout=30,
    )
    assert normalization.returncode == 0, normalization.stderr
    assert normalization.stdout.strip() == "installed normalization verified"
    assert normalization.stderr == ""

    package = operator_dir / "installed-package"
    cache = operator_dir / "installed-package-cache"
    before = {p.name: p.read_bytes() for p in package.iterdir()}
    fingerprint = hashlib.sha256(before["manifest.json"]).hexdigest()
    validation_command = [
        *_console_command(python, console_script),
        "corpus",
        "validate",
        package,
        "--expected-manifest-sha256",
        fingerprint,
        "--cache-dir",
        cache,
        "--json",
    ]
    validation = _run(validation_command, cwd=foreign_cwd, env=env, timeout=30)
    assert validation.returncode == 0, validation.stderr
    report = json.loads(validation.stdout)
    assert report["schema_version"] == "corpus-validation-1"
    assert report["status"] == "valid"
    assert report["scope"] == "topic_package"
    assert report["manifest_sha256"] == fingerprint
    assert report["topic_count"] == 1
    assert report["section_count"] == 1
    assert report["language_counts"] == {"en": 1}
    assert report["limitations"]
    assert str(operator_dir) not in validation.stdout
    assert "Synthetic" not in validation.stdout
    assert validation.stderr == ""
    assert list(cache.iterdir()) == []
    assert {p.name: p.read_bytes() for p in package.iterdir()} == before

    human_validation = _run(
        validation_command[:-1], cwd=foreign_cwd, env=env, timeout=30
    )
    assert human_validation.returncode == 0
    assert human_validation.stderr == ""
    assert human_validation.stdout.startswith(
        "Topic package valid: 1 topics, 1 sections.\n"
    )
    assert "not source authenticity or rights" in human_validation.stdout
    assert "No package activation" in human_validation.stdout
    assert str(operator_dir) not in human_validation.stdout

    # Exercise the installed snapshot operator commands before tampering with
    # the package.  The command is run from a foreign working directory.
    package_b = operator_dir / "installed-package-next"
    fingerprint_b = hashlib.sha256(
        (package_b / "manifest.json").read_bytes()
    ).hexdigest()
    snapshot_state = operator_dir / "snapshot-state"
    snapshot_cache = operator_dir / "snapshot-cache"
    snapshot_state.mkdir()
    snapshot_cache.mkdir()
    snapshot_config = operator_dir / "snapshot-cli.toml"
    created = _run(
        [
            *_console_command(python, console_script),
            "init",
            "--config",
            snapshot_config,
        ],
        cwd=foreign_cwd,
        env=env,
        timeout=30,
    )
    assert created.returncode == 0, created.stdout + created.stderr
    config_before = snapshot_config.read_bytes()
    snapshot_env = dict(env, HOME=str(operator_dir), USERPROFILE=str(operator_dir))
    activate_a = [
        *_console_command(python, console_script),
        "corpus",
        "activate",
        package,
        "--expected-manifest-sha256",
        fingerprint,
        "--state-dir",
        snapshot_state,
        "--cache-dir",
        snapshot_cache,
        "--json",
    ]
    selected_a = _run(
        [*activate_a, "--config", "~/snapshot-cli.toml"],
        cwd=foreign_cwd,
        env=snapshot_env,
        timeout=30,
    )
    assert snapshot_config.read_bytes() == config_before
    assert selected_a.returncode == 0, selected_a.stderr
    assert json.loads(selected_a.stdout)["active"]["manifest_sha256"] == fingerprint
    assert selected_a.stderr == ""
    assert list(snapshot_cache.iterdir()) == []

    listed = _run(
        [
            *_console_command(python, console_script),
            "corpus",
            "list",
            "--state-dir",
            snapshot_state,
            "--json",
        ],
        cwd=foreign_cwd,
        env=env,
        timeout=30,
    )
    assert listed.returncode == 0, listed.stderr
    listed_report = json.loads(listed.stdout)
    assert listed_report["status"] == "not_ready"
    assert listed_report["active"]["manifest_sha256"] == fingerprint
    assert "package_path" not in listed.stdout
    assert listed.stderr == ""
    list_config = operator_dir / "state-only.toml"
    list_config.write_text(
        '[paths]\nstate="snapshot-state"\ncache=42\n', encoding="utf-8"
    )
    pointer_before_list = (snapshot_state / "active.json").read_bytes()
    cache_ignored = _run(
        [
            *_console_command(python, console_script),
            "corpus",
            "list",
            "--config",
            "~/state-only.toml",
            "--json",
        ],
        cwd=foreign_cwd,
        env=dict(snapshot_env, TCK_CACHE_DIR=""),
        timeout=30,
    )
    assert cache_ignored.returncode == 0, cache_ignored.stdout + cache_ignored.stderr
    assert json.loads(cache_ignored.stdout)["active"]["manifest_sha256"] == fingerprint
    assert (snapshot_state / "active.json").read_bytes() == pointer_before_list
    assert list(snapshot_cache.iterdir()) == []

    activate_b = activate_a.copy()
    activate_b[activate_b.index(package)] = package_b
    activate_b[activate_b.index(fingerprint)] = fingerprint_b
    selected_b = _run(activate_b, cwd=foreign_cwd, env=env, timeout=30)
    assert selected_b.returncode == 0, selected_b.stderr
    selected_b_report = json.loads(selected_b.stdout)
    assert selected_b_report["active"]["manifest_sha256"] == fingerprint_b
    assert selected_b_report["previous"]["manifest_sha256"] == fingerprint

    rollback = _run(
        [
            *_console_command(python, console_script),
            "corpus",
            "rollback",
            "--state-dir",
            snapshot_state,
            "--cache-dir",
            snapshot_cache,
            "--json",
        ],
        cwd=foreign_cwd,
        env=env,
        timeout=30,
    )
    assert rollback.returncode == 0, rollback.stderr
    assert json.loads(rollback.stdout)["active"]["manifest_sha256"] == fingerprint
    assert list(snapshot_cache.iterdir()) == []

    state_before_bad_pin = (snapshot_state / "active.json").read_bytes()
    bad_pin = _run(
        [
            *_console_command(python, console_script),
            "corpus",
            "activate",
            package_b,
            "--expected-manifest-sha256",
            "0" * 64,
            "--state-dir",
            snapshot_state,
            "--cache-dir",
            snapshot_cache,
            "--json",
        ],
        cwd=foreign_cwd,
        env=env,
        timeout=30,
    )
    assert bad_pin.returncode == 1
    assert json.loads(bad_pin.stdout)["status"] == "error"
    assert bad_pin.stderr == ""
    assert (snapshot_state / "active.json").read_bytes() == state_before_bad_pin
    assert list(snapshot_cache.iterdir()) == []

    (package / "topics.jsonl").write_bytes(before["topics.jsonl"] + b" ")
    tampered_before = {p.name: p.read_bytes() for p in package.iterdir()}
    tampered = _run(validation_command, cwd=foreign_cwd, env=env, timeout=30)
    assert tampered.returncode == 1
    assert json.loads(tampered.stdout)["status"] == "error"
    assert tampered.stderr == ""
    assert "Traceback" not in tampered.stdout
    assert str(operator_dir) not in tampered.stdout
    assert list(cache.iterdir()) == []
    assert (package / "topics.jsonl").read_bytes() == before["topics.jsonl"] + b" "
    assert (package / "manifest.json").read_bytes() == before["manifest.json"]
    assert {p.name: p.read_bytes() for p in package.iterdir()} == tampered_before

    config_path = operator_dir / "config.toml"
    init = _run(
        [*_console_command(python, console_script), "init", "--config", config_path],
        cwd=foreign_cwd,
        env=env,
        timeout=30,
    )
    assert init.returncode == 0, init.stdout + init.stderr
    assert config_path.is_file()
    assert isinstance(tomllib.loads(config_path.read_text(encoding="utf-8")), dict)

    corpus_dir = operator_dir / "corpus"
    corpus_dir.mkdir()
    config_path.write_text("[paths]\ncorpus = 'corpus'\n", encoding="utf-8")
    doctor = _run(
        [
            python,
            "-m",
            "twincat_knowledge",
            "doctor",
            "--config",
            config_path,
            "--json",
        ],
        cwd=foreign_cwd,
        env=env,
        timeout=30,
    )
    assert doctor.returncode == 1, doctor.stderr
    assert (
        tomllib.loads(config_path.read_text(encoding="utf-8"))["paths"]["corpus"]
        == "corpus"
    )
    doctor_report = json.loads(doctor.stdout)
    assert doctor_report["status"] == "not_ready"
    assert doctor_report["checks"]["corpus"]["status"] == "unverified"
    assert str(config_path) not in doctor.stdout
    assert doctor.stderr == ""
