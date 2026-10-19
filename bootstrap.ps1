# Purrfect 4.0 fresh-clone lab bootstrap. Run from anywhere with: .\bootstrap.ps1
# No destructive Docker operations. Existing databases, models and users are preserved.
[CmdletBinding()]
param(
    [switch]$SiteB,
    [string]$Model = 'llama3.2:3b',
    [string]$AdminUser = 'purr-lab',
    [string]$AdminEmail = 'lab@example.invalid'
)
Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'
Set-Location $PSScriptRoot

function Step([string]$message) { Write-Host "[Purrfect] $message" -ForegroundColor Cyan }
function Invoke-DockerCli {
    & docker.exe @args
    if ($LASTEXITCODE -ne 0) { throw "Docker command failed (exit $LASTEXITCODE): $($args -join ' ')" }
}
function Compose {
    & docker.exe compose @composeArgs @args
    if ($LASTEXITCODE -ne 0) { throw "Docker Compose failed (exit $LASTEXITCODE): $($args -join ' ')" }
}
function WP([string]$service, [string[]]$commands) {
    & docker.exe compose @composeArgs --profile tools run --rm -T $service wp @commands
    if ($LASTEXITCODE -ne 0) { throw "WP-CLI failed on ${service}: $($commands -join ' ')" }
}
# Docker Compose emits status messages on stderr even for successful commands.
# Windows PowerShell 5.1 turns redirected native stderr into ErrorRecords when
# ErrorActionPreference is Stop. Quiet probes must inspect exit status instead.
function Test-WP([string]$service, [string[]]$commands) {
    $ErrorActionPreference = 'Continue'
    & docker.exe compose @composeArgs --profile tools run --rm -T $service wp @commands 2>&1 | Out-Null
    return ($LASTEXITCODE -eq 0)
}
function WaitForWP([string]$service) {
    for ($attempt = 0; $attempt -lt 40; $attempt++) {
        if (Test-WP $service @('core', 'version')) { return }
        Start-Sleep -Seconds 3
    }
    throw "WordPress files did not become available for $service"
}
function PrepareSite([string]$service, [string]$url, [string]$title) {
    Step "Checking $title"
    WaitForWP $service
    if (-not (Test-WP $service @('core', 'is-installed'))) {
        Write-Host "Fresh WordPress setup for $url. Enter a local lab admin password when prompted."
        # Interactive WP-CLI prompt prevents password from being embedded in Git or process args.
        & docker.exe compose @composeArgs --profile tools run --rm $service wp core install "--url=$url" "--title=$title" "--admin_user=$AdminUser" "--admin_email=$AdminEmail" --skip-email --prompt=admin_password
        if ($LASTEXITCODE -ne 0) { throw "WordPress installation failed on $service" }
    }
    WP $service @('plugin', 'activate', 'purr-child', 'mock-layout', 'mock-translation')
    Step "$title plugin activation verified"
}

try {
    Step 'Checking Docker Desktop and Compose'
    if (-not (Get-Command docker -ErrorAction SilentlyContinue)) { throw 'Docker CLI not found. Install/start Docker Desktop, then retry.' }
    Invoke-DockerCli info --format '{{.ServerVersion}}'
    Invoke-DockerCli compose version

    $composeArgs = @('-f', 'wordpress/lab/compose.yaml')
    if ($SiteB) { $composeArgs += @('-f', 'wordpress/lab/compose.site-b.yaml') }
    Compose config --quiet

    # Environment applies to initial container creation and repeated bootstrap runs.
    $env:PURRA_BRAIN_MODE = 'ollama'
    $env:PURRA_OLLAMA_MODEL = $Model

    Step 'Starting Ollama and lab containers (preserving existing volumes)'
    Compose --profile brain up -d --build ollama purra db wp clock
    if ($SiteB) { Compose --profile brain up -d --build db_b wp_b clock_b }

    Step 'Waiting for Ollama to accept connections'
    $ollamaReady = $false
    for ($attempt = 0; $attempt -lt 20; $attempt++) {
        & docker.exe compose @composeArgs exec -T ollama ollama list *> $null
        if ($LASTEXITCODE -eq 0) { $ollamaReady = $true; break }
        Start-Sleep -Seconds 3
    }
    if (-not $ollamaReady) { throw 'Ollama service did not become ready.' }
    Step "Checking required Ollama model $Model"
    # 'ollama show' exits with an expected stderr error for an absent model.
    # Under PowerShell's Stop preference that stderr can abort the bootstrap
    # before the automatic pull. A successful 'list' avoids that control-flow trap.
    $installedModels = @(& docker.exe compose @composeArgs exec -T ollama ollama list)
    if ($LASTEXITCODE -ne 0) { throw 'Unable to list installed Ollama models.' }
    $modelFound = @($installedModels | Where-Object {
        $columns = $_.Trim() -split '\s+'
        $columns[0] -ceq $Model
    }).Count -gt 0
    if (-not $modelFound) {
        Step "Downloading Ollama model $Model (preserved in its Docker volume)"
        $pulled = $false
        for ($attempt = 1; $attempt -le 3; $attempt++) {
            & docker.exe compose @composeArgs exec -T ollama ollama pull $Model
            if ($LASTEXITCODE -eq 0) { $pulled = $true; break }
            if ($attempt -lt 3) { Step 'Download interrupted; retrying in 5 seconds'; Start-Sleep -Seconds 5 }
        }
        if (-not $pulled) { throw 'Ollama model download failed after 3 attempts. Rerun bootstrap to resume.' }
    }
    Step "Running actual Ollama HTTP inference smoke test ($Model; timeout: 180 seconds)"
    # Use the same backend-to-Ollama HTTP path that Purr uses at runtime.
    # The interactive 'ollama run' CLI can hang without ever reaching model generation.
    # The backend Compose service already receives PURRA_OLLAMA_MODEL from the environment.
    $inferenceProbe = @'
import json
import os
import sys
import time
import urllib.request

model = os.environ.get("PURRA_OLLAMA_MODEL", "llama3.2:3b")
payload = json.dumps({
    "model": model,
    "prompt": "Reply with the single word READY.",
    "stream": False,
}).encode("utf-8")
request = urllib.request.Request(
    "http://ollama:11434/api/generate",
    data=payload,
    headers={"Content-Type": "application/json"},
)
started = time.monotonic()
try:
    with urllib.request.urlopen(request, timeout=180) as response:
        result = json.load(response)
except Exception as error:
    print(f"Ollama HTTP inference failed: {type(error).__name__}: {error}", file=sys.stderr)
    sys.exit(1)
answer = result.get("response", "")
if not result.get("done") or not isinstance(answer, str) or not answer.strip():
    print(f"Ollama returned an incomplete or empty response: {result!r}", file=sys.stderr)
    sys.exit(1)
print(f"Ollama HTTP inference passed in {time.monotonic() - started:.1f}s; response: {answer.strip()}")
'@
    $inferenceProbe | & docker.exe compose @composeArgs exec -T purra python -
    if ($LASTEXITCODE -ne 0) { throw "Ollama HTTP inference verification failed (exit $LASTEXITCODE)." }

    Step 'Initializing Sophia demo knowledge only if its catalog is empty'
    Compose exec -T purra python /workspace/wordpress/lab/bootstrap_knowledge.py

    PrepareSite 'cli' 'http://localhost:8084' 'Purrfect Lab A'
    if ($SiteB) { PrepareSite 'cli_b' 'http://localhost:8083' 'Purrfect Lab B' }

    Step 'Waiting for registry and knowledge heartbeat'
    # The existing independent minute clock owns heartbeat scheduling.
    Start-Sleep -Seconds 65
    Step 'Verifying initialized registry'
    WP 'cli' @('option', 'get', 'purr_child_registry', '--format=json')
    if ($SiteB) { WP 'cli_b' @('option', 'get', 'purr_child_registry', '--format=json') }

    Write-Host ''
    Write-Host 'Purrfect lab initialized! Open:' -ForegroundColor Green
    Write-Host '  Site A: http://localhost:8084/wp-admin/admin.php?page=purr-child-admin'
    if ($SiteB) { Write-Host '  Site B: http://localhost:8083/wp-admin/admin.php?page=purr-child-admin' }
    Write-Host '  Brain: Ollama (real inference verified)'
    Write-Host 'The WordPress admin credentials are the ones you chose during installation.'
} catch {
    Write-Error $_
    exit 1
}
