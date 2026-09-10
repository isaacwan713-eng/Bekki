[CmdletBinding()]
param()

$ErrorActionPreference = "Stop"
$projectRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
Push-Location $projectRoot
try {
    python -m unittest -q `
        tests.test_knowledge_curator_terminal_outcomes_v1_10_54_3_1 `
        tests.test_knowledge_curator_isolation_v1_10_54_3 `
        tests.test_knowledge_curator `
        tests.test_knowledge_judge_isolation_v1_10_54_2 `
        tests.test_knowledge_source_recovery_v1_10_54_1 `
        tests.test_unified_knowledge_autonomy_v1_10_54 `
        tests.test_knowledge_category_granularity_v1_10_53 `
        tests.test_topic_lifecycle_autonomy `
        tests.test_stable_knowledge_review
    if ($LASTEXITCODE -ne 0) {
        throw "Knowledge Curator isolation unit tests failed."
    }

@'
import hashlib
import json
from collections import Counter
from pathlib import Path
import sqlite3

import knowledge

root = Path.cwd()
database = (root / "data" / "bekki.sqlite3").resolve()
if not database.is_file():
    raise SystemExit("ERROR database_missing = " + str(database))

uri = "file:" + database.as_posix() + "?mode=ro"
connection = sqlite3.connect(uri, uri=True)
try:
    quick_check = connection.execute("PRAGMA quick_check").fetchone()[0]
    schema_version = connection.execute("PRAGMA user_version").fetchone()[0]
    rows = connection.execute(
        "SELECT namespace, document_key, payload, payload_sha256 "
        "FROM json_documents WHERE namespace IN ('knowledge', 'nerv')"
    ).fetchall()
finally:
    connection.close()

documents = {}
payload_hash_failures = []
for namespace, key, payload, expected_hash in rows:
    identity = namespace + "/" + key
    if hashlib.sha256(payload.encode("utf-8")).hexdigest() != expected_hash:
        payload_hash_failures.append(identity)
    try:
        documents[identity] = json.loads(payload)
    except json.JSONDecodeError:
        payload_hash_failures.append(identity + ":invalid_json")

ledger = documents.get("knowledge/knowledge.json")
ledger = ledger if isinstance(ledger, list) else []
inbox = documents.get("knowledge/knowledge/inbox.json")
inbox = inbox if isinstance(inbox, dict) else {}
inbox_items = [
    value for value in inbox.get("items", []) if isinstance(value, dict)
]
curator_runs = documents.get("knowledge/knowledge/curator_runs.json")
curator_runs = curator_runs if isinstance(curator_runs, dict) else {}
runs = [
    value for value in curator_runs.get("runs", [])
    if isinstance(value, dict)
]

def safe_int(value, default=0):
    try:
        return int(value or 0)
    except (TypeError, ValueError):
        return default

isolated_runs = []
for row in runs:
    details = row.get("details")
    details = details if isinstance(details, dict) else {}
    if safe_int(details.get("curator_isolation_contract_version")) >= 1:
        isolated_runs.append(row)
latest_isolated = isolated_runs[-1] if isolated_runs else {}
latest_details = latest_isolated.get("details")
latest_details = latest_details if isinstance(latest_details, dict) else {}
latest_status = str(latest_isolated.get("status") or "")

inbox_id_counts = Counter(
    str(value.get("knowledge_id") or "")
    for value in inbox_items
    if str(value.get("knowledge_id") or "")
)
duplicate_inbox_ids = sorted(
    value for value, count in inbox_id_counts.items() if count > 1
)

pending_ids = {
    str(value.get("knowledge_id") or "")
    for value in inbox_items
    if str(value.get("state") or "").upper() == "PENDING"
}

topic_documents = {
    key[len("knowledge/knowledge/topics/"):-len(".json")]: value
    for key, value in documents.items()
    if key.startswith("knowledge/knowledge/topics/")
    and key.endswith(".json")
    and isinstance(value, dict)
}
conflicts = documents.get("knowledge/knowledge/conflicts.json")
conflicts = conflicts if isinstance(conflicts, dict) else {}
terminal_audit = knowledge.audit_curator_terminal_outcome_payloads(
    ledger=ledger,
    inbox=inbox,
    topic_documents=topic_documents,
    conflicts=conflicts,
)
terminal_outcome_failures = terminal_audit.get("failures", [])

curator_source = (root / "nerv" / "knowledge_curator.py").read_text(
    encoding="utf-8"
)
knowledge_source = (root / "knowledge.py").read_text(encoding="utf-8")
worker_source = (root / "knowledge_worker.py").read_text(encoding="utf-8")
prompt_source = (
    root / "prompts" / "nerv_daily_knowledge_curator.txt"
).read_text(encoding="utf-8")
recovery_prompt = (
    root / "prompts" / "nerv_daily_knowledge_curator_recovery.txt"
).read_text(encoding="utf-8")
main_source = (root / "main.py").read_text(encoding="utf-8")

isolation_wiring = all([
    "MAX_BATCH_ITEMS = 1" in curator_source,
    "CURATOR_PLAN_CONTRACT_VERSION = 2" in curator_source,
    "CURATOR_ISOLATION_CONTRACT_VERSION = 1" in curator_source,
    "MAX_CURATOR_PACKET_BYTES = 12000" in curator_source,
    "current_verified_item" in curator_source,
    "required_curation_fingerprint" in curator_source,
    "relevant_topic_ecosystems" in curator_source,
    "[NERV KNOWLEDGE CURATOR ITEM WARNING]" in curator_source,
    "COMPLETED_WITH_ERRORS" in curator_source,
    "CURATOR_TERMINAL_OUTCOME_CONTRACT_VERSION = 1" in knowledge_source,
    "audit_curator_terminal_outcome_payloads" in knowledge_source,
    "knowledge_curator_isolation_contract_version" in worker_source,
    "curator_terminal_outcome_contract_version" in worker_source,
    "current_verified_item" in prompt_source,
    "required_curation_fingerprint" in prompt_source,
    "intentionally absent" in recovery_prompt,
    "invalid first plan" not in recovery_prompt.casefold(),
])
mirror_failures = [
    name for name in (
        "knowledge.py", "knowledge_ai.py", "knowledge_worker.py",
        "knowledge_autonomy.py", "knowledge_scheduler.py",
    )
    if (root / name).read_bytes() != (root / "casper" / name).read_bytes()
]
companion_watch_guard = (
    "knowledge_autonomy_thread," in main_source
    and "if current_thread is not None or _companion_watch_owns_idle_time()"
        in main_source
)

latest_run_failures = []
if isolated_runs:
    if safe_int(latest_details.get("curator_plan_contract_version")) != 2:
        latest_run_failures.append("plan_contract_version")
    if latest_status not in {"COMPLETED", "COMPLETED_WITH_ERRORS", "FAILED"}:
        latest_run_failures.append("status")
    processed = safe_int(latest_details.get("processed"))
    committed = safe_int(latest_details.get("committed"))
    failed = safe_int(latest_details.get("failed"))
    if committed + failed != processed:
        latest_run_failures.append("processed_accounting")

print("quick_check =", quick_check)
print("schema_version =", schema_version)
print("curator_plan_contract_version =", 2)
print("curator_isolation_contract_version =", 1)
print("curator_terminal_outcome_contract_version =",
      terminal_audit.get("contract_version"))
print("isolated_curator_runs =", len(isolated_runs))
print("latest_isolated_status =", latest_status or None)
print("latest_isolated_counts =", {
    key: safe_int(latest_details.get(key))
    for key in (
        "processed", "committed", "curated", "duplicate", "conflict",
        "deferred", "primary_valid", "recovered_valid", "failed",
    )
})
print("terminal_outcome_counts =", terminal_audit.get("counts", {}))
print("terminal_outcomes =", terminal_audit.get("outcomes", []))
print("terminal_outcome_failures =", terminal_outcome_failures)
print("pending_curation_rows =", len(pending_ids))
print("duplicate_inbox_ids =", duplicate_inbox_ids)
print("latest_run_failures =", latest_run_failures)
print("isolation_wiring =", isolation_wiring)
print("mirror_failures =", mirror_failures)
print("companion_watch_guard =", companion_watch_guard)
print("payload_hash_failures =", payload_hash_failures)

failures = any([
    quick_check != "ok",
    schema_version != 2,
    terminal_audit.get("contract_version") != 1,
    terminal_outcome_failures,
    duplicate_inbox_ids,
    latest_run_failures,
    not isolation_wiring,
    mirror_failures,
    not companion_watch_guard,
    payload_hash_failures,
])
if failures:
    raise SystemExit(
        "Knowledge Curator terminal-outcome live SQLite validation failed."
    )
'@ | python -
    if ($LASTEXITCODE -ne 0) {
        throw "Knowledge Curator terminal-outcome live SQLite validation failed."
    }
} finally {
    Pop-Location
}
