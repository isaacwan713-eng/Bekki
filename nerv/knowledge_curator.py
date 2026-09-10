"""Daily AI-owned organization of already-approved Bekki Knowledge records."""

from copy import deepcopy
from datetime import datetime, timedelta, timezone
import hashlib
import json
import re
import unicodedata

import knowledge
import knowledge_evidence


# Curator assignments are structurally rich (topic, entities, relations,
# keywords, and duplicate/conflict links).  More importantly, a multi-item
# schema permits a small local model to repeat one allowed ID while silently
# dropping another.  Judge one immutable curation identity at a time so the
# schema can bind both the exact knowledge ID and its exact revision
# fingerprint.  Each valid decision is committed independently.
MAX_BATCH_ITEMS = 1
MAX_DAILY_ITEMS = 48
CURATOR_FAILURE_RETRY_SECONDS = 15 * 60
CURATOR_PLAN_CONTRACT_VERSION = 2
CURATOR_ISOLATION_CONTRACT_VERSION = 1
MAX_RELEVANT_TOPICS = 2
MAX_CURATOR_PACKET_BYTES = 12000
_SAFE_ID_RE = re.compile(r"^[a-z0-9][a-z0-9_-]{0,79}$")
_SAFE_RELATION_RE = re.compile(r"^[a-z][a-z0-9_]{0,79}$")
_WORD_RE = re.compile(r"[^\W_]+", re.UNICODE)
_GENERIC_TOPIC_WORDS = {
    "and", "culture", "ecosystem", "entertainment", "group", "groups",
    "idol", "knowledge", "member", "members", "music", "organization",
    "organizations", "subject", "team", "topic", "virtual", "与", "成员",
    "偶像", "娱乐", "文化", "组织", "主题", "知识",
}
_MEMBERSHIP_LIST_RE = re.compile(
    r"(?:成员(?:名单)?|members?(?:\s+list)?)\s*"
    r"(?:包括|为|是|有|[:：]|includes?|are)\s*(.+)",
    re.IGNORECASE,
)
_MEMBERSHIP_SPLIT_RE = re.compile(r"\s*(?:、|，|,|\band\b|和|及)\s*", re.IGNORECASE)


ENTITY_SCHEMA = {
    "type": "object",
    "properties": {
        "id": {
            "type": "string",
            "maxLength": 80,
            "pattern": "^[a-z0-9][a-z0-9_-]{0,79}$",
        },
        "name": {"type": "string", "maxLength": 200},
        "type": {"type": "string", "maxLength": 80},
        "aliases": {
            "type": "array",
            "maxItems": 20,
            "items": {"type": "string", "maxLength": 120},
        },
    },
    "required": ["id", "name", "type", "aliases"],
    "additionalProperties": False,
}


RELATED_ENTITY_SCHEMA = deepcopy(ENTITY_SCHEMA)
RELATED_ENTITY_SCHEMA["properties"]["relation"] = {
    "type": "string",
    "maxLength": 80,
    "pattern": "^[a-z][a-z0-9_]{0,79}$",
}
RELATED_ENTITY_SCHEMA["properties"]["relation_direction"] = {
    "type": "string",
    "enum": ["SUBJECT_TO_RELATED", "RELATED_TO_SUBJECT"],
}
RELATED_ENTITY_SCHEMA["properties"]["claim_relation_evidence"] = {
    "type": "string",
    "minLength": 1,
    "maxLength": 300,
}
RELATED_ENTITY_SCHEMA["required"] = [
    "id", "name", "type", "aliases", "relation",
    "relation_direction", "claim_relation_evidence",
]


ASSIGNMENT_SCHEMA = {
    "type": "object",
    "properties": {
        "knowledge_id": {"type": "string", "maxLength": 160},
        "decision": {
            "type": "string",
            "enum": ["STORE", "DUPLICATE", "CONFLICT", "DEFER"],
        },
        "topic_id": {
            "type": "string",
            "maxLength": 80,
            "pattern": "^[a-z0-9][a-z0-9_-]{0,79}$",
        },
        "topic_title": {"type": "string", "maxLength": 200},
        "topic_aliases": {
            "type": "array",
            "maxItems": 30,
            "items": {"type": "string", "maxLength": 120},
        },
        "topic_keywords": {
            "type": "array",
            "maxItems": 50,
            "items": {"type": "string", "maxLength": 120},
        },
        "subject_entity": ENTITY_SCHEMA,
        "literal_claim_subject": {
            "type": "string",
            "minLength": 1,
            "maxLength": 300,
        },
        "selected_subject_entity_id": {
            "type": "string",
            "maxLength": 80,
            "pattern": "^[a-z0-9][a-z0-9_-]{0,79}$",
        },
        "rejected_adjacent_entity_ids": {
            "type": "array",
            "maxItems": 12,
            "items": {
                "type": "string",
                "maxLength": 80,
                "pattern": "^[a-z0-9][a-z0-9_-]{0,79}$",
            },
        },
        "subject_selection_reason": {
            "type": "string",
            "minLength": 1,
            "maxLength": 500,
        },
        "related_entities": {
            "type": "array",
            "maxItems": 12,
            "items": RELATED_ENTITY_SCHEMA,
        },
        "facet": {"type": "string", "maxLength": 120},
        "claim_keywords": {
            "type": "array",
            "maxItems": 24,
            "items": {"type": "string", "maxLength": 120},
        },
        "preferred_display_claim": {
            "type": "string",
            "minLength": 1,
            "maxLength": 3000,
        },
        "preferred_display_language": {
            "type": "string",
            "minLength": 1,
            "maxLength": 40,
        },
        "name_rendering_status": {
            "type": "string",
            "enum": [
                "NATIVE_PREFERRED",
                "SOURCE_PRESERVED",
                "MIXED_SAFE",
            ],
        },
        "display_semantics_preserved": {"type": "boolean"},
        "related_claim_ids": {
            "type": "array",
            "maxItems": 12,
            "items": {"type": "string", "maxLength": 160},
        },
        "entity_scope_preserved": {
            "type": "boolean",
            "description": (
                "True only when topic co-location did not merge distinct "
                "entities or organizational levels."
            ),
        },
        "relationship_semantics_consistent": {
            "type": "boolean",
            "description": (
                "True only when every related entity type and relation match "
                "the exact claim."
            ),
        },
        "reason": {"type": "string", "maxLength": 500},
    },
    "required": [
        "knowledge_id",
        "decision",
        "topic_id",
        "topic_title",
        "topic_aliases",
        "topic_keywords",
        "subject_entity",
        "literal_claim_subject",
        "selected_subject_entity_id",
        "rejected_adjacent_entity_ids",
        "subject_selection_reason",
        "related_entities",
        "facet",
        "claim_keywords",
        "preferred_display_claim",
        "preferred_display_language",
        "name_rendering_status",
        "display_semantics_preserved",
        "related_claim_ids",
        "entity_scope_preserved",
        "relationship_semantics_consistent",
        "reason",
    ],
    "additionalProperties": False,
}


CURATOR_PLAN_SCHEMA = {
    "type": "object",
    "properties": {
        "curation_fingerprint": {
            "type": "string",
            "pattern": "^[a-f0-9]{64}$",
        },
        "assignments": {
            "type": "array",
            "maxItems": MAX_BATCH_ITEMS,
            "items": ASSIGNMENT_SCHEMA,
        },
        "reason": {"type": "string", "maxLength": 500},
    },
    "required": ["assignments", "reason"],
    "additionalProperties": False,
}


class KnowledgeCurator:
    """Ask AI how to organize facts; execute only a complete valid plan."""

    def __init__(
        self,
        model_call,
        unload_model=None,
        topic_lifecycle=None,
        curiosity_journal=None,
    ):
        self.model_call = model_call
        self.unload_model = unload_model
        self.topic_lifecycle = topic_lifecycle
        self.curiosity = curiosity_journal
        self._last_plan_status = ""

    @staticmethod
    def _local_date():
        return datetime.now().astimezone().date().isoformat()

    def due(self):
        knowledge.initialize()
        runs = knowledge.load_curator_runs()
        history = runs.get("runs", []) if isinstance(runs, dict) else []
        latest = history[-1] if isinstance(history, list) and history else {}
        if (
            isinstance(latest, dict)
            and str(latest.get("status") or "").upper() == "FAILED"
        ):
            try:
                failed_at = datetime.fromisoformat(
                    str(latest.get("recorded_at") or "").replace("Z", "+00:00")
                )
                if failed_at.tzinfo is None:
                    failed_at = failed_at.replace(tzinfo=timezone.utc)
                if datetime.now(timezone.utc) - failed_at < timedelta(
                    seconds=CURATOR_FAILURE_RETRY_SECONDS
                ):
                    return False
            except (TypeError, ValueError):
                pass
        if knowledge.load_partition_lifecycle_audit_candidates(limit=1):
            return True
        topic_autonomy_due = (
            self.topic_lifecycle is not None
            and self.topic_lifecycle.due()
        )
        pending = knowledge.load_curation_inbox(pending_only=True)
        if not pending:
            return topic_autonomy_due
        if str(runs.get("last_successful_date") or "") != self._local_date():
            return True
        last_attempt = str(runs.get("last_attempt_at") or "")
        # A Curiosity answer may become verified after today's normal curator
        # pass.  Re-open only for records enqueued after that pass; an older
        # DEFER remains daily and cannot cause a tight retry loop.
        return topic_autonomy_due or any(
            str(entry.get("enqueued_at") or "") > last_attempt
            for entry in pending
            if isinstance(entry, dict)
        )

    def _release(self):
        if self.unload_model is None:
            return
        try:
            self.unload_model("gemma4:12b")
            print("[NERV KNOWLEDGE CURATOR MODEL RELEASED] gemma4:12b")
        except Exception as error:
            print("[NERV KNOWLEDGE CURATOR RELEASE WARNING]", repr(error))

    @staticmethod
    def _schema_for(knowledge_ids, curation_fingerprint=None):
        schema = deepcopy(CURATOR_PLAN_SCHEMA)
        schema["properties"]["assignments"]["minItems"] = len(knowledge_ids)
        schema["properties"]["assignments"]["maxItems"] = len(knowledge_ids)
        schema["properties"]["assignments"]["items"]["properties"][
            "knowledge_id"
        ] = {
            "type": "string",
            "enum": sorted(knowledge_ids),
        }
        if curation_fingerprint:
            schema["properties"]["curation_fingerprint"] = {
                "type": "string",
                "enum": [str(curation_fingerprint)],
            }
            schema["required"] = [
                "curation_fingerprint", "assignments", "reason",
            ]
        return schema

    @staticmethod
    def _compact_items(entries):
        records = {
            str(item.get("id") or ""): item
            for item in knowledge.load_items()
            if isinstance(item, dict) and item.get("id")
        }
        compact = []
        for entry in entries:
            item = records.get(str(entry.get("knowledge_id") or ""))
            if not isinstance(item, dict):
                continue
            verification = item.get("verification")
            verification = (
                verification if isinstance(verification, dict) else {}
            )
            source_context = verification.get("source_context")
            source_context = (
                source_context if isinstance(source_context, dict) else {}
            )
            provenance = item.get("provenance")
            provenance = provenance if isinstance(provenance, dict) else {}
            evidence_answers = verification.get("evidence_answers")
            evidence_answers = (
                evidence_answers if isinstance(evidence_answers, list) else []
            )
            sources = item.get("sources")
            sources = sources if isinstance(sources, list) else []
            evidence_summary = knowledge_evidence.bundle_summary(
                item.get("evidence_bundle")
            )
            compact.append({
                "knowledge_id": str(item.get("id") or "")[:160],
                "subject": str(item.get("subject") or "")[:300],
                "claim": str(item.get("claim") or "")[:2200],
                "topics": [str(value)[:80] for value in item.get("topics", [])[:8]],
                "knowledge_domain": str(item.get("knowledge_domain") or "other")[:80],
                "cluster_label": str(item.get("cluster_label") or "")[:120],
                "knowledge_type": str(item.get("knowledge_type") or "stable")[:20],
                "expires_at": item.get("expires_at"),
                "temporal_scope": (
                    item.get("temporal_scope")
                    if isinstance(item.get("temporal_scope"), dict)
                    else {}
                ),
                "status": str(item.get("status") or "")[:30],
                "verification_status": str(
                    item.get("verification_status") or ""
                )[:120],
                "verification_level": str(
                    item.get("verification_level") or ""
                )[:80],
                "source_evidence": evidence_summary,
                "provenance": {
                    key: str(provenance.get(key) or "")[:160]
                    for key in (
                        "origin", "source_domain", "source_kind",
                        "capture_route",
                    )
                    if provenance.get(key) is not None
                },
                "display_context": {
                    "original_request": str(
                        verification.get("original_request")
                        or verification.get("original_question")
                        or ""
                    )[:500],
                    "accepted_answer": str(
                        verification.get("accepted_answer")
                        or verification.get("answer")
                        or ""
                    )[:900],
                    "evidence_canonical_answer": str(
                        verification.get("evidence_canonical_answer")
                        or verification.get("canonical_answer")
                        or source_context.get("canonical_answer")
                        or ""
                    )[:900],
                    "evidence_answers": [
                        str(value)[:600]
                        for value in evidence_answers[:2]
                        if str(value).strip()
                    ],
                    "source_titles": [
                        str(value.get("title") or "")[:180]
                        for value in sources[:3]
                        if isinstance(value, dict)
                        and str(value.get("title") or "").strip()
                    ],
                },
                "curation_fingerprint": str(
                    entry.get("fingerprint")
                    or knowledge._curation_fingerprint(item)
                )[:64],
            })
        return compact

    @staticmethod
    def _text_key(value):
        normalized = unicodedata.normalize(
            "NFKC", str(value or "")
        ).casefold()
        return "".join(
            character for character in normalized if character.isalnum()
        )

    @classmethod
    def _tokens(cls, values):
        if not isinstance(values, (list, tuple, set)):
            values = [values]
        output = set()
        for value in values:
            normalized = unicodedata.normalize(
                "NFKC", str(value or "")
            ).casefold()
            for token in _WORD_RE.findall(normalized):
                if (
                    len(token) >= 3
                    and token not in _GENERIC_TOPIC_WORDS
                    and not token.isdigit()
                ):
                    output.add(token)
        return output

    @classmethod
    def _item_evidence_texts(cls, item):
        item = item if isinstance(item, dict) else {}
        display = item.get("display_context")
        display = display if isinstance(display, dict) else {}
        source_evidence = item.get("source_evidence")
        source_evidence = (
            source_evidence if isinstance(source_evidence, dict) else {}
        )
        values = [
            item.get("subject"),
            item.get("claim"),
            item.get("cluster_label"),
            *item.get("topics", []),
            display.get("original_request"),
            display.get("accepted_answer"),
            display.get("evidence_canonical_answer"),
            *display.get("evidence_answers", []),
            *display.get("source_titles", []),
            *source_evidence.get("text_support", []),
            *source_evidence.get("visual_observations", []),
        ]
        return [str(value) for value in values if str(value or "").strip()]

    @classmethod
    def _topic_match_score(cls, item, topic):
        item = item if isinstance(item, dict) else {}
        topic = topic if isinstance(topic, dict) else {}
        strong_values = [
            item.get("subject"), item.get("cluster_label"),
            *item.get("topics", []),
        ]
        topic_values = [
            topic.get("topic_id"), topic.get("title"),
            *topic.get("aliases", []),
        ]
        for entity in topic.get("entities", []):
            if not isinstance(entity, dict):
                continue
            topic_values.extend([
                entity.get("name"), *entity.get("aliases", []),
            ])
        strong_keys = [cls._text_key(value) for value in strong_values]
        strong_keys = [value for value in strong_keys if len(value) >= 3]
        topic_keys = [cls._text_key(value) for value in topic_values]
        topic_keys = [value for value in topic_keys if len(value) >= 3]
        score = 0
        for left in strong_keys:
            for right in topic_keys:
                if left == right:
                    score += 100
                elif left in right or right in left:
                    score += 35
        evidence_key = cls._text_key(" ".join(cls._item_evidence_texts(item)))
        score += 12 * sum(
            1 for value in set(topic_keys)
            if len(value) >= 4 and value in evidence_key
        )
        item_tokens = cls._tokens(cls._item_evidence_texts(item))
        topic_tokens = cls._tokens(topic_values)
        score += 6 * len(item_tokens & topic_tokens)
        return score

    @classmethod
    def _row_match_score(cls, item, values):
        evidence = cls._item_evidence_texts(item)
        evidence_key = cls._text_key(" ".join(evidence))
        score = 0
        for raw in values:
            value = cls._text_key(raw)
            if len(value) >= 3 and value in evidence_key:
                score += 20
        score += 4 * len(cls._tokens(evidence) & cls._tokens(values))
        return score

    @classmethod
    def _compact_catalog_topic(cls, item, topic):
        entities = []
        for index, entity in enumerate(topic.get("entities", [])):
            if not isinstance(entity, dict):
                continue
            score = cls._row_match_score(
                item,
                [entity.get("id"), entity.get("name"), *entity.get("aliases", [])],
            )
            if score:
                entities.append((score, index, {
                    "id": str(entity.get("id") or "")[:80],
                    "name": str(entity.get("name") or "")[:200],
                    "type": str(entity.get("type") or "other")[:80],
                    "aliases": [
                        str(value)[:120]
                        for value in entity.get("aliases", [])[:8]
                        if str(value).strip()
                    ],
                }))
        entities.sort(key=lambda value: (-value[0], value[1]))
        selected_entities = [value[2] for value in entities[:12]]
        selected_entity_ids = {
            str(value.get("id") or "") for value in selected_entities
        }

        claims = []
        item_subject = cls._text_key(item.get("subject"))
        for index, claim in enumerate(topic.get("claims", [])):
            if not isinstance(claim, dict):
                continue
            claim_subject = cls._text_key(claim.get("subject"))
            score = cls._row_match_score(
                item,
                [claim.get("subject"), claim.get("claim")],
            )
            if item_subject and claim_subject == item_subject:
                score += 100
            if score:
                claims.append((score, index, {
                    "id": str(claim.get("id") or "")[:120],
                    "subject": str(claim.get("subject") or "")[:240],
                    "claim": str(claim.get("claim") or "")[:500],
                    "subject_entity_id": str(
                        claim.get("subject_entity_id") or ""
                    )[:80],
                    "facet": str(claim.get("facet") or "")[:120],
                    "knowledge_layer": str(
                        claim.get("knowledge_layer") or ""
                    )[:40],
                    "fact_type": str(claim.get("fact_type") or "")[:40],
                    "temporal_scope": (
                        claim.get("temporal_scope")
                        if isinstance(claim.get("temporal_scope"), dict)
                        else {}
                    ),
                }))
        claims.sort(key=lambda value: (-value[0], value[1]))
        selected_claims = [value[2] for value in claims[:6]]
        selected_claim_ids = {
            str(value.get("id") or "") for value in selected_claims
        }

        relationships = []
        for relation in topic.get("relationships", []):
            if not isinstance(relation, dict):
                continue
            support_ids = {
                str(value) for value in relation.get(
                    "supporting_knowledge_ids", []
                )
            }
            if not (
                str(relation.get("source_entity_id") or "")
                in selected_entity_ids
                or str(relation.get("target_entity_id") or "")
                in selected_entity_ids
                or support_ids & selected_claim_ids
            ):
                continue
            relationships.append({
                "id": str(relation.get("id") or "")[:120],
                "source_entity_id": str(
                    relation.get("source_entity_id") or ""
                )[:80],
                "relation": str(relation.get("relation") or "")[:80],
                "target_entity_id": str(
                    relation.get("target_entity_id") or ""
                )[:80],
                "supporting_knowledge_ids": [
                    str(value)[:160]
                    for value in relation.get(
                        "supporting_knowledge_ids", []
                    )[:8]
                ],
                "temporal_status": str(
                    relation.get("temporal_status") or "INACTIVE"
                )[:40],
            })
            if len(relationships) >= 8:
                break

        return {
            "topic_id": str(topic.get("topic_id") or "")[:80],
            "title": str(topic.get("title") or "")[:200],
            "aliases": [
                str(value)[:120] for value in topic.get("aliases", [])[:8]
                if str(value).strip()
            ],
            "keywords": [
                str(value)[:120] for value in topic.get("keywords", [])[:8]
                if str(value).strip()
            ],
            "entities": selected_entities,
            "relationships": relationships,
            "classification": (
                topic.get("classification")
                if isinstance(topic.get("classification"), dict) else {}
            ),
            "claims": selected_claims,
        }

    @classmethod
    def _relevant_catalog(cls, item, catalog):
        ranked = []
        for index, topic in enumerate(catalog or []):
            if not isinstance(topic, dict):
                continue
            score = cls._topic_match_score(item, topic)
            if score > 0:
                ranked.append((score, index, topic))
        ranked.sort(key=lambda value: (-value[0], value[1]))
        return [
            cls._compact_catalog_topic(item, value[2])
            for value in ranked[:MAX_RELEVANT_TOPICS]
        ]

    @staticmethod
    def _packet_bytes(packet):
        return len(json.dumps(
            packet,
            ensure_ascii=False,
            separators=(",", ":"),
        ).encode("utf-8"))

    @classmethod
    def _fit_packet(cls, packet):
        """Drop only optional comparison context before model-runtime truncation."""

        fitted = deepcopy(packet)
        catalogs = fitted.get("relevant_topic_ecosystems", [])
        while cls._packet_bytes(fitted) > MAX_CURATOR_PACKET_BYTES:
            changed = False
            if len(catalogs) > 1:
                catalogs.pop()
                changed = True
            else:
                for field, minimum in (
                    ("relationships", 0),
                    ("keywords", 0),
                    ("aliases", 0),
                    ("entities", 1),
                    ("claims", 1),
                ):
                    for topic in reversed(catalogs):
                        values = topic.get(field)
                        if isinstance(values, list) and len(values) > minimum:
                            values.pop()
                            changed = True
                            break
                    if changed:
                        break
            if not changed:
                display = fitted.get("current_verified_item", {}).get(
                    "display_context", {}
                )
                for field in ("evidence_answers", "source_titles"):
                    values = display.get(field)
                    if isinstance(values, list) and values:
                        values.pop()
                        changed = True
                        break
            if not changed:
                display = fitted.get("current_verified_item", {}).get(
                    "display_context", {}
                )
                for field in (
                    "accepted_answer", "evidence_canonical_answer",
                    "original_request",
                ):
                    value = str(display.get(field) or "")
                    if len(value) > 160:
                        display[field] = value[:max(160, len(value) // 2)]
                        changed = True
                        break
            if not changed:
                break
        if cls._packet_bytes(fitted) > MAX_CURATOR_PACKET_BYTES:
            raise ValueError("curator_packet_too_large")
        return fitted

    @staticmethod
    def _known_claim_ids(catalog, batch_ids):
        values = set(batch_ids)
        for topic in catalog:
            if not isinstance(topic, dict):
                continue
            for claim in topic.get("claims", []):
                if isinstance(claim, dict) and claim.get("id"):
                    values.add(str(claim["id"]))
        return values

    @staticmethod
    def _known_entity_ids(catalog):
        values = set()
        for topic in catalog:
            if not isinstance(topic, dict):
                continue
            for entity in topic.get("entities", []):
                if isinstance(entity, dict) and entity.get("id"):
                    values.add(str(entity["id"]).lower().strip())
        return values

    @staticmethod
    def _membership_list_entries(claim):
        """Extract only explicit multi-name membership lists for coverage checks."""

        match = _MEMBERSHIP_LIST_RE.search(str(claim or ""))
        if not match:
            return []
        tail = re.split(r"[。；;\n]", match.group(1), maxsplit=1)[0]
        values = []
        for raw in _MEMBERSHIP_SPLIT_RE.split(tail):
            value = str(raw or "").strip(" \t\r\n:：。.;；'\"“”‘’")
            if value and value not in values:
                values.append(value[:120])
        return values if 2 <= len(values) <= 12 else []

    @staticmethod
    def _entry_names_entity(entry, entity):
        entry = str(entry or "").strip().casefold()
        names = [entity.get("name"), *entity.get("aliases", [])]
        return any(
            str(value or "").strip().casefold() == entry
            for value in names
            if str(value or "").strip()
        )

    @staticmethod
    def _membership_evidence_text(claim):
        """Return the exact bounded clause that contains an explicit roster."""

        claim = str(claim or "")
        match = _MEMBERSHIP_LIST_RE.search(claim)
        if not match:
            return claim[:300]
        end_match = re.search(r"[。；;\n]", claim[match.start():])
        end = (
            match.start() + end_match.start() + 1
            if end_match is not None
            else len(claim)
        )
        return claim[match.start():end][:300]

    @staticmethod
    def _catalog_member_entity(catalog, topic_id, member_name):
        """Reuse one exact existing topic entity, never a fuzzy name match."""

        normalized_name = str(member_name or "").strip().casefold()
        matches = []
        for topic in catalog or []:
            if (
                not isinstance(topic, dict)
                or str(topic.get("topic_id") or "").lower().strip()
                != str(topic_id or "").lower().strip()
            ):
                continue
            for entity in topic.get("entities", []):
                if not isinstance(entity, dict):
                    continue
                names = [entity.get("name"), *entity.get("aliases", [])]
                if any(
                    str(value or "").strip().casefold() == normalized_name
                    for value in names
                    if str(value or "").strip()
                ):
                    matches.append(entity)
        if len(matches) != 1:
            return None
        entity = matches[0]
        entity_id = str(entity.get("id") or "").lower().strip()
        entity_type = str(entity.get("type") or "").casefold().strip()
        if (
            not _SAFE_ID_RE.fullmatch(entity_id)
            or entity_type not in {
                "person", "member", "character", "virtual_character",
                "performer", "creator",
            }
        ):
            return None
        return {
            "id": entity_id,
            "name": str(entity.get("name") or member_name)[:200],
            "type": str(entity.get("type") or "member")[:80],
            "aliases": [
                str(value)[:120]
                for value in entity.get("aliases", [])[:20]
                if str(value).strip()
            ],
        }

    @classmethod
    def _repair_explicit_membership_relationships(
        cls,
        raw,
        evidence_items,
        catalog,
    ):
        """Complete only literal verified rosters after both AI passes fail.

        This is deliberately not a semantic fallback.  Topic and subject
        selection remain model-owned.  The runtime copies each literal name
        from an already-verified atomic roster claim and emits the one
        canonical edge shape required by the relationship contract.
        """

        if not isinstance(raw, dict) or not isinstance(
            raw.get("assignments"), list
        ):
            return None, []
        repaired = deepcopy(raw)
        repaired_ids = []
        evidence_items = (
            evidence_items if isinstance(evidence_items, dict) else {}
        )
        for assignment in repaired["assignments"]:
            if not isinstance(assignment, dict):
                continue
            if str(assignment.get("decision") or "").upper() != "STORE":
                continue
            knowledge_id = str(assignment.get("knowledge_id") or "")
            evidence_item = evidence_items.get(knowledge_id, {})
            evidence_subject = str(evidence_item.get("subject") or "")
            claim = str(evidence_item.get("claim") or "")
            evidence_texts = [evidence_subject, claim]
            member_names = cls._membership_list_entries(claim)
            if not member_names:
                continue
            topic_id = str(assignment.get("topic_id") or "").lower().strip()
            subject = assignment.get("subject_entity")
            subject_name = (
                str(subject.get("name") or "")
                if isinstance(subject, dict) else ""
            )
            subject_type = (
                str(subject.get("type") or "").casefold().strip()
                if isinstance(subject, dict) else ""
            )
            if (
                not _SAFE_ID_RE.fullmatch(topic_id)
                or not isinstance(subject, dict)
                or not _SAFE_ID_RE.fullmatch(
                    str(subject.get("id") or "").lower().strip()
                )
                or subject_type not in {
                    "group", "organization", "team", "unit", "pairing",
                    "virtual_idol_group", "umbrella_organization",
                }
                or not knowledge._value_supported_by_evidence(
                    subject_name,
                    evidence_texts,
                )
                or not knowledge._value_supported_by_evidence(
                    assignment.get("literal_claim_subject"),
                    evidence_texts,
                )
            ):
                continue
            original = bool(re.search(
                r"(?:最初|创始|初代|original|founding)",
                claim,
                re.IGNORECASE,
            ))
            relation = "original_member_of" if original else "member_of"
            evidence_text = cls._membership_evidence_text(claim)
            related_entities = []
            for member_name in member_names:
                entity = cls._catalog_member_entity(
                    catalog,
                    topic_id,
                    member_name,
                )
                if entity is None:
                    entity = {
                        "id": "member_" + hashlib.sha256(
                            member_name.encode("utf-8")
                        ).hexdigest()[:16],
                        "name": member_name,
                        "type": "member",
                        "aliases": [],
                    }
                related_entities.append({
                    **entity,
                    "relation": relation,
                    "relation_direction": "RELATED_TO_SUBJECT",
                    "claim_relation_evidence": evidence_text,
                })
            assignment["related_entities"] = related_entities
            assignment["relationship_semantics_consistent"] = True
            repaired_ids.append(knowledge_id)
        return repaired, repaired_ids

    @classmethod
    def _validate_plan(
        cls,
        raw,
        expected_ids,
        catalog,
        evidence_items=None,
        expected_fingerprint=None,
    ):
        errors = []
        if not isinstance(raw, dict) or not isinstance(raw.get("assignments"), list):
            return None, ["plan_or_assignments_invalid"]
        if (
            expected_fingerprint
            and str(raw.get("curation_fingerprint") or "")
            != str(expected_fingerprint)
        ):
            errors.append("curation_fingerprint_mismatch")
        assignments = raw["assignments"]
        returned_ids = [
            str(item.get("knowledge_id") or "")
            for item in assignments if isinstance(item, dict)
        ]
        if len(assignments) != len(expected_ids):
            errors.append("assignment_count_mismatch")
        if len(returned_ids) != len(set(returned_ids)):
            errors.append("duplicate_knowledge_id")
        if set(returned_ids) != set(expected_ids):
            errors.append("knowledge_id_set_mismatch")
        known_claim_ids = cls._known_claim_ids(catalog, expected_ids)
        known_entity_ids = cls._known_entity_ids(catalog)
        known_topics = {
            str(topic.get("topic_id") or "").lower().strip(): topic
            for topic in catalog
            if isinstance(topic, dict) and topic.get("topic_id")
        }
        known_entities = {}
        for topic in catalog:
            if not isinstance(topic, dict):
                continue
            for entity in topic.get("entities", []):
                if isinstance(entity, dict) and entity.get("id"):
                    known_entities[
                        str(entity.get("id") or "").lower().strip()
                    ] = entity
        normalized = []
        evidence_items = (
            evidence_items if isinstance(evidence_items, dict) else {}
        )
        for assignment in assignments:
            if not isinstance(assignment, dict):
                errors.append("assignment_not_object")
                continue
            item = deepcopy(assignment)
            evidence_item = evidence_items.get(
                str(item.get("knowledge_id") or ""),
                {},
            )
            claim_evidence = cls._item_evidence_texts(evidence_item)
            has_evidence = bool(claim_evidence)
            decision = str(item.get("decision") or "").upper()
            item["decision"] = decision
            if decision not in {"STORE", "DUPLICATE", "CONFLICT", "DEFER"}:
                errors.append("invalid_decision")
                continue
            topic_id = str(item.get("topic_id") or "").lower().strip()
            item["topic_id"] = topic_id
            if topic_id and not _SAFE_ID_RE.fullmatch(topic_id):
                errors.append("unsafe_topic_id")
            if decision == "STORE":
                if not _SAFE_ID_RE.fullmatch(topic_id):
                    errors.append("store_missing_topic_id")
                if not str(item.get("topic_title") or "").strip():
                    errors.append("store_missing_topic_title")
                if not str(item.get("facet") or "").strip():
                    errors.append("store_missing_facet")
                if not str(
                    item.get("preferred_display_claim") or ""
                ).strip():
                    errors.append("store_missing_preferred_display_claim")
                if not str(
                    item.get("preferred_display_language") or ""
                ).strip():
                    errors.append("store_missing_preferred_display_language")
                if str(item.get("name_rendering_status") or "") not in {
                    "NATIVE_PREFERRED", "SOURCE_PRESERVED", "MIXED_SAFE"
                }:
                    errors.append("invalid_name_rendering_status")
                if item.get("display_semantics_preserved") is not True:
                    errors.append("display_semantics_not_preserved")
                subject = item.get("subject_entity")
                literal_subject = str(
                    item.get("literal_claim_subject") or ""
                ).strip()
                if not literal_subject:
                    errors.append("missing_literal_claim_subject")
                elif has_evidence and not knowledge._value_supported_by_evidence(
                    literal_subject,
                    claim_evidence,
                ):
                    errors.append("ungrounded_literal_claim_subject")
                selected_subject_id = str(
                    item.get("selected_subject_entity_id") or ""
                ).lower().strip()
                item["selected_subject_entity_id"] = selected_subject_id
                if not _SAFE_ID_RE.fullmatch(selected_subject_id):
                    errors.append("unsafe_selected_subject_entity_id")
                if not str(item.get("subject_selection_reason") or "").strip():
                    errors.append("missing_subject_selection_reason")
                rejected_ids = [
                    str(value).lower().strip()
                    for value in item.get("rejected_adjacent_entity_ids", [])
                    if str(value).strip()
                ]
                item["rejected_adjacent_entity_ids"] = rejected_ids
                if len(rejected_ids) != len(set(rejected_ids)):
                    errors.append("duplicate_rejected_adjacent_entity_id")
                if any(
                    not _SAFE_ID_RE.fullmatch(value)
                    for value in rejected_ids
                ):
                    errors.append("unsafe_rejected_adjacent_entity_id")
                if any(
                    value not in known_entity_ids
                    for value in rejected_ids
                ):
                    errors.append("unknown_rejected_adjacent_entity_id")
                if not isinstance(subject, dict):
                    errors.append("store_missing_subject_entity")
                else:
                    subject_id = str(subject.get("id") or "").lower().strip()
                    subject["id"] = subject_id
                    if not _SAFE_ID_RE.fullmatch(subject_id):
                        errors.append("unsafe_subject_entity_id")
                    if not str(subject.get("name") or "").strip():
                        errors.append("missing_subject_entity_name")
                    if selected_subject_id != subject_id:
                        errors.append("selected_subject_id_mismatch")
                    if subject_id in rejected_ids:
                        errors.append("selected_subject_also_rejected")
                    subject_name = str(subject.get("name") or "").strip()
                    known_entity = known_entities.get(subject_id)
                    known_names = []
                    if isinstance(known_entity, dict):
                        known_names = [
                            known_entity.get("name"),
                            *known_entity.get("aliases", []),
                        ]
                    subject_aliases = [
                        str(value)
                        for value in subject.get("aliases", [])
                        if str(value or "").strip()
                    ]
                    if has_evidence and not (
                        knowledge._value_supported_by_evidence(
                            subject_name,
                            claim_evidence,
                        )
                        or any(
                            knowledge._value_supported_by_evidence(
                                value,
                                claim_evidence,
                            )
                            for value in subject_aliases
                        )
                        or any(
                            str(value or "").strip().casefold()
                            == subject_name.casefold()
                            for value in known_names
                            if str(value or "").strip()
                        )
                    ):
                        errors.append("ungrounded_subject_entity")
                proposed_title = str(item.get("topic_title") or "").strip()
                known_topic = known_topics.get(topic_id)
                known_topic_names = []
                if isinstance(known_topic, dict):
                    known_topic_names = [
                        known_topic.get("title"),
                        *known_topic.get("aliases", []),
                    ]
                if has_evidence and not (
                    knowledge._value_supported_by_evidence(
                        proposed_title,
                        claim_evidence,
                    )
                    or cls._row_match_score(
                        evidence_item,
                        [proposed_title],
                    ) > 0
                    or any(
                        str(value or "").strip().casefold()
                        == proposed_title.casefold()
                        for value in known_topic_names
                        if str(value or "").strip()
                    )
                ):
                    errors.append("ungrounded_topic_title")
                related_entities = item.get("related_entities", [])
                for related in related_entities:
                    if not isinstance(related, dict):
                        errors.append("related_entity_invalid")
                        continue
                    related_id = str(related.get("id") or "").lower().strip()
                    related["id"] = related_id
                    if not _SAFE_ID_RE.fullmatch(related_id):
                        errors.append("unsafe_related_entity_id")
                    if not str(related.get("name") or "").strip():
                        errors.append("missing_related_entity_name")
                    if not str(related.get("relation") or "").strip():
                        errors.append("missing_related_entity_relation")
                    elif not _SAFE_RELATION_RE.fullmatch(
                        str(related.get("relation") or "").lower().strip()
                    ):
                        errors.append("unsafe_related_entity_relation")
                    direction = str(
                        related.get("relation_direction") or ""
                    ).upper().strip()
                    related["relation_direction"] = direction
                    if direction not in {
                        "SUBJECT_TO_RELATED", "RELATED_TO_SUBJECT"
                    }:
                        errors.append("missing_or_invalid_relation_direction")
                    relation_evidence = str(
                        related.get("claim_relation_evidence") or ""
                    ).strip()
                    if not relation_evidence:
                        errors.append("missing_claim_relation_evidence")
                    elif not knowledge._value_supported_by_evidence(
                        relation_evidence,
                        claim_evidence,
                    ):
                        errors.append("ungrounded_claim_relation_evidence")
                    if not any(
                        knowledge._value_supported_by_evidence(
                            value,
                            claim_evidence,
                        )
                        for value in [
                            related.get("name"),
                            *related.get("aliases", []),
                        ]
                    ):
                        errors.append("ungrounded_related_entity")
                membership_entries = cls._membership_list_entries(
                    evidence_item.get("claim")
                )
                if membership_entries:
                    missing_entries = [
                        entry for entry in membership_entries
                        if not any(
                            cls._entry_names_entity(entry, related)
                            for related in related_entities
                            if isinstance(related, dict)
                        )
                    ]
                    if missing_entries:
                        errors.append("membership_relationships_incomplete")
                    original = bool(re.search(
                        r"(?:最初|创始|初代|original|founding)",
                        str(evidence_item.get("claim") or ""),
                        re.IGNORECASE,
                    ))
                    expected_relation = (
                        "original_member_of" if original else "member_of"
                    )
                    for related in related_entities:
                        if not isinstance(related, dict):
                            continue
                        if str(related.get("relation") or "").lower() != expected_relation:
                            errors.append("membership_relation_not_canonical")
                        if related.get("relation_direction") != "RELATED_TO_SUBJECT":
                            errors.append("membership_relation_direction_reversed")
            if item.get("entity_scope_preserved") is not True:
                errors.append("entity_scope_not_preserved")
            if item.get("relationship_semantics_consistent") is not True:
                errors.append("relationship_semantics_inconsistent")
            related_claim_ids = [
                str(value) for value in item.get("related_claim_ids", [])
                if str(value).strip()
            ]
            item["related_claim_ids"] = related_claim_ids
            if decision in {"DUPLICATE", "CONFLICT"}:
                if not related_claim_ids:
                    errors.append(decision.lower() + "_missing_target")
                if any(value not in known_claim_ids for value in related_claim_ids):
                    errors.append(decision.lower() + "_unknown_target")
                if str(item.get("knowledge_id") or "") in related_claim_ids:
                    errors.append(decision.lower() + "_self_target")
            normalized.append(item)
        if errors:
            return None, sorted(set(errors))
        return normalized, []

    def _call(self, prompt_path, packet, schema, recovery=False):
        try:
            return self.model_call(
                prompt_path,
                json.dumps(packet, ensure_ascii=False, separators=(",", ":")),
                expect_json=True,
                num_ctx=8192,
                num_predict=1500 if recovery else 1800,
                think=False,
                model_name="gemma4:12b",
                json_schema=schema,
            )
        finally:
            self._release()

    def _plan_batch(self, entries):
        if len(entries) != 1:
            raise ValueError("curator_isolation_requires_one_item")
        items = self._compact_items(entries)
        expected_ids = [str(item["knowledge_id"]) for item in items]
        if len(expected_ids) != len(entries):
            raise ValueError("pending_knowledge_missing")
        item = items[0]
        fingerprint = str(item.get("curation_fingerprint") or "")
        if not re.fullmatch(r"[a-f0-9]{64}", fingerprint):
            raise ValueError("curation_fingerprint_invalid")
        full_catalog = knowledge.load_topic_catalog(
            include_claims=True,
            max_topics=200,
            max_claims=20,
        )
        catalog = self._relevant_catalog(item, full_catalog)
        packet = {
            "curator_plan_contract_version": CURATOR_PLAN_CONTRACT_VERSION,
            "curator_isolation_contract_version": (
                CURATOR_ISOLATION_CONTRACT_VERSION
            ),
            "local_date": self._local_date(),
            "current_knowledge_id": expected_ids[0],
            "required_curation_fingerprint": fingerprint,
            "current_verified_item": item,
            "relevant_topic_ecosystems": catalog,
            "allowed_existing_topic_ids": [
                str(topic.get("topic_id") or "")
                for topic in catalog
                if topic.get("topic_id")
            ],
            "immutable_rules": {
                "verification_may_not_be_changed": True,
                "changing_event_news_are_not_in_this_queue": True,
                "one_topic_document_is_a_broad_knowledge_ecosystem": True,
                "related_people_members_sister_groups_stay_together_when_semantically_coherent": True,
                "topic_co_location_never_merges_distinct_entities": True,
                "internal_units_are_not_sister_organizations_of_their_parent": True,
            },
            "output_requirement": (
                "Return exactly one assignment for current_knowledge_id, "
                "echo required_curation_fingerprint, and return JSON only."
            ),
        }
        packet = self._fit_packet(packet)
        catalog = packet["relevant_topic_ecosystems"]
        packet["allowed_existing_topic_ids"] = [
            str(topic.get("topic_id") or "")
            for topic in catalog
            if topic.get("topic_id")
        ]
        input_bytes = self._packet_bytes(packet)
        print(
            "[NERV KNOWLEDGE CURATOR INPUT]",
            "knowledge_id=" + expected_ids[0],
            "relevant_topics=" + str(len(catalog)),
            "bytes=" + str(input_bytes),
            "fingerprint=" + fingerprint[:12],
        )
        schema = self._schema_for(expected_ids, fingerprint)
        raw = self._call(
            "prompts/nerv_daily_knowledge_curator.txt",
            packet,
            schema,
        )
        evidence_items = {
            str(item.get("knowledge_id") or ""): item
            for item in items
            if isinstance(item, dict) and item.get("knowledge_id")
        }
        assignments, errors = self._validate_plan(
            raw,
            expected_ids,
            catalog,
            evidence_items=evidence_items,
            expected_fingerprint=fingerprint,
        )
        if assignments is not None:
            self._last_plan_status = "PRIMARY_VALID"
            print(
                "[NERV KNOWLEDGE CURATOR DECISION]",
                "knowledge_id=" + expected_ids[0],
                "status=PRIMARY_VALID",
            )
            return assignments
        recovery_packet = {
            **packet,
            "contract_errors": errors,
            "recovery_mode": (
                "Fresh isolated decision. The invalid first response is "
                "intentionally absent and must not be reconstructed."
            ),
        }
        recovery_packet = self._fit_packet(recovery_packet)
        recovery_catalog = recovery_packet["relevant_topic_ecosystems"]
        print(
            "[NERV KNOWLEDGE CURATOR RETRY]",
            "knowledge_id=" + expected_ids[0],
            "errors=" + ",".join(errors),
            "bytes=" + str(self._packet_bytes(recovery_packet)),
        )
        recovered = self._call(
            "prompts/nerv_daily_knowledge_curator_recovery.txt",
            recovery_packet,
            schema,
            recovery=True,
        )
        assignments, errors = self._validate_plan(
            recovered,
            expected_ids,
            recovery_catalog,
            evidence_items=evidence_items,
            expected_fingerprint=fingerprint,
        )
        if assignments is None:
            repaired, repaired_ids = (
                self._repair_explicit_membership_relationships(
                    recovered,
                    evidence_items,
                    recovery_catalog,
                )
            )
            if repaired_ids:
                assignments, errors = self._validate_plan(
                    repaired,
                    expected_ids,
                    recovery_catalog,
                    evidence_items=evidence_items,
                    expected_fingerprint=fingerprint,
                )
                if assignments is not None:
                    print(
                        "[NERV KNOWLEDGE CURATOR EXPLICIT ROSTER REPAIR]",
                        "claims=" + str(len(repaired_ids)),
                        "relationships=" + str(sum(
                            len(item.get("related_entities", []))
                            for item in assignments
                            if str(item.get("knowledge_id") or "")
                            in repaired_ids
                        )),
                    )
        if assignments is None:
            raise ValueError("invalid_curator_plan:" + ",".join(errors))
        self._last_plan_status = "RECOVERED_VALID"
        print(
            "[NERV KNOWLEDGE CURATOR DECISION]",
            "knowledge_id=" + expected_ids[0],
            "status=RECOVERED_VALID",
        )
        return assignments

    @staticmethod
    def _reaudit_legacy_partition_lifecycles():
        """Correct pre-audit mixed claims before organizing topic copies."""
        from nerv import external_fact_fallback

        candidates = knowledge.load_partition_lifecycle_audit_candidates(
            limit=24
        )
        totals = {"audited": 0, "stable": 0, "reviewable": 0, "removed": 0}
        for offset in range(0, len(candidates), MAX_BATCH_ITEMS):
            batch = candidates[offset:offset + MAX_BATCH_ITEMS]
            print(
                "[NERV PARTITION LIFECYCLE REAUDIT BATCH]",
                "number=" + str((offset // MAX_BATCH_ITEMS) + 1),
                "items=" + str(len(batch)),
            )
            decisions = (
                external_fact_fallback.audit_existing_partition_lifecycles(
                    batch
                )
            )
            if not isinstance(decisions, list) or len(decisions) != len(batch):
                raise ValueError("partition_lifecycle_reaudit_invalid")
            counts = knowledge.apply_partition_lifecycle_reaudit(decisions)
            for key in totals:
                totals[key] += int(counts.get(key) or 0)
        if totals["audited"]:
            print(
                "[NERV PARTITION LIFECYCLE REAUDIT]",
                "audited=" + str(totals["audited"]),
                "stable=" + str(totals["stable"]),
                "reviewable=" + str(totals["reviewable"]),
                "removed=" + str(totals["removed"]),
            )
        return totals

    def run_once(self, force=False):
        """Classify the current pending snapshot, leaving failures untouched."""
        local_date = self._local_date()
        if not force and not self.due():
            return {"status": "SKIPPED", "reason": "not_due"}
        totals = {
            "curated": 0,
            "duplicate": 0,
            "conflict": 0,
            "deferred": 0,
            "inactive": 0,
            "primary_valid": 0,
            "recovered_valid": 0,
            "failed": 0,
        }
        lifecycle_totals = {
            "audited": 0,
            "stable": 0,
            "reviewable": 0,
            "removed": 0,
        }
        topic_autonomy = {
            "status": "SKIPPED",
            "reason": "topic_lifecycle_unavailable",
            "assessed": 0,
            "layered": 0,
            "classified": 0,
            "category_refined": 0,
            "failures": [],
        }
        try:
            lifecycle_totals = self._reaudit_legacy_partition_lifecycles()
            pending = knowledge.load_curation_inbox(
                pending_only=True
            )[:MAX_DAILY_ITEMS]
            autonomy_due = (
                self.topic_lifecycle is not None
                and self.topic_lifecycle.due()
            )
            if (
                not pending
                and not lifecycle_totals["audited"]
                and not autonomy_due
            ):
                return {"status": "SKIPPED", "reason": "empty_inbox"}
            processed_ids = []
            failures = []
            touched_topic_ids = []
            for offset in range(0, len(pending), MAX_BATCH_ITEMS):
                batch = pending[offset:offset + MAX_BATCH_ITEMS]
                batch_number = (offset // MAX_BATCH_ITEMS) + 1
                print(
                    "[NERV KNOWLEDGE CURATOR BATCH]",
                    "number=" + str(batch_number),
                    "items=" + str(len(batch)),
                    "remaining=" + str(max(
                        0, len(pending) - offset - len(batch)
                    )),
                )
                knowledge_id = str(
                    batch[0].get("knowledge_id") or ""
                ) if batch and isinstance(batch[0], dict) else ""
                try:
                    assignments = self._plan_batch(batch)
                    counts = knowledge.apply_curator_assignments(assignments)
                    for key in (
                        "curated", "duplicate", "conflict", "deferred",
                        "inactive",
                    ):
                        totals[key] += int(counts.get(key) or 0)
                    if self._last_plan_status == "PRIMARY_VALID":
                        totals["primary_valid"] += 1
                    elif self._last_plan_status == "RECOVERED_VALID":
                        totals["recovered_valid"] += 1
                    if knowledge_id:
                        processed_ids.append(knowledge_id)
                    for topic_id in counts.get("topic_ids", []):
                        if topic_id not in touched_topic_ids:
                            touched_topic_ids.append(topic_id)
                except Exception as error:
                    totals["failed"] += 1
                    failures.append({
                        "knowledge_id": knowledge_id[:160],
                        "error_type": type(error).__name__,
                        "error": str(error)[:500],
                    })
                    print(
                        "[NERV KNOWLEDGE CURATOR ITEM WARNING]",
                        "knowledge_id=" + knowledge_id,
                        repr(error),
                    )
            if self.curiosity is not None and processed_ids:
                self.curiosity.bind_curated_knowledge(
                    knowledge.topic_links_for_knowledge_ids(processed_ids)
                )
            if self.topic_lifecycle is not None:
                topic_autonomy = self.topic_lifecycle.run_once(
                    preferred_topic_ids=touched_topic_ids,
                    only_topic_ids=(touched_topic_ids or None),
                )
            details = {
                "curator_plan_contract_version": (
                    CURATOR_PLAN_CONTRACT_VERSION
                ),
                "curator_isolation_contract_version": (
                    CURATOR_ISOLATION_CONTRACT_VERSION
                ),
                **totals,
                "processed": len(pending),
                "committed": len(processed_ids),
                "failures": failures,
                "lifecycle_reaudit": lifecycle_totals,
                "topic_autonomy": topic_autonomy,
            }
            run_status = (
                "COMPLETED_WITH_ERRORS"
                if totals["failed"] and processed_ids
                else "FAILED"
                if totals["failed"]
                else "COMPLETED"
            )
            knowledge.record_curator_run(
                run_status, details=details, local_date=local_date
            )
            print(
                "[NERV KNOWLEDGE CURATOR]",
                "status=" + run_status,
                "processed=" + str(len(pending)),
                "committed=" + str(len(processed_ids)),
                "curated=" + str(totals["curated"]),
                "duplicates=" + str(totals["duplicate"]),
                "conflicts=" + str(totals["conflict"]),
                "failed=" + str(totals["failed"]),
            )
            return {"status": run_status, **details}
        except Exception as error:
            knowledge.record_curator_run(
                "FAILED",
                details={
                    "error_type": type(error).__name__,
                    "error": str(error)[:500],
                    **totals,
                    "lifecycle_reaudit": lifecycle_totals,
                    "topic_autonomy": topic_autonomy,
                },
                local_date=local_date,
            )
            print("[NERV KNOWLEDGE CURATOR WARNING]", repr(error))
            return {
                "status": "FAILED",
                "error": type(error).__name__,
                **totals,
                "lifecycle_reaudit": lifecycle_totals,
                "topic_autonomy": topic_autonomy,
            }
