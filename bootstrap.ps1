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
function WaitForWP([string]$service) {
    for ($attempt = 0; $attempt -lt 40; $attempt++) {
        & docker.exe compose @composeArgs --profile tools run --rm -T $service wp core version *> $null
        if ($LASTEXITCODE -eq 0) { return }
        Start-Sleep -Seconds 3
    }
    throw "WordPress files did not become available for $service"
}
function PrepareSite([string]$service, [string]$url, [string]$title) {
    Step "Checking $title"
    WaitForWP $service
    & docker.exe compose @composeArgs --profile tools run --rm -T $service wp core is-installed *> $null
    if ($LASTEXITCODE -ne 0) {
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
    Step "Running actual Ollama inference smoke test ($Model)"
    # A first CPU inference can take minutes, and captured stdout otherwise looks frozen.
    # Launch Docker as a monitored process so progress remains visible while preserving
    # its response for validation. Store temporary output inside this repository only.
    $inferenceOut = Join-Path $PSScriptRoot ".bootstrap-inference-$PID.out"
    $inferenceErr = Join-Path $PSScriptRoot ".bootstrap-inference-$PID.err"
    $inferenceArgs = @($composeArgs) + @('exec', '-T', 'ollama', 'ollama', 'run', $Model, 'Reply with the single word READY.')
    $inferenceCommandLine = ($inferenceArgs | ForEach-Object {
        if ($_ -match '[\s"]') { '"' + ($_ -replace '"', '\\"') + '"' } else { $_ }
    }) -join ' '
    $inferenceTimeoutSeconds = 600
    $inferenceClock = [System.Diagnostics.Stopwatch]::StartNew()
    $inferenceProcess = $null
    try {
        Step "Inference running; reporting every 10 seconds (timeout: $inferenceTimeoutSeconds seconds)"
        $inferenceProcess = Start-Process -FilePath 'docker.exe' -ArgumentList $inferenceCommandLine -NoNewWindow -PassThru -RedirectStandardOutput $inferenceOut -RedirectStandardError $inferenceErr
        while (-not $inferenceProcess.HasExited) {
            Start-Sleep -Seconds 2
            $inferenceProcess.Refresh()
            $elapsed = [int]$inferenceClock.Elapsed.TotalSeconds
            if ($elapsed -ge $inferenceTimeoutSeconds) {
                Stop-Process -Id $inferenceProcess.Id -Force -ErrorAction SilentlyContinue
                throw "Ollama inference timed out after $elapsed seconds. Check available CPU/RAM and Ollama logs."
            }
            if ($elapsed -ge 10 -and $elapsed % 10 -lt 2) {
                Step "Ollama still generating... ${elapsed}s elapsed"
            }
        }
        $inferenceClock.Stop()
        $reply = if (Test-Path $inferenceOut) { (Get-Content $inferenceOut -Raw).Trim() } else { '' }
        if ($inferenceProcess.ExitCode -ne 0 -or -not $reply) {
            $diagnostic = if (Test-Path $inferenceErr) { (Get-Content $inferenceErr -Raw).Trim() } else { '' }
            throw "Ollama inference failed (exit $($inferenceProcess.ExitCode)): $diagnostic"
        }
        Step "Ollama inference passed in $([int]$inferenceClock.Elapsed.TotalSeconds)s; received response: $reply"
    } finally {
        Remove-Item $inferenceOut, $inferenceErr -Force -ErrorAction SilentlyContinue
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
