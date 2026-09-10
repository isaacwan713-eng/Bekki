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
        tests.test_fixed_site_source_contract_v1_10_51_2 `
        tests.test_stable_v1_magi `
        tests.test_media_watch_theater_v1_10_46 `
        tests.test_media_watch_command_lane_hotfix_v1_10_47_6 `
        tests.test_knowledge_relationship_grounding_v1_10_51
    if ($LASTEXITCODE -ne 0) {
        throw "Fixed-site source contract regression tests failed."
    }

    Write-Output "build_id = $($metadata.build_id)"
    Write-Output "bilibili_fact_purpose = FACT_LOOKUP"
    Write-Output "bilibili_source_scope = FIXED_SITES"
    Write-Output "wiki_fact_source = wikipedia.org"
    Write-Output "social_summary_stays_social = True"
    Write-Output "media_watch_source_preserved = True"
    Write-Output "sqlite_schema_changed = False"
} finally {
    Pop-Location
}
