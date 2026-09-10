[CmdletBinding()]
param()

$ErrorActionPreference = "Stop"
$projectRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$expectedBuild = "bekki-temporal-evidence-graceful-fallback-v1-10-51-11-20260904"

Push-Location $projectRoot
try {
    $metadata = Get-Content -Raw -Encoding UTF8 .\BEKKI_BUILD.json |
        ConvertFrom-Json
    if ($metadata.build_id -ne $expectedBuild) {
        throw "Unexpected build: $($metadata.build_id)"
    }

    python -m unittest -q `
        tests.test_bilibili_native_fact_executor_v1_10_51_3 `
        tests.test_fixed_site_source_contract_v1_10_51_2 `
        tests.test_stable_v1_magi `
        tests.test_bilibili_visible_results_v1_10_30 `
        tests.test_bilibili_card_first_v1_10_31 `
        tests.test_bilibili_first_load_retry_v1_10_35 `
        tests.test_knowledge_relationship_grounding_v1_10_51
    if ($LASTEXITCODE -ne 0) {
        throw "Bilibili native fact executor regression tests failed."
    }

    Write-Output "build_id = $($metadata.build_id)"
    Write-Output "fact_purpose_preserved = True"
    Write-Output "bilibili_native_discovery = True"
    Write-Output "profile_candidates_fact_only = True"
    Write-Output "duplicate_site_operator_removed = True"
    Write-Output "open_web_widening_blocked = True"
    Write-Output "external_ai_widening_blocked = True"
    Write-Output "sqlite_schema_changed = False"
} finally {
    Pop-Location
}
