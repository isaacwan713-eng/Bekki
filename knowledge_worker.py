"""Run one profile-guided Bekki Knowledge V1 learning cycle."""

import json
import os
from datetime import datetime, timezone
from urllib.parse import urlparse

import knowledge
import knowledge_ai
import knowledge_autonomy
import knowledge_evidence
import knowledge_visual_backfill
import memory
import tools
from nerv.curiosity import CuriosityJournal
from nerv.knowledge_curator import (
    CURATOR_ISOLATION_CONTRACT_VERSION,
    CURATOR_PLAN_CONTRACT_VERSION,
    KnowledgeCurator,
)
from nerv.topic_lifecycle import (
    TOPIC_LIFECYCLE_ISOLATION_CONTRACT_VERSION,
    TopicLifecycleManager,
)


MAX_SOURCES_PER_RUN = 5
MAX_ITEMS_PER_SOURCE = 4
MAX_SOURCE_REVIEWS_PER_PHASE = 8
MAX_DISCOVERY_CANDIDATES_PER_PHASE = 6
SOURCE_READ_RETRY_HOURS = 24
SOURCE_RECOVERY_CONTRACT_VERSION = 1
KNOWLEDGE_JUDGE_ISOLATION_CONTRACT_VERSION = 1
AUTONOMOUS_VISUAL_EVIDENCE_CONTRACT_VERSION = 1
KNOWLEDGE_WORKER_VERSION = "1.4.8-legacy-visual-backfill"

_AUTONOMOUS_EXTRACTION_SCHEMA = {
    "type": "object",
    "properties": {
        "items": {
            "type": "array",
            "maxItems": MAX_ITEMS_PER_SOURCE,
            "items": {
                "type": "object",
                "properties": {
                    "subject": {"type": "string", "minLength": 1},
                    "claim": {"type": "string", "minLength": 1},
                    "evidence_excerpt": {"type": "string", "minLength": 1},
                    "topics": {"type": "array", "items": {"type": "string"}},
                    "published_at": {
                        "anyOf": [{"type": "string"}, {"type": "null"}],
                    },
                    "knowledge_type": {
                        "type": "string",
                        "enum": ["stable", "reviewable", "event", "news"],
                    },
                    "lifecycle_basis": {
                        "type": "string",
                        "enum": [
                            "FIXED_HISTORY",
                            "DURABLE_EXPLANATION_DEFINITION_OR_MECHANISM",
                            "MAINTAINED_SET_OR_STRUCTURE",
                            "TRANSIENT_CURRENT_STATE_OR_EVENT",
                        ],
                    },
                    "suggested_valid_for_days": {
                        "anyOf": [
                            {"type": "integer", "minimum": 1, "maximum": 3650},
                            {"type": "null"},
                        ],
                    },
                    "temporal_scope": {"type": "object"},
                    "confidence": {"type": "number", "minimum": 0, "maximum": 1},
                    "risk": {
                        "type": "string",
                        "enum": ["low", "medium", "high"],
                    },
                    "evidence": {
                        "type": "object",
                        "properties": {
                            "modality": {
                                "type": "string",
                                "enum": ["TEXT", "TEXT_AND_IMAGE"],
                            },
                            "image_indexes": {
                                "type": "array",
                                "items": {"type": "integer", "minimum": 1, "maximum": 2},
                                "maxItems": 2,
                            },
                            "visual_observation": {"type": "string"},
                        },
                        "required": [
                            "modality", "image_indexes", "visual_observation",
                        ],
                        "additionalProperties": False,
                    },
                },
                "required": [
                    "subject", "claim", "evidence_excerpt", "topics",
                    "published_at", "knowledge_type", "lifecycle_basis",
                    "suggested_valid_for_days", "temporal_scope",
                    "confidence", "risk", "evidence",
                ],
                "additionalProperties": False,
            },
        },
    },
    "required": ["items"],
    "additionalProperties": False,
}

_OFFICIAL_TEXT_SIGNALS = (
    "official", "公式", "官网", "government", "university",
    "documentation", "docs", "primary source",
)
_LOW_ACCOUNTABILITY_DOMAIN_SIGNALS = (
    "fandom.com", "grokipedia.com", "namu.wiki", "generasia.com",
)
_ESTABLISHED_REFERENCE_DOMAINS = (
    "britannica.com", "reuters.com", "apnews.com", "bbc.com",
    "nhk.or.jp", "who.int", "wikipedia.org",
)


def _use_project_directory():
    """Make relative data/prompt paths stable under Windows Task Scheduler."""

    project_directory = os.path.dirname(os.path.abspath(__file__))
    os.chdir(project_directory)


def profile_context():
    data = memory.initialize_memory().get("profile", {})
    relevant = {
        "profile": data.get("profile", []),
        "preference": data.get("preference", []),
    }
    return json.dumps(relevant, ensure_ascii=False, indent=2)


def _topic_key(value):
    return "".join(
        character
        for character in str(value or "").casefold()
        if character.isalnum()
    )


def derive_topics(limit=12, excluded_topic_ids=None):
    catalog = knowledge.load_topic_catalog(
        include_claims=False,
        max_topics=80,
    )
    due_topic_ids = {
        str(item.get("topic_id") or "")
        for item in knowledge.load_topic_refresh_candidates(limit=12)
        if isinstance(item, dict)
    }
    topic_lifecycle = [
        {
            "topic_id": str(item.get("topic_id") or "")[:80],
            "title": str(item.get("title") or "")[:200],
            "classification": item.get("classification")
            if isinstance(item.get("classification"), dict) else {},
            "lifecycle": item.get("lifecycle")
            if isinstance(item.get("lifecycle"), dict) else {},
            "refresh_due": str(item.get("topic_id") or "") in due_topic_ids,
        }
        for item in catalog
        if isinstance(item, dict)
    ]
    excluded = {
        str(value or "").strip().lower()
        for value in excluded_topic_ids or []
        if str(value or "").strip()
    }
    blocked_keys = set()
    for item in catalog:
        if not isinstance(item, dict):
            continue
        topic_id = str(item.get("topic_id") or "").strip().lower()
        lifecycle = item.get("lifecycle")
        lifecycle = lifecycle if isinstance(lifecycle, dict) else {}
        blocked = topic_id in excluded or (
            lifecycle.get("state") == "PAUSED_COMPLETE"
            and topic_id not in due_topic_ids
        )
        if not blocked:
            continue
        for raw in [
            topic_id,
            item.get("title"),
            *item.get("aliases", []),
        ]:
            key = _topic_key(raw)
            if key:
                blocked_keys.add(key)

    result = tools.run_ai_prompt(
        "prompts/knowledge_topics.txt",
        json.dumps(
            {
                "profile_and_preferences": json.loads(profile_context()),
                "existing_topic_lifecycle": topic_lifecycle,
            },
            ensure_ascii=False,
            separators=(",", ":"),
        ),
        expect_json=True,
        num_ctx=3072,
        num_predict=240,
    )
    if not isinstance(result, dict) or not isinstance(result.get("topics"), list):
        return []
    selected = list(dict.fromkeys(
        str(topic).lower().strip()[:80]
        for topic in result["topics"]
        if str(topic).strip() and _topic_key(topic) not in blocked_keys
    ))
    return selected[:max(0, min(12, int(limit)))]


def plan_autonomous_learning(
    *,
    trigger="status",
    background_interval_days=(
        knowledge_autonomy.DEFAULT_BACKGROUND_INTERVAL_DAYS
    ),
    force=False,
    now=None,
    open_topic_ids=None,
):
    """Return the one shared plan used by desktop and scheduled triggers."""

    del trigger
    if open_topic_ids is None:
        curiosity = CuriosityJournal(
            tools.run_ai_prompt,
            unload_model=tools.unload_model,
        )
        open_topic_ids = curiosity.open_topic_ids()
    catalog = knowledge.load_topic_catalog(
        include_claims=False,
        max_topics=200,
    )
    refresh = knowledge.load_topic_refresh_candidates(
        now=now,
        exclude_topic_ids=open_topic_ids,
        limit=200,
    )
    plan = knowledge_autonomy.build_plan(
        catalog,
        refresh,
        knowledge.load_learning_logs(),
        now=now,
        background_interval_days=background_interval_days,
        force=force,
        excluded_topic_ids=open_topic_ids,
    )
    plan["excluded_topic_ids"] = sorted({
        str(value or "").strip().lower()
        for value in open_topic_ids or []
        if str(value or "").strip()
    })
    return plan


def autonomy_due(
    background_interval_days=(
        knowledge_autonomy.DEFAULT_BACKGROUND_INTERVAL_DAYS
    ),
    now=None,
):
    """Cheap local due check for either runtime trigger."""

    plan = plan_autonomous_learning(
        background_interval_days=background_interval_days,
        now=now,
    )
    return plan.get("due") is True, plan


def _topics_from_plan(plan):
    """Return stable source-match labels without turning a gap into a fact."""

    output = []
    selected = plan.get("selected_topics", []) if isinstance(plan, dict) else []
    for item in selected:
        if not isinstance(item, dict):
            continue
        for raw in [item.get("title"), *item.get("aliases", [])]:
            value = " ".join(str(raw or "").split())[:120]
            if value and value.casefold() not in {
                current.casefold() for current in output
            }:
                output.append(value)
        if output:
            break
    return output[:4]


def _research_queries(topics, plan):
    selected = plan.get("selected_topics", []) if isinstance(plan, dict) else []
    if selected and isinstance(selected[0], dict):
        item = selected[0]
        title = str(item.get("title") or "").strip()
        focus = str(item.get("next_focus") or "").strip()
        query = " ".join(value for value in (title, focus) if value)
        output = []
        for value in (query, title):
            normalized = " ".join(str(value or "").split())[:600]
            if normalized and normalized.casefold() not in {
                current.casefold() for current in output
            }:
                output.append(normalized)
        if output:
            return output[:2]
    return [str(value)[:120] for value in topics[:3] if str(value).strip()]


def organize_learned_knowledge():
    """Finish curation, classification, layering, and topic-state judgment."""

    curiosity = CuriosityJournal(
        tools.run_ai_prompt,
        unload_model=tools.unload_model,
    )
    topic_lifecycle = TopicLifecycleManager(
        tools.run_ai_prompt,
        unload_model=tools.unload_model,
        curiosity_journal=curiosity,
    )
    curator = KnowledgeCurator(
        tools.run_ai_prompt,
        unload_model=tools.unload_model,
        topic_lifecycle=topic_lifecycle,
        curiosity_journal=curiosity,
    )
    return curator.run_once(force=True)


def _normalized_topic_set(values):
    return {
        _topic_key(value)
        for value in values or []
        if _topic_key(value)
    }


def _source_domain(source):
    domain = str((source or {}).get("domain") or "").strip().lower()
    if not domain:
        domain = urlparse(str((source or {}).get("url") or "")).netloc.lower()
    return domain.removeprefix("www.")


def _source_priority(source):
    """Rank discovery candidates only; Source Judge still decides trust."""

    domain = _source_domain(source)
    text = " ".join([
        domain,
        str((source or {}).get("title") or ""),
        str((source or {}).get("name") or ""),
        str((source or {}).get("description") or ""),
    ]).casefold()
    official = any(signal in text for signal in _OFFICIAL_TEXT_SIGNALS)
    institutional = (
        domain.endswith(".gov")
        or ".gov." in domain
        or domain.endswith(".edu")
        or ".edu." in domain
        or domain.endswith(".ac.uk")
        or domain.endswith(".ac.jp")
    )
    established = any(
        domain == value or domain.endswith("." + value)
        for value in _ESTABLISHED_REFERENCE_DOMAINS
    )
    low_accountability = any(
        domain == value or domain.endswith("." + value)
        for value in _LOW_ACCOUNTABILITY_DOMAIN_SIGNALS
    )
    if low_accountability:
        tier = 4
    elif official or institutional:
        tier = 0
    elif established:
        tier = 1
    elif "wiki" in domain:
        tier = 4
    elif domain.endswith(".org"):
        tier = 2
    else:
        tier = 3
    return tier, domain, str((source or {}).get("url") or "")


def choose_sources(topics):
    sources = knowledge.load_sources(approved_only=True)
    ranked = []
    topic_set = _normalized_topic_set(topics)
    for source in sources:
        source_topics = _normalized_topic_set(source.get("topics", []))
        overlap = len(topic_set & source_topics)
        if not overlap:
            continue
        try:
            trust_score = float(source.get("trust_score") or 0.0)
        except (TypeError, ValueError):
            trust_score = 0.0
        ranked.append((
            -overlap,
            _source_priority(source),
            -trust_score,
            source,
        ))
    ranked.sort(key=lambda item: item[:3])
    return [item[3] for item in ranked[:MAX_SOURCES_PER_RUN]]


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


def _candidate_retry_ready(candidate, now=None):
    retry_after = _parse_utc((candidate or {}).get("retry_after"))
    current = now or datetime.now(timezone.utc)
    return retry_after is None or current >= retry_after


def _candidate_needs_review(candidate):
    if str((candidate or {}).get("status") or "").lower() == "candidate":
        return True
    try:
        policy_version = int((candidate or {}).get("policy_version") or 0)
    except (TypeError, ValueError):
        policy_version = 0
    return policy_version < knowledge.SOURCE_POLICY_VERSION


def _rejected_source_domains():
    output = set()
    for item in knowledge.load_source_candidates():
        if not isinstance(item, dict):
            continue
        try:
            policy_version = int(item.get("policy_version") or 0)
        except (TypeError, ValueError):
            policy_version = 0
        if (
            str(item.get("status") or "").lower() == "rejected"
            and policy_version >= knowledge.SOURCE_POLICY_VERSION
        ):
            domain = _source_domain(item)
            if domain:
                output.add(domain)
    return output


def discover_source_candidates(
    topics,
    research_queries=None,
    *,
    phase="PRIMARY",
    blocked_domains=None,
):
    phase = str(phase or "PRIMARY").upper()
    queries = [
        " ".join(str(value or "").split())[:600]
        for value in (research_queries or topics)
        if str(value or "").strip()
    ][:2]
    if not queries:
        return 0
    if phase == "FALLBACK" and len(queries) > 1:
        bases = queries[1:2]
    else:
        bases = queries[:1]
    suffix = (
        " official site primary source"
        if phase == "PRIMARY"
        else " established reference organization history"
    )
    blocked = _rejected_source_domains()
    blocked.update(
        str(value or "").strip().lower()
        for value in blocked_domains or []
        if str(value or "").strip()
    )
    added = 0
    seen_domains = set()
    for query in bases:
        results = tools.search(query + suffix, count=8)
        if not isinstance(results, list):
            print(
                "[KNOWLEDGE SOURCE SEARCH]",
                "phase=" + phase,
                "status=unavailable",
            )
            continue
        for result in sorted(
            (item for item in results if isinstance(item, dict)),
            key=_source_priority,
        ):
            domain = _source_domain(result)
            if not domain or domain in blocked or domain in seen_domains:
                continue
            seen_domains.add(domain)
            if knowledge.add_source_candidate(result, topics[:4]):
                added += 1
            if added >= MAX_DISCOVERY_CANDIDATES_PER_PHASE:
                break
    return added


def read_source(source, *, include_images=False):
    for key in ("_page_images", "_page_image_labels", "_page_image_urls"):
        source.pop(key, None)
    if include_images:
        page = tools.read_page(source["url"], include_images=True)
    else:
        page = tools.read_page(source["url"])
    if not page.get("success") and page.get("reader_type") == "browser_needed":
        page = tools.read_page_with_browser(
            source["url"], include_images=include_images
        )
    if not page.get("success"):
        raise RuntimeError(page.get("error", "Source could not be read."))
    if include_images:
        source["_page_images"] = [
            str(value or "")
            for value in page.get("page_images", [])[:2]
        ] if isinstance(page.get("page_images"), list) else []
        source["_page_image_labels"] = [
            " ".join(str(value or "").split())[:120]
            for value in page.get("page_image_labels", [])[:2]
        ] if isinstance(page.get("page_image_labels"), list) else []
        source["_page_image_urls"] = [
            str(value or "")[:2000]
            for value in page.get("page_image_urls", [])[:2]
        ] if isinstance(page.get("page_image_urls"), list) else []
    return str(page.get("content", ""))[:30000]


def review_source_candidates(
    topics,
    *,
    attempted_urls=None,
    attempted_domains=None,
):
    counts = {"approved": 0, "pending": 0, "rejected": 0, "errors": 0}
    attempted_urls = attempted_urls if attempted_urls is not None else set()
    attempted_domains = (
        attempted_domains if attempted_domains is not None else set()
    )
    relevant_topics = _normalized_topic_set(topics)
    candidates = sorted([
        item for item in knowledge.load_source_candidates()
        if _candidate_needs_review(item)
        and relevant_topics.intersection(
            _normalized_topic_set(item.get("topics", []))
        )
        and _candidate_retry_ready(item)
    ], key=_source_priority)

    reviewed = 0
    for candidate in candidates:
        candidate_tier = _source_priority(candidate)[0]
        if counts["approved"] and candidate_tier >= 3:
            # Once a primary/reference source is approved, do not spend the
            # same cycle retrying generic or low-accountability leftovers.
            break
        url = str(candidate.get("url") or "").strip()
        domain = _source_domain(candidate)
        if (
            not url
            or url in attempted_urls
            or domain in attempted_domains
            or reviewed >= MAX_SOURCE_REVIEWS_PER_PHASE
        ):
            continue
        attempted_urls.add(url)
        if domain:
            attempted_domains.add(domain)
        reviewed += 1
        try:
            page_text = read_source(candidate)
            judgment = knowledge_ai.judge_source(candidate, page_text)
            decision = knowledge.apply_source_judgment(candidate, judgment)
            key = {
                "APPROVE": "approved",
                "PENDING_REVIEW": "pending",
                "REJECT": "rejected",
            }[decision]
            counts[key] += 1
            print("[SOURCE JUDGE]", candidate.get("domain"), decision)
        except Exception as error:
            counts["errors"] += 1
            knowledge.record_source_candidate_failure(
                candidate,
                error,
                retry_after_hours=SOURCE_READ_RETRY_HOURS,
            )
            print("[SOURCE JUDGE ERROR]", candidate.get("url"), repr(error))
    return counts


def _merge_review_counts(*values):
    output = {"approved": 0, "pending": 0, "rejected": 0, "errors": 0}
    for value in values:
        for key in output:
            try:
                output[key] += max(0, int((value or {}).get(key) or 0))
            except (TypeError, ValueError):
                continue
    return output


def extract_candidates(
    source,
    text,
    topics,
    *,
    page_images=None,
    page_image_labels=None,
    page_image_urls=None,
):
    page_images = [
        str(value or "")
        for value in (page_images if isinstance(page_images, list) else [])[:2]
    ]
    page_image_labels = [
        " ".join(str(value or "").split())[:120]
        for value in (
            page_image_labels if isinstance(page_image_labels, list) else []
        )[:len(page_images)]
    ]
    while len(page_image_labels) < len(page_images):
        page_image_labels.append(
            "Source page image " + str(len(page_image_labels) + 1)
        )
    page_image_urls = [
        str(value or "")[:2000]
        for value in (
            page_image_urls if isinstance(page_image_urls, list) else []
        )[:len(page_images)]
    ]
    while len(page_image_urls) < len(page_images):
        page_image_urls.append("")
    source_metadata = knowledge_evidence.compact_source(source)
    source_metadata.update({
        "status": str(source.get("status") or "")[:30],
        "trust": str(source.get("trust") or "")[:60],
        "trust_score": source.get("trust_score"),
        "topics": [
            str(value or "")[:120] for value in source.get("topics", [])[:12]
        ] if isinstance(source.get("topics"), list) else [],
    })
    image_catalog = [
        {"index": index, "label": label or "Source page image"}
        for index, label in enumerate(page_image_labels, start=1)
    ]
    result = tools.run_ai_prompt(
        "prompts/knowledge_extract.txt",
        "Learning topics:\n"
        + json.dumps(topics, ensure_ascii=False)
        + "\n\nSource metadata:\n"
        + json.dumps(source_metadata, ensure_ascii=False, indent=2)
        + "\n\nSource image catalog:\n"
        + json.dumps(image_catalog, ensure_ascii=False, indent=2)
        + "\n\nSource text:\n"
        + text,
        expect_json=True,
        num_ctx=8192,
        num_predict=1000,
        think=False,
        model_name="gemma4:12b",
        json_schema=_AUTONOMOUS_EXTRACTION_SCHEMA,
        images=page_images or None,
    )
    if not isinstance(result, dict) or not isinstance(result.get("items"), list):
        return []
    candidates = []
    for raw in result["items"]:
        if not isinstance(raw, dict):
            continue
        item = dict(raw)
        seed = knowledge_evidence.autonomous_evidence_seed(
            source,
            text,
            item,
            page_images,
            page_image_labels,
            page_image_urls,
        )
        if seed is None:
            print(
                "[KNOWLEDGE EVIDENCE REJECTED]",
                "reason=missing_literal_source_excerpt",
                "subject=" + str(item.get("subject") or "")[:120],
            )
            continue
        item["_evidence_seed"] = seed
        item["_evidence_fingerprint"] = (
            knowledge_evidence.seed_fingerprint(seed)
        )
        candidates.append(item)
        if len(candidates) >= MAX_ITEMS_PER_SOURCE:
            break
    return candidates


def run_learning_cycle(
    topics=None,
    *,
    autonomy_plan=None,
    trigger="manual",
    enable_legacy_visual_backfill=False,
):
    print("[KNOWLEDGE WORKER VERSION]", KNOWLEDGE_WORKER_VERSION)
    knowledge.initialize()
    unaudited = [
        item for item in knowledge.load_items()
        if item.get("lifecycle_version", 0) < knowledge.KNOWLEDGE_LIFECYCLE_VERSION
    ]
    lifecycle_audit = {"kept": 0, "expired": 0, "removed": 0}
    for start in range(0, len(unaudited), 30):
        decisions = knowledge_ai.audit_existing_knowledge(
            unaudited[start:start + 30]
        )
        batch_result = knowledge.apply_lifecycle_audit(decisions)
        for key, value in batch_result.items():
            lifecycle_audit[key] += value
    plan = autonomy_plan if isinstance(autonomy_plan, dict) else {}
    if topics is None:
        topics = _topics_from_plan(plan)
    if not topics:
        topics = derive_topics(
            limit=1,
            excluded_topic_ids=plan.get("excluded_topic_ids", []),
        )
    topics = list(dict.fromkeys(
        " ".join(str(topic or "").split())[:120]
        for topic in topics
        if str(topic or "").strip()
    ))[:4]
    research_queries = _research_queries(topics, plan)
    sources = choose_sources(topics)
    attempted_urls = set()
    attempted_domains = set()
    primary_discovered = 0
    if not sources and topics:
        primary_discovered = discover_source_candidates(
            topics,
            research_queries=research_queries,
            phase="PRIMARY",
        )

    # Review relevant candidates left by any earlier run, regardless of
    # whether other approved sources already exist.
    primary_reviews = review_source_candidates(
        topics,
        attempted_urls=attempted_urls,
        attempted_domains=attempted_domains,
    )
    sources = choose_sources(topics)

    fallback_discovered = 0
    fallback_reviews = {
        "approved": 0, "pending": 0, "rejected": 0, "errors": 0
    }
    if not sources and topics:
        fallback_discovered = discover_source_candidates(
            topics,
            research_queries=research_queries,
            phase="FALLBACK",
            blocked_domains=attempted_domains,
        )
        fallback_reviews = review_source_candidates(
            topics,
            attempted_urls=attempted_urls,
            attempted_domains=attempted_domains,
        )
        sources = choose_sources(topics)
    source_reviews = _merge_review_counts(
        primary_reviews,
        fallback_reviews,
    )
    discovered = primary_discovered + fallback_discovered

    summary = []
    counts = {
        "verified": 0,
        "pending_review": 0,
        "updated": 0,
        "log_only": 0,
        "duplicate": 0,
        "rejected": 0,
        "errors": 0,
    }
    judge_counts = {
        "primary_valid": 0,
        "recovered_valid": 0,
        "invalid_json": 0,
    }
    candidates_extracted = 0
    visual_evidence = {
        "contract_version": AUTONOMOUS_VISUAL_EVIDENCE_CONTRACT_VERSION,
        "sources_with_images": 0,
        "source_images_captured": 0,
        "candidates_with_images": 0,
        "claims_with_persisted_images": 0,
    }
    legacy_visual_backfill = {
        "contract_version": (
            knowledge_visual_backfill.KNOWLEDGE_LEGACY_VISUAL_BACKFILL_CONTRACT_VERSION
        ),
        "status": "SKIPPED",
        "reason": "not_enabled_for_this_entrypoint",
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
    for source in sources:
        try:
            text = read_source(source, include_images=True)
            page_images = source.get("_page_images", [])
            page_image_labels = source.get("_page_image_labels", [])
            page_image_urls = source.get("_page_image_urls", [])
            if page_images:
                visual_evidence["sources_with_images"] += 1
                visual_evidence["source_images_captured"] += len(page_images)
            candidates = extract_candidates(
                source,
                text,
                topics,
                page_images=page_images,
                page_image_labels=page_image_labels,
                page_image_urls=page_image_urls,
            )
            candidates_extracted += len(candidates)
            for candidate in candidates:
                candidate_has_images = any(
                    isinstance(record, dict)
                    and record.get("modality") == "IMAGE"
                    for record in candidate.get("_evidence_seed", {}).get(
                        "records", []
                    )
                )
                if candidate_has_images:
                    visual_evidence["candidates_with_images"] += 1
                judgment = knowledge_ai.judge_knowledge(candidate, source)
                judge_status = str(
                    judgment.get("_judge_output_status") or ""
                ).upper()
                if judge_status == "PRIMARY_VALID":
                    judge_counts["primary_valid"] += 1
                elif judge_status == "RECOVERED_VALID":
                    judge_counts["recovered_valid"] += 1
                elif judge_status == "INVALID_JSON":
                    judge_counts["invalid_json"] += 1
                    counts["errors"] += 1
                result, item = knowledge.apply_knowledge_judgment(
                    candidate,
                    source,
                    judgment,
                )
                counts[result] = counts.get(result, 0) + 1
                if item and result in {
                    "verified", "pending_review", "updated", "log_only"
                }:
                    summary.append(item["claim"])
                if candidate_has_images and item and any(
                    isinstance(record, dict) and record.get("asset_ids")
                    for record in item.get("evidence_bundle", {}).get(
                        "records", []
                    )
                ):
                    visual_evidence["claims_with_persisted_images"] += 1
        except Exception as error:
            counts["errors"] += 1
            print("[KNOWLEDGE SOURCE ERROR]", source.get("url"), repr(error))
        finally:
            for key in (
                "_page_images", "_page_image_labels", "_page_image_urls",
            ):
                source.pop(key, None)

    if enable_legacy_visual_backfill:
        try:
            legacy_visual_backfill = knowledge_visual_backfill.run_once(
                reader=read_source,
            )
        except Exception as error:
            legacy_visual_backfill = dict(legacy_visual_backfill)
            legacy_visual_backfill.update({
                "status": "COMPLETED_WITH_ERRORS",
                "reason": type(error).__name__,
                "errors": 1,
            })
            print("[KNOWLEDGE VISUAL BACKFILL ERROR]", repr(error))

    try:
        organization = organize_learned_knowledge()
    except Exception as error:
        organization = {
            "status": "FAILED",
            "error": type(error).__name__,
            "detail": str(error)[:500],
        }
        print("[KNOWLEDGE ORGANIZATION ERROR]", repr(error))

    verified_evidence_count = sum(
        counts.get(key, 0)
        for key in ("verified", "updated", "duplicate", "log_only")
    ) + int(legacy_visual_backfill.get("claims_attached") or 0)
    if verified_evidence_count == 0:
        status = "NO_VERIFIED_EVIDENCE"
        if judge_counts["invalid_json"]:
            outcome_reason = (
                "Approved sources produced candidates, but Knowledge Judge "
                "returned no valid candidate-anchored JSON after recovery."
            )
        elif candidates_extracted and counts["pending_review"]:
            outcome_reason = (
                "Approved sources produced candidates, but all remained "
                "pending review."
            )
        elif sources and candidates_extracted == 0:
            outcome_reason = (
                "Approved sources were readable, but extraction produced no "
                "usable candidate knowledge."
            )
        elif not sources:
            outcome_reason = "No approved readable source was available."
        else:
            outcome_reason = "No source-backed candidate was verified."
    elif (
        counts["errors"]
        or source_reviews["errors"]
        or legacy_visual_backfill.get("errors")
        or organization.get("status") not in {"COMPLETED", "SKIPPED"}
    ):
        status = "COMPLETED_WITH_ERRORS"
        outcome_reason = "Verified evidence was retained despite bounded errors."
    else:
        status = "COMPLETED"
        outcome_reason = "At least one source-backed outcome was verified."
    log = {
        "autonomy_contract_version": (
            knowledge_autonomy.AUTONOMY_CONTRACT_VERSION
        ),
        "source_recovery_contract_version": SOURCE_RECOVERY_CONTRACT_VERSION,
        "knowledge_judge_isolation_contract_version": (
            KNOWLEDGE_JUDGE_ISOLATION_CONTRACT_VERSION
        ),
        "knowledge_judge_contract_version": (
            knowledge_ai.KNOWLEDGE_JUDGE_CONTRACT_VERSION
        ),
        "knowledge_evidence_contract_version": (
            knowledge.KNOWLEDGE_EVIDENCE_CONTRACT_VERSION
        ),
        "knowledge_media_index_version": (
            knowledge.KNOWLEDGE_MEDIA_INDEX_VERSION
        ),
        "autonomous_visual_evidence_contract_version": (
            AUTONOMOUS_VISUAL_EVIDENCE_CONTRACT_VERSION
        ),
        "knowledge_legacy_visual_backfill_contract_version": (
            knowledge_visual_backfill.KNOWLEDGE_LEGACY_VISUAL_BACKFILL_CONTRACT_VERSION
        ),
        "knowledge_curator_plan_contract_version": (
            CURATOR_PLAN_CONTRACT_VERSION
        ),
        "knowledge_curator_isolation_contract_version": (
            CURATOR_ISOLATION_CONTRACT_VERSION
        ),
        "curator_terminal_outcome_contract_version": (
            knowledge.CURATOR_TERMINAL_OUTCOME_CONTRACT_VERSION
        ),
        "topic_lifecycle_assessment_contract_version": (
            knowledge.TOPIC_LIFECYCLE_ASSESSMENT_CONTRACT_VERSION
        ),
        "topic_lifecycle_isolation_contract_version": (
            TOPIC_LIFECYCLE_ISOLATION_CONTRACT_VERSION
        ),
        "pending_identity_contract_version": (
            knowledge.KNOWLEDGE_PENDING_IDENTITY_CONTRACT_VERSION
        ),
        "source_discovery_contract_version": (
            knowledge.SOURCE_DISCOVERY_CONTRACT_VERSION
        ),
        "status": status,
        "outcome_reason": outcome_reason,
        "trigger": str(trigger or "manual")[:60],
        "selection_mode": str(plan.get("mode") or "MANUAL")[:60],
        "selection_reason": str(plan.get("reason") or "")[:500],
        "selected_topic_ids": [
            str(value or "")[:80]
            for value in plan.get("selected_topic_ids", [])[:1]
            if str(value or "")
        ],
        "date": datetime.now().date().isoformat(),
        "finished_at": datetime.now(timezone.utc).isoformat(),
        "topics": topics,
        "sources_checked": len(sources),
        "source_candidates_discovered": discovered,
        "source_discovery": {
            "primary_added": primary_discovered,
            "fallback_added": fallback_discovered,
            "attempted_domains": sorted(attempted_domains),
        },
        "source_reviews": source_reviews,
        "lifecycle_audit": lifecycle_audit,
        "organization": organization,
        "candidates_extracted": candidates_extracted,
        "visual_evidence": visual_evidence,
        "legacy_visual_backfill": legacy_visual_backfill,
        "knowledge_judge": judge_counts,
        "verified_evidence_count": verified_evidence_count,
        **counts,
        "summary": summary[:12],
    }
    knowledge.append_learning_log(log)
    print("[KNOWLEDGE CYCLE]", json.dumps(log, ensure_ascii=False, indent=2))
    return log


def run_autonomy_cycle(
    *,
    trigger="manual",
    background_interval_days=(
        knowledge_autonomy.DEFAULT_BACKGROUND_INTERVAL_DAYS
    ),
    force=False,
):
    """Run the one shared autonomous pipeline without duplicate processes."""

    _use_project_directory()
    with knowledge_autonomy.cycle_lock() as acquired:
        if not acquired:
            result = {
                "status": "SKIPPED",
                "reason": "autonomy_cycle_busy",
                "trigger": str(trigger or "manual")[:60],
            }
            print("[KNOWLEDGE AUTONOMY] status=SKIPPED reason=busy")
            return result
        plan = plan_autonomous_learning(
            trigger=trigger,
            background_interval_days=background_interval_days,
            force=force,
        )
        print(
            "[KNOWLEDGE AUTONOMY PLAN]",
            "mode=" + str(plan.get("mode") or "unknown"),
            "topics=" + ",".join(plan.get("selected_topic_ids", [])),
            "due=" + str(plan.get("due") is True).lower(),
        )
        if plan.get("due") is not True:
            return {
                "status": "SKIPPED",
                "reason": "not_due",
                "trigger": str(trigger or "manual")[:60],
                "plan": plan,
            }
        topics = _topics_from_plan(plan)
        return run_learning_cycle(
            topics=topics or None,
            autonomy_plan=plan,
            trigger=trigger,
            enable_legacy_visual_backfill=True,
        )


if __name__ == "__main__":
    run_autonomy_cycle(trigger="manual", force=True)
