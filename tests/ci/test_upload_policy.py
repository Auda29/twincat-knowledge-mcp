"""Static contracts for the checked-in workflow; native CI proves execution."""

from pathlib import Path

import pytest

WORKFLOW = Path(__file__).resolve().parents[2] / ".github/workflows/foundation-ci.yml"


def test_package_upload_requires_explicit_manual_opt_in() -> None:
    workflow = WORKFLOW.read_text(encoding="utf-8")
    upload = workflow.split("      - name: Upload private CI build (not a release)\n")
    assert len(upload) == 2, "Keep exactly one explicit package upload step"
    assert (
        "        if: ${{ github.event_name == 'workflow_dispatch' "
        "&& inputs.upload_packages == true }}\n"
    ) in upload[1], "Ordinary pushes/PRs must not depend on artifact storage"


def test_dispatch_upload_input_is_boolean_and_defaults_off() -> None:
    workflow = WORKFLOW.read_text(encoding="utf-8")
    expected = (
        "  workflow_dispatch:\n"
        "    inputs:\n"
        "      upload_packages:\n"
        "        description: 'Upload verified software packages "
        "(requires storage quota)'\n"
        "        type: boolean\n"
        "        required: false\n"
        "        default: false\n"
    )
    assert expected in workflow, "Package delivery must be an explicit boolean opt-in"


@pytest.mark.parametrize(
    ("name", "command"),
    [
        ("Install locked dependencies", "uv sync --frozen --dev --python"),
        ("Lint", "uv run --frozen ruff check src tests"),
        ("Check formatting", "uv run --frozen ruff format --check src tests"),
        ("Type check", "uv run --frozen mypy"),
        ("Check dependency compatibility", "uv pip check"),
        ("Unit and installed-artifact tests", "uv run --frozen python -m pytest"),
        ("Build wheel and source archive", "uv build"),
        ("Hash software artifacts", "hashlib.sha256"),
    ],
)
def test_verification_steps_are_not_gated(name: str, command: str) -> None:
    workflow = WORKFLOW.read_text(encoding="utf-8")
    blocks = workflow.split("      - name: ")[1:]
    matches = [block for block in blocks if block.startswith(name + "\n")]
    assert len(matches) == 1
    assert command in matches[0]
    assert "        if:" not in matches[0]
    assert "upload_packages" not in matches[0]
    assert "continue-on-error" not in workflow
    assert "\n    if:" not in workflow, "Do not gate the foundation job"


def test_triggers_platforms_and_upload_failure_semantics_are_preserved() -> None:
    workflow = WORKFLOW.read_text(encoding="utf-8")
    assert "  push:\n    branches: [main, 'swarm/**']\n" in workflow
    assert "  pull_request:\n    branches: [main]\n" in workflow
    assert "os: [ubuntu-24.04, windows-2022]" in workflow
    assert any(
        matrix in workflow
        for matrix in (
            "python: ['3.12', '3.13']",
            "python: ['3.12.10', '3.13.12']",
        )
    )
    assert "          if-no-files-found: error\n" in workflow
    assert "          retention-days: 7\n" in workflow
    assert "          persist-credentials: false\n" in workflow
    assert "permissions:\n  contents: read\n" in workflow
    assert "            dist/SHA256SUMS.txt\n" in workflow
