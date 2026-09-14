"""Public regressions for snapshot CLI configuration review findings."""

import json
from pathlib import Path

import pytest

from twincat_knowledge.cli import main
from twincat_knowledge.config import load_snapshot_settings


def test_literal_config_tilde_uses_same_path_for_open_and_anchor(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys
) -> None:
    home = tmp_path / "home"
    home.mkdir()
    (home / "state").mkdir()
    config = home / "operator.toml"
    config.write_text('[paths]\nstate="state"\ncache="cache"\n', encoding="utf-8")
    foreign = tmp_path / "foreign"
    foreign.mkdir()
    monkeypatch.chdir(foreign)
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setenv("USERPROFILE", str(home))
    monkeypatch.delenv("TCK_STATE_DIR", raising=False)
    monkeypatch.delenv("TCK_CACHE_DIR", raising=False)
    expected = load_snapshot_settings(config, environ={})
    assert load_snapshot_settings("~/operator.toml", environ={}) == expected
    assert expected.state_dir == home / "state"
    assert main(["corpus", "list", "--config", "~/operator.toml", "--json"]) == 0
    assert json.loads(capsys.readouterr().out)["status"] == "not_available"


@pytest.mark.parametrize("cache_value", ['""', '"\\u0000"', "42"])
def test_state_only_listing_does_not_resolve_irrelevant_cache(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys, cache_value: str
) -> None:
    state = tmp_path / "state"
    state.mkdir()
    config = tmp_path / "operator.toml"
    config.write_text(
        f'[paths]\nstate="state"\ncache={cache_value}\n', encoding="utf-8"
    )
    monkeypatch.delenv("TCK_STATE_DIR", raising=False)
    monkeypatch.setenv("TCK_CACHE_DIR", "")
    settings = load_snapshot_settings(config, require_cache=False)
    assert settings.state_dir == state
    assert settings.cache_dir is None
    assert main(["corpus", "list", "--config", str(config), "--json"]) == 0
    assert json.loads(capsys.readouterr().out)["status"] == "not_available"
    assert list(state.iterdir()) == []
    assert sorted(p.name for p in tmp_path.iterdir()) == ["operator.toml", "state"]


def test_init_placeholders_allow_explicit_activation_paths(
    tmp_path: Path, capsys
) -> None:
    from twincat_knowledge.config import ConfigError, create_default_config

    config = create_default_config(tmp_path / "operator.toml")
    before = config.read_bytes()
    state, cache = tmp_path / "state", tmp_path / "cache"
    state.mkdir()
    cache.mkdir()
    settings = load_snapshot_settings(
        config, state_dir=state, cache_dir=cache, environ={}
    )
    assert settings.state_dir == state
    assert settings.cache_dir == cache
    assert (
        main(
            [
                "corpus",
                "list",
                "--config",
                str(config),
                "--state-dir",
                str(state),
                "--json",
            ]
        )
        == 0
    )
    assert json.loads(capsys.readouterr().out)["status"] == "not_available"
    assert config.read_bytes() == before
    with pytest.raises(ConfigError, match="not configured"):
        load_snapshot_settings(config, environ={})
    with pytest.raises(ConfigError):
        load_snapshot_settings(config, state_dir="", cache_dir=cache, environ={})


@pytest.mark.parametrize(
    "payload",
    [
        "[paths\n",
        "paths=42\n",
        "[paths]\nstate=42\n",
        '[paths]\nstate="\\u0000"\n',
    ],
)
@pytest.mark.parametrize("require_cache", [True, False])
def test_invalid_supplied_config_still_rejects_overrides(
    tmp_path: Path, payload: str, require_cache: bool
) -> None:
    from twincat_knowledge.config import ConfigError

    config = tmp_path / "invalid.toml"
    config.write_text(payload, encoding="utf-8")
    with pytest.raises(ConfigError):
        load_snapshot_settings(
            config,
            state_dir=tmp_path / "state",
            cache_dir=tmp_path / "cache",
            environ={},
            require_cache=require_cache,
        )
