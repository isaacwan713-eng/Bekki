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
                    },
                    "required": [
                        "question",
                        "reason",
                        "trigger_summary",
                        "interest_score",
                        "confidence",
                        "sharing_risk",
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
        "knowledge_type": {
            "type": "string",
            "enum": ["stable", "changing", "event", "news"],
        },
        "valid_for_days": {
            "anyOf": [
                {"type": "integer", "minimum": 1, "maximum": 3650},
                {"type": "null"},
            ]
        },
        "risk": {"type": "string", "enum": ["low", "medium", "high"]},
        "reason": {"type": "string", "maxLength": 300},
    },
    "required": [
        "decision",
        "subject",
        "claim",
        "topics",
        "knowledge_type",
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
        "knowledge_type": {
            "type": "string",
            "enum": ["stable", "changing", "event", "news"],
        },
        "valid_for_days": {
            "anyOf": [
                {"type": "integer", "minimum": 1, "maximum": 3650},
                {"type": "null"},
            ]
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
        "knowledge_type",
        "valid_for_days",
        "confidence",
        "risk",
        "reason",
    ],
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
