"""Unit tests for nexusai.core.config — NexusConfig YAML loader."""

from __future__ import annotations

import os

import pytest

from nexusai.core.config import NexusConfig, _deep_merge, _interpolate_env_vars


# ── Helpers ───────────────────────────────────────────────────────────────────


def _write(path, text: str) -> None:
    path.write_text(text, encoding="utf-8")


# ── test_load_default_yaml ────────────────────────────────────────────────────


def test_load_default_yaml(tmp_path) -> None:
    """Config loads values from default.yaml correctly."""
    _write(tmp_path / "default.yaml", "app:\n  name: NexusAI\n  debug: false\n")
    cfg = NexusConfig(config_dir=tmp_path)
    cfg.load()

    assert cfg.get("app.name") == "NexusAI"
    assert cfg.get("app.debug") is False


# ── test_get_nested_key ───────────────────────────────────────────────────────


def test_get_nested_key(tmp_path) -> None:
    """config.get() resolves arbitrarily deep dot-separated paths."""
    _write(
        tmp_path / "default.yaml",
        "features:\n  dashboard:\n    enabled: true\n    port: 8080\n",
    )
    cfg = NexusConfig(config_dir=tmp_path)
    cfg.load()

    assert cfg.get("features.dashboard.enabled") is True
    assert cfg.get("features.dashboard.port") == 8080


# ── test_get_with_default ─────────────────────────────────────────────────────


def test_get_with_default(tmp_path) -> None:
    """config.get() returns the supplied default for missing keys."""
    _write(tmp_path / "default.yaml", "existing: 42\n")
    cfg = NexusConfig(config_dir=tmp_path)
    cfg.load()

    assert cfg.get("missing.key", "fallback") == "fallback"
    assert cfg.get("also.missing") is None


# ── test_env_var_interpolation ────────────────────────────────────────────────


def test_env_var_interpolation(tmp_path, monkeypatch) -> None:
    """${MY_VAR} in YAML is replaced with the actual environment variable."""
    monkeypatch.setenv("TEST_TOKEN", "secret-abc")
    _write(tmp_path / "default.yaml", "api:\n  token: ${TEST_TOKEN}\n")
    cfg = NexusConfig(config_dir=tmp_path)
    cfg.load()

    assert cfg.get("api.token") == "secret-abc"


# ── test_env_var_default ──────────────────────────────────────────────────────


def test_env_var_default(tmp_path, monkeypatch) -> None:
    """${VAR:fallback} returns the fallback string when VAR is not set."""
    monkeypatch.delenv("NEXUS_UNSET_VAR", raising=False)
    _write(tmp_path / "default.yaml", "db:\n  host: ${NEXUS_UNSET_VAR:localhost}\n")
    cfg = NexusConfig(config_dir=tmp_path)
    cfg.load()

    assert cfg.get("db.host") == "localhost"


# ── test_deep_merge ───────────────────────────────────────────────────────────


def test_deep_merge(tmp_path) -> None:
    """local.yaml overrides values in default.yaml without removing other keys."""
    _write(
        tmp_path / "default.yaml",
        "app:\n  name: Default\n  version: 1\nfeature: enabled\n",
    )
    _write(tmp_path / "local.yaml", "app:\n  name: Local\n")
    cfg = NexusConfig(config_dir=tmp_path)
    cfg.load()

    # local.yaml overrides app.name
    assert cfg.get("app.name") == "Local"
    # default.yaml value preserved
    assert cfg.get("app.version") == 1
    # top-level key from default.yaml preserved
    assert cfg.get("feature") == "enabled"


# ── test_reload ───────────────────────────────────────────────────────────────


def test_reload(tmp_path) -> None:
    """config.reload() picks up file changes and returns diff of changed keys."""
    default = tmp_path / "default.yaml"
    _write(default, "app:\n  version: 1\n")
    cfg = NexusConfig(config_dir=tmp_path)
    cfg.load()
    assert cfg.get("app.version") == 1

    # Mutate the file on disk
    _write(default, "app:\n  version: 2\n")
    changes = cfg.reload()

    assert cfg.get("app.version") == 2
    assert "app.version" in changes
    assert changes["app.version"] == 2


# ── test_set_in_memory ────────────────────────────────────────────────────────


def test_set_in_memory(tmp_path) -> None:
    """config.set() updates an in-memory value without touching disk."""
    _write(tmp_path / "default.yaml", "key: original\n")
    cfg = NexusConfig(config_dir=tmp_path)
    cfg.load()

    cfg.set("key", "updated")
    assert cfg.get("key") == "updated"


# ── test_is_enabled ───────────────────────────────────────────────────────────


def test_is_enabled(tmp_path) -> None:
    """is_enabled() is a convenience wrapper for feature flag checks."""
    _write(
        tmp_path / "default.yaml",
        "features:\n  dashboard:\n    enabled: true\n  beta:\n    enabled: false\n",
    )
    cfg = NexusConfig(config_dir=tmp_path)
    cfg.load()

    assert cfg.is_enabled("features.dashboard") is True
    assert cfg.is_enabled("features.beta") is False
    assert cfg.is_enabled("features.nonexistent") is False


# ── test_missing_default_yaml ─────────────────────────────────────────────────


def test_missing_default_yaml(tmp_path) -> None:
    """Loading with no default.yaml produces an empty config without raising."""
    cfg = NexusConfig(config_dir=tmp_path)
    cfg.load()  # must not raise

    assert cfg.get("anything", "default") == "default"


# ── Module-level helper tests ─────────────────────────────────────────────────


def test_deep_merge_helper() -> None:
    """_deep_merge produces correct nested merge without mutating inputs."""
    base = {"a": 1, "nested": {"x": 10, "y": 20}}
    override = {"nested": {"y": 99, "z": 30}, "b": 2}
    result = _deep_merge(base, override)

    assert result["a"] == 1
    assert result["b"] == 2
    assert result["nested"]["x"] == 10  # preserved from base
    assert result["nested"]["y"] == 99  # overridden
    assert result["nested"]["z"] == 30  # new key

    # originals not mutated
    assert base["nested"]["y"] == 20


def test_interpolate_env_vars_list(monkeypatch) -> None:
    """_interpolate_env_vars handles lists containing ${VAR} strings."""
    monkeypatch.setenv("LIST_VAL", "hello")
    result = _interpolate_env_vars(["${LIST_VAL}", "static"])
    assert result == ["hello", "static"]
