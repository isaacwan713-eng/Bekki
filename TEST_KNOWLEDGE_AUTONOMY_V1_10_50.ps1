[CmdletBinding()]
param()

$ErrorActionPreference = "Stop"
$projectRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
Push-Location $projectRoot
try {
@'
import hashlib
import json
from pathlib import Path
import sqlite3

database = Path("data/bekki.sqlite3").resolve()
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

hash_failures = []
documents = {}
for namespace, key, payload, expected_hash in rows:
    actual_hash = hashlib.sha256(payload.encode("utf-8")).hexdigest()
    if actual_hash != expected_hash:
        hash_failures.append(namespace + "/" + key)
    try:
        documents[(namespace, key)] = json.loads(payload)
    except json.JSONDecodeError:
        hash_failures.append(namespace + "/" + key + ":invalid_json")

topic_documents = [
    value
    for (namespace, key), value in documents.items()
    if namespace == "knowledge"
    and key.startswith("knowledge/topics/")
    and isinstance(value, dict)
]
lifecycle_counts = {"ACTIVE": 0, "PAUSED_COMPLETE": 0, "UNASSESSED": 0}
layer_counts = {
    layer: 0
    for layer in (
        "L1_FOUNDATION",
        "L2_CONTEXT",
        "L3_RELATIONSHIPS",
        "L4_MECHANISMS",
        "L5_SPECIALIST",
    )
}
invalid_layers = []
for document in topic_documents:
    topic = document.get("topic") if isinstance(document.get("topic"), dict) else {}
    topic_id = str(topic.get("id") or "")
    lifecycle = (
        document.get("lifecycle")
        if isinstance(document.get("lifecycle"), dict)
        else {}
    )
    state = str(lifecycle.get("state") or "UNASSESSED")
    lifecycle_counts[state if state in lifecycle_counts else "UNASSESSED"] += 1
    for claim in document.get("claims", []):
        if not isinstance(claim, dict) or claim.get("status") != "verified":
            continue
        curation = claim.get("curation")
        curation = curation if isinstance(curation, dict) else {}
        layer = str(curation.get("knowledge_layer") or "")
        if layer in layer_counts:
            layer_counts[layer] += 1
        else:
            invalid_layers.append(topic_id + "/" + str(claim.get("id") or ""))

curiosity = documents.get(("nerv", "nerv/curiosity.json"), {})
curiosity_items = curiosity.get("items", []) if isinstance(curiosity, dict) else []
open_lifecycle = [
    item
    for item in curiosity_items
    if isinstance(item, dict)
    and str(item.get("seed_kind") or "").upper() in {"TOPIC_GAP", "TOPIC_REFRESH"}
    and item.get("state") in {"DRAFT", "ASKED", "ANSWERED_UNVERIFIED"}
]

print("quick_check =", quick_check)
print("schema_version =", schema_version)
print("knowledge_documents =", sum(1 for namespace, _key in documents if namespace == "knowledge"))
print("curiosity_sqlite_present =", ("nerv", "nerv/curiosity.json") in documents)
print("topic_documents =", len(topic_documents))
print("topic_lifecycle_counts =", lifecycle_counts)
print("knowledge_layer_counts =", layer_counts)
print("unlayered_or_invalid_claims =", invalid_layers)
print("open_lifecycle_questions =", len(open_lifecycle))
print("single_question_lock_valid =", len(open_lifecycle) <= 1)
print("payload_hash_failures =", hash_failures)
print(
    "source_contract_present =",
    Path("nerv/topic_lifecycle.py").is_file()
    and Path("prompts/nerv_topic_lifecycle.txt").is_file()
    and Path("prompts/nerv_topic_lifecycle_recovery.txt").is_file(),
)

if quick_check != "ok" or schema_version != 2 or hash_failures:
    raise SystemExit(1)
if len(open_lifecycle) > 1:
    raise SystemExit(1)
'@ | python -
    if ($LASTEXITCODE -ne 0) {
        throw "Knowledge autonomy read-only validation failed."
    }
}
finally {
    Pop-Location
}
