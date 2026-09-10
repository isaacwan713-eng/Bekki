"""AI-owned Knowledge layering, topic completion, pause, and refresh control."""

from copy import deepcopy
from datetime import datetime, timezone
import hashlib
import json

import knowledge


MAX_TOPICS_PER_RUN = 6
TOPIC_LIFECYCLE_ISOLATION_CONTRACT_VERSION = 1
MAX_TOPIC_LIFECYCLE_INPUT_BYTES = 12_000
MAX_TOPIC_CATEGORY_PATHS = 48
MAX_TOPIC_INTEREST_SIGNALS = 12


CLAIM_LAYER_SCHEMA = {
    "type": "object",
    "properties": {
        "knowledge_id": {"type": "string", "maxLength": 160},
        "knowledge_layer": {
            "type": "string",
            "enum": list(knowledge.KNOWLEDGE_LAYERS),
        },
        "reason": {"type": "string", "minLength": 1, "maxLength": 500},
    },
    "required": ["knowledge_id", "knowledge_layer", "reason"],
    "additionalProperties": False,
}


CATEGORY_NODE_SCHEMA = {
    "type": "object",
    "properties": {
        "id": {
            "type": "string",
            "maxLength": 80,
            "pattern": "^[a-z0-9][a-z0-9_-]{0,79}$",
        },
        "label": {"type": "string", "minLength": 1, "maxLength": 120},
    },
    "required": ["id", "label"],
    "additionalProperties": False,
}


TOPIC_CLASSIFICATION_SCHEMA = {
    "type": "object",
    "properties": {
        "version": {
            "type": "integer",
            "enum": [knowledge.KNOWLEDGE_CLASSIFICATION_VERSION],
        },
        "granularity_version": {
            "type": "integer",
            "enum": [knowledge.KNOWLEDGE_CATEGORY_GRANULARITY_VERSION],
        },
        "domain": {
            "type": "string",
            "enum": list(knowledge.KNOWLEDGE_CLASSIFICATION_DOMAINS),
        },
        "category_path": {
            "type": "array",
            "minItems": knowledge.KNOWLEDGE_CATEGORY_PATH_REQUIRED_DEPTH,
            "maxItems": knowledge.KNOWLEDGE_CATEGORY_PATH_REQUIRED_DEPTH,
            "items": CATEGORY_NODE_SCHEMA,
        },
        "reason": {"type": "string", "minLength": 1, "maxLength": 500},
    },
    "required": [
        "version",
        "granularity_version",
        "domain",
        "category_path",
        "reason",
    ],
    "additionalProperties": False,
}


CLAIM_CLASSIFICATION_SCHEMA = {
    "type": "object",
    "properties": {
        "knowledge_id": {"type": "string", "maxLength": 160},
        "fact_type": {
            "type": "string",
            "enum": list(knowledge.KNOWLEDGE_FACT_TYPES),
        },
        "reason": {"type": "string", "minLength": 1, "maxLength": 500},
    },
    "required": ["knowledge_id", "fact_type", "reason"],
    "additionalProperties": False,
}


COVERAGE_SCHEMA = {
    "type": "object",
    "properties": {
        "layer": {
            "type": "string",
            "enum": list(knowledge.KNOWLEDGE_LAYERS),
        },
        "status": {
            "type": "string",
            "enum": sorted(knowledge.TOPIC_COVERAGE_STATES),
        },
        "required_for_current_goal": {"type": "boolean"},
        "evidence_claim_ids": {
            "type": "array",
            "maxItems": 20,
            "items": {"type": "string", "maxLength": 160},
        },
        "reason": {"type": "string", "minLength": 1, "maxLength": 500},
    },
    "required": [
        "layer",
        "status",
        "required_for_current_goal",
        "evidence_claim_ids",
        "reason",
    ],
    "additionalProperties": False,
}


TOPIC_LIFECYCLE_PLAN_SCHEMA = {
    "type": "object",
    "properties": {
        "assessment_contract_version": {
            "type": "integer",
            "enum": [knowledge.TOPIC_LIFECYCLE_ASSESSMENT_CONTRACT_VERSION],
        },
        "assessment_fingerprint": {
            "type": "string",
            "minLength": 64,
            "maxLength": 64,
            "pattern": "^[a-f0-9]{64}$",
        },
        "topic_id": {"type": "string", "maxLength": 80},
        "claim_layers": {
            "type": "array",
            "maxItems": 8,
            "items": CLAIM_LAYER_SCHEMA,
        },
        "topic_classification": TOPIC_CLASSIFICATION_SCHEMA,
        "claim_classifications": {
            "type": "array",
            "maxItems": 8,
            "items": CLAIM_CLASSIFICATION_SCHEMA,
        },
        "target_layer": {
            "type": "string",
            "enum": list(knowledge.KNOWLEDGE_LAYERS),
        },
        "coverage": {
            "type": "array",
            "minItems": len(knowledge.KNOWLEDGE_LAYERS),
            "maxItems": len(knowledge.KNOWLEDGE_LAYERS),
            "items": COVERAGE_SCHEMA,
        },
        "completion_score": {"type": "number", "minimum": 0, "maximum": 1},
        "confidence": {"type": "number", "minimum": 0, "maximum": 1},
        "state": {
            "type": "string",
            "enum": sorted(knowledge.TOPIC_LIFECYCLE_STATES),
        },
        "next_focus": {"type": "string", "maxLength": 500},
        "pause_reason": {"type": "string", "maxLength": 500},
        "interest_score": {"type": "number", "minimum": 0, "maximum": 1},
        "interest_basis": {"type": "string", "minLength": 1, "maxLength": 500},
        "refresh_after_days": {
            "anyOf": [
                {"type": "null"},
                {
                    "type": "integer",
                    "minimum": knowledge.TOPIC_REFRESH_MIN_DAYS,
                    "maximum": knowledge.TOPIC_REFRESH_MAX_DAYS,
                },
            ]
        },
        "reason": {"type": "string", "minLength": 1, "maxLength": 800},
    },
    "required": [
        "assessment_contract_version",
        "assessment_fingerprint",
        "topic_id",
        "claim_layers",
        "topic_classification",
        "claim_classifications",
        "target_layer",
        "coverage",
        "completion_score",
        "confidence",
        "state",
        "next_focus",
        "pause_reason",
        "interest_score",
        "interest_basis",
        "refresh_after_days",
        "reason",
    ],
    "additionalProperties": False,
}


class TopicLifecycleManager:
    """Let AI judge semantic maturity while Python enforces state transitions."""

    def __init__(self, model_call, unload_model=None, curiosity_journal=None):
        self.model_call = model_call
        self.unload_model = unload_model
        self.curiosity = curiosity_journal
        self._last_assessment_status = ""
        self._last_input_bytes = 0

    def _release(self):
        if self.unload_model is None:
            return
        try:
            self.unload_model("gemma4:12b")
            print("[NERV TOPIC LIFECYCLE MODEL RELEASED] gemma4:12b")
        except Exception as error:
            print("[NERV TOPIC LIFECYCLE RELEASE WARNING]", repr(error))

    @staticmethod
    def _schema_for(candidate):
        schema = deepcopy(TOPIC_LIFECYCLE_PLAN_SCHEMA)
        topic_id = str(candidate.get("topic_id") or "")
        pending_ids = [
            str(value)
            for value in candidate.get("pending_layer_claim_ids", [])
            if str(value)
        ]
        schema["properties"]["topic_id"] = {
            "type": "string",
            "enum": [topic_id],
        }
        fingerprint = str(candidate.get("assessment_fingerprint") or "")
        schema["properties"]["assessment_fingerprint"] = {
            "type": "string",
            "enum": [fingerprint],
        }
        claim_layers = schema["properties"]["claim_layers"]
        claim_layers["minItems"] = len(pending_ids)
        claim_layers["maxItems"] = len(pending_ids)
        if pending_ids:
            claim_layers["items"]["properties"]["knowledge_id"] = {
                "type": "string",
                "enum": sorted(pending_ids),
            }
        pending_classification_ids = [
            str(value)
            for value in candidate.get(
                "pending_classification_claim_ids", []
            )
            if str(value)
        ]
        claim_classifications = schema["properties"][
            "claim_classifications"
        ]
        claim_classifications["minItems"] = len(
            pending_classification_ids
        )
        claim_classifications["maxItems"] = len(
            pending_classification_ids
        )
        if pending_classification_ids:
            claim_classifications["items"]["properties"]["knowledge_id"] = {
                "type": "string",
                "enum": sorted(pending_classification_ids),
            }
        known_ids = [
            str(value.get("knowledge_id") or "")
            for value in candidate.get("claims", [])
            if isinstance(value, dict) and value.get("knowledge_id")
        ]
        coverage_items = schema["properties"]["coverage"]["items"]
        if known_ids:
            coverage_items["properties"]["evidence_claim_ids"]["items"] = {
                "type": "string",
                "enum": sorted(set(known_ids)),
            }
        else:
            coverage_items["properties"]["evidence_claim_ids"]["maxItems"] = 0
        return schema

    def _interest_signals(self, topic_id):
        if self.curiosity is None:
            return []
        try:
            return self.curiosity.topic_interest_signals(topic_id)
        except Exception as error:
            print("[NERV TOPIC INTEREST WARNING]", repr(error))
            return []

    @staticmethod
    def _interest_fingerprint(signals):
        compact = [
            {
                "id": str(value.get("id") or "")[:120],
                "state": str(value.get("state") or "")[:40],
                "interest_score": value.get("interest_score"),
                "created_at": str(value.get("created_at") or "")[:80],
                "verified_at": str(value.get("verified_at") or "")[:80],
            }
            for value in signals
            if isinstance(value, dict)
        ]
        return hashlib.sha256(
            json.dumps(
                compact,
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
            ).encode("utf-8")
        ).hexdigest()

    @staticmethod
    def _packet_bytes(packet):
        return len(json.dumps(
            packet,
            ensure_ascii=False,
            separators=(",", ":"),
        ).encode("utf-8"))

    @staticmethod
    def _compact_interest_signals(signals):
        """Keep interest evidence useful without letting old prose fill context."""

        output = []
        for value in list(signals or [])[-MAX_TOPIC_INTEREST_SIGNALS:]:
            if not isinstance(value, dict):
                continue
            output.append({
                "id": str(value.get("id") or "")[:120],
                "question": " ".join(
                    str(value.get("question") or "").split()
                )[:180],
                "state": str(value.get("state") or "")[:40],
                "interest_score": value.get("interest_score"),
                "question_depth": str(
                    value.get("question_depth") or ""
                )[:40],
                "seed_kind": str(value.get("seed_kind") or "")[:60],
                "wake_reason": str(value.get("wake_reason") or "")[:60],
                "created_at": str(value.get("created_at") or "")[:80],
                "verified_at": str(value.get("verified_at") or "")[:80],
                "verification_status": str(
                    value.get("verification_status") or ""
                )[:40],
            })
        return output

    @staticmethod
    def _compact_category_catalog(rows):
        """Expose reusable taxonomy paths, never other Topic claim content."""

        output = []
        seen = set()
        for raw in rows or []:
            if not isinstance(raw, dict):
                continue
            normalized = knowledge.normalize_topic_classification({
                "version": raw.get(
                    "version", knowledge.KNOWLEDGE_CLASSIFICATION_VERSION
                ),
                "granularity_version": raw.get(
                    "granularity_version",
                    knowledge.KNOWLEDGE_CATEGORY_GRANULARITY_VERSION,
                ),
                "domain": raw.get("domain"),
                "category_path": raw.get("category_path"),
            })
            if not normalized:
                continue
            identity = knowledge.topic_classification_identity(normalized)
            if identity in seen:
                continue
            seen.add(identity)
            output.append({
                "version": normalized["version"],
                "granularity_version": normalized["granularity_version"],
                "domain": normalized["domain"],
                "category_path": deepcopy(normalized["category_path"]),
            })
            if len(output) >= MAX_TOPIC_CATEGORY_PATHS:
                break
        return output

    @staticmethod
    def _compact_candidate(candidate):
        """Copy one Topic snapshot while removing write-history bulk."""

        candidate = candidate if isinstance(candidate, dict) else {}
        claims = []
        for raw in candidate.get("claims", []):
            if not isinstance(raw, dict):
                continue
            claims.append({
                "knowledge_id": str(raw.get("knowledge_id") or "")[:160],
                "subject": " ".join(
                    str(raw.get("subject") or "").split()
                )[:240],
                "claim": " ".join(
                    str(raw.get("claim") or "").split()
                )[:420],
                "facet": str(raw.get("facet") or "")[:120],
                "relationship_ids": [
                    str(value)[:120]
                    for value in raw.get("relationship_ids", [])[:16]
                ],
                "has_relationships": raw.get("has_relationships") is True,
                "knowledge_layer": str(
                    raw.get("knowledge_layer") or ""
                )[:40],
                "fact_type": str(raw.get("fact_type") or "")[:40],
                "knowledge_type": str(
                    raw.get("knowledge_type") or "stable"
                )[:30],
                "expires_at": raw.get("expires_at"),
                "temporal_scope": (
                    deepcopy(raw.get("temporal_scope"))
                    if isinstance(raw.get("temporal_scope"), dict) else {}
                ),
            })
        lifecycle = candidate.get("existing_lifecycle")
        lifecycle = lifecycle if isinstance(lifecycle, dict) else {}
        existing_lifecycle = {
            "version": lifecycle.get("version"),
            "state": str(lifecycle.get("state") or "")[:40],
            "target_layer": str(lifecycle.get("target_layer") or "")[:40],
            "completion_score": lifecycle.get("completion_score"),
            "confidence": lifecycle.get("confidence"),
            "coverage": deepcopy(lifecycle.get("coverage") or []),
            "interest_score": lifecycle.get("interest_score"),
            "interest_basis": " ".join(
                str(lifecycle.get("interest_basis") or "").split()
            )[:300],
            "next_focus": " ".join(
                str(lifecycle.get("next_focus") or "").split()
            )[:300],
            "pause_reason": " ".join(
                str(lifecycle.get("pause_reason") or "").split()
            )[:300],
            "reason": " ".join(
                str(lifecycle.get("reason") or "").split()
            )[:400],
            "refresh": (
                deepcopy(lifecycle.get("refresh"))
                if isinstance(lifecycle.get("refresh"), dict) else {}
            ),
        }
        return {
            "topic_id": str(candidate.get("topic_id") or "")[:80],
            "title": " ".join(
                str(candidate.get("title") or "").split()
            )[:200],
            "aliases": [
                str(value)[:120]
                for value in candidate.get("aliases", [])[:12]
            ],
            "keywords": [
                str(value)[:120]
                for value in candidate.get("keywords", [])[:18]
            ],
            "claims": claims,
            "claim_count": candidate.get("claim_count"),
            "context_complete": candidate.get("context_complete") is True,
            "layer_counts": deepcopy(candidate.get("layer_counts") or {}),
            "pending_layer_claim_ids": [
                str(value)[:160]
                for value in candidate.get("pending_layer_claim_ids", [])[:8]
            ],
            "pending_layer_total": candidate.get("pending_layer_total"),
            "pending_classification_claim_ids": [
                str(value)[:160]
                for value in candidate.get(
                    "pending_classification_claim_ids", []
                )[:8]
            ],
            "pending_classification_total": candidate.get(
                "pending_classification_total"
            ),
            "existing_classification": (
                deepcopy(candidate.get("existing_classification"))
                if isinstance(candidate.get("existing_classification"), dict)
                else {}
            ),
            "classification_refinement_required": (
                candidate.get("classification_refinement_required") is True
            ),
            "classification_only_refinement": (
                candidate.get("classification_only_refinement") is True
            ),
            "assessment_fingerprint": str(
                candidate.get("assessment_fingerprint") or ""
            )[:64],
            "existing_lifecycle": existing_lifecycle,
            "updated_at": str(candidate.get("updated_at") or "")[:80],
        }

    @classmethod
    def _fit_packet(cls, packet):
        """Bound optional context without ever dropping Topic claim IDs."""

        fitted = deepcopy(packet)
        while cls._packet_bytes(fitted) > MAX_TOPIC_LIFECYCLE_INPUT_BYTES:
            changed = False
            catalog = fitted.get("existing_category_catalog")
            if isinstance(catalog, list) and catalog:
                catalog.pop()
                changed = True
            if not changed:
                signals = fitted.get("curiosity_interest_signals")
                if isinstance(signals, list) and len(signals) > 1:
                    signals.pop(0)
                    changed = True
            if not changed:
                topic = fitted.get("topic")
                topic = topic if isinstance(topic, dict) else {}
                for field in ("keywords", "aliases"):
                    values = topic.get(field)
                    if isinstance(values, list) and values:
                        values.pop()
                        changed = True
                        break
            if not changed:
                topic = fitted.get("topic")
                topic = topic if isinstance(topic, dict) else {}
                claims = topic.get("claims")
                claims = claims if isinstance(claims, list) else []
                long_claim = next(
                    (
                        value for value in reversed(claims)
                        if isinstance(value, dict)
                        and len(str(value.get("claim") or "")) > 180
                    ),
                    None,
                )
                if long_claim is not None:
                    long_claim["claim"] = str(long_claim["claim"])[:180]
                    changed = True
            if not changed:
                raise ValueError("topic_lifecycle_packet_too_large")
        return fitted

    def _interest_changed_topic_ids(self, include_topic_ids=None):
        allowed_topics = {
            str(value or "").lower().strip()
            for value in include_topic_ids or []
            if str(value or "").strip()
        }
        changed = []
        for topic in knowledge.load_topic_catalog(
            include_claims=False,
            max_topics=200,
        ):
            if not isinstance(topic, dict):
                continue
            topic_id = str(topic.get("topic_id") or "")
            if allowed_topics and topic_id not in allowed_topics:
                continue
            lifecycle = topic.get("lifecycle")
            lifecycle = lifecycle if isinstance(lifecycle, dict) else {}
            current = self._interest_fingerprint(
                self._interest_signals(topic_id)
            )
            if str(lifecycle.get("interest_fingerprint") or "") != current:
                changed.append(topic_id)
        return changed

    def due(self):
        changed = self._interest_changed_topic_ids()
        if knowledge.load_topic_lifecycle_assessment_candidates(
            limit=1,
            force_topic_ids=changed,
        ):
            return True
        if self.curiosity and self.curiosity.open_lifecycle_topic_ids():
            return False
        open_topics = self.curiosity.open_topic_ids() if self.curiosity else []
        return bool(knowledge.load_topic_refresh_candidates(
            exclude_topic_ids=open_topics,
            limit=1,
        ))

    @staticmethod
    def _normalize_score(value, field, errors):
        if isinstance(value, bool):
            errors.append(field + "_invalid")
            return 0.0
        try:
            score = float(value)
        except (TypeError, ValueError):
            errors.append(field + "_invalid")
            return 0.0
        if not 0 <= score <= 1:
            errors.append(field + "_out_of_range")
        return max(0.0, min(1.0, score))

    @classmethod
    def _validate_plan(cls, raw, candidate, category_catalog=None):
        errors = []
        if not isinstance(raw, dict):
            return None, ["plan_invalid"]
        normalized = deepcopy(raw)
        try:
            contract_version = int(
                normalized.get("assessment_contract_version") or 0
            )
        except (TypeError, ValueError):
            contract_version = 0
        normalized["assessment_contract_version"] = contract_version
        if contract_version != (
            knowledge.TOPIC_LIFECYCLE_ASSESSMENT_CONTRACT_VERSION
        ):
            errors.append("assessment_contract_version_mismatch")
        fingerprint = str(
            normalized.get("assessment_fingerprint") or ""
        ).lower().strip()
        normalized["assessment_fingerprint"] = fingerprint
        expected_fingerprint = str(
            candidate.get("assessment_fingerprint") or ""
        ).lower().strip()
        if (
            len(fingerprint) != 64
            or fingerprint != expected_fingerprint
        ):
            errors.append("assessment_fingerprint_mismatch")
        topic_id = str(normalized.get("topic_id") or "").lower().strip()
        normalized["topic_id"] = topic_id
        if topic_id != str(candidate.get("topic_id") or ""):
            errors.append("topic_id_mismatch")

        pending_ids = [
            str(value)
            for value in candidate.get("pending_layer_claim_ids", [])
            if str(value)
        ]
        relationship_claim_ids = {
            str(value.get("knowledge_id") or "")
            for value in candidate.get("claims", [])
            if isinstance(value, dict)
            and value.get("has_relationships") is True
        }
        claim_layers = normalized.get("claim_layers")
        if not isinstance(claim_layers, list):
            claim_layers = []
            errors.append("claim_layers_invalid")
        returned_ids = []
        for layer_plan in claim_layers:
            if not isinstance(layer_plan, dict):
                errors.append("claim_layer_invalid")
                continue
            knowledge_id = str(layer_plan.get("knowledge_id") or "")
            layer = str(layer_plan.get("knowledge_layer") or "").upper()
            layer_plan["knowledge_id"] = knowledge_id
            layer_plan["knowledge_layer"] = layer
            returned_ids.append(knowledge_id)
            if layer not in knowledge.KNOWLEDGE_LAYERS:
                errors.append("knowledge_layer_invalid")
            if (
                knowledge_id in relationship_claim_ids
                and layer != "L3_RELATIONSHIPS"
            ):
                errors.append("relationship_claim_not_l3")
            if not str(layer_plan.get("reason") or "").strip():
                errors.append("knowledge_layer_reason_missing")
        if (
            len(returned_ids) != len(set(returned_ids))
            or set(returned_ids) != set(pending_ids)
        ):
            errors.append("claim_layer_ids_mismatch")
        normalized["claim_layers"] = claim_layers

        topic_classification = knowledge.normalize_topic_classification(
            normalized.get("topic_classification")
        )
        if (
            not topic_classification
            or not knowledge.topic_classification_is_current(
                topic_classification
            )
        ):
            errors.append("topic_classification_invalid")
            topic_classification = {}
        elif not str(topic_classification.get("reason") or "").strip():
            errors.append("topic_classification_reason_missing")
        existing_classification = knowledge.normalize_topic_classification(
            candidate.get("existing_classification")
        )
        if topic_classification and existing_classification:
            if knowledge.topic_classification_is_current(
                existing_classification
            ):
                if (
                    knowledge.topic_classification_identity(
                        existing_classification
                    )
                    != knowledge.topic_classification_identity(
                        topic_classification
                    )
                ):
                    errors.append("topic_classification_locked")
            elif not knowledge.topic_classification_preserves_prefix(
                existing_classification,
                topic_classification,
            ):
                errors.append("topic_classification_refinement_prefix_changed")
        if topic_classification:
            errors.extend(knowledge.category_catalog_conflicts(
                topic_classification,
                category_catalog=category_catalog,
            ))
        normalized["topic_classification"] = topic_classification

        pending_classification_ids = [
            str(value)
            for value in candidate.get(
                "pending_classification_claim_ids", []
            )
            if str(value)
        ]
        claim_classifications = normalized.get("claim_classifications")
        if not isinstance(claim_classifications, list):
            claim_classifications = []
            errors.append("claim_classifications_invalid")
        returned_classification_ids = []
        for plan in claim_classifications:
            if not isinstance(plan, dict):
                errors.append("claim_classification_invalid")
                continue
            knowledge_id = str(plan.get("knowledge_id") or "")
            fact_type = str(plan.get("fact_type") or "").upper()
            plan["knowledge_id"] = knowledge_id
            plan["fact_type"] = fact_type
            returned_classification_ids.append(knowledge_id)
            if fact_type not in knowledge.KNOWLEDGE_FACT_TYPES:
                errors.append("fact_type_invalid")
            if (
                knowledge_id in relationship_claim_ids
                and fact_type != "RELATIONSHIP"
            ):
                errors.append("relationship_fact_type_invalid")
            if not str(plan.get("reason") or "").strip():
                errors.append("fact_type_reason_missing")
        if (
            len(returned_classification_ids)
            != len(set(returned_classification_ids))
            or set(returned_classification_ids)
            != set(pending_classification_ids)
        ):
            errors.append("claim_classification_ids_mismatch")
        normalized["claim_classifications"] = claim_classifications

        known_ids = {
            str(value.get("knowledge_id") or "")
            for value in candidate.get("claims", [])
            if isinstance(value, dict)
        }
        coverage = normalized.get("coverage")
        if not isinstance(coverage, list):
            coverage = []
            errors.append("coverage_invalid")
        coverage_layers = []
        required_gaps = []
        for coverage_item in coverage:
            if not isinstance(coverage_item, dict):
                errors.append("coverage_item_invalid")
                continue
            layer = str(coverage_item.get("layer") or "").upper()
            status = str(coverage_item.get("status") or "").upper()
            coverage_item["layer"] = layer
            coverage_item["status"] = status
            coverage_layers.append(layer)
            if layer not in knowledge.KNOWLEDGE_LAYERS:
                errors.append("coverage_layer_invalid")
            if status not in knowledge.TOPIC_COVERAGE_STATES:
                errors.append("coverage_status_invalid")
            required = coverage_item.get("required_for_current_goal")
            if not isinstance(required, bool):
                errors.append("coverage_required_flag_invalid")
            evidence_ids = [
                str(value)
                for value in coverage_item.get("evidence_claim_ids", [])
                if str(value)
            ]
            coverage_item["evidence_claim_ids"] = evidence_ids
            if not set(evidence_ids).issubset(known_ids):
                errors.append("coverage_evidence_unknown")
            if not str(coverage_item.get("reason") or "").strip():
                errors.append("coverage_reason_missing")
            if required is True and status in {"MISSING", "PARTIAL"}:
                required_gaps.append(layer)
        if (
            len(coverage_layers) != len(knowledge.KNOWLEDGE_LAYERS)
            or set(coverage_layers) != set(knowledge.KNOWLEDGE_LAYERS)
        ):
            errors.append("coverage_layers_mismatch")
        normalized["coverage"] = coverage

        target_layer = str(normalized.get("target_layer") or "").upper()
        normalized["target_layer"] = target_layer
        if target_layer not in knowledge.KNOWLEDGE_LAYERS:
            errors.append("target_layer_invalid")
        completion = cls._normalize_score(
            normalized.get("completion_score"), "completion_score", errors
        )
        confidence = cls._normalize_score(
            normalized.get("confidence"), "confidence", errors
        )
        interest = cls._normalize_score(
            normalized.get("interest_score"), "interest_score", errors
        )
        normalized["completion_score"] = completion
        normalized["confidence"] = confidence
        normalized["interest_score"] = interest
        if not str(normalized.get("interest_basis") or "").strip():
            errors.append("interest_basis_missing")
        if not str(normalized.get("reason") or "").strip():
            errors.append("reason_missing")

        state = str(normalized.get("state") or "").upper()
        normalized["state"] = state
        if state not in knowledge.TOPIC_LIFECYCLE_STATES:
            errors.append("state_invalid")
        remaining_after_batch = max(
            0,
            int(candidate.get("pending_layer_total") or 0) - len(pending_ids),
        )
        context_complete = candidate.get("context_complete") is True
        next_focus = str(normalized.get("next_focus") or "").strip()
        pause_reason = str(normalized.get("pause_reason") or "").strip()
        refresh_days = normalized.get("refresh_after_days")
        if state == "PAUSED_COMPLETE":
            if remaining_after_batch or not context_complete:
                errors.append("pause_before_complete_context")
            if completion < 0.75:
                errors.append("pause_score_too_low")
            if required_gaps:
                errors.append("pause_with_required_gap")
            if not pause_reason:
                errors.append("pause_reason_missing")
            if next_focus:
                errors.append("paused_topic_has_next_focus")
            if (
                not isinstance(refresh_days, int)
                or isinstance(refresh_days, bool)
                or not knowledge.TOPIC_REFRESH_MIN_DAYS
                <= refresh_days
                <= knowledge.TOPIC_REFRESH_MAX_DAYS
            ):
                errors.append("refresh_interval_invalid")
        elif state == "ACTIVE":
            if not next_focus:
                errors.append("active_topic_missing_next_focus")
            if not required_gaps and not remaining_after_batch and context_complete:
                errors.append("active_topic_missing_required_gap")
            if refresh_days is not None:
                errors.append("active_topic_has_refresh_interval")
        if errors:
            return None, sorted(set(errors))
        return normalized, []

    def _call(self, prompt_path, packet, schema):
        try:
            return self.model_call(
                prompt_path,
                json.dumps(packet, ensure_ascii=False, separators=(",", ":")),
                expect_json=True,
                num_ctx=8192,
                num_predict=2600,
                think=False,
                model_name="gemma4:12b",
                json_schema=schema,
            )
        finally:
            self._release()

    def _assess(self, candidate, signals):
        self._last_assessment_status = ""
        category_catalog = knowledge.load_category_catalog()
        compact_catalog = self._compact_category_catalog(category_catalog)
        compact_signals = self._compact_interest_signals(signals)
        packet = self._fit_packet({
            "topic_lifecycle_isolation_contract_version": (
                TOPIC_LIFECYCLE_ISOLATION_CONTRACT_VERSION
            ),
            "required_assessment_contract_version": (
                knowledge.TOPIC_LIFECYCLE_ASSESSMENT_CONTRACT_VERSION
            ),
            "required_assessment_fingerprint": str(
                candidate.get("assessment_fingerprint") or ""
            ),
            "local_date": datetime.now().astimezone().date().isoformat(),
            "topic": self._compact_candidate(candidate),
            "curiosity_interest_signals": compact_signals,
            "existing_category_catalog": compact_catalog,
            "layer_contract": {
                "layers": list(knowledge.KNOWLEDGE_LAYERS),
                "layer_version": knowledge.KNOWLEDGE_LAYER_VERSION,
                "topic_lifecycle_version": knowledge.TOPIC_LIFECYCLE_VERSION,
                "pause_threshold": 0.75,
                "refresh_days_min": knowledge.TOPIC_REFRESH_MIN_DAYS,
                "refresh_days_max": knowledge.TOPIC_REFRESH_MAX_DAYS,
            },
            "classification_contract": {
                "version": knowledge.KNOWLEDGE_CLASSIFICATION_VERSION,
                "granularity_version": (
                    knowledge.KNOWLEDGE_CATEGORY_GRANULARITY_VERSION
                ),
                "domains": list(
                    knowledge.KNOWLEDGE_CLASSIFICATION_DOMAINS
                ),
                "fact_types": list(knowledge.KNOWLEDGE_FACT_TYPES),
                "category_path_max_depth": (
                    knowledge.KNOWLEDGE_CATEGORY_PATH_MAX_DEPTH
                ),
                "category_path_required_depth": (
                    knowledge.KNOWLEDGE_CATEGORY_PATH_REQUIRED_DEPTH
                ),
                "reuse_existing_category_ids_first": True,
                "current_paths_are_locked": True,
                "legacy_paths_must_be_preserved_as_prefix": True,
            },
            "output_requirement": (
                "Return one assessment for the exact topic_id and exact pending "
                "Knowledge IDs. Echo required_assessment_contract_version and "
                "required_assessment_fingerprint. Return JSON only."
            ),
        })
        self._last_input_bytes = self._packet_bytes(packet)
        print(
            "[NERV TOPIC LIFECYCLE INPUT]",
            "topic=" + str(candidate.get("topic_id") or ""),
            "claims=" + str(len(candidate.get("claims", []))),
            "bytes=" + str(self._last_input_bytes),
            "fingerprint=" + str(
                candidate.get("assessment_fingerprint") or ""
            )[:12],
        )
        schema = self._schema_for(candidate)
        raw = self._call(
            "prompts/nerv_topic_lifecycle.txt",
            packet,
            schema,
        )
        assessment, errors = self._validate_plan(
            raw,
            candidate,
            category_catalog=category_catalog,
        )
        if assessment is not None:
            self._last_assessment_status = "PRIMARY_VALID"
            print(
                "[NERV TOPIC LIFECYCLE DECISION]",
                "topic=" + str(candidate.get("topic_id") or ""),
                "status=PRIMARY_VALID",
            )
            return assessment
        recovery_packet = self._fit_packet({
            **packet,
            "contract_errors": errors,
            "recovery_mode": (
                "Fresh isolated assessment. The invalid first response is "
                "intentionally absent and must not be reconstructed."
            ),
        })
        print(
            "[NERV TOPIC LIFECYCLE RETRY]",
            "topic=" + str(candidate.get("topic_id") or ""),
            "errors=" + ",".join(errors),
            "bytes=" + str(self._packet_bytes(recovery_packet)),
        )
        recovered = self._call(
            "prompts/nerv_topic_lifecycle_recovery.txt",
            recovery_packet,
            schema,
        )
        assessment, errors = self._validate_plan(
            recovered,
            candidate,
            category_catalog=category_catalog,
        )
        if assessment is None:
            raise ValueError("invalid_topic_lifecycle_plan:" + ",".join(errors))
        self._last_assessment_status = "RECOVERED_VALID"
        print(
            "[NERV TOPIC LIFECYCLE DECISION]",
            "topic=" + str(candidate.get("topic_id") or ""),
            "status=RECOVERED_VALID",
        )
        return assessment

    def _seed_one(self, assessments, eligible_topic_ids=None):
        if self.curiosity is None:
            return {"status": "SKIPPED", "reason": "curiosity_unavailable"}
        if self.curiosity.open_lifecycle_topic_ids():
            return {"status": "SKIPPED", "reason": "lifecycle_question_already_open"}
        open_topics = set(self.curiosity.open_topic_ids())
        allowed_topics = {
            str(value or "").lower().strip()
            for value in eligible_topic_ids or []
            if str(value or "").strip()
        }
        eligible = []
        for result in assessments:
            if (
                not isinstance(result, dict)
                or result.get("classification_only_refinement") is True
                or result.get("state") != "ACTIVE"
                or result.get("assessment_complete") is not True
                or result.get("topic_id") in open_topics
                or (
                    allowed_topics
                    and str(result.get("topic_id") or "") not in allowed_topics
                )
            ):
                continue
            seed = knowledge.load_topic_curiosity_seed(result.get("topic_id"))
            if not isinstance(seed, dict):
                continue
            refresh = seed.get("lifecycle", {}).get("refresh", {})
            refresh = refresh if isinstance(refresh, dict) else {}
            retry_at = self._parse_time(refresh.get("next_attempt_at"))
            if retry_at is not None and retry_at > datetime.now(timezone.utc):
                continue
            seed["seed_kind"] = "TOPIC_GAP"
            seed["wake_reason"] = "OPEN_GAP"
            eligible.append(seed)
        for seed in knowledge.load_topic_refresh_candidates(
            exclude_topic_ids=open_topics,
            limit=200 if allowed_topics else 6,
        ):
            if (
                allowed_topics
                and str(seed.get("topic_id") or "") not in allowed_topics
            ):
                continue
            seed["seed_kind"] = "TOPIC_REFRESH"
            eligible.append(seed)
        if not eligible:
            return {"status": "SKIPPED", "reason": "no_topic_seed_due"}
        eligible.sort(key=lambda value: (
            0 if value.get("wake_reason") in {
                "REVIEW_DUE", "AUTO_INTEREST_REFRESH"
            } else 1,
            -float((value.get("lifecycle") or {}).get("interest_score") or 0),
            str(value.get("due_at") or ""),
            str(value.get("topic_id") or ""),
        ))
        selected = eligible[0]
        result = self.curiosity.observe_topic_lifecycle(selected)
        status = "DRAFTED" if result.get("status") == "drafted" else "NO_QUESTION"
        knowledge.record_topic_seed_attempt(
            selected.get("topic_id"),
            status,
            curiosity_id=result.get("id"),
        )
        return {
            **result,
            "topic_id": selected.get("topic_id"),
            "seed_kind": selected.get("seed_kind"),
            "wake_reason": selected.get("wake_reason"),
        }

    @staticmethod
    def _parse_time(value):
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

    def run_once(self, preferred_topic_ids=None, only_topic_ids=None):
        restricted = {
            str(value or "").lower().strip()
            for value in only_topic_ids or []
            if str(value or "").strip()
        }
        changed = self._interest_changed_topic_ids(
            include_topic_ids=restricted,
        )
        candidates = knowledge.load_topic_lifecycle_assessment_candidates(
            limit=MAX_TOPICS_PER_RUN,
            preferred_topic_ids=preferred_topic_ids,
            force_topic_ids=(
                [value for value in changed if not restricted or value in restricted]
            ),
            include_topic_ids=restricted,
        )
        assessments = []
        failures = []
        layered = 0
        classified = 0
        category_refined = 0
        primary_valid = 0
        recovered_valid = 0
        for candidate in candidates:
            topic_id = str(candidate.get("topic_id") or "")
            signals = self._interest_signals(topic_id)
            try:
                assessment = self._assess(candidate, signals)
                if self._last_assessment_status == "PRIMARY_VALID":
                    primary_valid += 1
                elif self._last_assessment_status == "RECOVERED_VALID":
                    recovered_valid += 1
                assessment["_interest_fingerprint"] = (
                    self._interest_fingerprint(signals)
                )
                assessment["_classification_only_refinement"] = (
                    candidate.get("classification_only_refinement") is True
                )
                saved = knowledge.apply_topic_lifecycle_assessment(assessment)
                assessments.append(saved)
                layered += int(saved.get("layered") or 0)
                classified += int(saved.get("classified") or 0)
                category_refined += int(
                    saved.get("category_refined") is True
                )
                print(
                    "[NERV TOPIC LIFECYCLE]",
                    "topic=" + topic_id,
                    "state=" + str(saved.get("state") or "unknown"),
                    "completion=" + str(saved.get("completion_score")),
                    "layered=" + str(saved.get("layered") or 0),
                    "classified=" + str(saved.get("classified") or 0),
                    "category_refined=" + str(
                        saved.get("category_refined") is True
                    ).lower(),
                )
            except Exception as error:
                failures.append({
                    "topic_id": topic_id,
                    "error": type(error).__name__,
                    "detail": str(error)[:500],
                })
                print("[NERV TOPIC LIFECYCLE WARNING]", topic_id, repr(error))
        if self.curiosity is not None and candidates:
            try:
                links = knowledge.topic_links_for_knowledge_ids()
                self.curiosity.bind_curated_knowledge(links)
            except Exception as error:
                failures.append({
                    "topic_id": "",
                    "error": "CuriosityBindError",
                    "detail": str(error)[:500],
                })
        try:
            seed = self._seed_one(
                assessments,
                eligible_topic_ids=restricted,
            )
        except Exception as error:
            seed = {"status": "failed", "reason": type(error).__name__}
            failures.append({
                "topic_id": "",
                "error": "TopicSeedError",
                "detail": str(error)[:500],
            })
            print("[NERV TOPIC SEED WARNING]", repr(error))
        if not candidates and seed.get("status") == "SKIPPED":
            status = "SKIPPED"
        elif failures and not assessments and seed.get("status") != "drafted":
            status = "FAILED"
        elif failures:
            status = "COMPLETED_WITH_ERRORS"
        else:
            status = "COMPLETED"
        return {
            "topic_lifecycle_isolation_contract_version": (
                TOPIC_LIFECYCLE_ISOLATION_CONTRACT_VERSION
            ),
            "topic_lifecycle_assessment_contract_version": (
                knowledge.TOPIC_LIFECYCLE_ASSESSMENT_CONTRACT_VERSION
            ),
            "status": status,
            "selected_topic_ids": [
                str(value.get("topic_id") or "")
                for value in candidates
                if isinstance(value, dict)
            ],
            "restricted_topic_ids": sorted(restricted),
            "assessed": len(assessments),
            "primary_valid": primary_valid,
            "recovered_valid": recovered_valid,
            "layered": layered,
            "classified": classified,
            "category_refined": category_refined,
            "failures": failures,
            "assessments": assessments,
            "curiosity_seed": seed,
        }
