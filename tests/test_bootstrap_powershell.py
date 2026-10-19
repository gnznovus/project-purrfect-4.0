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


def test_missing_ollama_model_is_pulled_without_failing_show():
    script = BOOTSTRAP.read_text(encoding="utf-8-sig")
    assert "ollama show $Model" not in script
    assert "ollama list)" in script
    assert "if (-not $modelFound)" in script
    assert "ollama pull $Model" in script
    assert "if (-not $pulled)" in script


def test_inference_smoke_test_reports_progress_and_timeout():
    script = BOOTSTRAP.read_text(encoding="utf-8-sig")
    assert "$inferenceArgs = @('compose') + @($composeArgs)" in script
    assert "Start-Process -FilePath 'docker.exe'" in script
    assert "Ollama still generating" in script
    assert "inferenceTimeoutSeconds = 600" in script
    assert "if ($null -eq $inferenceProcess)" in script
    assert "$inferenceProcess.WaitForExit(2000)" in script
    assert "Stop-Process -Id $inferenceProcess.Id" in script
    assert "Remove-Item $inferenceOut, $inferenceErr" in script
