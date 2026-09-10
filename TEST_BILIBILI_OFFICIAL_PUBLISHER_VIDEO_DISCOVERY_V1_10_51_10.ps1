[CmdletBinding()]
param(
    [switch]$RequireLivePublisherEvidence
)

$ErrorActionPreference = "Stop"
$projectRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
Push-Location $projectRoot
try {
    python -m unittest -q `
        tests.test_bilibili_official_publisher_video_discovery_v1_10_51_10 `
        tests.test_bilibili_native_fact_executor_v1_10_51_3 `
        tests.test_bilibili_official_evidence_recovery_v1_10_51_4 `
        tests.test_bilibili_video_detail_recovery_v1_10_51_6 `
        tests.test_current_roster_lifecycle_normalization_v1_10_51_9 `
        tests.test_companion_watch_v1_10_47 `
        tests.test_iyf_companion_watch_hotfix_v1_10_47_7
    if ($LASTEXITCODE -ne 0) {
        throw "Bilibili official-publisher discovery tests failed."
    }

    $requireEvidence = if ($RequireLivePublisherEvidence) { "1" } else { "0" }
    $env:BEKKI_REQUIRE_LIVE_PUBLISHER_EVIDENCE = $requireEvidence
@'
import hashlib
import os
from pathlib import Path
import sqlite3
from urllib.parse import urlparse

import knowledge
from casper import browser


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

TARGET = "\u56db\u79a7\u4e38\u5b50"
EXPECTED_MEMBERS = {
    "\u6c90\u9702",
    "\u53c8\u4e00",
    "\u68a8\u5b89",
    "\u606c\u8c46",
}
PUBLISHER_URL = "https://space.bilibili.com/1129115529"

items = knowledge.load_items()
current_rosters = []
historical_rosters = []
bound_sources = []
for item in items:
    if not isinstance(item, dict) or item.get("subject") != TARGET:
        continue
    claim = str(item.get("claim") or "")
    if not all(name in claim for name in EXPECTED_MEMBERS):
        continue
    scope = knowledge.normalize_temporal_scope(item.get("temporal_scope"))
    if scope.get("closed_period") is True:
        historical_rosters.append(item)
    elif set(knowledge._current_people_roster_entries(item)) == EXPECTED_MEMBERS:
        current_rosters.append(item)
    for source in item.get("sources", []):
        if not isinstance(source, dict):
            continue
        try:
            source_host = str(
                urlparse(str(source.get("url") or "")).hostname or ""
            ).casefold()
        except ValueError:
            source_host = ""
        if (
            source.get("official_publisher_page_bound") is True
            and int(
                source.get(
                    "official_publisher_video_discovery_version"
                ) or 0
            ) >= 1
            and source.get("publisher_url") == PUBLISHER_URL
            and source_host in {"bilibili.com", "www.bilibili.com"}
            and "/video/" in str(source.get("url") or "")
        ):
            bound_sources.append({
                "knowledge_id": str(item.get("id") or ""),
                "url": str(source.get("url") or ""),
            })

relationship_failures = []
member_edges = [
    edge
    for edge in knowledge.load_topic_relationships(
        "sihixian_ecosystem", temporal_view="all"
    )
    if edge.get("relation") == "member_of"
    and edge.get("target_entity_name") == TARGET
]
if {
    str(edge.get("source_entity_name") or "") for edge in member_edges
} != EXPECTED_MEMBERS:
    relationship_failures.append("member_edges_incomplete")
if member_edges and any(
    edge.get("current_active") is not True
    or edge.get("historical_active") is not True
    for edge in member_edges
):
    relationship_failures.append("mixed_roster_support_changed")

require_live_evidence = os.environ.get(
    "BEKKI_REQUIRE_LIVE_PUBLISHER_EVIDENCE"
) == "1"
live_publisher_evidence_found = bool(bound_sources)

print("quick_check =", quick_check)
print("schema_version =", schema_version)
print(
    "official_publisher_video_discovery_version =",
    browser.BILIBILI_OFFICIAL_PUBLISHER_VIDEO_DISCOVERY_VERSION,
)
print("current_roster_count =", len(current_rosters))
print("historical_roster_count =", len(historical_rosters))
print("member_edge_count =", len(member_edges))
print("publisher_bound_sources =", bound_sources)
print(
    "live_publisher_evidence_found =",
    live_publisher_evidence_found,
)
print("require_live_publisher_evidence =", require_live_evidence)
print("relationship_failures =", relationship_failures)
print("payload_hash_failures =", payload_hash_failures)

if (
    quick_check != "ok"
    or schema_version != 2
    or len(current_rosters) != 1
    or not historical_rosters
    or relationship_failures
    or payload_hash_failures
    or (
        require_live_evidence
        and not live_publisher_evidence_found
    )
):
    raise SystemExit(1)
'@ | python -
    if ($LASTEXITCODE -ne 0) {
        throw "Bilibili official-publisher live SQLite validation failed."
    }
}
finally {
    Remove-Item Env:BEKKI_REQUIRE_LIVE_PUBLISHER_EVIDENCE -ErrorAction SilentlyContinue
    Pop-Location
}
