"""Local, auditable knowledge store for Bekki Knowledge V1."""

import hashlib
import json
import os
import random
import re
import threading
import unicodedata
from copy import deepcopy
from datetime import datetime, timedelta, timezone
from urllib.parse import urlparse

import sqlite_storage
import knowledge_evidence


DATA_DIR = "data"
KNOWLEDGE_FILE = os.path.join(DATA_DIR, "knowledge.json")
SOURCES_FILE = os.path.join(DATA_DIR, "knowledge_sources.json")
LOGS_FILE = os.path.join(DATA_DIR, "learning_logs.json")
PENDING_SOURCES_FILE = os.path.join(DATA_DIR, "knowledge_source_candidates.json")
SOURCE_POLICY_VERSION = 2
SOURCE_DISCOVERY_CONTRACT_VERSION = 2
SOURCE_CANDIDATE_MAX_URLS_PER_DOMAIN = 3
KNOWLEDGE_PENDING_IDENTITY_CONTRACT_VERSION = 1
CURATOR_TERMINAL_OUTCOME_CONTRACT_VERSION = 1
KNOWLEDGE_LIFECYCLE_VERSION = 1
PARTITION_LIFECYCLE_AUDIT_VERSION = 10
CURRENT_ROSTER_LIFECYCLE_NORMALIZATION_VERSION = 1
CURRENT_PEOPLE_ROSTER_REVIEW_DAYS = 365
KNOWLEDGE_CLUSTER_VERSION = 1
KNOWLEDGE_TOPIC_SCHEMA_VERSION = 3
KNOWLEDGE_EVIDENCE_CONTRACT_VERSION = (
    knowledge_evidence.KNOWLEDGE_EVIDENCE_CONTRACT_VERSION
)
KNOWLEDGE_MEDIA_INDEX_VERSION = (
    knowledge_evidence.KNOWLEDGE_MEDIA_INDEX_VERSION
)
KNOWLEDGE_LEGACY_VISUAL_BACKFILL_CONTRACT_VERSION = 1
KNOWLEDGE_DISPLAY_VERSION = 1
KNOWLEDGE_LAYER_VERSION = 1
KNOWLEDGE_CLASSIFICATION_VERSION = 1
KNOWLEDGE_CLASSIFICATION_CONTRACT_VERSION = 1
KNOWLEDGE_CATEGORY_GRANULARITY_VERSION = 1
KNOWLEDGE_TAXONOMY_ACTIVE_CLAIM_INDEX_VERSION = 1
TOPIC_LIFECYCLE_VERSION = 1
TOPIC_LIFECYCLE_ASSESSMENT_CONTRACT_VERSION = 1
KNOWLEDGE_SEMANTIC_CONTRACT_VERSION = 1
KNOWLEDGE_RELATIONSHIP_CONTRACT_VERSION = 2
KNOWLEDGE_RELATIONSHIP_SUPPORT_MIGRATION_VERSION = 1
OFFICIAL_SOURCE_PROOF_MIGRATION_VERSION = 1
KNOWLEDGE_LAYERS = (
    "L1_FOUNDATION",
    "L2_CONTEXT",
    "L3_RELATIONSHIPS",
    "L4_MECHANISMS",
    "L5_SPECIALIST",
)
KNOWLEDGE_CLASSIFICATION_DOMAINS = (
    "general",
    "mathematics",
    "physics",
    "chemistry",
    "astronomy",
    "geography",
    "computer_science",
    "medical",
    "legal",
    "sports",
    "culture_entertainment",
    "business_organization",
    "history_society",
    "other",
)
KNOWLEDGE_FACT_TYPES = (
    "IDENTITY_DEFINITION",
    "ATTRIBUTE",
    "COMPOSITION_STRUCTURE",
    "RELATIONSHIP",
    "HISTORY",
    "PROCESS_MECHANISM",
    "WORK_OUTPUT",
    "LOCATION",
    "QUANTITY_STATISTIC",
    "RULE_STANDARD",
    "COMPARISON",
    "OTHER",
)
KNOWLEDGE_CATEGORY_PATH_MAX_DEPTH = 2
KNOWLEDGE_CATEGORY_PATH_REQUIRED_DEPTH = 2
TOPIC_LIFECYCLE_STATES = {"ACTIVE", "PAUSED_COMPLETE"}
TOPIC_COVERAGE_STATES = {"COVERED", "PARTIAL", "MISSING", "NOT_NEEDED"}
TOPIC_REFRESH_MIN_DAYS = 7
TOPIC_REFRESH_MAX_DAYS = 3650
TOPIC_LIFECYCLE_CONTEXT_CLAIMS = 16

_TEMPORAL_SCOPE_TYPES = {
    "CURRENT_ACTIVE_STATE",
    "LATEST_COMPLETED_PERIOD",
    "EXPLICIT_PERIOD",
}

_PARTITION_LIFECYCLE_BASIS_TYPES = {
    "FIXED_HISTORY": {"stable"},
    "DURABLE_EXPLANATION_DEFINITION_OR_MECHANISM": {"stable"},
    "MAINTAINED_SET_OR_STRUCTURE": {"stable", "reviewable"},
    "TRANSIENT_CURRENT_STATE_OR_EVENT": {"changing", "event", "news"},
    "TRANSIENT_NONSTRUCTURAL_STATE_OR_EVENT": {
        "changing", "event", "news"
    },
}

_CURATION_LOCK = threading.RLock()
_SAFE_TOPIC_ID_RE = re.compile(r"^[a-z0-9][a-z0-9_-]{0,79}$")
_SAFE_RELATION_RE = re.compile(r"^[a-z][a-z0-9_]{0,79}$")
_RELATIONSHIP_TEMPORAL_VIEWS = {"all", "current", "historical"}
_CURRENT_PEOPLE_ROSTER_LIST_RE = re.compile(
    r"(?:成员(?:名单)?|人员名单|members?(?:\s+list)?|roster)\s*"
    r"(?:包括|为|是|有|[:：]|includes?|are)\s*(.+)",
    re.IGNORECASE,
)
_CURRENT_PEOPLE_ROSTER_SPLIT_RE = re.compile(
    r"\s*(?:、|，|,|\band\b|和|及)\s*",
    re.IGNORECASE,
)
_CLOSED_PEOPLE_ROSTER_WORDING_RE = re.compile(
    r"(?:最初|创始|初代|原成员|前成员|曾任|历史|当时|"
    r"original|founding|former|historical|at the time)",
    re.IGNORECASE,
)


def _partition_lifecycle_basis_matches(basis, knowledge_type):
    return str(knowledge_type or "").lower() in (
        _PARTITION_LIFECYCLE_BASIS_TYPES.get(
            str(basis or "").upper(),
            set(),
        )
    )


def normalize_temporal_scope(value):
    """Normalize an upstream AI-owned temporal contract without inferring it."""
    value = value if isinstance(value, dict) else {}
    scope_type = str(value.get("scope_type") or "").upper().strip()
    requested_period = " ".join(
        str(value.get("requested_period") or "").split()
    )[:240]
    if scope_type not in _TEMPORAL_SCOPE_TYPES or not requested_period:
        return {}
    return {
        "scope_type": scope_type,
        "requested_period": requested_period,
        "allow_previous_period": (
            value.get("allow_previous_period")
            if isinstance(value.get("allow_previous_period"), bool)
            else None
        ),
        "closed_period": scope_type in {
            "LATEST_COMPLETED_PERIOD", "EXPLICIT_PERIOD"
        },
    }


def _current_people_roster_entries(record):
    """Return a bounded literal member set for an unclosed roster claim."""

    if not isinstance(record, dict):
        return []
    raw_scope = record.get("temporal_scope")
    raw_scope = raw_scope if isinstance(raw_scope, dict) else {}
    if raw_scope.get("closed_period") is True or normalize_temporal_scope(
        raw_scope
    ).get(
        "closed_period"
    ) is True:
        return []
    text = " ".join([
        str(record.get("subject") or ""),
        str(record.get("claim") or ""),
    ])
    if _CLOSED_PEOPLE_ROSTER_WORDING_RE.search(text):
        return []
    match = _CURRENT_PEOPLE_ROSTER_LIST_RE.search(text)
    if not match:
        return []
    tail = re.split(r"[。；;\n]", match.group(1), maxsplit=1)[0]
    entries = []
    seen = set()
    for raw in _CURRENT_PEOPLE_ROSTER_SPLIT_RE.split(tail):
        value = str(raw or "").strip(
            " \t\r\n:：。.;；'\"“”‘’"
        )[:120]
        identity = " ".join(value.split()).casefold()
        if value and identity not in seen:
            entries.append(value)
            seen.add(identity)
    return entries if 2 <= len(entries) <= 50 else []


def _same_current_people_roster(left, right):
    """Match only an exact subject and exact unordered literal member set."""

    left_subject = " ".join(str(left.get("subject") or "").split()).casefold()
    right_subject = " ".join(str(right.get("subject") or "").split()).casefold()
    if not left_subject or left_subject != right_subject:
        return False
    left_entries = {
        " ".join(value.split()).casefold()
        for value in _current_people_roster_entries(left)
    }
    right_entries = {
        " ".join(value.split()).casefold()
        for value in _current_people_roster_entries(right)
    }
    return bool(left_entries) and left_entries == right_entries


def _merge_knowledge_sources(new_sources, previous_sources, limit=8):
    """Keep fresh evidence first without discarding earlier source history."""

    merged = []
    seen = set()
    for raw in [*(new_sources or []), *(previous_sources or [])]:
        if not isinstance(raw, dict):
            continue
        value = dict(raw)
        identity = str(value.get("url") or "").strip()
        if not identity:
            identity = json.dumps(
                value,
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
            )
        if identity in seen:
            continue
        seen.add(identity)
        merged.append(value)
        if len(merged) >= limit:
            break
    return merged


def _attach_evidence_bundle(item, seed=None, existing=None):
    """Seal new evidence and retain earlier immutable support records."""

    item = item if isinstance(item, dict) else {}
    existing = existing if isinstance(existing, dict) else {}
    claim_id = str(item.get("id") or existing.get("id") or "")
    new_bundle = knowledge_evidence.finalize_bundle(
        claim_id,
        seed,
        data_dir=DATA_DIR,
    )
    old_bundle = existing.get("evidence_bundle")
    merged = knowledge_evidence.merge_bundles(
        claim_id,
        new_bundle,
        old_bundle,
    )
    if merged:
        item["evidence_bundle"] = merged
        item["knowledge_evidence_contract_version"] = (
            KNOWLEDGE_EVIDENCE_CONTRACT_VERSION
        )
        item["evidence_status"] = "SOURCE_BOUND"
    elif isinstance(old_bundle, dict) and old_bundle:
        item["evidence_bundle"] = deepcopy(old_bundle)
        item["knowledge_evidence_contract_version"] = int(
            existing.get("knowledge_evidence_contract_version") or 0
        )
        item["evidence_status"] = str(
            existing.get("evidence_status") or "SOURCE_BOUND"
        )[:60]
    else:
        item["evidence_status"] = "LEGACY_OR_POLICY_ONLY"
    return item


def _temporal_identity_suffix(value):
    """Keep different closed historical snapshots distinct during dedup."""
    scope = normalize_temporal_scope(value)
    if scope.get("closed_period") is not True:
        return ""
    return json.dumps(
        {
            "scope_type": scope["scope_type"],
            "requested_period": scope["requested_period"],
        },
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )

DEFAULT_SOURCES = [
    {
        "name": "Python News",
        "url": "https://www.python.org/blogs/",
        "domain": "python.org",
        "topics": ["python", "programming"],
        "trust": "official",
        "status": "approved",
    },
    {
        "name": "Ollama Blog",
        "url": "https://ollama.com/blog",
        "domain": "ollama.com",
        "topics": ["ollama", "local ai", "language models"],
        "trust": "official",
        "status": "approved",
    },
    {
        "name": "Qt for Python",
        "url": "https://doc.qt.io/qtforpython-6/",
        "domain": "doc.qt.io",
        "topics": ["pyside6", "qt", "python", "desktop development"],
        "trust": "official",
        "status": "approved",
    },
]


def _load(path, default):
    return sqlite_storage.load_document(
        "knowledge",
        sqlite_storage.document_key_for(path),
        path,
        default,
        migration_backup_suffix=(
            sqlite_storage.PHASE_TWO_MIGRATION_BACKUP_SUFFIX
        ),
    )


def _save(path, value, backup=False):
    # ``backup`` remains in the API because knowledge callers use it to mark
    # important generations.  SQLite storage always rotates a last-good JSON
    # mirror and keeps a separate immutable phase-two migration snapshot.
    del backup
    return sqlite_storage.save_document(
        "knowledge",
        sqlite_storage.document_key_for(path),
        path,
        value,
        migration_backup_suffix=(
            sqlite_storage.PHASE_TWO_MIGRATION_BACKUP_SUFFIX
        ),
    )


def _topic_store_dir():
    return os.path.join(DATA_DIR, "knowledge")


def _topics_dir():
    return os.path.join(_topic_store_dir(), "topics")


def _curation_inbox_file():
    return os.path.join(_topic_store_dir(), "inbox.json")


def _topic_index_file():
    return os.path.join(_topic_store_dir(), "index.json")


def _conflicts_file():
    return os.path.join(_topic_store_dir(), "conflicts.json")


def _curator_runs_file():
    return os.path.join(_topic_store_dir(), "curator_runs.json")


def _stable_review_runs_file():
    return os.path.join(_topic_store_dir(), "stable_review_runs.json")


def _empty_inbox():
    return {
        "schema_version": KNOWLEDGE_TOPIC_SCHEMA_VERSION,
        "revision": 0,
        "items": [],
    }


def _empty_index():
    return {
        "schema_version": KNOWLEDGE_TOPIC_SCHEMA_VERSION,
        "active_claim_index_version": 0,
        "category_granularity_version": 0,
        "updated_at": None,
        "topics": {},
        "terms": {},
        "category_paths": [],
        "fact_type_counts": {
            value: 0 for value in KNOWLEDGE_FACT_TYPES
        },
    }


def _empty_conflicts():
    return {
        "schema_version": KNOWLEDGE_TOPIC_SCHEMA_VERSION,
        "revision": 0,
        "items": [],
    }


def _empty_curator_runs():
    return {
        "schema_version": KNOWLEDGE_TOPIC_SCHEMA_VERSION,
        "last_successful_date": None,
        "last_attempt_at": None,
        "runs": [],
    }


def _empty_stable_review_runs():
    return {
        "schema_version": KNOWLEDGE_TOPIC_SCHEMA_VERSION,
        "last_attempt_date": None,
        "last_attempt_at": None,
        "runs": [],
    }


def _topic_path(topic_id):
    value = str(topic_id or "").strip().lower()
    if not _SAFE_TOPIC_ID_RE.fullmatch(value):
        raise ValueError("invalid_topic_id")
    return os.path.join(_topics_dir(), value + ".json")


def normalize_topic_classification(value):
    """Return one current, structurally valid topic taxonomy assignment."""

    value = value if isinstance(value, dict) else {}
    try:
        version = int(value.get("version") or 0)
    except (TypeError, ValueError):
        version = 0
    try:
        granularity_version = int(value.get("granularity_version") or 0)
    except (TypeError, ValueError):
        granularity_version = 0
    domain = str(value.get("domain") or "").lower().strip()
    raw_path = value.get("category_path")
    if (
        version < KNOWLEDGE_CLASSIFICATION_VERSION
        or granularity_version < 0
        or domain not in KNOWLEDGE_CLASSIFICATION_DOMAINS
        or not isinstance(raw_path, list)
        or not 1 <= len(raw_path) <= KNOWLEDGE_CATEGORY_PATH_MAX_DEPTH
    ):
        return {}
    path = []
    seen = set()
    for raw in raw_path:
        if not isinstance(raw, dict):
            return {}
        category_id = str(raw.get("id") or "").lower().strip()
        label = " ".join(str(raw.get("label") or "").split())[:120]
        if (
            not _SAFE_TOPIC_ID_RE.fullmatch(category_id)
            or not label
            or category_id in seen
        ):
            return {}
        seen.add(category_id)
        path.append({"id": category_id, "label": label})
    return {
        "version": KNOWLEDGE_CLASSIFICATION_VERSION,
        "granularity_version": granularity_version,
        "domain": domain,
        "category_path": path,
        "reason": str(value.get("reason") or "")[:500],
        "classified_at": value.get("classified_at"),
    }


def topic_classification_is_current(value):
    """Return whether a valid legacy classification meets current depth."""

    normalized = normalize_topic_classification(value)
    return bool(
        normalized
        and normalized.get("granularity_version", 0)
        >= KNOWLEDGE_CATEGORY_GRANULARITY_VERSION
        and len(normalized.get("category_path", []))
        == KNOWLEDGE_CATEGORY_PATH_REQUIRED_DEPTH
    )


def _category_token_root(value):
    token = str(value or "").casefold()
    if token.endswith("ies") and len(token) > 4:
        return token[:-3] + "y"
    if (
        token.endswith("s")
        and len(token) > 3
        and not token.endswith(("ss", "us", "is"))
    ):
        return token[:-1]
    return token


def _category_id_key(value):
    tokens = re.findall(r"[a-z0-9]+", str(value or "").casefold())
    return "_".join(_category_token_root(token) for token in tokens)


def _category_label_key(value):
    text = unicodedata.normalize("NFKC", str(value or "")).casefold()
    tokens = re.findall(r"[a-z0-9]+", text)
    if tokens and re.sub(r"[^a-z0-9]+", "", text) == "".join(tokens):
        return "".join(_category_token_root(token) for token in tokens)
    return re.sub(r"[^\w]+", "", text, flags=re.UNICODE).replace("_", "")


def category_catalog_conflicts(classification, category_catalog=None):
    """Reject sibling category aliases before they fragment the catalog."""

    proposed = normalize_topic_classification(classification)
    if not proposed:
        return ["topic_classification_invalid"]
    rows = category_catalog
    if rows is None:
        rows = load_category_catalog()
    known = {}
    for row in rows or []:
        if not isinstance(row, dict):
            continue
        existing = normalize_topic_classification({
            "version": row.get("version", KNOWLEDGE_CLASSIFICATION_VERSION),
            "granularity_version": row.get("granularity_version", 0),
            "domain": row.get("domain"),
            "category_path": row.get("category_path"),
        })
        if not existing:
            continue
        parent_id = ""
        for depth, node in enumerate(existing["category_path"]):
            key = (existing["domain"], parent_id, depth)
            known.setdefault(key, []).append(node)
            parent_id = node["id"]

    errors = []
    parent_id = ""
    for depth, node in enumerate(proposed["category_path"]):
        key = (proposed["domain"], parent_id, depth)
        proposed_id = node["id"]
        proposed_label = node["label"]
        proposed_id_key = _category_id_key(proposed_id)
        proposed_label_key = _category_label_key(proposed_label)
        for old in known.get(key, []):
            old_id = str(old.get("id") or "")
            old_label = str(old.get("label") or "")
            if old_id == proposed_id:
                if _category_label_key(old_label) != proposed_label_key:
                    errors.append("category_label_mismatch")
                continue
            if (
                proposed_label_key
                and _category_label_key(old_label) == proposed_label_key
            ):
                errors.append("category_duplicate_label")
            if (
                proposed_id_key
                and _category_id_key(old_id) == proposed_id_key
            ):
                errors.append("category_duplicate_id")
        parent_id = proposed_id
    return sorted(set(errors))


def _classification_identity(value):
    normalized = normalize_topic_classification(value)
    if not normalized:
        return None
    return (
        normalized["domain"],
        tuple(
            (node["id"], _category_label_key(node["label"]))
            for node in normalized["category_path"]
        ),
    )


def topic_classification_identity(value):
    """Return the stable domain/path identity used by lifecycle guards."""

    return _classification_identity(value)


def topic_classification_preserves_prefix(existing, proposed):
    """Keep every established node while adding only missing path depth."""

    old = normalize_topic_classification(existing)
    new = normalize_topic_classification(proposed)
    if not old or not new:
        return False
    old_path = old.get("category_path", [])
    new_path = new.get("category_path", [])
    return bool(
        old.get("domain") == new.get("domain")
        and len(new_path) >= len(old_path)
        and all(
            old_node.get("id") == new_path[index].get("id")
            and _category_label_key(old_node.get("label"))
            == _category_label_key(new_path[index].get("label"))
            for index, old_node in enumerate(old_path)
        )
    )


def _claim_classification_state(claim):
    curation = claim.get("curation")
    curation = curation if isinstance(curation, dict) else {}
    fact_type = str(curation.get("fact_type") or "").upper().strip()
    try:
        version = int(curation.get("classification_version") or 0)
    except (TypeError, ValueError):
        version = 0
    return fact_type, version


def _active_persistable(item, now=None):
    """Check structural persistence state already decided by upstream AI."""
    if not isinstance(item, dict) or item.get("status") != "verified":
        return False
    knowledge_type = str(item.get("knowledge_type") or "stable").lower()
    if knowledge_type not in {"stable", "reviewable"}:
        return False
    if knowledge_type == "stable":
        return True
    expires_at = str(item.get("expires_at") or "").strip()
    if not expires_at:
        return False
    try:
        expiry = datetime.fromisoformat(expires_at.replace("Z", "+00:00"))
        if expiry.tzinfo is None:
            expiry = expiry.replace(tzinfo=timezone.utc)
    except (TypeError, ValueError):
        return False
    return expiry > (now or datetime.now(timezone.utc))


def _curation_fingerprint(item):
    evidence_bundle = item.get("evidence_bundle")
    evidence_bundle = (
        evidence_bundle if isinstance(evidence_bundle, dict) else {}
    )
    fields = {
        "id": item.get("id"),
        "subject": item.get("subject"),
        "claim": item.get("claim"),
        "knowledge_type": item.get("knowledge_type"),
        "expires_at": item.get("expires_at"),
        "verification_status": item.get("verification_status"),
        "sources": item.get("sources"),
        "temporal_scope": normalize_temporal_scope(
            item.get("temporal_scope")
        ),
        "display_version": KNOWLEDGE_DISPLAY_VERSION,
    }
    evidence_fingerprint = str(
        evidence_bundle.get("fingerprint") or ""
    )
    # Preserve every pre-evidence curation fingerprint exactly.  Evidence is
    # revision material only after a claim actually adopts this contract, so
    # installing the feature never requeues the user's existing knowledge.
    if evidence_fingerprint:
        fields["evidence_fingerprint"] = evidence_fingerprint
    material = json.dumps(
        fields,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(material).hexdigest()


def initialize_topic_store():
    os.makedirs(_topics_dir(), exist_ok=True)
    defaults = (
        (_curation_inbox_file(), _empty_inbox()),
        (_topic_index_file(), _empty_index()),
        (_conflicts_file(), _empty_conflicts()),
        (_curator_runs_file(), _empty_curator_runs()),
        (_stable_review_runs_file(), _empty_stable_review_runs()),
    )
    for path, default in defaults:
        _load(path, default)


def _sync_curation_inbox(items):
    """Queue every verified reusable revision exactly once for AI curation."""
    initialize_topic_store()
    with _CURATION_LOCK:
        payload = _load(_curation_inbox_file(), _empty_inbox())
        if not isinstance(payload, dict):
            payload = _empty_inbox()
        entries = payload.get("items")
        if not isinstance(entries, list):
            entries = []
        by_id = {
            str(entry.get("knowledge_id") or ""): entry
            for entry in entries
            if isinstance(entry, dict) and entry.get("knowledge_id")
        }
        changed = False
        now = datetime.now(timezone.utc)
        current_items = {
            str(item.get("id") or ""): item
            for item in items if isinstance(item, dict) and item.get("id")
        } if isinstance(items, list) else {}
        for entry in entries:
            if not isinstance(entry, dict) or entry.get("state") != "PENDING":
                continue
            current = current_items.get(str(entry.get("knowledge_id") or ""))
            if current is None or not _active_persistable(current, now=now):
                entry["state"] = "INACTIVE"
                entry["completed_at"] = now.isoformat()
                entry["last_reason"] = "authoritative_record_inactive"
                changed = True
        for item in current_items.values():
            if not _active_persistable(item, now=now):
                continue
            knowledge_id = str(item.get("id") or "").strip()
            if not knowledge_id:
                continue
            fingerprint = _curation_fingerprint(item)
            old = by_id.get(knowledge_id)
            if old is not None and old.get("fingerprint") == fingerprint:
                continue
            if old is None:
                old = {
                    "id": "curation_" + hashlib.sha256(
                        (knowledge_id + "\n" + fingerprint).encode("utf-8")
                    ).hexdigest()[:20],
                    "knowledge_id": knowledge_id,
                    "enqueued_at": now.isoformat(),
                    "attempt_count": 0,
                }
                entries.append(old)
                by_id[knowledge_id] = old
            else:
                old["previous_fingerprint"] = old.get("fingerprint")
                old["enqueued_at"] = now.isoformat()
            old["fingerprint"] = fingerprint
            old["state"] = "PENDING"
            old["last_reason"] = None
            changed = True
        if changed:
            payload["items"] = entries[-5000:]
            payload["revision"] = int(payload.get("revision") or 0) + 1
            _save(_curation_inbox_file(), payload, backup=True)
    return changed


def _clusters_file():
    return os.path.join(DATA_DIR, "knowledge_clusters.json")


def _cluster_metadata(item):
    """Build a stable topic/entity cluster without changing claim semantics."""
    domain = str(item.get("knowledge_domain") or "other").lower().strip()[:80]
    subject = str(item.get("subject") or "").strip()[:300]
    entity = str(item.get("cluster_label") or subject).strip()[:120]
    topics = []
    for value in item.get("topics", []):
        topic = str(value).strip()[:80]
        if topic and topic.casefold() not in {old.casefold() for old in topics}:
            topics.append(topic)
        if len(topics) >= 12:
            break
    material = (domain + "\n" + entity.casefold()).encode("utf-8")
    return {
        "id": "cluster_" + hashlib.sha256(material).hexdigest()[:16],
        "domain": domain,
        "entity": entity,
        "topics": topics,
        "version": KNOWLEDGE_CLUSTER_VERSION,
    }


def _rebuild_cluster_index(items):
    clusters = {}
    now = datetime.now(timezone.utc)
    for item in items:
        if not isinstance(item, dict) or item.get("status") != "verified":
            continue
        knowledge_type = str(
            item.get("knowledge_type") or "stable"
        ).lower()
        if knowledge_type not in {
            "stable", "reviewable"
        }:
            continue
        if knowledge_type == "reviewable":
            try:
                expiry = datetime.fromisoformat(str(item.get("expires_at") or ""))
                if expiry.tzinfo is None:
                    expiry = expiry.replace(tzinfo=timezone.utc)
                if expiry <= now:
                    continue
            except (TypeError, ValueError):
                continue
        cluster = item.get("cluster")
        if not isinstance(cluster, dict):
            cluster = _cluster_metadata(item)
        cluster_id = str(cluster.get("id") or "")
        if not cluster_id:
            continue
        group = clusters.setdefault(
            cluster_id,
            {
                "id": cluster_id,
                "domain": str(cluster.get("domain") or "other")[:80],
                "entity": str(cluster.get("entity") or "")[:300],
                "topics": [],
                "knowledge_ids": [],
            },
        )
        for topic in cluster.get("topics", []):
            topic = str(topic).strip()[:80]
            if topic and topic not in group["topics"]:
                group["topics"].append(topic)
        item_id = str(item.get("id") or "")
        if item_id and item_id not in group["knowledge_ids"]:
            group["knowledge_ids"].append(item_id)
    payload = {
        "version": KNOWLEDGE_CLUSTER_VERSION,
        "rebuilt_at": datetime.now(timezone.utc).isoformat(),
        "clusters": sorted(
            clusters.values(),
            key=lambda value: (
                value.get("domain", ""),
                value.get("entity", ""),
            ),
        ),
    }
    _save(_clusters_file(), payload)


def _save_knowledge(items, sync_curation=True):
    _save(KNOWLEDGE_FILE, items)
    _rebuild_cluster_index(items)
    if sync_curation:
        _sync_curation_inbox(items)


def _quarantine_unproven_strict_official_items(items):
    """Deactivate legacy Casper claims that violated an official-only request."""

    import source_scope

    if not isinstance(items, list):
        return 0
    changed = 0
    now = datetime.now(timezone.utc).isoformat()
    for item in items:
        if not isinstance(item, dict) or item.get("status") != "verified":
            continue
        provenance = item.get("provenance")
        provenance = dict(provenance) if isinstance(provenance, dict) else {}
        if str(provenance.get("origin") or "") != "casper_audited_fact_lookup":
            continue
        verification = item.get("verification")
        verification = (
            verification if isinstance(verification, dict) else {}
        )
        original_request = str(
            verification.get("original_request")
            or verification.get("original_question")
            or ""
        )
        contract = source_scope.route_contract(original_request)
        if not source_scope.official_only(original_request):
            continue
        sources = item.get("sources")
        sources = sources if isinstance(sources, list) else []
        if any(
            isinstance(source, dict)
            and source.get("official_identity_verified") is True
            for source in sources
        ):
            continue
        history = item.get("revision_history")
        history = list(history) if isinstance(history, list) else []
        history.append(
            _knowledge_revision_snapshot(
                item,
                "UNPROVEN_OFFICIAL_SOURCE_QUARANTINED",
                now,
            )
        )
        item["revision_history"] = history[-20:]
        item["status"] = "disputed"
        item["verification_status"] = (
            "QUARANTINED_UNPROVEN_OFFICIAL_SOURCE"
        )
        item["updated_at"] = now
        item["quarantine"] = {
            "status": "INACTIVE_PENDING_REVERIFICATION",
            "reason": "strict_official_request_missing_deterministic_identity_proof",
            "quarantined_at": now,
            "source_contract": contract,
        }
        item["dispute"] = {
            "status": "PENDING_REVERIFICATION",
            "disputed_at": now,
            "previous_status": "verified",
            "user_message": "",
            "reason": "Unproven official-source identity from a legacy build.",
        }
        provenance["official_source_proof_migration_version"] = (
            OFFICIAL_SOURCE_PROOF_MIGRATION_VERSION
        )
        item["provenance"] = provenance
        changed += 1
    return changed


def initialize():
    os.makedirs(DATA_DIR, exist_ok=True)
    items = _load(KNOWLEDGE_FILE, [])
    quarantined = _quarantine_unproven_strict_official_items(items)
    if quarantined:
        _save(KNOWLEDGE_FILE, items)
        print(
            "[KNOWLEDGE OFFICIAL SOURCE QUARANTINE]",
            "items=" + str(quarantined),
        )
    _load(SOURCES_FILE, DEFAULT_SOURCES)
    _load(LOGS_FILE, [])
    _load(PENDING_SOURCES_FILE, [])
    knowledge_evidence.initialize(DATA_DIR)
    clusters = _load(_clusters_file(), None)
    if quarantined or not isinstance(clusters, dict):
        _rebuild_cluster_index(items)
    initialize_topic_store()
    repaired_topics = _repair_topic_store_semantics()
    topic_index = _load(_topic_index_file(), _empty_index())
    try:
        active_claim_index_version = int(
            topic_index.get("active_claim_index_version") or 0
        ) if isinstance(topic_index, dict) else 0
    except (TypeError, ValueError):
        active_claim_index_version = 0
    try:
        category_granularity_version = int(
            topic_index.get("category_granularity_version") or 0
        ) if isinstance(topic_index, dict) else 0
    except (TypeError, ValueError):
        category_granularity_version = 0
    if (
        repaired_topics
        or active_claim_index_version
        < KNOWLEDGE_TAXONOMY_ACTIVE_CLAIM_INDEX_VERSION
        or category_granularity_version
        < KNOWLEDGE_CATEGORY_GRANULARITY_VERSION
    ):
        _rebuild_topic_index()
    _sync_curation_inbox(items)


def load_items():
    initialize()
    return _load(KNOWLEDGE_FILE, [])


def visual_backfill_claim_fingerprint(item):
    """Seal the exact active claim and its already-accepted source boundary."""

    item = item if isinstance(item, dict) else {}
    material = {
        "id": str(item.get("id") or ""),
        "subject": str(item.get("subject") or ""),
        "claim": str(item.get("claim") or ""),
        "status": str(item.get("status") or ""),
        "knowledge_type": str(item.get("knowledge_type") or "stable"),
        "expires_at": item.get("expires_at"),
        "temporal_scope": normalize_temporal_scope(
            item.get("temporal_scope")
        ),
        "verification_status": str(
            item.get("verification_status") or ""
        ),
        "sources": item.get("sources")
        if isinstance(item.get("sources"), list) else [],
    }
    return hashlib.sha256(
        json.dumps(
            material,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    ).hexdigest()


def attach_visual_evidence_to_existing_claim(
    knowledge_id,
    expected_claim_fingerprint,
    expected_source_id,
    evidence_seed,
    *,
    attached_at=None,
):
    """Attach sealed text+image evidence without rewriting claim semantics."""

    requested_id = str(knowledge_id or "").strip()
    expected_fingerprint = str(expected_claim_fingerprint or "").strip()
    source_id = str(expected_source_id or "").strip()
    if not requested_id or not expected_fingerprint or not source_id:
        return "invalid_request", None
    if not isinstance(evidence_seed, dict):
        return "invalid_evidence", None

    with _CURATION_LOCK:
        items = _load(KNOWLEDGE_FILE, [])
        index = next(
            (
                position for position, value in enumerate(items)
                if isinstance(value, dict)
                and str(value.get("id") or "") == requested_id
            ),
            None,
        )
        if index is None:
            return "missing", None
        existing = items[index]
        if not _active_persistable(existing):
            return "inactive", deepcopy(existing)
        if visual_backfill_claim_fingerprint(existing) != expected_fingerprint:
            return "claim_changed", deepcopy(existing)

        allowed_source_ids = set()
        raw_sources = [
            value for value in existing.get("sources", [])
            if isinstance(value, dict)
        ]
        if not raw_sources and existing.get("source_url"):
            raw_sources.append({
                "title": existing.get("source_name"),
                "url": existing.get("source_url"),
                "domain": existing.get("source_domain"),
            })
        for source in raw_sources:
            if not knowledge_evidence.is_public_source(source):
                continue
            compact = knowledge_evidence.compact_source(source)
            if compact.get("source_id"):
                allowed_source_ids.add(compact["source_id"])
            try:
                parsed = urlparse(str(source.get("url") or ""))
                sanitized = dict(source)
                sanitized["url"] = parsed._replace(
                    params="", query="", fragment=""
                ).geturl()
            except ValueError:
                sanitized = {}
            if sanitized and knowledge_evidence.is_public_source(sanitized):
                compact = knowledge_evidence.compact_source(sanitized)
                if compact.get("source_id"):
                    allowed_source_ids.add(compact["source_id"])
        if source_id not in allowed_source_ids:
            return "source_not_bound", deepcopy(existing)

        old_bundle = existing.get("evidence_bundle")
        old_bundle = old_bundle if isinstance(old_bundle, dict) else {}
        if any(
            isinstance(record, dict)
            and record.get("modality") == "IMAGE"
            for record in old_bundle.get("records", [])
        ):
            return "already_present", deepcopy(existing)
        media_index = knowledge_evidence.load_media_index(DATA_DIR)
        media_assets = media_index.get("assets")
        media_assets = media_assets if isinstance(media_assets, dict) else {}
        if old_bundle and knowledge_evidence.validate_bundle(
            old_bundle, media_assets
        ):
            return "existing_evidence_invalid", deepcopy(existing)

        seed_records = [
            value for value in evidence_seed.get("records", [])
            if isinstance(value, dict)
        ]
        seed_modalities = {
            str(value.get("modality") or "") for value in seed_records
        }
        seed_source_ids = {
            str(
                knowledge_evidence.compact_source(
                    value.get("source")
                ).get("source_id") or ""
            )
            for value in seed_records
        }
        if (
            not {"TEXT", "IMAGE"}.issubset(seed_modalities)
            or seed_source_ids != {source_id}
        ):
            return "invalid_evidence", deepcopy(existing)

        enriched = deepcopy(existing)
        _attach_evidence_bundle(
            enriched,
            evidence_seed,
            existing=existing,
        )
        bundle = enriched.get("evidence_bundle")
        bundle = bundle if isinstance(bundle, dict) else {}
        media_index = knowledge_evidence.load_media_index(DATA_DIR)
        media_assets = media_index.get("assets")
        media_assets = media_assets if isinstance(media_assets, dict) else {}
        if (
            str(bundle.get("claim_id") or "") != requested_id
            or not {"TEXT", "IMAGE"}.issubset(
                set(bundle.get("modalities") or [])
            )
            or knowledge_evidence.validate_bundle(bundle, media_assets)
        ):
            return "invalid_evidence", deepcopy(existing)

        timestamp = str(
            attached_at or datetime.now(timezone.utc).isoformat()
        )[:100]
        enriched["visual_evidence_backfill"] = {
            "contract_version": (
                KNOWLEDGE_LEGACY_VISUAL_BACKFILL_CONTRACT_VERSION
            ),
            "status": "ATTACHED",
            "source_id": source_id[:80],
            "attached_at": timestamp,
        }
        enriched["updated_at"] = timestamp
        items[index] = enriched
        # Evidence-only enrichment must not re-open semantic curation of the
        # unchanged claim.
        _save_knowledge(items, sync_curation=False)
        return "attached", deepcopy(enriched)


def load_knowledge_evidence(knowledge_id, include_asset_paths=False):
    """Return one claim's source evidence and public image metadata."""

    requested_id = str(knowledge_id or "").strip()
    item = next(
        (
            value for value in load_items()
            if isinstance(value, dict)
            and str(value.get("id") or "") == requested_id
        ),
        None,
    )
    if not isinstance(item, dict):
        return None
    bundle = item.get("evidence_bundle")
    bundle = deepcopy(bundle) if isinstance(bundle, dict) else {}
    media_index = knowledge_evidence.load_media_index(DATA_DIR)
    media_assets = media_index.get("assets")
    media_assets = media_assets if isinstance(media_assets, dict) else {}
    referenced_ids = []
    for record in bundle.get("records", []):
        if not isinstance(record, dict):
            continue
        for asset_id in record.get("asset_ids", []):
            asset_id = str(asset_id or "")
            if asset_id and asset_id not in referenced_ids:
                referenced_ids.append(asset_id)
    assets = []
    for asset_id in referenced_ids:
        metadata = media_assets.get(asset_id)
        if not isinstance(metadata, dict):
            continue
        value = deepcopy(metadata)
        if include_asset_paths:
            value["resolved_path"] = knowledge_evidence.resolve_asset_path(
                asset_id,
                data_dir=DATA_DIR,
            )
        assets.append(value)
    return {
        "knowledge_id": requested_id,
        "evidence_status": str(
            item.get("evidence_status") or "LEGACY_OR_POLICY_ONLY"
        ),
        "bundle": bundle,
        "summary": knowledge_evidence.bundle_summary(bundle),
        "assets": assets,
    }


def audit_knowledge_evidence(verify_files=True):
    """Read and verify all evidence bundles plus cached public media."""

    items = load_items()
    media_index = knowledge_evidence.load_media_index(DATA_DIR)
    return knowledge_evidence.audit_evidence_store(
        items,
        data_dir=DATA_DIR,
        media_index=media_index,
        verify_files=bool(verify_files),
    )


def load_partition_lifecycle_audit_candidates(limit=24):
    """Return pre-audit mixed-answer records without inferring semantics."""
    candidates = []
    for item in load_items():
        if not isinstance(item, dict):
            continue
        provenance = item.get("provenance")
        provenance = provenance if isinstance(provenance, dict) else {}
        if provenance.get("mixed_answer_partition") is not True:
            continue
        try:
            version = int(item.get("partition_lifecycle_audit_version") or 0)
        except (TypeError, ValueError):
            version = 0
        if version >= PARTITION_LIFECYCLE_AUDIT_VERSION:
            continue
        status = str(item.get("status") or "").lower()
        lifecycle_audit = item.get("lifecycle_audit")
        lifecycle_audit = (
            lifecycle_audit if isinstance(lifecycle_audit, dict) else {}
        )
        recoverable_old_demotion = (
            status == "expired"
            and version > 0
            and str(lifecycle_audit.get("status") or "").upper() == "PASSED"
            and str(item.get("knowledge_type") or "").lower()
            in {"changing", "event", "news"}
        )
        if status != "verified" and not recoverable_old_demotion:
            continue
        candidates.append(item)
        if len(candidates) >= max(1, int(limit)):
            break
    return candidates


def apply_partition_lifecycle_reaudit(decisions):
    """Apply exact AI lifecycle decisions while retaining an audit trail."""
    if not isinstance(decisions, list):
        raise ValueError("partition_lifecycle_decisions_invalid")
    decision_by_id = {
        str(item.get("id") or ""): item
        for item in decisions if isinstance(item, dict) and item.get("id")
    }
    if len(decision_by_id) != len(decisions):
        raise ValueError("partition_lifecycle_decision_ids_invalid")
    with _CURATION_LOCK:
        items = load_items()
        item_by_id = {
            str(item.get("id") or ""): item
            for item in items if isinstance(item, dict) and item.get("id")
        }
        if any(value not in item_by_id for value in decision_by_id):
            raise ValueError("partition_lifecycle_unknown_id")
        counts = {"audited": 0, "stable": 0, "reviewable": 0, "removed": 0}
        now = datetime.now(timezone.utc)
        for knowledge_id, decision in decision_by_id.items():
            item = item_by_id[knowledge_id]
            try:
                audit_version = int(
                    decision.get("partition_lifecycle_audit_version") or 0
                )
            except (TypeError, ValueError):
                audit_version = 0
            if (
                decision.get("lifecycle_proportional") is not True
                or audit_version < PARTITION_LIFECYCLE_AUDIT_VERSION
            ):
                raise ValueError("partition_lifecycle_audit_not_certified")
            knowledge_type = str(
                decision.get("knowledge_type") or "event"
            ).lower()
            lifecycle_basis = str(
                decision.get("lifecycle_basis") or ""
            ).upper()
            if not _partition_lifecycle_basis_matches(
                lifecycle_basis, knowledge_type
            ):
                raise ValueError("partition_lifecycle_basis_mismatch")
            valid_for_days = decision.get("valid_for_days")
            persist = decision.get("persist") is True
            if knowledge_type == "stable":
                if valid_for_days is not None:
                    raise ValueError("stable_partition_audit_has_expiry")
                expires_at = None
            elif knowledge_type == "reviewable":
                if (
                    not isinstance(valid_for_days, int)
                    or not 1 <= valid_for_days <= 3650
                ):
                    raise ValueError("reviewable_partition_audit_missing_expiry")
                expires_at = (now + timedelta(days=valid_for_days)).isoformat()
            elif knowledge_type in {"changing", "event", "news"}:
                if valid_for_days is not None:
                    raise ValueError("current_partition_audit_has_expiry")
                persist = False
                expires_at = now.isoformat()
            else:
                raise ValueError("partition_lifecycle_type_invalid")
            item["knowledge_type"] = knowledge_type
            item["valid_for_days"] = valid_for_days
            item["expires_at"] = expires_at
            item["partition_lifecycle_audit_version"] = audit_version
            item["lifecycle_audit"] = {
                "status": "PASSED",
                "audited_at": now.isoformat(),
                "basis": lifecycle_basis[:80],
                "reason": str(decision.get("reason") or "")[:500],
            }
            item["updated_at"] = now.isoformat()
            if persist and knowledge_type in {"stable", "reviewable"}:
                item["status"] = "verified"
                counts[knowledge_type] += 1
            else:
                item["status"] = "expired"
                counts["removed"] += 1
            counts["audited"] += 1
        _save_knowledge(items)
        return counts


def load_active_items():
    """Return permanent stable and unexpired reviewable knowledge."""
    pending_ids = {
        str(entry.get("knowledge_id") or "")
        for entry in load_curation_inbox(pending_only=True)
        if isinstance(entry, dict)
    }
    curated = {
        str(item.get("id") or ""): item
        for item in load_curated_items()
        if isinstance(item, dict) and item.get("id")
    }
    raw = load_items()
    raw_by_id = {
        str(item.get("id") or ""): item
        for item in raw if isinstance(item, dict) and item.get("id")
    }
    candidates = []
    for knowledge_id, curated_item in curated.items():
        raw_item = raw_by_id.get(knowledge_id)
        if raw_item is None or knowledge_id in pending_ids:
            continue
        raw_curation = raw_item.get("curation")
        raw_curation = raw_curation if isinstance(raw_curation, dict) else {}
        if raw_curation.get("status") in {"duplicate", "conflict"}:
            continue
        # The flat ledger remains authoritative for verification and expiry;
        # the topic document contributes only AI curation metadata.
        merged = dict(raw_item)
        curated_curation = curated_item.get("curation")
        if isinstance(curated_curation, dict):
            merged["curation"] = dict(curated_curation)
        topic_lifecycle = curated_item.get("topic_lifecycle")
        if isinstance(topic_lifecycle, dict):
            merged["topic_lifecycle"] = deepcopy(topic_lifecycle)
        candidates.append(merged)
    curated_ids = {
        str(item.get("id") or "")
        for item in candidates
        if isinstance(item, dict)
    }
    for item in raw:
        if not isinstance(item, dict):
            continue
        knowledge_id = str(item.get("id") or "")
        curation = item.get("curation")
        curation = curation if isinstance(curation, dict) else {}
        if curation.get("status") in {"duplicate", "conflict"}:
            continue
        if knowledge_id and knowledge_id in curated_ids:
            continue
        candidates.append(item)

    now = datetime.now(timezone.utc)
    active = []
    for item in candidates:
        if _active_persistable(item, now=now):
            active.append(item)
    return active


def _knowledge_revision_snapshot(item, event, recorded_at):
    """Keep a compact immutable record before a correction changes state."""
    return {
        "event": str(event or "")[:60],
        "recorded_at": str(recorded_at or "")[:80],
        "subject": str(item.get("subject") or "")[:300],
        "claim": str(item.get("claim") or "")[:3000],
        "knowledge_type": str(item.get("knowledge_type") or "")[:30],
        "valid_for_days": item.get("valid_for_days"),
        "expires_at": item.get("expires_at"),
        "status": str(item.get("status") or "")[:40],
        "verification_status": str(
            item.get("verification_status") or ""
        )[:100],
        "temporal_scope": normalize_temporal_scope(
            item.get("temporal_scope")
        ),
        "evidence_fingerprint": str(
            (
                item.get("evidence_bundle")
                if isinstance(item.get("evidence_bundle"), dict)
                else {}
            ).get("fingerprint") or ""
        )[:64],
    }


def mark_user_disputed_items(knowledge_ids, user_message, reason=""):
    """Deactivate only AI-selected objective claims pending reverification."""
    selected = []
    for value in knowledge_ids or []:
        knowledge_id = str(value or "").strip()
        if knowledge_id and knowledge_id not in selected:
            selected.append(knowledge_id)
    if not selected:
        return []
    selected_set = set(selected)
    now = datetime.now(timezone.utc).isoformat()
    disputed = []
    with _CURATION_LOCK:
        items = load_items()
        changed = False
        for item in items:
            if not isinstance(item, dict) or str(item.get("id") or "") not in selected_set:
                continue
            if str(item.get("status") or "").lower() not in {
                "verified", "disputed"
            }:
                continue
            if str(item.get("status") or "").lower() != "disputed":
                history = item.get("revision_history")
                history = list(history) if isinstance(history, list) else []
                history.append(
                    _knowledge_revision_snapshot(item, "USER_DISPUTED", now)
                )
                item["revision_history"] = history[-20:]
            previous_status = str(item.get("status") or "verified")
            item["status"] = "disputed"
            item["updated_at"] = now
            item["dispute"] = {
                "status": "PENDING_REVERIFICATION",
                "disputed_at": now,
                "previous_status": previous_status,
                "user_message": str(user_message or "")[:1200],
                "reason": str(reason or "")[:500],
            }
            disputed.append(dict(item))
            changed = True
        if changed:
            _save_knowledge(items)
    return disputed


def resolve_user_dispute(
    disputed_ids,
    replacement_ids=None,
    verified_answer=False,
    reason="",
):
    """Link replacement knowledge or keep the challenged record inactive."""
    targets = {
        str(value or "").strip()
        for value in (disputed_ids or [])
        if str(value or "").strip()
    }
    replacements = []
    for value in replacement_ids or []:
        knowledge_id = str(value or "").strip()
        if knowledge_id and knowledge_id not in replacements:
            replacements.append(knowledge_id)
    if not targets:
        return {"resolved": 0, "replacements": replacements}
    replacement_set = set(replacements)
    now = datetime.now(timezone.utc).isoformat()
    resolved = 0
    with _CURATION_LOCK:
        items = load_items()
        by_id = {
            str(item.get("id") or ""): item
            for item in items if isinstance(item, dict) and item.get("id")
        }
        for knowledge_id in targets:
            item = by_id.get(knowledge_id)
            if item is None:
                continue
            dispute = item.get("dispute")
            dispute = dict(dispute) if isinstance(dispute, dict) else {}
            dispute["resolved_at"] = now
            dispute["resolution_reason"] = str(reason or "")[:500]
            if knowledge_id in replacement_set:
                item["status"] = "verified"
                dispute["status"] = "RESOLVED_REFRESHED"
                item.pop("superseded_by", None)
            elif replacements:
                item["status"] = "superseded"
                item["superseded_by"] = list(replacements)
                dispute["status"] = "RESOLVED_REPLACED"
            elif verified_answer:
                item["status"] = "disputed"
                dispute["status"] = "ANSWERED_NO_REUSABLE_REPLACEMENT"
            else:
                item["status"] = "disputed"
                dispute["status"] = "PENDING_REVERIFICATION"
            item["dispute"] = dispute
            item["updated_at"] = now
            resolved += 1
        for replacement_id in replacement_set - targets:
            replacement = by_id.get(replacement_id)
            if replacement is None:
                continue
            provenance = replacement.get("provenance")
            provenance = dict(provenance) if isinstance(provenance, dict) else {}
            old = [
                str(value)
                for value in provenance.get("supersedes_knowledge_ids", [])
                if str(value)
            ]
            for knowledge_id in targets:
                if knowledge_id not in old:
                    old.append(knowledge_id)
            provenance["supersedes_knowledge_ids"] = old[-20:]
            provenance["correction_reverified_at"] = now
            replacement["provenance"] = provenance
        if resolved:
            _save_knowledge(items)
    return {"resolved": resolved, "replacements": replacements}


def load_clusters():
    initialize()
    value = _load(_clusters_file(), {})
    return value if isinstance(value, dict) else {"clusters": []}


def load_curation_inbox(pending_only=False):
    initialize_topic_store()
    payload = _load(_curation_inbox_file(), _empty_inbox())
    items = payload.get("items", []) if isinstance(payload, dict) else []
    items = [item for item in items if isinstance(item, dict)]
    if pending_only:
        return [item for item in items if item.get("state") == "PENDING"]
    return items


def load_curator_runs():
    initialize_topic_store()
    value = _load(_curator_runs_file(), _empty_curator_runs())
    return value if isinstance(value, dict) else _empty_curator_runs()


def audit_curator_terminal_outcome_payloads(
    ledger,
    inbox,
    topic_documents,
    conflicts,
):
    """Validate every Curator terminal state without topic-specific rules.

    The function is intentionally pure so a live validator can pass documents
    read from SQLite in read-only mode.  CURATED must resolve to its exact
    authoritative Topic claim, DUPLICATE must resolve to a real Topic claim,
    and CONFLICT must close through its conflict record, Topic, and every
    related existing claim.  No subject, team, or ecosystem is special-cased.
    """

    ledger = ledger if isinstance(ledger, list) else []
    inbox = inbox if isinstance(inbox, dict) else {}
    conflicts = conflicts if isinstance(conflicts, dict) else {}
    if isinstance(topic_documents, dict):
        supplied_topics = list(topic_documents.items())
    elif isinstance(topic_documents, list):
        supplied_topics = [("", value) for value in topic_documents]
    else:
        supplied_topics = []

    topics = {}
    claims_by_topic = {}
    claim_topics = {}
    for supplied_id, document in supplied_topics:
        if not isinstance(document, dict):
            continue
        topic = document.get("topic")
        topic = topic if isinstance(topic, dict) else {}
        topic_id = str(topic.get("id") or supplied_id or "").lower().strip()
        if not _SAFE_TOPIC_ID_RE.fullmatch(topic_id):
            continue
        topics[topic_id] = document
        topic_claims = {}
        for claim in document.get("claims", []):
            if not isinstance(claim, dict):
                continue
            claim_id = str(claim.get("id") or "").strip()
            if not claim_id:
                continue
            topic_claims[claim_id] = claim
            claim_topics.setdefault(claim_id, []).append(topic_id)
        claims_by_topic[topic_id] = topic_claims

    conflict_rows = {
        str(value.get("id") or ""): value
        for value in conflicts.get("items", [])
        if isinstance(value, dict) and str(value.get("id") or "")
    }
    ledger_by_id = {
        str(value.get("id") or ""): value
        for value in ledger
        if isinstance(value, dict) and str(value.get("id") or "")
    }
    counts = {
        "curated": 0,
        "duplicate": 0,
        "conflict": 0,
        "terminal": 0,
    }
    failures = []
    outcomes = []

    def add_failure(knowledge_id, code):
        value = str(knowledge_id or "unknown") + ":" + str(code)
        if value not in failures:
            failures.append(value)

    for knowledge_id, item in ledger_by_id.items():
        curation = item.get("curation")
        curation = curation if isinstance(curation, dict) else {}
        status = str(curation.get("status") or "").lower().strip()
        if status not in {"curated", "duplicate", "conflict"}:
            continue
        counts[status] += 1
        counts["terminal"] += 1
        resolved_topic_ids = []

        if status == "curated":
            topic_id = str(curation.get("topic_id") or "").lower().strip()
            if not _SAFE_TOPIC_ID_RE.fullmatch(topic_id):
                add_failure(knowledge_id, "curated_topic_id_invalid")
            elif topic_id not in topics:
                add_failure(knowledge_id, "curated_topic_missing")
            else:
                resolved_topic_ids = [topic_id]
                topic_claim = claims_by_topic[topic_id].get(knowledge_id)
                if not isinstance(topic_claim, dict):
                    add_failure(knowledge_id, "curated_claim_missing")
                else:
                    if str(topic_claim.get("subject") or "") != str(
                        item.get("subject") or ""
                    ):
                        add_failure(
                            knowledge_id, "curated_subject_snapshot_mismatch"
                        )
                    if str(topic_claim.get("claim") or "") != str(
                        item.get("claim") or ""
                    ):
                        add_failure(
                            knowledge_id, "curated_claim_snapshot_mismatch"
                        )
                    topic_curation = topic_claim.get("curation")
                    topic_curation = (
                        topic_curation
                        if isinstance(topic_curation, dict) else {}
                    )
                    subject_entity_id = str(
                        topic_curation.get("subject_entity_id")
                        or curation.get("subject_entity_id")
                        or ""
                    ).lower().strip()
                    entities = topics[topic_id].get("entities")
                    entities = entities if isinstance(entities, dict) else {}
                    if (
                        not _SAFE_TOPIC_ID_RE.fullmatch(subject_entity_id)
                        or subject_entity_id not in entities
                    ):
                        add_failure(
                            knowledge_id, "curated_subject_entity_missing"
                        )

        elif status == "duplicate":
            target_id = str(curation.get("duplicate_of") or "").strip()
            if not target_id or target_id == knowledge_id:
                add_failure(knowledge_id, "duplicate_target_invalid")
            else:
                resolved_topic_ids = sorted(set(claim_topics.get(target_id, [])))
                if not resolved_topic_ids:
                    add_failure(knowledge_id, "duplicate_target_not_in_topic")
                stated_topic = str(
                    curation.get("topic_id") or ""
                ).lower().strip()
                if stated_topic and stated_topic not in resolved_topic_ids:
                    add_failure(knowledge_id, "duplicate_topic_mismatch")

        elif status == "conflict":
            conflict_id = str(curation.get("conflict_id") or "").strip()
            conflict = conflict_rows.get(conflict_id)
            if not isinstance(conflict, dict):
                add_failure(knowledge_id, "conflict_record_missing")
            else:
                if str(conflict.get("knowledge_id") or "") != knowledge_id:
                    add_failure(knowledge_id, "conflict_owner_mismatch")
                if str(conflict.get("subject") or "") != str(
                    item.get("subject") or ""
                ):
                    add_failure(knowledge_id, "conflict_subject_mismatch")
                if str(conflict.get("claim") or "") != str(
                    item.get("claim") or ""
                ):
                    add_failure(knowledge_id, "conflict_claim_mismatch")
                topic_id = str(
                    conflict.get("topic_id") or ""
                ).lower().strip()
                if (
                    not _SAFE_TOPIC_ID_RE.fullmatch(topic_id)
                    or topic_id not in topics
                ):
                    add_failure(knowledge_id, "conflict_topic_missing")
                else:
                    resolved_topic_ids = [topic_id]
                    related_ids = [
                        str(value).strip()
                        for value in conflict.get("related_claim_ids", [])
                        if str(value).strip()
                    ]
                    if not related_ids:
                        add_failure(knowledge_id, "conflict_targets_missing")
                    for target_id in related_ids:
                        if target_id == knowledge_id:
                            add_failure(
                                knowledge_id, "conflict_target_is_self"
                            )
                        elif target_id not in claims_by_topic[topic_id]:
                            add_failure(
                                knowledge_id,
                                "conflict_target_not_in_topic:" + target_id,
                            )
                    stated_topic = str(
                        curation.get("topic_id") or ""
                    ).lower().strip()
                    if stated_topic and stated_topic != topic_id:
                        add_failure(knowledge_id, "conflict_topic_mismatch")

        outcomes.append({
            "knowledge_id": knowledge_id,
            "status": status,
            "resolved_topic_ids": resolved_topic_ids,
        })

    expected_inbox_status = {
        "CURATED": "curated",
        "DUPLICATE": "duplicate",
        "CONFLICT": "conflict",
    }
    for entry in inbox.get("items", []):
        if not isinstance(entry, dict):
            continue
        state = str(entry.get("state") or "").upper().strip()
        if state not in expected_inbox_status:
            continue
        knowledge_id = str(entry.get("knowledge_id") or "").strip()
        item = ledger_by_id.get(knowledge_id)
        if not isinstance(item, dict):
            add_failure(knowledge_id, "terminal_inbox_ledger_missing")
            continue
        curation = item.get("curation")
        curation = curation if isinstance(curation, dict) else {}
        if str(curation.get("status") or "").lower().strip() != (
            expected_inbox_status[state]
        ):
            add_failure(knowledge_id, "terminal_inbox_status_mismatch")
        if state == "CURATED":
            entry_topic = str(entry.get("topic_id") or "").lower().strip()
            curation_topic = str(
                curation.get("topic_id") or ""
            ).lower().strip()
            if entry_topic != curation_topic:
                add_failure(knowledge_id, "terminal_inbox_topic_mismatch")
        elif state == "CONFLICT":
            if str(entry.get("conflict_id") or "") != str(
                curation.get("conflict_id") or ""
            ):
                add_failure(knowledge_id, "terminal_inbox_conflict_mismatch")

    return {
        "contract_version": CURATOR_TERMINAL_OUTCOME_CONTRACT_VERSION,
        "counts": counts,
        "outcomes": outcomes,
        "failures": failures,
        "valid": not failures,
    }


def load_stable_review_runs():
    initialize_topic_store()
    value = _load(_stable_review_runs_file(), _empty_stable_review_runs())
    return value if isinstance(value, dict) else _empty_stable_review_runs()


def _parse_review_time(value):
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


def _stable_review_priority(item):
    """Derive a generic sampling weight from AI-owned lifecycle metadata."""
    metadata = item.get("stable_review")
    metadata = metadata if isinstance(metadata, dict) else {}
    explicit = str(metadata.get("priority") or "").upper()
    if explicit in {"LOW", "MEDIUM", "HIGH"}:
        return explicit
    lifecycle = item.get("lifecycle_audit")
    lifecycle = lifecycle if isinstance(lifecycle, dict) else {}
    basis = str(lifecycle.get("basis") or "").upper()
    if basis == "MAINTAINED_SET_OR_STRUCTURE":
        return "HIGH"
    if basis in {
        "FIXED_HISTORY",
        "DURABLE_EXPLANATION_DEFINITION_OR_MECHANISM",
    }:
        return "LOW"
    return "MEDIUM"


def stable_review_candidates(now=None, min_age_days=30):
    """Return stable facts eligible for a bounded random background check."""
    current = now or datetime.now(timezone.utc)
    if current.tzinfo is None:
        current = current.replace(tzinfo=timezone.utc)
    current = current.astimezone(timezone.utc)
    cutoff = current - timedelta(days=max(1, int(min_age_days)))
    candidates = []
    for item in load_items():
        if not isinstance(item, dict) or not _active_persistable(
            item, now=current
        ):
            continue
        if str(item.get("knowledge_type") or "").lower() != "stable":
            continue
        curation = item.get("curation")
        curation = curation if isinstance(curation, dict) else {}
        if curation.get("status") in {"duplicate", "conflict", "inactive"}:
            continue
        review = item.get("stable_review")
        review = review if isinstance(review, dict) else {}
        last_attempt = _parse_review_time(review.get("last_attempt_at"))
        if last_attempt is not None and last_attempt > cutoff:
            continue
        if last_attempt is None:
            learned = (
                _parse_review_time(item.get("updated_at"))
                or _parse_review_time(item.get("learned_at"))
                or _parse_review_time(item.get("created_at"))
            )
            if learned is not None and learned > cutoff:
                continue
        candidate = dict(item)
        candidate["stable_review_priority"] = _stable_review_priority(item)
        candidates.append(candidate)
    return candidates


def select_stable_review_candidate(now=None, min_age_days=30, rng=None):
    """Randomly sample one eligible fact; Python never judges its subject."""
    candidates = stable_review_candidates(
        now=now,
        min_age_days=min_age_days,
    )
    if not candidates:
        return None
    weights = {
        "LOW": 1,
        "MEDIUM": 3,
        "HIGH": 6,
    }
    randomizer = rng or random.SystemRandom()
    return randomizer.choices(
        candidates,
        weights=[
            weights.get(item.get("stable_review_priority"), 1)
            for item in candidates
        ],
        k=1,
    )[0]


def stable_review_due(local_date=None, now=None):
    """Allow at most one random stable review attempt per local day."""
    date_value = str(
        local_date
        or (now or datetime.now(timezone.utc)).astimezone().date().isoformat()
    )
    state = load_stable_review_runs()
    if str(state.get("last_attempt_date") or "") == date_value:
        return False
    return bool(stable_review_candidates(now=now))


def record_stable_review_run(status, knowledge_id="", details=None, local_date=None):
    """Record the bounded daily attempt without changing a claim."""
    normalized = str(status or "FAILED").upper()
    if normalized not in {
        "SUPPORTED", "CONTRADICTED", "INSUFFICIENT_EVIDENCE",
        "FAILED", "SKIPPED",
    }:
        normalized = "FAILED"
    now = datetime.now(timezone.utc).isoformat()
    date_value = str(
        local_date or datetime.now().astimezone().date().isoformat()
    )
    with _CURATION_LOCK:
        payload = load_stable_review_runs()
        payload["last_attempt_at"] = now
        payload["last_attempt_date"] = date_value
        payload.setdefault("runs", []).append({
            "status": normalized,
            "knowledge_id": str(knowledge_id or "")[:160],
            "recorded_at": now,
            "local_date": date_value,
            "details": details if isinstance(details, dict) else {},
        })
        payload["runs"] = payload["runs"][-730:]
        _save(_stable_review_runs_file(), payload, backup=True)
    return payload


def record_stable_review_result(
    knowledge_id,
    outcome,
    reason="",
    sources=None,
    checked_at=None,
):
    """Record support or quarantine contradiction; never replace claim text."""
    normalized = str(outcome or "FAILED").upper()
    if normalized not in {
        "SUPPORTED", "CONTRADICTED", "INSUFFICIENT_EVIDENCE", "FAILED",
    }:
        normalized = "FAILED"
    now = str(checked_at or datetime.now(timezone.utc).isoformat())
    clean_sources = []
    for source in sources or []:
        if not isinstance(source, dict):
            continue
        clean_sources.append({
            "title": str(source.get("title") or "")[:300],
            "domain": str(source.get("domain") or "")[:200],
            "url": str(source.get("url") or "")[:2000],
            "source_score": source.get("source_score"),
        })
        if len(clean_sources) >= 7:
            break
    with _CURATION_LOCK:
        items = load_items()
        target = None
        for item in items:
            if (
                isinstance(item, dict)
                and str(item.get("id") or "") == str(knowledge_id or "")
            ):
                target = item
                break
        if target is None:
            return None
        if str(target.get("knowledge_type") or "").lower() != "stable":
            return None
        review = target.get("stable_review")
        review = dict(review) if isinstance(review, dict) else {}
        review["priority"] = _stable_review_priority(target)
        review["last_attempt_at"] = now
        review["last_outcome"] = normalized
        review["last_reason"] = str(reason or "")[:500]
        review["last_sources"] = clean_sources
        review["attempt_count"] = int(review.get("attempt_count") or 0) + 1
        if normalized == "SUPPORTED":
            review["last_checked_at"] = now
            review["supported_count"] = int(
                review.get("supported_count") or 0
            ) + 1
        elif normalized == "CONTRADICTED":
            review["contradiction_count"] = int(
                review.get("contradiction_count") or 0
            ) + 1
            history = target.get("revision_history")
            history = list(history) if isinstance(history, list) else []
            history.append(
                _knowledge_revision_snapshot(
                    target,
                    "RANDOM_REVIEW_CONTRADICTION",
                    now,
                )
            )
            target["revision_history"] = history[-20:]
            target["status"] = "disputed"
            target["dispute"] = {
                "reason": "random_stable_review_contradiction",
                "detail": str(reason or "")[:500],
                "recorded_at": now,
                "sources": clean_sources,
                "replacement_applied": False,
            }
        target["stable_review"] = review
        target["updated_at"] = now
        _save_knowledge(items)
        return dict(target)


def load_topic_index():
    initialize_topic_store()
    value = _load(_topic_index_file(), _empty_index())
    return value if isinstance(value, dict) else _empty_index()


def load_category_catalog():
    """Return the derived browse taxonomy without exposing mutable state."""

    index = load_topic_index()
    rows = index.get("category_paths")
    if not isinstance(rows, list):
        return []
    return deepcopy([value for value in rows if isinstance(value, dict)])


def load_knowledge_by_category(
    domain=None,
    category_id=None,
    subcategory_id=None,
    fact_type=None,
    include_inactive=False,
):
    """Browse Knowledge by taxonomy; omitted filters act as wildcards."""

    requested_domain = str(domain or "").lower().strip()
    requested_category = str(category_id or "").lower().strip()
    requested_subcategory = str(subcategory_id or "").lower().strip()
    requested_fact_type = str(fact_type or "").upper().strip()
    if requested_domain and requested_domain not in (
        KNOWLEDGE_CLASSIFICATION_DOMAINS
    ):
        return []
    if requested_category and not _SAFE_TOPIC_ID_RE.fullmatch(
        requested_category
    ):
        return []
    if requested_subcategory and not _SAFE_TOPIC_ID_RE.fullmatch(
        requested_subcategory
    ):
        return []
    if requested_fact_type and requested_fact_type not in KNOWLEDGE_FACT_TYPES:
        return []

    matching_topics = set()
    index = load_topic_index()
    topic_rows = index.get("topics")
    topic_rows = topic_rows if isinstance(topic_rows, dict) else {}
    for topic_id, row in topic_rows.items():
        row = row if isinstance(row, dict) else {}
        classification = normalize_topic_classification(
            row.get("classification")
        )
        if not classification:
            continue
        path = classification["category_path"]
        if requested_domain and classification["domain"] != requested_domain:
            continue
        if requested_category and path[0]["id"] != requested_category:
            continue
        if requested_subcategory and (
            len(path) < 2 or path[1]["id"] != requested_subcategory
        ):
            continue
        matching_topics.add(str(topic_id))

    items = load_items() if include_inactive else load_active_items()
    output = []
    for item in items:
        if not isinstance(item, dict):
            continue
        curation = item.get("curation")
        curation = curation if isinstance(curation, dict) else {}
        if str(curation.get("topic_id") or "") not in matching_topics:
            continue
        if requested_fact_type and str(
            curation.get("fact_type") or ""
        ).upper() != requested_fact_type:
            continue
        output.append(deepcopy(item))
    return output


def record_curator_run(status, details=None, local_date=None):
    """Append an auditable run result without changing Knowledge semantics."""
    normalized = str(status or "FAILED").upper()
    if normalized not in {
        "COMPLETED", "COMPLETED_WITH_ERRORS", "FAILED", "SKIPPED",
    }:
        normalized = "FAILED"
    now = datetime.now(timezone.utc).isoformat()
    with _CURATION_LOCK:
        payload = load_curator_runs()
        payload["last_attempt_at"] = now
        if normalized in {"COMPLETED", "COMPLETED_WITH_ERRORS"}:
            payload["last_successful_date"] = str(local_date or "") or None
        payload.setdefault("runs", []).append({
            "status": normalized,
            "recorded_at": now,
            "local_date": str(local_date or "") or None,
            "details": details if isinstance(details, dict) else {},
        })
        payload["runs"] = payload["runs"][-730:]
        _save(_curator_runs_file(), payload, backup=True)
    return payload


def _topic_documents():
    initialize_topic_store()
    documents = []
    try:
        names = sorted(os.listdir(_topics_dir()))
    except OSError:
        return documents
    for name in names:
        if not name.endswith(".json"):
            continue
        topic_id = name[:-5]
        if not _SAFE_TOPIC_ID_RE.fullmatch(topic_id):
            continue
        value = _load(os.path.join(_topics_dir(), name), None)
        if isinstance(value, dict):
            documents.append(value)
    return documents


def load_curated_items():
    items = []
    seen = set()
    for document in _topic_documents():
        lifecycle = document.get("lifecycle")
        lifecycle = lifecycle if isinstance(lifecycle, dict) else {}
        topic_classification = normalize_topic_classification(
            document.get("classification")
        )
        for item in document.get("claims", []):
            if not isinstance(item, dict):
                continue
            knowledge_id = str(item.get("id") or "")
            if not knowledge_id or knowledge_id in seen:
                continue
            seen.add(knowledge_id)
            value = dict(item)
            value["topic_lifecycle"] = {
                "version": lifecycle.get("version"),
                "state": str(lifecycle.get("state") or "")[:40],
                "target_layer": str(
                    lifecycle.get("target_layer") or ""
                )[:40],
                "completion_score": lifecycle.get("completion_score"),
                "interest_score": lifecycle.get("interest_score"),
                "next_focus": str(lifecycle.get("next_focus") or "")[:500],
                "assessed_at": lifecycle.get("assessed_at"),
                "refresh": (
                    deepcopy(lifecycle.get("refresh"))
                    if isinstance(lifecycle.get("refresh"), dict)
                    else {}
                ),
            }
            value["topic_classification"] = deepcopy(topic_classification)
            items.append(value)
    return items


def load_topic_catalog(include_claims=True, max_topics=80, max_claims=20):
    """Return compact AI-facing topic metadata; no topic choice is inferred."""
    initialize()
    authoritative_active_ids = _authoritative_active_knowledge_ids()
    catalog = []
    for document in _topic_documents()[:max(0, int(max_topics))]:
        topic = document.get("topic")
        topic = topic if isinstance(topic, dict) else {}
        entities = document.get("entities")
        entities = entities if isinstance(entities, dict) else {}
        claim_limit = max(0, int(max_claims))
        active_topic_claims = _topic_active_claims(
            document,
            authoritative_active_ids=authoritative_active_ids,
        )
        classification = normalize_topic_classification(
            document.get("classification")
        )
        if claim_limit:
            active_topic_claims = active_topic_claims[-claim_limit:]
        else:
            active_topic_claims = []
        summary = {
            "topic_id": str(topic.get("id") or "")[:80],
            "title": str(topic.get("title") or "")[:200],
            "aliases": [
                str(value)[:120] for value in topic.get("aliases", [])[:24]
            ],
            "keywords": [
                str(value)[:120] for value in topic.get("keywords", [])[:36]
            ],
            "entities": [
                {
                    "id": str(entity.get("id") or key)[:80],
                    "name": str(entity.get("name") or "")[:200],
                    "type": str(entity.get("type") or "other")[:80],
                    "aliases": [
                        str(value)[:120]
                        for value in entity.get("aliases", [])[:12]
                    ],
                }
                for key, entity in list(entities.items())[:80]
                if isinstance(entity, dict)
            ],
            "relationships": [
                {
                    "id": str(value.get("id") or "")[:120],
                    "source_entity_id": str(
                        value.get("source_entity_id") or ""
                    )[:80],
                    "relation": str(value.get("relation") or "")[:80],
                    "target_entity_id": str(
                        value.get("target_entity_id") or ""
                    )[:80],
                    "supporting_knowledge_ids": [
                        str(knowledge_id)[:160]
                        for knowledge_id in value.get(
                            "active_supporting_knowledge_ids", []
                        )[:12]
                    ],
                    "temporal_status": str(
                        value.get("temporal_status") or "INACTIVE"
                    )[:40],
                    "current_active": value.get("current_active") is True,
                    "historical_active": (
                        value.get("historical_active") is True
                    ),
                    "current_active_supporting_knowledge_ids": [
                        str(knowledge_id)[:160]
                        for knowledge_id in value.get(
                            "current_active_supporting_knowledge_ids", []
                        )[:12]
                    ],
                    "historical_active_supporting_knowledge_ids": [
                        str(knowledge_id)[:160]
                        for knowledge_id in value.get(
                            "historical_active_supporting_knowledge_ids", []
                        )[:12]
                    ],
                }
                for value in _active_topic_relationships(
                    document,
                    authoritative_active_ids=authoritative_active_ids,
                    temporal_view="all",
                )[:80]
            ],
            "classification": deepcopy(classification),
            "lifecycle": {
                "version": (
                    document.get("lifecycle", {}).get("version")
                    if isinstance(document.get("lifecycle"), dict) else None
                ),
                "state": str(
                    document.get("lifecycle", {}).get("state")
                    if isinstance(document.get("lifecycle"), dict) else ""
                )[:40],
                "target_layer": str(
                    document.get("lifecycle", {}).get("target_layer")
                    if isinstance(document.get("lifecycle"), dict) else ""
                )[:40],
                "completion_score": (
                    document.get("lifecycle", {}).get("completion_score")
                    if isinstance(document.get("lifecycle"), dict) else None
                ),
                "interest_score": (
                    document.get("lifecycle", {}).get("interest_score")
                    if isinstance(document.get("lifecycle"), dict) else None
                ),
                "next_focus": str(
                    document.get("lifecycle", {}).get("next_focus")
                    if isinstance(document.get("lifecycle"), dict) else ""
                )[:500],
                "assessment_fingerprint": str(
                    document.get("lifecycle", {}).get("assessment_fingerprint")
                    if isinstance(document.get("lifecycle"), dict) else ""
                )[:64],
                "interest_fingerprint": str(
                    document.get("lifecycle", {}).get("interest_fingerprint")
                    if isinstance(document.get("lifecycle"), dict) else ""
                )[:64],
                "assessed_at": (
                    document.get("lifecycle", {}).get("assessed_at")
                    if isinstance(document.get("lifecycle"), dict) else None
                ),
                "refresh_due_at": (
                    document.get("lifecycle", {}).get("refresh", {}).get("due_at")
                    if isinstance(document.get("lifecycle"), dict)
                    and isinstance(
                        document.get("lifecycle", {}).get("refresh"), dict
                    ) else None
                ),
            },
        }
        if include_claims:
            summary["claims"] = [
                {
                    "id": str(item.get("id") or "")[:120],
                    "subject": str(item.get("subject") or "")[:240],
                    "claim": str(item.get("claim") or "")[:900],
                    "subject_entity_id": str(
                        (item.get("curation") or {}).get("subject_entity_id")
                        if isinstance(item.get("curation"), dict) else ""
                    )[:80],
                    "facet": str(
                        (item.get("curation") or {}).get("facet")
                        if isinstance(item.get("curation"), dict) else ""
                    )[:120],
                    "knowledge_layer": str(
                        (item.get("curation") or {}).get("knowledge_layer")
                        if isinstance(item.get("curation"), dict) else ""
                    )[:40],
                    "fact_type": str(
                        (item.get("curation") or {}).get("fact_type")
                        if isinstance(item.get("curation"), dict) else ""
                    )[:40],
                    "temporal_scope": normalize_temporal_scope(
                        item.get("temporal_scope")
                    ),
                    "evidence": knowledge_evidence.bundle_summary(
                        item.get("evidence_bundle")
                    ),
                }
                for item in active_topic_claims
                if isinstance(item, dict)
            ]
        catalog.append(summary)
    return catalog


def _merge_text_values(existing, additions, limit, value_limit=120):
    output = []
    seen = set()
    for raw in list(existing or []) + list(additions or []):
        value = " ".join(str(raw or "").split())[:value_limit]
        key = value.casefold()
        if value and key not in seen:
            seen.add(key)
            output.append(value)
        if len(output) >= limit:
            break
    return output


def curator_evidence_texts(item):
    """Return only source-carried text that may ground names and aliases."""

    item = item if isinstance(item, dict) else {}
    values = []

    def add(value):
        text = " ".join(str(value or "").split())
        if text and text not in values:
            values.append(text)

    add(item.get("subject"))
    add(item.get("claim"))
    verification = item.get("verification")
    verification = verification if isinstance(verification, dict) else {}
    for key in (
        "accepted_answer",
        "answer",
        "evidence_canonical_answer",
        "canonical_answer",
    ):
        add(verification.get(key))
    for value in verification.get("evidence_answers", []):
        add(value)
    source_context = verification.get("source_context")
    source_context = (
        source_context if isinstance(source_context, dict) else {}
    )
    add(source_context.get("canonical_answer"))
    display_context = item.get("display_context")
    display_context = (
        display_context if isinstance(display_context, dict) else {}
    )
    for key in ("accepted_answer", "evidence_canonical_answer"):
        add(display_context.get(key))
    for value in display_context.get("evidence_answers", []):
        add(value)
    for value in display_context.get("source_titles", []):
        add(value)
    for source in item.get("sources", []):
        if isinstance(source, dict):
            add(source.get("title"))
    evidence_bundle = item.get("evidence_bundle")
    evidence_bundle = (
        evidence_bundle if isinstance(evidence_bundle, dict) else {}
    )
    for record in evidence_bundle.get("records", []):
        if not isinstance(record, dict):
            continue
        add(record.get("excerpt"))
        add(record.get("extracted_answer"))
        add(record.get("visual_observation"))
    return values


def _value_supported_by_evidence(value, evidence_texts):
    """Require an exact source-carried phrase, with Latin token boundaries."""

    needle = " ".join(str(value or "").split()).casefold()
    if not needle:
        return False
    for raw in evidence_texts or []:
        haystack = " ".join(str(raw or "").split()).casefold()
        if not haystack:
            continue
        if re.fullmatch(r"[a-z0-9][a-z0-9 ._+&'/-]*", needle):
            if re.search(
                r"(?<![a-z0-9])" + re.escape(needle) + r"(?![a-z0-9])",
                haystack,
            ):
                return True
        elif needle in haystack:
            return True
    return False


def _grounded_text_values(existing, additions, evidence_items, limit):
    evidence = []
    for item in evidence_items or []:
        evidence.extend(curator_evidence_texts(item))
    return [
        value
        for value in _merge_text_values(existing, additions, limit)
        if _value_supported_by_evidence(value, evidence)
    ]


def _semantic_relationship_id(source_id, relation, target_id):
    material = (
        str(source_id).lower()
        + "\n"
        + str(relation).lower()
        + "\n"
        + str(target_id).lower()
    ).encode("utf-8")
    return "relation_" + hashlib.sha256(material).hexdigest()[:16]


def _relationship_support_ids(
    document,
    source_id,
    target_id,
    relationship,
    relationship_ids=None,
):
    known_claims = {
        str(claim.get("id") or ""): claim
        for claim in document.get("claims", [])
        if isinstance(claim, dict) and claim.get("id")
    }
    values = []
    for value in relationship.get("supporting_knowledge_ids", []):
        knowledge_id = str(value or "")
        if knowledge_id in known_claims and knowledge_id not in values:
            values.append(knowledge_id)
    for evidence in relationship.get("evidence", []):
        if not isinstance(evidence, dict):
            continue
        knowledge_id = str(evidence.get("knowledge_id") or "")
        if knowledge_id in known_claims and knowledge_id not in values:
            values.append(knowledge_id)
    pair = {str(source_id or ""), str(target_id or "")}
    relationship_ids = {
        str(value or "").lower().strip()
        for value in relationship_ids or []
        if _SAFE_TOPIC_ID_RE.fullmatch(
            str(value or "").lower().strip()
        )
    }
    for knowledge_id, claim in known_claims.items():
        curation = claim.get("curation")
        curation = curation if isinstance(curation, dict) else {}
        declared_relationship_ids = {
            str(value or "").lower().strip()
            for value in curation.get("relationship_ids", [])
            if _SAFE_TOPIC_ID_RE.fullmatch(
                str(value or "").lower().strip()
            )
        }
        subject_id = str(curation.get("subject_entity_id") or "")
        related_ids = {
            str(value or "")
            for value in curation.get("related_entity_ids", [])
        }
        explicitly_declared = bool(
            relationship_ids & declared_relationship_ids
        )
        pair_declared = (
            subject_id in pair
            and bool((pair - {subject_id}) & related_ids)
        )
        if explicitly_declared or pair_declared:
            if knowledge_id not in values:
                values.append(knowledge_id)
    return values


def _legacy_grounded_relationship_support(
    document,
    source_id,
    target_id,
    support_ids,
    evidence_text,
    evidence_text_by_knowledge_id=None,
    declared_relationship_ids=None,
    relationship_ids=None,
):
    """Keep legacy edges only when both entities and evidence occur in claim."""

    entities = document.get("entities")
    entities = entities if isinstance(entities, dict) else {}
    source = entities.get(source_id)
    source = source if isinstance(source, dict) else {}
    target = entities.get(target_id)
    target = target if isinstance(target, dict) else {}
    source_names = [source.get("name"), *source.get("aliases", [])]
    target_names = [target.get("name"), *target.get("aliases", [])]
    claims = {
        str(claim.get("id") or ""): claim
        for claim in document.get("claims", [])
        if isinstance(claim, dict) and claim.get("id")
    }
    evidence_text_by_knowledge_id = (
        evidence_text_by_knowledge_id
        if isinstance(evidence_text_by_knowledge_id, dict)
        else {}
    )
    declared_relationship_ids = (
        declared_relationship_ids
        if isinstance(declared_relationship_ids, dict)
        else {}
    )
    relationship_ids = {
        str(value or "").lower().strip()
        for value in relationship_ids or []
        if _SAFE_TOPIC_ID_RE.fullmatch(
            str(value or "").lower().strip()
        )
    }
    grounded = []
    for knowledge_id in support_ids:
        claim = claims.get(knowledge_id)
        claim = claim if isinstance(claim, dict) else {}
        claim_evidence = curator_evidence_texts(claim)
        if not str(claim.get("claim") or "").strip() or not claim_evidence:
            continue
        if not any(
            _value_supported_by_evidence(value, claim_evidence)
            for value in source_names
            if str(value or "").strip()
        ):
            continue
        if not any(
            _value_supported_by_evidence(value, claim_evidence)
            for value in target_names
            if str(value or "").strip()
        ):
            continue
        candidate_evidence = []
        per_claim_evidence = str(
            evidence_text_by_knowledge_id.get(knowledge_id) or ""
        )[:300]
        if per_claim_evidence:
            candidate_evidence.append(per_claim_evidence)
        if evidence_text and evidence_text not in candidate_evidence:
            candidate_evidence.append(evidence_text)
        evidence_grounded = any(
            _value_supported_by_evidence(value, claim_evidence)
            for value in candidate_evidence
        )
        explicitly_declared = bool(
            relationship_ids
            & {
                str(value or "").lower().strip()
                for value in declared_relationship_ids.get(
                    knowledge_id,
                    [],
                )
                if _SAFE_TOPIC_ID_RE.fullmatch(
                    str(value or "").lower().strip()
                )
            }
        )
        if candidate_evidence and not (
            evidence_grounded or explicitly_declared
        ):
            continue
        grounded.append(knowledge_id)
    return grounded


def _legacy_membership_direction(document, source_id, relation, target_id):
    entities = document.get("entities")
    entities = entities if isinstance(entities, dict) else {}
    source = entities.get(source_id)
    target = entities.get(target_id)
    source = source if isinstance(source, dict) else {}
    target = target if isinstance(target, dict) else {}
    source_type = str(source.get("type") or "").casefold()
    target_type = str(target.get("type") or "").casefold()
    group_types = {
        "group", "organization", "team", "unit", "pairing",
        "virtual_idol_group", "umbrella_organization",
    }
    individual_types = {
        "person", "member", "character", "virtual_character",
        "performer", "creator",
    }
    membership = str(relation or "").casefold().startswith((
        "member_of", "former_member_of", "original_member_of",
    ))
    if (
        membership
        and source_type in group_types
        and target_type in individual_types
    ):
        return target_id, source_id
    return source_id, target_id


def _hydrate_topic_claim_relationship_metadata(document):
    """Recover exact curator edge IDs from the authoritative flat ledger.

    V1.10.51.7 could clear a topic claim's relationship IDs before rejecting
    one support against another support's edge-level evidence text.  The flat
    ledger keeps the original curator metadata, so use only an exact claim-ID
    and claim-text match to restore those IDs before rebuilding the edge.
    """

    authoritative = {
        str(item.get("id") or ""): item
        for item in _load(KNOWLEDGE_FILE, [])
        if isinstance(item, dict) and str(item.get("id") or "")
    }
    for claim in document.get("claims", []):
        if not isinstance(claim, dict):
            continue
        knowledge_id = str(claim.get("id") or "")
        ledger_claim = authoritative.get(knowledge_id)
        if not isinstance(ledger_claim, dict):
            continue
        if str(ledger_claim.get("claim") or "") != str(
            claim.get("claim") or ""
        ):
            continue
        topic_curation = claim.get("curation")
        ledger_curation = ledger_claim.get("curation")
        if not isinstance(topic_curation, dict) or not isinstance(
            ledger_curation,
            dict,
        ):
            continue
        for field in ("relationship_ids", "related_entity_ids"):
            merged = []
            topic_values = topic_curation.get(field)
            topic_values = topic_values if isinstance(
                topic_values,
                list,
            ) else []
            ledger_values = ledger_curation.get(field)
            ledger_values = ledger_values if isinstance(
                ledger_values,
                list,
            ) else []
            for value in (
                topic_values + ledger_values
            ):
                normalized = str(value or "").lower().strip()
                if (
                    _SAFE_TOPIC_ID_RE.fullmatch(normalized)
                    and normalized not in merged
                ):
                    merged.append(normalized)
            topic_curation[field] = merged


def _upgrade_topic_relationships(document):
    claims = {
        str(claim.get("id") or ""): claim
        for claim in document.get("claims", [])
        if isinstance(claim, dict) and claim.get("id")
    }
    declared_relationship_ids = {}
    for knowledge_id, claim in claims.items():
        curation = claim.get("curation")
        if isinstance(curation, dict):
            declared_relationship_ids[knowledge_id] = [
                str(value or "").lower().strip()
                for value in curation.get("relationship_ids", [])
                if _SAFE_TOPIC_ID_RE.fullmatch(
                    str(value or "").lower().strip()
                )
            ]
            curation["relationship_ids"] = []
    merged = {}
    quarantined = [
        value for value in document.get("relationship_quarantine", [])
        if isinstance(value, dict)
    ]
    for raw in document.get("relationships", []):
        if not isinstance(raw, dict):
            continue
        original_source = str(raw.get("source_entity_id") or "").lower()
        original_target = str(raw.get("target_entity_id") or "").lower()
        relation = re.sub(
            r"[^a-z0-9_]+",
            "_",
            str(raw.get("relation") or "").lower().replace("-", "_"),
        ).strip("_")[:80]
        if (
            not _SAFE_TOPIC_ID_RE.fullmatch(original_source)
            or not _SAFE_TOPIC_ID_RE.fullmatch(original_target)
            or not _SAFE_RELATION_RE.fullmatch(relation)
        ):
            quarantined.append({
                **raw,
                "quarantine_reason": "invalid_legacy_relationship_shape",
            })
            continue
        source_id, target_id = _legacy_membership_direction(
            document,
            original_source,
            relation,
            original_target,
        )
        relationship_id = _semantic_relationship_id(
            source_id,
            relation,
            target_id,
        )
        relationship_ids = {
            relationship_id,
            str(raw.get("id") or "").lower().strip(),
        }
        evidence_text_by_knowledge_id = {
            str(value.get("knowledge_id") or ""): str(
                value.get("text") or ""
            )[:300]
            for value in raw.get("evidence", [])
            if isinstance(value, dict)
            and str(value.get("knowledge_id") or "")
            and str(value.get("text") or "").strip()
        }
        support_ids = _relationship_support_ids(
            document,
            original_source,
            original_target,
            raw,
            relationship_ids=relationship_ids,
        )
        if not support_ids:
            quarantined.append({
                **raw,
                "quarantine_reason": "missing_verified_claim_support",
            })
            continue
        evidence_text = str(raw.get("claim_relation_evidence") or "")[:300]
        support_ids = _legacy_grounded_relationship_support(
            document,
            original_source,
            original_target,
            support_ids,
            evidence_text,
            evidence_text_by_knowledge_id=(
                evidence_text_by_knowledge_id
            ),
            declared_relationship_ids=declared_relationship_ids,
            relationship_ids=relationship_ids,
        )
        if not support_ids:
            quarantined.append({
                **raw,
                "quarantine_reason": "legacy_relationship_not_grounded_in_claim",
            })
            continue
        row = merged.setdefault(relationship_id, {
            "id": relationship_id,
            "source_entity_id": source_id,
            "relation": relation,
            "target_entity_id": target_id,
            "claim_relation_evidence": "",
            "supporting_knowledge_ids": [],
            "evidence": [],
            "status": "VERIFIED_CLAIM",
            "contract_version": KNOWLEDGE_RELATIONSHIP_CONTRACT_VERSION,
        })
        if evidence_text:
            row["claim_relation_evidence"] = evidence_text
        for knowledge_id in support_ids:
            if knowledge_id not in row["supporting_knowledge_ids"]:
                row["supporting_knowledge_ids"].append(knowledge_id)
            claim = claims.get(knowledge_id, {})
            claim_evidence = curator_evidence_texts(claim)
            per_claim_evidence = str(
                evidence_text_by_knowledge_id.get(knowledge_id) or ""
            )[:300]
            if per_claim_evidence and _value_supported_by_evidence(
                per_claim_evidence,
                claim_evidence,
            ):
                grounded_evidence_text = per_claim_evidence
            elif evidence_text and _value_supported_by_evidence(
                evidence_text,
                claim_evidence,
            ):
                grounded_evidence_text = evidence_text
            else:
                grounded_evidence_text = str(
                    claim.get("claim") or ""
                )[:300]
            evidence = {
                "knowledge_id": knowledge_id,
                "text": grounded_evidence_text,
                "knowledge_type": str(
                    claim.get("knowledge_type") or "stable"
                )[:30],
                "temporal_scope": normalize_temporal_scope(
                    claim.get("temporal_scope")
                ),
            }
            row["evidence"] = [
                value for value in row["evidence"]
                if str(value.get("knowledge_id") or "") != knowledge_id
            ]
            row["evidence"].append(evidence)
            claim = claims.get(knowledge_id)
            curation = (
                claim.get("curation") if isinstance(claim, dict) else None
            )
            if isinstance(curation, dict):
                ids = curation.setdefault("relationship_ids", [])
                if relationship_id not in ids:
                    ids.append(relationship_id)
    for claim in claims.values():
        curation = claim.get("curation")
        if not isinstance(curation, dict) or not curation.get(
            "relationship_ids"
        ):
            continue
        if str(curation.get("knowledge_layer") or "").upper() == (
            "L3_RELATIONSHIPS"
        ):
            continue
        for field in (
            "knowledge_layer",
            "knowledge_layer_version",
            "knowledge_layer_reason",
            "knowledge_layered_at",
        ):
            curation.pop(field, None)
    return list(merged.values()), quarantined[-500:]


def _primary_topic_entity_name(document):
    entities = document.get("entities")
    entities = entities if isinstance(entities, dict) else {}
    counts = {}
    order = []
    for claim in document.get("claims", []):
        if not isinstance(claim, dict):
            continue
        curation = claim.get("curation")
        curation = curation if isinstance(curation, dict) else {}
        entity_id = str(curation.get("subject_entity_id") or "")
        if entity_id not in entities:
            continue
        counts[entity_id] = counts.get(entity_id, 0) + 1
        if entity_id not in order:
            order.append(entity_id)
    if order:
        entity_id = max(order, key=lambda value: counts[value])
        return str(entities[entity_id].get("name") or "")[:200]
    for entity in entities.values():
        if isinstance(entity, dict) and str(entity.get("name") or "").strip():
            return str(entity.get("name"))[:200]
    return ""


def _repair_topic_document_semantics(document):
    contract = document.get("semantic_contract")
    contract = contract if isinstance(contract, dict) else {}
    try:
        contract_version = int(contract.get("version") or 0)
    except (TypeError, ValueError):
        contract_version = 0
    try:
        relationship_contract_version = int(
            contract.get("relationship_contract_version") or 0
        )
    except (TypeError, ValueError):
        relationship_contract_version = 0
    try:
        relationship_support_migration_version = int(
            contract.get("relationship_support_migration_version") or 0
        )
    except (TypeError, ValueError):
        relationship_support_migration_version = 0
    try:
        classification_contract_version = int(
            contract.get("classification_contract_version") or 0
        )
    except (TypeError, ValueError):
        classification_contract_version = 0
    if (
        contract_version >= KNOWLEDGE_SEMANTIC_CONTRACT_VERSION
        and relationship_contract_version
        >= KNOWLEDGE_RELATIONSHIP_CONTRACT_VERSION
        and relationship_support_migration_version
        >= KNOWLEDGE_RELATIONSHIP_SUPPORT_MIGRATION_VERSION
        and classification_contract_version
        >= KNOWLEDGE_CLASSIFICATION_CONTRACT_VERSION
    ):
        return False
    claims = [
        value for value in document.get("claims", [])
        if isinstance(value, dict)
    ]
    topic = document.get("topic")
    topic = topic if isinstance(topic, dict) else {}
    removed = {
        "topic_aliases": [],
        "topic_keywords": [],
        "entity_aliases": {},
        "previous_title": None,
    }
    old_aliases = list(topic.get("aliases", []))
    topic["aliases"] = _grounded_text_values([], old_aliases, claims, 40)
    removed["topic_aliases"] = [
        value for value in old_aliases if value not in topic["aliases"]
    ]
    old_keywords = list(topic.get("keywords", []))
    topic["keywords"] = _grounded_text_values([], old_keywords, claims, 80)
    removed["topic_keywords"] = [
        value for value in old_keywords if value not in topic["keywords"]
    ]
    evidence = []
    for claim in claims:
        evidence.extend(curator_evidence_texts(claim))
    title = str(topic.get("title") or "")[:200]
    if title and not _value_supported_by_evidence(title, evidence):
        fallback = _primary_topic_entity_name(document)
        if fallback:
            removed["previous_title"] = title
            topic["title"] = fallback
    document["topic"] = topic
    entities = document.get("entities")
    entities = entities if isinstance(entities, dict) else {}
    for entity_id, entity in entities.items():
        if not isinstance(entity, dict):
            continue
        old_values = list(entity.get("aliases", []))
        entity["aliases"] = _grounded_text_values([], old_values, claims, 24)
        dropped = [
            value for value in old_values if value not in entity["aliases"]
        ]
        if dropped:
            removed["entity_aliases"][entity_id] = dropped
    _hydrate_topic_claim_relationship_metadata(document)
    relationships, quarantined = _upgrade_topic_relationships(document)
    document["relationships"] = relationships
    if quarantined:
        document["relationship_quarantine"] = quarantined
    document["semantic_contract"] = {
        "version": KNOWLEDGE_SEMANTIC_CONTRACT_VERSION,
        "alias_policy": "VERIFIED_CONTEXT_ONLY",
        "relationship_contract_version": (
            KNOWLEDGE_RELATIONSHIP_CONTRACT_VERSION
        ),
        "relationship_support_migration_version": (
            KNOWLEDGE_RELATIONSHIP_SUPPORT_MIGRATION_VERSION
        ),
        "classification_contract_version": (
            KNOWLEDGE_CLASSIFICATION_CONTRACT_VERSION
        ),
        "category_granularity_version": (
            KNOWLEDGE_CATEGORY_GRANULARITY_VERSION
            if topic_classification_is_current(
                document.get("classification")
            )
            else 0
        ),
        "migrated_at": datetime.now(timezone.utc).isoformat(),
        "repair_audit": removed,
    }
    document["schema_version"] = KNOWLEDGE_TOPIC_SCHEMA_VERSION
    document["updated_at"] = datetime.now(timezone.utc).isoformat()
    return True


def _repair_topic_store_semantics():
    changed = False
    try:
        names = sorted(os.listdir(_topics_dir()))
    except OSError:
        return False
    with _CURATION_LOCK:
        for name in names:
            if not name.endswith(".json"):
                continue
            topic_id = name[:-5]
            if not _SAFE_TOPIC_ID_RE.fullmatch(topic_id):
                continue
            path = os.path.join(_topics_dir(), name)
            document = _load(path, None)
            if not isinstance(document, dict):
                continue
            if _repair_topic_document_semantics(document):
                _save(path, document, backup=True)
                changed = True
    return changed


def _empty_topic_document(assignment):
    now = datetime.now(timezone.utc).isoformat()
    return {
        "schema_version": KNOWLEDGE_TOPIC_SCHEMA_VERSION,
        "topic": {
            "id": str(assignment.get("topic_id") or "").lower(),
            "title": str(assignment.get("topic_title") or "")[:200],
            "aliases": [],
            "keywords": [],
        },
        "entities": {},
        "relationships": [],
        "claims": [],
        "classification": {},
        "classification_history": [],
        "lifecycle": {},
        "semantic_contract": {
            "version": KNOWLEDGE_SEMANTIC_CONTRACT_VERSION,
            "alias_policy": "VERIFIED_CONTEXT_ONLY",
            "relationship_contract_version": (
                KNOWLEDGE_RELATIONSHIP_CONTRACT_VERSION
            ),
            "relationship_support_migration_version": (
                KNOWLEDGE_RELATIONSHIP_SUPPORT_MIGRATION_VERSION
            ),
            "classification_contract_version": (
                KNOWLEDGE_CLASSIFICATION_CONTRACT_VERSION
            ),
            "category_granularity_version": 0,
        },
        "created_at": now,
        "updated_at": now,
    }


def _merge_entity(document, entity, evidence_items=None):
    entity = entity if isinstance(entity, dict) else {}
    entity_id = str(entity.get("id") or "").lower().strip()
    if not _SAFE_TOPIC_ID_RE.fullmatch(entity_id):
        raise ValueError("invalid_entity_id")
    entities = document.setdefault("entities", {})
    old = entities.get(entity_id)
    old = old if isinstance(old, dict) else {}
    incoming_name = str(
        entity.get("name") or old.get("name") or ""
    )[:200]
    preserved_old_names = []
    old_name = str(old.get("name") or "")[:200]
    if old_name and old_name.casefold() != incoming_name.casefold():
        preserved_old_names.append(old_name)
    entities[entity_id] = {
        "id": entity_id,
        "name": incoming_name,
        "type": str(entity.get("type") or old.get("type") or "other")[:80],
        "aliases": _grounded_text_values(
            list(old.get("aliases", [])) + preserved_old_names,
            entity.get("aliases", []),
            evidence_items,
            24,
        ),
    }
    if not entities[entity_id]["name"]:
        raise ValueError("missing_entity_name")
    return entity_id


def _remove_relationship_support(document, knowledge_id):
    kept = []
    for relationship in document.get("relationships", []):
        if not isinstance(relationship, dict):
            continue
        row = dict(relationship)
        row["supporting_knowledge_ids"] = [
            str(value)
            for value in row.get("supporting_knowledge_ids", [])
            if str(value) != str(knowledge_id)
        ]
        row["evidence"] = [
            value
            for value in row.get("evidence", [])
            if isinstance(value, dict)
            and str(value.get("knowledge_id") or "") != str(knowledge_id)
        ]
        if row["supporting_knowledge_ids"]:
            kept.append(row)
    document["relationships"] = kept


def _upsert_relationship(
    document,
    item,
    source_id,
    relation,
    target_id,
    evidence_text,
):
    relation = str(relation or "").lower().strip()
    if not _SAFE_RELATION_RE.fullmatch(relation):
        raise ValueError("invalid_relationship_relation")
    relationship_id = _semantic_relationship_id(
        source_id,
        relation,
        target_id,
    )
    relationships = document.setdefault("relationships", [])
    row = next(
        (
            value for value in relationships
            if isinstance(value, dict) and value.get("id") == relationship_id
        ),
        None,
    )
    if row is None:
        row = {
            "id": relationship_id,
            "source_entity_id": source_id,
            "relation": relation,
            "target_entity_id": target_id,
            "claim_relation_evidence": "",
            "supporting_knowledge_ids": [],
            "evidence": [],
            "status": "VERIFIED_CLAIM",
            "contract_version": KNOWLEDGE_RELATIONSHIP_CONTRACT_VERSION,
        }
        relationships.append(row)
    knowledge_id = str(item.get("id") or "")
    if knowledge_id and knowledge_id not in row["supporting_knowledge_ids"]:
        row["supporting_knowledge_ids"].append(knowledge_id)
    evidence_text = str(evidence_text or item.get("claim") or "")[:300]
    row["claim_relation_evidence"] = evidence_text
    evidence = {
        "knowledge_id": knowledge_id,
        "text": evidence_text,
        "knowledge_type": str(item.get("knowledge_type") or "stable")[:30],
        "temporal_scope": normalize_temporal_scope(
            item.get("temporal_scope")
        ),
    }
    row["evidence"] = [
        value for value in row.get("evidence", [])
        if isinstance(value, dict)
        and str(value.get("knowledge_id") or "") != knowledge_id
    ]
    row["evidence"].append(evidence)
    row["status"] = "VERIFIED_CLAIM"
    row["contract_version"] = KNOWLEDGE_RELATIONSHIP_CONTRACT_VERSION
    return relationship_id


def _merge_assignment_into_topic(document, item, assignment):
    topic = document.setdefault("topic", {})
    topic["id"] = str(assignment.get("topic_id") or "").lower()
    evidence_items = [
        value for value in document.get("claims", [])
        if isinstance(value, dict)
    ] + [item]
    subject_id = _merge_entity(
        document,
        assignment.get("subject_entity"),
        evidence_items,
    )
    proposed_title = str(assignment.get("topic_title") or "")[:200]
    evidence_texts = []
    for evidence_item in evidence_items:
        evidence_texts.extend(curator_evidence_texts(evidence_item))
    if proposed_title and _value_supported_by_evidence(
        proposed_title,
        evidence_texts,
    ):
        topic["title"] = proposed_title
    elif not _value_supported_by_evidence(
        topic.get("title"),
        evidence_texts,
    ):
        topic["title"] = str(
            document["entities"][subject_id].get("name") or proposed_title
        )[:200]
    topic["aliases"] = _grounded_text_values(
        topic.get("aliases", []),
        assignment.get("topic_aliases", []),
        evidence_items,
        40,
    )
    topic["keywords"] = _grounded_text_values(
        topic.get("keywords", []),
        assignment.get("topic_keywords", []),
        evidence_items,
        80,
    )
    related_ids = []
    relationship_ids = []
    _remove_relationship_support(document, item.get("id"))
    for related in assignment.get("related_entities", []):
        if not isinstance(related, dict):
            continue
        related_id = _merge_entity(document, related, evidence_items)
        related_ids.append(related_id)
        direction = str(
            related.get("relation_direction") or "SUBJECT_TO_RELATED"
        ).upper()
        if direction == "RELATED_TO_SUBJECT":
            source_id, target_id = related_id, subject_id
        elif direction == "SUBJECT_TO_RELATED":
            source_id, target_id = subject_id, related_id
        else:
            raise ValueError("invalid_relationship_direction")
        relationship_ids.append(_upsert_relationship(
            document,
            item,
            source_id,
            related.get("relation") or "related_to",
            target_id,
            related.get("claim_relation_evidence"),
        ))
    claim = dict(item)
    claim["curation"] = {
        "status": "curated",
        "topic_id": topic["id"],
        "terminal_outcome_contract_version": (
            CURATOR_TERMINAL_OUTCOME_CONTRACT_VERSION
        ),
        "subject_entity_id": subject_id,
        "literal_claim_subject": str(
            assignment.get("literal_claim_subject") or ""
        )[:300],
        "selected_subject_entity_id": str(
            assignment.get("selected_subject_entity_id") or ""
        )[:80],
        "rejected_adjacent_entity_ids": [
            str(value)[:80]
            for value in assignment.get("rejected_adjacent_entity_ids", [])[:12]
            if str(value).strip()
        ],
        "subject_selection_reason": str(
            assignment.get("subject_selection_reason") or ""
        )[:500],
        "related_entity_ids": related_ids,
        "relationship_ids": relationship_ids,
        "facet": " ".join(str(assignment.get("facet") or "general").split())[:120],
        "keywords": _grounded_text_values(
            [],
            assignment.get("claim_keywords", []),
            [item],
            24,
        ),
        "preferred_display_claim": str(
            assignment.get("preferred_display_claim") or item.get("claim") or ""
        )[:3000],
        "preferred_display_language": str(
            assignment.get("preferred_display_language") or "source"
        )[:40],
        "name_rendering_status": str(
            assignment.get("name_rendering_status") or "SOURCE_PRESERVED"
        )[:40],
        "display_semantics_preserved": (
            assignment.get("display_semantics_preserved") is True
        ),
        "display_version": KNOWLEDGE_DISPLAY_VERSION,
        "curated_at": datetime.now(timezone.utc).isoformat(),
        "reason": str(assignment.get("reason") or "")[:500],
    }
    claims = document.setdefault("claims", [])
    for index, old in enumerate(claims):
        if isinstance(old, dict) and old.get("id") == claim.get("id"):
            claims[index] = claim
            break
    else:
        claims.append(claim)
    document["updated_at"] = datetime.now(timezone.utc).isoformat()
    return claim


def _rebuild_topic_index():
    payload = _empty_index()
    payload["active_claim_index_version"] = (
        KNOWLEDGE_TAXONOMY_ACTIVE_CLAIM_INDEX_VERSION
    )
    payload["category_granularity_version"] = (
        KNOWLEDGE_CATEGORY_GRANULARITY_VERSION
    )
    terms = {}
    category_groups = {}
    fact_type_counts = {value: 0 for value in KNOWLEDGE_FACT_TYPES}
    authoritative_active_ids = _authoritative_active_knowledge_ids()
    for document in _topic_documents():
        topic = document.get("topic")
        topic = topic if isinstance(topic, dict) else {}
        topic_id = str(topic.get("id") or "")
        if not _SAFE_TOPIC_ID_RE.fullmatch(topic_id):
            continue
        entities = document.get("entities")
        entities = entities if isinstance(entities, dict) else {}
        lifecycle = document.get("lifecycle")
        lifecycle = lifecycle if isinstance(lifecycle, dict) else {}
        classification = normalize_topic_classification(
            document.get("classification")
        )
        layer_counts = {layer: 0 for layer in KNOWLEDGE_LAYERS}
        topic_fact_type_counts = {
            value: 0 for value in KNOWLEDGE_FACT_TYPES
        }
        active_claims = _topic_active_claims(
            document,
            authoritative_active_ids=authoritative_active_ids,
        )
        for claim in active_claims:
            curation = claim.get("curation")
            curation = curation if isinstance(curation, dict) else {}
            layer = str(curation.get("knowledge_layer") or "").upper()
            if layer in layer_counts:
                layer_counts[layer] += 1
            fact_type, classification_version = _claim_classification_state(
                claim
            )
            if (
                fact_type in topic_fact_type_counts
                and classification_version >= KNOWLEDGE_CLASSIFICATION_VERSION
            ):
                topic_fact_type_counts[fact_type] += 1
                fact_type_counts[fact_type] += 1
        entry = {
            "path": "topics/" + topic_id + ".json",
            "title": str(topic.get("title") or "")[:200],
            "aliases": [str(value)[:120] for value in topic.get("aliases", [])[:40]],
            "keywords": [str(value)[:120] for value in topic.get("keywords", [])[:80]],
            "entity_ids": [str(value)[:80] for value in list(entities)[:200]],
            "claim_count": len(active_claims),
            "layer_counts": layer_counts,
            "fact_type_counts": topic_fact_type_counts,
            "classification": deepcopy(classification),
            "lifecycle_state": str(lifecycle.get("state") or "")[:40],
            "completion_score": lifecycle.get("completion_score"),
            "interest_score": lifecycle.get("interest_score"),
            "refresh_due_at": (
                lifecycle.get("refresh", {}).get("due_at")
                if isinstance(lifecycle.get("refresh"), dict)
                else None
            ),
        }
        payload["topics"][topic_id] = entry
        if classification:
            path = classification["category_path"]
            path_key = (
                classification["domain"],
                tuple(node["id"] for node in path),
            )
            group = category_groups.setdefault(path_key, {
                "domain": classification["domain"],
                "category_path": deepcopy(path),
                "topic_ids": [],
                "claim_count": 0,
            })
            if topic_id not in group["topic_ids"]:
                group["topic_ids"].append(topic_id)
            group["claim_count"] += entry["claim_count"]
        classification_terms = []
        if classification:
            classification_terms = [classification["domain"]]
            for node in classification["category_path"]:
                classification_terms.extend([node["id"], node["label"]])
        lookup_values = [
            entry["title"], topic_id, *entry["aliases"], *entry["keywords"],
            *classification_terms,
        ]
        for entity in entities.values():
            if not isinstance(entity, dict):
                continue
            lookup_values.extend([
                entity.get("name"), entity.get("id"), *entity.get("aliases", [])
            ])
        for claim in active_claims:
            curation = claim.get("curation")
            if isinstance(curation, dict):
                lookup_values.extend(curation.get("keywords", []))
                lookup_values.append(curation.get("fact_type"))
        for raw in lookup_values:
            term = " ".join(str(raw or "").split()).casefold()[:160]
            if not term:
                continue
            values = terms.setdefault(term, [])
            if topic_id not in values:
                values.append(topic_id)
    payload["terms"] = terms
    payload["category_paths"] = sorted(
        category_groups.values(),
        key=lambda value: (
            value.get("domain", ""),
            tuple(
                node.get("id", "")
                for node in value.get("category_path", [])
                if isinstance(node, dict)
            ),
        ),
    )
    payload["fact_type_counts"] = fact_type_counts
    payload["updated_at"] = datetime.now(timezone.utc).isoformat()
    _save(_topic_index_file(), payload, backup=True)
    return payload


def apply_curator_assignments(assignments):
    """Apply validated AI organization decisions without changing verification."""
    if not isinstance(assignments, list):
        raise ValueError("assignments_must_be_list")
    with _CURATION_LOCK:
        initialize()
        inbox_payload = _load(_curation_inbox_file(), _empty_inbox())
        inbox_entries = inbox_payload.get("items", [])
        pending = {
            str(entry.get("knowledge_id") or ""): entry
            for entry in inbox_entries
            if isinstance(entry, dict) and entry.get("state") == "PENDING"
        }
        items = load_items()
        by_id = {
            str(item.get("id") or ""): item
            for item in items if isinstance(item, dict) and item.get("id")
        }
        conflicts = _load(_conflicts_file(), _empty_conflicts())
        conflict_items = conflicts.get("items", [])
        counts = {
            "curated": 0,
            "duplicate": 0,
            "conflict": 0,
            "deferred": 0,
            "inactive": 0,
            "topic_ids": [],
        }
        touched_topics = {}
        now = datetime.now(timezone.utc).isoformat()

        for assignment in assignments:
            if not isinstance(assignment, dict):
                raise ValueError("invalid_assignment")
            knowledge_id = str(assignment.get("knowledge_id") or "")
            entry = pending.get(knowledge_id)
            item = by_id.get(knowledge_id)
            if entry is None or item is None:
                raise ValueError("assignment_not_pending")
            decision = str(assignment.get("decision") or "DEFER").upper()
            entry["attempt_count"] = int(entry.get("attempt_count") or 0) + 1
            entry["last_attempt_at"] = now
            entry["last_reason"] = str(assignment.get("reason") or "")[:500]
            if not _active_persistable(item):
                entry["state"] = "INACTIVE"
                item["curation"] = {"status": "inactive", "curated_at": now}
                counts["inactive"] += 1
                continue
            if decision == "DEFER":
                counts["deferred"] += 1
                continue
            if decision == "STORE":
                topic_id = str(assignment.get("topic_id") or "").lower()
                path = _topic_path(topic_id)
                document = touched_topics.get(topic_id)
                if document is None:
                    document = _load(path, None)
                    if not isinstance(document, dict):
                        document = _empty_topic_document(assignment)
                    touched_topics[topic_id] = document
                curated_claim = _merge_assignment_into_topic(
                    document, item, assignment
                )
                item["curation"] = dict(curated_claim["curation"])
                entry["state"] = "CURATED"
                entry["topic_id"] = topic_id
                entry["completed_at"] = now
                counts["curated"] += 1
                if topic_id not in counts["topic_ids"]:
                    counts["topic_ids"].append(topic_id)
                continue
            related_claim_ids = [
                str(value)[:120]
                for value in assignment.get("related_claim_ids", [])[:12]
                if str(value).strip()
            ]
            if decision == "DUPLICATE":
                if not related_claim_ids:
                    raise ValueError("duplicate_without_target")
                item["curation"] = {
                    "status": "duplicate",
                    "duplicate_of": related_claim_ids[0],
                    "related_claim_ids": related_claim_ids,
                    "topic_id": str(
                        assignment.get("topic_id") or ""
                    ).lower()[:80],
                    "terminal_outcome_contract_version": (
                        CURATOR_TERMINAL_OUTCOME_CONTRACT_VERSION
                    ),
                    "curated_at": now,
                    "reason": str(assignment.get("reason") or "")[:500],
                }
                entry["state"] = "DUPLICATE"
                entry["related_claim_ids"] = related_claim_ids
                entry["completed_at"] = now
                counts["duplicate"] += 1
                continue
            if decision == "CONFLICT":
                if not related_claim_ids:
                    raise ValueError("conflict_without_target")
                conflict_id = "conflict_" + hashlib.sha256(
                    (knowledge_id + "\n" + "\n".join(related_claim_ids)).encode("utf-8")
                ).hexdigest()[:20]
                conflict_record = {
                    "id": conflict_id,
                    "status": "OPEN",
                    "knowledge_id": knowledge_id,
                    "related_claim_ids": related_claim_ids,
                    "topic_id": str(assignment.get("topic_id") or "")[:80],
                    "subject": str(item.get("subject") or "")[:300],
                    "claim": str(item.get("claim") or "")[:3000],
                    "reason": str(assignment.get("reason") or "")[:500],
                    "detected_at": now,
                }
                for index, old in enumerate(conflict_items):
                    if isinstance(old, dict) and old.get("id") == conflict_id:
                        conflict_items[index] = conflict_record
                        break
                else:
                    conflict_items.append(conflict_record)
                item["curation"] = {
                    "status": "conflict",
                    "conflict_id": conflict_id,
                    "related_claim_ids": related_claim_ids,
                    "topic_id": conflict_record["topic_id"],
                    "terminal_outcome_contract_version": (
                        CURATOR_TERMINAL_OUTCOME_CONTRACT_VERSION
                    ),
                    "curated_at": now,
                    "reason": conflict_record["reason"],
                }
                entry["state"] = "CONFLICT"
                entry["conflict_id"] = conflict_id
                entry["completed_at"] = now
                counts["conflict"] += 1
                continue
            raise ValueError("unsupported_curator_decision")

        for topic_id, document in touched_topics.items():
            _save(_topic_path(topic_id), document, backup=True)
        conflicts["items"] = conflict_items[-5000:]
        conflicts["revision"] = int(conflicts.get("revision") or 0) + 1
        _save(_conflicts_file(), conflicts, backup=True)
        inbox_payload["items"] = inbox_entries
        inbox_payload["revision"] = int(inbox_payload.get("revision") or 0) + 1
        _save(_curation_inbox_file(), inbox_payload, backup=True)
        _save_knowledge(items, sync_curation=False)
        _rebuild_topic_index()
        return counts


def load_topic_document(topic_id):
    """Return one topic document without exposing a mutable store reference."""

    initialize()
    value = _load(_topic_path(topic_id), None)
    return deepcopy(value) if isinstance(value, dict) else None


def _topic_active_claims(
    document,
    now=None,
    authoritative_active_ids=None,
):
    current = now or datetime.now(timezone.utc)
    return [
        claim
        for claim in document.get("claims", [])
        if isinstance(claim, dict)
        and _active_persistable(claim, now=current)
        and (
            authoritative_active_ids is None
            or str(claim.get("id") or "") in authoritative_active_ids
        )
    ]


def _authoritative_active_knowledge_ids(now=None):
    """Read active claim IDs from the flat ledger without recursive initialize."""

    current = now or datetime.now(timezone.utc)
    return {
        str(item.get("id") or "")
        for item in _load(KNOWLEDGE_FILE, [])
        if isinstance(item, dict)
        and str(item.get("id") or "")
        and _active_persistable(item, now=current)
        and str(
            (
                item.get("curation")
                if isinstance(item.get("curation"), dict)
                else {}
            ).get("status") or ""
        ).lower() not in {"duplicate", "conflict"}
    }


def _active_topic_relationships(
    document,
    now=None,
    active_only=True,
    authoritative_active_ids=None,
    temporal_view="all",
):
    temporal_view = _normalize_relationship_temporal_view(temporal_view)
    active_ids = {
        str(claim.get("id") or "")
        for claim in _topic_active_claims(
            document,
            now=now,
            authoritative_active_ids=authoritative_active_ids,
        )
        if str(claim.get("id") or "")
    }
    claims = {
        str(claim.get("id") or ""): claim
        for claim in document.get("claims", [])
        if isinstance(claim, dict) and str(claim.get("id") or "")
    }
    entities = document.get("entities")
    entities = entities if isinstance(entities, dict) else {}
    rows = []
    for relationship in document.get("relationships", []):
        if not isinstance(relationship, dict):
            continue
        support_ids = [
            str(value)
            for value in relationship.get("supporting_knowledge_ids", [])
            if str(value)
        ]
        evidence_by_id = {
            str(evidence.get("knowledge_id") or ""): evidence
            for evidence in relationship.get("evidence", [])
            if isinstance(evidence, dict)
            and str(evidence.get("knowledge_id") or "")
        }

        def historical_support(knowledge_id):
            claim = claims.get(knowledge_id)
            claim = claim if isinstance(claim, dict) else {}
            evidence = evidence_by_id.get(knowledge_id)
            evidence = evidence if isinstance(evidence, dict) else {}
            scope = normalize_temporal_scope(claim.get("temporal_scope"))
            if not scope:
                scope = normalize_temporal_scope(
                    evidence.get("temporal_scope")
                )
            return scope.get("closed_period") is True

        historical_support_ids = [
            value for value in support_ids if historical_support(value)
        ]
        historical_support_set = set(historical_support_ids)
        current_support_ids = [
            value for value in support_ids
            if value not in historical_support_set
        ]
        all_active_support = [
            value for value in support_ids if value in active_ids
        ]
        current_active_support = [
            value for value in current_support_ids if value in active_ids
        ]
        historical_active_support = [
            value for value in historical_support_ids if value in active_ids
        ]
        if temporal_view == "current":
            view_support_ids = current_support_ids
            active_support = current_active_support
        elif temporal_view == "historical":
            view_support_ids = historical_support_ids
            active_support = historical_active_support
        else:
            view_support_ids = support_ids
            active_support = all_active_support
        if active_only and not active_support:
            continue
        source_id = str(relationship.get("source_entity_id") or "")
        target_id = str(relationship.get("target_entity_id") or "")
        source = entities.get(source_id)
        source = source if isinstance(source, dict) else {}
        target = entities.get(target_id)
        target = target if isinstance(target, dict) else {}
        value = deepcopy(relationship)
        value["temporal_view"] = temporal_view
        value["temporal_status"] = _relationship_temporal_status(
            current_active_support,
            historical_active_support,
        )
        value["current_supporting_knowledge_ids"] = current_support_ids
        value["historical_supporting_knowledge_ids"] = (
            historical_support_ids
        )
        value["all_active_supporting_knowledge_ids"] = all_active_support
        value["current_active_supporting_knowledge_ids"] = (
            current_active_support
        )
        value["historical_active_supporting_knowledge_ids"] = (
            historical_active_support
        )
        value["active_supporting_knowledge_ids"] = active_support
        value["active"] = bool(active_support)
        value["current_active"] = bool(current_active_support)
        value["historical_active"] = bool(historical_active_support)
        value["source_entity_name"] = str(source.get("name") or "")[:200]
        value["target_entity_name"] = str(target.get("name") or "")[:200]
        visible_support_ids = set(
            active_support if active_only else view_support_ids
        )
        value["evidence"] = [
            deepcopy(evidence)
            for evidence in relationship.get("evidence", [])
            if isinstance(evidence, dict)
            and str(evidence.get("knowledge_id") or "")
            in visible_support_ids
        ]
        rows.append(value)
    return rows


def _normalize_relationship_temporal_view(value):
    view = str(value or "current").lower().strip()
    if view not in _RELATIONSHIP_TEMPORAL_VIEWS:
        raise ValueError("invalid_relationship_temporal_view")
    return view


def _relationship_temporal_status(current_support, historical_support):
    if current_support and historical_support:
        return "CURRENT_AND_HISTORICAL"
    if current_support:
        return "CURRENT_ONLY"
    if historical_support:
        return "HISTORICAL_ONLY"
    return "INACTIVE"


def load_topic_relationships(
    topic_id=None,
    active_only=True,
    temporal_view="current",
):
    """Return provenance-bound edges through a current or historical view.

    The safe default is ``current``: a closed historical snapshot cannot keep
    a present-state relation visible after every current support expires.
    Callers answering an explicit past-period question must request
    ``historical`` (or ``all`` and retain each evidence temporal_scope).
    """

    initialize()
    temporal_view = _normalize_relationship_temporal_view(temporal_view)
    requested = str(topic_id or "").lower().strip()
    if requested and not _SAFE_TOPIC_ID_RE.fullmatch(requested):
        raise ValueError("invalid_topic_id")
    authoritative_active_ids = _authoritative_active_knowledge_ids()
    output = []
    for document in _topic_documents():
        topic = document.get("topic")
        topic = topic if isinstance(topic, dict) else {}
        current_id = str(topic.get("id") or "").lower().strip()
        if requested and current_id != requested:
            continue
        for relationship in _active_topic_relationships(
            document,
            active_only=bool(active_only),
            authoritative_active_ids=authoritative_active_ids,
            temporal_view=temporal_view,
        ):
            value = deepcopy(relationship)
            value["topic_id"] = current_id
            output.append(value)
    return output


def _claim_layer_state(claim):
    curation = claim.get("curation")
    curation = curation if isinstance(curation, dict) else {}
    layer = str(curation.get("knowledge_layer") or "").upper()
    try:
        version = int(curation.get("knowledge_layer_version") or 0)
    except (TypeError, ValueError):
        version = 0
    return layer, version


def _topic_assessment_fingerprint(
    document,
    now=None,
    authoritative_active_ids=None,
):
    """Hash only evidence inputs; AI-owned layers do not invalidate themselves."""

    topic = document.get("topic")
    topic = topic if isinstance(topic, dict) else {}
    claims = []
    for claim in _topic_active_claims(
        document,
        now=now,
        authoritative_active_ids=authoritative_active_ids,
    ):
        curation = claim.get("curation")
        curation = curation if isinstance(curation, dict) else {}
        claims.append({
            "id": str(claim.get("id") or "")[:160],
            "subject": str(claim.get("subject") or "")[:300],
            "claim": str(claim.get("claim") or "")[:3000],
            "facet": str(curation.get("facet") or "")[:120],
            "relationship_ids": [
                str(value)[:120]
                for value in curation.get("relationship_ids", [])[:24]
            ],
            "knowledge_type": str(
                claim.get("knowledge_type") or "stable"
            )[:30],
            "expires_at": claim.get("expires_at"),
            "temporal_scope": normalize_temporal_scope(
                claim.get("temporal_scope")
            ),
        })
    material = {
        "topic_id": str(topic.get("id") or "")[:80],
        "title": str(topic.get("title") or "")[:200],
        "claims": sorted(claims, key=lambda item: item["id"]),
        "layer_version": KNOWLEDGE_LAYER_VERSION,
        "lifecycle_version": TOPIC_LIFECYCLE_VERSION,
    }
    return hashlib.sha256(
        json.dumps(
            material,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    ).hexdigest()


def load_topic_lifecycle_assessment_candidates(
    limit=6,
    preferred_topic_ids=None,
    force_topic_ids=None,
    include_topic_ids=None,
):
    """Return bounded topic evidence that still needs AI lifecycle judgment."""

    initialize()
    authoritative_active_ids = _authoritative_active_knowledge_ids()
    preferred = [
        str(value or "").lower().strip()
        for value in preferred_topic_ids or []
        if _SAFE_TOPIC_ID_RE.fullmatch(str(value or "").lower().strip())
    ]
    preferred_order = {value: index for index, value in enumerate(preferred)}
    forced = {
        str(value or "").lower().strip()
        for value in force_topic_ids or []
        if _SAFE_TOPIC_ID_RE.fullmatch(str(value or "").lower().strip())
    }
    included = {
        str(value or "").lower().strip()
        for value in include_topic_ids or []
        if _SAFE_TOPIC_ID_RE.fullmatch(str(value or "").lower().strip())
    }
    candidates = []
    for document in _topic_documents():
        topic = document.get("topic")
        topic = topic if isinstance(topic, dict) else {}
        topic_id = str(topic.get("id") or "").lower().strip()
        if not _SAFE_TOPIC_ID_RE.fullmatch(topic_id):
            continue
        if included and topic_id not in included:
            continue
        active_claims = _topic_active_claims(
            document,
            authoritative_active_ids=authoritative_active_ids,
        )
        if not active_claims:
            continue
        lifecycle = document.get("lifecycle")
        lifecycle = lifecycle if isinstance(lifecycle, dict) else {}
        existing_classification = normalize_topic_classification(
            document.get("classification")
        )
        classification_refinement_required = not (
            topic_classification_is_current(existing_classification)
        )
        fingerprint = _topic_assessment_fingerprint(
            document,
            authoritative_active_ids=authoritative_active_ids,
        )
        pending_layer_ids = []
        pending_classification_ids = []
        compact_claims = []
        layer_counts = {layer: 0 for layer in KNOWLEDGE_LAYERS}
        for claim in active_claims:
            curation = claim.get("curation")
            curation = curation if isinstance(curation, dict) else {}
            layer, layer_version = _claim_layer_state(claim)
            if layer not in KNOWLEDGE_LAYERS or layer_version < KNOWLEDGE_LAYER_VERSION:
                pending_layer_ids.append(str(claim.get("id") or ""))
                layer = "UNLAYERED"
            else:
                layer_counts[layer] += 1
            fact_type, classification_version = _claim_classification_state(
                claim
            )
            if (
                fact_type not in KNOWLEDGE_FACT_TYPES
                or classification_version < KNOWLEDGE_CLASSIFICATION_VERSION
            ):
                pending_classification_ids.append(
                    str(claim.get("id") or "")
                )
                fact_type = "UNCLASSIFIED"
            if len(compact_claims) < TOPIC_LIFECYCLE_CONTEXT_CLAIMS:
                compact_claims.append({
                    "knowledge_id": str(claim.get("id") or "")[:160],
                    "subject": str(claim.get("subject") or "")[:300],
                    "claim": str(claim.get("claim") or "")[:500],
                    "facet": str(curation.get("facet") or "")[:120],
                    "relationship_ids": [
                        str(value)[:120]
                        for value in curation.get("relationship_ids", [])[:24]
                    ],
                    "has_relationships": bool(
                        curation.get("relationship_ids")
                    ),
                    "knowledge_layer": layer,
                    "fact_type": fact_type,
                    "knowledge_type": str(
                        claim.get("knowledge_type") or "stable"
                    )[:30],
                    "expires_at": claim.get("expires_at"),
                    "temporal_scope": normalize_temporal_scope(
                        claim.get("temporal_scope")
                    ),
                })
        forced_assessment = topic_id in forced
        lifecycle_current = (
            int(lifecycle.get("version") or 0) >= TOPIC_LIFECYCLE_VERSION
            and str(lifecycle.get("assessment_fingerprint") or "")
            == fingerprint
        )
        classification_only_refinement = bool(
            classification_refinement_required
            and not forced_assessment
            and not pending_layer_ids
            and not pending_classification_ids
            and lifecycle_current
        )
        needs_assessment = (
            forced_assessment
            or pending_layer_ids
            or pending_classification_ids
            or classification_refinement_required
            or int(lifecycle.get("version") or 0) < TOPIC_LIFECYCLE_VERSION
            or str(lifecycle.get("assessment_fingerprint") or "") != fingerprint
        )
        if not needs_assessment:
            continue
        candidates.append({
            "topic_id": topic_id,
            "title": str(topic.get("title") or "")[:200],
            "aliases": [
                str(value)[:120] for value in topic.get("aliases", [])[:24]
            ],
            "keywords": [
                str(value)[:120] for value in topic.get("keywords", [])[:36]
            ],
            "claims": compact_claims,
            "claim_count": len(active_claims),
            "context_complete": len(active_claims) <= len(compact_claims),
            "layer_counts": layer_counts,
            "pending_layer_claim_ids": pending_layer_ids[:8],
            "pending_layer_total": len(pending_layer_ids),
            "pending_classification_claim_ids": (
                pending_classification_ids[:8]
            ),
            "pending_classification_total": len(
                pending_classification_ids
            ),
            "existing_classification": deepcopy(existing_classification),
            "classification_refinement_required": (
                classification_refinement_required
            ),
            "classification_only_refinement": (
                classification_only_refinement
            ),
            "assessment_fingerprint": fingerprint,
            "existing_lifecycle": deepcopy(lifecycle),
            "updated_at": str(document.get("updated_at") or ""),
        })
    candidates.sort(key=lambda value: (
        0 if value["topic_id"] in preferred_order else 1,
        preferred_order.get(value["topic_id"], 999999),
        value.get("updated_at", ""),
        value["topic_id"],
    ))
    return candidates[:max(0, int(limit))]


def apply_topic_lifecycle_assessment(
    assessment,
    allow_reclassification=False,
):
    """Apply a validated AI layer/completion plan without changing any claim."""

    if not isinstance(assessment, dict):
        raise ValueError("topic_lifecycle_assessment_invalid")
    topic_id = str(assessment.get("topic_id") or "").lower().strip()
    if not _SAFE_TOPIC_ID_RE.fullmatch(topic_id):
        raise ValueError("topic_lifecycle_topic_id_invalid")
    with _CURATION_LOCK:
        document = _load(_topic_path(topic_id), None)
        if not isinstance(document, dict):
            raise ValueError("topic_lifecycle_topic_missing")
        authoritative_active_ids = _authoritative_active_knowledge_ids()
        try:
            assessment_contract_version = int(
                assessment.get("assessment_contract_version") or 0
            )
        except (TypeError, ValueError):
            assessment_contract_version = 0
        if assessment_contract_version != (
            TOPIC_LIFECYCLE_ASSESSMENT_CONTRACT_VERSION
        ):
            raise ValueError(
                "topic_lifecycle_assessment_contract_version_mismatch"
            )
        expected_fingerprint = _topic_assessment_fingerprint(
            document,
            authoritative_active_ids=authoritative_active_ids,
        )
        submitted_fingerprint = str(
            assessment.get("assessment_fingerprint") or ""
        ).lower().strip()
        if submitted_fingerprint != expected_fingerprint:
            raise ValueError("topic_lifecycle_assessment_snapshot_stale")
        active_claims = _topic_active_claims(
            document,
            authoritative_active_ids=authoritative_active_ids,
        )
        active_by_id = {
            str(claim.get("id") or ""): claim
            for claim in active_claims if str(claim.get("id") or "")
        }
        pending_ids = [
            knowledge_id
            for knowledge_id, claim in active_by_id.items()
            if _claim_layer_state(claim)[0] not in KNOWLEDGE_LAYERS
            or _claim_layer_state(claim)[1] < KNOWLEDGE_LAYER_VERSION
        ]
        expected_layer_ids = pending_ids[:8]
        layer_plans = assessment.get("claim_layers")
        if not isinstance(layer_plans, list):
            raise ValueError("topic_lifecycle_claim_layers_invalid")
        returned_layer_ids = [
            str(value.get("knowledge_id") or "")
            for value in layer_plans if isinstance(value, dict)
        ]
        if (
            len(returned_layer_ids) != len(set(returned_layer_ids))
            or set(returned_layer_ids) != set(expected_layer_ids)
        ):
            raise ValueError("topic_lifecycle_claim_layer_ids_mismatch")
        layered_at = datetime.now(timezone.utc).isoformat()
        layer_by_id = {}
        for plan in layer_plans:
            knowledge_id = str(plan.get("knowledge_id") or "")
            layer = str(plan.get("knowledge_layer") or "").upper()
            if layer not in KNOWLEDGE_LAYERS:
                raise ValueError("topic_lifecycle_layer_invalid")
            claim = active_by_id[knowledge_id]
            curation = claim.get("curation")
            curation = dict(curation) if isinstance(curation, dict) else {}
            if (
                curation.get("relationship_ids")
                and layer != "L3_RELATIONSHIPS"
            ):
                raise ValueError(
                    "topic_lifecycle_relationship_claim_not_l3"
                )
            curation["knowledge_layer"] = layer
            curation["knowledge_layer_version"] = KNOWLEDGE_LAYER_VERSION
            curation["knowledge_layer_reason"] = str(
                plan.get("reason") or ""
            )[:500]
            curation["knowledge_layered_at"] = layered_at
            claim["curation"] = curation
            layer_by_id[knowledge_id] = layer

        pending_classification_ids = [
            knowledge_id
            for knowledge_id, claim in active_by_id.items()
            if _claim_classification_state(claim)[0]
            not in KNOWLEDGE_FACT_TYPES
            or _claim_classification_state(claim)[1]
            < KNOWLEDGE_CLASSIFICATION_VERSION
        ]
        expected_classification_ids = pending_classification_ids[:8]
        classification_plans = assessment.get("claim_classifications")
        if not isinstance(classification_plans, list):
            raise ValueError(
                "topic_lifecycle_claim_classifications_invalid"
            )
        returned_classification_ids = [
            str(value.get("knowledge_id") or "")
            for value in classification_plans if isinstance(value, dict)
        ]
        if (
            len(returned_classification_ids)
            != len(set(returned_classification_ids))
            or set(returned_classification_ids)
            != set(expected_classification_ids)
        ):
            raise ValueError(
                "topic_lifecycle_claim_classification_ids_mismatch"
            )
        classified_at = datetime.now(timezone.utc).isoformat()
        classification_by_id = {}
        for plan in classification_plans:
            knowledge_id = str(plan.get("knowledge_id") or "")
            fact_type = str(plan.get("fact_type") or "").upper()
            if fact_type not in KNOWLEDGE_FACT_TYPES:
                raise ValueError("topic_lifecycle_fact_type_invalid")
            claim = active_by_id[knowledge_id]
            curation = claim.get("curation")
            curation = dict(curation) if isinstance(curation, dict) else {}
            if curation.get("relationship_ids") and fact_type != "RELATIONSHIP":
                raise ValueError(
                    "topic_lifecycle_relationship_fact_type_invalid"
                )
            curation["fact_type"] = fact_type
            curation["classification_version"] = (
                KNOWLEDGE_CLASSIFICATION_VERSION
            )
            curation["classification_reason"] = str(
                plan.get("reason") or ""
            )[:500]
            curation["classified_at"] = classified_at
            claim["curation"] = curation
            classification_by_id[knowledge_id] = fact_type

        topic_classification = normalize_topic_classification(
            assessment.get("topic_classification")
        )
        if (
            not topic_classification
            or not topic_classification_is_current(topic_classification)
            or not str(
                topic_classification.get("reason") or ""
            ).strip()
        ):
            raise ValueError("topic_classification_invalid")
        old_classification = normalize_topic_classification(
            document.get("classification")
        )
        category_refined = bool(
            not topic_classification_is_current(old_classification)
            and topic_classification_is_current(topic_classification)
        )
        old_identity = _classification_identity(old_classification)
        new_identity = _classification_identity(topic_classification)
        if old_classification and not allow_reclassification:
            if topic_classification_is_current(old_classification):
                if old_identity != new_identity:
                    raise ValueError("topic_classification_locked")
            elif not topic_classification_preserves_prefix(
                old_classification,
                topic_classification,
            ):
                raise ValueError(
                    "topic_classification_refinement_prefix_changed"
                )
        catalog_errors = category_catalog_conflicts(
            topic_classification,
            category_catalog=load_category_catalog(),
        )
        if catalog_errors:
            raise ValueError("topic_classification_" + catalog_errors[0])
        if (
            old_classification
            and topic_classification_is_current(old_classification)
            and old_identity == new_identity
            and not allow_reclassification
        ):
            topic_classification = deepcopy(old_classification)
        if (
            old_classification
            and old_identity != new_identity
        ):
            history = document.get("classification_history")
            history = list(history) if isinstance(history, list) else []
            history.append({
                **old_classification,
                "superseded_at": classified_at,
            })
            document["classification_history"] = history[-12:]
        topic_classification["classified_at"] = (
            old_classification.get("classified_at")
            if old_classification
            and old_identity == new_identity
            and old_classification.get("classified_at")
            else classified_at
        )
        document["classification"] = topic_classification

        remaining_unlayered = [
            knowledge_id
            for knowledge_id, claim in active_by_id.items()
            if _claim_layer_state(claim)[0] not in KNOWLEDGE_LAYERS
            or _claim_layer_state(claim)[1] < KNOWLEDGE_LAYER_VERSION
        ]
        remaining_unclassified = [
            knowledge_id
            for knowledge_id, claim in active_by_id.items()
            if _claim_classification_state(claim)[0]
            not in KNOWLEDGE_FACT_TYPES
            or _claim_classification_state(claim)[1]
            < KNOWLEDGE_CLASSIFICATION_VERSION
        ]
        coverage = assessment.get("coverage")
        coverage_layers = [
            str(value.get("layer") or "").upper()
            for value in coverage or [] if isinstance(value, dict)
        ]
        if (
            not isinstance(coverage, list)
            or len(coverage) != len(KNOWLEDGE_LAYERS)
            or set(coverage_layers) != set(KNOWLEDGE_LAYERS)
            or any(
                str(value.get("status") or "").upper()
                not in TOPIC_COVERAGE_STATES
                or not isinstance(value.get("required_for_current_goal"), bool)
                or any(
                    str(claim_id or "") not in active_by_id
                    for claim_id in value.get("evidence_claim_ids", [])
                )
                for value in coverage
                if isinstance(value, dict)
            )
        ):
            raise ValueError("topic_lifecycle_coverage_invalid")
        state = str(assessment.get("state") or "").upper()
        if state not in TOPIC_LIFECYCLE_STATES:
            raise ValueError("topic_lifecycle_state_invalid")
        context_complete = (
            len(active_claims) <= TOPIC_LIFECYCLE_CONTEXT_CLAIMS
        )
        layering_complete = not remaining_unlayered
        structurally_complete = layering_complete and context_complete
        target_layer = str(assessment.get("target_layer") or "").upper()
        if target_layer not in KNOWLEDGE_LAYERS:
            raise ValueError("topic_lifecycle_target_layer_invalid")
        required_gaps = [
            value
            for value in coverage
            if value.get("required_for_current_goal") is True
            and str(value.get("status") or "").upper() in {"MISSING", "PARTIAL"}
        ]
        if state == "PAUSED_COMPLETE" and not structurally_complete:
            raise ValueError("topic_lifecycle_pause_before_layering_complete")
        if state == "PAUSED_COMPLETE" and (
            required_gaps
            or float(assessment.get("completion_score") or 0) < 0.75
            or not str(assessment.get("pause_reason") or "").strip()
            or str(assessment.get("next_focus") or "").strip()
        ):
            raise ValueError("topic_lifecycle_pause_contract_invalid")
        if state == "ACTIVE" and (
            not str(assessment.get("next_focus") or "").strip()
            or (not required_gaps and structurally_complete)
        ):
            raise ValueError("topic_lifecycle_active_contract_invalid")
        refresh_after_days = assessment.get("refresh_after_days")
        if state == "PAUSED_COMPLETE":
            if (
                not isinstance(refresh_after_days, int)
                or isinstance(refresh_after_days, bool)
                or not TOPIC_REFRESH_MIN_DAYS
                <= refresh_after_days
                <= TOPIC_REFRESH_MAX_DAYS
            ):
                raise ValueError("topic_lifecycle_refresh_interval_invalid")
        elif refresh_after_days is not None:
            raise ValueError("active_topic_cannot_schedule_refresh")

        now = datetime.now(timezone.utc)
        fingerprint = _topic_assessment_fingerprint(
            document,
            now=now,
            authoritative_active_ids=authoritative_active_ids,
        )
        old_lifecycle = document.get("lifecycle")
        old_lifecycle = (
            old_lifecycle if isinstance(old_lifecycle, dict) else {}
        )
        old_refresh = old_lifecycle.get("refresh")
        old_refresh = old_refresh if isinstance(old_refresh, dict) else {}
        same_evidence = (
            str(old_lifecycle.get("assessment_fingerprint") or "")
            == fingerprint
        )
        preserve_lifecycle = (
            assessment.get("_classification_only_refinement") is True
            and category_refined
        )
        if preserve_lifecycle:
            if (
                int(old_lifecycle.get("version") or 0)
                < TOPIC_LIFECYCLE_VERSION
                or not same_evidence
                or layer_by_id
                or classification_by_id
                or not structurally_complete
            ):
                raise ValueError(
                    "classification_only_lifecycle_preservation_invalid"
                )
            lifecycle = deepcopy(old_lifecycle)
            state = str(lifecycle.get("state") or "").upper()
            if state not in TOPIC_LIFECYCLE_STATES:
                raise ValueError(
                    "classification_only_lifecycle_state_invalid"
                )
        else:
            if state == "PAUSED_COMPLETE":
                due_at = old_refresh.get("due_at") if same_evidence else None
                if not _parse_review_time(due_at):
                    due_at = (
                        now + timedelta(days=refresh_after_days)
                    ).isoformat()
            else:
                due_at = None
            refresh = {
                "after_days": refresh_after_days,
                "due_at": due_at,
                "last_attempt_at": (
                    old_refresh.get("last_attempt_at")
                    if same_evidence else None
                ),
                "last_attempt_status": (
                    old_refresh.get("last_attempt_status")
                    if same_evidence else None
                ),
                "last_curiosity_id": (
                    old_refresh.get("last_curiosity_id")
                    if same_evidence else None
                ),
                "next_attempt_at": (
                    old_refresh.get("next_attempt_at")
                    if same_evidence else None
                ),
            }
            lifecycle = {
                "version": TOPIC_LIFECYCLE_VERSION,
                "assessment_contract_version": (
                    TOPIC_LIFECYCLE_ASSESSMENT_CONTRACT_VERSION
                ),
                "state": state,
                "target_layer": target_layer,
                "completion_score": max(
                    0.0,
                    min(
                        1.0,
                        float(assessment.get("completion_score") or 0),
                    ),
                ),
                "confidence": max(
                    0.0,
                    min(1.0, float(assessment.get("confidence") or 0)),
                ),
                "coverage": deepcopy(coverage),
                "next_focus": str(
                    assessment.get("next_focus") or ""
                )[:500],
                "pause_reason": str(
                    assessment.get("pause_reason") or ""
                )[:500],
                "interest_score": max(
                    0.0,
                    min(
                        1.0,
                        float(assessment.get("interest_score") or 0),
                    ),
                ),
                "interest_basis": str(
                    assessment.get("interest_basis") or ""
                )[:500],
                "assessment_fingerprint": (
                    fingerprint if layering_complete else None
                ),
                "interest_fingerprint": str(
                    assessment.get("_interest_fingerprint") or ""
                )[:64],
                "assessed_at": now.isoformat(),
                "reason": str(assessment.get("reason") or "")[:800],
                "refresh": refresh,
            }
        document["schema_version"] = KNOWLEDGE_TOPIC_SCHEMA_VERSION
        semantic_contract = document.get("semantic_contract")
        semantic_contract = (
            dict(semantic_contract)
            if isinstance(semantic_contract, dict) else {}
        )
        semantic_contract["classification_contract_version"] = (
            KNOWLEDGE_CLASSIFICATION_CONTRACT_VERSION
        )
        semantic_contract["category_granularity_version"] = (
            KNOWLEDGE_CATEGORY_GRANULARITY_VERSION
        )
        semantic_contract["topic_lifecycle_assessment_contract_version"] = (
            TOPIC_LIFECYCLE_ASSESSMENT_CONTRACT_VERSION
        )
        document["semantic_contract"] = semantic_contract
        document["lifecycle"] = lifecycle
        document["updated_at"] = now.isoformat()
        _save(_topic_path(topic_id), document, backup=True)

        raw_items = load_items()
        raw_by_id = {
            str(item.get("id") or ""): item
            for item in raw_items if isinstance(item, dict)
        }
        raw_changed = False
        for knowledge_id, layer in layer_by_id.items():
            raw = raw_by_id.get(knowledge_id)
            if raw is None:
                continue
            curation = raw.get("curation")
            curation = dict(curation) if isinstance(curation, dict) else {}
            curation["knowledge_layer"] = layer
            curation["knowledge_layer_version"] = KNOWLEDGE_LAYER_VERSION
            curation["knowledge_layer_reason"] = str(
                next(
                    value.get("reason")
                    for value in layer_plans
                    if value.get("knowledge_id") == knowledge_id
                ) or ""
            )[:500]
            curation["knowledge_layered_at"] = layered_at
            raw["curation"] = curation
            raw_changed = True
        for knowledge_id, fact_type in classification_by_id.items():
            raw = raw_by_id.get(knowledge_id)
            if raw is None:
                continue
            curation = raw.get("curation")
            curation = dict(curation) if isinstance(curation, dict) else {}
            curation["fact_type"] = fact_type
            curation["classification_version"] = (
                KNOWLEDGE_CLASSIFICATION_VERSION
            )
            curation["classification_reason"] = str(
                next(
                    value.get("reason")
                    for value in classification_plans
                    if value.get("knowledge_id") == knowledge_id
                ) or ""
            )[:500]
            curation["classified_at"] = classified_at
            raw["curation"] = curation
            raw_changed = True
        if raw_changed:
            _save_knowledge(raw_items, sync_curation=False)
        _rebuild_topic_index()
        return {
            "topic_id": topic_id,
            "assessment_contract_version": (
                TOPIC_LIFECYCLE_ASSESSMENT_CONTRACT_VERSION
            ),
            "assessment_fingerprint": lifecycle.get(
                "assessment_fingerprint"
            ),
            "state": state,
            "completion_score": lifecycle["completion_score"],
            "interest_score": lifecycle["interest_score"],
            "next_focus": lifecycle["next_focus"],
            "layered": len(layer_by_id),
            "remaining_unlayered": len(remaining_unlayered),
            "classified": len(classification_by_id),
            "remaining_unclassified": len(remaining_unclassified),
            "classification": deepcopy(topic_classification),
            "category_refined": category_refined,
            "assessment_complete": structurally_complete,
            "classification_only_refinement": preserve_lifecycle,
        }


def audit_topic_lifecycle_payloads(ledger, topic_documents, now=None):
    """Read-only generic audit of stored Topic lifecycle terminal states."""

    ledger = ledger if isinstance(ledger, list) else []
    if isinstance(topic_documents, dict):
        supplied_topics = list(topic_documents.items())
    elif isinstance(topic_documents, list):
        supplied_topics = [("", value) for value in topic_documents]
    else:
        supplied_topics = []
    current = now or datetime.now(timezone.utc)
    if current.tzinfo is None:
        current = current.replace(tzinfo=timezone.utc)
    current = current.astimezone(timezone.utc)
    ledger_by_id = {
        str(value.get("id") or ""): value
        for value in ledger
        if isinstance(value, dict) and str(value.get("id") or "")
    }
    authoritative_active_ids = {
        knowledge_id
        for knowledge_id, item in ledger_by_id.items()
        if _active_persistable(item, now=current)
        and str(
            (
                item.get("curation")
                if isinstance(item.get("curation"), dict) else {}
            ).get("status") or ""
        ).lower() not in {"duplicate", "conflict"}
    }
    counts = {
        "topics": 0,
        "active": 0,
        "paused_complete": 0,
        "active_claims": 0,
        "contract_current": 0,
        "legacy_compatible": 0,
    }
    outcomes = []
    failures = []

    def add_failure(topic_id, code):
        value = str(topic_id or "unknown") + ":" + str(code)
        if value not in failures:
            failures.append(value)

    def safe_int(value, default=0):
        try:
            return int(value or 0)
        except (TypeError, ValueError):
            return default

    for supplied_id, document in supplied_topics:
        if not isinstance(document, dict):
            add_failure(supplied_id, "topic_document_invalid")
            continue
        topic = document.get("topic")
        topic = topic if isinstance(topic, dict) else {}
        topic_id = str(topic.get("id") or supplied_id or "").lower().strip()
        if not _SAFE_TOPIC_ID_RE.fullmatch(topic_id):
            add_failure(topic_id, "topic_id_invalid")
            continue
        counts["topics"] += 1
        active_claims = _topic_active_claims(
            document,
            now=current,
            authoritative_active_ids=authoritative_active_ids,
        )
        active_ids = {
            str(value.get("id") or "")
            for value in active_claims
            if str(value.get("id") or "")
        }
        counts["active_claims"] += len(active_ids)
        lifecycle = document.get("lifecycle")
        lifecycle = lifecycle if isinstance(lifecycle, dict) else {}
        state = str(lifecycle.get("state") or "").upper().strip()
        if state == "ACTIVE":
            counts["active"] += 1
        elif state == "PAUSED_COMPLETE":
            counts["paused_complete"] += 1
        elif active_ids:
            add_failure(topic_id, "lifecycle_state_invalid")

        lifecycle_version = safe_int(lifecycle.get("version"))
        if active_ids and lifecycle_version < TOPIC_LIFECYCLE_VERSION:
            add_failure(topic_id, "lifecycle_version_stale")
        contract_version = safe_int(
            lifecycle.get("assessment_contract_version"),
            default=-1,
        )
        if contract_version == TOPIC_LIFECYCLE_ASSESSMENT_CONTRACT_VERSION:
            counts["contract_current"] += 1
            semantic_contract = document.get("semantic_contract")
            semantic_contract = (
                semantic_contract
                if isinstance(semantic_contract, dict) else {}
            )
            if safe_int(semantic_contract.get(
                "topic_lifecycle_assessment_contract_version"
            )) != TOPIC_LIFECYCLE_ASSESSMENT_CONTRACT_VERSION:
                add_failure(topic_id, "semantic_contract_version_mismatch")
        elif contract_version == 0:
            counts["legacy_compatible"] += 1
        else:
            add_failure(topic_id, "assessment_contract_version_unknown")

        classification = normalize_topic_classification(
            document.get("classification")
        )
        if active_ids and not topic_classification_is_current(classification):
            add_failure(topic_id, "topic_classification_stale")

        all_layered = True
        all_classified = True
        for claim in active_claims:
            knowledge_id = str(claim.get("id") or "")
            ledger_claim = ledger_by_id.get(knowledge_id)
            if not isinstance(ledger_claim, dict):
                add_failure(topic_id, "active_claim_missing_from_ledger:" + knowledge_id)
                continue
            if str(claim.get("subject") or "") != str(
                ledger_claim.get("subject") or ""
            ):
                add_failure(topic_id, "claim_subject_mismatch:" + knowledge_id)
            if str(claim.get("claim") or "") != str(
                ledger_claim.get("claim") or ""
            ):
                add_failure(topic_id, "claim_text_mismatch:" + knowledge_id)
            layer, layer_version = _claim_layer_state(claim)
            fact_type, fact_version = _claim_classification_state(claim)
            if layer not in KNOWLEDGE_LAYERS or layer_version < KNOWLEDGE_LAYER_VERSION:
                all_layered = False
                add_failure(topic_id, "claim_layer_invalid:" + knowledge_id)
            if (
                fact_type not in KNOWLEDGE_FACT_TYPES
                or fact_version < KNOWLEDGE_CLASSIFICATION_VERSION
            ):
                all_classified = False
                add_failure(topic_id, "claim_fact_type_invalid:" + knowledge_id)
            curation = claim.get("curation")
            curation = curation if isinstance(curation, dict) else {}
            if curation.get("relationship_ids"):
                if layer != "L3_RELATIONSHIPS":
                    add_failure(topic_id, "relationship_layer_invalid:" + knowledge_id)
                if fact_type != "RELATIONSHIP":
                    add_failure(topic_id, "relationship_fact_type_invalid:" + knowledge_id)
            ledger_curation = ledger_claim.get("curation")
            ledger_curation = (
                ledger_curation if isinstance(ledger_curation, dict) else {}
            )
            for field in (
                "knowledge_layer", "knowledge_layer_version",
                "fact_type", "classification_version",
            ):
                if curation.get(field) != ledger_curation.get(field):
                    add_failure(
                        topic_id,
                        "ledger_curation_mismatch:" + knowledge_id + ":" + field,
                    )

        fingerprint_matches = False
        if active_ids and all_layered:
            expected_fingerprint = _topic_assessment_fingerprint(
                document,
                now=current,
                authoritative_active_ids=authoritative_active_ids,
            )
            fingerprint_matches = str(
                lifecycle.get("assessment_fingerprint") or ""
            ) == expected_fingerprint
            if not fingerprint_matches:
                add_failure(topic_id, "assessment_fingerprint_mismatch")

        coverage = lifecycle.get("coverage")
        coverage = coverage if isinstance(coverage, list) else []
        coverage_layers = [
            str(value.get("layer") or "").upper()
            for value in coverage
            if isinstance(value, dict)
        ]
        if active_ids and (
            len(coverage_layers) != len(KNOWLEDGE_LAYERS)
            or set(coverage_layers) != set(KNOWLEDGE_LAYERS)
        ):
            add_failure(topic_id, "coverage_layers_invalid")
        required_gaps = []
        for value in coverage:
            if not isinstance(value, dict):
                add_failure(topic_id, "coverage_row_invalid")
                continue
            status = str(value.get("status") or "").upper()
            required = value.get("required_for_current_goal")
            evidence_ids = {
                str(claim_id or "")
                for claim_id in value.get("evidence_claim_ids", [])
                if str(claim_id or "")
            }
            if status not in TOPIC_COVERAGE_STATES:
                add_failure(topic_id, "coverage_status_invalid")
            if not isinstance(required, bool):
                add_failure(topic_id, "coverage_required_flag_invalid")
            if not evidence_ids.issubset(active_ids):
                add_failure(topic_id, "coverage_evidence_unknown")
            if required is True and status in {"MISSING", "PARTIAL"}:
                required_gaps.append(str(value.get("layer") or ""))

        try:
            completion = float(lifecycle.get("completion_score"))
        except (TypeError, ValueError):
            completion = -1.0
        if active_ids and not 0 <= completion <= 1:
            add_failure(topic_id, "completion_score_invalid")
        refresh = lifecycle.get("refresh")
        refresh = refresh if isinstance(refresh, dict) else {}
        if state == "PAUSED_COMPLETE" and active_ids:
            if not all_layered or not all_classified:
                add_failure(topic_id, "paused_topic_not_structurally_complete")
            if completion < 0.75 or required_gaps:
                add_failure(topic_id, "paused_topic_coverage_invalid")
            if str(lifecycle.get("next_focus") or "").strip():
                add_failure(topic_id, "paused_topic_has_next_focus")
            if not str(lifecycle.get("pause_reason") or "").strip():
                add_failure(topic_id, "paused_topic_reason_missing")
            try:
                after_days = int(refresh.get("after_days"))
            except (TypeError, ValueError):
                after_days = 0
            if (
                after_days < TOPIC_REFRESH_MIN_DAYS
                or after_days > TOPIC_REFRESH_MAX_DAYS
                or _parse_review_time(refresh.get("due_at")) is None
            ):
                add_failure(topic_id, "paused_topic_refresh_invalid")
        elif state == "ACTIVE" and active_ids:
            if not str(lifecycle.get("next_focus") or "").strip():
                add_failure(topic_id, "active_topic_next_focus_missing")
            if not required_gaps and all_layered and all_classified:
                add_failure(topic_id, "active_topic_required_gap_missing")
            if refresh.get("after_days") is not None or refresh.get("due_at") is not None:
                add_failure(topic_id, "active_topic_refresh_present")

        outcomes.append({
            "topic_id": topic_id,
            "state": state,
            "active_claim_count": len(active_ids),
            "assessment_contract_version": contract_version,
            "assessment_fingerprint_matches": fingerprint_matches,
        })

    return {
        "contract_version": TOPIC_LIFECYCLE_ASSESSMENT_CONTRACT_VERSION,
        "counts": counts,
        "outcomes": outcomes,
        "failures": failures,
        "valid": not failures,
    }


def topic_links_for_knowledge_ids(knowledge_ids=None):
    """Return exact topic/layer links for Curiosity journal reconciliation."""

    selected = {
        str(value or "") for value in knowledge_ids or [] if str(value or "")
    }
    authoritative_active_ids = _authoritative_active_knowledge_ids()
    links = []
    for item in load_curated_items():
        if not isinstance(item, dict):
            continue
        knowledge_id = str(item.get("id") or "")
        if knowledge_id not in authoritative_active_ids:
            continue
        if selected and knowledge_id not in selected:
            continue
        curation = item.get("curation")
        curation = curation if isinstance(curation, dict) else {}
        topic_id = str(curation.get("topic_id") or "").lower().strip()
        if not _SAFE_TOPIC_ID_RE.fullmatch(topic_id):
            continue
        links.append({
            "knowledge_id": knowledge_id,
            "topic_id": topic_id,
            "knowledge_layer": str(
                curation.get("knowledge_layer") or ""
            ).upper(),
            "fact_type": str(curation.get("fact_type") or "").upper(),
        })
    return links


def load_topic_curiosity_seed(topic_id):
    """Return bounded, claim-preserving context for one lifecycle-owned seed."""

    document = load_topic_document(topic_id)
    if not isinstance(document, dict):
        return None
    topic = document.get("topic")
    topic = topic if isinstance(topic, dict) else {}
    lifecycle = document.get("lifecycle")
    lifecycle = lifecycle if isinstance(lifecycle, dict) else {}
    authoritative_active_ids = _authoritative_active_knowledge_ids()
    claims = []
    for claim in reversed(_topic_active_claims(
        document,
        authoritative_active_ids=authoritative_active_ids,
    )):
        value = dict(claim)
        value["topic_lifecycle"] = deepcopy(lifecycle)
        claims.append(value)
        if len(claims) >= 10:
            break
    if not claims:
        return None
    return {
        "topic_id": str(topic.get("id") or "")[:80],
        "title": str(topic.get("title") or "")[:200],
        "aliases": [str(value)[:120] for value in topic.get("aliases", [])[:20]],
        "keywords": [str(value)[:120] for value in topic.get("keywords", [])[:30]],
        "classification": normalize_topic_classification(
            document.get("classification")
        ),
        "lifecycle": deepcopy(lifecycle),
        "knowledge_candidates": claims,
        "source_knowledge_id": str(claims[0].get("id") or "")[:160],
    }


def load_topic_refresh_candidates(now=None, exclude_topic_ids=None, limit=6):
    """Rank only due paused topics, primarily by AI-owned interest score."""

    current = now or datetime.now(timezone.utc)
    if current.tzinfo is None:
        current = current.replace(tzinfo=timezone.utc)
    current = current.astimezone(timezone.utc)
    initialize()
    authoritative_active_ids = _authoritative_active_knowledge_ids(now=current)
    excluded = {
        str(value or "").lower().strip() for value in exclude_topic_ids or []
    }
    candidates = []
    for document in _topic_documents():
        topic = document.get("topic")
        topic = topic if isinstance(topic, dict) else {}
        topic_id = str(topic.get("id") or "").lower().strip()
        lifecycle = document.get("lifecycle")
        lifecycle = lifecycle if isinstance(lifecycle, dict) else {}
        if (
            topic_id in excluded
            or lifecycle.get("state") != "PAUSED_COMPLETE"
            or int(lifecycle.get("version") or 0) < TOPIC_LIFECYCLE_VERSION
        ):
            continue
        refresh = lifecycle.get("refresh")
        refresh = refresh if isinstance(refresh, dict) else {}
        next_attempt = _parse_review_time(refresh.get("next_attempt_at"))
        if next_attempt is not None and next_attempt > current:
            continue
        refresh_reason = ""
        due_value = _parse_review_time(refresh.get("due_at"))
        due_at = due_value
        active_claims = _topic_active_claims(
            document,
            now=current,
            authoritative_active_ids=authoritative_active_ids,
        )
        reviewable_due = []
        for claim in active_claims:
            if str(claim.get("knowledge_type") or "").lower() != "reviewable":
                continue
            expiry = _parse_review_time(claim.get("expires_at"))
            if expiry is not None and expiry <= current + timedelta(days=7):
                reviewable_due.append(expiry)
        if reviewable_due:
            refresh_reason = "REVIEW_DUE"
            due_at = min(reviewable_due)
        elif (
            str(lifecycle.get("assessment_fingerprint") or "")
            == _topic_assessment_fingerprint(
                document,
                now=current,
                authoritative_active_ids=authoritative_active_ids,
            )
            and due_value is not None
            and due_value <= current
        ):
            refresh_reason = "AUTO_INTEREST_REFRESH"
        if not refresh_reason:
            continue
        seed = load_topic_curiosity_seed(topic_id)
        if not isinstance(seed, dict):
            continue
        seed["wake_reason"] = refresh_reason
        seed["due_at"] = due_at.isoformat() if due_at is not None else None
        candidates.append(seed)
    candidates.sort(key=lambda value: (
        -float((value.get("lifecycle") or {}).get("interest_score") or 0),
        str(value.get("due_at") or ""),
        str(value.get("topic_id") or ""),
    ))
    return candidates[:max(0, int(limit))]


def record_topic_seed_attempt(topic_id, status, curiosity_id="", now=None):
    """Throttle a gap/refresh seed without treating it as learned evidence."""

    normalized = str(status or "FAILED").upper()
    if normalized not in {"DRAFTED", "NO_QUESTION", "FAILED"}:
        normalized = "FAILED"
    current = now or datetime.now(timezone.utc)
    if current.tzinfo is None:
        current = current.replace(tzinfo=timezone.utc)
    current = current.astimezone(timezone.utc)
    with _CURATION_LOCK:
        document = _load(_topic_path(topic_id), None)
        if not isinstance(document, dict):
            return None
        lifecycle = document.get("lifecycle")
        if not isinstance(lifecycle, dict):
            return None
        refresh = lifecycle.get("refresh")
        refresh = dict(refresh) if isinstance(refresh, dict) else {}
        refresh["last_attempt_at"] = current.isoformat()
        refresh["last_attempt_status"] = normalized
        refresh["last_curiosity_id"] = str(curiosity_id or "")[:120] or None
        retry_days = 30 if normalized == "DRAFTED" else 7
        refresh["next_attempt_at"] = (
            current + timedelta(days=retry_days)
        ).isoformat()
        lifecycle["refresh"] = refresh
        document["lifecycle"] = lifecycle
        document["updated_at"] = current.isoformat()
        _save(_topic_path(topic_id), document, backup=True)
        _rebuild_topic_index()
        return deepcopy(refresh)


def record_topic_refresh_attempt(topic_id, status, curiosity_id="", now=None):
    """Backward-compatible name for the topic seed throttle."""

    return record_topic_seed_attempt(topic_id, status, curiosity_id, now)


def load_sources(approved_only=True):
    initialize()
    sources = _load(SOURCES_FILE, DEFAULT_SOURCES)
    if approved_only:
        return [item for item in sources if item.get("status") == "approved"]
    return sources


def load_source_candidates():
    initialize()
    return _load(PENDING_SOURCES_FILE, [])


def _merge_source_topics(*groups, limit=12):
    merged = []
    seen = set()
    for group in groups:
        for raw in group or []:
            value = " ".join(str(raw or "").split())[:120]
            identity = value.casefold()
            if not value or identity in seen:
                continue
            seen.add(identity)
            merged.append(value)
            if len(merged) >= limit:
                return merged
    return merged


def apply_source_judgment(candidate, judgment):
    """Persist a validated AI source decision; Python does not infer trust."""

    decision = str(judgment.get("decision", "PENDING_REVIEW")).upper()
    if decision not in {"APPROVE", "PENDING_REVIEW", "REJECT"}:
        decision = "PENDING_REVIEW"

    trust_class = str(judgment.get("source_class", "unverified"))[:60]
    try:
        trust_score = max(0.0, min(1.0, float(judgment.get("trust_score", 0))))
    except (TypeError, ValueError):
        trust_score = 0.0

    reviewed_at = datetime.now(timezone.utc).isoformat()
    candidates = load_source_candidates()
    for item in candidates:
        if item.get("url") == candidate.get("url"):
            item["status"] = decision.lower()
            item["source_class"] = trust_class
            item["trust_score"] = trust_score
            item["judgment_reason"] = str(judgment.get("reason", ""))[:500]
            item["reviewed_at"] = reviewed_at
            item["policy_version"] = SOURCE_POLICY_VERSION
            item["last_attempt_at"] = reviewed_at
            item["last_attempt_status"] = "REVIEWED"
            item["last_error"] = None
            item["retry_after"] = None
    _save(PENDING_SOURCES_FILE, candidates)

    if decision == "APPROVE":
        sources = load_sources(approved_only=False)
        existing = next(
            (
                item for item in sources
                if item.get("url") == candidate.get("url")
            ),
            None,
        )
        if existing is None:
            sources.append(
                {
                    "name": candidate.get("name", candidate.get("domain", "")),
                    "url": candidate.get("url", ""),
                    "domain": candidate.get("domain", ""),
                    "topics": candidate.get("topics", []),
                    "trust": trust_class,
                    "trust_score": trust_score,
                    "status": "approved",
                    "approved_by": "source_judge_ai",
                    "approved_at": reviewed_at,
                }
            )
        else:
            existing["topics"] = _merge_source_topics(
                existing.get("topics", []),
                candidate.get("topics", []),
            )
            existing["trust"] = trust_class
            existing["trust_score"] = trust_score
            existing["status"] = "approved"
            existing.setdefault("approved_by", "source_judge_ai")
            existing.setdefault("approved_at", reviewed_at)
        _save(SOURCES_FILE, sources)
    else:
        # A newer AI judgment may revoke an earlier autonomous approval.
        sources = load_sources(approved_only=False)
        filtered = [
            item for item in sources
            if not (
                item.get("url") == candidate.get("url")
                and item.get("approved_by") == "source_judge_ai"
            )
        ]
        if len(filtered) != len(sources):
            _save(SOURCES_FILE, filtered)
    return decision


def record_source_candidate_failure(candidate, error, retry_after_hours=24):
    """Persist bounded source health metadata without making a trust judgment."""

    url = str((candidate or {}).get("url") or "").strip()
    if not url:
        return False
    try:
        retry_hours = max(1, min(168, int(retry_after_hours)))
    except (TypeError, ValueError):
        retry_hours = 24
    current = datetime.now(timezone.utc)
    candidates = load_source_candidates()
    changed = False
    for item in candidates:
        if item.get("url") != url:
            continue
        try:
            attempts = max(0, int(item.get("attempt_count") or 0))
        except (TypeError, ValueError):
            attempts = 0
        item["attempt_count"] = attempts + 1
        item["last_attempt_at"] = current.isoformat()
        item["last_attempt_status"] = "READ_ERROR"
        item["last_error"] = str(error or "Source could not be read.")[:500]
        item["retry_after"] = (
            current + timedelta(hours=retry_hours)
        ).isoformat()
        changed = True
        break
    if changed:
        _save(PENDING_SOURCES_FILE, candidates)
    return changed


def make_id(subject, claim, temporal_scope=None):
    material_text = subject.strip().lower() + "\n" + claim.strip().lower()
    temporal_suffix = _temporal_identity_suffix(temporal_scope)
    if temporal_suffix:
        material_text += "\n" + temporal_suffix
    material = material_text.encode()
    return "knowledge_" + hashlib.sha256(material).hexdigest()[:16]


def apply_knowledge_judgment(candidate, source, judgment):
    """Execute an AI knowledge decision within structural safety limits."""

    evidence_seed = (
        candidate.get("_evidence_seed")
        if isinstance(candidate.get("_evidence_seed"), dict)
        else {}
    )
    required_evidence_fingerprint = knowledge_evidence.seed_fingerprint(
        evidence_seed
    )
    action = str(judgment.get("action", "PENDING_REVIEW")).upper()
    if action not in {
        "AUTO_SAVE", "LOG_ONLY", "PENDING_REVIEW", "REJECT", "DUPLICATE", "UPDATE"
    }:
        action = "PENDING_REVIEW"

    judge_output_status = str(
        judgment.get("_judge_output_status") or "LEGACY_UNSPECIFIED"
    ).upper()[:60]
    judge_contract_version = judgment.get("_judge_contract_version")
    try:
        judge_contract_version = max(0, int(judge_contract_version or 0))
    except (TypeError, ValueError):
        judge_contract_version = 0
    # A transport/format failure is never allowed to inherit a semantic action
    # from malformed model text. It may be retained for later review, but it
    # cannot verify, update, reject, or deduplicate Knowledge.
    if judge_output_status == "INVALID_JSON":
        action = "PENDING_REVIEW"
    if required_evidence_fingerprint and str(
        judgment.get("evidence_fingerprint") or ""
    ) != required_evidence_fingerprint:
        action = "PENDING_REVIEW"

    if action in {"REJECT", "DUPLICATE"}:
        return action.lower(), None

    knowledge_type = str(judgment.get("knowledge_type", "stable")).lower()
    if knowledge_type not in {
        "stable", "reviewable", "changing", "event", "news"
    }:
        knowledge_type = "stable"

    if (
        judge_output_status == "INVALID_JSON"
        and knowledge_type in {"changing", "event", "news"}
    ):
        # A format failure cannot make a semantic LOG_ONLY decision. Keep the
        # candidate visible in the run diagnostics without persisting it as a
        # verified transient outcome.
        return "pending_review", {
            "subject": str(candidate.get("subject", "")).strip()[:300],
            "claim": str(candidate.get("claim", "")).strip()[:3000],
            "knowledge_type": knowledge_type,
            "source_url": source.get("url", ""),
            "reason": str(judgment.get("reason", ""))[:500],
        }

    # One-off state never enters reusable Knowledge. ``changing`` remains a
    # legacy model-output alias for transient state and therefore also logs
    # only; maintained sets must explicitly use the reviewable contract.
    if knowledge_type in {"changing", "event", "news"} or action == "LOG_ONLY":
        return "log_only", {
            "subject": str(candidate.get("subject", "")).strip()[:300],
            "claim": str(candidate.get("claim", "")).strip()[:3000],
            "knowledge_type": knowledge_type,
            "source_url": source.get("url", ""),
            "reason": str(judgment.get("reason", ""))[:500],
        }

    try:
        confidence = max(0.0, min(1.0, float(judgment.get("confidence", 0))))
    except (TypeError, ValueError):
        confidence = 0.0
    risk = str(judgment.get("risk", candidate.get("risk", "medium"))).lower()
    if risk not in {"low", "medium", "high"}:
        risk = "medium"

    # Hard limits do not make the semantic decision; they prevent unsafe or
    # malformed automatic persistence.
    if action in {"AUTO_SAVE", "UPDATE"} and (
        risk != "low"
        or confidence < 0.85
        or source.get("status") != "approved"
    ):
        action = "PENDING_REVIEW"

    temporal_scope = normalize_temporal_scope(
        judgment.get("temporal_scope") or candidate.get("temporal_scope")
    )
    lifecycle_basis = str(
        judgment.get("lifecycle_basis")
        or candidate.get("lifecycle_basis")
        or ""
    ).upper().strip()
    if not lifecycle_basis:
        if knowledge_type == "reviewable":
            lifecycle_basis = "MAINTAINED_SET_OR_STRUCTURE"
        elif temporal_scope.get("closed_period") is True:
            lifecycle_basis = "FIXED_HISTORY"
        else:
            lifecycle_basis = (
                "DURABLE_EXPLANATION_DEFINITION_OR_MECHANISM"
            )

    lifecycle_valid = _partition_lifecycle_basis_matches(
        lifecycle_basis,
        knowledge_type,
    )
    raw_valid_for_days = judgment.get(
        "valid_for_days",
        candidate.get("suggested_valid_for_days"),
    )
    valid_for_days = None
    expires_at = None
    if knowledge_type == "stable":
        if (
            raw_valid_for_days is not None
            or lifecycle_basis == "FIXED_HISTORY"
            and temporal_scope.get("closed_period") is not True
        ):
            lifecycle_valid = False
    elif knowledge_type == "reviewable":
        if isinstance(raw_valid_for_days, bool):
            lifecycle_valid = False
        else:
            try:
                valid_for_days = int(raw_valid_for_days)
            except (TypeError, ValueError):
                lifecycle_valid = False
            else:
                if not 1 <= valid_for_days <= 3650:
                    lifecycle_valid = False
    if not lifecycle_valid:
        action = "PENDING_REVIEW"

    current = datetime.now(timezone.utc)
    now = current.isoformat()
    if knowledge_type == "reviewable" and lifecycle_valid:
        expires_at = (current + timedelta(days=valid_for_days)).isoformat()
    evidence_source = {
        "title": str(source.get("name") or source.get("domain") or "")[:300],
        "url": str(source.get("url") or "")[:2000],
        "domain": str(source.get("domain") or "")[:200],
        "source_score": source.get("trust_score"),
    }
    item = {
        "id": make_id(
            candidate.get("subject", ""),
            candidate.get("claim", ""),
            temporal_scope,
        ),
        "subject": str(candidate.get("subject", "")).strip()[:300],
        "claim": str(candidate.get("claim", "")).strip()[:3000],
        "topics": candidate.get("topics", [])[:12],
        "knowledge_domain": str(
            judgment.get("knowledge_domain")
            or candidate.get("knowledge_domain")
            or "other"
        ).lower().strip()[:80],
        "cluster_label": str(
            judgment.get("cluster_label")
            or candidate.get("cluster_label")
            or candidate.get("subject")
            or ""
        ).strip()[:120],
        "source_url": source.get("url", ""),
        "source_domain": source.get("domain", ""),
        "source_name": source.get("name", ""),
        "published_at": candidate.get("published_at"),
        "learned_at": now,
        "confidence": confidence,
        "knowledge_type": knowledge_type,
        "valid_for_days": valid_for_days,
        "expires_at": expires_at,
        "temporal_scope": temporal_scope,
        "risk": risk,
        "status": (
            "verified"
            if action in {"AUTO_SAVE", "UPDATE"}
            else "pending_review"
        ),
        "judge_reason": str(judgment.get("reason", ""))[:500],
        "lifecycle_version": KNOWLEDGE_LIFECYCLE_VERSION,
        "partition_lifecycle_audit_version": (
            PARTITION_LIFECYCLE_AUDIT_VERSION if lifecycle_valid else 0
        ),
        "lifecycle_audit": {
            "status": "PASSED" if lifecycle_valid else "PENDING",
            "audited_at": now,
            "basis": lifecycle_basis[:80],
            "reason": str(judgment.get("reason") or "")[:500],
        },
        "verification_status": "AI_APPROVED_SOURCE_AUTONOMY",
        "verification_level": "standard",
        "knowledge_judge_contract_version": judge_contract_version,
        "knowledge_judge_output_status": judge_output_status,
        "pending_identity_contract_version": (
            KNOWLEDGE_PENDING_IDENTITY_CONTRACT_VERSION
        ),
        "sources": [evidence_source] if evidence_source["url"] else [],
        "provenance": {
            "autonomous_learning": True,
            "autonomy_contract_version": 1,
            "source_policy_version": SOURCE_POLICY_VERSION,
        },
    }
    if not item["subject"] or not item["claim"]:
        return "rejected", None

    items = load_items()
    target_id = judgment.get("target_id")
    if action == "UPDATE" and target_id:
        for index, old_item in enumerate(items):
            if old_item.get("id") == target_id:
                item["id"] = target_id
                item["created_at"] = old_item.get(
                    "created_at", old_item.get("learned_at")
                )
                item["updated_at"] = now
                _attach_evidence_bundle(
                    item,
                    evidence_seed,
                    existing=old_item,
                )
                items[index] = item
                _save_knowledge(items)
                return "updated", item
        item["status"] = "pending_review"

    exact_index = next(
        (
            index for index, existing in enumerate(items)
            if str(existing.get("id") or "") == item["id"]
        ),
        None,
    )
    if exact_index is not None:
        existing = items[exact_index]
        existing_status = str(existing.get("status") or "").lower()
        if action == "AUTO_SAVE":
            if existing_status == "verified":
                # Exact deterministic identity is structural duplicate
                # protection, not a new semantic judgment.
                if evidence_seed.get("records"):
                    enriched = deepcopy(existing)
                    before = str(
                        (
                            existing.get("evidence_bundle")
                            if isinstance(
                                existing.get("evidence_bundle"), dict
                            ) else {}
                        ).get("fingerprint") or ""
                    )
                    _attach_evidence_bundle(
                        enriched,
                        evidence_seed,
                        existing=existing,
                    )
                    after = str(
                        enriched.get("evidence_bundle", {}).get(
                            "fingerprint"
                        ) or ""
                    )
                    if after and after != before:
                        enriched["updated_at"] = now
                        items[exact_index] = enriched
                        _save_knowledge(items)
                        existing = enriched
                return "duplicate", existing
            item["created_at"] = existing.get(
                "created_at", existing.get("learned_at")
            )
            item["updated_at"] = now
            _attach_evidence_bundle(
                item,
                evidence_seed,
                existing=existing,
            )
            items[exact_index] = item
            _save_knowledge(items)
            return "updated", item

        # Invalid or uncertain re-judgments must not append another row with
        # the same deterministic Knowledge ID. They also must not downgrade a
        # verified item. Retain the existing item for a later valid UPDATE.
        if existing_status != "verified":
            try:
                existing_judge_contract = max(
                    0,
                    int(existing.get("knowledge_judge_contract_version") or 0),
                )
            except (TypeError, ValueError):
                existing_judge_contract = 0
            existing["last_pending_review_at"] = now
            existing["last_pending_review_reason"] = str(
                judgment.get("reason") or ""
            )[:500]
            existing["knowledge_judge_contract_version"] = max(
                existing_judge_contract,
                judge_contract_version,
            )
            existing["knowledge_judge_output_status"] = judge_output_status
            existing["pending_identity_contract_version"] = (
                KNOWLEDGE_PENDING_IDENTITY_CONTRACT_VERSION
            )
            prior_sources = [
                value for value in existing.get("sources", [])
                if isinstance(value, dict)
            ]
            if evidence_source["url"] and all(
                value.get("url") != evidence_source["url"]
                for value in prior_sources
            ):
                prior_sources.append(evidence_source)
                existing["sources"] = prior_sources[:8]
            items[exact_index] = existing
            _save_knowledge(items)
        return "pending_review", existing

    _attach_evidence_bundle(item, evidence_seed)
    items.append(item)
    _save_knowledge(items)
    return item["status"], item


def apply_curiosity_verification(candidate, verdict, search_result, curiosity_item):
    """Persist stable knowledge under its AI-selected verification contract."""

    candidate = candidate if isinstance(candidate, dict) else {}
    verdict = verdict if isinstance(verdict, dict) else {}
    search_result = search_result if isinstance(search_result, dict) else {}
    curiosity_item = curiosity_item if isinstance(curiosity_item, dict) else {}
    judgment = (
        search_result.get("judgment")
        if isinstance(search_result.get("judgment"), dict)
        else {}
    )
    try:
        votes = int(judgment.get("votes") or 0)
    except (TypeError, ValueError):
        votes = 0

    sources = []
    domains = set()
    for source in search_result.get("results", []):
        if not isinstance(source, dict) or source.get("page_success") is not True:
            continue
        try:
            score = int(source.get("source_score") or 0)
        except (TypeError, ValueError):
            score = 0
        url = str(source.get("url") or "").strip()
        domain = urlparse(url).netloc.lower().removeprefix("www.")
        if not url or not domain or domain in domains or score < 70:
            continue
        domains.add(domain)
        sources.append({
            "title": str(source.get("title") or "")[:300],
            "url": url[:2000],
            "domain": domain,
            "source_score": score,
        })

    verification_level = str(
        verdict.get("verification_level")
        or candidate.get("verification_level")
        or "double"
    ).lower().strip()
    if verification_level not in {"standard", "double"}:
        verification_level = "double"
    extracted_answer = any(
        isinstance(answer, dict) and str(answer.get("answer") or "").strip()
        for answer in search_result.get("answers", [])
    )
    if verification_level == "standard":
        evidence_allowed = (
            str(search_result.get("status") or "").upper()
            in {"OK", "INSUFFICIENT_EVIDENCE"}
            and len(sources) >= 1
            and extracted_answer
        )
    else:
        evidence_allowed = (
            str(search_result.get("status") or "").upper() == "OK"
            and judgment.get("consensus") is True
            and judgment.get("need_more_sources") is not True
            and votes >= 2
            and len(sources) >= 2
            and isinstance(verdict.get("double_certification"), dict)
            and verdict["double_certification"].get("decision") == "CERTIFY"
        )
    if verdict.get("decision") != "PROMOTE" or not evidence_allowed:
        return "unverified", None

    try:
        confidence = max(0.0, min(1.0, float(verdict.get("confidence") or 0)))
    except (TypeError, ValueError):
        confidence = 0.0
    risk = str(verdict.get("risk") or "high").lower()
    knowledge_type = str(verdict.get("knowledge_type") or "event").lower()
    claim = str(verdict.get("canonical_claim") or "").strip()[:3000]
    subject = str(verdict.get("subject") or candidate.get("subject") or "").strip()[:300]
    temporal_scope = normalize_temporal_scope(
        verdict.get("temporal_scope") or candidate.get("temporal_scope")
    )
    lifecycle_basis = str(
        verdict.get("lifecycle_basis")
        or candidate.get("lifecycle_basis")
        or ""
    ).upper().strip()
    if not lifecycle_basis:
        if knowledge_type == "stable" and temporal_scope:
            lifecycle_basis = "FIXED_HISTORY"
        elif knowledge_type == "stable":
            lifecycle_basis = (
                "DURABLE_EXPLANATION_DEFINITION_OR_MECHANISM"
            )
        elif knowledge_type == "reviewable":
            lifecycle_basis = "MAINTAINED_SET_OR_STRUCTURE"
    valid_for_days = verdict.get("valid_for_days")
    if knowledge_type == "stable":
        if lifecycle_basis not in {
            "FIXED_HISTORY",
            "DURABLE_EXPLANATION_DEFINITION_OR_MECHANISM",
        } or valid_for_days is not None:
            return "unverified", None
        if lifecycle_basis == "FIXED_HISTORY" and (
            temporal_scope.get("closed_period") is not True
            or temporal_scope.get("allow_previous_period") is not False
        ):
            return "unverified", None
        expires_at = None
    elif knowledge_type == "reviewable":
        if (
            lifecycle_basis != "MAINTAINED_SET_OR_STRUCTURE"
            or not isinstance(valid_for_days, int)
            or not 1 <= valid_for_days <= 3650
        ):
            return "unverified", None
        expires_at = (
            datetime.now(timezone.utc) + timedelta(days=valid_for_days)
        ).isoformat()
    else:
        return "unverified", None
    if (
        risk != "low"
        or confidence < (0.80 if verification_level == "standard" else 0.88)
        or not claim
        or not subject
    ):
        return "unverified", None

    topics = []
    for value in verdict.get("topics", candidate.get("topics", [])):
        topic = str(value).strip()[:80]
        if topic and topic not in topics:
            topics.append(topic)
        if len(topics) >= 12:
            break

    now = datetime.now(timezone.utc).isoformat()
    item = {
        "id": make_id(subject, claim, temporal_scope),
        "subject": subject,
        "claim": claim,
        "topics": topics,
        "knowledge_domain": str(
            verdict.get("knowledge_domain")
            or candidate.get("knowledge_domain")
            or "other"
        ).lower().strip()[:80],
        "cluster_label": str(
            verdict.get("cluster_label")
            or candidate.get("cluster_label")
            or subject
        ).strip()[:120],
        "source_url": sources[0]["url"],
        "source_domain": sources[0]["domain"],
        "source_name": sources[0]["title"],
        "sources": sources,
        "published_at": None,
        "learned_at": now,
        "confidence": confidence,
        "knowledge_type": knowledge_type,
        "valid_for_days": valid_for_days,
        "expires_at": expires_at,
        "risk": "low",
        "status": "verified",
        "judge_reason": str(verdict.get("reason") or "")[:500],
        "verification_level": verification_level,
        "verification_status": (
            "AI_PLUS_SOURCE_CORROBORATION"
            if verification_level == "standard"
            else "DOUBLE_CERTIFIED_MULTI_SOURCE"
        ),
        "verification": {
            "query": str(search_result.get("query") or "")[:1000],
            "canonical_answer": str(judgment.get("canonical_answer") or "")[:2000],
            "original_question": str(
                curiosity_item.get("question") or ""
            )[:1200],
            "accepted_answer": str(
                curiosity_item.get("answer") or ""
            )[:6000],
            "evidence_canonical_answer": str(
                judgment.get("canonical_answer") or ""
            )[:3000],
            "evidence_answers": [
                str(value.get("answer") or "")[:2000]
                for value in search_result.get("answers", [])[:6]
                if isinstance(value, dict)
                and str(value.get("answer") or "").strip()
            ],
            "votes": votes,
            "independent_source_count": len(sources),
        },
        "provenance": {
            "origin": "nerv_curiosity",
            "curiosity_id": str(curiosity_item.get("id") or "")[:120],
            "external_ai_role": (
                "corroborating_signal"
                if verification_level == "standard"
                else "hypothesis_only"
            ),
            "external_ai_status": "UNVERIFIED_EXTERNAL_AI",
        },
        "lifecycle_audit": {
            "status": "PASSED",
            "basis": lifecycle_basis,
            "reason": str(verdict.get("reason") or "")[:500],
            "audited_at": now,
            "source": "nerv_curiosity_knowledge_verdict",
        },
        "lifecycle_version": KNOWLEDGE_LIFECYCLE_VERSION,
    }
    if temporal_scope:
        item["temporal_scope"] = temporal_scope
    item["cluster"] = _cluster_metadata(item)
    evidence_seed = knowledge_evidence.search_result_evidence_seed(
        search_result,
        accepted_only=False,
    )
    _attach_evidence_bundle(item, evidence_seed)

    items = load_items()
    for index, existing in enumerate(items):
        if existing.get("id") != item["id"]:
            continue
        if _active_persistable(existing):
            if evidence_seed.get("records"):
                enriched = deepcopy(existing)
                before = str(
                    (
                        existing.get("evidence_bundle")
                        if isinstance(existing.get("evidence_bundle"), dict)
                        else {}
                    ).get("fingerprint") or ""
                )
                _attach_evidence_bundle(
                    enriched,
                    evidence_seed,
                    existing=existing,
                )
                after = str(
                    enriched.get("evidence_bundle", {}).get("fingerprint")
                    or ""
                )
                if after and after != before:
                    enriched["updated_at"] = now
                    items[index] = enriched
                    _save_knowledge(items)
                    existing = enriched
            return "duplicate", existing
        item["created_at"] = existing.get(
            "created_at", existing.get("learned_at", now)
        )
        item["updated_at"] = now
        if isinstance(existing.get("revision_history"), list):
            item["revision_history"] = list(
                existing["revision_history"]
            )[-20:]
        _attach_evidence_bundle(
            item,
            evidence_seed,
            existing=existing,
        )
        items[index] = item
        _save_knowledge(items)
        return "verified", item

    items.append(item)
    _save_knowledge(items)
    return "verified", item


def apply_external_ai_fact_fallback(
    user_request,
    answer,
    assessment,
    audit,
    provider="ChatGPT Desktop",
    outbound_prompt="",
):
    """Persist one AI-approved low-impact fallback with explicit provenance."""

    assessment = assessment if isinstance(assessment, dict) else {}
    audit = audit if isinstance(audit, dict) else {}
    if (
        assessment.get("decision") != "ASK"
        or str(assessment.get("importance") or "").upper() != "LOW"
        or str(assessment.get("sharing_risk") or "").upper() != "NORMAL"
        or audit.get("decision") != "AUTO_VERIFY"
        or audit.get("directly_answers") is not True
        or audit.get("complete_for_request") is not True
        or audit.get("policy_satisfied") is not True
        or audit.get("no_evidence_conflict") is not True
    ):
        return "rejected", None
    try:
        confidence = max(0.0, min(1.0, float(audit.get("confidence") or 0)))
    except (TypeError, ValueError):
        confidence = 0.0
    if confidence < 0.80:
        return "rejected", None

    knowledge_type = str(
        assessment.get("knowledge_type") or "event"
    ).lower().strip()
    lifecycle_basis = str(
        assessment.get("lifecycle_basis") or ""
    ).upper()
    if not _partition_lifecycle_basis_matches(
        lifecycle_basis, knowledge_type
    ):
        return "rejected", None
    if knowledge_type not in {"stable", "reviewable"}:
        return "rejected", None
    valid_for_days = assessment.get("valid_for_days")
    if knowledge_type == "stable":
        valid_for_days = None
        expires_at = None
    elif (
        not isinstance(valid_for_days, int)
        or not 1 <= valid_for_days <= 3650
    ):
        return "rejected", None
    else:
        expires_at = (
            datetime.now(timezone.utc) + timedelta(days=valid_for_days)
        ).isoformat()

    subject = str(audit.get("subject") or "").strip()[:300]
    claim = str(audit.get("canonical_claim") or answer or "").strip()[:3000]
    if not subject or not claim or not str(answer or "").strip():
        return "rejected", None
    topics = []
    for value in audit.get("topics", []):
        topic = str(value).strip()[:80]
        if topic and topic.casefold() not in {
            old.casefold() for old in topics
        }:
            topics.append(topic)
        if len(topics) >= 12:
            break

    now = datetime.now(timezone.utc).isoformat()
    temporal_scope = normalize_temporal_scope(
        assessment.get("temporal_scope")
    )
    if (
        lifecycle_basis == "FIXED_HISTORY"
        and (
            temporal_scope.get("closed_period") is not True
            or temporal_scope.get("allow_previous_period") is not False
        )
    ):
        return "rejected", None
    item = {
        "id": make_id(subject, claim, temporal_scope),
        "subject": subject,
        "claim": claim,
        "topics": topics,
        "knowledge_domain": str(
            audit.get("knowledge_domain") or "other"
        ).lower().strip()[:80],
        "cluster_label": str(
            audit.get("cluster_label") or subject
        ).strip()[:120],
        "source_url": "",
        "source_domain": "external_ai",
        "source_name": str(provider or "ChatGPT Desktop")[:200],
        "sources": [],
        "published_at": None,
        "learned_at": now,
        "confidence": confidence,
        "knowledge_type": knowledge_type,
        "valid_for_days": valid_for_days,
        "expires_at": expires_at,
        "risk": "low",
        "status": "verified",
        "judge_reason": str(audit.get("reason") or "")[:500],
        "verification_level": "external_ai_low_impact",
        "verification_status": "EXTERNAL_AI_LOW_IMPACT_POLICY_VERIFIED",
        "evidence_status": "POLICY_VERIFIED_WITHOUT_PUBLIC_SOURCE_ASSET",
        "verification": {
            "original_request": str(user_request or "")[:2000],
            "outbound_prompt": str(outbound_prompt or "")[:5000],
            "answer": str(answer or "")[:12000],
            "valid_until": expires_at,
        },
        "provenance": {
            "origin": "external_ai_fact_fallback",
            "external_ai_role": "primary_low_impact_authority",
            "external_ai_status": "POLICY_VERIFIED",
            "provider": str(provider or "ChatGPT Desktop")[:200],
        },
        "lifecycle_version": KNOWLEDGE_LIFECYCLE_VERSION,
        "lifecycle_audit": {
            "version": PARTITION_LIFECYCLE_AUDIT_VERSION,
            "status": "PASSED",
            "basis": lifecycle_basis[:80],
            "audited_at": now,
            "source": "external_fact_fallback_policy_audit",
        },
    }
    if temporal_scope:
        item["temporal_scope"] = temporal_scope
    item["cluster"] = _cluster_metadata(item)
    items = load_items()
    for index, existing in enumerate(items):
        if existing.get("id") != item["id"]:
            continue
        if existing.get("status") == "verified":
            item["created_at"] = existing.get(
                "created_at", existing.get("learned_at", now)
            )
            item["updated_at"] = now
            if isinstance(existing.get("revision_history"), list):
                item["revision_history"] = list(
                    existing["revision_history"]
                )[-20:]
            if isinstance(existing.get("dispute"), dict):
                item["dispute"] = dict(existing["dispute"])
            items[index] = item
            _save_knowledge(items)
            return "updated", item
        item["created_at"] = existing.get(
            "created_at", existing.get("learned_at", now)
        )
        item["updated_at"] = now
        if isinstance(existing.get("revision_history"), list):
            item["revision_history"] = list(existing["revision_history"])[-20:]
        if isinstance(existing.get("dispute"), dict):
            item["dispute"] = dict(existing["dispute"])
        items[index] = item
        _save_knowledge(items)
        return "updated", item
    items.append(item)
    _save_knowledge(items)
    return "verified", item


def apply_external_ai_partitioned_claim(
    user_request,
    answer,
    assessment,
    candidate,
    provider="ChatGPT Desktop",
    outbound_prompt="",
    source_context=None,
):
    """Persist one AI-separated reusable claim from a mixed low-impact answer."""
    assessment = assessment if isinstance(assessment, dict) else {}
    candidate = candidate if isinstance(candidate, dict) else {}
    source_context = (
        source_context if isinstance(source_context, dict) else {}
    )
    try:
        lifecycle_audit_version = int(
            candidate.get("partition_lifecycle_audit_version") or 0
        )
    except (TypeError, ValueError):
        lifecycle_audit_version = 0
    try:
        roster_normalization_version = int(
            candidate.get(
                "current_roster_lifecycle_normalization_version"
            ) or 0
        )
    except (TypeError, ValueError):
        roster_normalization_version = 0
    if (
        assessment.get("decision") != "ASK"
        or str(assessment.get("importance") or "").upper() != "LOW"
        or str(assessment.get("sharing_risk") or "").upper() != "NORMAL"
        or assessment.get("has_reusable_component") is not True
        or candidate.get("persist") is not True
        or candidate.get("directly_supported_by_answer") is not True
        or candidate.get("no_evidence_conflict") is not True
        or str(candidate.get("lifecycle_audit_status") or "").upper()
        != "PASSED"
        or lifecycle_audit_version < PARTITION_LIFECYCLE_AUDIT_VERSION
    ):
        return "rejected", None
    try:
        confidence = max(0.0, min(1.0, float(candidate.get("confidence") or 0)))
    except (TypeError, ValueError):
        confidence = 0.0
    if confidence < 0.80:
        return "rejected", None
    knowledge_type = str(candidate.get("knowledge_type") or "event").lower()
    lifecycle_basis = str(
        candidate.get("lifecycle_basis") or ""
    ).upper()
    if not _partition_lifecycle_basis_matches(
        lifecycle_basis, knowledge_type
    ):
        return "rejected", None
    if knowledge_type not in {"stable", "reviewable"}:
        return "rejected", None
    valid_for_days = candidate.get("valid_for_days")
    current_people_roster = candidate.get("current_people_roster") is True
    if current_people_roster and (
        lifecycle_basis != "MAINTAINED_SET_OR_STRUCTURE"
        or knowledge_type != "reviewable"
        or valid_for_days != CURRENT_PEOPLE_ROSTER_REVIEW_DAYS
        or roster_normalization_version
        < CURRENT_ROSTER_LIFECYCLE_NORMALIZATION_VERSION
    ):
        return "rejected", None
    if knowledge_type == "stable":
        if valid_for_days is not None:
            return "rejected", None
        expires_at = None
    elif not isinstance(valid_for_days, int) or not 1 <= valid_for_days <= 3650:
        return "rejected", None
    else:
        expires_at = (
            datetime.now(timezone.utc) + timedelta(days=valid_for_days)
        ).isoformat()
    subject = str(candidate.get("subject") or "").strip()[:300]
    claim = str(candidate.get("claim") or "").strip()[:3000]
    if not subject or not claim or not str(answer or "").strip():
        return "rejected", None
    topics = []
    for value in candidate.get("topics", []):
        topic = str(value).strip()[:80]
        if topic and topic.casefold() not in {old.casefold() for old in topics}:
            topics.append(topic)
        if len(topics) >= 12:
            break
    now = datetime.now(timezone.utc).isoformat()
    sources = [
        dict(value)
        for value in source_context.get("sources", [])[:8]
        if isinstance(value, dict)
    ]
    source_url = str(source_context.get("source_url") or "")[:2000]
    source_domain = str(
        source_context.get("source_domain") or "external_ai"
    )[:200]
    source_name = str(
        source_context.get("source_name") or provider or "ChatGPT Desktop"
    )[:300]
    if sources and not source_url:
        source_url = str(sources[0].get("url") or "")[:2000]
    if sources and source_domain == "external_ai":
        source_domain = str(sources[0].get("domain") or source_domain)[:200]
    provenance = source_context.get("provenance")
    provenance = (
        dict(provenance) if isinstance(provenance, dict) else {
            "origin": "external_ai_fact_fallback",
            "external_ai_role": "primary_low_impact_authority",
            "external_ai_status": "POLICY_VERIFIED",
        }
    )
    provenance["provider"] = str(provider or "ChatGPT Desktop")[:200]
    provenance["mixed_answer_partition"] = True
    temporal_scope = normalize_temporal_scope(
        candidate.get("temporal_scope")
    )
    if (
        lifecycle_basis == "FIXED_HISTORY"
        and (
            temporal_scope.get("closed_period") is not True
            or temporal_scope.get("allow_previous_period") is not False
        )
    ):
        return "rejected", None
    if not temporal_scope and lifecycle_basis != "FIXED_HISTORY":
        temporal_scope = normalize_temporal_scope(
            assessment.get("temporal_scope")
        )
    item = {
        "id": make_id(subject, claim, temporal_scope),
        "subject": subject,
        "claim": claim,
        "topics": topics,
        "knowledge_domain": str(
            candidate.get("knowledge_domain") or "other"
        ).lower().strip()[:80],
        "cluster_label": str(
            candidate.get("cluster_label") or subject
        ).strip()[:120],
        "source_url": source_url,
        "source_domain": source_domain,
        "source_name": source_name,
        "sources": sources,
        "published_at": None,
        "learned_at": now,
        "confidence": confidence,
        "knowledge_type": knowledge_type,
        "lifecycle_basis": lifecycle_basis,
        "valid_for_days": valid_for_days,
        "expires_at": expires_at,
        "risk": "low",
        "status": "verified",
        "judge_reason": str(candidate.get("reason") or "")[:500],
        "verification_level": str(
            source_context.get("verification_level")
            or "external_ai_low_impact"
        )[:100],
        "verification_status": str(
            source_context.get("verification_status")
            or "EXTERNAL_AI_LOW_IMPACT_POLICY_VERIFIED"
        )[:120],
        "verification": {
            "original_request": str(user_request or "")[:2000],
            "outbound_prompt": str(outbound_prompt or "")[:5000],
            "answer": str(answer or "")[:12000],
            "partitioned_claim": True,
            "valid_until": expires_at,
            "source_context": (
                source_context.get("verification")
                if isinstance(source_context.get("verification"), dict)
                else {}
            ),
        },
        "provenance": provenance,
        "partition_lifecycle_audit_version": int(
            lifecycle_audit_version
        ),
        "lifecycle_audit": {
            "status": str(
                candidate.get("lifecycle_audit_status") or "NOT_AUDITED"
            )[:40],
            "basis": lifecycle_basis[:80],
            "reason": str(
                candidate.get("lifecycle_audit_reason") or ""
            )[:500],
        },
        "lifecycle_version": KNOWLEDGE_LIFECYCLE_VERSION,
    }
    if current_people_roster:
        item["current_people_roster"] = True
        item["current_roster_lifecycle_normalization_version"] = (
            CURRENT_ROSTER_LIFECYCLE_NORMALIZATION_VERSION
        )
    if temporal_scope:
        item["temporal_scope"] = temporal_scope
    item["cluster"] = _cluster_metadata(item)
    evidence_seed = (
        source_context.get("evidence_seed")
        if isinstance(source_context.get("evidence_seed"), dict)
        else {}
    )
    _attach_evidence_bundle(item, evidence_seed)
    items = load_items()
    for index, existing in enumerate(items):
        if existing.get("id") != item["id"]:
            continue
        item["created_at"] = existing.get(
            "created_at", existing.get("learned_at", now)
        )
        item["updated_at"] = now
        if isinstance(existing.get("revision_history"), list):
            item["revision_history"] = list(existing["revision_history"])[-20:]
        if isinstance(existing.get("dispute"), dict):
            item["dispute"] = dict(existing["dispute"])
        if isinstance(existing.get("curation"), dict):
            item["curation"] = deepcopy(existing["curation"])
        _attach_evidence_bundle(
            item,
            evidence_seed,
            existing=existing,
        )
        items[index] = item
        _save_knowledge(items)
        return "updated", item
    if current_people_roster:
        for index, existing in enumerate(items):
            if not _active_persistable(existing):
                continue
            curation = existing.get("curation")
            if (
                isinstance(curation, dict)
                and curation.get("status") in {
                    "duplicate", "conflict", "inactive",
                }
            ):
                continue
            if not _same_current_people_roster(existing, item):
                continue
            refreshed = deepcopy(existing)
            history = refreshed.get("revision_history")
            history = list(history) if isinstance(history, list) else []
            history.append(
                _knowledge_revision_snapshot(
                    refreshed,
                    "CURRENT_ROSTER_REVERIFIED",
                    now,
                )
            )
            refreshed["revision_history"] = history[-20:]
            for key in (
                "confidence", "knowledge_type", "lifecycle_basis",
                "valid_for_days",
                "expires_at", "risk", "status", "judge_reason",
                "verification_level", "verification_status", "verification",
                "provenance", "partition_lifecycle_audit_version",
                "lifecycle_audit", "lifecycle_version",
                "current_people_roster",
                "current_roster_lifecycle_normalization_version",
            ):
                refreshed[key] = deepcopy(item.get(key))
            refreshed["sources"] = _merge_knowledge_sources(
                item.get("sources"), existing.get("sources")
            )
            _attach_evidence_bundle(
                refreshed,
                evidence_seed,
                existing=existing,
            )
            refreshed["source_url"] = item.get("source_url")
            refreshed["source_domain"] = item.get("source_domain")
            refreshed["source_name"] = item.get("source_name")
            refreshed["updated_at"] = now
            refreshed["last_verified_at"] = now
            review = refreshed.get("current_roster_review")
            review = dict(review) if isinstance(review, dict) else {}
            review["last_verified_at"] = now
            review["refresh_count"] = int(
                review.get("refresh_count") or 0
            ) + 1
            review["matched_member_count"] = len(
                _current_people_roster_entries(item)
            )
            refreshed["current_roster_review"] = review
            items[index] = refreshed
            _save_knowledge(items)
            print(
                "[KNOWLEDGE CURRENT ROSTER REFRESH]",
                "id=" + str(refreshed.get("id") or ""),
                "members=" + str(review["matched_member_count"]),
            )
            return "updated", refreshed
    items.append(item)
    _save_knowledge(items)
    return "verified", item


def _apply_verified_browser_partitioned_claim(
    user_request,
    answer,
    candidate,
    search_result,
    *,
    origin,
    verification_level,
    verification_status,
    user_correction=False,
):
    """Persist one AI-audited reusable claim from accepted browser evidence."""
    search_result = search_result if isinstance(search_result, dict) else {}
    sources = []
    seen_urls = set()
    for raw in search_result.get("results", [])[:12]:
        if not isinstance(raw, dict):
            continue
        url = str(raw.get("url") or "").strip()[:2000]
        if not url or url in seen_urls:
            continue
        seen_urls.add(url)
        domain = str(raw.get("domain") or "").strip().lower()
        if not domain:
            domain = urlparse(url).netloc.lower().removeprefix("www.")
        sources.append({
            "title": str(raw.get("title") or "")[:300],
            "url": url,
            "domain": domain[:200],
            "source_score": raw.get("source_score"),
            "published_at": str(
                raw.get("published_at") or raw.get("published") or ""
            )[:100],
            "official_identity_verified": (
                raw.get("official_identity_verified") is True
            ),
            "official_identity_basis": str(
                raw.get("official_identity_basis") or ""
            )[:160],
            "publisher_name": str(raw.get("publisher_name") or "")[:200],
            "publisher_url": str(raw.get("publisher_url") or "")[:2000],
            "official_publisher_page_bound": (
                raw.get("official_publisher_page_bound") is True
            ),
            "official_publisher_video_discovery_version": (
                raw.get(
                    "official_publisher_video_discovery_version"
                )
            ),
        })
        if len(sources) >= 8:
            break
    assessment = {
        "decision": "ASK",
        "importance": "LOW",
        "sharing_risk": "NORMAL",
        "has_reusable_component": True,
    }
    return apply_external_ai_partitioned_claim(
        user_request=user_request,
        answer=answer,
        assessment=assessment,
        candidate=candidate,
        provider="Casper Audited Fact Lookup",
        source_context={
            "sources": sources,
            "evidence_seed": knowledge_evidence.search_result_evidence_seed(
                search_result,
                accepted_only=True,
            ),
            "source_domain": (
                sources[0]["domain"] if sources else "casper_fact_lookup"
            ),
            "source_name": (
                sources[0]["title"] if sources else "Casper Fact Lookup"
            ),
            "verification_level": verification_level,
            "verification_status": verification_status,
            "verification": {
                "query": str(search_result.get("query") or "")[:1000],
                "original_request": str(user_request or "")[:2000],
                "accepted_answer": str(answer or "")[:6000],
                "evidence_canonical_answer": str(
                    (
                        search_result.get("judgment")
                        if isinstance(search_result.get("judgment"), dict)
                        else {}
                    ).get("canonical_answer")
                    or ""
                )[:3000],
                "evidence_answers": [
                    str(value.get("answer") or "")[:2000]
                    for value in search_result.get("answers", [])[:6]
                    if isinstance(value, dict)
                    and str(value.get("answer") or "").strip()
                ],
                "discovery_type": str(
                    search_result.get("discovery_type") or ""
                )[:100],
                "source_contract": (
                    deepcopy(search_result.get("source_contract"))
                    if isinstance(search_result.get("source_contract"), dict)
                    else {}
                ),
                "independent_source_count": len(sources),
                "accepted_temporal_validations": [
                    item.get("temporal_validation")
                    for item in search_result.get("answers", [])[:8]
                    if isinstance(item, dict)
                    and item.get("accepted") is True
                    and isinstance(item.get("temporal_validation"), dict)
                ],
            },
            "provenance": {
                "origin": origin,
                "casper_status": str(
                    search_result.get("status") or ""
                )[:40],
                "knowledge_capture_after_reply": not user_correction,
                "official_source_proof_version": (
                    OFFICIAL_SOURCE_PROOF_MIGRATION_VERSION
                ),
                "user_correction_is_evidence": (
                    False if user_correction else None
                ),
            },
        },
    )


def apply_verified_fact_lookup_partitioned_claim(
    user_request,
    answer,
    candidate,
    search_result,
):
    """Persist reusable Knowledge from a normal accepted FACT_LOOKUP."""
    return _apply_verified_browser_partitioned_claim(
        user_request,
        answer,
        candidate,
        search_result,
        origin="casper_audited_fact_lookup",
        verification_level="casper_fact_lookup_knowledge_intake",
        verification_status="AI_PARTITIONED_AUDITED_FACT_LOOKUP",
    )


def apply_verified_correction_partitioned_claim(
    user_request,
    answer,
    candidate,
    search_result,
):
    """Persist one reusable claim from an accepted correction lookup."""
    return _apply_verified_browser_partitioned_claim(
        user_request,
        answer,
        candidate,
        search_result,
        origin="user_correction_fact_lookup",
        verification_level="casper_fact_correction",
        verification_status="AI_PARTITIONED_AUDITED_FACT_ANSWER",
        user_correction=True,
    )


def apply_lifecycle_audit(decisions):
    """Execute AI lifecycle decisions for existing knowledge entries."""

    if not isinstance(decisions, list):
        return {"kept": 0, "expired": 0, "removed": 0}
    by_id = {
        str(item.get("id")): item
        for item in decisions
        if isinstance(item, dict) and item.get("id")
    }
    items = load_items()
    kept_items = []
    counts = {"kept": 0, "expired": 0, "removed": 0}
    now = datetime.now(timezone.utc)

    for item in items:
        decision = by_id.get(str(item.get("id")))
        if not decision:
            kept_items.append(item)
            continue
        action = str(decision.get("action", "KEEP")).upper()
        knowledge_type = str(decision.get("knowledge_type", "stable")).lower()
        if knowledge_type not in {"stable", "changing", "event", "news"}:
            knowledge_type = "stable"

        if action == "REMOVE_LONG_TERM" or knowledge_type != "stable":
            counts["removed"] += 1
            continue

        item["knowledge_type"] = knowledge_type
        item["lifecycle_version"] = KNOWLEDGE_LIFECYCLE_VERSION
        item["lifecycle_reason"] = str(decision.get("reason", ""))[:500]
        if action == "EXPIRE":
            item["status"] = "expired"
            item["expires_at"] = now.isoformat()
            counts["expired"] += 1
        else:
            item["valid_for_days"] = None
            item["expires_at"] = None
            item["cluster"] = _cluster_metadata(item)
            counts["kept"] += 1
        kept_items.append(item)

    _save_knowledge(kept_items)
    return counts


def append_learning_log(log):
    initialize()
    logs = _load(LOGS_FILE, [])
    logs.append(log)
    _save(LOGS_FILE, logs[-365:])


def load_learning_logs():
    """Read learning history from SQLite with its rollback-compatible mirror."""

    initialize()
    value = _load(LOGS_FILE, [])
    return [item for item in value if isinstance(item, dict)]


def today_log():
    initialize()
    today = datetime.now().date().isoformat()
    return [item for item in load_learning_logs() if item.get("date") == today]


def format_today_report():
    logs = today_log()
    if not logs:
        return "我今天还没有完成新的自主学习周期哦。"

    latest = logs[-1]
    summaries = [
        str(item).strip()
        for item in latest.get("summary", [])
        if str(item).strip()
    ]
    if not summaries:
        return (
            "我今天检查了学习主题和来源，但没有发现适合记录的新知识。"
        )

    lines = ["我今天学到或记录了这些内容 📚"]
    lines.extend(
        str(index) + ". " + summary
        for index, summary in enumerate(summaries[:8], start=1)
    )
    log_only = int(latest.get("log_only", 0))
    if log_only:
        lines.append(
            "其中有 " + str(log_only) + " 条是短期事件/新闻，只保留在今天的学习日志里。"
        )
    return "\n".join(lines)


def add_source_candidate(result, topics):
    url = str(result.get("url", "")).strip()
    domain = urlparse(url).netloc.lower().removeprefix("www.")
    if not url or not domain:
        return False

    candidates = _load(PENDING_SOURCES_FILE, [])
    for item in candidates:
        if item.get("url") != url:
            continue
        previous_topics = item.get("topics", [])
        merged_topics = _merge_source_topics(previous_topics, topics)
        if merged_topics == previous_topics:
            return False
        if item.get("status") == "rejected":
            return False
        item["topics"] = merged_topics
        if item.get("status") == "approved":
            # Re-check page relevance before extending an approval to a new
            # topic; the Source Judge still owns that semantic decision.
            item["status"] = "candidate"
            item["topic_extension_review"] = True
        item["discovery_contract_version"] = SOURCE_DISCOVERY_CONTRACT_VERSION
        _save(PENDING_SOURCES_FILE, candidates)
        return True

    same_domain = [
        item for item in candidates
        if str(item.get("domain") or "").lower() == domain
    ]
    if len(same_domain) >= SOURCE_CANDIDATE_MAX_URLS_PER_DOMAIN:
        return False

    suffix_signal = domain.endswith(".org") or domain.endswith(".edu")
    candidates.append(
        {
            "name": result.get("title") or domain,
            "url": url,
            "domain": domain,
            "topics": _merge_source_topics(topics),
            "status": "candidate",
            "trust": "unverified",
            "suffix_signal": "org_or_edu" if suffix_signal else None,
            "discovered_at": datetime.now(timezone.utc).isoformat(),
            "discovery_contract_version": SOURCE_DISCOVERY_CONTRACT_VERSION,
            "attempt_count": 0,
            "last_attempt_at": None,
            "last_attempt_status": None,
            "last_error": None,
            "retry_after": None,
        }
    )
    _save(PENDING_SOURCES_FILE, candidates)
    return True
