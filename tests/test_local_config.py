"""Persistent dotenv configuration, safe bootstrap and legacy migration."""
import json

import pytest
from purrfect.config import Settings, initialize, load_settings


def test_new_dotenv_bootstrap_matches_gateway_and_console_credentials(tmp_path):
    path = tmp_path / ".env"
    initialize(path, legacy_path=tmp_path / "no-legacy.json")
    settings = load_settings(path)
    clients = json.loads(settings.get("PURR_CLIENTS_JSON"))
    assert settings.get("PURR_OPERATIONS_GATEWAY_TOKEN") == clients[0]["token"]
    assert settings.get("PURR_OPERATIONS_METRICS_TOKEN") == settings.get("PURR_METRICS_TOKEN")
    assert len(settings.get("PURR_OPERATIONS_TOKEN")) >= 64
    assert len(settings.get("PURR_SESSION_SIGNING_KEY")) >= 64
    initial = path.read_bytes()
    with pytest.raises(FileExistsError):
        initialize(path)
    assert path.read_bytes() == initial


def test_environment_precedence_and_no_mutation(monkeypatch, tmp_path):
    path = tmp_path / ".env"
    path.write_text('PURR_OPERATIONS_PORT="8775"\nPURR_OPERATIONS_MODEL_LABEL="Local Console"\n')
    monkeypatch.setenv("PURR_OPERATIONS_PORT", "9999")
    s = load_settings(path)
    assert s.get("PURR_OPERATIONS_PORT", "1234") == "9999"
    assert s.get("PURR_OPERATIONS_MODEL_LABEL") == "Local Console"
    assert path.read_text().startswith("PURR_OPERATIONS_PORT=")


def test_json_quoted_arrays_unchanged_and_no_interpolation(tmp_path, monkeypatch):
    path = tmp_path / ".env"
    monkeypatch.setenv("SENSITIVE", "should-not-expand")
    payload = [{"token": 'secret-"quoted"', "tenant_id": "dev", "products": ["demo"]}]
    path.write_text("PURR_CLIENTS_JSON=" + json.dumps(json.dumps(payload, separators=(",", ":"))) +
                    '\nPURR_OPERATIONS_MODEL_LABEL="literal-${SENSITIVE}"\n')
    s = load_settings(path)
    assert json.loads(s.get("PURR_CLIENTS_JSON")) == payload
    assert s.get("PURR_OPERATIONS_MODEL_LABEL") == "literal-${SENSITIVE}"


def test_migrates_old_json_secrets_without_rotation(tmp_path):
    previous = tmp_path / "config" / "local.json"
    previous.parent.mkdir()
    original = {"PURR_CLIENTS_JSON": [{"token": "stable-old-token-123456789", "tenant_id": "dev", "products": []}],
                "PURR_OPERATIONS_GATEWAY_TOKEN": "stable-old-token-123456789",
                "PURR_SESSION_SIGNING_KEY": "stable-signing-key-32-chars-abcdefg",
                "PURR_OPERATIONS_PORT": 8775}
    previous.write_text(json.dumps(original))
    destination = tmp_path / ".env"
    initialize(destination, legacy_path=previous)
    migrated = load_settings(destination)
    assert json.loads(migrated.get("PURR_CLIENTS_JSON")) == original["PURR_CLIENTS_JSON"]
    assert migrated.get("PURR_OPERATIONS_PORT") == "8775"
    assert migrated.get("PURR_SESSION_SIGNING_KEY") == original["PURR_SESSION_SIGNING_KEY"]
    assert json.loads(previous.read_text()) == original


def test_missing_dotenv_allows_env_and_defaults(monkeypatch, tmp_path):
    monkeypatch.setenv("PURR_OPERATIONS_HOST", "127.0.0.1")
    s = load_settings(tmp_path / "missing.env")
    assert s.get("PURR_OPERATIONS_PORT", "8775") == "8775"
    assert s.get("PURR_OPERATIONS_HOST") == "127.0.0.1"


def test_symlinks_and_invalid_keys_fail_closed(tmp_path):
    path = tmp_path / ".env"
    path.write_text("INVALID_KEY=unexpected\n")
    with pytest.raises(ValueError):
        load_settings(path)
    path.write_text("PURR_OPERATIONS_TOKEN=test")
    link = tmp_path / "link.env"
    try:
        link.symlink_to(path)
    except (OSError, NotImplementedError):
        pytest.skip("Symlinks not supported here")
    with pytest.raises(ValueError):
        load_settings(link)
    with pytest.raises(FileExistsError):
        initialize(link, legacy_path=tmp_path / "missing.json")


def test_invalid_legacy_does_not_create_dotenv(tmp_path):
    legacy = tmp_path / "legacy.json"
    legacy.write_text("[]")
    target = tmp_path / ".env"
    with pytest.raises(ValueError):
        initialize(target, legacy_path=legacy)
    assert not target.exists()


def test_dev_bootstrap_refuses_explicit_production_mode(tmp_path, monkeypatch):
    from purrfect.config import initialize
    monkeypatch.setenv("PURR_ENV", "production")
    path = tmp_path / ".env"
    with pytest.raises(RuntimeError, match="disabled"):
        initialize(path, legacy_path=tmp_path / "none.json")
    assert not path.exists()
