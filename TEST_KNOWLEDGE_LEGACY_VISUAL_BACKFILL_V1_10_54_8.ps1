[CmdletBinding()]
param()

$ErrorActionPreference = "Stop"
$releaseName = "Knowledge Legacy Visual Evidence Backfill V1.10.54.8"
$projectRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
Push-Location $projectRoot
try {
    python -m unittest -q `
        tests.test_knowledge_legacy_visual_backfill_v1_10_54_8
    if ($LASTEXITCODE -ne 0) {
        throw "$releaseName unit tests failed."
    }
}
finally {
    Pop-Location
}

$validator = Join-Path $PSScriptRoot "TEST_KNOWLEDGE_VISUAL_RECALL_V1_10_54_7.ps1"
if (-not (Test-Path $validator)) {
    throw "Inherited visual-recall validator is missing: $validator"
}

& $validator
if ($LASTEXITCODE -ne 0) {
    throw "$releaseName validation failed."
}
