[CmdletBinding()]
param()

$ErrorActionPreference = "Stop"
$projectRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
Push-Location $projectRoot
try {
    python -m unittest -q `
        tests.test_knowledge_relationship_temporal_scope_v1_10_51_7 `
        tests.test_knowledge_relationship_grounding_v1_10_51 `
        tests.test_knowledge_curator
    if ($LASTEXITCODE -ne 0) {
        throw "Knowledge relationship temporal-scope tests failed."
    }

@'
import hashlib
import json
from pathlib import Path
import sqlite3

import knowledge


knowledge.initialize()

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
        "FROM json_documents WHERE namespace = 'knowledge'"
    ).fetchall()
finally:
    connection.close()

payload_hash_failures = []
topic_contract_failures = []
topic_documents = []
for namespace, key, payload, expected_hash in rows:
    actual_hash = hashlib.sha256(payload.encode("utf-8")).hexdigest()
    if actual_hash != expected_hash:
        payload_hash_failures.append(namespace + "/" + key)
    if not key.startswith("knowledge/topics/"):
        continue
    try:
        document = json.loads(payload)
    except json.JSONDecodeError:
        topic_contract_failures.append(key + ":invalid_json")
        continue
    if not isinstance(document, dict):
        topic_contract_failures.append(key + ":not_object")
        continue
    topic_documents.append(document)
    semantic = document.get("semantic_contract")
    semantic = semantic if isinstance(semantic, dict) else {}
    if int(semantic.get("relationship_contract_version") or 0) < 2:
        topic_contract_failures.append(key + ":semantic_contract")
    for relationship in document.get("relationships", []):
        if not isinstance(relationship, dict):
            topic_contract_failures.append(key + ":relationship_not_object")
            continue
        if int(relationship.get("contract_version") or 0) < 2:
            topic_contract_failures.append(
                key + "/" + str(relationship.get("id") or "")
            )

all_edges = knowledge.load_topic_relationships(temporal_view="all")
current_edges = knowledge.load_topic_relationships(temporal_view="current")
default_current_edges = knowledge.load_topic_relationships()
historical_edges = knowledge.load_topic_relationships(
    temporal_view="historical"
)

projection_failures = []
scope_overlap_failures = []
for edge in all_edges:
    topic_id = str(edge.get("topic_id") or "")
    edge_id = str(edge.get("id") or "")
    label = topic_id + "/" + edge_id
    current_ids = set(
        edge.get("current_active_supporting_knowledge_ids", [])
    )
    historical_ids = set(
        edge.get("historical_active_supporting_knowledge_ids", [])
    )
    all_ids = set(edge.get("all_active_supporting_knowledge_ids", []))
    if current_ids & historical_ids:
        scope_overlap_failures.append(label)
    if current_ids | historical_ids != all_ids:
        projection_failures.append(label + ":support_partition")
    if edge.get("current_active") is not bool(current_ids):
        projection_failures.append(label + ":current_active")
    if edge.get("historical_active") is not bool(historical_ids):
        projection_failures.append(label + ":historical_active")
    expected_status = (
        "CURRENT_AND_HISTORICAL"
        if current_ids and historical_ids
        else "CURRENT_ONLY"
        if current_ids
        else "HISTORICAL_ONLY"
        if historical_ids
        else "INACTIVE"
    )
    if edge.get("temporal_status") != expected_status:
        projection_failures.append(label + ":temporal_status")
    for evidence in edge.get("evidence", []):
        if not isinstance(evidence, dict):
            projection_failures.append(label + ":invalid_evidence")
            continue
        knowledge_id = str(evidence.get("knowledge_id") or "")
        scope = knowledge.normalize_temporal_scope(
            evidence.get("temporal_scope")
        )
        historical = scope.get("closed_period") is True
        if knowledge_id in current_ids and historical:
            projection_failures.append(label + ":history_in_current")
        if knowledge_id in historical_ids and not historical:
            projection_failures.append(label + ":current_in_history")

current_keys = {
    (str(edge.get("topic_id") or ""), str(edge.get("id") or ""))
    for edge in current_edges
}
default_current_keys = {
    (str(edge.get("topic_id") or ""), str(edge.get("id") or ""))
    for edge in default_current_edges
}
historical_keys = {
    (str(edge.get("topic_id") or ""), str(edge.get("id") or ""))
    for edge in historical_edges
}
if current_keys != default_current_keys:
    projection_failures.append("default_view_not_current")
if any(edge.get("current_active") is not True for edge in current_edges):
    projection_failures.append("inactive_edge_in_current_view")
if any(
    edge.get("historical_active") is not True
    for edge in historical_edges
):
    projection_failures.append("inactive_edge_in_historical_view")

TARGET_GROUP_NAME = "\u56db\u79a7\u4e38\u5b50"
EXPECTED_MEMBER_NAMES = {
    "\u6c90\u9702",
    "\u53c8\u4e00",
    "\u68a8\u5b89",
    "\u606c\u8c46",
}

sihixian_all = knowledge.load_topic_relationships(
    "sihixian_ecosystem",
    temporal_view="all",
)
sihixian_names = sorted({
    str(edge.get("source_entity_name") or "")
    for edge in sihixian_all
    if edge.get("relation") == "member_of"
    and edge.get("target_entity_name") == TARGET_GROUP_NAME
})
sihixian_temporal_statuses = sorted({
    str(edge.get("temporal_status") or "")
    for edge in sihixian_all
})
if sihixian_all and set(sihixian_names) != EXPECTED_MEMBER_NAMES:
    projection_failures.append("sihixian_roster_incomplete")

print("quick_check =", quick_check)
print("schema_version =", schema_version)
print("relationship_contract_version =", knowledge.KNOWLEDGE_RELATIONSHIP_CONTRACT_VERSION)
print("topic_documents =", len(topic_documents))
print("all_active_edges =", len(all_edges))
print("current_active_edges =", len(current_edges))
print("historical_active_edges =", len(historical_edges))
print("default_current_matches_explicit =", current_keys == default_current_keys)
print("scope_overlap_failures =", scope_overlap_failures)
print("projection_failures =", projection_failures)
print("topic_contract_failures =", topic_contract_failures)
print("payload_hash_failures =", payload_hash_failures)
print("sihixian_member_edges =", sihixian_names)
print("sihixian_temporal_statuses =", sihixian_temporal_statuses)

failures = (
    scope_overlap_failures
    + projection_failures
    + topic_contract_failures
    + payload_hash_failures
)
if quick_check != "ok" or schema_version != 2 or failures:
    raise SystemExit(1)
'@ | python -
    if ($LASTEXITCODE -ne 0) {
        throw "Knowledge relationship temporal-scope live validation failed."
    }
}
finally {
    Pop-Location
}
