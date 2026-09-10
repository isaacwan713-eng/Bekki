[CmdletBinding()]
param()

$ErrorActionPreference = "Stop"
$projectRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
Push-Location $projectRoot
try {
    python -m unittest -q `
        tests.test_knowledge_source_recovery_v1_10_54_1 `
        tests.test_unified_knowledge_autonomy_v1_10_54 `
        tests.test_knowledge_category_granularity_v1_10_53 `
        tests.test_topic_lifecycle_autonomy `
        tests.test_stable_knowledge_review
    if ($LASTEXITCODE -ne 0) {
        throw "Knowledge source recovery unit tests failed."
    }

@'
import hashlib
import json
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
import sqlite3

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

logs = documents.get("knowledge/learning_logs.json")
logs = logs if isinstance(logs, list) else []
candidates = documents.get("knowledge/knowledge_source_candidates.json")
candidates = candidates if isinstance(candidates, list) else []
ledger = documents.get("knowledge/knowledge.json")
ledger = ledger if isinstance(ledger, list) else []

def evidence_count(row):
    total = 0
    for key in ("verified", "updated", "duplicate", "log_only"):
        try:
            total += max(0, int(row.get(key) or 0))
        except (TypeError, ValueError):
            pass
    return total

autonomy_rows = [
    row for row in logs
    if isinstance(row, dict)
    and int(row.get("autonomy_contract_version") or 0) >= 1
]
source_recovery_rows = [
    row for row in autonomy_rows
    if int(row.get("source_recovery_contract_version") or 0) >= 1
]
explicit_no_evidence_rows = [
    row for row in autonomy_rows
    if str(row.get("status") or "").upper() == "NO_VERIFIED_EVIDENCE"
]
legacy_zero_evidence_rows = [
    row for row in autonomy_rows
    if int(row.get("source_recovery_contract_version") or 0) < 1
    and str(row.get("status") or "").upper() in {
        "COMPLETED", "COMPLETED_WITH_ERRORS"
    }
    and "verified" in row
    and evidence_count(row) == 0
]
outcome_failures = []
for index, row in enumerate(autonomy_rows):
    status = str(row.get("status") or "").upper()
    evidence = evidence_count(row)
    if status == "NO_VERIFIED_EVIDENCE" and evidence != 0:
        outcome_failures.append(str(index) + ":no_evidence_has_evidence")
    if (
        int(row.get("source_recovery_contract_version") or 0) >= 1
        and status in {"COMPLETED", "COMPLETED_WITH_ERRORS"}
        and evidence == 0
    ):
        outcome_failures.append(str(index) + ":false_completion")

retry_metadata_failures = []
new_domain_counts = Counter()
now = datetime.now(timezone.utc)
for index, item in enumerate(candidates):
    if not isinstance(item, dict):
        continue
    if int(item.get("discovery_contract_version") or 0) >= 2:
        domain = str(item.get("domain") or "").lower()
        if domain:
            new_domain_counts[domain] += 1
    if str(item.get("last_attempt_status") or "") != "READ_ERROR":
        continue
    try:
        last_attempt = datetime.fromisoformat(
            str(item.get("last_attempt_at") or "").replace("Z", "+00:00")
        )
        retry_after = datetime.fromisoformat(
            str(item.get("retry_after") or "").replace("Z", "+00:00")
        )
        if last_attempt.tzinfo is None:
            last_attempt = last_attempt.replace(tzinfo=timezone.utc)
        if retry_after.tzinfo is None:
            retry_after = retry_after.replace(tzinfo=timezone.utc)
        if retry_after <= last_attempt:
            retry_metadata_failures.append(str(index) + ":retry_order")
    except (TypeError, ValueError):
        retry_metadata_failures.append(str(index) + ":retry_timestamp")

domain_cap_failures = [
    domain for domain, count in new_domain_counts.items() if count > 3
]
transient_active_failures = [
    str(item.get("id") or "unknown")
    for item in ledger
    if isinstance(item, dict)
    and str(item.get("status") or "") == "verified"
    and str(item.get("knowledge_type") or "stable").lower()
        in {"changing", "event", "news"}
]

worker_source = (root / "knowledge_worker.py").read_text(encoding="utf-8")
autonomy_source = (root / "knowledge_autonomy.py").read_text(encoding="utf-8")
scheduler_source = (root / "knowledge_scheduler.py").read_text(encoding="utf-8")
main_source = (root / "main.py").read_text(encoding="utf-8")
source_recovery_wiring = all([
    'phase="PRIMARY"' in worker_source,
    'phase="FALLBACK"' in worker_source,
    'status = "NO_VERIFIED_EVIDENCE"' in worker_source,
    "NO_EVIDENCE_RETRY_HOURS = 24" in autonomy_source,
    "knowledge_autonomy.is_successful_run(log)" in scheduler_source,
])
companion_watch_guard = (
    "knowledge_autonomy_thread," in main_source
    and "if current_thread is not None or _companion_watch_owns_idle_time()"
        in main_source
)

print("quick_check =", quick_check)
print("schema_version =", schema_version)
print("source_discovery_contract_version =", 2)
print("source_recovery_contract_version =", 1)
print("no_evidence_retry_hours =", 24)
print("learning_log_rows =", len(logs))
print("autonomy_log_rows =", len(autonomy_rows))
print("source_recovery_rows =", len(source_recovery_rows))
print("explicit_no_evidence_rows =", len(explicit_no_evidence_rows))
print("legacy_zero_evidence_rows =", len(legacy_zero_evidence_rows))
print("outcome_failures =", outcome_failures)
print("retry_metadata_failures =", retry_metadata_failures)
print("domain_cap_failures =", domain_cap_failures)
print("transient_active_failures =", transient_active_failures)
print("source_recovery_wiring =", source_recovery_wiring)
print("companion_watch_guard =", companion_watch_guard)
print("payload_hash_failures =", payload_hash_failures)

failures = any([
    quick_check != "ok",
    schema_version != 2,
    outcome_failures,
    retry_metadata_failures,
    domain_cap_failures,
    transient_active_failures,
    not source_recovery_wiring,
    not companion_watch_guard,
    payload_hash_failures,
])
if failures:
    raise SystemExit("Knowledge source recovery live SQLite validation failed.")
'@ | python -
    if ($LASTEXITCODE -ne 0) {
        throw "Knowledge source recovery live SQLite validation failed."
    }
} finally {
    Pop-Location
}
