"""Local, auditable knowledge store for Bekki Knowledge V1."""

import hashlib
import json
import os
from datetime import datetime, timedelta, timezone
from urllib.parse import urlparse


DATA_DIR = "data"
KNOWLEDGE_FILE = os.path.join(DATA_DIR, "knowledge.json")
SOURCES_FILE = os.path.join(DATA_DIR, "knowledge_sources.json")
LOGS_FILE = os.path.join(DATA_DIR, "learning_logs.json")
PENDING_SOURCES_FILE = os.path.join(DATA_DIR, "knowledge_source_candidates.json")
SOURCE_POLICY_VERSION = 2
KNOWLEDGE_LIFECYCLE_VERSION = 1

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


def _save(path, value):
    os.makedirs(DATA_DIR, exist_ok=True)
    temporary = path + ".tmp"
    with open(temporary, "w", encoding="utf-8") as file:
        json.dump(value, file, ensure_ascii=False, indent=2)
    os.replace(temporary, path)


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


def load_items():
    initialize()
    return _load(KNOWLEDGE_FILE, [])


def load_active_items():
    """Return verified, non-expired items; this is structural filtering only."""

    now = datetime.now(timezone.utc)
    active = []
    for item in load_items():
        if item.get("status") != "verified":
            continue
        expires_at = item.get("expires_at")
        if expires_at:
            try:
                expiry = datetime.fromisoformat(expires_at)
                if expiry.tzinfo is None:
                    expiry = expiry.replace(tzinfo=timezone.utc)
                if expiry <= now:
                    continue
            except (TypeError, ValueError):
                continue
        active.append(item)
    return active


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


def make_id(subject, claim):
    material = (subject.strip().lower() + "\n" + claim.strip().lower()).encode()
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

    if knowledge_type in {"event", "news"} or action == "LOG_ONLY":
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

    valid_for_days = judgment.get("valid_for_days")
    try:
        valid_for_days = int(valid_for_days) if valid_for_days is not None else None
    except (TypeError, ValueError):
        valid_for_days = None
    if valid_for_days is not None:
        valid_for_days = max(1, min(3650, valid_for_days))

    if knowledge_type == "changing" and valid_for_days is None:
        action = "PENDING_REVIEW"

    now = datetime.now(timezone.utc).isoformat()
    item = {
        "id": make_id(candidate.get("subject", ""), candidate.get("claim", "")),
        "subject": str(candidate.get("subject", "")).strip()[:300],
        "claim": str(candidate.get("claim", "")).strip()[:3000],
        "topics": candidate.get("topics", [])[:12],
        "source_url": source.get("url", ""),
        "source_domain": source.get("domain", ""),
        "source_name": source.get("name", ""),
        "published_at": candidate.get("published_at"),
        "learned_at": now,
        "confidence": confidence,
        "knowledge_type": knowledge_type,
        "valid_for_days": valid_for_days,
        "expires_at": (
            (datetime.now(timezone.utc) + timedelta(days=valid_for_days)).isoformat()
            if valid_for_days is not None else None
        ),
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
                _save(KNOWLEDGE_FILE, items)
                return "updated", item
        item["status"] = "pending_review"

    items.append(item)
    _save(KNOWLEDGE_FILE, items)
    return item["status"], item


def apply_curiosity_verification(candidate, verdict, search_result, curiosity_item):
    """Promote only a low-risk claim backed by independent search consensus."""

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

    if (
        verdict.get("decision") != "PROMOTE"
        or str(search_result.get("status") or "").upper() != "OK"
        or judgment.get("consensus") is not True
        or judgment.get("need_more_sources") is True
        or votes < 2
        or len(sources) < 2
    ):
        return "unverified", None

    try:
        confidence = max(0.0, min(1.0, float(verdict.get("confidence") or 0)))
    except (TypeError, ValueError):
        confidence = 0.0
    risk = str(verdict.get("risk") or "high").lower()
    knowledge_type = str(verdict.get("knowledge_type") or "event").lower()
    claim = str(verdict.get("canonical_claim") or "").strip()[:3000]
    subject = str(verdict.get("subject") or candidate.get("subject") or "").strip()[:300]
    if (
        risk != "low"
        or confidence < 0.85
        or knowledge_type not in {"stable", "changing"}
        or not claim
        or not subject
    ):
        return "unverified", None

    valid_for_days = verdict.get("valid_for_days")
    try:
        valid_for_days = int(valid_for_days) if valid_for_days is not None else None
    except (TypeError, ValueError):
        valid_for_days = None
    if valid_for_days is not None:
        valid_for_days = max(1, min(3650, valid_for_days))
    if knowledge_type == "changing" and valid_for_days is None:
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
        "id": make_id(subject, claim),
        "subject": subject,
        "claim": claim,
        "topics": topics,
        "source_url": sources[0]["url"],
        "source_domain": sources[0]["domain"],
        "source_name": sources[0]["title"],
        "sources": sources,
        "published_at": None,
        "learned_at": now,
        "confidence": confidence,
        "knowledge_type": knowledge_type,
        "valid_for_days": valid_for_days,
        "expires_at": (
            (datetime.now(timezone.utc) + timedelta(days=valid_for_days)).isoformat()
            if valid_for_days is not None else None
        ),
        "risk": "low",
        "status": "verified",
        "judge_reason": str(verdict.get("reason") or "")[:500],
        "verification_status": "MULTI_SOURCE_CONSENSUS",
        "verification": {
            "query": str(search_result.get("query") or "")[:1000],
            "canonical_answer": str(judgment.get("canonical_answer") or "")[:2000],
            "votes": votes,
            "independent_source_count": len(sources),
        },
        "provenance": {
            "origin": "nerv_curiosity",
            "curiosity_id": str(curiosity_item.get("id") or "")[:120],
            "external_ai_role": "hypothesis_only",
            "external_ai_status": "UNVERIFIED_EXTERNAL_AI",
        },
        "lifecycle_version": KNOWLEDGE_LIFECYCLE_VERSION,
    }

    items = load_items()
    for index, existing in enumerate(items):
        if existing.get("id") != item["id"]:
            continue
        if existing.get("status") == "verified":
            return "duplicate", existing
        item["created_at"] = existing.get(
            "created_at", existing.get("learned_at", now)
        )
        item["updated_at"] = now
        items[index] = item
        _save(KNOWLEDGE_FILE, items)
        return "verified", item

    items.append(item)
    _save(KNOWLEDGE_FILE, items)
    return "verified", item


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

        if action == "REMOVE_LONG_TERM" or knowledge_type in {"event", "news"}:
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
            days = decision.get("valid_for_days")
            try:
                days = int(days) if days is not None else None
            except (TypeError, ValueError):
                days = None
            if knowledge_type == "changing" and days:
                days = max(1, min(3650, days))
                item["valid_for_days"] = days
                item["expires_at"] = (now + timedelta(days=days)).isoformat()
            counts["kept"] += 1
        kept_items.append(item)

    _save(KNOWLEDGE_FILE, kept_items)
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
