[CmdletBinding()]
param(
    [Parameter(Mandatory)][ValidatePattern('^[a-z0-9-]+$')][string]$Label,
    [string]$SourcePath = '/workspace/src',
    [ValidatePattern('^[a-z0-9-]+\.json$')][string]$Corpus = 'corpus.json',
    [ValidateRange(1, 20)][int]$Rounds = 1,
    [switch]$Cold
)
Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'
Set-Location (Split-Path $PSScriptRoot -Parent)
$runArgs = @('exec', '-e', "PYTHONPATH=$SourcePath", 'lab-purra-1',
    'python', '-u', '/workspace/benchmarks/chat_latency.py', '--label', $Label,
    '--rounds', "$Rounds", '--corpus', "/workspace/benchmarks/$Corpus")
if ($Cold) { $runArgs += '--cold' }
$reportPath = Join-Path (Get-Location) "docs/performance/$Label.json"
$recorded = $false
# Docker stderr contains ordinary HTTP access logs on Windows PowerShell 5.1.
$ErrorActionPreference = 'Continue'
& docker @runArgs | ForEach-Object {
    if ($_ -like 'REPORT_JSON:*') {
        $json = $_.Substring('REPORT_JSON:'.Length)
        [System.IO.File]::WriteAllText($reportPath, $json + "`n", [System.Text.UTF8Encoding]::new($false))
        $recorded = $true
    } else {
        Write-Host $_
    }
}
if ($LASTEXITCODE -ne 0 -or -not $recorded) { throw 'Benchmark failed; no complete report recorded.' }
Write-Host "Saved $reportPath"
