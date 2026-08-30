"""Closed schemas and constants used by NERV Core V1."""

PROFILE_SCHEMA_VERSION = 1
SKILL_SCHEMA_VERSION = 1
CURIOSITY_SCHEMA_VERSION = 1

PROFILE_CATEGORIES = {
    "identity",
    "household",
    "location",
    "work",
    "device",
    "preference",
    "routine",
    "constraint",
    "relationship",
}

PROFILE_OPERATIONS = {"NONE", "ADD", "UPDATE", "REMOVE"}
PROFILE_SENSITIVITY = {"NORMAL", "SENSITIVE"}
PROFILE_STATUSES = {"active", "pending_review", "removed"}
LEARNING_STATES = {"OBSERVED", "DRAFT", "TESTED", "VERIFIED", "DEPRECATED"}
KNOWLEDGE_DOMAINS = {
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
}
KNOWLEDGE_VERIFICATION_LEVELS = {"standard", "double"}

KNOWLEDGE_TEMPORAL_SCOPE_SCHEMA = {
    "type": "object",
    "properties": {
        "scope_type": {
            "type": "string",
            "enum": [
                "LATEST_COMPLETED_PERIOD",
                "EXPLICIT_PERIOD",
            ],
        },
        "requested_period": {"type": "string", "minLength": 1, "maxLength": 240},
        "allow_previous_period": {"type": "boolean"},
    },
    "required": [
        "scope_type", "requested_period", "allow_previous_period"
    ],
    "additionalProperties": False,
}


PROFILE_WRITER_SCHEMA = {
    "type": "object",
    "properties": {
        "proposals": {
            "type": "array",
            "maxItems": 3,
            "items": {
                "type": "object",
                "properties": {
                    "operation": {
                        "type": "string",
                        "enum": sorted(PROFILE_OPERATIONS),
                    },
                    "category": {
                        "type": "string",
                        "enum": sorted(PROFILE_CATEGORIES),
                    },
                    "key": {"type": "string"},
                    "value": {"type": "string"},
                    "confidence": {
                        "type": "number",
                        "minimum": 0,
                        "maximum": 1,
                    },
                    "evidence_quote": {"type": "string"},
                    "sensitivity": {
                        "type": "string",
                        "enum": sorted(PROFILE_SENSITIVITY),
                    },
                    "reason": {"type": "string"},
                },
                "required": [
                    "operation",
                    "category",
                    "key",
                    "value",
                    "confidence",
                    "evidence_quote",
                    "sensitivity",
                    "reason",
                ],
                "additionalProperties": False,
            },
        }
    },
    "required": ["proposals"],
    "additionalProperties": False,
}


CURIOSITY_WRITER_SCHEMA = {
    "type": "object",
    "properties": {
        "proposal": {
            "anyOf": [
                {"type": "null"},
                {
                    "type": "object",
                    "properties": {
                        "question": {"type": "string", "maxLength": 300},
                        "reason": {"type": "string", "maxLength": 300},
                        "trigger_summary": {"type": "string", "maxLength": 160},
                        "interest_score": {
                            "type": "number",
                            "minimum": 0,
                            "maximum": 1,
                        },
                        "confidence": {
                            "type": "number",
                            "minimum": 0,
                            "maximum": 1,
                        },
                        "sharing_risk": {
                            "type": "string",
                            "enum": ["NORMAL", "SENSITIVE", "PROHIBITED"],
                        },
                        "topic_stage": {
                            "type": "string",
                            "enum": [
                                "NEW_OR_SPARSE",
                                "DEVELOPING",
                                "SUSTAINED",
                            ],
                        },
                        "current_turn_depth": {
                            "type": "string",
                            "enum": [
                                "FOUNDATION",
                                "ADJACENT",
                                "SPECIALIST",
                            ],
                        },
                        "question_depth": {
                            "type": "string",
                            "enum": [
                                "FOUNDATION",
                                "ADJACENT",
                                "SPECIALIST",
                            ],
                        },
                        "foundation_facet": {
                            "type": "string",
                            "enum": [
                                "PEOPLE",
                                "HISTORY",
                                "WORKS_OR_PERFORMANCES",
                                "EVENTS_OR_STORIES",
                                "RELATIONSHIPS_OR_CULTURE",
                                "ORDINARY_BEHAVIOR",
                                "STRUCTURE_OR_ROSTER",
                                "OTHER_CONCRETE_CONTEXT",
                                "SPECIALIST_ANALYSIS",
                            ],
                        },
                        "breadth_relation": {
                            "type": "string",
                            "enum": [
                                "DISTINCT_FOUNDATION_FACET",
                                "SAME_NARROW_FACET",
                                "PROPORTIONATE_DEEPENING",
                            ],
                        },
                        "breadth_fit": {"type": "boolean"},
                        "related_curiosity_ids": {
                            "type": "array",
                            "maxItems": 8,
                            "items": {"type": "string", "maxLength": 120},
                        },
                        "related_knowledge_ids": {
                            "type": "array",
                            "maxItems": 8,
                            "items": {"type": "string", "maxLength": 160},
                        },
                        "depth_fit": {"type": "boolean"},
                    },
                    "required": [
                        "question",
                        "reason",
                        "trigger_summary",
                        "interest_score",
                        "confidence",
                        "sharing_risk",
                        "topic_stage",
                        "current_turn_depth",
                        "question_depth",
                        "foundation_facet",
                        "breadth_relation",
                        "breadth_fit",
                        "related_curiosity_ids",
                        "related_knowledge_ids",
                        "depth_fit",
                    ],
                    "additionalProperties": False,
                },
            ]
        }
    },
    "required": ["proposal"],
    "additionalProperties": False,
}


CURIOSITY_SELECTION_SCHEMA = {
    "type": "object",
    "properties": {
        "decision": {"type": "string", "enum": ["ASK", "SKIP"]},
        "candidate_id": {
            "anyOf": [{"type": "string"}, {"type": "null"}],
        },
        "reason": {"type": "string"},
    },
    "required": ["decision", "candidate_id", "reason"],
    "additionalProperties": False,
}


CURIOSITY_KNOWLEDGE_CANDIDATE_SCHEMA = {
    "type": "object",
    "properties": {
        "decision": {"type": "string", "enum": ["VERIFY", "SKIP"]},
        "subject": {"type": "string", "maxLength": 200},
        "claim": {"type": "string", "maxLength": 1200},
        "topics": {
            "type": "array",
            "maxItems": 8,
            "items": {"type": "string", "maxLength": 80},
        },
        "knowledge_domain": {
            "type": "string",
            "enum": sorted(KNOWLEDGE_DOMAINS),
        },
        "cluster_label": {"type": "string", "maxLength": 120},
        "verification_level": {
            "type": "string",
            "enum": sorted(KNOWLEDGE_VERIFICATION_LEVELS),
        },
        "knowledge_type": {
            "type": "string",
            "enum": [
                "stable", "reviewable", "changing", "event", "news"
            ],
        },
        "lifecycle_basis": {
            "type": "string",
            "enum": [
                "FIXED_HISTORY",
                "DURABLE_EXPLANATION_DEFINITION_OR_MECHANISM",
                "MAINTAINED_SET_OR_STRUCTURE",
                "TRANSIENT_NONSTRUCTURAL_STATE_OR_EVENT",
            ],
        },
        "valid_for_days": {
            "anyOf": [
                {"type": "integer", "minimum": 1, "maximum": 3650},
                {"type": "null"},
            ]
        },
        "temporal_scope": {
            "anyOf": [KNOWLEDGE_TEMPORAL_SCOPE_SCHEMA, {"type": "null"}]
        },
        "risk": {"type": "string", "enum": ["low", "medium", "high"]},
        "reason": {"type": "string", "maxLength": 300},
    },
    "required": [
        "decision",
        "subject",
        "claim",
        "topics",
        "knowledge_domain",
        "cluster_label",
        "verification_level",
        "knowledge_type",
        "lifecycle_basis",
        "valid_for_days",
        "risk",
        "reason",
    ],
    "additionalProperties": False,
}


CURIOSITY_KNOWLEDGE_VERDICT_SCHEMA = {
    "type": "object",
    "properties": {
        "decision": {
            "type": "string",
            "enum": ["PROMOTE", "KEEP_UNVERIFIED", "REJECT"],
        },
        "subject": {"type": "string", "maxLength": 200},
        "canonical_claim": {"type": "string", "maxLength": 1200},
        "topics": {
            "type": "array",
            "maxItems": 8,
            "items": {"type": "string", "maxLength": 80},
        },
        "knowledge_domain": {
            "type": "string",
            "enum": sorted(KNOWLEDGE_DOMAINS),
        },
        "cluster_label": {"type": "string", "maxLength": 120},
        "verification_level": {
            "type": "string",
            "enum": sorted(KNOWLEDGE_VERIFICATION_LEVELS),
        },
        "knowledge_type": {
            "type": "string",
            "enum": [
                "stable", "reviewable", "changing", "event", "news"
            ],
        },
        "lifecycle_basis": {
            "type": "string",
            "enum": [
                "FIXED_HISTORY",
                "DURABLE_EXPLANATION_DEFINITION_OR_MECHANISM",
                "MAINTAINED_SET_OR_STRUCTURE",
                "TRANSIENT_NONSTRUCTURAL_STATE_OR_EVENT",
            ],
        },
        "valid_for_days": {
            "anyOf": [
                {"type": "integer", "minimum": 1, "maximum": 3650},
                {"type": "null"},
            ]
        },
        "temporal_scope": {
            "anyOf": [KNOWLEDGE_TEMPORAL_SCOPE_SCHEMA, {"type": "null"}]
        },
        "confidence": {"type": "number", "minimum": 0, "maximum": 1},
        "risk": {"type": "string", "enum": ["low", "medium", "high"]},
        "reason": {"type": "string", "maxLength": 400},
    },
    "required": [
        "decision",
        "subject",
        "canonical_claim",
        "topics",
        "knowledge_domain",
        "cluster_label",
        "verification_level",
        "knowledge_type",
        "lifecycle_basis",
        "valid_for_days",
        "confidence",
        "risk",
        "reason",
    ],
    "additionalProperties": False,
}


CURIOSITY_KNOWLEDGE_CERTIFICATION_SCHEMA = {
    "type": "object",
    "properties": {
        "decision": {"type": "string", "enum": ["CERTIFY", "DECLINE"]},
        "confidence": {"type": "number", "minimum": 0, "maximum": 1},
        "reason": {"type": "string", "maxLength": 400},
    },
    "required": ["decision", "confidence", "reason"],
    "additionalProperties": False,
}


EXTERNAL_AI_REQUEST_SCHEMA = {
    "type": "object",
    "properties": {
        "decision": {
            "type": "string",
            "enum": ["SEND", "CLARIFY", "REFUSE"],
        },
        "outbound_prompt": {"type": "string"},
        "purpose": {"type": "string"},
        "sharing_risk": {
            "type": "string",
            "enum": ["NORMAL", "SENSITIVE", "PROHIBITED"],
        },
        "reason": {"type": "string"},
    },
    "required": [
        "decision",
        "outbound_prompt",
        "purpose",
        "sharing_risk",
        "reason",
    ],
    "additionalProperties": False,
}
