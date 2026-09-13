"""Bounded visual-evidence enrichment for active legacy Knowledge claims."""

import hashlib
import ipaddress
import json
import os
import re
from copy import deepcopy
from datetime import datetime, timedelta, timezone
from urllib.parse import urlparse

import knowledge
import knowledge_evidence
import sqlite_storage
import tools


KNOWLEDGE_LEGACY_VISUAL_BACKFILL_CONTRACT_VERSION = 1
MAX_CLAIMS_PER_RUN = 1
MAX_SOURCES_PER_CLAIM = 2
MAX_TRACKED_ATTEMPTS = 2048
READ_RETRY_DAYS = 7
INVALID_RETRY_DAYS = 30
NO_IMAGE_RETRY_DAYS = 90
NO_SUPPORT_RETRY_DAYS = 180

_SAFE_ATTEMPT_KEY = re.compile(r"^backfill_[0-9a-f]{24}$")

_PROPOSAL_SCHEMA = {
    "type": "object",
    "properties": {
        "decision": {"type": "string", "enum": ["ATTACH", "SKIP"]},
        "knowledge_id": {"type": "string", "minLength": 1},
        "claim_fingerprint": {"type": "string", "minLength": 64},
        "evidence_excerpt": {"type": "string"},
        "image_indexes": {
            "type": "array",
            "items": {"type": "integer", "minimum": 1, "maximum": 2},
            "maxItems": 2,
        },
        "visual_observation": {"type": "string"},
        "reason": {"type": "string"},
    },
    "required": [
        "decision",
        "knowledge_id",
        "claim_fingerprint",
        "evidence_excerpt",
        "image_indexes",
        "visual_observation",
        "reason",
    ],
    "additionalProperties": False,
}

_VERIFIER_SCHEMA = {
    "type": "object",
    "properties": {
        "decision": {"type": "string", "enum": ["APPROVE", "REJECT"]},
        "knowledge_id": {"type": "string", "minLength": 1},
        "claim_fingerprint": {"type": "string", "minLength": 64},
        "proposal_fingerprint": {"type": "string", "minLength": 64},
        "reason": {"type": "string"},
    },
    "required": [
        "decision",
        "knowledge_id",
        "claim_fingerprint",
        "proposal_fingerprint",
        "reason",
    ],
    "additionalProperties": False,
}


def _now_utc(now=None):
    value = now or datetime.now(timezone.utc)
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def _canonical(value):
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )


def _fingerprint(value):
    return hashlib.sha256(_canonical(value).encode("utf-8")).hexdigest()


def _state_file():
    return os.path.join(
        knowledge.DATA_DIR,
        "knowledge",
        "media",
        "backfill.json",
    )


def _empty_state():
    return {
        "schema_version": KNOWLEDGE_LEGACY_VISUAL_BACKFILL_CONTRACT_VERSION,
        "revision": 0,
        "updated_at": None,
        "attempts": {},
    }


def load_state():
    path = _state_file()
    value = sqlite_storage.load_document(
        "knowledge",
        sqlite_storage.document_key_for(path),
        path,
        _empty_state(),
        migration_backup_suffix=(
            sqlite_storage.PHASE_TWO_MIGRATION_BACKUP_SUFFIX
        ),
    )
    if not isinstance(value, dict):
        return _empty_state()
    attempts = value.get("attempts")
    value["attempts"] = attempts if isinstance(attempts, dict) else {}
    value["schema_version"] = (
        KNOWLEDGE_LEGACY_VISUAL_BACKFILL_CONTRACT_VERSION
    )
    return value


def _save_state(value):
    path = _state_file()
    sqlite_storage.save_document(
        "knowledge",
        sqlite_storage.document_key_for(path),
        path,
        value,
        migration_backup_suffix=(
            sqlite_storage.PHASE_TWO_MIGRATION_BACKUP_SUFFIX
        ),
    )


def _parse_utc(value):
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


def _attempt_key(knowledge_id, source_id):
    material = str(knowledge_id or "") + "\n" + str(source_id or "")
    return "backfill_" + hashlib.sha256(material.encode("utf-8")).hexdigest()[:24]


def _retry_days(status):
    return {
        "READ_ERROR": READ_RETRY_DAYS,
        "PROCESSING_ERROR": INVALID_RETRY_DAYS,
        "PROPOSAL_INVALID": INVALID_RETRY_DAYS,
        "ATTACH_REJECTED": INVALID_RETRY_DAYS,
        "NO_IMAGES": NO_IMAGE_RETRY_DAYS,
        "PROPOSAL_SKIPPED": NO_SUPPORT_RETRY_DAYS,
        "VERIFIER_REJECTED": NO_SUPPORT_RETRY_DAYS,
    }.get(str(status or "").upper())


def _record_attempt(
    state,
    knowledge_id,
    claim_fingerprint,
    source,
    status,
    *,
    now=None,
    reason_code="",
):
    current = _now_utc(now)
    source_info = knowledge_evidence.compact_source(source)
    source_id = str(source_info.get("source_id") or "")
    key = _attempt_key(knowledge_id, source_id)
    retry_days = _retry_days(status)
    attempts = state.setdefault("attempts", {})
    previous = attempts.get(key)
    previous = previous if isinstance(previous, dict) else {}
    try:
        attempt_count = max(0, int(previous.get("attempt_count") or 0)) + 1
    except (TypeError, ValueError):
        attempt_count = 1
    attempts[key] = {
        "knowledge_id": str(knowledge_id or "")[:160],
        "claim_fingerprint": str(claim_fingerprint or "")[:64],
        "source_id": source_id[:80],
        "source_domain": str(source_info.get("domain") or "")[:200],
        "status": str(status or "PROCESSING_ERROR").upper()[:40],
        "reason_code": str(reason_code or "")[:80] or None,
        "attempt_count": attempt_count,
        "last_attempt_at": current.isoformat(),
        "next_attempt_at": (
            (current + timedelta(days=retry_days)).isoformat()
            if retry_days is not None else None
        ),
    }
    if len(attempts) > MAX_TRACKED_ATTEMPTS:
        attempts = dict(list(attempts.items())[-MAX_TRACKED_ATTEMPTS:])
        state["attempts"] = attempts
    state["revision"] = int(state.get("revision") or 0) + 1
    state["updated_at"] = current.isoformat()
    _save_state(state)


def _attempt_ready(state, knowledge_id, source_id, now=None):
    key = _attempt_key(knowledge_id, source_id)
    previous = state.get("attempts", {}).get(key)
    if not isinstance(previous, dict):
        return True
    if str(previous.get("status") or "").upper() == "ATTACHED":
        return False
    next_attempt = _parse_utc(previous.get("next_attempt_at"))
    return next_attempt is None or _now_utc(now) >= next_attempt


def _has_image_evidence(item):
    bundle = item.get("evidence_bundle")
    bundle = bundle if isinstance(bundle, dict) else {}
    return any(
        isinstance(record, dict) and record.get("modality") == "IMAGE"
        for record in bundle.get("records", [])
    )


def _source_candidates(item):
    raw_sources = [
        deepcopy(value) for value in item.get("sources", [])
        if isinstance(value, dict)
    ]
    if not raw_sources and item.get("source_url"):
        raw_sources.append({
            "title": item.get("source_name"),
            "name": item.get("source_name"),
            "url": item.get("source_url"),
            "domain": item.get("source_domain"),
        })
    output = []
    seen = set()
    for source in raw_sources:
        url = str(source.get("url") or "").strip()
        try:
            parsed = urlparse(url)
            port = parsed.port
        except ValueError:
            continue
        if (
            parsed.scheme.lower() != "https"
            or not parsed.hostname
            or parsed.username
            or parsed.password
            or port not in {None, 443}
            or not knowledge_evidence.is_public_source(source)
        ):
            continue
        hostname = parsed.hostname.lower()
        if hostname == "localhost" or hostname.endswith(
            (".local", ".internal", ".localhost")
        ):
            continue
        try:
            if not ipaddress.ip_address(hostname).is_global:
                continue
        except ValueError:
            pass
        source["url"] = parsed._replace(
            params="", query="", fragment=""
        ).geturl()
        source.setdefault("name", source.get("title") or parsed.hostname)
        source.setdefault("title", source.get("name") or parsed.hostname)
        source.setdefault("domain", parsed.hostname.lower().removeprefix("www."))
        compact = knowledge_evidence.compact_source(source)
        source_id = str(compact.get("source_id") or "")
        if not source_id or source_id in seen:
            continue
        seen.add(source_id)
        output.append(source)
        if len(output) >= MAX_SOURCES_PER_CLAIM:
            break
    return output


def eligible_candidates(*, state=None, now=None, limit=200):
    """Return active claims with no image and a due, already-bound HTTPS source."""

    state = state if isinstance(state, dict) else load_state()
    candidates = []
    for item in knowledge.load_active_items():
        if (
            not isinstance(item, dict)
            or item.get("status") != "verified"
            or not str(item.get("id") or "").strip()
            or not str(item.get("subject") or "").strip()
            or not str(item.get("claim") or "").strip()
            or _has_image_evidence(item)
        ):
            continue
        sources = []
        for source in _source_candidates(item):
            source_id = str(
                knowledge_evidence.compact_source(source).get("source_id") or ""
            )
            if _attempt_ready(state, item.get("id"), source_id, now=now):
                sources.append(source)
        if not sources:
            continue
        candidates.append({
            "item": item,
            "claim_fingerprint": knowledge.visual_backfill_claim_fingerprint(
                item
            ),
            "sources": sources,
            "legacy_first": 0 if not item.get("evidence_bundle") else 1,
        })
    candidates.sort(key=lambda value: (
        value["legacy_first"],
        str(value["item"].get("learned_at") or ""),
        str(value["item"].get("id") or ""),
    ))
    try:
        bounded = max(0, min(200, int(limit)))
    except (TypeError, ValueError):
        bounded = 200
    return candidates[:bounded]


def _normalize_indexes(values, image_count):
    output = []
    for raw in values if isinstance(values, list) else []:
        if isinstance(raw, bool):
            continue
        try:
            index = int(raw)
        except (TypeError, ValueError):
            continue
        if 1 <= index <= image_count and index not in output:
            output.append(index)
        if len(output) >= 2:
            break
    return output


def _normalized_proposal(value, knowledge_id, claim_fingerprint, image_count):
    value = value if isinstance(value, dict) else {}
    return {
        "decision": str(value.get("decision") or "").upper(),
        "knowledge_id": str(value.get("knowledge_id") or "")[:160],
        "claim_fingerprint": str(value.get("claim_fingerprint") or "")[:64],
        "evidence_excerpt": " ".join(
            str(value.get("evidence_excerpt") or "").split()
        )[:2400],
        "image_indexes": _normalize_indexes(
            value.get("image_indexes"), image_count
        ),
        "visual_observation": " ".join(
            str(value.get("visual_observation") or "").split()
        )[:1200],
        "reason": " ".join(str(value.get("reason") or "").split())[:500],
        "binding_valid": (
            str(value.get("knowledge_id") or "") == knowledge_id
            and str(value.get("claim_fingerprint") or "")
            == claim_fingerprint
        ),
    }


def proposal_fingerprint(proposal):
    value = dict(proposal) if isinstance(proposal, dict) else {}
    value.pop("binding_valid", None)
    return _fingerprint(value)


def _empty_result():
    return {
        "contract_version": KNOWLEDGE_LEGACY_VISUAL_BACKFILL_CONTRACT_VERSION,
        "status": "NO_ELIGIBLE",
        "eligible_claims": 0,
        "claims_attempted": 0,
        "sources_checked": 0,
        "images_captured": 0,
        "proposal_calls": 0,
        "verification_calls": 0,
        "claims_attached": 0,
        "deferred_sources": 0,
        "errors": 0,
        "attached_knowledge_ids": [],
    }


def run_once(
    *,
    reader,
    ai_prompt=tools.run_ai_prompt,
    limit=MAX_CLAIMS_PER_RUN,
    now=None,
):
    """Attempt bounded enrichment without changing any existing claim text."""

    state = load_state()
    candidates = eligible_candidates(state=state, now=now)
    result = _empty_result()
    result["eligible_claims"] = len(candidates)
    try:
        bounded_limit = max(0, min(MAX_CLAIMS_PER_RUN, int(limit)))
    except (TypeError, ValueError):
        bounded_limit = MAX_CLAIMS_PER_RUN
    if not candidates or bounded_limit == 0:
        return result

    for candidate in candidates[:bounded_limit]:
        item = candidate["item"]
        knowledge_id = str(item.get("id") or "")
        claim_fingerprint = candidate["claim_fingerprint"]
        result["claims_attempted"] += 1
        attached = False
        for source in candidate["sources"][:MAX_SOURCES_PER_CLAIM]:
            source_info = knowledge_evidence.compact_source(source)
            source_id = str(source_info.get("source_id") or "")
            result["sources_checked"] += 1
            try:
                page_text = reader(source, include_images=True)
            except Exception as error:
                result["errors"] += 1
                result["deferred_sources"] += 1
                _record_attempt(
                    state,
                    knowledge_id,
                    claim_fingerprint,
                    source,
                    "READ_ERROR",
                    now=now,
                    reason_code=type(error).__name__,
                )
                continue
            try:
                page_images = [
                    str(value or "")
                    for value in source.get("_page_images", [])[:2]
                ] if isinstance(source.get("_page_images"), list) else []
                image_labels = [
                    " ".join(str(value or "").split())[:120]
                    for value in source.get("_page_image_labels", [])[:2]
                ] if isinstance(source.get("_page_image_labels"), list) else []
                image_urls = [
                    str(value or "")[:2000]
                    for value in source.get("_page_image_urls", [])[:2]
                ] if isinstance(source.get("_page_image_urls"), list) else []
                while len(image_labels) < len(page_images):
                    image_labels.append(
                        "Source page image " + str(len(image_labels) + 1)
                    )
                while len(image_urls) < len(page_images):
                    image_urls.append("")
                result["images_captured"] += len(page_images)
                if not page_images:
                    result["deferred_sources"] += 1
                    _record_attempt(
                        state,
                        knowledge_id,
                        claim_fingerprint,
                        source,
                        "NO_IMAGES",
                        now=now,
                    )
                    continue

                image_catalog = [
                    {"index": index, "label": label}
                    for index, label in enumerate(image_labels, start=1)
                ]
                proposal_raw = ai_prompt(
                    "prompts/knowledge_legacy_visual_backfill.txt",
                    _canonical({
                        "fixed_existing_claim": {
                            "knowledge_id": knowledge_id,
                            "claim_fingerprint": claim_fingerprint,
                            "subject": str(item.get("subject") or "")[:300],
                            "claim": str(item.get("claim") or "")[:3000],
                            "knowledge_type": str(
                                item.get("knowledge_type") or "stable"
                            )[:30],
                            "temporal_scope": item.get("temporal_scope")
                            if isinstance(item.get("temporal_scope"), dict)
                            else {},
                        },
                        "bound_public_source": source_info,
                        "source_image_catalog": image_catalog,
                        "source_text": str(page_text or "")[:30000],
                    }),
                    expect_json=True,
                    num_ctx=8192,
                    num_predict=600,
                    think=False,
                    model_name="gemma4:12b",
                    json_schema=_PROPOSAL_SCHEMA,
                    images=page_images,
                )
                result["proposal_calls"] += 1
                proposal = _normalized_proposal(
                    proposal_raw,
                    knowledge_id,
                    claim_fingerprint,
                    len(page_images),
                )
                if (
                    not proposal["binding_valid"]
                    or proposal["decision"] not in {"ATTACH", "SKIP"}
                ):
                    result["errors"] += 1
                    result["deferred_sources"] += 1
                    _record_attempt(
                        state,
                        knowledge_id,
                        claim_fingerprint,
                        source,
                        "PROPOSAL_INVALID",
                        now=now,
                        reason_code="binding_or_decision_invalid",
                    )
                    continue
                if proposal["decision"] == "SKIP":
                    result["deferred_sources"] += 1
                    _record_attempt(
                        state,
                        knowledge_id,
                        claim_fingerprint,
                        source,
                        "PROPOSAL_SKIPPED",
                        now=now,
                    )
                    continue
                if (
                    not proposal["evidence_excerpt"]
                    or not proposal["image_indexes"]
                    or not proposal["visual_observation"]
                ):
                    result["errors"] += 1
                    result["deferred_sources"] += 1
                    _record_attempt(
                        state,
                        knowledge_id,
                        claim_fingerprint,
                        source,
                        "PROPOSAL_INVALID",
                        now=now,
                        reason_code="evidence_fields_missing",
                    )
                    continue

                seed_candidate = {
                    "subject": item.get("subject"),
                    "claim": item.get("claim"),
                    "evidence_excerpt": proposal["evidence_excerpt"],
                    "evidence": {
                        "modality": "TEXT_AND_IMAGE",
                        "image_indexes": proposal["image_indexes"],
                        "visual_observation": proposal[
                            "visual_observation"
                        ],
                    },
                }
                evidence_seed = knowledge_evidence.autonomous_evidence_seed(
                    source,
                    page_text,
                    seed_candidate,
                    page_images,
                    image_labels,
                    image_urls,
                )
                if not isinstance(evidence_seed, dict) or not any(
                    isinstance(record, dict)
                    and record.get("modality") == "IMAGE"
                    for record in evidence_seed.get("records", [])
                ):
                    result["errors"] += 1
                    result["deferred_sources"] += 1
                    _record_attempt(
                        state,
                        knowledge_id,
                        claim_fingerprint,
                        source,
                        "PROPOSAL_INVALID",
                        now=now,
                        reason_code="literal_or_image_evidence_invalid",
                    )
                    continue

                proposal_hash = proposal_fingerprint(proposal)
                selected_images = [
                    page_images[index - 1]
                    for index in proposal["image_indexes"]
                ]
                verification_raw = ai_prompt(
                    "prompts/knowledge_legacy_visual_backfill_verify.txt",
                    _canonical({
                        "fixed_existing_claim": {
                            "knowledge_id": knowledge_id,
                            "claim_fingerprint": claim_fingerprint,
                            "subject": str(item.get("subject") or "")[:300],
                            "claim": str(item.get("claim") or "")[:3000],
                        },
                        "bound_public_source": source_info,
                        "proposal_fingerprint": proposal_hash,
                        "literal_evidence_excerpt": proposal[
                            "evidence_excerpt"
                        ],
                        "visual_observation": proposal[
                            "visual_observation"
                        ],
                        "selected_source_image_indexes": proposal[
                            "image_indexes"
                        ],
                    }),
                    expect_json=True,
                    num_ctx=4096,
                    num_predict=300,
                    think=False,
                    model_name="gemma4:12b",
                    json_schema=_VERIFIER_SCHEMA,
                    images=selected_images,
                )
                result["verification_calls"] += 1
                verification = (
                    verification_raw if isinstance(verification_raw, dict)
                    else {}
                )
                valid_verification = (
                    str(verification.get("knowledge_id") or "")
                    == knowledge_id
                    and str(verification.get("claim_fingerprint") or "")
                    == claim_fingerprint
                    and str(verification.get("proposal_fingerprint") or "")
                    == proposal_hash
                    and str(verification.get("decision") or "").upper()
                    in {"APPROVE", "REJECT"}
                )
                if not valid_verification:
                    result["errors"] += 1
                    result["deferred_sources"] += 1
                    _record_attempt(
                        state,
                        knowledge_id,
                        claim_fingerprint,
                        source,
                        "PROPOSAL_INVALID",
                        now=now,
                        reason_code="verification_binding_invalid",
                    )
                    continue
                if str(verification.get("decision") or "").upper() != "APPROVE":
                    result["deferred_sources"] += 1
                    _record_attempt(
                        state,
                        knowledge_id,
                        claim_fingerprint,
                        source,
                        "VERIFIER_REJECTED",
                        now=now,
                    )
                    continue

                attach_status, _updated = (
                    knowledge.attach_visual_evidence_to_existing_claim(
                        knowledge_id,
                        claim_fingerprint,
                        source_id,
                        evidence_seed,
                        attached_at=_now_utc(now).isoformat(),
                    )
                )
                if attach_status != "attached":
                    result["errors"] += 1
                    result["deferred_sources"] += 1
                    _record_attempt(
                        state,
                        knowledge_id,
                        claim_fingerprint,
                        source,
                        "ATTACH_REJECTED",
                        now=now,
                        reason_code=attach_status,
                    )
                    continue
                _record_attempt(
                    state,
                    knowledge_id,
                    claim_fingerprint,
                    source,
                    "ATTACHED",
                    now=now,
                )
                result["claims_attached"] += 1
                result["attached_knowledge_ids"].append(knowledge_id[:160])
                attached = True
                break
            except Exception as error:
                result["errors"] += 1
                result["deferred_sources"] += 1
                _record_attempt(
                    state,
                    knowledge_id,
                    claim_fingerprint,
                    source,
                    "PROCESSING_ERROR",
                    now=now,
                    reason_code=type(error).__name__,
                )
            finally:
                for key in (
                    "_page_images",
                    "_page_image_labels",
                    "_page_image_urls",
                ):
                    source.pop(key, None)
        if attached:
            continue

    if result["claims_attached"]:
        result["status"] = "ATTACHED"
    elif result["errors"]:
        result["status"] = "COMPLETED_WITH_ERRORS"
    else:
        result["status"] = "NO_ATTACHMENT"
    return result


def audit_state(state=None):
    """Read-only structural audit for the bounded operational backfill ledger."""

    value = state if isinstance(state, dict) else load_state()
    failures = []
    if value.get("schema_version") != (
        KNOWLEDGE_LEGACY_VISUAL_BACKFILL_CONTRACT_VERSION
    ):
        failures.append("schema_version_invalid")
    attempts = value.get("attempts")
    if not isinstance(attempts, dict):
        return {"attempts": 0, "failures": ["attempts_invalid"]}
    if len(attempts) > MAX_TRACKED_ATTEMPTS:
        failures.append("attempts_unbounded")
    serialized = _canonical(value)
    if "_image_payloads" in serialized or "data:image/" in serialized:
        failures.append("raw_image_payload_present")
    if "relative_path" in serialized or "resolved_path" in serialized:
        failures.append("local_path_present")
    for key, attempt in attempts.items():
        if not _SAFE_ATTEMPT_KEY.fullmatch(str(key or "")):
            failures.append("attempt_key_invalid:" + str(key)[:80])
        if not isinstance(attempt, dict):
            failures.append("attempt_invalid:" + str(key)[:80])
            continue
        if not str(attempt.get("knowledge_id") or ""):
            failures.append("knowledge_id_missing:" + str(key)[:80])
        if not re.fullmatch(
            r"[0-9a-f]{64}",
            str(attempt.get("claim_fingerprint") or ""),
        ):
            failures.append("claim_fingerprint_invalid:" + str(key)[:80])
        if not str(attempt.get("source_id") or "").startswith("source_"):
            failures.append("source_id_invalid:" + str(key)[:80])
    return {"attempts": len(attempts), "failures": failures}
