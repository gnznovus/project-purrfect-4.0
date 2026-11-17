# One-time local setup. Never overwrites existing .env credentials.
$ErrorActionPreference = 'Stop'
$root = $PSScriptRoot
$python = Join-Path $root '.venv\Scripts\python.exe'

if (-not (Test-Path -LiteralPath $python -PathType Leaf)) {
    Write-Host 'Creating Python 3.14 virtual environment...'
    & py -3.14 -m venv (Join-Path $root '.venv')
    if ($LASTEXITCODE -ne 0) {
        throw 'Python 3.14 is required. Install it and rerun .\setup-local.ps1'
    }
}
if (-not (Test-Path -LiteralPath $python -PathType Leaf)) {
    throw "Virtual environment Python was not found at $python"
}

& $python -c 'import sys; assert sys.version_info >= (3, 14), "Purr requires Python 3.14+"'
if ($LASTEXITCODE -ne 0) {
    throw 'Existing .venv uses an unsupported Python. Recreate it with Python 3.14.'
}

Push-Location $root
try {
    Write-Host 'Installing Purr and development dependencies...'
    & $python -m pip install -e '.[dev]'
    if ($LASTEXITCODE -ne 0) { throw 'Package installation failed.' }

    if (Test-Path -LiteralPath (Join-Path $root '.env')) {
        Write-Host 'Existing .env preserved (no credential rotation).'
    } else {
        & $python -m purrfect.config init
        if ($LASTEXITCODE -ne 0) { throw 'Local credential initialization failed.' }
    }
    Write-Host 'Ready. Use .\start-gateway.ps1 and .\start-console.ps1 in separate terminals.'
} finally {
    Pop-Location
}
