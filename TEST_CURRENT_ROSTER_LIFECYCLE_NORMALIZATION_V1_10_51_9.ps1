[CmdletBinding()]
param(
    [switch]$RequireLiveRefresh
)

$ErrorActionPreference = "Stop"
$projectRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
Push-Location $projectRoot
try {
    python -m unittest -q `
        tests.test_current_roster_lifecycle_normalization_v1_10_51_9 `
        tests.test_external_fact_fallback `
        tests.test_knowledge_relationship_support_recovery_v1_10_51_8
    if ($LASTEXITCODE -ne 0) {
        throw "Current-roster lifecycle normalization tests failed."
    }

    $requireRefresh = if ($RequireLiveRefresh) { "1" } else { "0" }
    $env:BEKKI_REQUIRE_LIVE_ROSTER_REFRESH = $requireRefresh
@'
import hashlib
import json
import os
from pathlib import Path
import sqlite3
from datetime import datetime, timezone

import knowledge
from nerv import external_fact_fallback


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
for namespace, key, payload, expected_hash in rows:
    actual_hash = hashlib.sha256(payload.encode("utf-8")).hexdigest()
    if actual_hash != expected_hash:
        payload_hash_failures.append(namespace + "/" + key)

TARGET_GROUP_NAME = "\u56db\u79a7\u4e38\u5b50"
EXPECTED_MEMBER_NAMES = {
    "\u6c90\u9702",
    "\u53c8\u4e00",
    "\u68a8\u5b89",
    "\u606c\u8c46",
}

items = knowledge.load_items()
matching_rosters = []
roster_shape_failures = []
for item in items:
    if not isinstance(item, dict):
        continue
    if str(item.get("subject") or "") != TARGET_GROUP_NAME:
        continue
    entries = set(knowledge._current_people_roster_entries(item))
    if entries != EXPECTED_MEMBER_NAMES:
        continue
    matching_rosters.append(item)
    label = str(item.get("id") or "")
    if str(item.get("knowledge_type") or "") != "reviewable":
        roster_shape_failures.append(label + ":not_reviewable")
    if str(item.get("lifecycle_basis") or "") not in {
        "", "MAINTAINED_SET_OR_STRUCTURE"
    }:
        roster_shape_failures.append(label + ":wrong_basis")
    valid_for_days = item.get("valid_for_days")
    if not isinstance(valid_for_days, int) or not 1 <= valid_for_days <= 3650:
        roster_shape_failures.append(label + ":invalid_review_days")
    try:
        expires_at = datetime.fromisoformat(
            str(item.get("expires_at") or "").replace("Z", "+00:00")
        )
        if expires_at.tzinfo is None:
            expires_at = expires_at.replace(tzinfo=timezone.utc)
        if expires_at <= datetime.now(timezone.utc):
            roster_shape_failures.append(label + ":expired")
    except (TypeError, ValueError):
        roster_shape_failures.append(label + ":invalid_expiry")

current_ids = sorted(str(item.get("id") or "") for item in matching_rosters)
normalization_versions = sorted({
    int(item.get("current_roster_lifecycle_normalization_version") or 0)
    for item in matching_rosters
})
refresh_counts = sorted({
    int(
        (
            item.get("current_roster_review")
            if isinstance(item.get("current_roster_review"), dict)
            else {}
        ).get("refresh_count") or 0
    )
    for item in matching_rosters
})
curation_relationship_counts = sorted({
    len(
        (
            item.get("curation")
            if isinstance(item.get("curation"), dict)
            else {}
        ).get("relationship_ids", [])
    )
    for item in matching_rosters
})
if matching_rosters and curation_relationship_counts != [4]:
    roster_shape_failures.append("curation_relationships_not_preserved")

member_edges = [
    edge
    for edge in knowledge.load_topic_relationships(
        "sihixian_ecosystem", temporal_view="all"
    )
    if edge.get("relation") == "member_of"
    and edge.get("target_entity_name") == TARGET_GROUP_NAME
]
relationship_failures = []
member_edge_names = {
    str(edge.get("source_entity_name") or "") for edge in member_edges
}
if member_edge_names != EXPECTED_MEMBER_NAMES:
    relationship_failures.append("member_edges_incomplete")
if member_edges and any(
    edge.get("current_active") is not True
    or edge.get("historical_active") is not True
    for edge in member_edges
):
    relationship_failures.append("mixed_roster_support_changed")

live_refresh_found = any(
    int(item.get("current_roster_lifecycle_normalization_version") or 0) >= 1
    and int(
        (
            item.get("current_roster_review")
            if isinstance(item.get("current_roster_review"), dict)
            else {}
        ).get("refresh_count") or 0
    ) >= 1
    for item in matching_rosters
)
require_live_refresh = os.environ.get(
    "BEKKI_REQUIRE_LIVE_ROSTER_REFRESH"
) == "1"

print("quick_check =", quick_check)
print("schema_version =", schema_version)
print(
    "current_roster_lifecycle_normalization_version =",
    external_fact_fallback.CURRENT_ROSTER_LIFECYCLE_NORMALIZATION_VERSION,
)
print(
    "current_people_roster_review_days =",
    external_fact_fallback.CURRENT_PEOPLE_ROSTER_REVIEW_DAYS,
)
print("matching_current_roster_ids =", current_ids)
print("matching_current_roster_count =", len(matching_rosters))
print("stored_normalization_versions =", normalization_versions)
print("stored_refresh_counts =", refresh_counts)
print("curation_relationship_counts =", curation_relationship_counts)
print("live_refresh_found =", live_refresh_found)
print("require_live_refresh =", require_live_refresh)
print("roster_shape_failures =", roster_shape_failures)
print("relationship_failures =", relationship_failures)
print("payload_hash_failures =", payload_hash_failures)

failures = roster_shape_failures + relationship_failures + payload_hash_failures
if (
    quick_check != "ok"
    or schema_version != 2
    or len(matching_rosters) != 1
    or failures
    or (require_live_refresh and not live_refresh_found)
):
    raise SystemExit(1)
'@ | python -
    if ($LASTEXITCODE -ne 0) {
        throw "Current-roster lifecycle live SQLite validation failed."
    }
}
finally {
    Remove-Item Env:BEKKI_REQUIRE_LIVE_ROSTER_REFRESH -ErrorAction SilentlyContinue
    Pop-Location
}
