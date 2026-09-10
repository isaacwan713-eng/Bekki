[CmdletBinding()]
param()

$ErrorActionPreference = "Stop"
$releaseName = "Knowledge Visual Recall V1.10.54.7"
$projectRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
Push-Location $projectRoot
try {
    python -m unittest -q `
        tests.test_knowledge_visual_recall_v1_10_54_7
    if ($LASTEXITCODE -ne 0) {
        throw "$releaseName unit tests failed."
    }
}
finally {
    Pop-Location
}

$validator = Join-Path $PSScriptRoot "TEST_KNOWLEDGE_AUTONOMOUS_VISUAL_EVIDENCE_V1_10_54_6.ps1"
if (-not (Test-Path $validator)) {
    throw "Inherited autonomous visual-evidence validator is missing: $validator"
}

& $validator
if ($LASTEXITCODE -ne 0) {
    throw "$releaseName validation failed."
}
