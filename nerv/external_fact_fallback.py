"""Governed External-AI fallback after bounded web fact research fails.

The external answer is never trusted merely because it came from ChatGPT.
Local AI first assigns persistence, freshness, and impact policy. Stable or
reviewable low-impact answers are scope-audited before persistence; current
facts answer only the present turn; high-impact answers require certification.
"""

import json
import re
from copy import deepcopy
from datetime import datetime

from nerv.schemas import KNOWLEDGE_TEMPORAL_SCOPE_SCHEMA


PARTITION_LIFECYCLE_AUDIT_VERSION = 7

_NO_COMPLETE_CORE = "NO_COMPLETE_CORE"

FALLBACK_LIFECYCLE_BASES = [
    "FIXED_HISTORY",
    "DURABLE_EXPLANATION_DEFINITION_OR_MECHANISM",
    "MAINTAINED_SET_OR_STRUCTURE",
    "TRANSIENT_NONSTRUCTURAL_STATE_OR_EVENT",
]


FACT_FALLBACK_PREFLIGHT_SCHEMA = {
    "type": "object",
    "properties": {
        "decision": {"type": "string", "enum": ["ASK", "SKIP"]},
        "importance": {"type": "string", "enum": ["LOW", "HIGH"]},
        "sharing_risk": {
            "type": "string",
            "enum": ["NORMAL", "SENSITIVE", "PROHIBITED"],
        },
        "outbound_prompt": {"type": "string", "maxLength": 5000},
        "knowledge_type": {
            "type": "string",
            "enum": ["stable", "reviewable", "changing", "event", "news"],
        },
        "lifecycle_basis": {
            "type": "string",
            "enum": FALLBACK_LIFECYCLE_BASES,
        },
        "valid_for_days": {
            "anyOf": [
                {"type": "integer", "minimum": 1, "maximum": 3650},
                {"type": "null"},
            ]
        },
        "has_reusable_component": {"type": "boolean"},
        "reason": {"type": "string", "maxLength": 500},
    },
    "required": [
        "decision",
        "importance",
        "sharing_risk",
        "outbound_prompt",
        "knowledge_type",
        "lifecycle_basis",
        "valid_for_days",
        "has_reusable_component",
        "reason",
    ],
    "additionalProperties": False,
}


FACT_FALLBACK_POLICY_AUDIT_SCHEMA = {
    "type": "object",
    "properties": {
        "decision": {"type": "string", "enum": ["ASK", "SKIP"]},
        "importance": {"type": "string", "enum": ["LOW", "HIGH"]},
        "sharing_risk": {
            "type": "string",
            "enum": ["NORMAL", "SENSITIVE", "PROHIBITED"],
        },
        "outbound_prompt": {"type": "string", "maxLength": 5000},
        "knowledge_type": {
            "type": "string",
            "enum": ["stable", "reviewable", "changing", "event", "news"],
        },
        "lifecycle_basis": {
            "type": "string",
            "enum": FALLBACK_LIFECYCLE_BASES,
        },
        "valid_for_days": {
            "anyOf": [
                {"type": "integer", "minimum": 1, "maximum": 3650},
                {"type": "null"},
            ]
        },
        "has_reusable_component": {"type": "boolean"},
        "entity_scope_preserved": {"type": "boolean"},
        "lifecycle_proportional": {"type": "boolean"},
        "review_interval_proportional": {"type": "boolean"},
        "reason": {"type": "string", "maxLength": 500},
    },
    "required": [
        "decision",
        "importance",
        "sharing_risk",
        "outbound_prompt",
        "knowledge_type",
        "lifecycle_basis",
        "valid_for_days",
        "has_reusable_component",
        "entity_scope_preserved",
        "lifecycle_proportional",
        "review_interval_proportional",
        "reason",
    ],
    "additionalProperties": False,
}


FACT_FALLBACK_PARTITION_SCHEMA = {
    "type": "object",
    "properties": {
        "answer_usable": {"type": "boolean"},
        "directly_answers": {"type": "boolean"},
        "complete_for_request": {"type": "boolean"},
        "claims": {
            "type": "array",
            "maxItems": 8,
            "items": {
                "type": "object",
                "properties": {
                    "persist": {"type": "boolean"},
                    "directly_supported_by_answer": {"type": "boolean"},
                    "no_evidence_conflict": {"type": "boolean"},
                    "subject": {"type": "string", "maxLength": 300},
                    "claim": {"type": "string", "maxLength": 3000},
                    "knowledge_type": {
                        "type": "string",
                        "enum": [
                            "stable", "reviewable", "changing", "event", "news"
                        ],
                    },
                    "valid_for_days": {
                        "anyOf": [
                            {"type": "integer", "minimum": 1, "maximum": 3650},
                            {"type": "null"},
                        ]
                    },
                    "confidence": {
                        "type": "number", "minimum": 0, "maximum": 1
                    },
                    "topics": {
                        "type": "array",
                        "maxItems": 12,
                        "items": {"type": "string", "maxLength": 80},
                    },
                    "knowledge_domain": {
                        "type": "string",
                        "enum": [
                            "general", "mathematics", "physics", "chemistry",
                            "astronomy", "geography", "computer_science",
                            "medical", "legal", "sports",
                            "culture_entertainment", "business_organization",
                            "history_society", "other"
                        ],
                    },
                    "cluster_label": {"type": "string", "maxLength": 120},
                    "temporal_scope": {
                        "anyOf": [
                            KNOWLEDGE_TEMPORAL_SCOPE_SCHEMA,
                            {"type": "null"},
                        ]
                    },
                    "reason": {"type": "string", "maxLength": 500},
                },
                "required": [
                    "persist", "directly_supported_by_answer",
                    "no_evidence_conflict", "subject", "claim",
                    "knowledge_type", "valid_for_days", "confidence", "topics",
                    "knowledge_domain", "cluster_label", "temporal_scope",
                    "reason"
                ],
                "additionalProperties": False,
            },
        },
        "reason": {"type": "string", "maxLength": 500},
    },
    "required": [
        "answer_usable", "directly_answers", "complete_for_request",
        "claims", "reason"
    ],
    "additionalProperties": False,
}


def _partition_lifecycle_audit_schema(audit_ids):
    return {
        "type": "object",
        "properties": {
            "decisions": {
                "type": "array",
                "minItems": len(audit_ids),
                "maxItems": len(audit_ids),
                "items": {
                    "type": "object",
                    "properties": {
                        "audit_id": {
                            "type": "string",
                            "enum": sorted(audit_ids),
                        },
                        "persist": {
                            "type": "boolean",
                            "description": (
                                "Use true whenever persistence_eligible is "
                                "true and the final semantic basis is fixed "
                                "history, a durable explanation, or a "
                                "maintained set—even when proposed_persist "
                                "was false. Use false only for an ineligible "
                                "claim or a genuinely transient current "
                                "state/event."
                            ),
                        },
                        "lifecycle_basis": {
                            "type": "string",
                            "enum": [
                                "FIXED_HISTORY",
                                "DURABLE_EXPLANATION_DEFINITION_OR_MECHANISM",
                                "MAINTAINED_SET_OR_STRUCTURE",
                                "TRANSIENT_CURRENT_STATE_OR_EVENT",
                            ],
                            "description": (
                                "Select meaning before the lifecycle label. "
                                "An exact people-roster snapshot anchored to "
                                "a completed past date or closed season is "
                                "FIXED_HISTORY, not transient; future roster "
                                "changes cannot alter that historical record."
                            ),
                        },
                        "knowledge_type": {
                            "type": "string",
                            "enum": [
                                "stable", "reviewable", "changing",
                                "event", "news",
                            ],
                            "description": (
                                "FIXED_HISTORY is stable even when its subject "
                                "is a roster of people. Changing applies to an "
                                "open/current roster, not an exact completed "
                                "snapshot."
                            ),
                        },
                        "valid_for_days": {
                            "anyOf": [
                                {
                                    "type": "integer",
                                    "minimum": 1,
                                    "maximum": 3650,
                                },
                                {"type": "null"},
                            ]
                        },
                        "lifecycle_proportional": {"type": "boolean"},
                        "reason": {
                            "type": "string",
                            "minLength": 1,
                            "maxLength": 500,
                        },
                    },
                    "required": [
                        "audit_id", "persist", "lifecycle_basis",
                        "knowledge_type",
                        "valid_for_days", "lifecycle_proportional", "reason",
                    ],
                    "additionalProperties": False,
                },
            },
            "reason": {"type": "string", "maxLength": 500},
        },
        "required": ["decisions", "reason"],
        "additionalProperties": False,
    }


FACT_FALLBACK_AUDIT_SCHEMA = {
    "type": "object",
    "properties": {
        "directly_answers": {"type": "boolean"},
        "complete_for_request": {"type": "boolean"},
        "policy_satisfied": {"type": "boolean"},
        "no_evidence_conflict": {"type": "boolean"},
        "candidate_has_removable_additions": {"type": "boolean"},
        "confidence": {"type": "number", "minimum": 0, "maximum": 1},
        "subject": {"type": "string", "maxLength": 300},
        "canonical_answer": {
            "type": "string",
            "minLength": 1,
            "maxLength": 12000,
        },
        "canonical_claim": {
            "type": "string",
            "minLength": 1,
            "maxLength": 3000,
        },
        "topics": {
            "type": "array",
            "maxItems": 12,
            "items": {"type": "string", "maxLength": 80},
        },
        "knowledge_domain": {
            "type": "string",
            "enum": [
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
            ],
        },
        "cluster_label": {"type": "string", "maxLength": 120},
        "reason": {"type": "string", "maxLength": 500},
    },
    "required": [
        "directly_answers",
        "complete_for_request",
        "policy_satisfied",
        "no_evidence_conflict",
        "candidate_has_removable_additions",
        "confidence",
        "subject",
        "canonical_answer",
        "canonical_claim",
        "topics",
        "knowledge_domain",
        "cluster_label",
        "reason",
    ],
    "additionalProperties": False,
}


def _authoritative_local_date():
    """Return the host-local calendar date used by Bekki at runtime."""
    return datetime.now().astimezone().date().isoformat()


_CJK_RE = re.compile(r"[\u3400-\u9fff]")
_HARD_BLOCK_RE = re.compile(
    r"(?:密码|口令|验证码|信用卡号|银行卡号|账号密码|登录凭据|私钥|"
    r"password|passcode|verification code|credit card|bank account|login|"
    r"private key|authentication token|api key)",
    re.IGNORECASE,
)


def _release_model(tools_module, model_name):
    try:
        tools_module.unload_model(model_name)
        print("[EXTERNAL FACT FALLBACK MODEL RELEASED]", model_name)
    except Exception as error:
        print("[EXTERNAL FACT FALLBACK RELEASE WARNING]", repr(error))


def _fallback_lifecycle_shape_valid(
    lifecycle_basis,
    knowledge_type,
    valid_for_days,
):
    """Validate AI-selected lifecycle fields without classifying semantics."""
    basis = str(lifecycle_basis or "").upper()
    kind = str(knowledge_type or "").lower()
    if basis in {
        "FIXED_HISTORY",
        "DURABLE_EXPLANATION_DEFINITION_OR_MECHANISM",
    }:
        basis_matches = kind == "stable"
    elif basis == "MAINTAINED_SET_OR_STRUCTURE":
        basis_matches = kind in {"stable", "reviewable"}
    elif basis == "TRANSIENT_NONSTRUCTURAL_STATE_OR_EVENT":
        basis_matches = kind in {"changing", "event", "news"}
    else:
        return False
    if not basis_matches:
        return False
    if kind == "stable":
        return valid_for_days is None
    if kind == "reviewable":
        return (
            isinstance(valid_for_days, int)
            and not isinstance(valid_for_days, bool)
            and 1 <= valid_for_days <= 3650
        )
    return valid_for_days is None


def _normalize_closed_temporal_scope(value):
    """Validate AI-provided closed-period metadata without inferring dates."""
    value = value if isinstance(value, dict) else {}
    scope_type = str(value.get("scope_type") or "").upper().strip()
    requested_period = " ".join(
        str(value.get("requested_period") or "").split()
    )[:240]
    allow_previous_period = value.get("allow_previous_period")
    if (
        scope_type not in {"LATEST_COMPLETED_PERIOD", "EXPLICIT_PERIOD"}
        or not requested_period
        or not isinstance(allow_previous_period, bool)
    ):
        return None
    return {
        "scope_type": scope_type,
        "requested_period": requested_period,
        "allow_previous_period": allow_previous_period,
    }


def _evidence_packet(search_result):
    compact = []
    for item in (search_result or {}).get("results", [])[:14]:
        if not isinstance(item, dict):
            continue
        compact.append(
            {
                "title": str(item.get("title") or "")[:300],
                "domain": str(item.get("domain") or "")[:200],
                "description": str(
                    item.get("description") or item.get("snippet") or ""
                )[:900],
                "page_content": str(item.get("page_content") or "")[:1600],
            }
        )
    return compact


def _bounded_utf8_text(value, maximum_bytes):
    """Bound audit context by bytes without interpreting its semantics."""
    text = str(value or "")
    encoded = text.encode("utf-8")
    if len(encoded) <= maximum_bytes:
        return text
    marker = "\n[... truncated for bounded answer audit ...]"
    marker_bytes = marker.encode("utf-8")
    budget = max(0, maximum_bytes - len(marker_bytes))
    return encoded[:budget].decode("utf-8", errors="ignore") + marker


def _audit_conflict_evidence_packet(search_result):
    """Keep web material compact and subordinate to the exact audit pair."""
    compact = []
    for item in (search_result or {}).get("results", [])[:6]:
        if not isinstance(item, dict):
            continue
        excerpt = (
            item.get("description")
            or item.get("snippet")
            or item.get("page_content")
            or ""
        )
        compact.append({
            "title": _bounded_utf8_text(item.get("title"), 220),
            "domain": _bounded_utf8_text(item.get("domain"), 160),
            "conflict_excerpt": _bounded_utf8_text(excerpt, 420),
        })
    return compact


def _audit_request_policy(tools_module, packet, first_result, model_name):
    """Let a second AI independently own lifecycle and freshness policy."""
    audit_packet = {
        **packet,
        "first_governor_sharing_preview": {
            "decision": str(first_result.get("decision") or "SKIP")[:20],
            "importance": str(
                first_result.get("importance") or "HIGH"
            )[:20],
            "sharing_risk": str(
                first_result.get("sharing_risk") or "SENSITIVE"
            )[:20],
            "outbound_prompt": str(
                first_result.get("outbound_prompt") or ""
            )[:5000],
        },
    }
    try:
        result = tools_module.run_ai_prompt(
            "prompts/external_fact_fallback_policy_audit.txt",
            json.dumps(
                audit_packet,
                ensure_ascii=False,
                separators=(",", ":"),
            ),
            expect_json=True,
            num_ctx=6144,
            num_predict=760,
            think=False,
            model_name=model_name,
            json_schema=FACT_FALLBACK_POLICY_AUDIT_SCHEMA,
        )
    except Exception as error:
        print(
            "[EXTERNAL FACT FALLBACK POLICY AUDIT]",
            "failed=" + type(error).__name__,
        )
        return None
    finally:
        _release_model(tools_module, model_name)
    required_bools = (
        "entity_scope_preserved",
        "lifecycle_proportional",
        "review_interval_proportional",
    )
    if (
        not isinstance(result, dict)
        or any(
            not isinstance(result.get(name), bool)
            for name in required_bools
        )
        or not isinstance(result.get("reason"), str)
        or not result["reason"].strip()
    ):
        return None
    normalized = {
        "decision": str(result.get("decision") or "SKIP").upper(),
        "importance": str(result.get("importance") or "HIGH").upper(),
        "sharing_risk": str(
            result.get("sharing_risk") or "SENSITIVE"
        ).upper(),
        "outbound_prompt": str(result.get("outbound_prompt") or "").strip(),
        "knowledge_type": str(
            result.get("knowledge_type") or "event"
        ).lower(),
        "lifecycle_basis": str(
            result.get("lifecycle_basis") or ""
        ).upper(),
        "valid_for_days": result.get("valid_for_days"),
        "has_reusable_component": (
            result.get("has_reusable_component") is True
        ),
        **{name: result[name] for name in required_bools},
        "reason": result["reason"].strip()[:500],
    }
    if normalized["knowledge_type"] in {"changing", "event", "news"}:
        normalized["valid_for_days"] = None
    lifecycle_shape_valid = _fallback_lifecycle_shape_valid(
        normalized["lifecycle_basis"],
        normalized["knowledge_type"],
        normalized["valid_for_days"],
    )
    if normalized["decision"] == "ASK" and not all(
        normalized[name] is True for name in required_bools
    ):
        normalized["decision"] = "SKIP"
    if normalized["decision"] == "ASK" and not lifecycle_shape_valid:
        normalized["decision"] = "SKIP"
    print(
        "[EXTERNAL FACT FALLBACK POLICY AUDIT]",
        "decision=" + normalized["decision"],
        "importance=" + normalized["importance"],
        "type=" + normalized["knowledge_type"],
        "basis=" + normalized["lifecycle_basis"],
        "days=" + str(normalized["valid_for_days"]),
        "mixed_reusable=" + str(normalized["has_reusable_component"]),
    )
    return normalized


def assess_request(user_request, fact_scope, risk="low"):
    """Assign External-AI sharing, persistence, freshness, and impact policy."""
    import tools

    request = str(user_request or "").strip()
    if not request or _HARD_BLOCK_RE.search(request):
        return {
            "decision": "SKIP",
            "importance": "HIGH",
            "sharing_risk": "SENSITIVE",
            "outbound_prompt": "",
            "knowledge_type": "event",
            "lifecycle_basis": "TRANSIENT_NONSTRUCTURAL_STATE_OR_EVENT",
            "valid_for_days": None,
            "has_reusable_component": False,
            "reason": "deterministic_high_impact_guard",
        }
    scope = fact_scope if isinstance(fact_scope, dict) else {}
    requested_period = scope.get("requested_period")
    packet = {
        "current_date": __import__("datetime").date.today().isoformat(),
        "authoritative_public_fact_request": request[:4000],
        "retrieval_time_scope": {
            "scope_type": str(scope.get("scope_type") or "")[:80],
            "requested_period": (
                str(requested_period)[:200]
                if requested_period is not None
                else None
            ),
            "allow_previous_period": (
                scope.get("allow_previous_period")
                if isinstance(scope.get("allow_previous_period"), bool)
                else None
            ),
        },
        "retrieval_scope_is_non_authoritative": True,
        "melchior_risk": str(risk or "low")[:20],
    }
    model_name = "gemma4:12b"
    try:
        result = tools.run_ai_prompt(
            "prompts/external_fact_fallback_preflight.txt",
            json.dumps(packet, ensure_ascii=False, separators=(",", ":")),
            expect_json=True,
            num_ctx=6144,
            num_predict=700,
            think=False,
            model_name=model_name,
            json_schema=FACT_FALLBACK_PREFLIGHT_SCHEMA,
        )
    except Exception as error:
        return {
            "decision": "SKIP",
            "importance": "HIGH",
            "sharing_risk": "SENSITIVE",
            "outbound_prompt": "",
            "knowledge_type": "event",
            "lifecycle_basis": "TRANSIENT_NONSTRUCTURAL_STATE_OR_EVENT",
            "valid_for_days": None,
            "has_reusable_component": False,
            "reason": "preflight_failed:" + type(error).__name__,
        }
    finally:
        _release_model(tools, model_name)
    if not isinstance(result, dict):
        return {"decision": "SKIP", "reason": "invalid_preflight"}
    decision = str(result.get("decision") or "SKIP").upper()
    importance = str(result.get("importance") or "HIGH").upper()
    sharing_risk = str(result.get("sharing_risk") or "SENSITIVE").upper()
    if decision == "SKIP" and sharing_risk == "NORMAL":
        recovery_packet = {
            **packet,
            "first_pass": result,
            "recovery_reason": (
                "The first pass called a public NORMAL-risk request SKIP. "
                "Re-evaluate the lifecycle and return a self-consistent decision."
            ),
        }
        try:
            recovered = tools.run_ai_prompt(
                "prompts/external_fact_fallback_preflight_recovery.txt",
                json.dumps(
                    recovery_packet,
                    ensure_ascii=False,
                    separators=(",", ":"),
                ),
                expect_json=True,
                num_ctx=6144,
                num_predict=700,
                think=False,
                model_name=model_name,
                json_schema=FACT_FALLBACK_PREFLIGHT_SCHEMA,
            )
        except Exception as error:
            print(
                "[EXTERNAL FACT FALLBACK PREFLIGHT RECOVERY]",
                "failed=" + type(error).__name__,
            )
            recovered = None
        finally:
            _release_model(tools, model_name)
        if isinstance(recovered, dict):
            print("[EXTERNAL FACT FALLBACK PREFLIGHT RECOVERY] decision=" + str(
                recovered.get("decision") or "SKIP"
            ))
            result = recovered
            decision = str(result.get("decision") or "SKIP").upper()
            importance = str(result.get("importance") or "HIGH").upper()
            sharing_risk = str(
                result.get("sharing_risk") or "SENSITIVE"
            ).upper()
    if decision == "ASK" and sharing_risk == "NORMAL":
        audited_policy = _audit_request_policy(
            tools,
            packet,
            result,
            model_name,
        )
        if audited_policy is None:
            result = {
                "decision": "SKIP",
                "importance": "HIGH",
                "sharing_risk": "SENSITIVE",
                "outbound_prompt": "",
                "knowledge_type": "event",
                "lifecycle_basis": "TRANSIENT_NONSTRUCTURAL_STATE_OR_EVENT",
                "valid_for_days": None,
                "has_reusable_component": False,
                "reason": "invalid_independent_policy_audit",
            }
        else:
            result = audited_policy
        decision = str(result.get("decision") or "SKIP").upper()
        importance = str(result.get("importance") or "HIGH").upper()
        sharing_risk = str(
            result.get("sharing_risk") or "SENSITIVE"
        ).upper()
    outbound_prompt = str(result.get("outbound_prompt") or "").strip()
    knowledge_type = str(result.get("knowledge_type") or "event").lower()
    lifecycle_basis = str(result.get("lifecycle_basis") or "").upper()
    valid_for_days = result.get("valid_for_days")
    has_reusable_component = result.get("has_reusable_component") is True
    temporal_scope = {
        "scope_type": str(scope.get("scope_type") or "")[:80],
        "requested_period": (
            str(scope.get("requested_period") or "")[:240]
        ),
        "allow_previous_period": (
            scope.get("allow_previous_period")
            if isinstance(scope.get("allow_previous_period"), bool)
            else None
        ),
    }
    if knowledge_type in {"changing", "event", "news"}:
        # These types never enter Knowledge, so an expiry would serve no
        # purpose. Requiring one incorrectly turned valid current facts into
        # SKIP after the AI had selected ASK.
        valid_for_days = None
    allowed = (
        decision == "ASK"
        and sharing_risk == "NORMAL"
        and bool(outbound_prompt)
        and len(outbound_prompt) <= 5000
        and knowledge_type in {
            "stable", "reviewable", "changing", "event", "news"
        }
        and _fallback_lifecycle_shape_valid(
            lifecycle_basis,
            knowledge_type,
            valid_for_days,
        )
    )
    if _CJK_RE.search(request) and not _CJK_RE.search(outbound_prompt):
        allowed = False
    normalized_reason = str(result.get("reason") or "")[:500]
    if decision == "ASK" and not allowed:
        normalized_reason = "python_contract_rejected_ai_ask: " + normalized_reason
    return {
        "decision": "ASK" if allowed else "SKIP",
        "importance": importance,
        "sharing_risk": sharing_risk,
        "outbound_prompt": outbound_prompt[:5000] if allowed else "",
        "knowledge_type": knowledge_type,
        "lifecycle_basis": lifecycle_basis,
        "valid_for_days": valid_for_days,
        "has_reusable_component": has_reusable_component,
        # This is copied from Casper's earlier AI temporal contract. It is
        # metadata for identity/retrieval; Python does not infer a period.
        "temporal_scope": temporal_scope,
        "reason": normalized_reason,
    }


def audit_answer(
    user_request,
    external_answer,
    search_result,
    assessment,
    certification_context=None,
):
    """Check scope, completeness, impact, and conflicts—not factual truth."""
    import tools

    authoritative_request = _bounded_utf8_text(user_request, 3000)
    candidate_answer = _bounded_utf8_text(external_answer, 12000)
    authoritative_current_date = _authoritative_local_date()
    selected_policy = {
        "decision": str((assessment or {}).get("decision") or "")[:20],
        "importance": str(
            (assessment or {}).get("importance") or ""
        )[:20],
        "sharing_risk": str(
            (assessment or {}).get("sharing_risk") or ""
        )[:20],
        "knowledge_type": str(
            (assessment or {}).get("knowledge_type") or ""
        )[:20],
        "lifecycle_basis": str(
            (assessment or {}).get("lifecycle_basis") or ""
        )[:80],
        "valid_for_days": (assessment or {}).get("valid_for_days"),
    }
    certification_summary = None
    if isinstance(certification_context, dict):
        certification_summary = {
            "performed": certification_context.get("performed") is True,
            "provider": _bounded_utf8_text(
                certification_context.get("provider"), 200
            ),
        }
    packet = {
        "authoritative_user_request": authoritative_request,
        "candidate_external_answer": candidate_answer,
        "authoritative_runtime_context": {
            "current_date": authoritative_current_date,
            "date_role": "AUTHORITATIVE_FOR_TEMPORAL_JUDGMENTS",
            "instruction": (
                "Use this host-local date instead of the model's training "
                "date or assumed present date."
            ),
        },
        "audit_evidence_contract": {
            "mode": "EXTRACTIVE_SCOPE_POLICY_CONFLICT_AUDIT",
            "candidate_role": (
                "PRIMARY_AUTHORITY_WHEN_SELECTED_POLICY_ALLOWS"
            ),
            "permitted_negative_evidence": (
                "DIRECT_RETAINED_CORE_CONTRADICTION_OR_"
                "BOUNDED_WEB_CONFLICT_ONLY"
            ),
            "latent_model_knowledge_role": "NOT_EVIDENCE",
            "missing_web_corroboration_role": (
                "EXPECTED_AFTER_BOUNDED_RESEARCH_NOT_A_CONFLICT"
            ),
        },
        "selected_policy": selected_policy,
        "certification_summary": certification_summary,
        "bounded_web_conflict_evidence": (
            _audit_conflict_evidence_packet(search_result)
        ),
        "web_evidence_role": "CONFLICT_CHECK_ONLY",
        "final_scope_anchor": {
            "authoritative_user_request": authoritative_request,
            "authoritative_current_date": authoritative_current_date,
            "candidate_field": "candidate_external_answer",
            "latent_model_knowledge_role": "NOT_EVIDENCE",
            "missing_web_corroboration_role": "NOT_A_CONFLICT",
            "instruction": (
                "Judge only whether candidate_external_answer answers this "
                "exact request. Evidence titles and adjacent page topics "
                "cannot redefine the request. Use authoritative_current_date "
                "for all temporal judgments. Judge retained core claims "
                "independently from removable additions."
            ),
        },
    }
    model_name = "gemma4:12b"
    try:
        result = tools.run_ai_prompt(
            "prompts/external_fact_fallback_audit.txt",
            json.dumps(packet, ensure_ascii=False, separators=(",", ":")),
            expect_json=True,
            num_ctx=8192,
            num_predict=1800,
            think=False,
            model_name=model_name,
            json_schema=FACT_FALLBACK_AUDIT_SCHEMA,
        )
    except Exception as error:
        return {"decision": "REJECT", "reason": "audit_failed:" + type(error).__name__}
    finally:
        _release_model(tools, model_name)
    if not isinstance(result, dict):
        return {"decision": "REJECT", "reason": "invalid_audit"}
    try:
        confidence = float(result.get("confidence") or 0)
    except (TypeError, ValueError):
        confidence = 0.0
    canonical_answer = str(result.get("canonical_answer") or "").strip()
    canonical_claim = str(result.get("canonical_claim") or "").strip()
    removable_additions = (
        result.get("candidate_has_removable_additions") is True
    )
    canonical_available = (
        bool(canonical_answer)
        and bool(canonical_claim)
        and canonical_answer.upper() != _NO_COMPLETE_CORE
        and canonical_claim.upper() != _NO_COMPLETE_CORE
    )
    # The model owns every semantic finding and the extracted text. This
    # mapping only prevents a duplicate global label from contradicting those
    # findings; it never interprets an entity, claim, or domain keyword.
    accepted = (
        result.get("directly_answers") is True
        and result.get("complete_for_request") is True
        and result.get("policy_satisfied") is True
        and result.get("no_evidence_conflict") is True
        and confidence >= 0.80
        and bool(str(result.get("subject") or "").strip())
        and canonical_available
    )
    result = dict(result)
    result["decision"] = "AUTO_VERIFY" if accepted else "REJECT"
    result["answer_disposition"] = (
        (
            "USE_CANONICAL_CORE"
            if removable_additions
            else "USE_AS_IS"
        )
        if accepted
        else "REJECT"
    )
    if accepted:
        result["canonical_answer"] = canonical_answer
        result["canonical_claim"] = canonical_claim
    else:
        result["canonical_answer"] = ""
        result["canonical_claim"] = ""
    result["confidence"] = max(0.0, min(1.0, confidence))
    return result


def _call_partition_lifecycle_audit(
    prompt_path,
    packet,
    audit_ids,
    stage,
):
    """Call one lifecycle judge without interpreting claim semantics."""
    import tools

    model_name = "gemma4:12b"
    try:
        return tools.run_ai_prompt(
            prompt_path,
            json.dumps(packet, ensure_ascii=False, separators=(",", ":")),
            expect_json=True,
            num_ctx=8192,
            num_predict=1800,
            think=False,
            model_name=model_name,
            json_schema=_partition_lifecycle_audit_schema(audit_ids),
        )
    except Exception as error:
        print(
            "[EXTERNAL FACT PARTITION LIFECYCLE " + stage + "]",
            "failed=" + type(error).__name__,
        )
        return None
    finally:
        _release_model(tools, model_name)


def _normalize_partition_lifecycle_result(result, audit_ids):
    """Validate one AI contract without choosing a lifecycle in Python."""
    if not isinstance(result, dict) or not isinstance(
        result.get("decisions"), list
    ):
        return None, ["missing_decisions"]
    decisions = result["decisions"]
    returned_ids = [
        str(item.get("audit_id") or "")
        for item in decisions if isinstance(item, dict)
    ]
    if (
        len(decisions) != len(audit_ids)
        or len(returned_ids) != len(set(returned_ids))
        or set(returned_ids) != set(audit_ids)
    ):
        return None, ["decision_ids_invalid"]
    normalized = []
    errors = []
    for raw in decisions:
        if not isinstance(raw, dict):
            return None, ["decision_not_object"]
        audit_id = str(raw.get("audit_id") or "")
        lifecycle_basis = str(raw.get("lifecycle_basis") or "").upper()
        knowledge_type = str(raw.get("knowledge_type") or "event").lower()
        valid_for_days = raw.get("valid_for_days")
        persist = raw.get("persist") is True
        proportional = raw.get("lifecycle_proportional") is True
        if lifecycle_basis in {
            "FIXED_HISTORY",
            "DURABLE_EXPLANATION_DEFINITION_OR_MECHANISM",
        }:
            basis_type_valid = knowledge_type == "stable"
        elif lifecycle_basis == "MAINTAINED_SET_OR_STRUCTURE":
            basis_type_valid = knowledge_type in {"stable", "reviewable"}
        elif lifecycle_basis == "TRANSIENT_CURRENT_STATE_OR_EVENT":
            basis_type_valid = knowledge_type in {
                "changing", "event", "news",
            }
        else:
            basis_type_valid = False
            errors.append(audit_id + ":lifecycle_basis_invalid")
        if not basis_type_valid:
            errors.append(audit_id + ":basis_type_mismatch")
        if knowledge_type == "stable":
            lifecycle_valid = valid_for_days is None
        elif knowledge_type == "reviewable":
            lifecycle_valid = (
                isinstance(valid_for_days, int)
                and not isinstance(valid_for_days, bool)
                and 1 <= valid_for_days <= 3650
            )
        elif knowledge_type in {"changing", "event", "news"}:
            lifecycle_valid = valid_for_days is None
            if persist:
                errors.append(audit_id + ":current_claim_persisted")
            persist = False
        else:
            errors.append(audit_id + ":knowledge_type_invalid")
            lifecycle_valid = False
        if not lifecycle_valid:
            errors.append(audit_id + ":lifecycle_shape_invalid")
        if not proportional:
            errors.append(audit_id + ":lifecycle_not_proportional")
        reason = str(raw.get("reason") or "").strip()
        if not reason:
            errors.append(audit_id + ":reason_missing")
        normalized.append({
            "audit_id": audit_id,
            "persist": persist,
            "lifecycle_basis": lifecycle_basis,
            "knowledge_type": knowledge_type,
            "valid_for_days": valid_for_days if lifecycle_valid else None,
            "lifecycle_proportional": proportional,
            "reason": reason[:500],
        })
    if errors:
        return None, errors
    return normalized, []


def _partition_lifecycle_proposal_errors(decisions, records):
    """Validate final AI persistence against non-semantic eligibility."""
    proposal_by_id = {
        str(item.get("audit_id") or ""): item
        for item in records if isinstance(item, dict)
    }
    errors = []
    for decision in decisions or []:
        audit_id = decision["audit_id"]
        proposed = proposal_by_id.get(audit_id, {})
        persistence_eligible = proposed.get(
            "persistence_eligible",
            proposed.get("proposed_persist") is True,
        ) is True
        transient = (
            decision.get("lifecycle_basis")
            == "TRANSIENT_CURRENT_STATE_OR_EVENT"
        )
        if decision.get("persist") is True and not persistence_eligible:
            errors.append(audit_id + ":ineligible_claim_persisted")
        if transient and decision.get("persist") is True:
            errors.append(audit_id + ":transient_claim_persisted")
        if (
            persistence_eligible
            and not transient
            and decision.get("persist") is not True
        ):
            errors.append(audit_id + ":reusable_claim_not_persisted")
    return errors


def _run_partition_lifecycle_audit(records, context):
    """Independently audit persistence and freshness for exact claim records."""
    records = [item for item in records if isinstance(item, dict)]
    audit_ids = [str(item.get("audit_id") or "") for item in records]
    if (
        not records
        or any(not value for value in audit_ids)
        or len(audit_ids) != len(set(audit_ids))
    ):
        return None
    packet = {
        "audit_version": PARTITION_LIFECYCLE_AUDIT_VERSION,
        "claims": records,
        "context": context if isinstance(context, dict) else {},
    }
    result = _call_partition_lifecycle_audit(
        "prompts/external_fact_fallback_partition_lifecycle_audit.txt",
        packet,
        audit_ids,
        "AUDIT",
    )
    normalized, errors = _normalize_partition_lifecycle_result(
        result, audit_ids
    )
    if normalized is not None:
        proposal_errors = _partition_lifecycle_proposal_errors(
            normalized, records
        )
        if proposal_errors:
            errors = proposal_errors
            normalized = None
    if normalized is None:
        print(
            "[EXTERNAL FACT PARTITION LIFECYCLE RECOVERY]",
            "triggered=" + ",".join(errors)[:500],
        )
        recovery_packet = {
            **packet,
            "invalid_first_audit": (
                result if isinstance(result, dict) else None
            ),
            "contract_errors": errors,
        }
        recovered = _call_partition_lifecycle_audit(
            "prompts/external_fact_fallback_partition_lifecycle_audit_recovery.txt",
            recovery_packet,
            audit_ids,
            "RECOVERY",
        )
        normalized, recovery_errors = _normalize_partition_lifecycle_result(
            recovered, audit_ids
        )
        if normalized is not None:
            recovery_errors = _partition_lifecycle_proposal_errors(
                normalized, records
            )
            if recovery_errors:
                normalized = None
        if normalized is None:
            print(
                "[EXTERNAL FACT PARTITION LIFECYCLE RECOVERY]",
                "status=FAILED errors=" + ",".join(recovery_errors)[:500],
            )
            return None
        print(
            "[EXTERNAL FACT PARTITION LIFECYCLE RECOVERY] status=PASSED"
        )

    return normalized


def audit_partition_lifecycles(
    user_request,
    external_answer,
    search_result,
    assessment,
    partition,
    additional_context=None,
):
    """Require two AI judgments before a mixed-answer claim can persist."""
    claims = partition.get("claims", []) if isinstance(partition, dict) else []
    assessment = assessment if isinstance(assessment, dict) else {}
    policy_eligible = (
        assessment.get("decision") == "ASK"
        and str(assessment.get("importance") or "").upper() == "LOW"
        and str(assessment.get("sharing_risk") or "").upper() == "NORMAL"
        and assessment.get("has_reusable_component") is True
    )
    records = []
    eligibility_by_index = {}
    for index, claim in enumerate(claims):
        if not isinstance(claim, dict):
            continue
        try:
            confidence = float(claim.get("confidence") or 0)
        except (TypeError, ValueError):
            confidence = 0.0
        persistence_eligible = (
            policy_eligible
            and claim.get("directly_supported_by_answer") is True
            and claim.get("no_evidence_conflict") is True
            and confidence >= 0.80
            and bool(str(claim.get("subject") or "").strip())
            and bool(str(claim.get("claim") or "").strip())
        )
        eligibility_by_index[index] = persistence_eligible
        records.append({
            "audit_id": "partition_claim_" + str(index),
            "subject": str(claim.get("subject") or "")[:300],
            "claim": str(claim.get("claim") or "")[:3000],
            "proposed_persist": claim.get("persist") is True,
            "proposed_knowledge_type": str(
                claim.get("knowledge_type") or "event"
            )[:20],
            "proposed_valid_for_days": claim.get("valid_for_days"),
            "confidence": claim.get("confidence"),
            "persistence_eligible": persistence_eligible,
            "temporal_scope": _normalize_closed_temporal_scope(
                claim.get("temporal_scope")
            ),
        })
    decisions = _run_partition_lifecycle_audit(records, {
        "mode": "new_mixed_answer",
        "current_user_request": str(user_request or "")[:4000],
        "external_ai_answer": str(external_answer or "")[:12000],
        "preflight": assessment if isinstance(assessment, dict) else {},
        "bounded_web_evidence": _evidence_packet(search_result),
        "additional_context": (
            additional_context
            if isinstance(additional_context, dict)
            else {}
        ),
    })
    output = dict(partition) if isinstance(partition, dict) else {}
    if decisions is None:
        output["claims"] = [
            {**claim, "persist": False, "lifecycle_audit_status": "FAILED_CLOSED"}
            for claim in claims if isinstance(claim, dict)
        ]
        output["lifecycle_audit_status"] = "FAILED_CLOSED"
        print(
            "[EXTERNAL FACT PARTITION LIFECYCLE AUDIT]",
            "status=FAILED_CLOSED persisted=0",
        )
        return output
    by_id = {item["audit_id"]: item for item in decisions}
    audited_claims = []
    persist_count = 0
    reviewable_count = 0
    for index, claim in enumerate(claims):
        if not isinstance(claim, dict):
            continue
        decision = by_id["partition_claim_" + str(index)]
        persist = (
            eligibility_by_index.get(index) is True
            and decision.get("persist") is True
        )
        temporal_scope = _normalize_closed_temporal_scope(
            claim.get("temporal_scope")
        )
        missing_fixed_period = (
            decision.get("lifecycle_basis") == "FIXED_HISTORY"
            and temporal_scope is None
        )
        if missing_fixed_period:
            persist = False
        audited = dict(claim)
        audited.update({
            "persist": persist,
            "knowledge_type": decision["knowledge_type"],
            "lifecycle_basis": decision["lifecycle_basis"],
            "valid_for_days": decision["valid_for_days"],
            "lifecycle_audit_status": "PASSED",
            "lifecycle_audit_reason": decision["reason"],
            "partition_lifecycle_audit_version": (
                PARTITION_LIFECYCLE_AUDIT_VERSION
            ),
        })
        if temporal_scope is not None:
            audited["temporal_scope"] = temporal_scope
        elif missing_fixed_period:
            audited["lifecycle_audit_status"] = "MISSING_TEMPORAL_SCOPE"
        audited_claims.append(audited)
        persist_count += int(persist)
        reviewable_count += int(
            persist and decision["knowledge_type"] == "reviewable"
        )
    output["claims"] = audited_claims
    output["lifecycle_audit_status"] = "PASSED"
    print(
        "[EXTERNAL FACT PARTITION LIFECYCLE AUDIT]",
        "status=PASSED",
        "persisted=" + str(persist_count),
        "reviewable=" + str(reviewable_count),
    )
    return output


def audit_existing_partition_lifecycles(items):
    """Re-audit mixed-answer items written before the independent audit."""
    records = []
    for item in items:
        if not isinstance(item, dict) or not item.get("id"):
            continue
        records.append({
            "audit_id": str(item.get("id")),
            "subject": str(item.get("subject") or "")[:300],
            "claim": str(item.get("claim") or "")[:3000],
            "proposed_persist": True,
            "proposed_knowledge_type": str(
                item.get("knowledge_type") or "stable"
            )[:20],
            "proposed_valid_for_days": item.get("valid_for_days"),
            "confidence": item.get("confidence"),
            "persistence_eligible": True,
        })
    decisions = _run_partition_lifecycle_audit(records, {
        "mode": "legacy_mixed_answer_reaudit",
        "policy": "correct lifecycle without changing claim text",
    })
    if decisions is None:
        return None
    return [
        {
            "id": item["audit_id"],
            "persist": item["persist"],
            "knowledge_type": item["knowledge_type"],
            "lifecycle_basis": item["lifecycle_basis"],
            "valid_for_days": item["valid_for_days"],
            "lifecycle_proportional": item["lifecycle_proportional"],
            "reason": item["reason"],
            "partition_lifecycle_audit_version": (
                PARTITION_LIFECYCLE_AUDIT_VERSION
            ),
        }
        for item in decisions
    ]


def partition_mixed_answer(
    user_request,
    external_answer,
    search_result,
    assessment,
    prompt_path="prompts/external_fact_fallback_partition.txt",
    answer_source="external_ai_low_impact",
    additional_context=None,
):
    """Let AI separate reusable claims from current-turn-only mixed content."""
    import tools

    additional_context = (
        additional_context if isinstance(additional_context, dict) else {}
    )
    packet = {
        "current_user_request": str(user_request or "")[:4000],
        "external_ai_answer": str(external_answer or "")[:12000],
        "candidate_answer": str(external_answer or "")[:12000],
        "answer_source": str(answer_source or "")[:80],
        "preflight": assessment if isinstance(assessment, dict) else {},
        "bounded_web_evidence": _evidence_packet(search_result),
        "additional_context": additional_context,
    }
    partition_schema = deepcopy(FACT_FALLBACK_PARTITION_SCHEMA)
    if additional_context.get("strict_source_temporal_scope") is True:
        source_periods = []
        for value in additional_context.get("source_supported_periods", []):
            period = " ".join(str(value or "").split())[:240]
            if period and period not in source_periods:
                source_periods.append(period)
            if len(source_periods) >= 8:
                break
        temporal_schema = partition_schema["properties"]["claims"][
            "items"
        ]["properties"]["temporal_scope"]
        if source_periods:
            temporal_schema["anyOf"][0]["properties"][
                "requested_period"
            ] = {
                "type": "string",
                "enum": source_periods,
            }
        else:
            temporal_schema.clear()
            temporal_schema.update({"type": "null"})
    model_name = "gemma4:12b"
    try:
        result = tools.run_ai_prompt(
            str(prompt_path or "prompts/external_fact_fallback_partition.txt"),
            json.dumps(packet, ensure_ascii=False, separators=(",", ":")),
            expect_json=True,
            num_ctx=8192,
            num_predict=1800,
            think=False,
            model_name=model_name,
            json_schema=partition_schema,
        )
    except Exception as error:
        print(
            "[EXTERNAL FACT FALLBACK PARTITION]",
            "failed=" + type(error).__name__,
        )
        return None
    finally:
        _release_model(tools, model_name)
    if not isinstance(result, dict) or not isinstance(result.get("claims"), list):
        return None
    normalized_claims = []
    seen = set()
    for raw in result["claims"][:8]:
        if not isinstance(raw, dict):
            continue
        claim = " ".join(str(raw.get("claim") or "").split())[:3000]
        subject = " ".join(str(raw.get("subject") or "").split())[:300]
        knowledge_type = str(raw.get("knowledge_type") or "event").lower()
        valid_for_days = raw.get("valid_for_days")
        try:
            confidence = max(0.0, min(1.0, float(raw.get("confidence") or 0)))
        except (TypeError, ValueError):
            confidence = 0.0
        persist = raw.get("persist") is True
        if knowledge_type == "stable":
            lifecycle_valid = valid_for_days is None
        elif knowledge_type == "reviewable":
            lifecycle_valid = (
                isinstance(valid_for_days, int)
                and 1 <= valid_for_days <= 3650
            )
        else:
            lifecycle_valid = valid_for_days is None
            persist = False
        persist = (
            persist
            and lifecycle_valid
            and knowledge_type in {"stable", "reviewable"}
            and confidence >= 0.80
            and raw.get("directly_supported_by_answer") is True
            and raw.get("no_evidence_conflict") is True
            and bool(subject)
            and bool(claim)
        )
        identity = (subject.casefold(), claim.casefold())
        if not subject or not claim or identity in seen:
            continue
        seen.add(identity)
        candidate = dict(raw)
        temporal_scope = _normalize_closed_temporal_scope(
            raw.get("temporal_scope")
        )
        candidate.update({
            "persist": persist,
            "subject": subject,
            "claim": claim,
            "knowledge_type": knowledge_type,
            "valid_for_days": valid_for_days if lifecycle_valid else None,
            "confidence": confidence,
            "temporal_scope": temporal_scope,
        })
        normalized_claims.append(candidate)
    directly_answers = result.get("directly_answers") is True
    complete_for_request = result.get("complete_for_request") is True
    partition = {
        "answer_usable": (
            result.get("answer_usable") is True
            and directly_answers
            and complete_for_request
        ),
        "directly_answers": directly_answers,
        "complete_for_request": complete_for_request,
        "claims": normalized_claims,
        "reason": str(result.get("reason") or "")[:500],
    }
    return audit_partition_lifecycles(
        user_request,
        external_answer,
        search_result,
        assessment,
        partition,
        additional_context=additional_context,
    )


def intake_audited_fact_lookup(
    user_request,
    accepted_answer,
    search_result,
    risk="low",
):
    """Capture reusable claims from an already accepted Casper fact answer."""
    import knowledge

    search_result = search_result if isinstance(search_result, dict) else {}
    answer = str(accepted_answer or "").strip()
    if str(risk or "low").lower() != "low" or not answer:
        return {"status": "SKIPPED", "reason": "risk_or_answer_ineligible"}
    fallback = search_result.get("external_ai_fallback")
    fallback = fallback if isinstance(fallback, dict) else {}
    if str(fallback.get("status") or "").upper() in {
        "VERIFIED", "CURRENT_REFERENCE", "CERTIFIED"
    }:
        return {"status": "SKIPPED", "reason": "fallback_already_governed"}
    accepted_records = [
        item for item in search_result.get("answers", [])
        if isinstance(item, dict)
        and item.get("accepted") is True
        and str(item.get("answer") or "").strip()
    ]
    if not accepted_records:
        return {"status": "SKIPPED", "reason": "no_accepted_fact_record"}
    source_periods = []
    compact_records = []
    for item in accepted_records[:8]:
        temporal = item.get("temporal_validation")
        temporal = temporal if isinstance(temporal, dict) else {}
        source_period = " ".join(
            str(temporal.get("source_period") or "").split()
        )[:240]
        if (
            temporal.get("time_scope_match") is True
            and source_period
            and source_period not in source_periods
        ):
            source_periods.append(source_period)
        compact_records.append({
            "answer": str(item.get("answer") or "")[:5000],
            "answer_status": str(item.get("answer_status") or "")[:80],
            "temporal_validation": temporal,
        })
    assessment = {
        "decision": "ASK",
        "importance": "LOW",
        "sharing_risk": "NORMAL",
        "knowledge_type": "changing",
        "lifecycle_basis": "TRANSIENT_NONSTRUCTURAL_STATE_OR_EVENT",
        "valid_for_days": None,
        "has_reusable_component": True,
        "reason": (
            "Casper already accepted this low-risk public fact answer; "
            "the existing partition and lifecycle judges decide reuse."
        ),
    }
    partition = partition_mixed_answer(
        user_request,
        answer,
        search_result,
        assessment,
        prompt_path="prompts/nerv_fact_lookup_knowledge_partition.txt",
        answer_source="casper_audited_fact_lookup",
        additional_context={
            "authoritative_current_date": _authoritative_local_date(),
            "current_date_role": "HOST_LOCAL_TEMPORAL_AUTHORITY",
            "fact_scope": (
                search_result.get("fact_scope")
                if isinstance(search_result.get("fact_scope"), dict)
                else {}
            ),
            "accepted_answer_records": compact_records,
            "source_supported_periods": source_periods,
            "strict_source_temporal_scope": True,
            "answer_already_accepted_for_current_turn": True,
            "knowledge_capture_cannot_change_user_reply": True,
        },
    )
    if not isinstance(partition, dict):
        return {"status": "SKIPPED", "reason": "partition_failed"}
    if partition.get("answer_usable") is not True:
        return {
            "status": "SKIPPED",
            "reason": "partition_did_not_accept_exact_answer",
            "partition": partition,
        }
    knowledge_ids = []
    statuses = []
    for candidate in partition.get("claims", []):
        if not isinstance(candidate, dict) or candidate.get("persist") is not True:
            continue
        status, item = knowledge.apply_verified_fact_lookup_partitioned_claim(
            user_request,
            answer,
            candidate,
            search_result,
        )
        statuses.append(status)
        if (
            status in {"verified", "updated", "duplicate"}
            and isinstance(item, dict)
            and item.get("id")
        ):
            knowledge_ids.append(str(item["id"]))
    return {
        "status": "COMPLETED",
        "knowledge_ids": knowledge_ids,
        "claim_statuses": statuses,
        "partition": partition,
    }


def partition_verified_correction_answer(
    user_request,
    verified_answer,
    search_result,
    disputed_items,
):
    """Extract reusable correction claims from an already accepted fact answer."""
    compact_disputed = [
        {
            "id": str(item.get("id") or "")[:120],
            "subject": str(item.get("subject") or "")[:300],
            "claim": str(item.get("claim") or "")[:2000],
        }
        for item in (disputed_items or [])[:8]
        if isinstance(item, dict) and item.get("id")
    ]
    assessment = {
        "decision": "ASK",
        "importance": "LOW",
        "sharing_risk": "NORMAL",
        "knowledge_type": "changing",
        "valid_for_days": None,
        "has_reusable_component": True,
        "reason": (
            "A low-impact public correction already passed Casper's fact "
            "answer acceptance gate; lifecycle remains AI-owned."
        ),
    }
    return partition_mixed_answer(
        user_request,
        verified_answer,
        search_result,
        assessment,
        prompt_path="prompts/nerv_knowledge_correction_partition.txt",
        answer_source="casper_audited_fact_correction",
        additional_context={
            "disputed_knowledge": compact_disputed,
            "user_correction_is_not_evidence": True,
        },
    )


def _certification_prompt(user_request, candidate_answer):
    """Build a second, explicit fact-certification request."""
    request = str(user_request or "").strip()[:1800]
    answer = str(candidate_answer or "").strip()[:2800]
    if _CJK_RE.search(request):
        return (
            "请独立重新核验下面问题。不要默认候选回答正确；请检查其中每个"
            "关键事实。若有错误或遗漏，请纠正后给出完整答案；若正确，也请"
            "重新给出完整答案。只回答问题，不要讨论这段指令。\n\n原问题：\n"
            + request
            + "\n\n待核验回答：\n"
            + answer
        )[:5000]
    return (
        "Independently re-check the question below. Do not assume the candidate "
        "answer is correct. Check every consequential factual claim. Correct "
        "errors or omissions and then provide a complete answer; if it is "
        "correct, restate the complete answer. Answer only the question.\n\n"
        "Original question:\n"
        + request
        + "\n\nCandidate answer:\n"
        + answer
    )[:5000]


def attempt(user_request, query, search_result, fact_scope, risk="low", status_callback=None):
    """Return a governed answer, handoff, or skipped-policy record."""
    from casper import external_ai
    import knowledge

    assessment = assess_request(user_request, fact_scope, risk=risk)
    print(
        "[EXTERNAL FACT FALLBACK PREFLIGHT]",
        "decision=" + str(assessment.get("decision") or "SKIP"),
        "importance=" + str(assessment.get("importance") or "HIGH"),
        "type=" + str(assessment.get("knowledge_type") or "event"),
        "mixed_reusable=" + str(
            assessment.get("has_reusable_component") is True
        ),
    )
    if assessment.get("decision") != "ASK":
        return {"status": "SKIPPED", "assessment": assessment}
    if status_callback:
        status_callback("3-5-7 没有完整答案，Bekki 正在询问外部 AI… 🧠")
    external_result = external_ai.ask_prompt(
        assessment["outbound_prompt"],
        source_kind="fact_lookup_fallback",
    )
    status = str((external_result or {}).get("status") or "").upper()
    print(
        "[EXTERNAL FACT FALLBACK DESKTOP]",
        "status=" + (status or "UNKNOWN"),
        "prompt_sent=" + str((external_result or {}).get("prompt_sent")),
        "answer_chars=" + str(
            len(str((external_result or {}).get("answer") or ""))
        ),
    )
    if status == "DESKTOP_LOGIN_REQUIRED":
        return {
            "status": "HUMAN_HANDOFF",
            "pending_approval": {
                "event": "external_ai_desktop_login",
                "handoff_type": "external_ai_login_handoff",
                "resume_after_user_confirmation": True,
                "original_request": str(user_request or query),
                "reason": "ChatGPT Desktop requires login before fallback.",
            },
            "assessment": assessment,
        }
    if status != "COMPLETED":
        return {
            "status": status or "EXTERNAL_AI_FAILED",
            "assessment": assessment,
        }
    answer = str(external_result.get("answer") or "").strip()
    if not answer:
        return {"status": "EMPTY_ANSWER", "assessment": assessment}

    knowledge_type = str(assessment.get("knowledge_type") or "event").lower()
    importance = str(assessment.get("importance") or "HIGH").upper()

    # Time-sensitive facts answer the current turn directly but never enter
    # Knowledge. A mixed request may still contain separate reusable claims;
    # AI must explicitly partition those claims before any partial persistence.
    if knowledge_type in {"changing", "event", "news"} and importance == "LOW":
        partition = None
        knowledge_ids = []
        if assessment.get("has_reusable_component") is True:
            partition = partition_mixed_answer(
                user_request,
                answer,
                search_result,
                assessment,
            )
            if isinstance(partition, dict) and partition.get("answer_usable") is not True:
                return {
                    "status": "REJECTED",
                    "assessment": assessment,
                    "partition": partition,
                }
            if isinstance(partition, dict):
                for candidate in partition.get("claims", []):
                    if not isinstance(candidate, dict) or candidate.get("persist") is not True:
                        continue
                    claim_status, claim_item = knowledge.apply_external_ai_partitioned_claim(
                        user_request=user_request,
                        answer=answer,
                        assessment=assessment,
                        candidate=candidate,
                        provider=str(
                            external_result.get("provider") or "ChatGPT Desktop"
                        ),
                        outbound_prompt=str(
                            external_result.get("outbound_prompt")
                            or assessment["outbound_prompt"]
                        ),
                    )
                    if claim_status in {"verified", "updated", "duplicate"} and isinstance(
                        claim_item, dict
                    ):
                        knowledge_ids.append(str(claim_item.get("id") or ""))
        print(
            "[EXTERNAL FACT FALLBACK CURRENT]",
            (
                "accepted_with_partitioned_knowledge=" + str(len(knowledge_ids))
                if knowledge_ids else "accepted_without_persistence"
            ),
        )
        return {
            "status": "CURRENT_REFERENCE",
            "answer": answer,
            "assessment": assessment,
            "partition": partition,
            "knowledge_status": (
                "reusable_components_recorded"
                if knowledge_ids else "not_recorded_time_sensitive"
            ),
            "knowledge_ids": [value for value in knowledge_ids if value],
            "provider": str(external_result.get("provider") or "ChatGPT Desktop"),
        }

    certification_context = None
    final_answer = answer
    if importance == "HIGH":
        if status_callback:
            status_callback("这个问题影响较高，Bekki 正在进行第二次认证… 🛡️")
        certification_prompt = _certification_prompt(user_request, answer)
        certification_result = external_ai.ask_prompt(
            certification_prompt,
            source_kind="fact_lookup_high_impact_certification",
        )
        certification_status = str(
            (certification_result or {}).get("status") or ""
        ).upper()
        if certification_status != "COMPLETED":
            return {
                "status": "CERTIFICATION_FAILED",
                "assessment": assessment,
            }
        final_answer = str(certification_result.get("answer") or "").strip()
        if not final_answer:
            return {
                "status": "CERTIFICATION_EMPTY",
                "assessment": assessment,
            }
        certification_context = {
            "performed": True,
            "initial_answer": answer[:6000],
            "certification_prompt": certification_prompt,
            "provider": str(
                certification_result.get("provider") or "ChatGPT Desktop"
            ),
        }

    if status_callback:
        status_callback("Bekki 正在检查回答范围和认证结果… 🔐")
    audit = audit_answer(
        user_request,
        final_answer,
        search_result,
        assessment,
        certification_context=certification_context,
    )
    print(
        "[EXTERNAL FACT FALLBACK AUDIT]",
        "decision=" + str(audit.get("decision") or "REJECT"),
        "disposition=" + str(
            audit.get("answer_disposition") or "REJECT"
        ),
        "confidence=" + str(audit.get("confidence") or 0),
    )
    if audit.get("decision") != "AUTO_VERIFY":
        return {
            "status": "REJECTED",
            "assessment": assessment,
            "audit": audit,
        }
    audited_answer = str(audit.get("canonical_answer") or "").strip()
    if not audited_answer:
        audited_answer = final_answer
    if not audited_answer:
        return {
            "status": "REJECTED",
            "assessment": assessment,
            "audit": audit,
        }
    if importance == "HIGH":
        return {
            "status": "CERTIFIED",
            "answer": audited_answer,
            "assessment": assessment,
            "audit": audit,
            "knowledge_status": "not_recorded_high_impact",
            "provider": str(external_result.get("provider") or "ChatGPT Desktop"),
        }
    knowledge_status, knowledge_item = knowledge.apply_external_ai_fact_fallback(
        user_request=user_request,
        answer=audited_answer,
        assessment=assessment,
        audit=audit,
        provider=str(external_result.get("provider") or "ChatGPT Desktop"),
        outbound_prompt=str(external_result.get("outbound_prompt") or assessment["outbound_prompt"]),
    )
    if knowledge_status not in {"verified", "duplicate", "updated"}:
        return {
            "status": "PERSISTENCE_REJECTED",
            "assessment": assessment,
            "audit": audit,
        }
    return {
        "status": "VERIFIED",
        "answer": audited_answer,
        "assessment": assessment,
        "audit": audit,
        "knowledge_status": knowledge_status,
        "knowledge_id": (
            knowledge_item.get("id") if isinstance(knowledge_item, dict) else None
        ),
        "provider": str(external_result.get("provider") or "ChatGPT Desktop"),
    }
