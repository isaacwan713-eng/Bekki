[CmdletBinding()]
param()

$ErrorActionPreference = "Stop"
$projectRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
Push-Location $projectRoot
try {
    python -m unittest -q `
        tests.test_knowledge_judge_isolation_v1_10_54_2 `
        tests.test_knowledge_source_recovery_v1_10_54_1 `
        tests.test_unified_knowledge_autonomy_v1_10_54 `
        tests.test_knowledge_category_granularity_v1_10_53 `
        tests.test_topic_lifecycle_autonomy `
        tests.test_stable_knowledge_review
    if ($LASTEXITCODE -ne 0) {
        throw "Knowledge Judge isolation unit tests failed."
    }

@'
import hashlib
import json
from collections import Counter
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
ledger = documents.get("knowledge/knowledge.json")
ledger = ledger if isinstance(ledger, list) else []

def safe_int(value, default=0):
    try:
        return int(value or 0)
    except (TypeError, ValueError):
        return default

def evidence_count(row):
    return sum(
        max(0, safe_int(row.get(key)))
        for key in ("verified", "updated", "duplicate", "log_only")
    )

def judge_payload(row):
    value = row.get("knowledge_judge")
    return value if isinstance(value, dict) else {}

judge_rows = [
    row for row in logs
    if isinstance(row, dict)
    and safe_int(row.get("knowledge_judge_isolation_contract_version")) >= 1
]
invalid_judge_rows = [
    row for row in judge_rows
    if safe_int(judge_payload(row).get("invalid_json")) > 0
]
recovered_judge_rows = [
    row for row in judge_rows
    if safe_int(judge_payload(row).get("recovered_valid")) > 0
]

outcome_failures = []
for index, row in enumerate(judge_rows):
    status = str(row.get("status") or "").upper()
    evidence = evidence_count(row)
    judge = judge_payload(row)
    invalid = safe_int(judge.get("invalid_json"))
    if status == "NO_VERIFIED_EVIDENCE" and evidence != 0:
        outcome_failures.append(str(index) + ":no_evidence_has_evidence")
    if status in {"COMPLETED", "COMPLETED_WITH_ERRORS"} and evidence == 0:
        outcome_failures.append(str(index) + ":false_completion")
    if invalid and "Knowledge Judge" not in str(row.get("outcome_reason") or ""):
        outcome_failures.append(str(index) + ":judge_error_reason_missing")
    if invalid and safe_int(row.get("errors")) < invalid:
        outcome_failures.append(str(index) + ":judge_error_not_counted")
    if safe_int(row.get("candidates_extracted")) < sum(
        safe_int(judge.get(key))
        for key in ("primary_valid", "recovered_valid", "invalid_json")
    ):
        outcome_failures.append(str(index) + ":judge_count_exceeds_candidates")

identity_counts = Counter(
    str(item.get("id") or "")
    for item in ledger
    if isinstance(item, dict) and str(item.get("id") or "")
)
pending_identity_failures = sorted({
    str(item.get("id") or "")
    for item in ledger
    if isinstance(item, dict)
    and safe_int(item.get("pending_identity_contract_version")) >= 1
    and identity_counts[str(item.get("id") or "")] > 1
})

transient_active_failures = [
    str(item.get("id") or "unknown")
    for item in ledger
    if isinstance(item, dict)
    and str(item.get("status") or "").lower() == "verified"
    and str(item.get("knowledge_type") or "stable").lower()
        in {"changing", "event", "news"}
]

knowledge_ai_source = (root / "knowledge_ai.py").read_text(encoding="utf-8")
knowledge_source = (root / "knowledge.py").read_text(encoding="utf-8")
worker_source = (root / "knowledge_worker.py").read_text(encoding="utf-8")
prompt_source = (root / "prompts" / "knowledge_judge.txt").read_text(
    encoding="utf-8"
)
recovery_prompt = (
    root / "prompts" / "knowledge_judge_recover.txt"
).read_text(encoding="utf-8")
main_source = (root / "main.py").read_text(encoding="utf-8")

judge_isolation_wiring = all([
    "MAX_RELEVANT_EXISTING_ITEMS = 12" in knowledge_ai_source,
    "required_candidate_fingerprint" in knowledge_ai_source,
    '"_judge_output_status"] = "RECOVERED_VALID"' in knowledge_ai_source,
    '"_judge_output_status": "INVALID_JSON"' in knowledge_ai_source,
    "KNOWLEDGE_PENDING_IDENTITY_CONTRACT_VERSION = 1" in knowledge_source,
    '"wikipedia.org"' in worker_source,
    "knowledge_judge_isolation_contract_version" in worker_source,
    "pending_review" in prompt_source,
    "compact recovery mode" in recovery_prompt,
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

print("quick_check =", quick_check)
print("schema_version =", schema_version)
print("knowledge_judge_contract_version =", 2)
print("knowledge_judge_isolation_contract_version =", 1)
print("pending_identity_contract_version =", 1)
print("judge_log_rows =", len(judge_rows))
print("invalid_judge_rows =", len(invalid_judge_rows))
print("recovered_judge_rows =", len(recovered_judge_rows))
print("pending_knowledge_rows =", sum(
    1 for item in ledger
    if isinstance(item, dict)
    and str(item.get("status") or "").lower() == "pending_review"
))
print("outcome_failures =", outcome_failures)
print("pending_identity_failures =", pending_identity_failures)
print("transient_active_failures =", transient_active_failures)
print("judge_isolation_wiring =", judge_isolation_wiring)
print("mirror_failures =", mirror_failures)
print("companion_watch_guard =", companion_watch_guard)
print("payload_hash_failures =", payload_hash_failures)

failures = any([
    quick_check != "ok",
    schema_version != 2,
    outcome_failures,
    pending_identity_failures,
    transient_active_failures,
    not judge_isolation_wiring,
    mirror_failures,
    not companion_watch_guard,
    payload_hash_failures,
])
if failures:
    raise SystemExit("Knowledge Judge isolation live SQLite validation failed.")
'@ | python -
    if ($LASTEXITCODE -ne 0) {
        throw "Knowledge Judge isolation live SQLite validation failed."
    }
} finally {
    Pop-Location
}
