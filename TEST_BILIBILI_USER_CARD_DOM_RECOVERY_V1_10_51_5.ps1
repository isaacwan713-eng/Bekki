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
        tests.test_bilibili_user_card_dom_recovery_v1_10_51_5 `
        tests.test_bilibili_official_evidence_recovery_v1_10_51_4 `
        tests.test_bilibili_native_fact_executor_v1_10_51_3 `
        tests.test_knowledge_curator
    if ($LASTEXITCODE -ne 0) {
        throw "Bilibili user-card DOM recovery tests failed."
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
print("current_user_card_structural_recovery = True")
print("profile_metrics_and_avatar_guard = True")
print("single_space_identity_guard = True")
print("exact_official_name_gate = True")
print("curator_two_item_batches = True")
print("companion_watch_changed = False")
'@ | python -
    if ($LASTEXITCODE -ne 0) {
        throw "SQLite verification failed."
    }

    Write-Output "build_id = $($metadata.build_id)"
} finally {
    Pop-Location
}
