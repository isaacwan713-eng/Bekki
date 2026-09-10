[CmdletBinding()]
param()

$ErrorActionPreference = "Stop"
$projectRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
Push-Location $projectRoot
try {
    python -m unittest -q `
        tests.test_knowledge_evidence_index_bootstrap_hotfix_v1_10_54_5_1 `
        tests.test_knowledge_evidence_lineage_v1_10_54_5 `
        tests.test_knowledge_judge_isolation_v1_10_54_2 `
        tests.test_knowledge_source_recovery_v1_10_54_1 `
        tests.test_unified_knowledge_autonomy_v1_10_54 `
        tests.test_knowledge_curator_isolation_v1_10_54_3 `
        tests.test_topic_lifecycle_isolation_v1_10_54_4 `
        tests.test_bilibili_video_evidence_v1_10_41_4 `
        tests.test_nerv_knowledge_verification
    if ($LASTEXITCODE -ne 0) {
        throw "Knowledge evidence lineage unit tests failed."
    }

@'
import hashlib
import json
from pathlib import Path
import sqlite3

import knowledge_evidence

root = Path.cwd()
data_dir = (root / "data").resolve()
database = data_dir / "bekki.sqlite3"
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
        "FROM json_documents WHERE namespace = 'knowledge'"
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

ledger_document_present = isinstance(
    documents.get("knowledge/knowledge.json"), list
)
ledger = documents.get("knowledge/knowledge.json")
ledger = ledger if ledger_document_present else []
media_index_document_present = isinstance(
    documents.get("knowledge/knowledge/media/index.json"), dict
)
media_index = documents.get("knowledge/knowledge/media/index.json")
media_index = media_index if media_index_document_present else {
    "schema_version": knowledge_evidence.KNOWLEDGE_MEDIA_INDEX_VERSION,
    "assets": {},
}
evidence_audit = knowledge_evidence.audit_evidence_store(
    ledger,
    data_dir=str(data_dir),
    media_index=media_index,
    verify_files=True,
)
counts = evidence_audit.get("counts", {})
evidence_failures = evidence_audit.get("failures", [])
media_index_required = knowledge_evidence.media_index_document_required(
    evidence_audit
)
media_index_state_valid = (
    media_index_document_present or not media_index_required
)

raw_image_payload_failures = []
for item in ledger:
    if not isinstance(item, dict):
        continue
    bundle = item.get("evidence_bundle")
    if not isinstance(bundle, dict):
        continue
    rendered = json.dumps(bundle, ensure_ascii=False)
    if "_image_payloads" in rendered or "data:image/" in rendered:
        raw_image_payload_failures.append(str(item.get("id") or "unknown"))

evidence_source = (root / "knowledge_evidence.py").read_text(encoding="utf-8")
knowledge_source = (root / "knowledge.py").read_text(encoding="utf-8")
knowledge_ai_source = (root / "knowledge_ai.py").read_text(encoding="utf-8")
worker_source = (root / "knowledge_worker.py").read_text(encoding="utf-8")
tools_source = (root / "tools.py").read_text(encoding="utf-8")
browser_source = (root / "casper" / "browser.py").read_text(encoding="utf-8")
curator_source = (
    root / "nerv" / "knowledge_curator.py"
).read_text(encoding="utf-8")
main_source = (root / "main.py").read_text(encoding="utf-8")

evidence_wiring = all([
    "KNOWLEDGE_EVIDENCE_CONTRACT_VERSION = 1" in evidence_source,
    "KNOWLEDGE_MEDIA_INDEX_VERSION = 1" in evidence_source,
    "privacy_class\") or \"\"" in evidence_source,
    "USER_UPLOAD" in evidence_source,
    "LITERAL_SOURCE_EXCERPT" in evidence_source,
    "SOURCE_BOUND_VISUAL_OBSERVATION" in evidence_source,
    "audit_evidence_store" in evidence_source,
    "media_index_document_required" in evidence_source,
    "load_knowledge_evidence" in knowledge_source,
    "audit_knowledge_evidence" in knowledge_source,
    "required_evidence_fingerprint" in knowledge_ai_source,
    "missing_literal_source_excerpt" in worker_source,
    "TEXT_AND_IMAGE" in tools_source,
    "Keep the exact opened-source frames available" in browser_source,
    "source_evidence" in curator_source,
])

mirror_failures = [
    name for name in (
        "knowledge.py", "knowledge_ai.py", "knowledge_evidence.py",
        "knowledge_worker.py", "knowledge_retrieval.py", "tools.py",
    )
    if (root / name).read_bytes() != (root / "casper" / name).read_bytes()
]
for name in (
    "extract_single.txt", "knowledge_extract.txt", "knowledge_judge.txt",
    "knowledge_judge_recover.txt", "nerv_daily_knowledge_curator.txt",
    "nerv_daily_knowledge_curator_recovery.txt",
):
    if (root / "prompts" / name).read_bytes() != (
        root / "casper" / "prompts" / name
    ).read_bytes():
        mirror_failures.append("prompts/" + name)

build_wiring = all([
    build.get("build_id") == expected_build,
    build.get("package_id") == expected_build,
    build.get("update_kind") == "Knowledge Visual Recall V1.10.54.7",
    expected_build in main_source,
])
companion_watch_guard = all([
    "knowledge_autonomy_thread," in main_source,
    "if current_thread is not None or _companion_watch_owns_idle_time()"
        in main_source,
])

claim_count = int(counts.get("claims") or 0)
contract_accounting_valid = (
    int(counts.get("contract_current") or 0)
    + int(counts.get("legacy_compatible") or 0)
) == claim_count

print("quick_check =", quick_check)
print("schema_version =", schema_version)
print("validation_mode = read_only")
print("sqlite_query_only =", bool(query_only))
print("knowledge_evidence_contract_version =",
      knowledge_evidence.KNOWLEDGE_EVIDENCE_CONTRACT_VERSION)
print("knowledge_media_index_version =",
      knowledge_evidence.KNOWLEDGE_MEDIA_INDEX_VERSION)
print("media_index_document_present =", media_index_document_present)
print("media_index_required =", media_index_required)
print("media_index_state_valid =", media_index_state_valid)
print("knowledge_claims =", claim_count)
print("ledger_document_present =", ledger_document_present)
print("evidence_counts =", counts)
print("contract_accounting_valid =", contract_accounting_valid)
print("evidence_failures =", evidence_failures)
print("raw_image_payload_failures =", raw_image_payload_failures)
print("evidence_wiring =", evidence_wiring)
print("build_wiring =", build_wiring)
print("mirror_failures =", mirror_failures)
print("companion_watch_guard =", companion_watch_guard)
print("payload_hash_failures =", payload_hash_failures)

failures = any([
    quick_check != "ok",
    schema_version != 2,
    not bool(query_only),
    not ledger_document_present,
    not media_index_state_valid,
    evidence_failures,
    not contract_accounting_valid,
    raw_image_payload_failures,
    not evidence_wiring,
    not build_wiring,
    mirror_failures,
    not companion_watch_guard,
    payload_hash_failures,
])
if failures:
    raise SystemExit(
        "Knowledge evidence lineage live SQLite validation failed."
    )
'@ | python -
    if ($LASTEXITCODE -ne 0) {
        throw "Knowledge evidence lineage live SQLite validation failed."
    }
} finally {
    Pop-Location
}
