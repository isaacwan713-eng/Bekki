"""Daily AI-owned organization of already-approved Bekki Knowledge records."""

from copy import deepcopy
from datetime import datetime
import json
import re

import knowledge


# Curator assignments are structurally rich (topic, entities, relations,
# keywords, and duplicate/conflict links).  A twelve-item response routinely
# exceeds Gemma's bounded output budget before the JSON object can close.  Keep
# semantic ownership with the model, but ask it to finish three complete
# decisions at a time and atomically commit each completed batch.
MAX_BATCH_ITEMS = 3
MAX_DAILY_ITEMS = 48
_SAFE_ID_RE = re.compile(r"^[a-z0-9][a-z0-9_-]{0,79}$")


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
    "maxLength": 120,
}
RELATED_ENTITY_SCHEMA["properties"]["claim_relation_evidence"] = {
    "type": "string",
    "minLength": 1,
    "maxLength": 300,
}
RELATED_ENTITY_SCHEMA["required"] = [
    "id", "name", "type", "aliases", "relation",
    "claim_relation_evidence",
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

    def __init__(self, model_call, unload_model=None):
        self.model_call = model_call
        self.unload_model = unload_model

    @staticmethod
    def _local_date():
        return datetime.now().astimezone().date().isoformat()

    def due(self):
        knowledge.initialize()
        if knowledge.load_partition_lifecycle_audit_candidates(limit=1):
            return True
        pending = knowledge.load_curation_inbox(pending_only=True)
        if not pending:
            return False
        runs = knowledge.load_curator_runs()
        if str(runs.get("last_successful_date") or "") != self._local_date():
            return True
        last_attempt = str(runs.get("last_attempt_at") or "")
        # A Curiosity answer may become verified after today's normal curator
        # pass.  Re-open only for records enqueued after that pass; an older
        # DEFER remains daily and cannot cause a tight retry loop.
        return any(
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
    def _schema_for(knowledge_ids):
        schema = deepcopy(CURATOR_PLAN_SCHEMA)
        schema["properties"]["assignments"]["minItems"] = len(knowledge_ids)
        schema["properties"]["assignments"]["maxItems"] = len(knowledge_ids)
        schema["properties"]["assignments"]["items"]["properties"][
            "knowledge_id"
        ] = {
            "type": "string",
            "enum": sorted(knowledge_ids),
        }
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
            compact.append({
                "knowledge_id": str(item.get("id") or "")[:160],
                "subject": str(item.get("subject") or "")[:300],
                "claim": str(item.get("claim") or "")[:3000],
                "topics": [str(value)[:80] for value in item.get("topics", [])[:12]],
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
                "provenance": item.get("provenance")
                if isinstance(item.get("provenance"), dict) else {},
                "display_context": {
                    "original_request": str(
                        verification.get("original_request")
                        or verification.get("original_question")
                        or ""
                    )[:2000],
                    "accepted_answer": str(
                        verification.get("accepted_answer")
                        or verification.get("answer")
                        or ""
                    )[:5000],
                    "evidence_canonical_answer": str(
                        verification.get("evidence_canonical_answer")
                        or verification.get("canonical_answer")
                        or source_context.get("canonical_answer")
                        or ""
                    )[:3000],
                    "evidence_answers": [
                        str(value)[:2000]
                        for value in verification.get("evidence_answers", [])[:6]
                        if str(value).strip()
                    ],
                    "source_titles": [
                        str(value.get("title") or "")[:300]
                        for value in item.get("sources", [])[:8]
                        if isinstance(value, dict)
                        and str(value.get("title") or "").strip()
                    ],
                },
            })
        return compact

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

    @classmethod
    def _validate_plan(cls, raw, expected_ids, catalog):
        errors = []
        if not isinstance(raw, dict) or not isinstance(raw.get("assignments"), list):
            return None, ["plan_or_assignments_invalid"]
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
        normalized = []
        for assignment in assignments:
            if not isinstance(assignment, dict):
                errors.append("assignment_not_object")
                continue
            item = deepcopy(assignment)
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
                for related in item.get("related_entities", []):
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
                    if not str(
                        related.get("claim_relation_evidence") or ""
                    ).strip():
                        errors.append("missing_claim_relation_evidence")
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

    def _call(self, prompt_path, packet, schema):
        try:
            return self.model_call(
                prompt_path,
                json.dumps(packet, ensure_ascii=False, separators=(",", ":")),
                expect_json=True,
                num_ctx=12288,
                num_predict=2600,
                think=False,
                model_name="gemma4:12b",
                json_schema=schema,
            )
        finally:
            self._release()

    def _plan_batch(self, entries):
        items = self._compact_items(entries)
        expected_ids = [str(item["knowledge_id"]) for item in items]
        if len(expected_ids) != len(entries):
            raise ValueError("pending_knowledge_missing")
        catalog = knowledge.load_topic_catalog(include_claims=True)
        packet = {
            "local_date": self._local_date(),
            "already_verified_items": items,
            "existing_topic_ecosystems": catalog,
            "immutable_rules": {
                "verification_may_not_be_changed": True,
                "changing_event_news_are_not_in_this_queue": True,
                "one_topic_document_is_a_broad_knowledge_ecosystem": True,
                "related_people_members_sister_groups_stay_together_when_semantically_coherent": True,
                "topic_co_location_never_merges_distinct_entities": True,
                "internal_units_are_not_sister_organizations_of_their_parent": True,
            },
        }
        schema = self._schema_for(expected_ids)
        raw = self._call(
            "prompts/nerv_daily_knowledge_curator.txt",
            packet,
            schema,
        )
        assignments, errors = self._validate_plan(raw, expected_ids, catalog)
        if assignments is not None:
            return assignments
        recovery_packet = {
            **packet,
            "invalid_first_plan": raw if isinstance(raw, dict) else None,
            "contract_errors": errors,
        }
        recovered = self._call(
            "prompts/nerv_daily_knowledge_curator_recovery.txt",
            recovery_packet,
            schema,
        )
        assignments, errors = self._validate_plan(
            recovered, expected_ids, catalog
        )
        if assignments is None:
            raise ValueError("invalid_curator_plan:" + ",".join(errors))
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
        }
        lifecycle_totals = {
            "audited": 0,
            "stable": 0,
            "reviewable": 0,
            "removed": 0,
        }
        try:
            lifecycle_totals = self._reaudit_legacy_partition_lifecycles()
            pending = knowledge.load_curation_inbox(
                pending_only=True
            )[:MAX_DAILY_ITEMS]
            if not pending and not lifecycle_totals["audited"]:
                return {"status": "SKIPPED", "reason": "empty_inbox"}
            for offset in range(0, len(pending), MAX_BATCH_ITEMS):
                batch = pending[offset:offset + MAX_BATCH_ITEMS]
                batch_number = (offset // MAX_BATCH_ITEMS) + 1
                print(
                    "[NERV KNOWLEDGE CURATOR BATCH]",
                    "number=" + str(batch_number),
                    "items=" + str(len(batch)),
                    "remaining=" + str(max(0, len(pending) - offset)),
                )
                assignments = self._plan_batch(batch)
                counts = knowledge.apply_curator_assignments(assignments)
                for key in totals:
                    totals[key] += int(counts.get(key) or 0)
            details = {
                **totals,
                "processed": len(pending),
                "lifecycle_reaudit": lifecycle_totals,
            }
            knowledge.record_curator_run(
                "COMPLETED", details=details, local_date=local_date
            )
            print(
                "[NERV KNOWLEDGE CURATOR]",
                "status=COMPLETED",
                "processed=" + str(len(pending)),
                "curated=" + str(totals["curated"]),
                "duplicates=" + str(totals["duplicate"]),
                "conflicts=" + str(totals["conflict"]),
            )
            return {"status": "COMPLETED", **details}
        except Exception as error:
            knowledge.record_curator_run(
                "FAILED",
                details={
                    "error_type": type(error).__name__,
                    "error": str(error)[:500],
                    **totals,
                    "lifecycle_reaudit": lifecycle_totals,
                },
                local_date=local_date,
            )
            print("[NERV KNOWLEDGE CURATOR WARNING]", repr(error))
            return {
                "status": "FAILED",
                "error": type(error).__name__,
                **totals,
                "lifecycle_reaudit": lifecycle_totals,
            }
