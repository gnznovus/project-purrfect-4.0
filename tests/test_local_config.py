"""Configuration is persistent, ignored and never checked into the repository."""
import json

import pytest
from purrfect.config import Settings, initialize, load_settings


def test_init_produces_matching_credentials_and_persists(tmp_path):
    path = tmp_path / "config" / "local.json"
    initialize(path)
    data = json.loads(path.read_text())
    assert data["PURR_OPERATIONS_GATEWAY_TOKEN"] == data["PURR_CLIENTS_JSON"][0]["token"]
    assert data["PURR_OPERATIONS_METRICS_TOKEN"] == data["PURR_METRICS_TOKEN"]
    assert len(data["PURR_OPERATIONS_TOKEN"]) >= 64
    assert load_settings(path).get("PURR_CLIENTS_JSON") == json.dumps(data["PURR_CLIENTS_JSON"], separators=(",", ":"))
    with pytest.raises(FileExistsError):
        initialize(path)
    assert json.loads(path.read_text()) == data


def test_environment_values_override_file_without_rewriting(monkeypatch, tmp_path):
    path = tmp_path / "local.json"
    path.write_text('{"PURR_OPERATIONS_PORT": 8775}')
    monkeypatch.setenv("PURR_OPERATIONS_PORT", "9999")
    assert load_settings(path).get("PURR_OPERATIONS_PORT", "1234") == "9999"
    assert json.loads(path.read_text())["PURR_OPERATIONS_PORT"] == 8775


def test_missing_file_falls_back_to_defaults_and_environment(tmp_path, monkeypatch):
    monkeypatch.setenv("PURR_OPERATIONS_HOST", "127.0.0.1")
    config = load_settings(tmp_path/"missing.json")
    assert config.get("PURR_OPERATIONS_PORT", "8775") == "8775"
    assert config.get("PURR_OPERATIONS_HOST") == "127.0.0.1"


def test_reject_invalid_or_symlink_configuration(tmp_path):
    path = tmp_path/"local.json"
    path.write_text('{"BAD": "value"}')
    with pytest.raises(ValueError):
        load_settings(path)
    path.write_text("[]")
    with pytest.raises(ValueError):
        load_settings(path)
    link = tmp_path/"linked.json"
    try:
        link.symlink_to(path)
    except (OSError, NotImplementedError):
        pytest.skip("Symlinks unavailable")
    with pytest.raises(ValueError):
        load_settings(link)
