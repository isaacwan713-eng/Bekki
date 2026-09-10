[CmdletBinding()]
param()

$ErrorActionPreference = "Stop"
$projectRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
Push-Location $projectRoot
try {
    python -m unittest -q `
        tests.test_topic_lifecycle_isolation_v1_10_54_4 `
        tests.test_knowledge_curator_terminal_outcomes_v1_10_54_3_1 `
        tests.test_knowledge_curator_isolation_v1_10_54_3 `
        tests.test_knowledge_curator `
        tests.test_knowledge_category_granularity_v1_10_53 `
        tests.test_knowledge_taxonomy_v1_10_52 `
        tests.test_topic_lifecycle_autonomy `
        tests.test_stable_knowledge_review
    if ($LASTEXITCODE -ne 0) {
        throw "Topic Lifecycle isolation unit tests failed."
    }

@'
import hashlib
import json
from pathlib import Path
import sqlite3

import knowledge

root = Path.cwd()
database = (root / "data" / "bekki.sqlite3").resolve()
if not database.is_file():
    raise SystemExit("ERROR database_missing = " + str(database))

build = json.loads(
    (root / "BEKKI_BUILD.json").read_text(encoding="utf-8")
)
expected_build = "bekki-knowledge-visual-recall-v1-10-54-7-20260910"

uri = "file:" + database.as_posix() + "?mode=ro"
connection = sqlite3.connect(uri, uri=True)
try:
    connection.execute("PRAGMA query_only=ON")
    quick_check = connection.execute("PRAGMA quick_check").fetchone()[0]
    schema_version = connection.execute("PRAGMA user_version").fetchone()[0]
    query_only = connection.execute("PRAGMA query_only").fetchone()[0]
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
topic_documents = {
    key[len("knowledge/knowledge/topics/"):-len(".json")]: value
    for key, value in documents.items()
    if key.startswith("knowledge/knowledge/topics/")
    and key.endswith(".json")
    and isinstance(value, dict)
}
lifecycle_audit = knowledge.audit_topic_lifecycle_payloads(
    ledger=ledger,
    topic_documents=topic_documents,
)
lifecycle_counts = lifecycle_audit.get("counts", {})
lifecycle_failures = lifecycle_audit.get("failures", [])

curator_runs = documents.get("knowledge/knowledge/curator_runs.json")
curator_runs = curator_runs if isinstance(curator_runs, dict) else {}
isolated_lifecycle_runs = []
for row in curator_runs.get("runs", []):
    if not isinstance(row, dict):
        continue
    details = row.get("details")
    details = details if isinstance(details, dict) else {}
    autonomy = details.get("topic_autonomy")
    autonomy = autonomy if isinstance(autonomy, dict) else {}
    if int(autonomy.get(
        "topic_lifecycle_isolation_contract_version"
    ) or 0) >= 1:
        isolated_lifecycle_runs.append(autonomy)

latest_autonomy = (
    isolated_lifecycle_runs[-1] if isolated_lifecycle_runs else {}
)
latest_autonomy_failures = []
if latest_autonomy:
    if int(latest_autonomy.get(
        "topic_lifecycle_assessment_contract_version"
    ) or 0) != 1:
        latest_autonomy_failures.append("assessment_contract_version")
    if str(latest_autonomy.get("status") or "") not in {
        "COMPLETED", "COMPLETED_WITH_ERRORS", "FAILED", "SKIPPED",
    }:
        latest_autonomy_failures.append("status")
    selected = {
        str(value) for value in latest_autonomy.get("selected_topic_ids", [])
        if str(value)
    }
    restricted = {
        str(value) for value in latest_autonomy.get("restricted_topic_ids", [])
        if str(value)
    }
    if restricted and not selected.issubset(restricted):
        latest_autonomy_failures.append("selection_escaped_restriction")

lifecycle_source = (
    root / "nerv" / "topic_lifecycle.py"
).read_text(encoding="utf-8")
knowledge_source = (root / "knowledge.py").read_text(encoding="utf-8")
curator_source = (
    root / "nerv" / "knowledge_curator.py"
).read_text(encoding="utf-8")
worker_source = (root / "knowledge_worker.py").read_text(encoding="utf-8")
prompt_source = (
    root / "prompts" / "nerv_topic_lifecycle.txt"
).read_text(encoding="utf-8")
recovery_prompt = (
    root / "prompts" / "nerv_topic_lifecycle_recovery.txt"
).read_text(encoding="utf-8")
recovery_prompt_compact = " ".join(recovery_prompt.split())
main_source = (root / "main.py").read_text(encoding="utf-8")

isolation_wiring = all([
    "TOPIC_LIFECYCLE_ISOLATION_CONTRACT_VERSION = 1" in lifecycle_source,
    "MAX_TOPIC_LIFECYCLE_INPUT_BYTES = 12_000" in lifecycle_source,
    "required_assessment_fingerprint" in lifecycle_source,
    "assessment_fingerprint_mismatch" in lifecycle_source,
    "intentionally absent" in lifecycle_source,
    "invalid_first_assessment" not in lifecycle_source,
    "include_topic_ids=restricted" in lifecycle_source,
    "eligible_topic_ids=restricted" in lifecycle_source,
    "COMPLETED_WITH_ERRORS" in lifecycle_source,
    "topic_lifecycle_assessment_snapshot_stale" in knowledge_source,
    "audit_topic_lifecycle_payloads" in knowledge_source,
    "only_topic_ids=(touched_topic_ids or None)" in curator_source,
    "topic_lifecycle_isolation_contract_version" in worker_source,
    "required_assessment_fingerprint" in prompt_source,
    "intentionally not included" in recovery_prompt_compact,
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
build_wiring = all([
    build.get("build_id") == expected_build,
    build.get("package_id") == expected_build,
    build.get("update_kind") == "Knowledge Visual Recall V1.10.54.7",
    expected_build in main_source,
])

topic_count = int(lifecycle_counts.get("topics") or 0)
contract_count = (
    int(lifecycle_counts.get("contract_current") or 0)
    + int(lifecycle_counts.get("legacy_compatible") or 0)
)
contract_accounting_valid = contract_count == topic_count

print("quick_check =", quick_check)
print("schema_version =", schema_version)
print("validation_mode = read_only")
print("sqlite_query_only =", bool(query_only))
print("topic_lifecycle_assessment_contract_version =",
      lifecycle_audit.get("contract_version"))
print("topic_lifecycle_isolation_contract_version =", 1)
print("topic_documents =", topic_count)
print("lifecycle_counts =", lifecycle_counts)
print("lifecycle_outcomes =", lifecycle_audit.get("outcomes", []))
print("lifecycle_failures =", lifecycle_failures)
print("contract_accounting_valid =", contract_accounting_valid)
print("isolated_lifecycle_runs =", len(isolated_lifecycle_runs))
print("latest_isolated_lifecycle_status =",
      latest_autonomy.get("status") or None)
print("latest_autonomy_failures =", latest_autonomy_failures)
print("isolation_wiring =", isolation_wiring)
print("build_wiring =", build_wiring)
print("mirror_failures =", mirror_failures)
print("companion_watch_guard =", companion_watch_guard)
print("payload_hash_failures =", payload_hash_failures)

failures = any([
    quick_check != "ok",
    schema_version != 2,
    not bool(query_only),
    lifecycle_audit.get("contract_version") != 1,
    topic_count < 1,
    lifecycle_failures,
    not contract_accounting_valid,
    latest_autonomy_failures,
    not isolation_wiring,
    not build_wiring,
    mirror_failures,
    not companion_watch_guard,
    payload_hash_failures,
])
if failures:
    raise SystemExit(
        "Topic Lifecycle isolation live SQLite validation failed."
    )
'@ | python -
    if ($LASTEXITCODE -ne 0) {
        throw "Topic Lifecycle isolation live SQLite validation failed."
    }
} finally {
    Pop-Location
}
