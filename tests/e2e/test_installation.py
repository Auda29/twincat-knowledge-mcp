from __future__ import annotations

import contextlib
import fcntl
import os
import shutil
import subprocess
import time
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
LOCK_PATH = Path("/home/hermes/workspace/.hermes/twincat-build.lock")


@contextlib.contextmanager
def build_lock():
    LOCK_PATH.parent.mkdir(parents=True, exist_ok=True)
    with LOCK_PATH.open("w", encoding="utf-8") as handle:
        try:
            deadline = time.monotonic() + 30
            while True:
                try:
                    fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
                    break
                except BlockingIOError as exc:
                    if time.monotonic() >= deadline:
                        raise RuntimeError("build lock is busy") from exc
                    time.sleep(0.1)
        except OSError as exc:
            raise RuntimeError("build lock could not be acquired") from exc
        try:
            yield
        finally:
            fcntl.flock(handle, fcntl.LOCK_UN)


def test_wheel_installs_without_source_checkout(tmp_path: Path) -> None:
    uv = shutil.which("uv")
    if uv is None:
        pytest.fail("uv is required for the wheel installation proof")

    dist = tmp_path / "dist"
    venv = tmp_path / "venv"
    foreign_cwd = tmp_path / "foreign-cwd"
    dist.mkdir()
    foreign_cwd.mkdir()

    with build_lock():
        build = subprocess.run(
            [uv, "build", "--wheel", "--out-dir", str(dist)],
            cwd=ROOT,
            env={
                key: value for key, value in os.environ.items() if key != "PYTHONPATH"
            },
            capture_output=True,
            text=True,
            check=False,
        )
        assert build.returncode == 0, build.stdout + build.stderr

        wheels = sorted(dist.glob("*.whl"))
        assert len(wheels) == 1

        create_venv = subprocess.run(
            [uv, "venv", "--python", "3.13", str(venv)],
            cwd=tmp_path,
            capture_output=True,
            text=True,
            check=False,
        )
        assert create_venv.returncode == 0, create_venv.stdout + create_venv.stderr

        python = venv / "bin" / "python"
        install = subprocess.run(
            [uv, "pip", "install", "--python", str(python), str(wheels[0])],
            cwd=foreign_cwd,
            env={
                key: value for key, value in os.environ.items() if key != "PYTHONPATH"
            },
            capture_output=True,
            text=True,
            check=False,
        )
        assert install.returncode == 0, install.stdout + install.stderr

    result = subprocess.run(
        [
            str(venv / "bin" / "python"),
            str(venv / "bin" / "twincat-knowledge"),
            "--version",
        ],
        cwd=foreign_cwd,
        env={key: value for key, value in os.environ.items() if key != "PYTHONPATH"},
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == "twincat-knowledge 0.1.0"
    assert result.stderr == ""
