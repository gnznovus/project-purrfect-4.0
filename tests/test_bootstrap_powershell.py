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


def test_inference_smoke_test_uses_backend_http_path():
    script = BOOTSTRAP.read_text(encoding="utf-8-sig")
    assert "Running actual Ollama HTTP inference smoke test" in script
    assert "http://ollama:11434/api/generate" in script
    assert '"stream": False' in script
    assert "urllib.request.urlopen(request, timeout=180)" in script
    assert "result.get(\"done\")" in script
    assert "exec -T purra python -" in script
    assert "if ($LASTEXITCODE -ne 0)" in script
    assert "ollama run $Model" not in script


def test_wordpress_probes_ignore_compose_status_stderr_and_check_exit_status():
    script = BOOTSTRAP.read_text(encoding="utf-8-sig")
    assert "function Test-WP" in script
    assert "$ErrorActionPreference = 'Continue'" in script
    assert "wp @commands 2>&1 | Out-Null" in script
    assert "return ($LASTEXITCODE -eq 0)" in script
    assert "Test-WP $service @('core', 'version')" in script
    assert "Test-WP $service @('core', 'is-installed')" in script


def test_fresh_lab_admin_credentials_are_generated_without_interactive_prompt():
    script = BOOTSTRAP.read_text(encoding="utf-8-sig")
    assert "RandomNumberGenerator]::Create()" in script
    assert "$adminPassword | & docker.exe compose" in script
    assert "--prompt=admin_password" in script
    assert "run --rm -T $service wp core install" in script
    assert "Password: $adminPassword" in script
    assert "if (-not (Test-WP $service @('core', 'is-installed')))" in script
    assert "Enter a local lab admin password when prompted" not in script


def test_bootstrap_triggers_real_heartbeat_without_fixed_minute_sleep():
    script = BOOTSTRAP.read_text(encoding="utf-8-sig")
    assert "Compose exec -T clock php /opt/purr-child-heartbeat.php" in script
    assert "Compose exec -T clock_b php /opt/purr-child-heartbeat.php" in script
    assert "Start-Sleep -Seconds 65" not in script
    assert "WP 'cli' @('option', 'get', 'purr_child_registry', '--format=json')" in script


def test_new_credentials_are_repeated_after_success_not_saved_to_disk():
    script = BOOTSTRAP.read_text(encoding="utf-8-sig")
    assert "$script:newLabCredentials = @()" in script
    assert "$script:newLabCredentials += [pscustomobject]" in script
    assert "New WordPress lab credentials (save now):" in script
    assert "foreach ($credential in $script:newLabCredentials)" in script
    assert "No new accounts created. Existing passwords are preserved" in script
