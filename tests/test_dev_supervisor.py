"""Process ownership and stop/status safety, without starting real services."""
import json
from unittest.mock import Mock

import pytest

from purrfect.dev import supervisor as s


def test_port_settings_reject_non_loopback_and_collisions(monkeypatch):
    class Settings:
        def __init__(self, values):
            self.values = values

        def get(self, key, default=None):
            return self.values.get(key, default)

    monkeypatch.setattr(s, "load_settings", lambda: Settings({}))
    entries = s._config()
    assert [entry[3] for entry in entries] == [8765, 8775]
    monkeypatch.setattr(s, "load_settings", lambda: Settings({"PURR_HOST": "0.0.0.0"}))
    with pytest.raises(ValueError):
        s._config()
    monkeypatch.setattr(s, "load_settings", lambda: Settings({"PURR_OPERATIONS_PORT": "8765"}))
    with pytest.raises(ValueError):
        s._config()
    monkeypatch.setattr(s, "load_settings", lambda: Settings({"PURR_PORT": "70000"}))
    with pytest.raises(ValueError):
        s._config()


def test_state_writes_are_atomic(tmp_path):
    dest = tmp_path / "state.json"
    s._write_atomic(dest, {"state": "running", "pid": 15, "token": "internal"})
    assert s._read(dest) == {"state": "running", "pid": 15, "token": "internal"}
    assert not list(tmp_path.glob("*.tmp"))
    dest.write_text("invalid")
    assert s._read(dest) == {}


def test_stale_pid_not_treated_as_managed(monkeypatch):
    process = Mock()
    process.create_time.return_value = 120.0
    process.is_running.return_value = True
    process.status.return_value = "running"
    monkeypatch.setattr(s.psutil, "Process", lambda pid: process)
    assert s._active({"pid": 1100, "created": 119.0}) is None
    assert s._active({"pid": 1100, "created": 120.0}) is process


def test_stop_never_kills_stale_process(tmp_path, monkeypatch):
    path = tmp_path / "supervisor.json"
    path.write_text(json.dumps({"pid": 123, "created": 42.0, "token": "secret"}))
    monkeypatch.setattr(s, "STATE", path)
    monkeypatch.setattr(s, "STOP", tmp_path / "stop.json")
    monkeypatch.setattr(s, "_active", lambda state: None)
    assert s.stop() == 0
    assert not s.STOP.exists()


def test_stop_requests_only_matching_supervisor(tmp_path, monkeypatch):
    path = tmp_path / "supervisor.json"
    path.write_text(json.dumps({"pid": 123, "created": 42.0, "token": "unique"}))
    monkeypatch.setattr(s, "STATE", path)
    monkeypatch.setattr(s, "STOP", tmp_path / "stop.json")
    proc = Mock()
    monkeypatch.setattr(s, "_active", lambda state: proc)
    assert s.stop() == 0
    assert s._read(s.STOP) == {"token": "unique", "action": "stop"}
    proc.wait.assert_called_once_with(timeout=12)


def test_start_refuses_foreign_port_and_does_not_spawn(tmp_path, monkeypatch):
    monkeypatch.setattr(s, '_require_development', lambda: True)
    monkeypatch.setattr(s.os, "name", "nt")
    monkeypatch.setattr(s, "status", lambda: {"state": "stopped"})
    monkeypatch.setattr(s, "config_path", lambda: tmp_path / ".env")
    (tmp_path / ".env").touch()
    monkeypatch.setattr(s, "_config", lambda: [("gateway", "purrfect", "127.0.0.1", 8765)])
    monkeypatch.setattr(s, "_port_busy", lambda host, port: True)
    monkeypatch.setattr(s.subprocess, "Popen", lambda *args, **kwargs: pytest.fail("Must not spawn"))
    assert s.start() == 2


def test_status_without_live_owner_is_stopped(tmp_path, monkeypatch):
    monkeypatch.setattr(s, "STATE", tmp_path / "missing.json")
    assert s.status()["state"] == "stopped"


def test_production_disables_init_start_and_stop(tmp_path, monkeypatch):
    from purrfect.config import Settings
    monkeypatch.setattr(s, "load_settings", lambda: Settings({"PURR_ENV": "production"}))
    monkeypatch.setattr(s, "config_path", lambda: tmp_path / ".env")
    assert s.init() == 2
    assert s.start() == 2
    assert not (tmp_path / ".env").exists()


def test_dev_init_creates_env_only_once(tmp_path, monkeypatch):
    monkeypatch.setattr(s, "_require_development", lambda: True)
    monkeypatch.setattr(s, "config_path", lambda: tmp_path / ".env")
    from purrfect import config
    real_initialize = config.initialize
    monkeypatch.setattr(config, "initialize", lambda: real_initialize(tmp_path / ".env", legacy_path=tmp_path / "none.json"))
    assert s.init() == 0
    initial = (tmp_path / ".env").read_text()
    assert s.init() == 0
    assert (tmp_path / ".env").read_text() == initial
