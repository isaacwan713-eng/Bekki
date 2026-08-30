"""Local, auditable knowledge store for Bekki Knowledge V1."""

import hashlib
import json
import os
import random
import re
import shutil
import threading
from datetime import datetime, timedelta, timezone
from urllib.parse import urlparse


DATA_DIR = "data"
KNOWLEDGE_FILE = os.path.join(DATA_DIR, "knowledge.json")
SOURCES_FILE = os.path.join(DATA_DIR, "knowledge_sources.json")
LOGS_FILE = os.path.join(DATA_DIR, "learning_logs.json")
PENDING_SOURCES_FILE = os.path.join(DATA_DIR, "knowledge_source_candidates.json")
SOURCE_POLICY_VERSION = 2
KNOWLEDGE_LIFECYCLE_VERSION = 1
PARTITION_LIFECYCLE_AUDIT_VERSION = 7
KNOWLEDGE_CLUSTER_VERSION = 1
KNOWLEDGE_TOPIC_SCHEMA_VERSION = 1
KNOWLEDGE_DISPLAY_VERSION = 1

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
    try:
        with open(path, "r", encoding="utf-8") as file:
            value = json.load(file)
        return value
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        return default


def _save(path, value, backup=False):
    directory = os.path.dirname(os.path.abspath(path))
    os.makedirs(directory, exist_ok=True)
    temporary = path + ".tmp"
    with open(temporary, "w", encoding="utf-8") as file:
        json.dump(value, file, ensure_ascii=False, indent=2)
    if backup and os.path.exists(path):
        try:
            shutil.copy2(path, path + ".bak")
        except OSError:
            # The temporary file still replaces the old value atomically. A
            # backup failure must not leave a half-written JSON document.
            pass
    os.replace(temporary, path)


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
        "updated_at": None,
        "topics": {},
        "terms": {},
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
        if not os.path.exists(path):
            _save(path, default)


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


def initialize():
    os.makedirs(DATA_DIR, exist_ok=True)
    if not os.path.exists(KNOWLEDGE_FILE):
        _save(KNOWLEDGE_FILE, [])
    if not os.path.exists(SOURCES_FILE):
        _save(SOURCES_FILE, DEFAULT_SOURCES)
    if not os.path.exists(LOGS_FILE):
        _save(LOGS_FILE, [])
    if not os.path.exists(PENDING_SOURCES_FILE):
        _save(PENDING_SOURCES_FILE, [])
    if not os.path.exists(_clusters_file()):
        _rebuild_cluster_index(_load(KNOWLEDGE_FILE, []))
    initialize_topic_store()
    _sync_curation_inbox(_load(KNOWLEDGE_FILE, []))


def load_items():
    initialize()
    return _load(KNOWLEDGE_FILE, [])


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


def record_curator_run(status, details=None, local_date=None):
    """Append an auditable run result without changing Knowledge semantics."""
    normalized = str(status or "FAILED").upper()
    if normalized not in {"COMPLETED", "FAILED", "SKIPPED"}:
        normalized = "FAILED"
    now = datetime.now(timezone.utc).isoformat()
    with _CURATION_LOCK:
        payload = load_curator_runs()
        payload["last_attempt_at"] = now
        if normalized == "COMPLETED":
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
        for item in document.get("claims", []):
            if not isinstance(item, dict):
                continue
            knowledge_id = str(item.get("id") or "")
            if not knowledge_id or knowledge_id in seen:
                continue
            seen.add(knowledge_id)
            items.append(item)
    return items


def load_topic_catalog(include_claims=True, max_topics=80, max_claims=20):
    """Return compact AI-facing topic metadata; no topic choice is inferred."""
    catalog = []
    for document in _topic_documents()[:max(0, int(max_topics))]:
        topic = document.get("topic")
        topic = topic if isinstance(topic, dict) else {}
        entities = document.get("entities")
        entities = entities if isinstance(entities, dict) else {}
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
                    "temporal_scope": normalize_temporal_scope(
                        item.get("temporal_scope")
                    ),
                }
                for item in document.get("claims", [])[-max(0, int(max_claims)):]
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
        "created_at": now,
        "updated_at": now,
    }


def _merge_entity(document, entity):
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
        "aliases": _merge_text_values(
            list(old.get("aliases", [])) + preserved_old_names,
            entity.get("aliases", []),
            24,
        ),
    }
    if not entities[entity_id]["name"]:
        raise ValueError("missing_entity_name")
    return entity_id


def _merge_assignment_into_topic(document, item, assignment):
    topic = document.setdefault("topic", {})
    topic["id"] = str(assignment.get("topic_id") or "").lower()
    if assignment.get("topic_title"):
        topic["title"] = str(assignment.get("topic_title"))[:200]
    topic["aliases"] = _merge_text_values(
        topic.get("aliases", []), assignment.get("topic_aliases", []), 40
    )
    topic["keywords"] = _merge_text_values(
        topic.get("keywords", []), assignment.get("topic_keywords", []), 80
    )
    subject_id = _merge_entity(document, assignment.get("subject_entity"))
    related_ids = []
    relationships = document.setdefault("relationships", [])
    relationship_ids = {
        str(value.get("id") or "")
        for value in relationships if isinstance(value, dict)
    }
    for related in assignment.get("related_entities", []):
        if not isinstance(related, dict):
            continue
        related_id = _merge_entity(document, related)
        related_ids.append(related_id)
        relation = " ".join(str(related.get("relation") or "related_to").split())[:120]
        material = (subject_id + "\n" + relation.casefold() + "\n" + related_id).encode("utf-8")
        relationship_id = "relation_" + hashlib.sha256(material).hexdigest()[:16]
        if relationship_id not in relationship_ids:
            relationships.append({
                "id": relationship_id,
                "source_entity_id": subject_id,
                "relation": relation,
                "target_entity_id": related_id,
                "claim_relation_evidence": str(
                    related.get("claim_relation_evidence") or ""
                )[:300],
            })
            relationship_ids.add(relationship_id)
    claim = dict(item)
    claim["curation"] = {
        "status": "curated",
        "topic_id": topic["id"],
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
        "facet": " ".join(str(assignment.get("facet") or "general").split())[:120],
        "keywords": _merge_text_values([], assignment.get("claim_keywords", []), 24),
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
    terms = {}
    for document in _topic_documents():
        topic = document.get("topic")
        topic = topic if isinstance(topic, dict) else {}
        topic_id = str(topic.get("id") or "")
        if not _SAFE_TOPIC_ID_RE.fullmatch(topic_id):
            continue
        entities = document.get("entities")
        entities = entities if isinstance(entities, dict) else {}
        entry = {
            "path": "topics/" + topic_id + ".json",
            "title": str(topic.get("title") or "")[:200],
            "aliases": [str(value)[:120] for value in topic.get("aliases", [])[:40]],
            "keywords": [str(value)[:120] for value in topic.get("keywords", [])[:80]],
            "entity_ids": [str(value)[:80] for value in list(entities)[:200]],
            "claim_count": len([
                value for value in document.get("claims", [])
                if isinstance(value, dict)
            ]),
        }
        payload["topics"][topic_id] = entry
        lookup_values = [entry["title"], topic_id, *entry["aliases"], *entry["keywords"]]
        for entity in entities.values():
            if not isinstance(entity, dict):
                continue
            lookup_values.extend([
                entity.get("name"), entity.get("id"), *entity.get("aliases", [])
            ])
        for claim in document.get("claims", []):
            if not isinstance(claim, dict):
                continue
            curation = claim.get("curation")
            if isinstance(curation, dict):
                lookup_values.extend(curation.get("keywords", []))
        for raw in lookup_values:
            term = " ".join(str(raw or "").split()).casefold()[:160]
            if not term:
                continue
            values = terms.setdefault(term, [])
            if topic_id not in values:
                values.append(topic_id)
    payload["terms"] = terms
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


def load_sources(approved_only=True):
    initialize()
    sources = _load(SOURCES_FILE, DEFAULT_SOURCES)
    if approved_only:
        return [item for item in sources if item.get("status") == "approved"]
    return sources


def load_source_candidates():
    initialize()
    return _load(PENDING_SOURCES_FILE, [])


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

    candidates = load_source_candidates()
    for item in candidates:
        if item.get("url") == candidate.get("url"):
            item["status"] = decision.lower()
            item["source_class"] = trust_class
            item["trust_score"] = trust_score
            item["judgment_reason"] = str(judgment.get("reason", ""))[:500]
            item["reviewed_at"] = datetime.now(timezone.utc).isoformat()
            item["policy_version"] = SOURCE_POLICY_VERSION
    _save(PENDING_SOURCES_FILE, candidates)

    if decision == "APPROVE":
        sources = load_sources(approved_only=False)
        if not any(item.get("url") == candidate.get("url") for item in sources):
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
                    "approved_at": datetime.now(timezone.utc).isoformat(),
                }
            )
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


def make_id(subject, claim, temporal_scope=None):
    material_text = subject.strip().lower() + "\n" + claim.strip().lower()
    temporal_suffix = _temporal_identity_suffix(temporal_scope)
    if temporal_suffix:
        material_text += "\n" + temporal_suffix
    material = material_text.encode()
    return "knowledge_" + hashlib.sha256(material).hexdigest()[:16]


def apply_knowledge_judgment(candidate, source, judgment):
    """Execute an AI knowledge decision within structural safety limits."""

    action = str(judgment.get("action", "PENDING_REVIEW")).upper()
    if action not in {
        "AUTO_SAVE", "LOG_ONLY", "PENDING_REVIEW", "REJECT", "DUPLICATE", "UPDATE"
    }:
        action = "PENDING_REVIEW"

    if action in {"REJECT", "DUPLICATE"}:
        return action.lower(), None

    knowledge_type = str(judgment.get("knowledge_type", "stable")).lower()
    if knowledge_type not in {"stable", "changing", "event", "news"}:
        knowledge_type = "stable"

    if knowledge_type != "stable" or action == "LOG_ONLY":
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
    if action == "AUTO_SAVE" and (
        risk != "low"
        or confidence < 0.85
        or source.get("status") != "approved"
    ):
        action = "PENDING_REVIEW"

    valid_for_days = None

    now = datetime.now(timezone.utc).isoformat()
    item = {
        "id": make_id(candidate.get("subject", ""), candidate.get("claim", "")),
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
        "expires_at": None,
        "risk": risk,
        "status": "verified" if action == "AUTO_SAVE" else "pending_review",
        "judge_reason": str(judgment.get("reason", ""))[:500],
        "lifecycle_version": KNOWLEDGE_LIFECYCLE_VERSION,
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
                items[index] = item
                _save_knowledge(items)
                return "updated", item
        item["status"] = "pending_review"

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

    items = load_items()
    for index, existing in enumerate(items):
        if existing.get("id") != item["id"]:
            continue
        if _active_persistable(existing):
            return "duplicate", existing
        item["created_at"] = existing.get(
            "created_at", existing.get("learned_at", now)
        )
        item["updated_at"] = now
        if isinstance(existing.get("revision_history"), list):
            item["revision_history"] = list(
                existing["revision_history"]
            )[-20:]
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
    if temporal_scope:
        item["temporal_scope"] = temporal_scope
    item["cluster"] = _cluster_metadata(item)
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
        items[index] = item
        _save_knowledge(items)
        return "updated", item
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
            "published_at": str(raw.get("published_at") or "")[:100],
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


def today_log():
    initialize()
    today = datetime.now().date().isoformat()
    return [item for item in _load(LOGS_FILE, []) if item.get("date") == today]


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
    if any(item.get("domain") == domain for item in candidates):
        return False

    suffix_signal = domain.endswith(".org") or domain.endswith(".edu")
    candidates.append(
        {
            "name": result.get("title") or domain,
            "url": url,
            "domain": domain,
            "topics": topics,
            "status": "candidate",
            "trust": "unverified",
            "suffix_signal": "org_or_edu" if suffix_signal else None,
            "discovered_at": datetime.now(timezone.utc).isoformat(),
        }
    )
    _save(PENDING_SOURCES_FILE, candidates)
    return True
