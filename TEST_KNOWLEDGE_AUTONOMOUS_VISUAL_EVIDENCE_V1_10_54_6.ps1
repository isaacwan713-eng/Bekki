[CmdletBinding()]
param()

$ErrorActionPreference = "Stop"
$releaseName = "Knowledge Autonomous Visual Evidence V1.10.54.6"
$projectRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
Push-Location $projectRoot
try {
    python -m unittest -q `
        tests.test_knowledge_autonomous_visual_evidence_v1_10_54_6
    if ($LASTEXITCODE -ne 0) {
        throw "$releaseName unit tests failed."
    }
}
finally {
    Pop-Location
}

$validator = Join-Path $PSScriptRoot "TEST_KNOWLEDGE_EVIDENCE_INDEX_BOOTSTRAP_HOTFIX_V1_10_54_5_1.ps1"
if (-not (Test-Path $validator)) {
    throw "Inherited Knowledge Evidence validator is missing: $validator"
}

& $validator
if ($LASTEXITCODE -ne 0) {
    throw "$releaseName validation failed."
}
