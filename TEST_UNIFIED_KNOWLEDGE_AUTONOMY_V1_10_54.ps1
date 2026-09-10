[CmdletBinding()]
param()

$ErrorActionPreference = "Stop"
$projectRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
Push-Location $projectRoot
try {
    python -m unittest -q `
        tests.test_unified_knowledge_autonomy_v1_10_54 `
        tests.test_knowledge_category_granularity_v1_10_53 `
        tests.test_topic_lifecycle_autonomy `
        tests.test_stable_knowledge_review
    if ($LASTEXITCODE -ne 0) {
        throw "Unified Knowledge autonomy unit tests failed."
    }

@'
import hashlib
import json
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

ledger = documents.get("knowledge/knowledge.json")
ledger = ledger if isinstance(ledger, list) else []
logs = documents.get("knowledge/learning_logs.json")
logs = logs if isinstance(logs, list) else []
topic_documents = {
    key.rsplit("/", 1)[-1].removesuffix(".json"): value
    for key, value in documents.items()
    if key.startswith("knowledge/knowledge/topics/") and isinstance(value, dict)
}

autonomy_rows = [
    row for row in logs
    if isinstance(row, dict)
    and int(row.get("autonomy_contract_version") or 0) >= 1
]
single_topic_failures = []
selection_lifecycle_failures = []
valid_modes = {
    "REVIEW_DUE", "AUTO_INTEREST_REFRESH", "OPEN_GAP", "BACKGROUND_PROFILE",
}
for index, row in enumerate(autonomy_rows):
    selected = [str(value) for value in row.get("selected_topic_ids", [])]
    mode = str(row.get("selection_mode") or "")
    if len(selected) > 1:
        single_topic_failures.append(index)
    if mode not in valid_modes:
        selection_lifecycle_failures.append(str(index) + ":invalid_mode")
    for topic_id in selected:
        document = topic_documents.get(topic_id)
        if not isinstance(document, dict):
            continue
        lifecycle = document.get("lifecycle")
        lifecycle = lifecycle if isinstance(lifecycle, dict) else {}
        state = str(lifecycle.get("state") or "")
        if state == "ACTIVE" and mode != "OPEN_GAP":
            selection_lifecycle_failures.append(topic_id + ":active_mode")
        if state == "PAUSED_COMPLETE" and mode not in {
            "REVIEW_DUE", "AUTO_INTEREST_REFRESH"
        }:
            selection_lifecycle_failures.append(topic_id + ":paused_mode")

transient_active_failures = []
autonomy_record_failures = []
now = datetime.now(timezone.utc)
for item in ledger:
    if not isinstance(item, dict):
        continue
    knowledge_type = str(item.get("knowledge_type") or "stable").lower()
    status = str(item.get("status") or "")
    if status == "verified" and knowledge_type in {"changing", "event", "news"}:
        transient_active_failures.append(str(item.get("id") or "unknown"))
    provenance = item.get("provenance")
    provenance = provenance if isinstance(provenance, dict) else {}
    if provenance.get("autonomous_learning") is not True:
        continue
    record_id = str(item.get("id") or "unknown")
    lifecycle = item.get("lifecycle_audit")
    lifecycle = lifecycle if isinstance(lifecycle, dict) else {}
    if status == "verified" and (
        knowledge_type not in {"stable", "reviewable"}
        or lifecycle.get("status") != "PASSED"
        or not item.get("sources")
    ):
        autonomy_record_failures.append(record_id)
    if status == "verified" and knowledge_type == "reviewable":
        try:
            expiry = datetime.fromisoformat(
                str(item.get("expires_at") or "").replace("Z", "+00:00")
            )
            if expiry.tzinfo is None:
                expiry = expiry.replace(tzinfo=timezone.utc)
            if expiry <= now:
                autonomy_record_failures.append(record_id + ":expired")
        except (TypeError, ValueError):
            autonomy_record_failures.append(record_id + ":expiry")

main_source = (root / "main.py").read_text(encoding="utf-8")
scheduler_source = (root / "knowledge_scheduler.py").read_text(encoding="utf-8")
worker_source = (root / "knowledge_worker.py").read_text(encoding="utf-8")
unified_scheduler_wiring = all([
    'knowledge_worker.run_autonomy_cycle(trigger="desktop_idle")' in main_source,
    'trigger="windows_scheduler"' in scheduler_source,
    "def run_autonomy_cycle(" in worker_source,
])
companion_watch_guard = (
    "knowledge_autonomy_thread," in main_source
    and "if current_thread is not None or _companion_watch_owns_idle_time()" in main_source
)
learning_log_sqlite_present = "knowledge/learning_logs.json" in documents

print("quick_check =", quick_check)
print("schema_version =", schema_version)
print("autonomy_contract_version =", 1)
print("priority_order =", "refresh_due_then_interest")
print("single_topic_limit =", 1)
print("topic_documents =", len(topic_documents))
print("learning_log_sqlite_present =", learning_log_sqlite_present)
print("learning_log_rows =", len(logs))
print("autonomy_log_rows =", len(autonomy_rows))
print("single_topic_failures =", single_topic_failures)
print("selection_lifecycle_failures =", selection_lifecycle_failures)
print("transient_active_failures =", transient_active_failures)
print("autonomy_record_failures =", autonomy_record_failures)
print("unified_scheduler_wiring =", unified_scheduler_wiring)
print("companion_watch_guard =", companion_watch_guard)
print("payload_hash_failures =", payload_hash_failures)

failures = any([
    quick_check != "ok",
    schema_version != 2,
    not learning_log_sqlite_present,
    single_topic_failures,
    selection_lifecycle_failures,
    transient_active_failures,
    autonomy_record_failures,
    not unified_scheduler_wiring,
    not companion_watch_guard,
    payload_hash_failures,
])
if failures:
    raise SystemExit("Unified Knowledge autonomy live SQLite validation failed.")
'@ | python -
    if ($LASTEXITCODE -ne 0) {
        throw "Unified Knowledge autonomy live SQLite validation failed."
    }
} finally {
    Pop-Location
}
