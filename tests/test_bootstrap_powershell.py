"""Guard against PowerShell's case-insensitive function/native-command collision."""

from pathlib import Path
import re

BOOTSTRAP = Path(__file__).resolve().parents[1] / "bootstrap.ps1"


def test_bootstrap_does_not_shadow_docker_executable():
    script = BOOTSTRAP.read_text(encoding="utf-8-sig")
    functions = re.findall(r"(?im)^function\s+([\w-]+)", script)
    assert "docker" not in {name.casefold() for name in functions}
    assert re.search(r"(?m)^function Invoke-DockerCli\s*\{", script)
    assert re.search(r"(?m)^\s*Invoke-DockerCli info --format", script)
    assert re.search(r"(?m)^\s*Invoke-DockerCli compose version", script)


def test_bootstrap_invokes_explicit_docker_exe():
    script = BOOTSTRAP.read_text(encoding="utf-8-sig")
    assert not re.search(r"(?im)&\s+docker\s", script)
    assert script.count("& docker.exe") >= 2
