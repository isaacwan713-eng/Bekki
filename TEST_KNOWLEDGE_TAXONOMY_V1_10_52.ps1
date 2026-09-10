[CmdletBinding()]
param()

$ErrorActionPreference = "Stop"
$projectRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
Push-Location $projectRoot
try {
    python -m unittest -q `
        tests.test_knowledge_taxonomy_v1_10_52 `
        tests.test_topic_lifecycle_autonomy `
        tests.test_knowledge_relationship_grounding_v1_10_51
    if ($LASTEXITCODE -ne 0) {
        throw "Knowledge taxonomy unit tests failed."
    }

@'
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
import re
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
        "FROM json_documents WHERE namespace = 'knowledge'"
    ).fetchall()
finally:
    connection.close()

documents = {}
payload_hash_failures = []
for namespace, key, payload, expected_hash in rows:
    if hashlib.sha256(payload.encode("utf-8")).hexdigest() != expected_hash:
        payload_hash_failures.append(namespace + "/" + key)
    try:
        documents[key] = json.loads(payload)
    except json.JSONDecodeError:
        payload_hash_failures.append(namespace + "/" + key + ":invalid_json")

now = datetime.now(timezone.utc)
ledger = documents.get("knowledge.json")
ledger = ledger if isinstance(ledger, list) else []

def is_authoritative_active(item):
    if not isinstance(item, dict) or item.get("status") != "verified":
        return False
    curation = item.get("curation")
    curation = curation if isinstance(curation, dict) else {}
    if str(curation.get("status") or "").lower() in {"duplicate", "conflict"}:
        return False
    knowledge_type = str(item.get("knowledge_type") or "stable").lower()
    if knowledge_type == "stable":
        return True
    if knowledge_type != "reviewable":
        return False
    try:
        expires_at = datetime.fromisoformat(
            str(item.get("expires_at") or "").replace("Z", "+00:00")
        )
        if expires_at.tzinfo is None:
            expires_at = expires_at.replace(tzinfo=timezone.utc)
        return expires_at > now
    except (TypeError, ValueError):
        return False

authoritative_active_ids = {
    str(item.get("id") or "")
    for item in ledger
    if is_authoritative_active(item) and str(item.get("id") or "")
}

domains = {
    "general", "mathematics", "physics", "chemistry", "astronomy",
    "geography", "computer_science", "medical", "legal", "sports",
    "culture_entertainment", "business_organization", "history_society",
    "other",
}
fact_types = {
    "IDENTITY_DEFINITION", "ATTRIBUTE", "COMPOSITION_STRUCTURE",
    "RELATIONSHIP", "HISTORY", "PROCESS_MECHANISM", "WORK_OUTPUT",
    "LOCATION", "QUANTITY_STATISTIC", "RULE_STANDARD", "COMPARISON",
    "OTHER",
}
safe_id = re.compile(r"^[a-z0-9][a-z0-9_-]{0,79}$")
topic_documents = [
    (key, value)
    for key, value in documents.items()
    if key.startswith("knowledge/topics/") and isinstance(value, dict)
]
classification_failures = []
unclassified_topics = []
unclassified_claims = []
fact_type_counts = {value: 0 for value in sorted(fact_types)}
category_paths = []
layered_before = 0
lifecycle_states = {}
relationship_edges = 0
ignored_topic_claim_copies = []

for key, document in topic_documents:
    topic = document.get("topic") if isinstance(document.get("topic"), dict) else {}
    topic_id = str(topic.get("id") or key)
    semantic = document.get("semantic_contract")
    semantic = semantic if isinstance(semantic, dict) else {}
    if int(document.get("schema_version") or 0) < 3:
        classification_failures.append(topic_id + ":topic_schema")
    if int(semantic.get("classification_contract_version") or 0) < 1:
        classification_failures.append(topic_id + ":classification_contract")

    classification = document.get("classification")
    classification = classification if isinstance(classification, dict) else {}
    path = classification.get("category_path")
    path = path if isinstance(path, list) else []
    valid_classification = (
        int(classification.get("version") or 0) >= 1
        and str(classification.get("domain") or "") in domains
        and 1 <= len(path) <= 2
        and all(
            isinstance(node, dict)
            and safe_id.fullmatch(str(node.get("id") or ""))
            and str(node.get("label") or "").strip()
            for node in path
        )
    )
    if not valid_classification:
        unclassified_topics.append(topic_id)
    else:
        category_paths.append(
            str(classification["domain"]) + "/"
            + "/".join(str(node["id"]) for node in path)
        )

    lifecycle = document.get("lifecycle")
    lifecycle = lifecycle if isinstance(lifecycle, dict) else {}
    state = str(lifecycle.get("state") or "UNASSESSED")
    lifecycle_states[state] = lifecycle_states.get(state, 0) + 1
    relationships = document.get("relationships")
    relationship_edges += len(relationships) if isinstance(relationships, list) else 0
    for claim in document.get("claims", []):
        if not isinstance(claim, dict) or claim.get("status") != "verified":
            continue
        claim_id = str(claim.get("id") or "")
        if claim_id not in authoritative_active_ids:
            ignored_topic_claim_copies.append(topic_id + "/" + claim_id)
            continue
        curation = claim.get("curation")
        curation = curation if isinstance(curation, dict) else {}
        if str(curation.get("knowledge_layer") or "").startswith("L"):
            layered_before += 1
        fact_type = str(curation.get("fact_type") or "")
        if (
            fact_type not in fact_types
            or int(curation.get("classification_version") or 0) < 1
        ):
            unclassified_claims.append(
                topic_id + "/" + str(claim.get("id") or "")
            )
        else:
            fact_type_counts[fact_type] += 1
        if curation.get("relationship_ids") and fact_type != "RELATIONSHIP":
            classification_failures.append(
                topic_id + "/" + str(claim.get("id") or "")
                + ":relationship_fact_type"
            )

index = documents.get("knowledge/index.json")
index = index if isinstance(index, dict) else {}
active_claim_index_version = int(index.get("active_claim_index_version") or 0)
if active_claim_index_version < 1:
    classification_failures.append("active_claim_index_version")
index_fact_type_counts = index.get("fact_type_counts")
index_fact_type_counts = (
    index_fact_type_counts if isinstance(index_fact_type_counts, dict) else {}
)
if {
    key: int(index_fact_type_counts.get(key) or 0)
    for key in sorted(fact_types)
} != fact_type_counts:
    classification_failures.append("fact_type_index_mismatch")
index_paths = index.get("category_paths")
index_paths = index_paths if isinstance(index_paths, list) else []
indexed_topic_ids = {
    str(topic_id)
    for row in index_paths
    if isinstance(row, dict)
    for topic_id in row.get("topic_ids", [])
}
classified_topic_ids = {
    str(
        (document.get("topic") or {}).get("id")
        if isinstance(document.get("topic"), dict) else ""
    )
    for _key, document in topic_documents
    if isinstance(document.get("classification"), dict)
    and int(document["classification"].get("version") or 0) >= 1
}
if indexed_topic_ids != classified_topic_ids:
    classification_failures.append("category_index_topic_mismatch")

print("quick_check =", quick_check)
print("schema_version =", schema_version)
print("topic_schema_version =", 3)
print("classification_contract_version =", 1)
print("active_claim_index_version =", active_claim_index_version)
print("topic_documents =", len(topic_documents))
print("category_paths =", sorted(set(category_paths)))
print("fact_type_counts =", fact_type_counts)
print("unclassified_topics =", unclassified_topics)
print("unclassified_claims =", unclassified_claims)
print("classification_failures =", classification_failures)
print("lifecycle_states =", lifecycle_states)
print("existing_layered_claims =", layered_before)
print("relationship_edges_preserved =", relationship_edges)
print("authoritative_active_claims =", len(authoritative_active_ids))
print("ignored_topic_claim_copies =", ignored_topic_claim_copies)
print("payload_hash_failures =", payload_hash_failures)

failures = (
    unclassified_topics
    + unclassified_claims
    + classification_failures
    + payload_hash_failures
)
if quick_check != "ok" or schema_version != 2 or failures:
    raise SystemExit(1)
'@ | python -
    if ($LASTEXITCODE -ne 0) {
        throw (
            "Knowledge taxonomy live SQLite validation failed. " +
            "If unclassified current topics or claims remain, leave Bekki idle until the " +
            "NERV TOPIC LIFECYCLE line finishes, then run this test again."
        )
    }
}
finally {
    Pop-Location
}
