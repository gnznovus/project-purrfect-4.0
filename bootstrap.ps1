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
function Docker {
    & docker @args
    if ($LASTEXITCODE -ne 0) { throw "Docker command failed (exit $LASTEXITCODE): $($args -join ' ')" }
}
function Compose {
    & docker compose @composeArgs @args
    if ($LASTEXITCODE -ne 0) { throw "Docker Compose failed (exit $LASTEXITCODE): $($args -join ' ')" }
}
function WP([string]$service, [string[]]$commands) {
    & docker compose @composeArgs --profile tools run --rm -T $service wp @commands
    if ($LASTEXITCODE -ne 0) { throw "WP-CLI failed on ${service}: $($commands -join ' ')" }
}
function WaitForWP([string]$service) {
    for ($attempt = 0; $attempt -lt 40; $attempt++) {
        & docker compose @composeArgs --profile tools run --rm -T $service wp core version *> $null
        if ($LASTEXITCODE -eq 0) { return }
        Start-Sleep -Seconds 3
    }
    throw "WordPress files did not become available for $service"
}
function PrepareSite([string]$service, [string]$url, [string]$title) {
    Step "Checking $title"
    WaitForWP $service
    & docker compose @composeArgs --profile tools run --rm -T $service wp core is-installed *> $null
    if ($LASTEXITCODE -ne 0) {
        Write-Host "Fresh WordPress setup for $url. Enter a local lab admin password when prompted."
        # Interactive WP-CLI prompt prevents password from being embedded in Git or process args.
        & docker compose @composeArgs --profile tools run --rm $service wp core install "--url=$url" "--title=$title" "--admin_user=$AdminUser" "--admin_email=$AdminEmail" --skip-email --prompt=admin_password
        if ($LASTEXITCODE -ne 0) { throw "WordPress installation failed on $service" }
    }
    WP $service @('plugin', 'activate', 'purr-child', 'mock-layout', 'mock-translation')
    Step "$title plugin activation verified"
}

try {
    Step 'Checking Docker Desktop and Compose'
    if (-not (Get-Command docker -ErrorAction SilentlyContinue)) { throw 'Docker CLI not found. Install/start Docker Desktop, then retry.' }
    Docker info --format '{{.ServerVersion}}'
    Docker compose version

    $composeArgs = @('-f', 'wordpress/lab/compose.yaml')
    if ($SiteB) { $composeArgs += @('-f', 'wordpress/lab/compose.site-b.yaml') }
    Compose config --quiet

    # Environment applies to initial container creation and repeated bootstrap runs.
    $env:PURRA_BRAIN_MODE = 'ollama'
    $env:PURRA_OLLAMA_MODEL = $Model

    Step 'Starting Ollama and lab containers (preserving existing volumes)'
    Compose --profile brain up -d --build ollama purra db wp clock
    if ($SiteB) { Compose --profile brain up -d --build db_b wp_b clock_b }

    Step "Ensuring Ollama model $Model is present (first run downloads it)"
    Compose exec -T ollama ollama pull $Model
    Step 'Running actual Ollama inference smoke test'
    $reply = & docker compose @composeArgs exec -T ollama ollama run $Model 'Reply with the single word READY.'
    if ($LASTEXITCODE -ne 0 -or -not (($reply | Out-String).Trim())) {
        throw 'Ollama inference failed. The lab was not declared ready.'
    }

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
