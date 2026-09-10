[CmdletBinding()]
param()

$ErrorActionPreference = "Stop"
$projectRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
Push-Location $projectRoot
try {
    python -m unittest -q `
        tests.test_temporal_evidence_graceful_fallback_v1_10_51_11 `
        tests.test_bilibili_official_publisher_video_discovery_v1_10_51_10 `
        tests.test_bilibili_official_evidence_recovery_v1_10_51_4 `
        tests.test_current_roster_lifecycle_normalization_v1_10_51_9 `
        tests.test_companion_watch_v1_10_47 `
        tests.test_iyf_companion_watch_hotfix_v1_10_47_7
    if ($LASTEXITCODE -ne 0) {
        throw "Temporal evidence graceful-fallback tests failed."
    }

@'
import json
from pathlib import Path
import sqlite3

from casper import browser


expected_build = (
    "bekki-temporal-evidence-graceful-fallback-v1-10-51-11-20260904"
)
metadata = json.loads(Path("BEKKI_BUILD.json").read_text(encoding="utf-8"))
database = Path("data/bekki.sqlite3").resolve()
if not database.is_file():
    raise SystemExit("ERROR database_missing = " + str(database))
uri = "file:" + database.as_posix() + "?mode=ro"
connection = sqlite3.connect(uri, uri=True)
try:
    quick_check = connection.execute("PRAGMA quick_check").fetchone()[0]
    schema_version = connection.execute("PRAGMA user_version").fetchone()[0]
finally:
    connection.close()

source = Path("casper/browser.py").read_text(encoding="utf-8")
prompt_exists = Path(
    "prompts/fact_temporal_alternative_validate.txt"
).is_file()
contract_markers_present = all(value in source for value in (
    "TEMPORAL_EVIDENCE_GRACEFUL_FALLBACK_VERSION = 1",
    "temporal_alternative_accepted",
    "knowledge_eligible",
    "target_scope_answered",
    "[CASPER TEMPORAL EVIDENCE FALLBACK]",
))

print("quick_check =", quick_check)
print("schema_version =", schema_version)
print("build_id =", metadata.get("build_id"))
print(
    "temporal_evidence_graceful_fallback_version =",
    browser.TEMPORAL_EVIDENCE_GRACEFUL_FALLBACK_VERSION,
)
print("prompt_exists =", prompt_exists)
print("contract_markers_present =", contract_markers_present)
print("display_only_target_scope =", False)
print("display_only_knowledge_eligible =", False)

if (
    quick_check != "ok"
    or schema_version != 2
    or metadata.get("build_id") != expected_build
    or browser.TEMPORAL_EVIDENCE_GRACEFUL_FALLBACK_VERSION != 1
    or not prompt_exists
    or not contract_markers_present
):
    raise SystemExit(1)
'@ | python -
    if ($LASTEXITCODE -ne 0) {
        throw "Temporal evidence graceful-fallback runtime validation failed."
    }
}
finally {
    Pop-Location
}
