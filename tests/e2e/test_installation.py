from __future__ import annotations

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
    "build_flags", [("--wheel",), ()], ids=["wheel", "sdist-wheel"]
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

    wheels = sorted(dist.glob("*.whl"))
    assert len(wheels) == 1

    create_venv = _run(
        [uv, "venv", "--python", sys.executable, venv],
        cwd=tmp_path,
        env=env,
        timeout=120,
    )
    assert create_venv.returncode == 0, create_venv.stdout + create_venv.stderr

    python = _venv_python(venv)
    install = _run(
        [uv, "pip", "install", "--python", python, wheels[0]],
        cwd=foreign_cwd,
        env=env,
        timeout=180,
    )
    assert install.returncode == 0, install.stdout + install.stderr
    assert python.is_file()

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
