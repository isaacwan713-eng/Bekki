"""V2 Melchior request router.

Melchior decides what kind of result the user needs and how that request
should be handled. It does not execute searches, read documents, or generate
the final user-facing reply.
"""

import copy
import json
import re
from datetime import datetime

import context as context_manager
import document
import magi
import memory
import tools
import vision


VALID_MODES = {
    "LOCAL_ANSWER",
    "NEWS_FEED",
    "DISCUSSION_FEED",
    "FACT_LOOKUP",
    "CLAIM_CHECK",
    "SOCIAL_RESEARCH",
    "MEDIA_WATCH",
    "SHOPPING_RESEARCH",
    "RECOMMENDATION_RESEARCH",
    "TASK_ACTION",
    "NERV_SKILL_ACTION",
    "EXTERNAL_AI_ACTION",
    "DEVICE_ACTION",
}

VALID_SOCIAL_PLATFORMS = {
    "bilibili",
    "reddit",
    "xiaohongshu",
    "instagram",
    "x",
    "youtube",
}

VALID_RISKS = {
    "low",
    "medium",
    "high",
}


def _runtime_profile_context():
    try:
        import location

        return location.get_localization_context()
    except (ImportError, AttributeError, OSError, TypeError, ValueError):
        return "Runtime localization profile unavailable."

VALID_COMPLEXITIES = {
    "low",
    "medium",
    "high",
}

VALID_REASONING_PROFILES = {
    "quick",
    "standard",
    "analytical",
    "cautious",
}

VALID_RESEARCH_PROFILES = {
    "local_context",
    "weighted_news",
    "discussion_synthesis",
    "official_first",
    "evidence_verification",
    "platform_native",
    "media_watch",
    "shopping_match",
    "recommendation_match",
}

VALID_SKILL_ROUTES = {"none", "lookup"}
VALID_DEVICE_SCOPES = {
    "FILE_ACTION",
    "APPLICATION_ACTION",
    "WINDOW_ACTION",
    "SYSTEM_ACTION",
    "LIBRARY_ACTION",
    "RECYCLE_BIN_ACTION",
    "OTHER",
}
VALID_INTERACTION_MODES = {"TASK", "COMPANION"}
VALID_CONTEXT_PROFILES = {
    "MINIMAL",
    "CONVERSATION",
    "MEMORY",
    "NERV_LEARNING",
    "NERV_CURIOSITY",
    "COMPANION",
    "DOCUMENT",
    "IMAGE",
}

_ROUTER_PLAN_SCHEMA = {
    "type": "object",
    "properties": {
        "response_mode": {
            "type": "string",
            "enum": sorted(VALID_MODES),
        },
        "needs_search": {"type": "boolean"},
        "research_depth": {"type": "string"},
        "source_policy": {"type": "string"},
        "risk": {"type": "string", "enum": sorted(VALID_RISKS)},
        "complexity": {
            "type": "string",
            "enum": sorted(VALID_COMPLEXITIES),
        },
        "reasoning_profile": {
            "type": "string",
            "enum": sorted(VALID_REASONING_PROFILES),
        },
        "research_profile": {"type": "string"},
        "claim_to_verify": {
            "anyOf": [{"type": "string"}, {"type": "null"}],
        },
        "social_platforms": {
            "type": "array",
            "items": {"type": "string"},
        },
        "recommendation_domain": {
            "anyOf": [{"type": "string"}, {"type": "null"}],
        },
        "skill_route": {
            "type": "string",
            "enum": sorted(VALID_SKILL_ROUTES),
        },
        "device_scope": {
            "anyOf": [
                {"type": "string", "enum": sorted(VALID_DEVICE_SCOPES)},
                {"type": "null"},
            ]
        },
        "interaction_mode": {
            "type": "string",
            "enum": sorted(VALID_INTERACTION_MODES),
        },
        "context_profile": {
            "type": "string",
            "enum": sorted(VALID_CONTEXT_PROFILES),
        },
        "reason": {"type": "string"},
    },
    "required": [
        "response_mode",
        "risk",
        "complexity",
        "reasoning_profile",
        "skill_route",
        "device_scope",
        "interaction_mode",
        "context_profile",
        "reason",
    ],
    "additionalProperties": False,
}

MODE_INVARIANTS = {
    "LOCAL_ANSWER": {
        "needs_search": False,
        "research_depth": "none",
        "source_policy": "local_context",
        "research_profile": "local_context",
    },
    "NEWS_FEED": {
        "needs_search": True,
        "research_depth": "ranked_feed",
        "source_policy": "weighted_news",
        "research_profile": "weighted_news",
    },
    "DISCUSSION_FEED": {
        "needs_search": True,
        "research_depth": "discussion_roundup",
        "source_policy": "discussion_sources",
        "research_profile": "discussion_synthesis",
    },
    "FACT_LOOKUP": {
        "needs_search": True,
        "research_depth": "direct_lookup",
        "source_policy": "official_first",
        "research_profile": "official_first",
    },
    "CLAIM_CHECK": {
        "needs_search": True,
        "research_depth": "3_5_7",
        "source_policy": "evidence_verification",
        "research_profile": "evidence_verification",
    },
    "SOCIAL_RESEARCH": {
        "needs_search": True,
        "research_depth": "social_handoff",
        "source_policy": "platform_native",
        "research_profile": "platform_native",
    },
    "MEDIA_WATCH": {
        "needs_search": True,
        "research_depth": "watch_discovery",
        "source_policy": "user_bounded_watch_sources",
        "research_profile": "media_watch",
    },
    "SHOPPING_RESEARCH": {
        "needs_search": True,
        "research_depth": "shopping_compare",
        "source_policy": "merchant_results",
        "research_profile": "shopping_match",
    },
    "RECOMMENDATION_RESEARCH": {
        "needs_search": True,
        "research_depth": "recommendation_compare",
        "source_policy": "domain_evidence",
        "research_profile": "recommendation_match",
    },
    "TASK_ACTION": {
        "needs_search": False,
        "research_depth": "none",
        "source_policy": "local_context",
        "research_profile": "local_context",
    },
    "NERV_SKILL_ACTION": {
        "needs_search": False,
        "research_depth": "none",
        "source_policy": "local_context",
        "research_profile": "local_context",
    },
    "EXTERNAL_AI_ACTION": {
        "needs_search": False,
        "research_depth": "none",
        "source_policy": "local_context",
        "research_profile": "local_context",
    },
    "DEVICE_ACTION": {
        "needs_search": False,
        "research_depth": "none",
        "source_policy": "local_context",
        "research_profile": "local_context",
    },
}

DEFAULT_PLAN = {
    "response_mode": "LOCAL_ANSWER",
    "needs_search": False,
    "research_depth": "none",
    "source_policy": "local_context",
    "risk": "low",
    "complexity": "low",
    "reasoning_profile": "standard",
    "research_profile": "local_context",
    "claim_to_verify": None,
    "social_platforms": [],
    "recommendation_domain": None,
    "skill_route": "none",
    "interaction_mode": "TASK",
    "context_profile": "MINIMAL",
    "needs_balthasar": False,
    "reason": "Fallback route: answer from local context when possible.",
}


def _document_context():
    if not document.has_document():
        return "NO DOCUMENT ATTACHED"

    current = document.get_current_document()
    return (
        "An active local document is loaded.\n"
        "File name: " + str(current.get("file_name", ""))
    )


def _image_context():
    if not vision.has_image():
        return "NO IMAGE ATTACHED"

    current = vision.get_current_image()
    return (
        "An active image is loaded.\n"
        "File name: " + str(current.get("file_name", ""))
    )


def _normalize_choice(value, valid_values, fallback):
    normalized = str(value).lower().strip()
    if normalized not in valid_values:
        return fallback
    return normalized


def _raw_plan_has_valid_mode(plan):
    if not isinstance(plan, dict):
        return False
    return str(plan.get("response_mode", "")).upper().strip() in VALID_MODES


def _repair_raw_plan_format_aliases(plan):
    """Repair a known schema-label echo without making a new semantic choice."""
    if not isinstance(plan, dict):
        return plan
    repaired = dict(plan)
    if str(repaired.get("response_mode") or "").upper().strip() == "COMPANION":
        repaired["response_mode"] = "LOCAL_ANSWER"
        repaired["interaction_mode"] = "COMPANION"
        repaired["context_profile"] = "COMPANION"
    return repaired


def _builtin_device_scope(user_message):
    """Return the deterministic scope of a built-in Windows device surface.

    This helper only runs after the main router has already selected
    DEVICE_ACTION.  Recycle Bin is an operating-system primitive with a
    dedicated bounded executor, so it must never be widened into a web/content
    learning workflow by a second semantic model.
    """
    normalized = re.sub(r"\s+", " ", str(user_message or "")).casefold().strip()
    if "回收站" in normalized or "recycle bin" in normalized:
        return "RECYCLE_BIN_ACTION"
    return ""


def _is_direct_application_launch(user_message):
    """Recognize only a simple app launch, not a reusable content workflow."""
    text = re.sub(r"\s+", " ", str(user_message or "")).strip()
    matches = bool(
        re.match(
            r"^(?:(?:请|麻烦)\s*)?(?:帮我\s*)?(?:打开|启动|运行)\s*\S.+$",
            text,
            flags=re.IGNORECASE,
        )
        or re.match(
            r"^(?:please\s+)?(?:open|launch|start|run)\s+\S.+$",
            text,
            flags=re.IGNORECASE,
        )
    )
    if not matches:
        return False
    content_markers = (
        "文件夹", "目录", "回收站", "战术", "模组", "插件", "地图", "存档",
        "folder", "directory", "recycle bin", "tactic", "mod", "plugin",
        "map", "save", "shader",
    )
    lowered = text.casefold()
    return not any(marker in lowered for marker in content_markers)


def _is_explicit_steam_game_launch(user_message):
    """Recognize a bounded request to launch one named game through Steam."""
    text = re.sub(r"\s+", " ", str(user_message or "")).strip()
    patterns = (
        r"^(?:请|麻烦)?\s*(?:帮我)?\s*(?:打开|启动|运行)\s*steam\s*(?:里|中的|上)?\s*(?:的)?\s*(?:游戏)?\s*\S.+$",
        r"^(?:请|麻烦)?\s*(?:帮我)?\s*用\s*steam\s*(?:打开|启动|运行)\s*\S.+$",
        r"^(?:请|麻烦)?\s*(?:帮我)?\s*在\s*steam\s*(?:里|中|上)?\s*(?:打开|启动|运行)\s*\S.+$",
        r"^(?:please\s+)?(?:open|launch|start|run)\s+\S.+\s+(?:in|with|through)\s+steam$",
    )
    return any(re.match(pattern, text, flags=re.IGNORECASE) for pattern in patterns)


def _is_steam_library_list_request(user_message):
    """Recognize an explicit request to list locally installed Steam games."""
    text = re.sub(r"\s+", " ", str(user_message or "")).strip()
    patterns = (
        r"^(?:请|麻烦)?\s*(?:帮我)?\s*(?:看看|看一下|查看|列出|显示)\s*(?:我的)?\s*steam\s*(?:游戏)?库\s*(?:里|中)?\s*(?:有|装了|安装了)?\s*(?:什么|哪些)?\s*(?:游戏)?\s*[？?。.!！]?$",
        r"^(?:请|麻烦)?\s*(?:帮我)?\s*(?:看看|看一下|查看|列出|显示)\s*steam\s*(?:里|中|上)?\s*(?:有|装了|安装了)\s*(?:什么|哪些)\s*(?:游戏)?\s*[？?。.!！]?$",
        r"^(?:我的)?\s*steam\s*(?:游戏)?库\s*(?:里|中)?\s*(?:有|装了|安装了)\s*(?:什么|哪些)\s*(?:游戏)?\s*[？?。.!！]?$",
        r"^(?:please\s+)?(?:show|list|display)\s+(?:me\s+)?(?:my\s+)?installed\s+steam\s+games\s*[.!]?$",
        r"^(?:what(?:'s| is)\s+in\s+my\s+steam\s+library|which\s+steam\s+games\s+are\s+installed)\s*[?!.]?$",
    )
    return any(re.match(pattern, text, flags=re.IGNORECASE) for pattern in patterns)


def _classify_content_device_scope(
    user_message,
    conversation_context,
    router_skill_route="none",
    router_device_scope=None,
):
    """Focused AI gate that may narrow, but never widen, the main route."""
    builtin_scope = _builtin_device_scope(user_message)
    if builtin_scope:
        return builtin_scope

    skill_lookup_selected = (
        str(router_skill_route or "none").lower().strip() == "lookup"
    )
    normalized_device_scope = str(
        router_device_scope or ""
    ).upper().strip()

    # A file/system/library action must not be widened into browser research.
    # When the detailed router says APPLICATION_ACTION or OTHER, however, an
    # explicit request to learn and execute a reusable content-folder workflow
    # deserves one independent reliable-model audit. This keeps the semantic
    # decision in AI while providing a safe bootstrap path before any verified
    # Skill exists.
    learning_bootstrap_audit = (
        not skill_lookup_selected
        and normalized_device_scope in {"APPLICATION_ACTION", "OTHER"}
    )
    if not skill_lookup_selected and not learning_bootstrap_audit:
        return "OTHER"

    prompt_input = (
        "CURRENT_REQUEST (authoritative):\n"
        + str(user_message)[:800]
        + "\nRECENT_CONTEXT (reference resolution only):\n"
        + _routing_reference_context(
            user_message,
            conversation_context,
            1200,
        )
    )
    if learning_bootstrap_audit:
        attempts = (
            (
                "prompts/melchior_content_action_scope.txt",
                "gemma4:12b",
                700,
                3072,
            ),
            (
                "prompts/melchior_content_action_scope_retry.txt",
                "gemma4:12b",
                1000,
                4096,
            ),
        )
    else:
        attempts = (
            (
                "prompts/melchior_content_action_scope.txt",
                "llama3.2:latest",
                320,
                2048,
            ),
            (
                "prompts/melchior_content_action_scope_retry.txt",
                "gemma4:12b",
                1000,
                4096,
            ),
        )
    for prompt_path, model_name, output_budget, context_budget in attempts:
        raw = tools.run_ai_prompt(
            prompt_path,
            prompt_input,
            expect_json=False,
            num_ctx=context_budget,
            num_predict=output_budget,
            think=False,
            model_name=model_name,
        )
        value = str(raw or "").strip().upper()
        if value in {
            "CONTENT_DEVICE_ACTION", "RECYCLE_BIN_ACTION", "OTHER"
        }:
            return value
        prompt_input += "\nINVALID_PREVIOUS_OUTPUT:\n" + value[:80]
    return ""


def _normalize_plan(plan):
    if not isinstance(plan, dict):
        return dict(DEFAULT_PLAN)

    normalized = dict(DEFAULT_PLAN)
    normalized.update(plan)

    response_mode = str(normalized.get("response_mode", "")).upper().strip()
    if response_mode not in VALID_MODES:
        return dict(DEFAULT_PLAN)
    normalized["response_mode"] = response_mode

    # Mode behavior remains deterministic so malformed model output cannot
    # accidentally disable required search or select the wrong source policy.
    normalized.update(MODE_INVARIANTS[response_mode])

    normalized["risk"] = _normalize_choice(
        normalized.get("risk"),
        VALID_RISKS,
        DEFAULT_PLAN["risk"],
    )
    normalized["complexity"] = _normalize_choice(
        normalized.get("complexity"),
        VALID_COMPLEXITIES,
        DEFAULT_PLAN["complexity"],
    )
    normalized["reasoning_profile"] = _normalize_choice(
        normalized.get("reasoning_profile"),
        VALID_REASONING_PROFILES,
        DEFAULT_PLAN["reasoning_profile"],
    )

    # research_profile is owned by response_mode during this migration phase.
    # Later MAGI versions may allow persona and research strategy to vary
    # independently after each controller supports that behavior.
    normalized["research_profile"] = MODE_INVARIANTS[response_mode][
        "research_profile"
    ]

    platforms = normalized.get("social_platforms", [])
    if not isinstance(platforms, list):
        platforms = []
    normalized["social_platforms"] = [
        str(platform).lower().strip()
        for platform in platforms
        if str(platform).lower().strip() in VALID_SOCIAL_PLATFORMS
    ]
    normalized["social_platforms"] = list(
        dict.fromkeys(normalized["social_platforms"])
    )

    domain = str(normalized.get("recommendation_domain", "")).upper().strip()
    valid_domains = {
        "PRODUCT", "RESTAURANT", "LOCAL_SERVICE", "HEALTHCARE_PROVIDER",
    }
    if response_mode == "SHOPPING_RESEARCH":
        domain = "PRODUCT"
    elif response_mode != "RECOMMENDATION_RESEARCH" or domain not in valid_domains:
        domain = None
    normalized["recommendation_domain"] = domain

    if not isinstance(normalized.get("claim_to_verify"), str):
        normalized["claim_to_verify"] = None
    elif not normalized["claim_to_verify"].strip():
        normalized["claim_to_verify"] = None
    else:
        normalized["claim_to_verify"] = normalized[
            "claim_to_verify"
        ].strip()[:500]

    normalized["reason"] = str(normalized.get("reason", ""))[:280]
    skill_route = str(normalized.get("skill_route") or "none").lower().strip()
    if response_mode != "DEVICE_ACTION" or skill_route not in VALID_SKILL_ROUTES:
        skill_route = "none"
    normalized["skill_route"] = skill_route
    device_scope = str(
        normalized.get("device_scope") or ""
    ).upper().strip()
    if (
        response_mode != "DEVICE_ACTION"
        or device_scope not in VALID_DEVICE_SCOPES
    ):
        device_scope = None
    normalized["device_scope"] = device_scope

    interaction_mode = str(
        normalized.get("interaction_mode") or "TASK"
    ).upper().strip()
    context_profile = str(
        normalized.get("context_profile") or "MINIMAL"
    ).upper().strip()
    if interaction_mode not in VALID_INTERACTION_MODES:
        interaction_mode = "TASK"
    if context_profile not in VALID_CONTEXT_PROFILES:
        context_profile = "MINIMAL"

    # Emotional alignment is useful only for an actual companion reply.  A
    # recommendation, lookup, action, or routine question must not load a
    # second persona model merely because the wording happens to be warm.
    if response_mode != "LOCAL_ANSWER":
        interaction_mode = "TASK"
        if context_profile in {"COMPANION", "NERV_LEARNING", "NERV_CURIOSITY"}:
            context_profile = "MINIMAL"
    # IMAGE and DOCUMENT are concrete current-turn evidence profiles. If the
    # model simultaneously labels one as COMPANION, preserve its evidence
    # selection and drop only the inconsistent emotional-mode flag. This is a
    # contract reconciliation, not a semantic reclassification.
    if context_profile in {"IMAGE", "DOCUMENT"}:
        interaction_mode = "TASK"
    elif interaction_mode == "COMPANION":
        context_profile = "COMPANION"
    elif context_profile == "COMPANION":
        context_profile = "MINIMAL"
    normalized["interaction_mode"] = interaction_mode
    normalized["context_profile"] = context_profile
    normalized["needs_balthasar"] = interaction_mode == "COMPANION"
    return normalized


def _reconcile_platformless_social_plan(plan, magi_route, user_message):
    """Keep platform-native search closed when no native platform was named.

    Open cross-site discussion requests are recovered as DISCUSSION_FEED;
    closed claims remain CLAIM_CHECK. Python applies MAGI's AI-owned semantic
    scope here and never guesses a platform.
    """

    if str(plan.get("response_mode") or "").upper().strip() != "SOCIAL_RESEARCH":
        return plan
    if plan.get("social_platforms"):
        return plan

    route = _valid_magi_route(magi_route)
    magi_scope = str(
        (magi_route or {}).get("search_scope") or ""
    ).upper().strip()
    if route is None or route[0] != "SEARCH" or magi_scope not in {
        "NEWS_FEED", "DISCUSSION_FEED", "FACT_LOOKUP", "CLAIM_CHECK", "MEDIA_WATCH",
    }:
        raise RuntimeError(
            "Melchior selected SOCIAL_RESEARCH without a supported platform "
            "or a recoverable MAGI search scope."
        )

    reconciled = dict(plan)
    reconciled.update(
        {
            "response_mode": magi_scope,
            "social_platforms": [],
            "claim_to_verify": (
                str(plan.get("claim_to_verify") or user_message).strip()[:500]
                if magi_scope == "CLAIM_CHECK"
                else None
            ),
            "reason": (
                "Platformless social routing was reconciled to MAGI's "
                + magi_scope
                + " search scope; no native platform was guessed."
            ),
        }
    )
    print("[MELCHIOR PLATFORMLESS SOCIAL RECONCILED]", magi_scope)
    return _normalize_plan(reconciled)


def _raw_plan_requests_nerv_audit(plan):
    """Detect an AI-produced local/skill contradiction, not user keywords."""
    if not isinstance(plan, dict):
        return False
    return (
        str(plan.get("response_mode") or "").upper().strip()
        == "LOCAL_ANSWER"
        and str(plan.get("context_profile") or "").upper().strip()
        not in {"NERV_LEARNING", "NERV_CURIOSITY"}
        and (
            str(plan.get("skill_route") or "").lower().strip() == "lookup"
            or bool(str(plan.get("device_scope") or "").strip())
        )
    )


def _audit_nerv_learning_query(user_message):
    """Ask the reliable model for one closed NERV inventory decision."""
    value = ""
    try:
        raw = tools.run_ai_prompt(
            "prompts/melchior_nerv_query_scope.txt",
            json.dumps(
                {"current_user_message": str(user_message or "")[:1600]},
                ensure_ascii=False,
                separators=(",", ":"),
            ),
            expect_json=False,
            num_ctx=2048,
            num_predict=40,
            think=False,
            model_name="gemma4:12b",
        )
        value = str(raw or "").strip().upper()
    except Exception as error:
        print("[MELCHIOR NERV QUERY AUDIT WARNING]", repr(error))
    finally:
        try:
            tools.unload_model("gemma4:12b")
            print("[MELCHIOR NERV AUDIT MODEL RELEASED] gemma4:12b")
        except Exception as error:
            print("[MELCHIOR NERV AUDIT RELEASE WARNING]", repr(error))
    if value not in {"NERV_LEARNING", "NERV_CURIOSITY", "OTHER"}:
        value = "OTHER"
    print("[MELCHIOR NERV QUERY AUDIT]", value)
    return value


def _explicit_nerv_curiosity_query(user_message):
    """Require an explicit request before exposing Curiosity Journal.

    The model still owns semantic routing.  This deterministic boundary only
    prevents a surprising fact or ordinary reflective conversation from being
    mistaken for a request to inspect Bekki's private NERV journal.
    """
    text = " ".join(str(user_message or "").casefold().split())
    if not text:
        return False
    chinese_patterns = (
        r"(?:你|bekki).{0,12}(?:最近|今天|现在)?.{0,8}(?:在想什么|想些什么|好奇什么)",
        r"(?:最近|今天|现在).{0,10}(?:有什么)?好奇",
        r"(?:你的|bekki的).{0,8}好奇心",
        r"(?:你|bekki).{0,12}(?:问了|问过|询问).{0,8}chatgpt",
        r"(?:查看|看看|显示|打开).{0,8}(?:好奇心|curiosity).{0,8}(?:记录|日志|journal)?",
    )
    english_patterns = (
        r"\bwhat (?:are|were) you curious about\b",
        r"\bwhat (?:have you|were you) been (?:wondering|thinking)\b",
        r"\bwhat did (?:you|bekki) ask chatgpt\b",
        r"\b(?:show|open|view) (?:your |bekki'?s )?curiosity (?:journal|log)\b",
        r"\b(?:your|bekki'?s) recent curiosit(?:y|ies)\b",
    )
    return any(
        re.search(pattern, text, re.IGNORECASE)
        for pattern in chinese_patterns + english_patterns
    )


def _explicit_nerv_learning_query(user_message):
    """Require an explicit verified-skill inventory request.

    NERV_LEARNING is not general factual learning. It exposes Bekki's local
    verified-operation inventory, so a surprising fact, public person, or
    ordinary statement must never open it implicitly.
    """
    text = " ".join(str(user_message or "").casefold().split())
    if not text:
        return False
    chinese_patterns = (
        r"(?:你|bekki).{0,12}(?:学会了|学到了|已经会了).{0,12}(?:什么|哪些)(?:操作|技能|方法)?",
        r"(?:你|bekki).{0,12}(?:有哪些|有什么).{0,10}(?:已学习|学过|已验证|验证过).{0,6}(?:操作|技能)",
        r"(?:查看|看看|显示|列出|打开).{0,10}(?:已学习|学过|已验证|验证过).{0,8}(?:操作|技能)(?:列表|清单|记录)?",
        r"(?:已学习|已验证|验证过).{0,8}(?:操作|技能)(?:有|是).{0,6}(?:什么|哪些)",
    )
    english_patterns = (
        r"\bwhat (?:operations|skills) (?:have you|has bekki) learned\b",
        r"\bwhat (?:verified|learned) (?:operations|skills) do you have\b",
        r"\b(?:show|list|view) (?:your |bekki'?s )?(?:verified|learned) (?:operations|skills)\b",
    )
    return any(
        re.search(pattern, text, re.IGNORECASE)
        for pattern in chinese_patterns + english_patterns
    )


def _audit_command_store_action(user_message):
    """Reliably separate reminder deletion from verified-skill deletion."""
    value = ""
    try:
        raw = tools.run_ai_prompt(
            "prompts/melchior_command_store_scope.txt",
            json.dumps(
                {"current_user_message": str(user_message or "")[:1600]},
                ensure_ascii=False,
                separators=(",", ":"),
            ),
            expect_json=False,
            num_ctx=2048,
            num_predict=30,
            think=False,
            model_name="gemma4:12b",
        )
        value = str(raw or "").strip().upper()
    except Exception as error:
        print("[MELCHIOR COMMAND STORE AUDIT WARNING]", repr(error))
    finally:
        try:
            tools.unload_model("gemma4:12b")
            print("[MELCHIOR COMMAND STORE MODEL RELEASED] gemma4:12b")
        except Exception as error:
            print("[MELCHIOR COMMAND STORE RELEASE WARNING]", repr(error))
    if value not in {"TASK_ACTION", "NERV_SKILL_ACTION"}:
        value = "TASK_ACTION"
    print("[MELCHIOR COMMAND STORE AUDIT]", value)
    return value


MAGI_LANE_MODES = {
    "SEARCH": {
        "NEWS_FEED", "DISCUSSION_FEED", "FACT_LOOKUP", "CLAIM_CHECK",
        "SOCIAL_RESEARCH", "MEDIA_WATCH",
        "SHOPPING_RESEARCH", "RECOMMENDATION_RESEARCH",
    },
    "LOCAL": {"LOCAL_ANSWER"},
    "COMMAND": {
        "TASK_ACTION", "NERV_SKILL_ACTION", "EXTERNAL_AI_ACTION",
        "DEVICE_ACTION",
    },
}


def _valid_magi_route(magi_route):
    if not isinstance(magi_route, dict):
        return None
    lane = str(magi_route.get("lane") or "").upper().strip()
    if lane not in MAGI_LANE_MODES:
        return None
    try:
        confidence = float(magi_route.get("confidence"))
    except (TypeError, ValueError):
        return None
    if not 0 <= confidence <= 1:
        return None
    return lane, confidence


def _plan_matches_magi(plan, magi_route):
    route = _valid_magi_route(magi_route)
    if route is None:
        return magi_route is None
    lane, _confidence = route
    return str(plan.get("response_mode") or "").upper().strip() in MAGI_LANE_MODES[lane]


def _annotate_magi(plan, magi_route):
    route = _valid_magi_route(magi_route)
    if route is None:
        if magi_route is not None:
            raise RuntimeError("MAGI supplied an invalid route contract.")
        return plan
    lane, confidence = route
    plan["magi_lane"] = lane
    plan["magi_confidence"] = confidence
    return plan


def _authoritative_social_plan(magi_route):
    """Use only MAGI AI's closed social-search judgment."""
    route = _valid_magi_route(magi_route)
    if route is None or route[0] != "SEARCH":
        return None
    if str(
        magi_route.get("social_scope") or ""
    ).upper().strip() != "SOCIAL_RESEARCH":
        return None
    raw_platforms = magi_route.get("social_platforms")
    if not isinstance(raw_platforms, list):
        raise RuntimeError("MAGI supplied an invalid social platform contract.")
    platforms = []
    for platform in raw_platforms:
        value = str(platform or "").lower().strip()
        if value not in VALID_SOCIAL_PLATFORMS:
            raise RuntimeError(
                "MAGI supplied an unsupported social platform."
            )
        if value not in platforms:
            platforms.append(value)
    if not platforms:
        raise RuntimeError("MAGI selected social research without a platform.")
    return _normalize_plan(
        {
            "response_mode": "SOCIAL_RESEARCH",
            "risk": "low",
            "complexity": "medium",
            "reasoning_profile": "analytical",
            "social_platforms": platforms,
            "skill_route": "none",
            "device_scope": None,
            "interaction_mode": "TASK",
            "context_profile": "MINIMAL",
            "reason": (
                "Reliable MAGI selected explicit named social-platform "
                "research."
            ),
        }
    )


def _finish_authoritative_social_plan(magi_route):
    plan = _authoritative_social_plan(magi_route)
    if plan is None:
        return None
    plan = _annotate_magi(plan, magi_route)
    print(
        "[MELCHIOR SOCIAL ROUTE]",
        json.dumps(plan.get("social_platforms", []), ensure_ascii=False),
    )
    print("[MELCHIOR PLAN]", json.dumps(plan, ensure_ascii=False))
    return plan


def _authoritative_discussion_plan(magi_route):
    """Honor MAGI's closed cross-site discussion-summary judgment."""

    route = _valid_magi_route(magi_route)
    if route is None or route[0] != "SEARCH":
        return None
    if str(
        magi_route.get("search_scope") or ""
    ).upper().strip() != "DISCUSSION_FEED":
        return None
    if str(magi_route.get("social_scope") or "OTHER").upper().strip() != "OTHER":
        raise RuntimeError(
            "MAGI supplied a contradictory DISCUSSION_FEED social contract."
        )
    if magi_route.get("social_platforms"):
        raise RuntimeError(
            "DISCUSSION_FEED cannot carry platform-native social platforms."
        )
    return _normalize_plan(
        {
            "response_mode": "DISCUSSION_FEED",
            "risk": "low",
            "complexity": "medium",
            "reasoning_profile": "analytical",
            "social_platforms": [],
            "claim_to_verify": None,
            "skill_route": "none",
            "device_scope": None,
            "interaction_mode": "TASK",
            "context_profile": "MINIMAL",
            "reason": (
                "Reliable MAGI selected a cross-site discussion roundup that "
                "must preserve multiple attributed viewpoints."
            ),
        }
    )


def _finish_authoritative_discussion_plan(magi_route):
    plan = _authoritative_discussion_plan(magi_route)
    if plan is None:
        return None
    plan = _annotate_magi(plan, magi_route)
    print("[MELCHIOR DISCUSSION ROUTE] cross_site")
    print("[MELCHIOR PLAN]", json.dumps(plan, ensure_ascii=False))
    return plan


def _authoritative_media_watch_plan(magi_route):
    """Honor MAGI's closed watch-search outcome without guessing a website."""

    route = _valid_magi_route(magi_route)
    if route is None or route[0] != "SEARCH":
        return None
    if str(
        magi_route.get("search_scope") or ""
    ).upper().strip() != "MEDIA_WATCH":
        return None
    if str(magi_route.get("social_scope") or "OTHER").upper().strip() != "OTHER":
        raise RuntimeError("MEDIA_WATCH cannot carry a social-research scope.")
    if magi_route.get("social_platforms"):
        raise RuntimeError(
            "MEDIA_WATCH site conditions are extracted from the user request, "
            "not from social_platforms."
        )
    return _normalize_plan(
        {
            "response_mode": "MEDIA_WATCH",
            "risk": "low",
            "complexity": "medium",
            "reasoning_profile": "standard",
            "social_platforms": [],
            "claim_to_verify": None,
            "skill_route": "none",
            "device_scope": None,
            "interaction_mode": "TASK",
            "context_profile": "MINIMAL",
            "reason": (
                "Reliable MAGI selected a bounded media watch search. Literal "
                "website conditions remain owned by the downstream watch plan."
            ),
        }
    )


def _finish_authoritative_media_watch_plan(magi_route):
    plan = _authoritative_media_watch_plan(magi_route)
    if plan is None:
        return None
    plan = _annotate_magi(plan, magi_route)
    print("[MELCHIOR MEDIA WATCH ROUTE] bounded_watch_search")
    print("[MELCHIOR PLAN]", json.dumps(plan, ensure_ascii=False))
    return plan


def _authoritative_recommendation_plan(magi_route):
    """Honor reliable MAGI's closed recommendation type without compact drift."""

    route = _valid_magi_route(magi_route)
    if route is None or route[0] != "SEARCH":
        return None
    if str(
        magi_route.get("search_scope") or ""
    ).upper().strip() != "RECOMMENDATION_RESEARCH":
        return None
    domain = str(
        magi_route.get("recommendation_domain") or ""
    ).upper().strip()
    if domain not in {
        "PRODUCT", "RESTAURANT", "LOCAL_SERVICE", "HEALTHCARE_PROVIDER",
    }:
        raise RuntimeError(
            "MAGI selected recommendation research without a valid domain."
        )
    return _normalize_plan(
        {
            "response_mode": "RECOMMENDATION_RESEARCH",
            "risk": "medium",
            "complexity": "medium",
            "reasoning_profile": "analytical",
            "recommendation_domain": domain,
            "social_platforms": [],
            "skill_route": "none",
            "device_scope": None,
            "interaction_mode": "TASK",
            "context_profile": "MINIMAL",
            "reason": (
                "Reliable MAGI selected open-ended real-world recommendation "
                "research in the " + domain + " domain."
            ),
        }
    )


def _finish_authoritative_recommendation_plan(magi_route):
    plan = _authoritative_recommendation_plan(magi_route)
    if plan is None:
        return None
    plan = _annotate_magi(plan, magi_route)
    print(
        "[MELCHIOR RECOMMENDATION ROUTE]",
        plan.get("recommendation_domain"),
    )
    print("[MELCHIOR PLAN]", json.dumps(plan, ensure_ascii=False))
    return plan


def _authoritative_local_knowledge_plan(magi_route):
    """Honor MAGI's existing AI judgment that recalled Knowledge is complete."""
    route = _valid_magi_route(magi_route)
    if route is None or route[0] != "LOCAL":
        return None
    if str(
        magi_route.get("local_knowledge_sufficiency") or "NONE"
    ).upper().strip() != "SUFFICIENT":
        return None
    return _normalize_plan(
        {
            "response_mode": "LOCAL_ANSWER",
            "risk": "low",
            "complexity": "low",
            "reasoning_profile": "quick",
            "social_platforms": [],
            "recommendation_domain": None,
            "skill_route": "none",
            "device_scope": None,
            "interaction_mode": "TASK",
            "context_profile": "MEMORY",
            "knowledge_route_selected": True,
            "reason": (
                "Reliable MAGI judged the active recalled Knowledge complete "
                "for the exact current request."
            ),
        }
    )


def _finish_authoritative_local_knowledge_plan(magi_route):
    plan = _authoritative_local_knowledge_plan(magi_route)
    if plan is None:
        return None
    plan = _annotate_magi(plan, magi_route)
    print("[MELCHIOR KNOWLEDGE ROUTE] LOCAL_ANSWER")
    print("[MELCHIOR PLAN]", json.dumps(plan, ensure_ascii=False))
    return plan


def _router_schema_for_magi(magi_route):
    """Restrict audited replanning to the lane selected by AI MAGI."""
    schema = copy.deepcopy(_ROUTER_PLAN_SCHEMA)
    route = _valid_magi_route(magi_route)
    if route is not None:
        lane, _confidence = route
        schema["properties"]["response_mode"]["enum"] = sorted(
            MAGI_LANE_MODES[lane]
        )
    return schema


def _routing_reference_context(user_message, conversation_context, limit=1600):
    """Expose prior turns to routing only for an explicit unresolved reference."""
    message = " ".join(str(user_message or "").split()).casefold()
    if not message:
        return ""
    chinese_patterns = (
        r"(?:这个|那个|这些|那些|上面|前面|刚才|刚刚|之前说的|上一条)",
        r"(?:第一个|第二个|第三个|前一个|后一个|另一个)",
        r"^(?:那|然后|所以)?(?:呢|怎么办|为什么|真的吗|可以吗)[？?。.!！]?$",
        r"^(?:继续|接着|再来|还有呢|然后呢|那第二个呢)",
    )
    english_patterns = (
        r"\b(?:this|that|these|those|the previous|the above|the first|the second|the third)\b",
        r"^(?:continue|go on|what about|and then|why|really)\b",
    )
    needs_reference = any(
        re.search(pattern, message, re.IGNORECASE)
        for pattern in chinese_patterns + english_patterns
    )
    if not needs_reference:
        return ""
    return str(conversation_context or "")[-max(0, int(limit)):]


def _independent_router_schema():
    """Allow Melchior's first judgment to challenge MAGI across all modes."""
    return copy.deepcopy(_ROUTER_PLAN_SCHEMA)


def _compact_router_input(
    user_message,
    conversation_context,
    magi_route,
    state,
    memory_data,
    image_context="",
):
    return json.dumps(
        {
            "current_date": datetime.now().date().isoformat(),
            "runtime_localization_defaults": _runtime_profile_context(),
            "current_user_message": str(user_message or "")[:1600],
            "initial_magi_ai_route_for_independent_review": magi_route,
            "allowed_response_modes": sorted(VALID_MODES),
            "recent_conversation_for_reference_only": _routing_reference_context(
                user_message,
                conversation_context,
                1600,
            ),
            "conversation_state_available": bool(state),
            "long_term_memory_available": bool(
                memory.get_long_term_context(memory_data).strip()
            ),
            "active_document": bool(document.has_document()),
            "active_image": bool(vision.has_image()),
            "active_image_evidence_for_current_request": str(
                image_context or ""
            )[:3200],
        },
        ensure_ascii=False,
        separators=(",", ":"),
    )


def plan_request(
    user_message,
    conversation_context="",
    magi_route=None,
    image_context="",
):
    """Return a normalized V2 routing plan for one user message."""

    memory_data = memory.initialize_memory()
    state = context_manager.load_context()

    knowledge_plan = _finish_authoritative_local_knowledge_plan(magi_route)
    if knowledge_plan is not None:
        return knowledge_plan
    discussion_plan = _finish_authoritative_discussion_plan(magi_route)
    if discussion_plan is not None:
        return discussion_plan
    media_watch_plan = _finish_authoritative_media_watch_plan(magi_route)
    if media_watch_plan is not None:
        return media_watch_plan
    social_plan = _finish_authoritative_social_plan(magi_route)
    if social_plan is not None:
        return social_plan
    recommendation_plan = _finish_authoritative_recommendation_plan(magi_route)
    if recommendation_plan is not None:
        return recommendation_plan

    input_text = _compact_router_input(
        user_message,
        conversation_context,
        magi_route,
        state,
        memory_data,
        image_context=image_context,
    )
    # Melchior must be able to disagree with the first MAGI judgment.  Lane
    # restriction is applied only after the reliable 12B MAGI audit below.
    router_schema = _independent_router_schema()

    small_model_unloaded = False
    try:
        raw_plan = tools.run_ai_prompt(
            "prompts/melchior_router.txt",
            input_text,
            expect_json=True,
            num_ctx=4096,
            num_predict=1200,
            think=False,
            model_name="gemma4:e4b",
            json_schema=router_schema,
        )
    except Exception as error:
        # Routine routing belongs on the small model.  If that runner fails,
        # unload the model that actually failed before one bounded 12B retry.
        print("[MELCHIOR ROUTER MODEL ERROR]", repr(error))
        raw_plan = None
        try:
            tools.unload_model("gemma4:e4b")
            small_model_unloaded = True
        except Exception as unload_error:
            print(
                "[MELCHIOR ROUTER RECOVERY UNLOAD SKIPPED]",
                repr(unload_error),
            )

    raw_plan = _repair_raw_plan_format_aliases(raw_plan)

    # A local model can still occasionally truncate structured output.  Ask
    # Melchior to make the routing judgment again; Python only detects the
    # format failure and never substitutes a semantic route here.
    if not _raw_plan_has_valid_mode(raw_plan):
        if not small_model_unloaded:
            try:
                tools.unload_model("gemma4:e4b")
                small_model_unloaded = True
            except Exception as unload_error:
                print(
                    "[MELCHIOR ROUTER RECOVERY UNLOAD SKIPPED]",
                    repr(unload_error),
                )
        recovery_input = json.dumps(
            {
                "current_date": datetime.now().date().isoformat(),
                "runtime_localization_defaults": _runtime_profile_context(),
                "current_conversation_state": state,
                "recent_conversation": _routing_reference_context(
                    user_message,
                    conversation_context,
                    5000,
                ),
                "current_user_message": user_message,
                "initial_magi_ai_route_for_independent_review": magi_route,
                "allowed_response_modes": sorted(VALID_MODES),
                "active_image_evidence_for_current_request": str(
                    image_context or ""
                )[:3200],
            },
            ensure_ascii=False,
            indent=2,
        )
        try:
            raw_plan = tools.run_ai_prompt(
                "prompts/melchior_router_recover.txt",
                recovery_input,
                expect_json=True,
                num_ctx=4096,
                num_predict=1800,
                think=False,
                model_name="gemma4:12b",
                json_schema=router_schema,
            )
            raw_plan = _repair_raw_plan_format_aliases(raw_plan)
        except Exception as error:
            print("[MELCHIOR ROUTER RECOVERY ERROR]", repr(error))
            raise RuntimeError(
                "Melchior routing model was unavailable after one recovery retry."
            ) from error

    if not _raw_plan_has_valid_mode(raw_plan):
        raise RuntimeError(
            "Melchior could not produce a valid routing mode after retry."
        )

    nerv_audit_needed = _raw_plan_requests_nerv_audit(raw_plan)
    command_store_audit_needed = (
        str(raw_plan.get("response_mode") or "").upper().strip()
        == "TASK_ACTION"
        and str(raw_plan.get("context_profile") or "").upper().strip()
        == "NERV_LEARNING"
    )
    plan = _normalize_plan(raw_plan)
    plan = _reconcile_platformless_social_plan(
        plan,
        magi_route,
        user_message,
    )
    crossed_lane_replanned = False
    if not _plan_matches_magi(plan, magi_route):
        crossed_lane_replanned = True
        print(
            "[MELCHIOR CROSSED MAGI LANE]",
            str(plan.get("response_mode")),
            "lane=" + str((magi_route or {}).get("lane")),
        )
        # A disagreement can mean the detailed planner is wrong, but it can
        # also mean MAGI's first judgment was wrong. Return the request to the
        # reliable 12B MAGI auditor instead of blindly forcing the old lane.
        magi_route = magi.audit_route(
            user_message,
            previous_route=magi_route,
            downstream_mode=plan.get("response_mode"),
            downstream_reason=plan.get("reason", ""),
            recent_context=_routing_reference_context(
                user_message,
                conversation_context,
                1600,
            ),
            image_context=image_context,
        )
        discussion_plan = _finish_authoritative_discussion_plan(magi_route)
        if discussion_plan is not None:
            return discussion_plan
        media_watch_plan = _finish_authoritative_media_watch_plan(magi_route)
        if media_watch_plan is not None:
            return media_watch_plan
        social_plan = _finish_authoritative_social_plan(magi_route)
        if social_plan is not None:
            return social_plan
        recommendation_plan = _finish_authoritative_recommendation_plan(
            magi_route
        )
        if recommendation_plan is not None:
            return recommendation_plan
        router_schema = _router_schema_for_magi(magi_route)
        lane_recovery_input = json.dumps(
            {
                "audited_authoritative_magi_ai_route": magi_route,
                "current_date": datetime.now().date().isoformat(),
                "current_user_message": user_message,
                "recent_conversation_for_reference_only": _routing_reference_context(
                    user_message,
                    conversation_context,
                    1600,
                ),
                "previous_cross_lane_mode": plan.get("response_mode"),
                "active_image_evidence_for_current_request": str(
                    image_context or ""
                )[:3200],
            },
            ensure_ascii=False,
            separators=(",", ":"),
        )
        try:
            lane_plan = tools.run_ai_prompt(
                "prompts/melchior_lane_recover.txt",
                lane_recovery_input,
                expect_json=True,
                num_ctx=3072,
                num_predict=900,
                think=False,
                model_name="gemma4:e4b",
                json_schema=router_schema,
            )
            lane_plan = _repair_raw_plan_format_aliases(lane_plan)
        except Exception as error:
            raise RuntimeError(
                "Melchior disagreed with MAGI and audited AI replanning failed."
            ) from error
        if not _raw_plan_has_valid_mode(lane_plan):
            raise RuntimeError(
                "Melchior AI returned an invalid audited-lane route."
            )
        command_store_audit_needed = command_store_audit_needed or (
            str(lane_plan.get("response_mode") or "").upper().strip()
            == "TASK_ACTION"
            and str(lane_plan.get("context_profile") or "").upper().strip()
            == "NERV_LEARNING"
        )
        plan = _normalize_plan(lane_plan)
        plan = _reconcile_platformless_social_plan(
            plan,
            magi_route,
            user_message,
        )
        if not _plan_matches_magi(plan, magi_route):
            raise RuntimeError(
                "Melchior AI crossed the audited MAGI lane; request stopped safely."
            )
    if (
        str(plan.get("response_mode") or "").upper().strip() == "TASK_ACTION"
        and command_store_audit_needed
        and _valid_magi_route(magi_route)
        and _valid_magi_route(magi_route)[0] == "COMMAND"
    ):
        command_mode = _audit_command_store_action(user_message)
        if command_mode == "NERV_SKILL_ACTION":
            plan = _normalize_plan(
                {
                    "response_mode": "NERV_SKILL_ACTION",
                    "risk": "low",
                    "complexity": "low",
                    "reasoning_profile": "standard",
                    "skill_route": "none",
                    "device_scope": None,
                    "interaction_mode": "TASK",
                    "context_profile": "MINIMAL",
                    "reason": (
                        "Reliable focused AI selected verified-skill lifecycle "
                        "management instead of the reminder store."
                    ),
                }
            )
    plan = _annotate_magi(plan, magi_route)
    # A syntactically explicit open/launch command is an execution boundary,
    # not an open-ended semantic routing choice.  The model may describe it as
    # casual conversation, but it must never turn a requested local action into
    # a fabricated LOCAL_ANSWER confirmation.
    if magi_route is None and (
        _builtin_device_scope(user_message)
        or _is_explicit_steam_game_launch(user_message)
        or _is_direct_application_launch(user_message)
    ):
        plan.update(
            {
                "response_mode": "DEVICE_ACTION",
                "needs_search": False,
                "research_depth": "none",
                "source_policy": "local_context",
                "risk": "low",
                "complexity": "low",
                "reasoning_profile": "quick",
                "research_profile": "local_context",
                "skill_route": "none",
                "interaction_mode": "TASK",
                "context_profile": "MINIMAL",
                "needs_balthasar": False,
            }
        )
    if magi_route is None and _is_steam_library_list_request(user_message):
        plan.update(
            {
                "response_mode": "DEVICE_ACTION",
                "needs_search": False,
                "research_depth": "none",
                "source_policy": "local_context",
                "risk": "low",
                "complexity": "low",
                "reasoning_profile": "quick",
                "research_profile": "local_context",
                "skill_route": "none",
                "interaction_mode": "TASK",
                "context_profile": "MINIMAL",
                "needs_balthasar": False,
                "steam_library_list_selected": True,
                "reason": (
                    "The user requested a read-only list of locally installed "
                    "Steam games."
                ),
            }
        )
    if plan["response_mode"] == "DEVICE_ACTION":
        if plan.get("steam_library_list_selected"):
            content_scope = "OTHER"
            print("[MELCHIOR CONTENT GATE] STEAM_LIBRARY_LIST")
        elif _is_explicit_steam_game_launch(user_message):
            plan["skill_route"] = "none"
            plan["steam_game_launch_selected"] = True
            content_scope = "OTHER"
            plan["reason"] = (
                "The user requested one locally installed Steam game launch."
            )
            print("[MELCHIOR CONTENT GATE] STEAM_GAME_LAUNCH")
        elif _is_direct_application_launch(user_message):
            plan["skill_route"] = "none"
            content_scope = "OTHER"
            plan["reason"] = (
                "The user requested a bounded installed-application launch."
            )
            print("[MELCHIOR CONTENT GATE] SIMPLE_APP_LAUNCH")
        else:
            content_scope = _classify_content_device_scope(
                user_message,
                conversation_context,
                plan.get("skill_route", "none"),
                plan.get("device_scope"),
            )
        if content_scope == "CONTENT_DEVICE_ACTION":
            plan["risk"] = "medium"
            plan["complexity"] = "high"
            plan["reasoning_profile"] = "analytical"
            plan["content_workflow_selected"] = True
            plan["skill_route"] = "lookup"
            plan["device_scope"] = "OTHER"
            plan["reason"] = (
                "Focused AI selected a skill-eligible web-to-local content workflow."
            )
            print("[MELCHIOR CONTENT GATE] CONTENT_DEVICE_ACTION")
        elif content_scope == "RECYCLE_BIN_ACTION":
            plan["risk"] = "low"
            plan["complexity"] = "low"
            plan["reasoning_profile"] = "quick"
            plan["recycle_workflow_selected"] = True
            plan["skill_route"] = "none"
            plan["reason"] = (
                "Focused AI selected the bounded Windows Recycle Bin workflow."
            )
            print("[MELCHIOR CONTENT GATE] RECYCLE_BIN_ACTION")
        elif content_scope == "":
            raise RuntimeError(
                "Melchior content-action gate returned invalid output twice."
            )
    nerv_context_audit = "OTHER"
    if (
        plan.get("response_mode") == "LOCAL_ANSWER"
        and plan.get("context_profile") not in {"NERV_LEARNING", "NERV_CURIOSITY"}
        and (nerv_audit_needed or crossed_lane_replanned)
    ):
        nerv_context_audit = _audit_nerv_learning_query(user_message)
    if nerv_context_audit in {"NERV_LEARNING", "NERV_CURIOSITY"}:
        plan["context_profile"] = nerv_context_audit
        plan["interaction_mode"] = "TASK"
        plan["needs_balthasar"] = False
    if (
        plan.get("context_profile") == "NERV_CURIOSITY"
        and not _explicit_nerv_curiosity_query(user_message)
    ):
        plan["context_profile"] = "MINIMAL"
        plan["interaction_mode"] = "TASK"
        plan["needs_balthasar"] = False
        print("[MELCHIOR NERV QUERY GUARD] NERV_CURIOSITY -> OTHER")
    if (
        plan.get("context_profile") == "NERV_LEARNING"
        and not _explicit_nerv_learning_query(user_message)
    ):
        plan["context_profile"] = "MINIMAL"
        plan["interaction_mode"] = "TASK"
        plan["needs_balthasar"] = False
        print("[MELCHIOR NERV QUERY GUARD] NERV_LEARNING -> OTHER")
    print("[MELCHIOR PLAN]", json.dumps(plan, ensure_ascii=False))
    return plan
