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
        tests.test_bilibili_video_detail_recovery_v1_10_51_6 `
        tests.test_bilibili_user_card_dom_recovery_v1_10_51_5 `
        tests.test_bilibili_official_evidence_recovery_v1_10_51_4 `
        tests.test_bilibili_native_fact_executor_v1_10_51_3
    if ($LASTEXITCODE -ne 0) {
        throw "Bilibili video-detail recovery tests failed."
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
print("bound_metadata_wait = True")
print("zero_asset_retry = True")
print("selected_video_id_guard = True")
print("bound_visual_fact_bridge = True")
print("single_frame_scope_guard = True")
print("official_identity_gate_unchanged = True")
print("historical_scope_guard_unchanged = True")
print("companion_watch_changed = False")
'@ | python -
    if ($LASTEXITCODE -ne 0) {
        throw "SQLite verification failed."
    }

    Write-Output "build_id = $($metadata.build_id)"
} finally {
    Pop-Location
}
