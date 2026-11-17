# Start the Operations Console with the project Python; no activation required.
$ErrorActionPreference = 'Stop'
$root = $PSScriptRoot
$python = Join-Path $root '.venv\Scripts\python.exe'

if (-not (Test-Path -LiteralPath $python -PathType Leaf)) {
    throw 'Project Python missing. Run .\setup-local.ps1 first.'
}
Push-Location $root
try {
    & $python -m purrfect.operations
    if ($LASTEXITCODE -ne 0) { throw "Operations Console exited with code $LASTEXITCODE" }
} finally {
    Pop-Location
}
