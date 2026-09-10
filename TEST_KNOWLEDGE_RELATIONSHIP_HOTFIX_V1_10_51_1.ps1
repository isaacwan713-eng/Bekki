[CmdletBinding()]
param()

$ErrorActionPreference = "Stop"
$projectRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
Push-Location $projectRoot
try {
    python -m unittest -q `
        tests.test_knowledge_relationship_grounding_v1_10_51 `
        tests.test_objective_fact_verification `
        tests.test_r21_summary_first
    if ($LASTEXITCODE -ne 0) {
        throw "Knowledge relationship isolated tests failed."
    }

@'
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
import re
import sqlite3

import knowledge


# Apply the bounded topic semantic migration before opening the live database
# read-only for the remaining checks.
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

documents = {}
payload_hash_failures = []
for namespace, key, payload, expected_hash in rows:
    actual_hash = hashlib.sha256(payload.encode("utf-8")).hexdigest()
    if actual_hash != expected_hash:
        payload_hash_failures.append(namespace + "/" + key)
    try:
        documents[(namespace, key)] = json.loads(payload)
    except json.JSONDecodeError:
        payload_hash_failures.append(namespace + "/" + key + ":invalid_json")

flat_items = documents.get(("knowledge", "knowledge.json"), [])
flat_items = flat_items if isinstance(flat_items, list) else []
flat_by_id = {
    str(item.get("id") or ""): item
    for item in flat_items
    if isinstance(item, dict) and item.get("id")
}

now = datetime.now(timezone.utc)

def parse_time(value):
    text = str(value or "").strip()
    if not text:
        return None
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)

def is_active(item):
    if not isinstance(item, dict) or item.get("status") != "verified":
        return False
    curation = item.get("curation")
    curation = curation if isinstance(curation, dict) else {}
    if str(curation.get("status") or "").lower() in {"duplicate", "conflict"}:
        return False
    kind = str(item.get("knowledge_type") or "stable").lower()
    if kind == "stable":
        return True
    if kind != "reviewable":
        return False
    expiry = parse_time(item.get("expires_at"))
    return expiry is not None and expiry > now

active_ids = {
    knowledge_id
    for knowledge_id, item in flat_by_id.items()
    if is_active(item)
}
topic_documents = [
    value
    for (namespace, key), value in documents.items()
    if namespace == "knowledge"
    and key.startswith("knowledge/topics/")
    and isinstance(value, dict)
]

safe_id = re.compile(r"^[a-z0-9][a-z0-9_-]{0,79}$")
safe_relation = re.compile(r"^[a-z][a-z0-9_]{0,79}$")
individual_types = {
    "person", "member", "character", "virtual_character", "performer", "creator"
}
group_types = {
    "group", "organization", "team", "unit", "pairing",
    "virtual_idol_group", "umbrella_organization"
}
semantic_contract_failures = []
relationship_contract_failures = []
orphan_relationship_support = []
reversed_membership_edges = []
relationship_layer_failures = []
relationship_claims_pending_l3 = []
stored_relationships = 0
active_relationships = 0
sihixian_topic = None

for document in topic_documents:
    topic = document.get("topic")
    topic = topic if isinstance(topic, dict) else {}
    topic_id = str(topic.get("id") or "")
    if topic_id == "sihixian_ecosystem":
        sihixian_topic = document
    semantic = document.get("semantic_contract")
    semantic = semantic if isinstance(semantic, dict) else {}
    if int(semantic.get("version") or 0) < 1:
        semantic_contract_failures.append(topic_id or "<missing_topic_id>")
    entities = document.get("entities")
    entities = entities if isinstance(entities, dict) else {}
    claims = {
        str(item.get("id") or ""): item
        for item in document.get("claims", [])
        if isinstance(item, dict) and item.get("id")
    }
    for relationship in document.get("relationships", []):
        if not isinstance(relationship, dict):
            relationship_contract_failures.append(topic_id + ":not_object")
            continue
        stored_relationships += 1
        relation_id = str(relationship.get("id") or "")
        source_id = str(relationship.get("source_entity_id") or "")
        target_id = str(relationship.get("target_entity_id") or "")
        relation = str(relationship.get("relation") or "")
        support_ids = [
            str(value)
            for value in relationship.get("supporting_knowledge_ids", [])
            if str(value)
        ]
        if (
            not relation_id.startswith("relation_")
            or not safe_id.fullmatch(source_id)
            or not safe_id.fullmatch(target_id)
            or not safe_relation.fullmatch(relation)
            or relationship.get("status") != "VERIFIED_CLAIM"
            or int(relationship.get("contract_version") or 0) < 1
            or not support_ids
        ):
            relationship_contract_failures.append(topic_id + "/" + relation_id)
        missing = [
            knowledge_id
            for knowledge_id in support_ids
            if knowledge_id not in claims or knowledge_id not in flat_by_id
        ]
        if missing:
            orphan_relationship_support.append(
                topic_id + "/" + relation_id + ":" + ",".join(missing)
            )
        evidence_ids = {
            str(value.get("knowledge_id") or "")
            for value in relationship.get("evidence", [])
            if isinstance(value, dict) and str(value.get("text") or "").strip()
        }
        if not set(support_ids).issubset(evidence_ids):
            relationship_contract_failures.append(
                topic_id + "/" + relation_id + ":evidence"
            )
        if set(support_ids) & active_ids:
            active_relationships += 1
        source = entities.get(source_id)
        source = source if isinstance(source, dict) else {}
        target = entities.get(target_id)
        target = target if isinstance(target, dict) else {}
        source_type = str(source.get("type") or "").lower()
        target_type = str(target.get("type") or "").lower()
        if relation.startswith(("member_of", "former_member_of", "original_member_of")):
            if source_type in group_types and target_type in individual_types:
                reversed_membership_edges.append(topic_id + "/" + relation_id)
        for knowledge_id in support_ids:
            claim = claims.get(knowledge_id)
            if not isinstance(claim, dict):
                continue
            curation = claim.get("curation")
            curation = curation if isinstance(curation, dict) else {}
            if relation_id not in curation.get("relationship_ids", []):
                relationship_contract_failures.append(
                    topic_id + "/" + relation_id + ":claim_link"
                )
            layer = str(curation.get("knowledge_layer") or "").upper()
            if not layer:
                relationship_claims_pending_l3.append(knowledge_id)
            elif layer != "L3_RELATIONSHIPS":
                relationship_layer_failures.append(knowledge_id + ":" + layer)

sihixian_member_edges = []
sihixian_member_support_ids = set()
sihixian_alias_failures = []
if isinstance(sihixian_topic, dict):
    topic = sihixian_topic.get("topic")
    topic = topic if isinstance(topic, dict) else {}
    unsupported = {"sihixian", "sihixian maruko"}
    for value in [topic.get("title"), *topic.get("aliases", []), *topic.get("keywords", [])]:
        if str(value or "").strip().casefold() in unsupported:
            sihixian_alias_failures.append(str(value))
    entities = sihixian_topic.get("entities")
    entities = entities if isinstance(entities, dict) else {}
    for relationship in sihixian_topic.get("relationships", []):
        if not isinstance(relationship, dict):
            continue
        source = entities.get(str(relationship.get("source_entity_id") or ""), {})
        target = entities.get(str(relationship.get("target_entity_id") or ""), {})
        support = set(relationship.get("supporting_knowledge_ids", [])) & active_ids
        if (
            relationship.get("relation") in {"member_of", "original_member_of"}
            and str(target.get("name") or "") == "四禧丸子"
            and support
        ):
            sihixian_member_edges.append(str(source.get("name") or ""))
            sihixian_member_support_ids.update(support)

sihixian_member_edges = sorted(set(sihixian_member_edges))
sihixian_roster_ready = set(sihixian_member_edges) == {"沐霂", "又一", "梨安", "恬豆"}
sihixian_rerun_required = len(sihixian_member_edges) == 0
sihixian_roster_lifecycle_failures = []
for knowledge_id in sorted(sihixian_member_support_ids):
    item = flat_by_id.get(knowledge_id, {})
    claim_text = str(item.get("claim") or "")
    temporal_scope = item.get("temporal_scope")
    temporal_scope = (
        temporal_scope if isinstance(temporal_scope, dict) else {}
    )
    closed_history = (
        temporal_scope.get("closed_period") is True
        or str(temporal_scope.get("scope_type") or "").upper()
        in {"EXPLICIT_PERIOD", "LATEST_COMPLETED_PERIOD"}
    )
    is_current_roster = (
        all(name in claim_text for name in ("沐霂", "又一", "梨安", "恬豆"))
        and not re.search(r"最初|创始|初代|原成员|前成员", claim_text)
        and not closed_history
    )
    if not is_current_roster:
        continue
    if (
        str(item.get("knowledge_type") or "").lower() != "reviewable"
        or str(item.get("lifecycle_basis") or "").upper()
        != "MAINTAINED_SET_OR_STRUCTURE"
        or parse_time(item.get("expires_at")) is None
        or parse_time(item.get("expires_at")) <= now
        or int(item.get("partition_lifecycle_audit_version") or 0) < 9
    ):
        sihixian_roster_lifecycle_failures.append(knowledge_id)

print("quick_check =", quick_check)
print("schema_version =", schema_version)
print("knowledge_documents =", len(rows))
print("topic_documents =", len(topic_documents))
print("stored_relationships =", stored_relationships)
print("active_relationships =", active_relationships)
print("semantic_contract_failures =", semantic_contract_failures)
print("relationship_contract_failures =", relationship_contract_failures)
print("orphan_relationship_support =", orphan_relationship_support)
print("reversed_membership_edges =", reversed_membership_edges)
print("relationship_layer_failures =", relationship_layer_failures)
print("relationship_claims_pending_l3 =", sorted(set(relationship_claims_pending_l3)))
print("sihixian_topic_present =", sihixian_topic is not None)
print("sihixian_alias_failures =", sihixian_alias_failures)
print("sihixian_member_edges =", sihixian_member_edges)
print("sihixian_roster_ready =", sihixian_roster_ready)
print("sihixian_rerun_required =", sihixian_rerun_required)
print("sihixian_roster_lifecycle_failures =", sihixian_roster_lifecycle_failures)
print("payload_hash_failures =", payload_hash_failures)
print(
    "source_contract_present =",
    Path("nerv/knowledge_curator.py").is_file()
    and Path("nerv/topic_lifecycle.py").is_file()
    and Path("prompts/nerv_daily_knowledge_curator.txt").is_file()
    and Path("prompts/nerv_topic_lifecycle.txt").is_file(),
)

failures = (
    payload_hash_failures
    + semantic_contract_failures
    + relationship_contract_failures
    + orphan_relationship_support
    + reversed_membership_edges
    + relationship_layer_failures
    + sihixian_alias_failures
    + sihixian_roster_lifecycle_failures
)
if quick_check != "ok" or schema_version != 2 or failures:
    raise SystemExit(1)
if sihixian_member_edges and not sihixian_roster_ready:
    raise SystemExit("ERROR incomplete_sihixian_roster_relationships")
'@ | python -
    if ($LASTEXITCODE -ne 0) {
        throw "Knowledge relationship live SQLite validation failed."
    }
}
finally {
    Pop-Location
}
