# Build an installable WordPress ZIP from the current checked-out Purr Assistant source.
# Output: dist/PurrAssistant.zip (all files stay inside this repository).
$ErrorActionPreference = 'Stop'
$repo = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
$source = Join-Path $repo 'wordpress/purr-child'
$dist = Join-Path $repo 'dist'
$staging = Join-Path $dist 'PurrAssistant'
$destination = Join-Path $dist 'PurrAssistant.zip'
if (-not (Test-Path (Join-Path $source 'purr-child.php'))) {
    throw 'Purr Assistant plugin bootstrap was not found.'
}
New-Item -ItemType Directory -Force -Path $dist | Out-Null
if (Test-Path $staging) { Remove-Item -LiteralPath $staging -Recurse -Force }
New-Item -ItemType Directory -Force -Path $staging | Out-Null
# Copy-Item -LiteralPath does not expand wildcards: copy children explicitly.
Get-ChildItem -LiteralPath $source -Force | Copy-Item -Destination $staging -Recurse -Force
if (Test-Path $destination) { Remove-Item -LiteralPath $destination -Force }
Compress-Archive -LiteralPath $staging -DestinationPath $destination -CompressionLevel Optimal
Remove-Item -LiteralPath $staging -Recurse -Force
Write-Host "Created $destination"
