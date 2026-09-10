[CmdletBinding()]
param()

$ErrorActionPreference = "Stop"
$validator = Join-Path $PSScriptRoot "TEST_KNOWLEDGE_EVIDENCE_LINEAGE_V1_10_54_5.ps1"
if (-not (Test-Path $validator)) {
    throw "Knowledge Evidence Lineage validator is missing: $validator"
}

& $validator
if ($LASTEXITCODE -ne 0) {
    throw "Knowledge Evidence Index Bootstrap Hotfix validation failed."
}
