"""The installed command must target the one unified supervisor CLI."""
import importlib.metadata
import sys
import tomllib
from pathlib import Path

from purrfect.dev import supervisor


def test_package_declares_unified_cli():
    metadata = tomllib.loads((Path(__file__).resolve().parents[1] / "pyproject.toml").read_text())
    assert metadata["project"]["scripts"]["purrfect"] == "purrfect.dev.supervisor:main"
    entrypoints = importlib.metadata.entry_points(group="console_scripts")
    assert any(e.name == "purrfect" and e.value == "purrfect.dev.supervisor:main" for e in entrypoints)


def test_cli_status_uses_same_supervisor(monkeypatch, capsys):
    monkeypatch.setattr(supervisor, "_require_development", lambda: True)
    monkeypatch.setattr(supervisor, "status", lambda: {"state": "stopped"})
    monkeypatch.setattr(sys, "argv", ["purrfect", "status"])
    assert supervisor.main() == 0
    assert '"stopped"' in capsys.readouterr().out


def test_cli_rejects_prod(monkeypatch, capsys):
    monkeypatch.setattr(supervisor, "_require_development", lambda: False)
    monkeypatch.setattr(sys, "argv", ["purrfect", "start"])
    assert supervisor.main() == 2


def test_windows_bootstrap_registers_managed_cli():
    root = Path(__file__).resolve().parents[1]
    init = (root / "purrfect.init.cmd").read_text()
    install = (root / "scripts" / "install-cli.ps1").read_text()
    assert "install-cli.ps1" in init
    assert "purrfect.dev.supervisor init" in init
    assert "Purrfect managed CLI shim" in install
    assert "SetEnvironmentVariable('Path'" in install
    assert 'purrfect.dev.supervisor %*' in install
