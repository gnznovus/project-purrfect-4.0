# Register a stable user-scoped CLI shim without activating the venv.
# The shim points to this checkout's Python and delegates to a single CLI.
$ErrorActionPreference = 'Stop'
$root = (Resolve-Path -LiteralPath (Join-Path $PSScriptRoot '..')).Path
$python = Join-Path $root '.venv\Scripts\python.exe'
if (-not (Test-Path -LiteralPath $python -PathType Leaf)) {
    throw "Project interpreter missing: $python"
}

$bin = Join-Path $env:LOCALAPPDATA 'Purrfect\bin'
if (-not $env:LOCALAPPDATA) { throw 'LOCALAPPDATA is required for user CLI installation' }
New-Item -ItemType Directory -Path $bin -Force | Out-Null
$command = Join-Path $bin 'purrfect.cmd'
# A previous registration may belong to another project; never silently replace it.
if (Test-Path -LiteralPath $command) {
    $previous = Get-Content -LiteralPath $command -Raw
    $signature = 'REM Purrfect managed CLI shim'
    if (-not $previous.Contains($signature)) {
        throw "Unrecognized purrfect.cmd exists at $command. Not overwriting it."
    }
}
# The project path is quoted; reject characters used for CMD expansion.
if ($python -match '[%!"\r\n]') {
    throw 'Project path contains characters unsupported by the CMD shim; use the venv CLI instead.'
}
$shim = @"
@echo off
REM Purrfect managed CLI shim
"$python" -m purrfect.dev.supervisor %*
exit /b %ERRORLEVEL%
"@
[System.IO.File]::WriteAllText($command, $shim + "`r`n", [System.Text.Encoding]::ASCII)
$userPath = [Environment]::GetEnvironmentVariable('Path', 'User')
$entries = @($userPath -split ';' | Where-Object { $_ })
if (-not ($entries | Where-Object { $_.TrimEnd('\') -ieq $bin.TrimEnd('\') })) {
    $updated = ($entries + $bin) -join ';'
    [Environment]::SetEnvironmentVariable('Path', $updated, 'User')
    Write-Host "User PATH updated: $bin"
    Write-Host 'Open a NEW terminal to use the purrfect command.'
} else {
    Write-Host "User PATH already includes: $bin"
}
Write-Host "CLI command installed: $command"
