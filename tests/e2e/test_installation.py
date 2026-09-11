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
            "loaded.close(); loaded.close(); "
            "assert list(cache.iterdir()) == []; "
            "assert all(hashlib.sha256((built.path / f.filename).read_bytes())"
            ".hexdigest() == f.sha256 for f in built.manifest.files); "
            "assert built.manifest_path.read_bytes() == descriptor_bytes; "
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
