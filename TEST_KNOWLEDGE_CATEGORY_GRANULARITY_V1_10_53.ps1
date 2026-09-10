[CmdletBinding()]
param()

$ErrorActionPreference = "Stop"
$projectRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
Push-Location $projectRoot
try {
    python -m unittest -q `
        tests.test_knowledge_category_granularity_v1_10_53 `
        tests.test_knowledge_taxonomy_v1_10_52 `
        tests.test_topic_lifecycle_autonomy `
        tests.test_knowledge_relationship_grounding_v1_10_51
    if ($LASTEXITCODE -ne 0) {
        throw "Knowledge category granularity unit tests failed."
    }

@'
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
import re
import sqlite3
import unicodedata

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

def token_root(value):
    value = str(value or "").casefold()
    if value.endswith("ies") and len(value) > 4:
        return value[:-3] + "y"
    if (
        value.endswith("s")
        and len(value) > 3
        and not value.endswith(("ss", "us", "is"))
    ):
        return value[:-1]
    return value

def id_key(value):
    return "_".join(
        token_root(token)
        for token in re.findall(r"[a-z0-9]+", str(value or "").casefold())
    )

def label_key(value):
    text = unicodedata.normalize("NFKC", str(value or "")).casefold()
    tokens = re.findall(r"[a-z0-9]+", text)
    if tokens and re.sub(r"[^a-z0-9]+", "", text) == "".join(tokens):
        return "".join(token_root(token) for token in tokens)
    return re.sub(r"[^\w]+", "", text, flags=re.UNICODE).replace("_", "")

topic_documents = [
    (key, value)
    for key, value in documents.items()
    if key.startswith("knowledge/topics/") and isinstance(value, dict)
]
pending_granularity_topics = []
classification_failures = []
category_duplicate_failures = []
unlayered_claims = []
unclassified_claims = []
topic_category_paths = {}
active_topic_ids = set()
current_topic_rows = []
lifecycle_states = {}
relationship_edges = 0

for key, document in topic_documents:
    topic = document.get("topic") if isinstance(document.get("topic"), dict) else {}
    topic_id = str(topic.get("id") or key)
    active_claims = [
        claim for claim in document.get("claims", [])
        if isinstance(claim, dict)
        and str(claim.get("id") or "") in authoritative_active_ids
    ]
    if not active_claims:
        continue
    active_topic_ids.add(topic_id)
    lifecycle = document.get("lifecycle")
    lifecycle = lifecycle if isinstance(lifecycle, dict) else {}
    state = str(lifecycle.get("state") or "UNASSESSED")
    lifecycle_states[state] = lifecycle_states.get(state, 0) + 1
    relationships = document.get("relationships")
    relationship_edges += len(relationships) if isinstance(relationships, list) else 0

    classification = document.get("classification")
    classification = classification if isinstance(classification, dict) else {}
    path = classification.get("category_path")
    path = path if isinstance(path, list) else []
    semantic = document.get("semantic_contract")
    semantic = semantic if isinstance(semantic, dict) else {}
    valid = (
        int(classification.get("version") or 0) >= 1
        and int(classification.get("granularity_version") or 0) >= 1
        and str(classification.get("domain") or "") in domains
        and len(path) == 2
        and len({str(node.get("id") or "") for node in path if isinstance(node, dict)}) == 2
        and all(
            isinstance(node, dict)
            and safe_id.fullmatch(str(node.get("id") or ""))
            and str(node.get("label") or "").strip()
            for node in path
        )
        and str(classification.get("reason") or "").strip()
        and int(semantic.get("category_granularity_version") or 0) >= 1
    )
    if not valid:
        pending_granularity_topics.append(topic_id)
    else:
        path_text = (
            str(classification["domain"]) + "/"
            + "/".join(str(node["id"]) for node in path)
        )
        topic_category_paths[topic_id] = path_text
        current_topic_rows.append((topic_id, classification, path))

    for claim in active_claims:
        claim_id = str(claim.get("id") or "")
        curation = claim.get("curation")
        curation = curation if isinstance(curation, dict) else {}
        if (
            str(curation.get("knowledge_layer") or "")
            not in {"L1_FOUNDATION", "L2_CONTEXT", "L3_RELATIONSHIPS", "L4_MECHANISMS", "L5_SPECIALIST"}
            or int(curation.get("knowledge_layer_version") or 0) < 1
        ):
            unlayered_claims.append(topic_id + "/" + claim_id)
        fact_type = str(curation.get("fact_type") or "")
        if fact_type not in fact_types or int(curation.get("classification_version") or 0) < 1:
            unclassified_claims.append(topic_id + "/" + claim_id)
        if curation.get("relationship_ids") and fact_type != "RELATIONSHIP":
            classification_failures.append(topic_id + "/" + claim_id + ":relationship_fact_type")

known = {}
for topic_id, classification, path in current_topic_rows:
    parent_id = ""
    for depth, node in enumerate(path):
        key = (str(classification["domain"]), parent_id, depth)
        category_id = str(node["id"])
        label = str(node["label"])
        for old_id, old_label, old_topic in known.get(key, []):
            if old_id == category_id:
                if label_key(old_label) != label_key(label):
                    category_duplicate_failures.append(
                        topic_id + ":label_mismatch_with:" + old_topic
                    )
            elif label_key(old_label) == label_key(label):
                category_duplicate_failures.append(
                    topic_id + ":duplicate_label_with:" + old_topic
                )
            elif id_key(old_id) == id_key(category_id):
                category_duplicate_failures.append(
                    topic_id + ":duplicate_id_with:" + old_topic
                )
        known.setdefault(key, []).append((category_id, label, topic_id))
        parent_id = category_id

index = documents.get("knowledge/index.json")
index = index if isinstance(index, dict) else {}
category_granularity_version = int(index.get("category_granularity_version") or 0)
if category_granularity_version < 1:
    classification_failures.append("category_granularity_index_version")
index_paths = index.get("category_paths")
index_paths = index_paths if isinstance(index_paths, list) else []
indexed_paths = {}
for row in index_paths:
    if not isinstance(row, dict):
        continue
    path = row.get("category_path")
    path = path if isinstance(path, list) else []
    path_text = (
        str(row.get("domain") or "") + "/"
        + "/".join(str(node.get("id") or "") for node in path if isinstance(node, dict))
    )
    for topic_id in row.get("topic_ids", []):
        indexed_paths[str(topic_id)] = path_text
for topic_id, path_text in topic_category_paths.items():
    if indexed_paths.get(topic_id) != path_text:
        classification_failures.append(topic_id + ":category_index_mismatch")

print("quick_check =", quick_check)
print("schema_version =", schema_version)
print("topic_schema_version =", 3)
print("classification_contract_version =", 1)
print("category_granularity_version =", category_granularity_version)
print("required_category_depth =", 2)
print("topic_documents =", len(topic_documents))
print("active_topics =", len(active_topic_ids))
print("topic_category_paths =", dict(sorted(topic_category_paths.items())))
print("category_paths =", sorted(set(topic_category_paths.values())))
print("pending_granularity_topics =", sorted(pending_granularity_topics))
print("category_duplicate_failures =", sorted(set(category_duplicate_failures)))
print("classification_failures =", classification_failures)
print("unlayered_claims =", unlayered_claims)
print("unclassified_claims =", unclassified_claims)
print("lifecycle_states =", lifecycle_states)
print("relationship_edges_preserved =", relationship_edges)
print("authoritative_active_claims =", len(authoritative_active_ids))
print("payload_hash_failures =", payload_hash_failures)

failures = (
    pending_granularity_topics
    + category_duplicate_failures
    + classification_failures
    + unlayered_claims
    + unclassified_claims
    + payload_hash_failures
)
if quick_check != "ok" or schema_version != 2 or failures:
    raise SystemExit(1)
'@ | python -
    if ($LASTEXITCODE -ne 0) {
        throw (
            "Knowledge category granularity live SQLite validation failed. " +
            "If pending_granularity_topics is nonempty, start Bekki, leave it " +
            "idle until all NERV TOPIC LIFECYCLE category_refined lines finish, " +
            "then run this test again."
        )
    }
}
finally {
    Pop-Location
}
