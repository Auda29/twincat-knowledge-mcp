"""Operator CLI error contracts; installed success is exercised separately."""

import json

import pytest

from twincat_knowledge.cli import main


@pytest.mark.parametrize("fingerprint", ["a" * 64, "A" * 64, "invalid-pin"])
@pytest.mark.parametrize("as_json", [False, True])
def test_validation_rejects_bad_source_without_disclosing_paths(
    tmp_path, capsys, fingerprint, as_json
):
    package = tmp_path / "private-operator-package"
    cache = tmp_path / "private-cache"
    cache.mkdir()
    argv = [
        "corpus",
        "validate",
        str(package),
        "--expected-manifest-sha256",
        fingerprint,
        "--cache-dir",
        str(cache),
    ]
    if as_json:
        argv.append("--json")
    assert main(argv) == 1
    output = capsys.readouterr()
    if as_json:
        assert json.loads(output.out) == {
            "schema_version": "corpus-validation-1",
            "status": "error",
            "scope": "topic_package",
            "message": "Topic package validation failed.",
        }
        assert output.err == ""
    else:
        assert output.out == ""
        assert output.err == "Topic package validation failed.\n"
    assert str(tmp_path) not in output.out + output.err
    assert fingerprint not in output.out + output.err
    assert list(cache.iterdir()) == []
    assert not package.exists()


@pytest.mark.parametrize("missing", ["pin", "cache"])
def test_validation_requires_operator_trust_and_cache_arguments(capsys, missing):
    argv = ["corpus", "validate", "package"]
    if missing != "pin":
        argv += ["--expected-manifest-sha256", "a" * 64]
    if missing != "cache":
        argv += ["--cache-dir", "cache"]
    with pytest.raises(SystemExit) as error:
        main(argv)
    assert error.value.code == 2
    assert capsys.readouterr().out == ""
