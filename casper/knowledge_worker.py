"""Run one profile-guided Bekki Knowledge V1 learning cycle."""

import json
import os
from datetime import datetime, timezone

from bs4 import BeautifulSoup
import requests

import knowledge
import knowledge_ai
import memory
import tools


MAX_SOURCES_PER_RUN = 5
MAX_ITEMS_PER_SOURCE = 4
KNOWLEDGE_WORKER_VERSION = "1.1-ai-judges"


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


def derive_topics():
    result = tools.run_ai_prompt(
        "prompts/knowledge_topics.txt",
        "Current user profile and preferences:\n" + profile_context(),
        expect_json=True,
        num_ctx=3072,
        num_predict=240,
    )
    if not isinstance(result, dict) or not isinstance(result.get("topics"), list):
        return []
    return list(dict.fromkeys(
        str(topic).lower().strip()[:80]
        for topic in result["topics"]
        if str(topic).strip()
    ))[:12]


def choose_sources(topics):
    sources = knowledge.load_sources(approved_only=True)
    ranked = []
    topic_set = set(topics)
    for source in sources:
        source_topics = {str(item).lower() for item in source.get("topics", [])}
        overlap = len(topic_set & source_topics)
        if overlap:
            ranked.append((overlap, source))
    ranked.sort(key=lambda item: item[0], reverse=True)
    return [source for _, source in ranked[:MAX_SOURCES_PER_RUN]]


def discover_source_candidates(topics):
    added = 0
    for topic in topics[:3]:
        results = tools.search(
            topic + " official organization university documentation",
            count=5,
        )
        if not isinstance(results, list):
            continue
        for result in results:
            if knowledge.add_source_candidate(result, [topic]):
                added += 1
    return added


def read_source(source):
    page = tools.read_page(source["url"])
    if not page.get("success"):
        raise RuntimeError(page.get("error", "Source could not be read."))
    return str(page.get("content", ""))[:30000]


def review_source_candidates(topics):
    counts = {"approved": 0, "pending": 0, "rejected": 0, "errors": 0}
    relevant_topics = set(topics)
    candidates = [
        item for item in knowledge.load_source_candidates()
        if (
            item.get("status") == "candidate"
            or item.get("policy_version", 0) < knowledge.SOURCE_POLICY_VERSION
        )
        and relevant_topics.intersection(item.get("topics", []))
    ][:15]

    for candidate in candidates:
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
            print("[SOURCE JUDGE ERROR]", candidate.get("url"), repr(error))
    return counts


def extract_candidates(source, text, topics):
    result = tools.run_ai_prompt(
        "prompts/knowledge_extract.txt",
        "Learning topics:\n"
        + json.dumps(topics, ensure_ascii=False)
        + "\n\nSource metadata:\n"
        + json.dumps(source, ensure_ascii=False, indent=2)
        + "\n\nSource text:\n"
        + text,
        expect_json=True,
        num_ctx=8192,
        num_predict=1000,
    )
    if not isinstance(result, dict) or not isinstance(result.get("items"), list):
        return []
    return [item for item in result["items"] if isinstance(item, dict)][
        :MAX_ITEMS_PER_SOURCE
    ]


def run_learning_cycle():
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
    topics = derive_topics()
    sources = choose_sources(topics)
    discovered = 0
    if not sources and topics:
        discovered = discover_source_candidates(topics)

    # Review relevant candidates left by any earlier run, regardless of
    # whether other approved sources already exist.
    source_reviews = review_source_candidates(topics)
    sources = choose_sources(topics)

    summary = []
    counts = {"verified": 0, "pending_review": 0, "duplicate": 0, "errors": 0}
    for source in sources:
        try:
            text = read_source(source)
            for candidate in extract_candidates(source, text, topics):
                judgment = knowledge_ai.judge_knowledge(candidate, source)
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
        except Exception as error:
            counts["errors"] += 1
            print("[KNOWLEDGE SOURCE ERROR]", source.get("url"), repr(error))

    log = {
        "date": datetime.now().date().isoformat(),
        "finished_at": datetime.now(timezone.utc).isoformat(),
        "topics": topics,
        "sources_checked": len(sources),
        "source_candidates_discovered": discovered,
        "source_reviews": source_reviews,
        "lifecycle_audit": lifecycle_audit,
        **counts,
        "summary": summary[:12],
    }
    knowledge.append_learning_log(log)
    print("[KNOWLEDGE CYCLE]", json.dumps(log, ensure_ascii=False, indent=2))
    return log


if __name__ == "__main__":
    _use_project_directory()
    run_learning_cycle()