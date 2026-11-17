# Start the Gateway with the project Python without activating .venv.
$ErrorActionPreference = 'Stop'
$root = $PSScriptRoot
$python = Join-Path $root '.venv\Scripts\python.exe'

if (-not (Test-Path -LiteralPath $python -PathType Leaf)) {
    throw 'Project Python missing. Run .\setup-local.ps1 first.'
}
Push-Location $root
try {
    & $python -m purrfect
    if ($LASTEXITCODE -ne 0) { throw "Gateway exited with code $LASTEXITCODE" }
} finally {
    Pop-Location
}
