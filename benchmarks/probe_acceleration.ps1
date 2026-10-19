[CmdletBinding()]
param()
Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'
Set-Location (Split-Path $PSScriptRoot -Parent)
if (Get-NetTCPConnection -LocalPort 11435 -State Listen -ErrorAction SilentlyContinue) {
    throw 'Port 11435 is already in use; no existing process will be changed.'
}
$saved = @{}
foreach ($name in @('OLLAMA_HOST','OLLAMA_IGPU_ENABLE','OLLAMA_VULKAN','OLLAMA_NOPRUNE')) {
    $saved[$name] = [Environment]::GetEnvironmentVariable($name, 'Process')
}
$probeProcess = $null
try {
    # Per-process settings only. The installed Windows service is untouched.
    $env:OLLAMA_HOST = '127.0.0.1:11435'
    $env:OLLAMA_IGPU_ENABLE = '1'
    $env:OLLAMA_VULKAN = 'true'
    $env:OLLAMA_NOPRUNE = '1'
    $probeProcess = Start-Process -FilePath (Get-Command ollama).Source -ArgumentList 'serve' `
        -WindowStyle Hidden -PassThru `
        -RedirectStandardOutput (Join-Path (Get-Location) 'docs/performance/native-probe.stdout.log') `
        -RedirectStandardError (Join-Path (Get-Location) 'docs/performance/native-probe.stderr.log')
    foreach ($name in $saved.Keys) { [Environment]::SetEnvironmentVariable($name, $saved[$name], 'Process') }
    $ready = $false
    for ($attempt = 0; $attempt -lt 60; $attempt++) {
        if ($probeProcess.HasExited) { throw 'Dedicated probe server exited; inspect its repository log.' }
        try {
            Invoke-RestMethod 'http://127.0.0.1:11435/api/version' -TimeoutSec 1 | Out-Null
            $ready = $true
            break
        } catch { Start-Sleep -Seconds 1 }
    }
    if (-not $ready) { throw 'Dedicated probe server did not become ready.' }
    & .\.venv\Scripts\python benchmarks/probe_acceleration.py
    if ($LASTEXITCODE -ne 0) { throw 'Native acceleration probe failed.' }
} finally {
    foreach ($name in $saved.Keys) { [Environment]::SetEnvironmentVariable($name, $saved[$name], 'Process') }
    if ($null -ne $probeProcess -and -not $probeProcess.HasExited) {
        Stop-Process -Id $probeProcess.Id
    }
}
