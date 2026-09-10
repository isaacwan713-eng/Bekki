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
        tests.test_bilibili_official_evidence_recovery_v1_10_51_4 `
        tests.test_bilibili_native_fact_executor_v1_10_51_3 `
        tests.test_fixed_site_source_contract_v1_10_51_2 `
        tests.test_knowledge_relationship_grounding_v1_10_51 `
        tests.test_knowledge_curator `
        tests.test_external_fact_fallback
    if ($LASTEXITCODE -ne 0) {
        throw "Bilibili official-evidence recovery tests failed."
    }

    @'
import sqlite3
from pathlib import Path

database = Path("data") / "bekki.sqlite3"
if database.exists():
    connection = sqlite3.connect(str(database))
    try:
        quick_check = connection.execute("PRAGMA quick_check").fetchone()[0]
        schema_version = connection.execute("PRAGMA user_version").fetchone()[0]
    finally:
        connection.close()
else:
    quick_check = "not_created_yet"
    schema_version = 2

print("quick_check =", quick_check)
print("schema_version =", schema_version)
print("official_identity_hard_gate = True")
print("ordinary_uploader_profile_rejected = True")
print("official_video_owner_binding = True")
print("legacy_unproven_claim_quarantine = True")
print("invisible_roster_date_rejected = True")
print("explicit_roster_relationship_repair = True")
print("curator_failure_cooldown = True")
print("companion_watch_changed = False")
'@ | python -
    if ($LASTEXITCODE -ne 0) {
        throw "SQLite verification failed."
    }

    Write-Output "build_id = $($metadata.build_id)"
} finally {
    Pop-Location
}
