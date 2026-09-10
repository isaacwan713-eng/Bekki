"""Casper-managed background browser for public web research."""

import os
import base64
import hashlib
import time
import json
import re
import managed_browser
import secrets
from datetime import datetime
from functools import lru_cache
from pathlib import Path
from urllib.parse import (
    parse_qs,
    parse_qsl,
    quote,
    quote_plus,
    unquote,
    urljoin,
    urlparse,
)


CDP_PORT = managed_browser.CDP_PORT
CDP_URL = managed_browser.CDP_URL
MAX_PAGE_TEXT = 15000
BILIBILI_OFFICIAL_PUBLISHER_VIDEO_DISCOVERY_VERSION = 1
TEMPORAL_EVIDENCE_GRACEFUL_FALLBACK_VERSION = 1

SEARCH_ENGINE_CATALOG = [
    {
        "id": "google", "label": "Google", "available": True,
        "market_scope": "global", "audience_country_codes": [],
    },
    {
        "id": "bing", "label": "Bing", "available": True,
        "market_scope": "global", "audience_country_codes": [],
    },
]
SUPPORTED_SEARCH_ENGINES = frozenset(
    item["id"] for item in SEARCH_ENGINE_CATALOG
)
SEARCH_ENGINE_BY_ID = {
    item["id"]: item for item in SEARCH_ENGINE_CATALOG
}


@lru_cache(maxsize=1)
def _load_bekki_light_persona():
    """Load final-writing style without coupling research tests to tools.py."""
    path = Path(__file__).resolve().parents[1] / "prompts" / (
        "bekki_persona_light.txt"
    )
    try:
        return path.read_text(encoding="utf-8")
    except OSError:
        return ""


def _merchant_has_known_detail_contract(domain):
    value = str(domain or "").casefold().strip().removeprefix("www.")
    return value.startswith("amazon.") or value in {
        "walmart.com", "target.com", "nordstrom.com", "buybuybaby.com",
        "ebay.com", "taobao.com", "tmall.com", "jd.com",
    }


def _merchant_product_url(domain, url):
    """Structural URL contract for merchants whose detail URLs are known."""
    domain = str(domain).lower().strip().removeprefix("www.")
    try:
        parsed = urlparse(str(url))
    except ValueError:
        return False
    host = parsed.netloc.lower().removeprefix("www.")
    path = parsed.path
    if not host or not (host == domain or host.endswith("." + domain)):
        return False
    if host.startswith(("help.", "support.", "blog.", "community.")):
        return False
    if domain.startswith("amazon.") or host.startswith("amazon."):
        return bool(re.search(r"/(?:dp|gp/product)/[A-Z0-9]{10}(?:[/?]|$)", path, re.I))
    if domain == "walmart.com":
        return "/ip/" in path and bool(re.search(r"/\d+(?:[/?]|$)", path))
    if domain == "target.com":
        return "/p/" in path
    if domain == "nordstrom.com":
        return bool(re.search(r"/s/[^/]+/\d+(?:[/?]|$)", path, re.I))
    if domain == "buybuybaby.com":
        return "/store/product/" in path or "/product/" in path
    if domain == "ebay.com":
        return "/itm/" in path
    if domain == "taobao.com":
        return host == "item.taobao.com" and path.endswith("item.htm")
    if domain == "tmall.com":
        return host == "detail.tmall.com" and path.endswith("item.htm")
    if domain == "jd.com":
        return host == "item.jd.com" and bool(re.search(r"/\d+\.html$", path))
    # Unknown merchants are judged from rendered page evidence by AI.
    return True


def _merchant_discovery_query(domain, query):
    """Aim search engines at known concrete product-detail URL shapes."""
    domain = str(domain).lower().strip().removeprefix("www.")
    path_hints = {
        "amazon.com": "/dp/",
        "walmart.com": "/ip/",
        "target.com": "/p/",
        "nordstrom.com": "/s/",
        "buybuybaby.com": "/store/product/",
        "ebay.com": "/itm/",
    }
    site_target = domain + path_hints.get(domain, "")
    return ("site:" + site_target + " " + str(query)).strip()[:300]


def _product_json_ld(raw_scripts):
    """Return compact Product JSON-LD and its first HTTPS image when present."""
    products = []

    def visit(value):
        if isinstance(value, list):
            for item in value:
                visit(item)
            return
        if not isinstance(value, dict):
            return
        value_type = value.get("@type")
        types = value_type if isinstance(value_type, list) else [value_type]
        if any(str(item).lower() == "product" for item in types):
            products.append(value)
        graph = value.get("@graph")
        if graph is not None:
            visit(graph)

    for raw in raw_scripts:
        try:
            visit(json.loads(raw))
        except (TypeError, ValueError, json.JSONDecodeError):
            continue
    if not products:
        return "", ""
    product = products[0]
    image = product.get("image", "")
    if isinstance(image, list):
        image = next((item for item in image if isinstance(item, str)), "")
    elif isinstance(image, dict):
        image = image.get("url") or image.get("contentUrl") or ""
    image = str(image).strip()
    if not image.startswith("https://"):
        image = ""
    return json.dumps(product, ensure_ascii=False)[:12000], image[:2048]


def _structured_product_identity(raw_value):
    """Return the primary schema.org Product name and brand, if present."""
    try:
        value = json.loads(str(raw_value or ""))
    except (TypeError, ValueError, json.JSONDecodeError):
        return "", ""
    if not isinstance(value, dict):
        return "", ""
    name = str(value.get("name") or "").strip()[:240]
    brand_value = value.get("brand")
    if isinstance(brand_value, dict):
        brand = str(brand_value.get("name") or "").strip()
    elif isinstance(brand_value, list):
        brand = next(
            (
                str(item.get("name") or "").strip()
                for item in brand_value
                if isinstance(item, dict) and str(item.get("name") or "").strip()
            ),
            "",
        )
    else:
        brand = str(brand_value or "").strip()
    return name, brand[:100]


def _usable_product_image(url):
    """Reject empty, non-HTTPS, and obvious merchant/logo artwork."""
    value = str(url or "").strip()
    if not value.startswith("https://"):
        return ""
    lowered = value.lower()
    blocked = ("logo", "sprite", "favicon", "placeholder", "transparent")
    if any(token in lowered for token in blocked):
        return ""
    return value[:2048]


def _status(callback, text):
    if callback:
        callback(text)


def _app_data_dir():
    return managed_browser.app_data_dir()


def _profile_dir():
    return managed_browser.profile_dir()


def _edge_executable():
    return managed_browser.edge_executable()


def _cdp_ready():
    return managed_browser.cdp_is_ready()


def ensure_browser():
    """Attach every Casper web task to Bekki's one normal Edge."""

    managed_browser.ensure_browser()


def _stop_casper_browser():
    """Compatibility no-op: individual tasks must not stop the shared browser."""

    return None


def open_human_handoff(url):
    """Show a verification page without replacing the shared browser."""

    return managed_browser.open_human_handoff(url)


def _protected_event(text):
    lowered = str(text).lower()
    captcha_signals = (
        "captcha",
        "verify you are human",
        "verify that you are human",
        "unusual traffic",
        "enter the characters you see",
        "robot check",
    )
    if any(signal in lowered for signal in captcha_signals):
        return "captcha"
    access_block_signals = (
        "access denied",
        "unusual activity",
        "security notice",
        "request blocked",
    )
    if any(signal in lowered for signal in access_block_signals):
        return "access_block"
    return None


def _extract_google_ai_summary(body_text, limit=3000):
    """Extract a visible Google AI overview without treating it as proof."""
    lines = [
        re.sub(r"\s+", " ", line).strip()
        for line in str(body_text or "").splitlines()
        if re.sub(r"\s+", " ", line).strip()
    ]
    markers = {"ai overview", "ai 概览", "ai 摘要", "ai overview is ready"}
    start = None
    for index, line in enumerate(lines):
        if line.casefold() in markers or line.casefold().startswith("ai overview"):
            start = index + 1
            break
    if start is None:
        return ""
    stop_markers = {
        "sources", "web results", "people also ask", "more results",
        "dive deeper", "相关问题", "网页结果", "更多结果", "来源",
    }
    selected = []
    for line in lines[start:]:
        if line.casefold() in stop_markers:
            break
        if line.casefold().startswith("generative ai is experimental"):
            continue
        selected.append(line)
        if len(" ".join(selected)) >= limit:
            break
    return " ".join(selected).strip()[:limit]


def _clean_result(title, description, url):
    url = _unwrap_bing_url(url)
    url = _unwrap_google_url(url)
    parsed = urlparse(url)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        return None
    return {
        "title": str(title).strip()[:500],
        "description": str(description).strip()[:1200],
        "url": url[:2048],
        "domain": parsed.netloc.lower().removeprefix("www."),
        "published": "",
        "discovery_type": "casper_browser",
    }


def _unwrap_bing_url(url):
    """Return the real target behind Bing's ``/ck/a`` result wrapper."""
    raw = str(url).strip()
    try:
        parsed = urlparse(raw)
    except ValueError:
        return raw

    if parsed.netloc.lower().removeprefix("www.") != "bing.com":
        return raw
    encoded = parse_qs(parsed.query).get("u", [""])[0]
    if not encoded:
        return raw

    encoded = unquote(encoded)
    # Bing commonly prefixes the URL-safe Base64 target with "a1".
    if encoded.startswith("a1"):
        encoded = encoded[2:]
    try:
        padding = "=" * (-len(encoded) % 4)
        decoded = base64.urlsafe_b64decode(encoded + padding).decode("utf-8")
        target = decoded.strip()
        if urlparse(target).scheme in {"http", "https"}:
            return target
    except (ValueError, UnicodeDecodeError):
        pass
    return raw


def _unwrap_google_url(url):
    """Return the target behind Google's ``/url?q=`` result wrapper."""
    raw = str(url).strip()
    try:
        parsed = urlparse(raw)
    except ValueError:
        return raw
    host = parsed.netloc.lower().removeprefix("www.")
    if host not in {"google.com", "googleusercontent.com"}:
        return raw
    target = parse_qs(parsed.query).get("q", [""])[0]
    target = unquote(target).strip()
    return target if urlparse(target).scheme in {"http", "https"} else raw


def _accepted_answer_text(answers):
    """Return only one non-empty answer that passed every fact check."""
    for item in answers or []:
        if not isinstance(item, dict) or item.get("accepted") is not True:
            continue
        answer = item.get("answer")
        if isinstance(answer, str) and answer.strip():
            return answer.strip()
    return ""


def _has_answer(answers):
    """Keep browser result validation inside Casper, not private V1 tools."""
    return bool(_accepted_answer_text(answers))


def _validate_candidate_answer(
    query,
    source,
    answer,
    user_request="",
    fact_scope=None,
):
    """Ask AI whether one extracted value actually answers the query."""
    if (
        isinstance(source, dict)
        and source.get("official_only") is True
        and source.get("official_identity_verified") is not True
    ):
        print(
            "[CASPER OFFICIAL SOURCE REJECTED]",
            "reason=deterministic_identity_proof_missing",
        )
        return {
            "accepted": False,
            "reason": "Deterministic official-account identity proof is missing.",
        }
    import tools

    validation_schema = {
        "type": "object",
        "properties": {
            "accepted": {
                "type": "boolean",
                "description": (
                    "Whether the literal query clearly communicates the "
                    "requested scope; this is not a guarantee about every "
                    "search result."
                ),
            },
            "directly_answers": {"type": "boolean"},
            "complete_for_request": {"type": "boolean"},
            "source_supported": {"type": "boolean"},
            "no_unsupported_additions": {"type": "boolean"},
            "reason": {"type": "string"},
        },
        "required": [
            "accepted",
            "directly_answers",
            "complete_for_request",
            "source_supported",
            "no_unsupported_additions",
            "reason",
        ],
        "additionalProperties": False,
    }

    packet = {
        "original_user_request": str(user_request or query),
        "query": query,
        "fact_intent_scope": fact_scope,
        "candidate_answer": answer,
        "source": {
            "title": source.get("title", ""),
            "description": source.get("description", ""),
            "domain": source.get("domain", ""),
            "url": source.get("url", ""),
            "page_content": str(source.get("page_content", ""))[:5000],
        },
    }

    result = tools.run_ai_prompt(
        "prompts/fact_candidate_validate.txt",
        json.dumps(packet, ensure_ascii=False, indent=2),
        expect_json=True,
        num_ctx=8192,
        num_predict=220,
        think=False,
        model_name="gemma4:12b",
        json_schema=validation_schema,
    )
    checks = (
        "directly_answers",
        "complete_for_request",
        "source_supported",
        "no_unsupported_additions",
    )
    if (
        not isinstance(result, dict)
        or not isinstance(result.get("accepted"), bool)
        or any(not isinstance(result.get(name), bool) for name in checks)
    ):
        return None
    accepted = result["accepted"] is True and all(
        result[name] is True for name in checks
    )
    if accepted:
        audit_packet = dict(packet)
        audit_packet["first_validator_verdict"] = result
        audit = tools.run_ai_prompt(
            "prompts/fact_candidate_validate_audit.txt",
            json.dumps(audit_packet, ensure_ascii=False, indent=2),
            expect_json=True,
            num_ctx=8192,
            num_predict=300,
            think=False,
            model_name="gemma4:12b",
            json_schema=validation_schema,
        )
        if (
            not isinstance(audit, dict)
            or not isinstance(audit.get("accepted"), bool)
            or any(not isinstance(audit.get(name), bool) for name in checks)
        ):
            return None
        accepted = audit["accepted"] is True and all(
            audit[name] is True for name in checks
        )
        result = audit
    return {
        "accepted": accepted,
        "reason": str(result.get("reason", ""))[:400],
    }


def _plan_fact_intent_scope(user_request, query):
    """Let AI bind the original request to one temporal intent contract."""
    import tools

    scope_schema = {
        "type": "object",
        "properties": {
            "scope_type": {
                "type": "string",
                "enum": [
                    "CURRENT_ACTIVE_STATE",
                    "LATEST_COMPLETED_PERIOD",
                    "EXPLICIT_PERIOD",
                ],
            },
            "requested_period": {"type": "string", "minLength": 1},
            "allow_previous_period": {"type": "boolean"},
            "reason": {"type": "string", "minLength": 1},
        },
        "required": [
            "scope_type",
            "requested_period",
            "allow_previous_period",
            "reason",
        ],
        "additionalProperties": False,
    }

    packet = {
        "current_date": datetime.now().date().isoformat(),
        "original_user_message": str(user_request),
        "retrieval_query": str(query),
    }

    def run(prompt, previous=None):
        value = dict(packet)
        if previous is not None:
            value["previous_incomplete_scope"] = previous
        return tools.run_ai_prompt(
            prompt,
            json.dumps(value, ensure_ascii=False, indent=2),
            expect_json=True,
            num_ctx=4096,
            num_predict=260,
            think=False,
            model_name="gemma4:12b",
            json_schema=scope_schema,
        )

    def complete_current_period(value):
        if not isinstance(value, dict):
            return value
        if (
            str(value.get("scope_type") or "").upper().strip()
            == "CURRENT_ACTIVE_STATE"
            and not str(value.get("requested_period") or "").strip()
        ):
            value = dict(value)
            value["requested_period"] = (
                "current active state as of "
                + packet["current_date"]
            )
        return value

    def valid(value):
        return (
            isinstance(value, dict)
            and str(value.get("scope_type", "")).upper().strip()
            in {
                "CURRENT_ACTIVE_STATE",
                "LATEST_COMPLETED_PERIOD",
                "EXPLICIT_PERIOD",
            }
            and isinstance(value.get("requested_period"), str)
            and bool(value["requested_period"].strip())
            and isinstance(value.get("allow_previous_period"), bool)
            and isinstance(value.get("reason"), str)
            and bool(value["reason"].strip())
        )

    result = complete_current_period(run("prompts/fact_intent_scope.txt"))
    if not valid(result):
        result = complete_current_period(
            run("prompts/fact_intent_scope_retry.txt", result)
        )
    if not valid(result):
        return None
    normalized = {
        "scope_type": str(result["scope_type"]).upper().strip(),
        "requested_period": result["requested_period"].strip()[:240],
        "allow_previous_period": result["allow_previous_period"],
        "reason": result["reason"].strip()[:400],
    }
    if (
        normalized["scope_type"] == "CURRENT_ACTIVE_STATE"
        and normalized["allow_previous_period"] is not False
    ):
        normalized["allow_previous_period"] = False
        normalized["reason"] = (
            normalized["reason"]
            + " Current-state lookup cannot substitute a previous period."
        )[:400]
        print("[CASPER FACT CURRENT SCOPE LOCKED] allow_previous_period=false")
    period_key = normalized["requested_period"].casefold()
    if (
        normalized["scope_type"] == "CURRENT_ACTIVE_STATE"
        and any(
            marker in period_key
            for marker in ("yesterday", "last night", "昨天", "昨晚")
        )
    ):
        normalized["scope_type"] = "EXPLICIT_PERIOD"
        normalized["allow_previous_period"] = False
        normalized["reason"] = (
            "The AI named a completed relative period, so it cannot be a "
            "current active state."
        )
        print(
            "[CASPER FACT SCOPE RECONCILED]",
            normalized["requested_period"],
        )
    return normalized


def _plan_fact_entity_scope(user_request, query):
    """Let AI bind the original request to one semantic entity contract."""
    import tools

    scope_schema = {
        "type": "object",
        "properties": {
            "target_entity": {"type": "string", "minLength": 1},
            "requested_relation": {"type": "string", "minLength": 1},
            "required_facets": {
                "type": "array",
                "items": {"type": "string", "minLength": 1},
                "minItems": 1,
            },
            "included_scope": {"type": "string", "minLength": 1},
            "excluded_adjacent_scopes": {
                "type": "array",
                "items": {"type": "string", "minLength": 1},
            },
            "source_language_boundaries": {
                "type": "array",
                "maxItems": 6,
                "items": {
                    "type": "object",
                    "properties": {
                        "source_expression": {
                            "type": "string",
                            "minLength": 1,
                        },
                        "established_equivalent": {
                            "anyOf": [
                                {"type": "string", "minLength": 1},
                                {"type": "null"},
                            ],
                            "description": (
                                "Null unless the user's own message gives "
                                "one exact equivalent."
                            ),
                        },
                        "meaning_status": {
                            "type": "string",
                            "enum": [
                                "USER_ESTABLISHED",
                                "OPEN_RESEARCH_TARGET",
                            ],
                            "description": (
                                "OPEN_RESEARCH_TARGET whenever the user's "
                                "question asks what the expression means or "
                                "how it differs; model background knowledge "
                                "does not establish an equivalence."
                            ),
                        },
                        "translation_policy": {
                            "type": "string",
                            "enum": [
                                "EXACT_EQUIVALENT_ALLOWED",
                                "PRESERVE_SOURCE_EXPRESSION",
                            ],
                            "description": (
                                "Preserve the source expression when its "
                                "meaning remains a research target or an "
                                "exact translation is uncertain."
                            ),
                        },
                        "boundary_reason": {
                            "type": "string",
                            "enum": [
                                "USER_PROVIDED_EXACT_EQUIVALENT",
                                "MEANING_OR_RELATION_IS_RESEARCH_TARGET",
                                "NO_SAFE_EXACT_EQUIVALENT",
                            ],
                        },
                        "excluded_conflations": {
                            "type": "array",
                            "maxItems": 8,
                            "items": {
                                "type": "string",
                                "minLength": 1,
                            },
                        },
                    },
                    "required": [
                        "source_expression",
                        "established_equivalent",
                        "meaning_status",
                        "translation_policy",
                        "boundary_reason",
                        "excluded_conflations",
                    ],
                    "additionalProperties": False,
                },
            },
            "reason": {"type": "string", "minLength": 1},
        },
        "required": [
            "target_entity",
            "requested_relation",
            "required_facets",
            "included_scope",
            "excluded_adjacent_scopes",
            "source_language_boundaries",
            "reason",
        ],
        "additionalProperties": False,
    }
    packet = {
        "original_user_message": str(user_request),
        "proposed_retrieval_query": str(query),
    }

    def run(prompt, previous=None):
        value = dict(packet)
        if previous is not None:
            value["previous_incomplete_scope"] = previous
        return tools.run_ai_prompt(
            prompt,
            json.dumps(value, ensure_ascii=False, indent=2),
            expect_json=True,
            num_ctx=4096,
            num_predict=520,
            think=False,
            model_name="gemma4:12b",
            json_schema=scope_schema,
        )

    def valid(value):
        return (
            isinstance(value, dict)
            and isinstance(value.get("target_entity"), str)
            and bool(value["target_entity"].strip())
            and isinstance(value.get("requested_relation"), str)
            and bool(value["requested_relation"].strip())
            and isinstance(value.get("required_facets"), list)
            and bool(value["required_facets"])
            and all(
                isinstance(item, str) and bool(item.strip())
                for item in value["required_facets"]
            )
            and isinstance(value.get("included_scope"), str)
            and bool(value["included_scope"].strip())
            and isinstance(value.get("excluded_adjacent_scopes"), list)
            and all(
                isinstance(item, str) and bool(item.strip())
                for item in value["excluded_adjacent_scopes"]
            )
            and isinstance(value.get("source_language_boundaries"), list)
            and all(
                isinstance(item, dict)
                and isinstance(item.get("source_expression"), str)
                and bool(item["source_expression"].strip())
                and item["source_expression"].strip() in str(user_request)
                and item.get("meaning_status") in {
                    "USER_ESTABLISHED",
                    "OPEN_RESEARCH_TARGET",
                }
                and item.get("translation_policy") in {
                    "EXACT_EQUIVALENT_ALLOWED",
                    "PRESERVE_SOURCE_EXPRESSION",
                }
                and not (
                    item.get("meaning_status") == "OPEN_RESEARCH_TARGET"
                    and (
                        item.get("translation_policy")
                        != "PRESERVE_SOURCE_EXPRESSION"
                        or item.get("established_equivalent") is not None
                        or item.get("boundary_reason")
                        == "USER_PROVIDED_EXACT_EQUIVALENT"
                    )
                )
                and not (
                    item.get("meaning_status") == "USER_ESTABLISHED"
                    and (
                        item.get("translation_policy")
                        != "EXACT_EQUIVALENT_ALLOWED"
                        or not isinstance(
                            item.get("established_equivalent"), str
                        )
                        or not item["established_equivalent"].strip()
                        or item.get("boundary_reason")
                        != "USER_PROVIDED_EXACT_EQUIVALENT"
                    )
                )
                and item.get("boundary_reason") in {
                    "USER_PROVIDED_EXACT_EQUIVALENT",
                    "MEANING_OR_RELATION_IS_RESEARCH_TARGET",
                    "NO_SAFE_EXACT_EQUIVALENT",
                }
                and isinstance(item.get("excluded_conflations"), list)
                and all(
                    isinstance(adjacent, str) and bool(adjacent.strip())
                    for adjacent in item["excluded_conflations"]
                )
                for item in value["source_language_boundaries"]
            )
            and isinstance(value.get("reason"), str)
            and bool(value["reason"].strip())
        )

    result = run("prompts/fact_entity_scope.txt")
    if not valid(result):
        result = run("prompts/fact_entity_scope_retry.txt", result)
    if not valid(result):
        return None
    return {
        "target_entity": result["target_entity"].strip()[:240],
        "requested_relation": result["requested_relation"].strip()[:300],
        "required_facets": [
            item.strip()[:240] for item in result["required_facets"][:8]
        ],
        "included_scope": result["included_scope"].strip()[:500],
        "excluded_adjacent_scopes": [
            item.strip()[:300]
            for item in result["excluded_adjacent_scopes"][:8]
        ],
        "source_language_boundaries": [
            {
                "source_expression": item["source_expression"].strip()[:120],
                "established_equivalent": (
                    item["established_equivalent"].strip()[:300]
                    if isinstance(item.get("established_equivalent"), str)
                    else None
                ),
                "meaning_status": item["meaning_status"],
                "translation_policy": item["translation_policy"],
                "boundary_reason": item["boundary_reason"],
                "excluded_conflations": [
                    adjacent.strip()[:200]
                    for adjacent in item["excluded_conflations"][:8]
                ],
            }
            for item in result["source_language_boundaries"][:8]
        ],
        "reason": result["reason"].strip()[:500],
    }


def _focused_query_context(
    current_query,
    query_set,
    original_focused_query=None,
):
    """Label one focused candidate and its siblings without judging meaning."""
    candidate = str(current_query or "").strip()[:500]
    original = str(original_focused_query or current_query or "").strip()[:500]
    values = [
        str(value).strip()[:500]
        for value in (query_set or [])[:2]
        if str(value).strip()
    ]
    original_index = next(
        (index for index, value in enumerate(values) if value == original),
        None,
    )
    siblings = [
        value
        for index, value in enumerate(values)
        if index != original_index
    ] if original_index is not None else values
    return {
        "focused_candidate_before_audit": original,
        "focused_candidate_under_review": candidate,
        "sibling_queries": siblings[:1],
        "effective_candidate_query_set": [candidate, *siblings[:1]],
    }


def _certify_fact_search_query(
    user_request,
    query,
    entity_scope,
    query_role="PRIMARY",
    query_set=None,
    gap_plan=None,
    original_focused_query=None,
):
    """Ask an independent AI if the literal query exposes the bound scope."""
    import tools

    role = str(query_role or "PRIMARY").upper().strip()
    focused_mode = role == "FOCUSED_FOLLOW_UP"
    certification_schema = {
        "type": "object",
        "properties": {
            "accepted": {"type": "boolean"},
            "literal_scope_paraphrase": {
                "type": "string",
                "minLength": 1,
            },
            "strongest_adjacent_interpretation": {
                "type": "string",
                "minLength": 1,
            },
            "adjacent_interpretation_plausible": {
                "type": "boolean",
                "description": (
                    "True only if the query itself could reasonably request "
                    "the adjacent scope; irrelevant results do not count."
                ),
            },
            "hierarchy_boundary_explicit": {
                "type": "boolean",
                "description": (
                    "True when literal positive identity, relationship, or "
                    "exclusion wording communicates the hierarchy boundary."
                ),
            },
            "exact_entity_scope": {"type": "boolean"},
            "translation_boundary_clear": {
                "type": "boolean",
                "description": (
                    "Judge taxonomy translation independently from entity "
                    "hierarchy concerns."
                ),
            },
            "source_language_boundaries_respected": {
                "type": "boolean",
                "description": (
                    "True only when every OPEN_RESEARCH_TARGET remains "
                    "verbatim and the query asserts no unestablished "
                    "equivalence for it."
                ),
            },
            "standalone_for_search_engine": {"type": "boolean"},
            "reason": {"type": "string", "minLength": 1},
        },
        "required": [
            "accepted",
            "literal_scope_paraphrase",
            "strongest_adjacent_interpretation",
            "adjacent_interpretation_plausible",
            "hierarchy_boundary_explicit",
            "exact_entity_scope",
            "translation_boundary_clear",
            "source_language_boundaries_respected",
            "standalone_for_search_engine",
            "reason",
        ],
        "additionalProperties": False,
    }
    if focused_mode:
        certification_schema["properties"].update({
            "focused_facet": {"type": "string", "minLength": 1},
            "focused_facet_preserved": {
                "type": "boolean",
                "description": (
                    "Whether the candidate keeps the same semantic facet; "
                    "exact wording and explicit negative exclusions are not "
                    "required when positive taxonomy is precise."
                ),
            },
            "query_set_collectively_covers_gaps": {
                "type": "boolean",
                "description": (
                    "Whether the effective candidate plus labeled siblings "
                    "cover the gap; do not require one query to cover all."
                ),
            },
        })
        certification_schema["required"].extend([
            "focused_facet",
            "focused_facet_preserved",
            "query_set_collectively_covers_gaps",
        ])
        prompt = "prompts/fact_query_scope_certify_focused.txt"
        positive_checks = (
            "hierarchy_boundary_explicit",
            "exact_entity_scope",
            "focused_facet_preserved",
            "query_set_collectively_covers_gaps",
            "translation_boundary_clear",
            "source_language_boundaries_respected",
            "standalone_for_search_engine",
        )
    else:
        certification_schema["properties"]["all_facets_preserved"] = {
            "type": "boolean"
        }
        certification_schema["required"].append("all_facets_preserved")
        prompt = "prompts/fact_query_scope_certify.txt"
        positive_checks = (
            "hierarchy_boundary_explicit",
            "exact_entity_scope",
            "all_facets_preserved",
            "translation_boundary_clear",
            "source_language_boundaries_respected",
            "standalone_for_search_engine",
        )
    packet = {
        "original_user_message": str(user_request),
        "entity_scope": entity_scope,
        "literal_candidate_search_query": str(query),
        "query_role": role,
        "candidate_query_set": [
            str(value)[:500]
            for value in (query_set or [])[:2]
            if str(value).strip()
        ],
        "evidence_gap_plan": (
            gap_plan if isinstance(gap_plan, dict) else None
        ),
    }
    if focused_mode:
        packet.update(
            _focused_query_context(
                query,
                query_set,
                original_focused_query=original_focused_query,
            )
        )
    result = tools.run_ai_prompt(
        prompt,
        json.dumps(packet, ensure_ascii=False, indent=2),
        expect_json=True,
        num_ctx=4096,
        num_predict=520,
        think=False,
        model_name="gemma4:12b",
        json_schema=certification_schema,
    )
    if (
        not isinstance(result, dict)
        or not isinstance(result.get("accepted"), bool)
        or not isinstance(result.get("literal_scope_paraphrase"), str)
        or not result["literal_scope_paraphrase"].strip()
        or not isinstance(
            result.get("strongest_adjacent_interpretation"),
            str,
        )
        or not result["strongest_adjacent_interpretation"].strip()
        or not isinstance(
            result.get("adjacent_interpretation_plausible"),
            bool,
        )
        or any(
            not isinstance(result.get(name), bool)
            for name in positive_checks
        )
        or (
            focused_mode
            and (
                not isinstance(result.get("focused_facet"), str)
                or not result["focused_facet"].strip()
            )
        )
        or not isinstance(result.get("reason"), str)
        or not result["reason"].strip()
    ):
        return None
    accepted = result["accepted"] is True and all(
        result[name] is True for name in positive_checks
    ) and result["adjacent_interpretation_plausible"] is False
    normalized = {
        "accepted": accepted,
        "literal_scope_paraphrase": result[
            "literal_scope_paraphrase"
        ].strip()[:500],
        "strongest_adjacent_interpretation": result[
            "strongest_adjacent_interpretation"
        ].strip()[:500],
        "adjacent_interpretation_plausible": result[
            "adjacent_interpretation_plausible"
        ],
        **{name: result[name] for name in positive_checks},
        "reason": result["reason"].strip()[:500],
    }
    if focused_mode:
        normalized["focused_facet"] = result["focused_facet"].strip()[:300]
        normalized["all_facets_preserved"] = (
            result["focused_facet_preserved"] is True
            and result["query_set_collectively_covers_gaps"] is True
        )
    return normalized


def _audit_fact_search_query(
    user_request,
    query,
    entity_scope,
    query_role="PRIMARY",
    query_set=None,
    gap_plan=None,
):
    """Let a separate AI approve or rewrite a query to the bound entity scope."""
    import tools

    role = str(query_role or "PRIMARY").upper().strip()
    focused_mode = role == "FOCUSED_FOLLOW_UP"
    audit_schema = {
        "type": "object",
        "properties": {
            "decision": {"type": "string", "enum": ["USE", "REWRITE"]},
            "proposed_query_scope_match": {"type": "boolean"},
            "approved_query_scope_match": {
                "type": "boolean",
                "description": (
                    "Whether the approved query communicates the exact "
                    "search intent, not whether results can be guaranteed."
                ),
            },
            "approved_search_query": {
                "type": "string",
                "minLength": 1,
                "description": (
                    "A literal standalone query with the intended entity and "
                    "any necessary adjacent-scope exclusion."
                ),
            },
            "source_language_boundaries_respected": {
                "type": "boolean",
                "description": (
                    "True only when the approved query preserves every open "
                    "source expression without asserting an unestablished "
                    "translation."
                ),
            },
            "reason": {"type": "string", "minLength": 1},
        },
        "required": [
            "decision",
            "proposed_query_scope_match",
            "approved_query_scope_match",
            "approved_search_query",
            "source_language_boundaries_respected",
            "reason",
        ],
        "additionalProperties": False,
    }
    if focused_mode:
        audit_schema["properties"].update({
            "focused_facet": {"type": "string", "minLength": 1},
            "proposed_focused_facet_preserved": {"type": "boolean"},
            "approved_focused_facet_preserved": {
                "type": "boolean",
                "description": (
                    "Whether the approved query preserves this query slot's "
                    "positive semantic taxonomy rather than a sibling facet."
                ),
            },
            "query_set_collectively_covers_gaps": {
                "type": "boolean",
                "description": (
                    "Judge collective coverage across the effective query "
                    "set, not full coverage by this candidate alone."
                ),
            },
        })
        audit_schema["required"].extend([
            "focused_facet",
            "proposed_focused_facet_preserved",
            "approved_focused_facet_preserved",
            "query_set_collectively_covers_gaps",
        ])
        audit_prompt = "prompts/fact_query_scope_audit_focused.txt"
        retry_prompt = "prompts/fact_query_scope_audit_focused_retry.txt"
    else:
        audit_prompt = "prompts/fact_query_scope_audit.txt"
        retry_prompt = "prompts/fact_query_scope_audit_retry.txt"
    packet = {
        "original_user_message": str(user_request),
        "entity_scope": entity_scope,
        "proposed_search_query": str(query),
        "query_role": role,
        "candidate_query_set": [
            str(value)[:500]
            for value in (query_set or [])[:2]
            if str(value).strip()
        ],
        "evidence_gap_plan": (
            gap_plan if isinstance(gap_plan, dict) else None
        ),
    }
    if focused_mode:
        packet.update(_focused_query_context(query, query_set))

    def run(prompt, previous=None, certification=None):
        value = dict(packet)
        if previous is not None:
            value["previous_incomplete_audit"] = previous
        if certification is not None:
            value["independent_certification_failure"] = certification
        return tools.run_ai_prompt(
            prompt,
            json.dumps(value, ensure_ascii=False, indent=2),
            expect_json=True,
            num_ctx=4096,
            num_predict=520,
            think=False,
            model_name="gemma4:12b",
            json_schema=audit_schema,
        )

    def valid(value):
        base_valid = (
            isinstance(value, dict)
            and str(value.get("decision", "")).upper().strip()
            in {"USE", "REWRITE"}
            and isinstance(value.get("proposed_query_scope_match"), bool)
            and value.get("approved_query_scope_match") is True
            and isinstance(value.get("approved_search_query"), str)
            and bool(value["approved_search_query"].strip())
            and value.get("source_language_boundaries_respected") is True
            and isinstance(value.get("reason"), str)
            and bool(value["reason"].strip())
        )
        if not base_valid or not focused_mode:
            return base_valid
        return (
            isinstance(value.get("focused_facet"), str)
            and bool(value["focused_facet"].strip())
            and isinstance(
                value.get("proposed_focused_facet_preserved"),
                bool,
            )
            and value.get("approved_focused_facet_preserved") is True
            and value.get("query_set_collectively_covers_gaps") is True
        )

    result = run(audit_prompt)
    if not valid(result):
        result = run(retry_prompt, result)
    if not valid(result):
        return None
    certification = _certify_fact_search_query(
        user_request,
        result["approved_search_query"],
        entity_scope,
        query_role=query_role,
        query_set=query_set,
        gap_plan=gap_plan,
        original_focused_query=query if focused_mode else None,
    )
    if (
        not isinstance(certification, dict)
        or certification.get("accepted") is not True
    ):
        result = run(
            retry_prompt,
            result,
            certification,
        )
        if not valid(result):
            return None
        certification = _certify_fact_search_query(
            user_request,
            result["approved_search_query"],
            entity_scope,
            query_role=query_role,
            query_set=query_set,
            gap_plan=gap_plan,
            original_focused_query=query if focused_mode else None,
        )
    if (
        not isinstance(certification, dict)
        or certification.get("accepted") is not True
    ):
        return None
    return {
        "decision": str(result["decision"]).upper().strip(),
        "proposed_query_scope_match": result["proposed_query_scope_match"],
        "approved_query_scope_match": True,
        "approved_search_query": result["approved_search_query"].strip()[:500],
        "reason": result["reason"].strip()[:500],
        "certification": certification,
    }


def _validate_temporal_scope(query, source, answer, fact_scope):
    """Ask a dedicated AI whether source and query refer to the same period."""
    import tools

    result = tools.run_ai_prompt(
        "prompts/fact_temporal_validate.txt",
        json.dumps(
            {
                "current_date": datetime.now().date().isoformat(),
                "query": query,
                "fact_intent_scope": fact_scope,
                "candidate_answer": answer,
                "source": {
                    "title": source.get("title", ""),
                    "description": source.get("description", ""),
                    "domain": source.get("domain", ""),
                    "url": source.get("url", ""),
                    "page_content": str(source.get("page_content", ""))[:5000],
                },
            },
            ensure_ascii=False,
            indent=2,
        ),
        expect_json=True,
        num_ctx=8192,
        num_predict=260,
        think=False,
        model_name="gemma4:12b",
    )
    if (
        not isinstance(result, dict)
        or not isinstance(result.get("time_scope_match"), bool)
    ):
        return None
    return {
        "time_scope_match": result["time_scope_match"],
        "requested_period": str(result.get("requested_period", ""))[:200],
        "source_period": str(result.get("source_period", ""))[:200],
        "reason": str(result.get("reason", ""))[:400],
    }


def _validate_temporal_alternative(
    query,
    source,
    answer,
    fact_scope,
    temporal_validation,
    user_request="",
):
    """Validate dated evidence for display without answering the target date."""

    temporal_validation = (
        temporal_validation
        if isinstance(temporal_validation, dict) else {}
    )
    source_period = " ".join(
        str(temporal_validation.get("source_period") or "").split()
    ).strip()[:200]
    if (
        temporal_validation.get("time_scope_match") is not False
        or not source_period
    ):
        return {
            "accepted": False,
            "reason": "A dated, explicitly mismatched source period is required.",
        }
    if (
        isinstance(source, dict)
        and source.get("official_only") is True
        and source.get("official_identity_verified") is not True
    ):
        print(
            "[CASPER TEMPORAL ALTERNATIVE REJECTED]",
            "reason=deterministic_identity_proof_missing",
        )
        return {
            "accepted": False,
            "reason": "Deterministic official-account identity proof is missing.",
        }

    import tools

    checks = (
        "exact_entity_scope",
        "requested_fact_facet_match",
        "source_supported",
        "no_unsupported_additions",
        "explicit_source_period",
    )
    validation_schema = {
        "type": "object",
        "properties": {
            "accepted": {"type": "boolean"},
            **{name: {"type": "boolean"} for name in checks},
            "reason": {"type": "string", "minLength": 1},
        },
        "required": ["accepted", *checks, "reason"],
        "additionalProperties": False,
    }
    result = tools.run_ai_prompt(
        "prompts/fact_temporal_alternative_validate.txt",
        json.dumps(
            {
                "original_user_request": str(user_request or query),
                "query": query,
                "fact_intent_scope": fact_scope,
                "candidate_answer": answer,
                "temporal_validation": temporal_validation,
                "source": {
                    "title": source.get("title", ""),
                    "description": source.get("description", ""),
                    "domain": source.get("domain", ""),
                    "url": source.get("url", ""),
                    "published": source.get("published", ""),
                    "page_content": str(
                        source.get("page_content", "")
                    )[:5000],
                    "official_only": source.get("official_only") is True,
                    "official_identity_verified": (
                        source.get("official_identity_verified") is True
                    ),
                },
            },
            ensure_ascii=False,
            indent=2,
        ),
        expect_json=True,
        num_ctx=8192,
        num_predict=300,
        think=False,
        model_name="gemma4:12b",
        json_schema=validation_schema,
    )
    if (
        not isinstance(result, dict)
        or not isinstance(result.get("accepted"), bool)
        or any(not isinstance(result.get(name), bool) for name in checks)
        or not isinstance(result.get("reason"), str)
        or not result["reason"].strip()
    ):
        return None
    accepted = result["accepted"] is True and all(
        result[name] is True for name in checks
    )
    return {
        "accepted": accepted,
        **{name: result[name] for name in checks},
        "reason": result["reason"].strip()[:400],
    }


def _temporal_period_sort_key(value):
    """Return a conservative sortable key for common visible source dates."""

    text = " ".join(str(value or "").split()).strip()
    match = re.search(
        r"(?<!\d)(\d{4})(?:[-/.年](\d{1,2}))?"
        r"(?:[-/.月](\d{1,2}))?日?",
        text,
    )
    if not match:
        return None
    year = int(match.group(1))
    month = int(match.group(2) or 1)
    day = int(match.group(3) or 1)
    if not (1 <= month <= 12 and 1 <= day <= 31):
        return None
    return year, month, day, text.casefold()


def _temporal_alternative_answer_text(value, chinese=False):
    if isinstance(value, str):
        return " ".join(value.split()).strip()[:1200]
    if isinstance(value, (list, tuple)):
        items = [
            " ".join(str(item).split()).strip()
            for item in value[:20]
            if " ".join(str(item).split()).strip()
        ]
        return ("、" if chinese else ", ").join(items)[:1200]
    if isinstance(value, dict):
        return json.dumps(value, ensure_ascii=False, separators=(",", ":"))[
            :1200
        ]
    return " ".join(str(value or "").split()).strip()[:1200]


def _validate_temporal_alternative_candidates(
    query,
    user_request,
    fact_scope,
    answers,
    read_results,
    limit=3,
):
    """Validate only the best dated fallback after exact research is exhausted."""

    fact_scope = fact_scope if isinstance(fact_scope, dict) else {}
    scope_type = str(fact_scope.get("scope_type") or "").upper().strip()
    pending = []
    for item in answers or []:
        if not isinstance(item, dict) or item.get("accepted") is True:
            continue
        temporal = item.get("temporal_validation")
        temporal = temporal if isinstance(temporal, dict) else {}
        if temporal.get("time_scope_match") is not False:
            continue
        period_key = _temporal_period_sort_key(
            temporal.get("source_period")
        )
        if period_key is None or item.get("answer") in (None, "", [], {}):
            continue
        pending.append((period_key, item))
    pending.sort(
        key=lambda value: value[0],
        reverse=scope_type != "EXPLICIT_PERIOD",
    )
    attempted = 0
    for _period_key, item in pending[:max(1, min(int(limit or 3), 3))]:
        try:
            source_index = int(item.get("index") or 0) - 1
        except (TypeError, ValueError):
            source_index = -1
        if not (0 <= source_index < len(read_results)):
            continue
        attempted += 1
        validation = _validate_temporal_alternative(
            query,
            read_results[source_index],
            item.get("answer"),
            fact_scope,
            item.get("temporal_validation"),
            user_request=user_request or query,
        )
        item["temporal_alternative_validation"] = validation
        item["temporal_alternative_accepted"] = bool(
            isinstance(validation, dict)
            and validation.get("accepted") is True
        )
        if item["temporal_alternative_accepted"]:
            break
    return attempted


def _build_temporal_evidence_fallback(
    user_request,
    fact_scope,
    answers,
    read_results,
    source_contract,
):
    """Build a display-only dated fallback without accepting the target scope."""

    fact_scope = fact_scope if isinstance(fact_scope, dict) else {}
    scope_type = str(fact_scope.get("scope_type") or "").upper().strip()
    if scope_type not in {
        "EXPLICIT_PERIOD",
        "LATEST_COMPLETED_PERIOD",
        "CURRENT_ACTIVE_STATE",
    }:
        return None
    alternatives = []
    seen = set()
    for item in answers or []:
        if (
            not isinstance(item, dict)
            or item.get("accepted") is True
            or item.get("temporal_alternative_accepted") is not True
        ):
            continue
        temporal = item.get("temporal_validation")
        temporal = temporal if isinstance(temporal, dict) else {}
        source_period = " ".join(
            str(temporal.get("source_period") or "").split()
        ).strip()[:200]
        period_key = _temporal_period_sort_key(source_period)
        if period_key is None:
            continue
        try:
            source_index = int(item.get("index") or 0) - 1
        except (TypeError, ValueError):
            source_index = -1
        source = (
            read_results[source_index]
            if 0 <= source_index < len(read_results) else {}
        )
        answer_value = item.get("answer")
        fingerprint = (
            source_period.casefold(),
            json.dumps(answer_value, ensure_ascii=False, sort_keys=True),
        )
        if fingerprint in seen:
            continue
        seen.add(fingerprint)
        alternatives.append({
            "source_period": source_period,
            "requested_period": " ".join(
                str(temporal.get("requested_period") or "").split()
            ).strip()[:200],
            "period_sort_key": period_key,
            "answer": answer_value,
            "source_index": source_index + 1,
            "source_title": str(source.get("title") or "")[:300],
            "source_url": str(source.get("url") or "")[:2000],
            "validation": item.get("temporal_alternative_validation"),
        })
    if not alternatives:
        return None

    if scope_type == "EXPLICIT_PERIOD":
        selected = min(alternatives, key=lambda value: value["period_sort_key"])
        selection = "EARLIEST_VERIFIED_ALTERNATIVE"
    else:
        selected = max(alternatives, key=lambda value: value["period_sort_key"])
        selection = "LATEST_VERIFIED_ALTERNATIVE"
    chinese = bool(re.search(r"[\u3400-\u9fff]", str(user_request or "")))
    answer_text = _temporal_alternative_answer_text(
        selected.get("answer"), chinese=chinese
    )
    if not answer_text:
        return None
    requested_period = " ".join(
        str(fact_scope.get("requested_period") or "").split()
    ).strip()
    if chinese and scope_type == "CURRENT_ACTIVE_STATE":
        requested_date = re.search(
            r"(?<!\d)\d{4}-\d{1,2}-\d{1,2}(?!\d)",
            requested_period,
        )
        requested_period = (
            "截至 " + requested_date.group(0) + " 的当前状态"
            if requested_date else "当前状态"
        )
    elif not requested_period:
        requested_period = "当前状态" if chinese else "the current state"
    source_period = selected["source_period"]
    official = bool(
        isinstance(source_contract, dict)
        and source_contract.get("official_only") is True
    )
    if chinese:
        source_kind = "官方资料" if official else "资料"
        direction = "最早" if scope_type == "EXPLICIT_PERIOD" else "最新"
        reply = (
            "我没有查到能直接核实 " + requested_period + " 的"
            + source_kind + "。不过，这次检索中能核实到的" + direction
            + source_kind + "是 " + source_period + "：" + answer_text
            + "。这只能作为 " + source_period + " 的记录，不能当作 "
            + requested_period + " 的结论。"
        )
    else:
        source_kind = "official evidence" if official else "evidence"
        direction = "earliest" if scope_type == "EXPLICIT_PERIOD" else "latest"
        reply = (
            "I could not find " + source_kind + " that directly verifies "
            + requested_period + ". The " + direction + " verifiable "
            + source_kind + " found in this search is from " + source_period
            + ": " + answer_text + ". This is only a " + source_period
            + " record and does not establish the requested period."
        )
    selected = dict(selected)
    selected.pop("period_sort_key", None)
    return {
        "version": TEMPORAL_EVIDENCE_GRACEFUL_FALLBACK_VERSION,
        "display_only": True,
        "target_scope_answered": False,
        "knowledge_eligible": False,
        "selection": selection,
        "requested_period": requested_period,
        "selected_evidence": selected,
        "candidate_count": len(alternatives),
        "reply": reply[:3000],
    }


def _audit_combined_fact_resolution(
    user_request,
    query,
    fact_scope,
    judgment,
    browser_sources,
    answers,
):
    """Ask an independent AI whether the resolver kept scope and evidence."""
    import tools

    audit_schema = {
        "type": "object",
        "properties": {
            "accepted": {"type": "boolean"},
            "exact_entity_scope": {"type": "boolean"},
            "exact_temporal_scope": {"type": "boolean"},
            "status_supported_by_evidence": {"type": "boolean"},
            "not_missing_evidence_mislabeled_unavailable": {
                "type": "boolean"
            },
            "reason": {"type": "string", "minLength": 1},
        },
        "required": [
            "accepted",
            "exact_entity_scope",
            "exact_temporal_scope",
            "status_supported_by_evidence",
            "not_missing_evidence_mislabeled_unavailable",
            "reason",
        ],
        "additionalProperties": False,
    }
    result = tools.run_ai_prompt(
        "prompts/fact_resolution_audit.txt",
        json.dumps(
            {
                "current_date": datetime.now().date().isoformat(),
                "original_user_request": str(user_request or query),
                "retrieval_query": query,
                "fact_intent_scope": fact_scope,
                "resolver_judgment": judgment,
                "single_source_answers": answers,
                "browser_sources": browser_sources,
            },
            ensure_ascii=False,
            indent=2,
        ),
        expect_json=True,
        num_ctx=8192,
        num_predict=420,
        think=False,
        model_name="gemma4:12b",
        json_schema=audit_schema,
    )
    checks = (
        "exact_entity_scope",
        "exact_temporal_scope",
        "status_supported_by_evidence",
        "not_missing_evidence_mislabeled_unavailable",
    )
    if (
        not isinstance(result, dict)
        or not isinstance(result.get("accepted"), bool)
        or any(not isinstance(result.get(name), bool) for name in checks)
        or not isinstance(result.get("reason"), str)
        or not result["reason"].strip()
    ):
        return None
    accepted = result["accepted"] is True and all(
        result[name] is True for name in checks
    )
    return {
        "accepted": accepted,
        **{name: result[name] for name in checks},
        "reason": result["reason"].strip()[:500],
    }


def _resolve_combined_fact(
    query,
    read_results,
    answers,
    fact_scope,
    user_request="",
):
    """Let AI distinguish a missing value from a value not produced yet."""
    import tools

    compact_sources = []
    for item in read_results[:7]:
        compact_sources.append(
            {
                "title": item.get("title", ""),
                "description": item.get("description", ""),
                "domain": item.get("domain", ""),
                "url": item.get("url", ""),
                "page_success": item.get("page_success", False),
                "page_error": item.get("page_error", ""),
                "page_content": str(item.get("page_content", ""))[:900],
            }
        )

    evidence_packet = {
        "current_date": datetime.now().date().isoformat(),
        "original_user_request": str(user_request or query),
        "query": query,
        "fact_intent_scope": fact_scope,
        "single_source_answers": answers,
        "browser_sources": compact_sources,
    }
    result = tools.run_ai_prompt(
        "prompts/fact_resolve.txt",
        json.dumps(evidence_packet, ensure_ascii=False, indent=2),
        expect_json=True,
        num_ctx=8192,
        num_predict=420,
        think=False,
        model_name="gemma4:12b",
    )
    if not isinstance(result, dict):
        result = {}

    def judgment_contract_complete(value):
        if not isinstance(value, dict):
            return False
        status = str(value.get("answer_status", "")).upper().strip()
        reason = value.get("reason")
        return (
            status in {"FOUND", "NOT_YET_AVAILABLE", "INSUFFICIENT"}
            and isinstance(reason, str)
            and bool(reason.strip())
        )

    if not judgment_contract_complete(result):
        result = tools.run_ai_prompt(
            "prompts/fact_resolve_retry.txt",
            json.dumps(
                {
                    "evidence_packet": evidence_packet,
                    "previous_incomplete_decision": result,
                },
                ensure_ascii=False,
                indent=2,
            ),
            expect_json=True,
            num_ctx=8192,
            num_predict=420,
            think=False,
            model_name="gemma4:12b",
        )

    if not judgment_contract_complete(result):
        return None

    status = str(result["answer_status"]).upper().strip()
    judgment = {
        "answer_status": status,
        "reason": str(result["reason"]).strip()[:500],
    }
    if status == "INSUFFICIENT":
        return {
            **judgment,
            "accepted": False,
            "resolution_audit": None,
        }

    resolution_audit = _audit_combined_fact_resolution(
        user_request or query,
        query,
        fact_scope,
        judgment,
        compact_sources,
        answers,
    )
    if (
        not isinstance(resolution_audit, dict)
        or resolution_audit.get("accepted") is not True
    ):
        return {
            "answer_status": "INSUFFICIENT",
            "resolver_answer_status": status,
            "reason": (
                "The independent AI rejected the combined-evidence outcome: "
                + str(
                    (resolution_audit or {}).get(
                        "reason", "invalid resolution-audit contract"
                    )
                )
            )[:500],
            "accepted": False,
            "resolution_audit": resolution_audit,
        }

    answer_input = {
        "original_user_request": str(user_request or query),
        "query": query,
        "fact_intent_scope": fact_scope,
        "evidence_judgment": judgment,
    }
    answer_result = tools.run_ai_prompt(
        "prompts/fact_answer.txt",
        json.dumps(answer_input, ensure_ascii=False, indent=2),
        expect_json=True,
        num_ctx=4096,
        num_predict=300,
        think=False,
        model_name="gemma4:12b",
    )

    def answer_contract_complete(value):
        return (
            isinstance(value, dict)
            and isinstance(value.get("answer"), str)
            and bool(value["answer"].strip())
            and isinstance(value.get("response_instruction"), str)
            and bool(value["response_instruction"].strip())
        )

    if not answer_contract_complete(answer_result):
        answer_result = tools.run_ai_prompt(
            "prompts/fact_answer_retry.txt",
            json.dumps(
                {
                    **answer_input,
                    "previous_incomplete_answer": answer_result,
                },
                ensure_ascii=False,
                indent=2,
            ),
            expect_json=True,
            num_ctx=4096,
            num_predict=300,
            think=False,
            model_name="gemma4:12b",
        )

    if not answer_contract_complete(answer_result):
        return None

    return {
        "answer_status": status,
        "answer": answer_result["answer"].strip()[:1000],
        "reason": judgment["reason"],
        "accepted": True,
        "resolution_audit": resolution_audit,
        "response_instruction": answer_result[
            "response_instruction"
        ].strip()[:500],
    }


def _plan_evidence_gap(
    query,
    read_results,
    answers,
    fact_scope,
    user_request="",
):
    """Ask AI whether one bounded follow-up browser pass is worthwhile."""
    import tools

    compact_sources = []
    for item in read_results[:7]:
        compact_sources.append(
            {
                "title": item.get("title", ""),
                "description": item.get("description", ""),
                "domain": item.get("domain", ""),
                "url": item.get("url", ""),
                "page_success": item.get("page_success", False),
                "page_error": item.get("page_error", ""),
                "page_content": str(item.get("page_content", ""))[:600],
            }
        )
    result = tools.run_ai_prompt(
        "prompts/fact_evidence_gap.txt",
        json.dumps(
            {
                "current_date": datetime.now().date().isoformat(),
                "original_user_request": str(user_request or query),
                "original_query": query,
                "fact_intent_scope": fact_scope,
                "candidate_answers": answers,
                "browser_sources": compact_sources,
            },
            ensure_ascii=False,
            indent=2,
        ),
        expect_json=True,
        num_ctx=6144,
        num_predict=500,
        think=False,
        model_name="gemma4:12b",
    )
    if not isinstance(result, dict):
        return None
    action = str(result.get("action", "")).upper().strip()
    queries = result.get("follow_up_queries")
    if action not in {"RESEARCH_AGAIN", "RESOLVE_NOW"} or not isinstance(
        queries, list
    ):
        return None
    queries = [
        str(value).strip()[:240]
        for value in queries
        if isinstance(value, str) and value.strip()
    ][:2]
    if action == "RESEARCH_AGAIN" and not queries:
        return None
    if action == "RESOLVE_NOW" and queries:
        return None
    return {
        "action": action,
        "gap_type": str(result.get("gap_type", ""))[:160],
        "follow_up_queries": queries,
        "reason": str(result.get("reason", ""))[:500],
    }


def _detected_search_region(country_code=None):
    """Read explicit/local region state without inferring it from language."""
    code = str(country_code or "").upper().strip()
    try:
        import location

        detected = location.detect_location()
    except (ImportError, AttributeError, TypeError, ValueError):
        detected = {}
    return {
        "country_code": code or str(
            detected.get("country_code") or ""
        ).upper().strip(),
        "country_name": str(detected.get("country_name") or "").strip()[:120],
        "location_name": str(detected.get("location_name") or "").strip()[:120],
        "time_zone": str(detected.get("time_zone") or "").strip()[:120],
        "unit_system": str(detected.get("unit_system") or "").strip()[:80],
        "preferred_search_engines": [
            str(value or "").strip()
            for value in detected.get("preferred_search_engines", [])[:2]
            if str(value or "").strip()
        ],
        "source": (
            "explicit_country_code+cached_profile"
            if code
            else str(detected.get("source") or "unknown").strip()[:80]
        ),
        "confidence": str(
            detected.get("confidence") or "unknown"
        ).strip()[:40],
    }


def _engine_is_eligible_for_region(engine_id, country_code):
    """Validate catalog availability and regional audience metadata only."""
    entry = SEARCH_ENGINE_BY_ID.get(str(engine_id or ""))
    if not entry or entry.get("available") is not True:
        return False
    if entry.get("market_scope") == "global":
        return True
    audiences = {
        str(value or "").upper().strip()
        for value in entry.get("audience_country_codes", [])
        if str(value or "").strip()
    }
    return bool(country_code and country_code in audiences)


def _valid_search_engine_plan(value, country_code=""):
    if not isinstance(value, dict) or not isinstance(value.get("reason"), str):
        return False
    engines = value.get("engines")
    code = str(country_code or "").upper().strip()
    return (
        isinstance(engines, list)
        and len(engines) == 2
        and len(set(engines)) == 2
        and all(
            isinstance(engine, str)
            and engine in SUPPORTED_SEARCH_ENGINES
            and _engine_is_eligible_for_region(engine, code)
            for engine in engines
        )
    )


def _eligible_engine_catalog(country_code=""):
    code = str(country_code or "").upper().strip()
    return [
        dict(entry)
        for entry in SEARCH_ENGINE_CATALOG
        if _engine_is_eligible_for_region(entry.get("id"), code)
    ]


def _safe_engine_recovery_pair(country_code=""):
    """Return Bekki's fixed US-oriented primary/fallback pair."""
    del country_code
    return ("google", "bing")


@lru_cache(maxsize=64)
def _ai_search_engine_policy(
    country_code,
    country_name,
    location_name,
    time_zone,
    location_source,
    location_confidence,
    research_query,
):
    """Compatibility entry point; R21 performs no per-query engine planning."""
    del (
        country_code,
        country_name,
        location_name,
        time_zone,
        location_source,
        location_confidence,
        research_query,
    )
    return ("google", "bing")


def _search_engine_policy(country_code=None, research_query=""):
    """Use one fixed US-oriented pair for both Chinese and English queries."""
    region = _detected_search_region(country_code)
    print("[CASPER SEARCH REGION]", json.dumps({
        key: region.get(key, "")
        for key in (
            "country_code",
            "time_zone",
            "source",
            "confidence",
        )
    }, ensure_ascii=False))
    del research_query
    engines = ("google", "bing")
    print("[CASPER SEARCH ENGINES FIXED_US]", engines)
    print("[CASPER SEARCH ENGINES]", engines)
    return engines


def search_web(query, count=7, engine="google"):
    """Discover public results through one managed-browser search engine."""
    from playwright.sync_api import (
        sync_playwright,
        TimeoutError,
        Error as PlaywrightError,
    )

    ensure_browser()
    engine = str(engine).lower().strip()
    targets = {
        "bing": "https://www.bing.com/search?q=" + quote(str(query)),
        "google": "https://www.google.com/search?q=" + quote(str(query)),
    }
    if engine not in targets:
        raise ValueError("Unsupported managed-browser search engine: " + engine)
    target = targets[engine]

    with sync_playwright() as playwright:
        browser = playwright.chromium.connect_over_cdp(CDP_URL)
        if not browser.contexts:
            raise RuntimeError("Casper Browser has no usable context.")
        page = browser.contexts[0].new_page()
        try:
            try:
                page.goto(target, wait_until="domcontentloaded", timeout=20000)
            except (TimeoutError, PlaywrightError) as error:
                print("[CASPER SEARCH NAVIGATION]", repr(error))
                pass
            page.wait_for_timeout(1200)
            body_text = page.locator("body").inner_text(timeout=10000)
            protected = _protected_event(body_text)
            if protected:
                return {"status": "HUMAN_HANDOFF", "event": protected, "results": []}

            results = []
            seen = set()
            ai_summary = (
                _extract_google_ai_summary(body_text)
                if engine == "google"
                else ""
            )
            if engine == "bing":
                cards = page.locator("li.b_algo")
            else:
                cards = page.locator("div.MjjYud, div.g")
            for index in range(min(cards.count(), max(int(count), 1) * 2)):
                card = cards.nth(index)
                if engine == "bing":
                    link = card.locator("h2 a").first
                else:
                    link = card.locator("a:has(h3)").first
                if link.count() == 0:
                    continue
                url = link.get_attribute("href") or ""
                title = link.inner_text(timeout=3000)
                if engine == "bing":
                    snippets = card.locator(".b_caption p")
                else:
                    snippets = card.locator("div.VwiC3b, div[data-sncf]")
                description = (
                    snippets.first.inner_text(timeout=3000)
                    if snippets.count()
                    else ""
                )
                item = _clean_result(title, description, url)
                if not item or item["url"] in seen:
                    continue
                item["discovery_engine"] = engine
                seen.add(item["url"])
                results.append(item)
                if len(results) >= count:
                    break
            return {
                "status": "OK" if results else "NO_RESULTS",
                "results": results,
                "engine": engine,
                "ai_summary": ai_summary,
            }
        finally:
            page.close()


def discover_web(
    query,
    count=7,
    status_callback=None,
    allowed_domains=None,
    multi_engine=False,
    country_code=None,
    engine_plan=None,
    minimum_results=1,
):
    """Search the primary engine first and use fallbacks only if insufficient."""
    allowed_domains = [
        str(value).lower().strip().removeprefix("www.")
        for value in (allowed_domains or [])
        if str(value).strip()
    ]

    def in_scope(item):
        if not allowed_domains:
            return True
        domain = str(item.get("domain", "")).lower().strip().removeprefix("www.")
        return any(
            domain == allowed or domain.endswith("." + allowed)
            for allowed in allowed_domains
        )

    merged = []
    seen_urls = set()
    protected_events = []
    engine_errors = []
    ai_summaries = []
    code = str(country_code or "").upper().strip()
    if engine_plan is None:
        planned_engines = _search_engine_policy(country_code, query)
    else:
        planned_engines = tuple(str(value or "").strip() for value in engine_plan)
        if (
            len(planned_engines) != 2
            or len(set(planned_engines)) != 2
            or any(
                not _engine_is_eligible_for_region(engine, code)
                for engine in planned_engines
            )
        ):
            planned_engines = ()
    if not planned_engines:
        return {
            "status": "NO_RESULTS",
            "reason": "search_engine_plan_invalid",
            "results": [],
            "discovery_type": "casper_browser_multi_engine",
        }
    engines = list(planned_engines)
    if not multi_engine:
        # The AI chooses the primary pair. Python supplies one execution-only
        # recovery engine when both primary parsers are blocked or empty.
        for recovery in ("bing", "google"):
            if (
                recovery not in engines
                and _engine_is_eligible_for_region(recovery, country_code)
            ):
                engines.append(recovery)
                break
    try:
        required_results = max(1, min(int(minimum_results), int(count)))
    except (TypeError, ValueError):
        required_results = 1
    for index, engine in enumerate(engines):
        if index:
            _status(
                status_callback,
                "正在通过另一个浏览器搜索引擎补充候选… 🔄",
            )
            print(
                "[CASPER BROWSER SEARCH FALLBACK]",
                engine,
                repr(str(query)[:240]),
            )
        try:
            result = search_web(query, count=count, engine=engine)
        except Exception as error:
            print("[CASPER SEARCH ENGINE ERROR]", engine, repr(error))
            engine_errors.append(engine + ": " + repr(error)[:240])
            continue
        if result.get("status") == "HUMAN_HANDOFF":
            protected_events.append(result.get("event") or "access_block")
            continue
        ai_summary = str(result.get("ai_summary") or "").strip()[:3000]
        if ai_summary:
            ai_summaries.append(
                {"engine": engine, "summary": ai_summary}
            )
        for item in result.get("results", []):
            if not isinstance(item, dict) or not in_scope(item):
                continue
            url = str(item.get("url") or "").strip()
            if not url or url in seen_urls:
                continue
            seen_urls.add(url)
            merged.append(item)
        if len(merged) >= required_results:
            break

    if merged:
        limit = max(int(count), 1)
        return {
            "status": "OK",
            "results": merged[:limit],
            "ai_summaries": ai_summaries,
            "discovery_type": "casper_browser_multi_engine",
        }
    if protected_events:
        return {
            "status": "HUMAN_HANDOFF",
            "event": protected_events[0],
            "results": [],
            "discovery_type": "casper_browser_multi_engine",
        }
    return {
        "status": "NO_RESULTS",
        "reason": "all_search_engines_failed" if engine_errors else "no_results",
        "engine_errors": engine_errors,
        "results": [],
        "ai_summaries": ai_summaries,
        "discovery_type": "casper_browser_multi_engine",
    }


def _page_link_id(text_value, href):
    material = (str(text_value).strip() + "\0" + str(href).strip()).encode(
        "utf-8", errors="ignore"
    )
    return "link_" + hashlib.sha256(material).hexdigest()[:16]


def _select_clicked_navigation_url(
    before_url, primary_after_url, opened_urls, selected_href
):
    """Structurally identify the tab opened by one exact selected anchor."""
    before = str(before_url or "").strip()
    after = str(primary_after_url or "").strip()
    expected = str(selected_href or "").strip()
    expected_host = urlparse(expected).netloc.casefold()
    valid_opened = []
    for value in opened_urls or []:
        candidate = str(value or "").strip()
        parsed = urlparse(candidate)
        if parsed.scheme not in {"http", "https"} or not parsed.netloc:
            continue
        if candidate == before:
            continue
        valid_opened.append(candidate)
        if candidate == expected:
            return candidate
    if expected_host:
        for candidate in valid_opened:
            if urlparse(candidate).netloc.casefold() == expected_host:
                return candidate
    parsed_after = urlparse(after)
    if (
        after != before
        and parsed_after.scheme in {"http", "https"}
        and parsed_after.netloc
    ):
        return after
    return valid_opened[0] if len(valid_opened) == 1 else ""


def _document_url_key(url):
    """Normalize only URL structure needed to recognize one browser document."""
    parsed = urlparse(str(url).strip())
    scheme = parsed.scheme.casefold()
    hostname = (parsed.hostname or "").casefold().removeprefix("www.")
    try:
        port = parsed.port
    except ValueError:
        port = None
    if (scheme == "http" and port == 80) or (scheme == "https" and port == 443):
        port = None
    path = unquote(parsed.path or "/").rstrip("/") or "/"
    query = tuple(sorted(parse_qsl(parsed.query, keep_blank_values=True)))
    return scheme, hostname, port, path, query


def list_page_links(url, maximum=100):
    """Return bounded visible HTTP links with opaque IDs from one page."""
    from playwright.sync_api import (
        sync_playwright,
        TimeoutError,
        Error as PlaywrightError,
    )

    target = str(url).strip()
    parsed = urlparse(target)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        return {"status": "INVALID_URL", "links": []}
    ensure_browser()
    with sync_playwright() as playwright:
        browser = playwright.chromium.connect_over_cdp(CDP_URL)
        page = browser.contexts[0].new_page()
        try:
            try:
                page.goto(target, wait_until="domcontentloaded", timeout=20000)
            except (TimeoutError, PlaywrightError) as error:
                print("[CASPER LINK PAGE NAVIGATION]", repr(error))
            page.wait_for_timeout(1000)
            body = page.locator("body").inner_text(timeout=10000)
            protected = _protected_event(body)
            if protected:
                return {
                    "status": "HUMAN_HANDOFF",
                    "event": protected,
                    "links": [],
                }
            links, seen = [], set()
            anchors = page.locator("a[href]")
            for index in range(min(anchors.count(), 300)):
                anchor = anchors.nth(index)
                href = urljoin(page.url, anchor.get_attribute("href") or "")
                href_parsed = urlparse(href)
                if href_parsed.scheme not in {"http", "https"} or not href_parsed.netloc:
                    continue
                text_value = " ".join(
                    (anchor.inner_text(timeout=1000) or "").split()
                )[:240]
                if not text_value:
                    text_value = str(anchor.get_attribute("aria-label") or "").strip()[:240]
                link_id = _page_link_id(text_value, href)
                if link_id in seen:
                    continue
                seen.add(link_id)
                links.append(
                    {
                        "id": link_id,
                        "text": text_value,
                        "domain": href_parsed.netloc.lower().removeprefix("www."),
                        "path": href_parsed.path[:500],
                        "query": href_parsed.query[:500],
                        "target_relation": (
                            "same_document"
                            if _document_url_key(href)
                            == _document_url_key(page.url)
                            else "different_document"
                        ),
                        "download_attribute": (
                            anchor.get_attribute("download") is not None
                        ),
                        "opens_new_context": (
                            str(anchor.get_attribute("target") or "").casefold()
                            == "_blank"
                        ),
                    }
                )
                if len(links) >= max(1, min(int(maximum), 120)):
                    break
            return {
                "status": "OK" if links else "NO_RESULTS",
                "links": links,
                "page_url": page.url,
            }
        finally:
            page.close()


def activate_page_link(url, link_id, destination_dir):
    """Click one exact catalogued link and capture a download or navigation."""
    from playwright.sync_api import (
        sync_playwright,
        TimeoutError,
        Error as PlaywrightError,
    )

    target = str(url).strip()
    if urlparse(target).scheme not in {"http", "https"}:
        return {"status": "INVALID_URL"}
    destination = Path(destination_dir)
    destination.mkdir(parents=True, exist_ok=True)
    ensure_browser()
    with sync_playwright() as playwright:
        browser = playwright.chromium.connect_over_cdp(CDP_URL)
        context = browser.contexts[0]
        page = context.new_page()
        downloads = []
        opened_pages = []

        def capture_page(opened_page):
            opened_pages.append(opened_page)
            opened_page.on("download", lambda item: downloads.append(item))

        context.on("page", capture_page)
        page.on("download", lambda item: downloads.append(item))
        try:
            try:
                page.goto(target, wait_until="domcontentloaded", timeout=20000)
            except (TimeoutError, PlaywrightError) as error:
                print("[CASPER DOWNLOAD PAGE NAVIGATION]", repr(error))
            page.wait_for_timeout(1000)
            body = page.locator("body").inner_text(timeout=10000)
            protected = _protected_event(body)
            if protected:
                return {"status": "HUMAN_HANDOFF", "event": protected}
            selected = None
            selected_href = ""
            anchors = page.locator("a[href]")
            for index in range(min(anchors.count(), 300)):
                anchor = anchors.nth(index)
                href = urljoin(page.url, anchor.get_attribute("href") or "")
                if urlparse(href).scheme not in {"http", "https"}:
                    continue
                text_value = " ".join(
                    (anchor.inner_text(timeout=1000) or "").split()
                )[:240]
                if not text_value:
                    text_value = str(anchor.get_attribute("aria-label") or "").strip()[:240]
                if _page_link_id(text_value, href) == str(link_id):
                    selected = anchor
                    selected_href = href
                    break
            if selected is None:
                return {"status": "LINK_NOT_FOUND"}
            before = page.url
            if (
                _document_url_key(selected_href) == _document_url_key(before)
                and selected.get_attribute("download") is None
            ):
                return {
                    "status": "STRUCTURAL_NOOP",
                    "url": before,
                    "selected_href": selected_href,
                }
            try:
                selected.click(timeout=10000)
            except (TimeoutError, PlaywrightError) as error:
                return {"status": "CLICK_FAILED", "reason": str(error)[:300]}
            page.wait_for_timeout(5000)
            if downloads:
                download = downloads[0]
                filename = Path(download.suggested_filename or "download.bin").name
                if not filename:
                    filename = "download.bin"
                saved_path = destination / filename
                download.save_as(str(saved_path))
                return {
                    "status": "DOWNLOADED",
                    "path": str(saved_path),
                    "filename": filename,
                }
            after = page.url
            navigation_url = _select_clicked_navigation_url(
                before,
                after,
                [opened_page.url for opened_page in opened_pages],
                selected_href,
            )
            return {
                "status": "NAVIGATED" if navigation_url else "NO_DOWNLOAD",
                "url": navigation_url or after,
            }
        finally:
            try:
                context.remove_listener("page", capture_page)
            except (AttributeError, PlaywrightError):
                pass
            for opened_page in opened_pages:
                try:
                    if not opened_page.is_closed():
                        opened_page.close()
                except PlaywrightError:
                    pass
            page.close()


def read_url(url):
    """Read visible rendered text from one public page in the managed browser."""
    from playwright.sync_api import (
        sync_playwright,
        TimeoutError,
        Error as PlaywrightError,
    )

    ensure_browser()
    with sync_playwright() as playwright:
        browser = playwright.chromium.connect_over_cdp(CDP_URL)
        if not browser.contexts:
            raise RuntimeError("Casper Browser has no usable context.")
        page = browser.contexts[0].new_page()
        try:
            try:
                page.goto(url, wait_until="domcontentloaded", timeout=20000)
            except TimeoutError as error:
                print("[CASPER PAGE TIMEOUT]", url, repr(error))
            except PlaywrightError as error:
                # A protocol, TLS, DNS, or connection failure belongs to this
                # candidate only. Casper must continue to the next source.
                return {
                    "success": False,
                    "reader_type": "casper_browser",
                    "content": "",
                    "error": str(error)[:1000],
                    "navigation_error": True,
                }

            try:
                page.wait_for_timeout(1400)
                text = page.locator("body").inner_text(timeout=12000).strip()
            except PlaywrightError as error:
                return {
                    "success": False,
                    "reader_type": "casper_browser",
                    "content": "",
                    "error": str(error)[:1000],
                    "navigation_error": True,
                }
            protected = _protected_event(text)
            if protected:
                return {
                    "success": False,
                    "reader_type": "casper_browser",
                    "content": "",
                    "error": "Protected browser event: " + protected,
                    "protected_event": protected,
                }
            image_url = ""
            structured_product = ""
            published = ""
            try:
                scripts = page.locator('script[type="application/ld+json"]')
                raw_scripts = scripts.all_text_contents()[:20] if scripts.count() else []
                structured_product, structured_image = _product_json_ld(raw_scripts)
                image_url = _usable_product_image(structured_image)

                # Prefer a concrete product image over generic OpenGraph art.
                if not image_url:
                    product_image = page.locator(
                        'meta[itemprop="image"], img#landingImage, '
                        'img[data-old-hires], img[itemprop="image"]'
                    ).first
                    if product_image.count():
                        for attribute in ("content", "data-old-hires", "src"):
                            image_url = _usable_product_image(
                                product_image.get_attribute(attribute) or ""
                            )
                            if image_url:
                                break
                        if not image_url:
                            dynamic = product_image.get_attribute(
                                "data-a-dynamic-image"
                            ) or ""
                            try:
                                dynamic_urls = json.loads(dynamic)
                            except (TypeError, ValueError, json.JSONDecodeError):
                                dynamic_urls = {}
                            if isinstance(dynamic_urls, dict):
                                for candidate_url in dynamic_urls:
                                    image_url = _usable_product_image(candidate_url)
                                    if image_url:
                                        break

                if not image_url:
                    image = page.locator(
                        'meta[property="og:image"], meta[name="twitter:image"], '
                        'link[rel="image_src"]'
                    ).first
                    if image.count():
                        image_url = _usable_product_image(
                            image.get_attribute("content")
                            or image.get_attribute("href")
                            or ""
                        )
                date_meta = page.locator(
                    'meta[property="article:published_time"], '
                    'meta[name="date"], meta[name="pubdate"]'
                ).first
                if date_meta.count():
                    published = date_meta.get_attribute("content") or ""
            except PlaywrightError:
                pass
            # Modern merchant pages can expose a complete Product object while
            # rendering very little body text. That is still usable evidence.
            if len(text) < 250 and not structured_product:
                return {
                    "success": False,
                    "reader_type": "casper_browser",
                    "content": text[:MAX_PAGE_TEXT],
                    "final_url": page.url,
                    "error": "Rendered page contained too little usable product evidence.",
                }
            return {
                "success": True,
                "reader_type": "casper_browser",
                "content": text[:MAX_PAGE_TEXT],
                "image_url": image_url[:2048],
                "structured_product": structured_product,
                "final_url": page.url,
                "published": published[:160],
                "error": None,
            }
        finally:
            page.close()


def _extract_news_events(user_request, articles):
    """Let AI classify rendered pages and extract one event per article."""
    import tools

    packet = {
        "current_date": datetime.now().date().isoformat(),
        "original_user_request": str(user_request),
        "articles": [
            {
                "index": index,
                "title": item.get("title", ""),
                "description": item.get("description", ""),
                "domain": item.get("domain", ""),
                "url": item.get("url", ""),
                "published_metadata": item.get("published", ""),
                "source_score": item.get("source_score", 50),
                "page_success": item.get("page_success", False),
                "page_content": str(item.get("page_content", ""))[:4500],
            }
            for index, item in enumerate(articles[:6], start=1)
        ],
    }
    result = tools.run_ai_prompt(
        "prompts/casper_news_extract.txt",
        json.dumps(packet, ensure_ascii=False, indent=2),
        expect_json=True,
        num_ctx=12288,
        num_predict=1600,
        think=False,
        model_name="gemma4:12b",
    )
    items = result.get("items") if isinstance(result, dict) else None
    if not isinstance(items, list):
        recovery_packet = dict(packet)
        recovery_packet["articles"] = [
            {
                **item,
                "page_content": str(item.get("page_content", ""))[:1800],
            }
            for item in packet["articles"]
        ]
        print("[CASPER NEWS EXTRACT RECOVERY] invalid_json_contract")
        result = tools.run_ai_prompt(
            "prompts/casper_news_extract_retry.txt",
            json.dumps(
                recovery_packet,
                ensure_ascii=False,
                separators=(",", ":"),
            ),
            expect_json=True,
            num_ctx=8192,
            num_predict=1600,
            think=False,
            model_name="gemma4:12b",
            json_schema={
                "type": "object",
                "properties": {
                    "items": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "properties": {
                                "index": {"type": "integer"},
                                "is_concrete_news": {"type": "boolean"},
                                "content_type": {"type": "string"},
                                "event_title": {"type": "string"},
                                "summary": {"type": "string"},
                                "published_at": {"type": "string"},
                                "event_date": {"type": "string"},
                                "event_key": {"type": "string"},
                                "uncertainty": {"type": "string"},
                                "relevance_score": {"type": "integer"},
                                "reason": {"type": "string"},
                            },
                            "required": [
                                "index", "is_concrete_news", "content_type",
                                "event_title", "summary", "published_at",
                                "event_date", "event_key", "uncertainty",
                                "relevance_score", "reason",
                            ],
                        },
                    },
                },
                "required": ["items"],
            },
        )
        items = result.get("items") if isinstance(result, dict) else None
        if not isinstance(items, list):
            return None
    decisions = {}
    for value in items:
        if not isinstance(value, dict):
            continue
        try:
            index = int(value.get("index"))
            score = int(value.get("relevance_score", 0))
        except (TypeError, ValueError):
            continue
        if index < 1 or index > len(packet["articles"]):
            continue
        raw_content_type = str(
            value.get("content_type", "OTHER")
        ).upper().strip()
        allowed_content_types = {
            "NEWS", "AGGREGATOR", "TEAM_PAGE", "SCHEDULE", "ROSTER",
            "BACKGROUND", "OTHER",
        }
        content_type = raw_content_type
        if content_type not in allowed_content_types:
            # Compact models occasionally copy a schema union literally, for
            # example ``NEWS | AGGREGATOR``.  Recover the strongest supported
            # label instead of discarding the entire otherwise valid batch.
            declared_types = [
                item
                for item in re.findall(r"[A-Z_]+", raw_content_type)
                if item in allowed_content_types
            ]
            if value.get("is_concrete_news") is True and "NEWS" in declared_types:
                content_type = "NEWS"
            elif declared_types:
                content_type = declared_types[0]
        concrete = value.get("is_concrete_news") is True
        if content_type not in allowed_content_types:
            continue
        decisions[index] = {
            "is_concrete_news": concrete and content_type == "NEWS",
            "content_type": content_type,
            "event_title": str(value.get("event_title", "")).strip()[:240],
            "summary": str(value.get("summary", "")).strip()[:900],
            "published_at": str(value.get("published_at", "")).strip()[:160],
            "event_date": str(value.get("event_date", "")).strip()[:160],
            "event_key": str(value.get("event_key", "")).strip()[:240],
            "uncertainty": str(value.get("uncertainty", "")).strip()[:500],
            "relevance_score": max(0, min(100, score)),
            "reason": str(value.get("reason", "")).strip()[:500],
        }
    # Treat the model output as a per-article decision set.  One missing or
    # malformed row must not erase every valid news item in the batch.
    return decisions or None


def _curate_news_feed(user_request, articles):
    """Let AI merge repeated events and choose a ranked feed."""
    import tools

    candidates = []
    for index, item in enumerate(articles, start=1):
        if not item.get("is_concrete_news"):
            continue
        candidates.append(
            {
                "source_index": index,
                "event_title": item.get("event_title", ""),
                "summary": item.get("event_summary", ""),
                "event_date": item.get("event_date", ""),
                "published_at": item.get("published", ""),
                "event_key": item.get("event_key", ""),
                "uncertainty": item.get("uncertainty", ""),
                "domain": item.get("domain", ""),
                "source_score": item.get("source_score", 50),
                "relevance_score": item.get("news_score", 0),
            }
        )
    if not candidates:
        return []
    result = tools.run_ai_prompt(
        "prompts/casper_news_curate.txt",
        json.dumps(
            {
                "current_date": datetime.now().date().isoformat(),
                "original_user_request": str(user_request),
                "candidates": candidates,
            },
            ensure_ascii=False,
            indent=2,
        ),
        expect_json=True,
        num_ctx=4096,
        num_predict=700,
        think=False,
        model_name="gemma4:12b",
    )
    selected = result.get("selected") if isinstance(result, dict) else None
    if not isinstance(selected, list):
        return None
    valid_indices = {item["source_index"] for item in candidates}
    candidates_by_index = {
        item["source_index"]: item for item in candidates
    }
    output = []
    seen = set()
    seen_event_keys = set()
    for value in selected:
        if not isinstance(value, dict):
            continue
        try:
            index = int(value.get("source_index"))
        except (TypeError, ValueError):
            continue
        if index not in valid_indices or index in seen:
            continue
        # Curation is AI-owned, but the UI must not render two cards for the
        # same exact event key merely because two publishers covered it.
        event_key = re.sub(
            r"[^a-z0-9]+",
            " ",
            str(candidates_by_index[index].get("event_key") or "").lower(),
        ).strip()
        if event_key and event_key in seen_event_keys:
            continue
        seen.add(index)
        if event_key:
            seen_event_keys.add(event_key)
        output.append(index)
        if len(output) >= 5:
            break
    return output


def _select_discussion_sources(user_request, candidates):
    """Let AI select relevant and varied discussion pages before reading."""
    import tools

    packet = {
        "current_date": datetime.now().date().isoformat(),
        "original_user_request": str(user_request),
        "candidates": [
            {
                "source_index": index,
                "title": item.get("title", ""),
                "description": str(item.get("description", ""))[:900],
                "domain": item.get("domain", ""),
                "url": item.get("url", ""),
                "published_metadata": item.get("published", ""),
            }
            for index, item in enumerate(candidates[:18], start=1)
        ],
    }
    schema = {
        "type": "object",
        "properties": {
            "selected": {
                "type": "array",
                "maxItems": 8,
                "items": {
                    "type": "object",
                    "properties": {
                        "source_index": {"type": "integer"},
                        "relevance_score": {
                            "type": "integer", "minimum": 0, "maximum": 100,
                        },
                        "source_kind": {"type": "string"},
                        "perspective_hint": {"type": "string"},
                        "reason": {"type": "string"},
                    },
                    "required": [
                        "source_index", "relevance_score", "source_kind",
                        "perspective_hint", "reason",
                    ],
                    "additionalProperties": False,
                },
            }
        },
        "required": ["selected"],
        "additionalProperties": False,
    }
    try:
        raw = tools.run_ai_prompt(
            "prompts/casper_discussion_select.txt",
            json.dumps(packet, ensure_ascii=False, separators=(",", ":")),
            expect_json=True,
            num_ctx=8192,
            num_predict=1300,
            think=False,
            model_name="gemma4:12b",
            json_schema=schema,
        )
    except Exception as error:
        print("[CASPER DISCUSSION SELECT ERROR]", repr(error))
        return None
    selected = raw.get("selected") if isinstance(raw, dict) else None
    if not isinstance(selected, list):
        return None
    allowed_kinds = {
        "FORUM_THREAD", "QA_THREAD", "SOCIAL_POST", "COMMENTARY",
        "BACKGROUND", "OTHER",
    }
    output = []
    seen = set()
    for value in selected:
        if not isinstance(value, dict):
            continue
        try:
            index = int(value.get("source_index"))
            score = int(value.get("relevance_score", 0))
        except (TypeError, ValueError):
            continue
        if index < 1 or index > len(packet["candidates"]) or index in seen:
            continue
        kind = str(value.get("source_kind") or "OTHER").upper().strip()
        if kind not in allowed_kinds:
            kind = "OTHER"
        item = dict(candidates[index - 1])
        item.update(
            {
                "discussion_source_kind": kind,
                "discussion_relevance_score": max(0, min(100, score)),
                "discussion_perspective_hint": str(
                    value.get("perspective_hint") or ""
                ).strip()[:300],
                "discussion_selection_reason": str(
                    value.get("reason") or ""
                ).strip()[:400],
            }
        )
        output.append(item)
        seen.add(index)
        if len(output) >= 6:
            break
    return output


_DISCUSSION_EXTRACT_BATCH_SIZE = 2


def _recover_complete_discussion_payload(raw_output):
    """Keep only fully closed item objects from a truncated items array."""

    candidate = str(raw_output or "").strip()
    if candidate.startswith("```"):
        first_newline = candidate.find("\n")
        if first_newline >= 0:
            candidate = candidate[first_newline + 1:]
    marker = re.search(r'"items"\s*:\s*\[', candidate)
    if marker is None:
        return None
    cursor = marker.end()
    decoder = json.JSONDecoder()
    recovered = []
    while cursor < len(candidate):
        while cursor < len(candidate) and (
            candidate[cursor].isspace() or candidate[cursor] == ","
        ):
            cursor += 1
        if cursor >= len(candidate) or candidate[cursor] == "]":
            break
        if candidate[cursor] != "{":
            break
        try:
            value, end = decoder.raw_decode(candidate, cursor)
        except json.JSONDecodeError:
            break
        if not isinstance(value, dict):
            break
        recovered.append(value)
        cursor = end
    if not recovered:
        return None
    print(
        "[CASPER DISCUSSION EXTRACT PARTIAL RECOVERY]",
        "complete_items=" + str(len(recovered)),
    )
    return {
        "items": recovered,
        "_partial_json_recovery": True,
    }


def _discussion_extract_schema(expected_indices):
    expected_indices = [int(value) for value in expected_indices]
    schema = {
        "type": "object",
        "properties": {
            "items": {
                "type": "array",
                "maxItems": len(expected_indices),
                "items": {
                    "type": "object",
                    "properties": {
                        "index": {
                            "type": "integer",
                            "enum": expected_indices,
                        },
                        "is_relevant": {"type": "boolean"},
                        "source_kind": {"type": "string"},
                        "discussion_title": {"type": "string"},
                        "summary": {"type": "string"},
                        "claims": {
                            "type": "array",
                            "items": {"type": "string"},
                            "maxItems": 3,
                        },
                        "evidence_quote": {"type": "string"},
                        "stance": {"type": "string"},
                        "perspective_key": {"type": "string"},
                        "published_at": {"type": "string"},
                        "uncertainty": {"type": "string"},
                        "relevance_score": {
                            "type": "integer", "minimum": 0, "maximum": 100,
                        },
                        "reason": {"type": "string"},
                    },
                    "required": [
                        "index", "is_relevant", "source_kind",
                        "discussion_title", "summary", "claims",
                        "evidence_quote", "stance", "perspective_key",
                        "published_at", "uncertainty", "relevance_score",
                        "reason",
                    ],
                    "additionalProperties": False,
                },
            }
        },
        "required": ["items"],
        "additionalProperties": False,
    }
    return schema


def _extract_discussion_batch(
    user_request,
    indexed_sources,
    *,
    compact=False,
):
    """Extract one small source batch; malformed siblings cannot erase it."""
    import tools

    description_limit = 700 if compact else 1000
    content_limit = 1200 if compact else 2000
    packet = {
        "current_date": datetime.now().date().isoformat(),
        "original_user_request": str(user_request),
        "sources": [
            {
                "index": index,
                "search_title": item.get("title", ""),
                "search_description": str(
                    item.get("description", "")
                )[:description_limit],
                "domain": item.get("domain", ""),
                "url": item.get("url", ""),
                "published_metadata": item.get("published", ""),
                "selected_source_kind": item.get(
                    "discussion_source_kind", "OTHER"
                ),
                "page_success": item.get("page_success") is True,
                "page_content": str(
                    item.get("page_content", "")
                )[:content_limit],
            }
            for index, item in indexed_sources
        ],
    }
    expected_indices = [index for index, _item in indexed_sources]
    schema = _discussion_extract_schema(expected_indices)
    try:
        raw = tools.run_ai_prompt(
            "prompts/casper_discussion_extract.txt",
            json.dumps(packet, ensure_ascii=False, separators=(",", ":")),
            expect_json=True,
            num_ctx=8192,
            num_predict=(1100 if compact else 1800),
            think=False,
            model_name="gemma4:12b",
            json_schema=schema,
            invalid_json_handler=_recover_complete_discussion_payload,
        )
    except Exception as error:
        print(
            "[CASPER DISCUSSION EXTRACT BATCH ERROR]",
            "indices=" + repr(expected_indices),
            repr(error),
        )
        return []
    if isinstance(raw, dict) and raw.get("_partial_json_recovery") is True:
        print(
            "[CASPER DISCUSSION EXTRACT BATCH PARTIAL]",
            "indices=" + repr(expected_indices),
        )
    values = raw.get("items") if isinstance(raw, dict) else None
    if not isinstance(values, list):
        return []
    return [value for value in values if isinstance(value, dict)]


def _extract_discussion_sources(user_request, sources):
    """Extract attributed viewpoints in isolated, truncation-safe batches."""

    indexed_sources = list(enumerate(sources[:6], start=1))
    values = []
    for offset in range(0, len(indexed_sources), _DISCUSSION_EXTRACT_BATCH_SIZE):
        batch = indexed_sources[
            offset:offset + _DISCUSSION_EXTRACT_BATCH_SIZE
        ]
        batch_values = _extract_discussion_batch(user_request, batch)
        expected = {index for index, _item in batch}
        completed = set()
        for value in batch_values:
            try:
                index = int(value.get("index"))
            except (TypeError, ValueError):
                continue
            if index in expected:
                values.append(value)
                completed.add(index)
        missing = sorted(expected - completed)
        if missing:
            print(
                "[CASPER DISCUSSION EXTRACT RETRY]",
                "indices=" + repr(missing),
            )
        by_index = {index: item for index, item in batch}
        for index in missing:
            retry_values = _extract_discussion_batch(
                user_request,
                [(index, by_index[index])],
                compact=True,
            )
            retry_value = next(
                (
                    value for value in retry_values
                    if str(value.get("index") or "") == str(index)
                ),
                None,
            )
            if retry_value is not None:
                values.append(retry_value)
            else:
                print(
                    "[CASPER DISCUSSION SOURCE OMITTED]",
                    "index=" + str(index),
                    "reason=extract_failed",
                )

    allowed_kinds = {
        "FORUM_THREAD", "QA_THREAD", "SOCIAL_POST", "COMMENTARY",
        "BACKGROUND", "OTHER",
    }
    allowed_stances = {
        "SUPPORTS_PREMISE", "DISPUTES_PREMISE", "EXPLAINS_CONTEXT",
        "MIXED", "UNCLEAR",
    }
    output = []
    seen = set()
    sources_by_index = dict(indexed_sources)
    for value in values:
        if not isinstance(value, dict):
            continue
        try:
            index = int(value.get("index"))
            score = int(value.get("relevance_score", 0))
        except (TypeError, ValueError):
            continue
        if index not in sources_by_index or index in seen:
            continue
        source = sources_by_index[index]
        summary = str(value.get("summary") or "").strip()[:900]
        if value.get("is_relevant") is not True or score < 50 or not summary:
            seen.add(index)
            continue
        kind = str(value.get("source_kind") or "OTHER").upper().strip()
        if kind not in allowed_kinds:
            kind = "OTHER"
        stance = str(value.get("stance") or "UNCLEAR").upper().strip()
        if stance not in allowed_stances:
            stance = "UNCLEAR"
        claims = [
            str(claim).strip()[:320]
            for claim in value.get("claims", [])[:3]
            if str(claim).strip()
        ] if isinstance(value.get("claims"), list) else []
        uncertainty = str(value.get("uncertainty") or "").strip()[:500]
        evidence_level = (
            "opened_page" if source.get("page_success") is True
            else "search_snippet"
        )
        if evidence_level == "search_snippet" and not uncertainty:
            uncertainty = "只读取到搜索摘要，未能打开完整页面。"
        output.append(
            {
                "source_index": index,
                "source_title": str(source.get("title") or "").strip()[:300],
                "domain": str(source.get("domain") or "").strip()[:160],
                "url": str(source.get("url") or "").strip()[:2048],
                "published_at": str(
                    value.get("published_at") or source.get("published") or ""
                ).strip()[:160],
                "source_kind": kind,
                "summary": summary,
                "claims": claims,
                "evidence_quote": str(
                    value.get("evidence_quote") or ""
                ).strip()[:240],
                "stance": stance,
                "perspective_key": str(
                    value.get("perspective_key") or ""
                ).strip()[:160],
                "uncertainty": uncertainty,
                "relevance_score": max(0, min(100, score)),
                "reason": str(value.get("reason") or "").strip()[:400],
                "evidence_level": evidence_level,
                "image_url": str(source.get("image_url") or "").strip()[:2048],
            }
        )
        seen.add(index)
    output.sort(key=lambda item: -item["relevance_score"])
    return output


def _synthesize_discussion_feed(user_request, items):
    """Return a grounded Markdown roundup without performing a claim vote."""
    import tools

    packet = {
        "original_user_request": str(user_request),
        "required_narrative_language": (
            "Chinese"
            if re.search(r"[\u3400-\u9fff]", str(user_request or ""))
            else "the same language as the user request"
        ),
        "discussion_sources": [
            {
                key: item.get(key)
                for key in (
                    "source_index", "source_title", "domain", "published_at",
                    "source_kind", "summary", "claims", "evidence_quote",
                    "stance", "perspective_key", "uncertainty",
                    "relevance_score", "evidence_level",
                )
            }
            for item in items[:6]
        ],
    }
    schema = {
        "type": "object",
        "properties": {
            "answer": {"type": "string"},
            "themes": {
                "type": "array",
                "maxItems": 5,
                "items": {
                    "type": "object",
                    "properties": {
                        "label": {"type": "string"},
                        "summary": {"type": "string"},
                        "source_indices": {
                            "type": "array",
                            "items": {"type": "integer"},
                        },
                        "agreement": {"type": "string"},
                    },
                    "required": [
                        "label", "summary", "source_indices", "agreement",
                    ],
                    "additionalProperties": False,
                },
            },
            "limitations": {
                "type": "array",
                "items": {"type": "string"},
                "maxItems": 4,
            },
            "confidence": {"type": "string"},
        },
        "required": ["answer", "themes", "limitations", "confidence"],
        "additionalProperties": False,
    }
    try:
        raw = tools.run_ai_prompt(
            "prompts/casper_discussion_synthesis.txt",
            json.dumps(packet, ensure_ascii=False, separators=(",", ":")),
            expect_json=True,
            num_ctx=8192,
            num_predict=1700,
            think=False,
            model_name="gemma4:12b",
            json_schema=schema,
        )
    except Exception as error:
        print("[CASPER DISCUSSION SYNTHESIS ERROR]", repr(error))
        raw = None
    chinese = bool(re.search(r"[\u3400-\u9fff]", str(user_request or "")))
    answer = str((raw or {}).get("answer") or "").strip()[:2400]
    if not answer:
        answer = (
            "这次读取到的讨论来源没有形成可安全呈现的跨来源总结。"
            if chinese else
            "The readable discussion sources did not yield a safe cross-source summary."
        )
    valid_indices = {int(item.get("source_index")) for item in items}
    allowed_agreement = {
        "REPEATED", "SINGLE_SOURCE", "DISPUTED", "CONTEXT_ONLY",
    }
    themes = []
    for value in (raw or {}).get("themes", [])[:5]:
        if not isinstance(value, dict):
            continue
        label = str(value.get("label") or "").strip()[:120]
        summary = str(value.get("summary") or "").strip()[:600]
        indices = []
        for raw_index in value.get("source_indices", []):
            try:
                index = int(raw_index)
            except (TypeError, ValueError):
                continue
            if index in valid_indices and index not in indices:
                indices.append(index)
        agreement = str(value.get("agreement") or "").upper().strip()
        if agreement not in allowed_agreement:
            agreement = "SINGLE_SOURCE" if len(indices) < 2 else "REPEATED"
        if agreement == "REPEATED" and len(indices) < 2:
            agreement = "SINGLE_SOURCE"
        if label and summary and indices:
            themes.append((label, summary, indices, agreement))
    limitations = [
        str(value).strip()[:400]
        for value in (raw or {}).get("limitations", [])[:4]
        if str(value).strip()
    ]
    if len(items) < 2 and not any(
        ("少于" in value or "fewer" in value.casefold() or "sample" in value.casefold())
        for value in limitations
    ):
        limitations.append(
            "可读且相关的来源少于 2 个，不能形成可靠的跨来源结论。"
            if chinese else
            "Fewer than two relevant readable sources were available, so no reliable cross-source conclusion is possible."
        )
    lines = [answer]
    if themes:
        lines.extend(["", "主要说法：" if chinese else "Main themes:"])
        labels = {
            "REPEATED": "多个来源重复出现",
            "SINGLE_SOURCE": "仅单一来源",
            "DISPUTED": "来源之间有分歧",
            "CONTEXT_ONLY": "背景信息",
        }
        for label, summary, _indices, agreement in themes:
            suffix = labels.get(agreement, agreement) if chinese else agreement.replace("_", " ").title()
            lines.append("- **" + label + "**：" + summary + "（" + suffix + "）")
    if limitations:
        lines.extend(["", "需要注意：" if chinese else "Limitations:"])
        lines.extend("- " + value for value in limitations)
    return "\n".join(lines).strip()


def _normalized_media_watch_plan(value, user_request=""):
    """Validate a new or persisted watch plan before it reaches web search."""

    import media_watch

    raw = value if isinstance(value, dict) else {}
    topic = re.sub(r"\s+", " ", str(raw.get("topic") or "")).strip()[:180]
    requested_sites = []
    for site in raw.get("requested_sites", []):
        normalized = media_watch.normalize_site(site)
        if normalized and normalized not in requested_sites:
            requested_sites.append(normalized)
    requested_sites = requested_sites[:4]
    selection_mode = str(raw.get("selection_mode") or "EXACT").upper().strip()
    if selection_mode not in {"EXACT", "RANDOM_ONE"}:
        selection_mode = media_watch.selection_mode(user_request)
    content_kind = str(raw.get("content_kind") or "VIDEO").upper().strip()
    if content_kind not in {
        "SERIES", "MOVIE", "EPISODE", "LIVE", "VIDEO", "CATEGORY",
    }:
        content_kind = "CATEGORY" if selection_mode == "RANDOM_ONE" else "VIDEO"
    if not topic:
        topic = media_watch.fallback_topic(
            user_request,
            requested_sites=requested_sites,
        )
    return {
        "topic": topic,
        "selection_mode": selection_mode,
        "content_kind": content_kind,
        "episode_hint": str(raw.get("episode_hint") or "").strip()[:100] or None,
        "requested_sites": requested_sites,
        "site_scope_explicit": bool(requested_sites),
    }


def _media_watch_queries(plan):
    """Build bounded discovery queries without weakening a requested site."""

    import media_watch

    topic = str(plan.get("topic") or "视频").strip()
    sites = list(plan.get("requested_sites") or [])
    explicit = bool(sites)
    if not sites:
        sites = list(media_watch.DEFAULT_WATCH_SITES)
    queries = []
    for site in sites:
        search_site = site
        if site == "bilibili.com":
            search_site = "bilibili.com/video"
        elif site == "youtube.com":
            search_site = "youtube.com/watch"
        suffix = "" if plan.get("selection_mode") == "RANDOM_ONE" else " watch"
        queries.append(("site:" + search_site + " " + topic + suffix).strip()[:260])
    if not explicit:
        queries.append((topic + " official streaming watch").strip()[:260])
    return list(dict.fromkeys(queries))[:4]


def _media_watch_topic_tokens(topic):
    text = re.sub(r"\s+", " ", str(topic or "")).casefold().strip()
    tokens = []
    if len(text) >= 2:
        tokens.append(text)
    tokens.extend(
        value for value in re.findall(r"[a-z0-9][a-z0-9_-]+", text)
        if len(value) >= 2
    )
    tokens.extend(
        value for value in re.findall(r"[\u3400-\u9fff]{2,}", text)
        if len(value) >= 2
    )
    # Native search results often omit the generic media noun while keeping
    # the user's actual subject (for example ``下饭视频`` -> ``下饭``).  Keep
    # that bounded subject token so a relevant native card does not require an
    # unnatural exact-title echo.  This is deliberately suffix-only; it does
    # not turn arbitrary Chinese text into permissive bigrams.
    for suffix in ("短视频", "纪录片", "电视剧", "动画片", "视频", "影片", "节目"):
        if text.endswith(suffix):
            subject = text[:-len(suffix)].strip()
            if len(subject) >= 2:
                tokens.append(subject)
            break
    return list(dict.fromkeys(tokens))[:12]


def _score_media_watch_candidate(candidate, plan):
    """Return a relevance score or ``None`` for an off-contract result."""

    import media_watch
    import social_video

    url = str(candidate.get("url") or "").strip()
    domain = str(candidate.get("domain") or "").casefold().removeprefix("www.")
    title_for_log = re.sub(
        r"\s+", " ", str(candidate.get("title") or "")
    ).strip()[:120]

    def reject(reason):
        print(
            "[MEDIA WATCH CANDIDATE REJECTED]",
            "reason=" + str(reason),
            "domain=" + (domain or "unknown"),
            "title=" + repr(title_for_log),
        )
        return None

    requested_sites = plan.get("requested_sites") or []
    allowed_sites = requested_sites or list(media_watch.ALLOWED_WATCH_SITES)
    if not any(media_watch.domain_matches_site(domain, site) for site in allowed_sites):
        return reject("site_mismatch")
    combined = re.sub(
        r"\s+",
        " ",
        (str(candidate.get("title") or "") + " " + str(candidate.get("description") or "")),
    ).casefold()
    tokens = _media_watch_topic_tokens(plan.get("topic"))
    hits = [token for token in tokens if token and token in combined]
    if tokens and not hits:
        return reject("topic_miss")
    exact_topic = str(plan.get("topic") or "").casefold().strip()
    candidate_title = re.sub(
        r"\s+", " ", str(candidate.get("title") or "")
    ).casefold().strip()
    if exact_topic and candidate_title == exact_topic:
        score = 90
    elif exact_topic and exact_topic in combined:
        score = 60
    else:
        score = min(42, len(hits) * 14)
    contract = social_video.social_video_contract(url)
    if contract is not None:
        score += 30
    if any(marker in combined for marker in ("官方", "official", "正版")):
        score += 14
    if requested_sites:
        for index, site in enumerate(requested_sites):
            if media_watch.domain_matches_site(domain, site):
                score += max(0, 8 - index * 2)
                break
    derivative_markers = (
        "解说", "reaction", "剪辑", "盘点", "预告", "trailer", "review",
        "解读", "片段", "clip", "shorts",
    )
    if plan.get("selection_mode") == "EXACT" and not any(
        marker in exact_topic for marker in derivative_markers
    ) and any(marker in combined for marker in derivative_markers):
        # A request for the work itself must fail closed instead of silently
        # replacing it with commentary, clips, trailers, Shorts, or reactions.
        return reject("derived_content")
    if score < 25:
        return reject("score_below_threshold")
    enriched = dict(candidate)
    enriched["watch_score"] = score
    enriched["inline_playable"] = contract is not None
    enriched["video_contract"] = contract
    return enriched


def _media_watch_thumbnail(candidate):
    """Use deterministic YouTube artwork; do not invent an image for other sites."""

    contract = candidate.get("video_contract")
    if isinstance(contract, dict) and contract.get("platform") == "youtube":
        video_id = str(contract.get("video_id") or "")
        if video_id:
            return "https://i.ytimg.com/vi/" + video_id + "/hqdefault.jpg"
    return str(candidate.get("image_url") or "").strip()


def _native_media_watch_candidate(item, platform):
    """Convert one rendered native video card into the watch-search contract."""

    if not isinstance(item, dict):
        return None
    url = str(item.get("url") or "").strip()
    try:
        domain = str(urlparse(url).hostname or "").casefold().removeprefix("www.")
    except ValueError:
        return None
    visible_text = re.sub(
        r"\s+", " ", str(item.get("visible_text") or "")
    ).strip()[:1200]
    title = re.sub(
        r"\s+",
        " ",
        str(item.get("title") or item.get("image_alt") or ""),
    ).strip()[:300]
    if not title:
        title = visible_text[:220]
    if not url or not domain or not title:
        return None
    description = re.sub(
        r"\s+",
        " ",
        str(item.get("description") or visible_text),
    ).strip()[:700]
    return {
        "title": title,
        "description": description,
        "url": url,
        "domain": domain,
        "image_url": str(item.get("image_url") or "").strip(),
        "author": re.sub(
            r"\s+", " ", str(item.get("author") or "")
        ).strip()[:160],
        "published": str(item.get("published") or "").strip()[:80],
        "discovery_engine": platform + "_native",
    }


_VIDEO_SITE_DETAIL_PATH = re.compile(
    r"/(?:play|watch|video|videos|episode|episodes|movie|movies|show|shows)/?",
    re.IGNORECASE,
)
_VIDEO_SITE_TAXONOMY = (
    "视频", "影视", "电影", "电视剧", "动漫", "动画", "综艺", "纪录片",
    "短剧", "剧集", "立即播放", "movies", "videos", "episodes", "shows",
    "anime", "watch now", "tv series",
)


def _video_site_surface_evidence(domain, body_text, links, media_element_count=0):
    """Classify a site from repeatable video-catalog structure, not user wording."""

    import media_watch

    normalized = media_watch.normalize_site(domain)
    detail_urls = set()
    for item in links if isinstance(links, list) else []:
        url = str((item or {}).get("url") or "").strip()
        try:
            parsed = urlparse(url)
        except ValueError:
            continue
        host = media_watch.normalize_site(parsed.hostname)
        if (
            host
            and media_watch.domain_matches_site(host, normalized)
            and _VIDEO_SITE_DETAIL_PATH.search(parsed.path or "")
        ):
            detail_urls.add(url)
    folded = re.sub(r"\s+", " ", str(body_text or "")).casefold()
    taxonomy_hits = sum(
        1 for marker in _VIDEO_SITE_TAXONOMY if marker.casefold() in folded
    )
    detail_count = len(detail_urls)
    try:
        media_count = max(0, int(media_element_count or 0))
    except (TypeError, ValueError, OverflowError):
        media_count = 0
    verified = bool(
        (detail_count >= 6 and taxonomy_hits >= 2)
        or (detail_count >= 3 and taxonomy_hits >= 1 and media_count >= 1)
    )
    return {
        "verified": verified,
        "detail_link_count": detail_count,
        "taxonomy_hit_count": taxonomy_hits,
        "media_element_count": media_count,
    }


def _video_site_links(page, domain, maximum=600):
    """Read bounded same-site anchors, retaining the best label per URL."""

    import media_watch

    raw_items = page.locator("a[href]").evaluate_all(
        """nodes => nodes.slice(0, 1200).map(node => {
          const image = node.querySelector("img");
          const heading = node.querySelector("h1,h2,h3,h4,h5,h6");
          return {
            url: node.href || "",
            text: (heading?.textContent || node.textContent || node.getAttribute("aria-label") || image?.alt || "").trim(),
            image_url: image?.currentSrc || image?.src || "",
            has_heading: Boolean(heading)
          };
        })"""
    )
    by_url = {}
    order = []
    for item in raw_items if isinstance(raw_items, list) else []:
        url = str((item or {}).get("url") or "").strip()
        try:
            parsed = urlparse(url)
        except ValueError:
            continue
        host = media_watch.normalize_site(parsed.hostname)
        if not host or not media_watch.domain_matches_site(host, domain):
            continue
        text_value = re.sub(
            r"\s+", " ", str((item or {}).get("text") or "")
        ).strip()[:300]
        if not url:
            continue
        current = {
            "url": url,
            "text": text_value,
            "image_url": str((item or {}).get("image_url") or "").strip()[:2048],
            "has_heading": bool((item or {}).get("has_heading")),
        }
        previous = by_url.get(url)
        if previous is None:
            by_url[url] = current
            order.append(url)
            continue
        if (
            _video_site_link_text_quality(
                current["text"], current["has_heading"]
            )
            > _video_site_link_text_quality(
                previous.get("text"), previous.get("has_heading")
            )
        ):
            if not current["image_url"]:
                current["image_url"] = previous.get("image_url", "")
            by_url[url] = current
        elif not previous.get("image_url") and current["image_url"]:
            previous["image_url"] = current["image_url"]
    limit = max(1, min(int(maximum), 800))
    return [by_url[url] for url in order[:limit]]


_VIDEO_SITE_GENERIC_LABELS = {
    "立即播放", "播放", "观看", "详情", "查看更多", "更多",
    "play", "watch", "watch now", "details", "more",
}


def _video_site_link_text_quality(text, has_heading=False):
    """Rank a catalog label without treating buttons or glyphs as titles."""

    value = re.sub(r"\s+", " ", str(text or "")).strip()
    if not value or not any(character.isalnum() for character in value):
        return -1000
    if re.fullmatch(r"[\d\s:./+\-]+", value):
        return -900
    folded = value.casefold()
    score = min(len(value), 120)
    if bool(has_heading):
        score += 200
    if folded in _VIDEO_SITE_GENERIC_LABELS:
        score -= 500
    elif any(folded.startswith(label + " ") for label in _VIDEO_SITE_GENERIC_LABELS):
        score -= 120
    if re.search(r"[\u3400-\u9fff]", value):
        score += 20
    return score


def _video_site_search_template(current_url, topic, domain):
    """Generalize only an observed same-site search URL."""

    import media_watch

    value = str(current_url or "").strip()
    try:
        parsed = urlparse(value)
    except ValueError:
        return ""
    host = media_watch.normalize_site(parsed.hostname)
    if not host or not media_watch.domain_matches_site(host, domain):
        return ""
    variants = (quote(str(topic), safe=""), quote_plus(str(topic)), str(topic))
    for variant in variants:
        if variant and variant in value:
            return value.replace(variant, "{query}", 1)[:2000]
    return ""


def _video_site_aliases(page_title, domain):
    title = re.sub(r"\s+", " ", str(page_title or "")).strip()
    aliases = [str(domain).split(".", 1)[0]]
    if title:
        label = re.split(r"\s*[-|｜—_]\s*", title, maxsplit=1)[0].strip()
        if 2 <= len(label) <= 40 and not label.casefold().startswith("search"):
            aliases.append(label)
    return aliases


def _video_site_candidates(links, domain):
    """Keep one meaningful, title-like candidate per catalog detail URL."""

    by_url = {}
    order = []
    for item in links if isinstance(links, list) else []:
        url = str((item or {}).get("url") or "").strip()
        text_value = re.sub(
            r"\s+", " ", str((item or {}).get("text") or "")
        ).strip()[:300]
        try:
            path = urlparse(url).path
        except ValueError:
            continue
        if not _VIDEO_SITE_DETAIL_PATH.search(path or ""):
            continue
        if (
            not text_value
            or not any(character.isalnum() for character in text_value)
            or re.fullmatch(r"[\d\s:./+\-]+", text_value)
            or text_value.casefold() in _VIDEO_SITE_GENERIC_LABELS
        ):
            continue
        canonical = url.split("?", 1)[0]
        candidate = {
            "title": text_value,
            "description": text_value,
            "url": canonical,
            "domain": domain,
            "image_url": str((item or {}).get("image_url") or "").strip(),
            "author": "",
            "published": "",
            "discovery_engine": domain + "_native",
            "_label_quality": _video_site_link_text_quality(
                text_value, (item or {}).get("has_heading")
            ),
        }
        previous = by_url.get(canonical)
        if previous is None:
            by_url[canonical] = candidate
            order.append(canonical)
        elif candidate["_label_quality"] > previous["_label_quality"]:
            if not candidate["image_url"]:
                candidate["image_url"] = previous.get("image_url", "")
            by_url[canonical] = candidate
        elif not previous.get("image_url") and candidate["image_url"]:
            previous["image_url"] = candidate["image_url"]
    results = []
    for canonical in order:
        candidate = by_url[canonical]
        candidate.pop("_label_quality", None)
        results.append(candidate)
    return results[:80]


def _discover_verified_video_site(plan, site, status_callback=None):
    """Verify an unfamiliar public site, learn its search, and read its catalog."""

    from playwright.sync_api import Error as PlaywrightError
    from playwright.sync_api import TimeoutError, sync_playwright

    import media_watch
    import video_sites

    domain = media_watch.normalize_site(site)
    if not domain:
        return [], []
    ensure_browser()
    query_log = [domain + "_native:" + str(plan.get("topic") or "视频")]
    with sync_playwright() as playwright:
        browser = playwright.chromium.connect_over_cdp(CDP_URL)
        if not browser.contexts:
            raise RuntimeError("Casper Browser has no usable context.")
        page = browser.contexts[0].new_page()
        try:
            entry = video_sites.get_site(domain)
            template = str((entry or {}).get("search_url_template") or "")
            topic = str(plan.get("topic") or "视频").strip()[:180]
            if template:
                target = template.replace("{query}", quote(topic, safe=""))
            else:
                target = "https://" + domain + "/"
            try:
                page.goto(target, wait_until="domcontentloaded", timeout=20000)
            except (TimeoutError, PlaywrightError) as error:
                print("[MEDIA WATCH SITE NAVIGATION]", domain, repr(error))
            page.wait_for_timeout(1000)
            body = page.locator("body").inner_text(timeout=10000)
            protected = _protected_event(body)
            if protected:
                return [], query_log
            opened_host = media_watch.normalize_site(urlparse(page.url).hostname)
            if not media_watch.domain_matches_site(opened_host, domain):
                print("[MEDIA WATCH SITE REJECTED]", "domain=" + domain, "reason=redirect")
                return [], query_log
            links = _video_site_links(page, domain)
            if not entry or not entry.get("verified"):
                media_count = page.locator("video, audio").count()
                evidence = _video_site_surface_evidence(
                    domain,
                    body,
                    links,
                    media_element_count=media_count,
                )
                if not evidence["verified"]:
                    print(
                        "[MEDIA WATCH SITE REJECTED]",
                        "domain=" + domain,
                        "detail_links=" + str(evidence["detail_link_count"]),
                        "taxonomy=" + str(evidence["taxonomy_hit_count"]),
                        "media=" + str(evidence["media_element_count"]),
                    )
                    return [], query_log
                aliases = _video_site_aliases(page.title(), domain)
            else:
                evidence = dict(entry.get("evidence") or {})
                aliases = list(entry.get("aliases") or [])

            if not template:
                search_box = page.locator(
                    'input[type="search"], input[placeholder*="搜索"], '
                    'input[placeholder*="Search" i], input[aria-label*="search" i]'
                )
                chosen = None
                for index in range(min(search_box.count(), 8)):
                    candidate = search_box.nth(index)
                    if candidate.is_visible():
                        chosen = candidate
                        break
                if chosen is not None:
                    chosen.fill(topic)
                    chosen.press("Enter")
                    page.wait_for_timeout(1400)
                    template = _video_site_search_template(page.url, topic, domain)
                    body = page.locator("body").inner_text(timeout=10000)
                    links = _video_site_links(page, domain)

            if not entry or not entry.get("verified") or template != str(
                (entry or {}).get("search_url_template") or ""
            ):
                stored = video_sites.record_verified_site(
                    domain,
                    evidence,
                    aliases=aliases,
                    search_url_template=template,
                )
                print(
                    "[MEDIA WATCH SITE VERIFIED]",
                    "domain=" + domain,
                    "detail_links=" + str(evidence.get("detail_link_count") or 0),
                    "taxonomy=" + str(evidence.get("taxonomy_hit_count") or 0),
                    "search=" + str(bool(stored.get("search_url_template"))).lower(),
                )
            candidates = _video_site_candidates(links, domain)
            print(
                "[MEDIA WATCH SITE NATIVE]",
                "domain=" + domain,
                "candidates=" + str(len(candidates)),
            )
            return candidates, query_log
        finally:
            page.close()


def _discover_native_media_watch(plan, status_callback=None):
    """Discover Bilibili/YouTube cards on their own rendered search pages."""

    import media_watch
    import social_browser

    requested_sites = list(plan.get("requested_sites") or [])
    sites = requested_sites or list(media_watch.DEFAULT_WATCH_SITES)
    native_routes = []
    if any(media_watch.domain_matches_site("bilibili.com", site) for site in sites):
        native_routes.append(("bilibili", "B 站"))
    if any(media_watch.domain_matches_site("youtube.com", site) for site in sites):
        native_routes.append(("youtube", "YouTube"))
    generic_sites = [
        site
        for site in requested_sites
        if not media_watch.domain_matches_site("bilibili.com", site)
        and not media_watch.domain_matches_site("youtube.com", site)
    ]
    if not native_routes and not generic_sites:
        return [], []

    topic = str(plan.get("topic") or "视频").strip()[:180]
    candidates = []
    query_log = []
    for platform, label in native_routes:
        _status(status_callback, "正在直接搜索 " + label + " 视频… 🎬")
        query_log.append(platform + "_native:" + topic)
        try:
            opened = social_browser.open_social_search(
                platform,
                topic,
                selection_mode="RELEVANCE",
            )
            page = social_browser.inspect_active_social_page(
                platform,
                expected_url=opened.get("url", ""),
            )
            platform_count = 0
            for item in page.get("post_candidates", []):
                converted = _native_media_watch_candidate(item, platform)
                if converted is not None:
                    candidates.append(converted)
                    platform_count += 1
            print(
                "[MEDIA WATCH NATIVE]",
                "platform=" + platform,
                "candidates=" + str(platform_count),
            )
        except Exception as error:
            # Native rendering is the preferred discovery surface, but a
            # temporary site/runtime failure still gets the bounded web-search
            # fallback below.
            print("[MEDIA WATCH NATIVE ERROR]", platform, repr(error))
        finally:
            try:
                social_browser.close_social_browser()
            except Exception as error:
                print("[MEDIA WATCH NATIVE CLOSE WARNING]", repr(error))
    for site in generic_sites:
        _status(
            status_callback,
            "正在验证并搜索 " + media_watch.site_label(site) + "… 🎬",
        )
        try:
            site_candidates, site_queries = _discover_verified_video_site(
                plan,
                site,
                status_callback=status_callback,
            )
            candidates.extend(site_candidates)
            query_log.extend(site_queries)
        except Exception as error:
            print("[MEDIA WATCH SITE NATIVE ERROR]", site, repr(error))
    return candidates, query_log


def _media_watch_card(candidate, plan):
    import media_watch

    title = re.sub(r"\s+", " ", str(candidate.get("title") or "观看候选")).strip()[:180]
    description = re.sub(
        r"\s+", " ", str(candidate.get("description") or "")
    ).strip()[:500]
    domain = str(candidate.get("domain") or "").casefold().removeprefix("www.")
    platform = next(
        (
            media_watch.site_label(site)
            for site in (plan.get("requested_sites") or media_watch.DEFAULT_WATCH_SITES)
            if media_watch.domain_matches_site(domain, site)
        ),
        domain,
    )
    playable = bool(candidate.get("inline_playable"))
    mode_text = "可在 Bekki 内播放并进入影院模式" if playable else "当前仅支持打开原网站"
    image_url = _media_watch_thumbnail(candidate)
    return {
        "type": "article",
        "title": title,
        "summary": description or ("来自 " + platform + " 的观看候选。"),
        "context_markdown": (
            "### 观看候选\n\n"
            + (description or "搜索结果提供了这个可打开的观看页面。")
            + "\n\n- **来源：** " + platform
            + "\n- **播放方式：** " + mode_text
        ),
        "url": str(candidate.get("url") or ""),
        "domain": domain,
        "image": (
            {
                "url": image_url,
                "alt": title,
                "source_url": str(candidate.get("url") or ""),
                "label": "视频封面",
                "kind": "media",
            }
            if image_url else None
        ),
        "metadata": {
            "brand": platform,
            "captured_at": datetime.now().astimezone().isoformat(),
            "link_target": "watch_page",
        },
        "sections": [
            {
                "kind": "note",
                "label": "筛选方式",
                "text": (
                    "在符合网站与主题条件的候选中随机选择"
                    if plan.get("selection_mode") == "RANDOM_ONE"
                    else "按主题相关性与可播放性选择"
                ),
            }
        ],
        "requirements": [],
    }


def media_watch_controller(
    user_request,
    status_callback=None,
    preplanned=None,
    excluded_urls=None,
    chooser=None,
):
    """Find one bounded watch candidate and prepare a theater-mode question."""

    import media_watch
    import result_cards
    import social_video
    import tools

    plan = _normalized_media_watch_plan(
        preplanned if isinstance(preplanned, dict) else tools.build_media_watch_plan(user_request),
        user_request=user_request,
    )
    excluded = {
        str(value or "").strip()
        for value in (excluded_urls or [])
        if str(value or "").strip()
    }
    _status(status_callback, "Casper 正在寻找可观看的内容… 🎬")
    candidates = []
    seen = set(excluded)
    native_items, native_queries = _discover_native_media_watch(
        plan,
        status_callback=status_callback,
    )
    for item in native_items:
        url = str(item.get("url") or "").strip()
        if not url or url in seen:
            continue
        seen.add(url)
        scored = _score_media_watch_candidate(item, plan)
        if scored is not None:
            candidates.append(scored)

    queries = list(native_queries)
    # A literal but previously unknown domain is not a video website merely
    # because the request says “go there and play”.  Its rendered catalog must
    # pass the structural verifier above before any general search result can
    # be accepted from it.  Built-in sources already have a shipped contract.
    try:
        import video_sites

        unverified_sites = [
            site
            for site in plan.get("requested_sites", [])
            if not media_watch.is_builtin_video_site(site)
            and not video_sites.is_verified(site)
        ]
    except (ImportError, OSError, ValueError):
        unverified_sites = [
            site
            for site in plan.get("requested_sites", [])
            if not media_watch.is_builtin_video_site(site)
        ]
    if unverified_sites:
        site_text = "、".join(media_watch.site_label(site) for site in unverified_sites)
        print(
            "[MEDIA WATCH SITE UNVERIFIED]",
            "sites=" + ",".join(unverified_sites),
        )
        return {
            "status": "UNVERIFIED_VIDEO_SITE",
            "query": " | ".join(queries),
            "queries": queries,
            "plan": plan,
            "results": [],
            "cards": [],
            "direct_reply": (
                "我检查了 " + site_text + "，但页面没有呈现足够且可重复的视频目录、"
                "播放详情页或剧集结构，所以没有把它登记为视频网站，也不会用普通"
                "网页搜索结果冒充可观看内容。你可以换一个网站，或提供该站的具体"
                "视频页面让我再核对。"
            ),
        }
    if not candidates:
        web_queries = _media_watch_queries(plan)
        queries.extend(web_queries)
        for query in web_queries:
            discovery = discover_web(query, count=7, status_callback=status_callback)
            if discovery.get("status") == "HUMAN_HANDOFF":
                return {
                    "status": "HUMAN_HANDOFF",
                    "query": " | ".join(queries),
                    "plan": plan,
                    "pending_approval": {
                        "event": discovery.get("event", "captcha"),
                        "reason": "Background browser requires human control.",
                    },
                    "results": [],
                    "cards": [],
                }
            for item in discovery.get("results", []):
                url = str(item.get("url") or "").strip()
                if not url or url in seen:
                    continue
                seen.add(url)
                scored = _score_media_watch_candidate(item, plan)
                if scored is not None:
                    candidates.append(scored)
    candidates.sort(key=lambda item: item.get("watch_score", 0), reverse=True)
    if not candidates:
        site_text = "、".join(
            media_watch.site_label(site) for site in plan.get("requested_sites", [])
        ) or "已支持的观看网站"
        return {
            "status": "NO_WATCH_RESULT",
            "query": " | ".join(queries),
            "queries": queries,
            "plan": plan,
            "results": [],
            "cards": [],
            "direct_reply": (
                "这次没有在 " + site_text + " 找到同时符合主题与页面条件的可靠观看结果。"
                "我没有用解说、剪辑或无关视频补位；你可以换一个关键词或指定其他网站。"
            ),
        }
    if plan.get("selection_mode") == "RANDOM_ONE":
        pool = candidates[: min(5, len(candidates))]
        selected = (chooser or secrets.choice)(pool)
    else:
        selected = candidates[0]
    card_list = result_cards.clean_cards([_media_watch_card(selected, plan)])
    if not card_list:
        return {
            "status": "NO_WATCH_RESULT",
            "query": " | ".join(queries),
            "queries": queries,
            "plan": plan,
            "results": [],
            "cards": [],
            "direct_reply": "找到了候选页面，但它没有通过 Bekki 的安全卡片校验，因此没有打开。",
        }
    card = card_list[0]
    playable = social_video.social_video_contract(card.get("url")) is not None
    title = str(card.get("title") or "这个视频")
    if playable:
        direct_reply = (
            "我找到《" + title + "》了。要现在进入影院模式吗？\n\n"
            "你可以回答“可以”，也可以直接点卡片上的“影院模式”；"
            "不喜欢就说“换一个”。"
        )
        pending_action = {
            "type": "media_watch_choice",
            "original_request": str(user_request or "")[:1200],
            "approval_payload": {
                "selected_url": str(card.get("url") or ""),
                "selected_title": title,
                "selected_card": card,
                "plan": plan,
                "excluded_urls": list(excluded | {str(card.get("url") or "")})[:20],
            },
        }
    else:
        direct_reply = (
            "我找到《" + title + "》了，但这个网站目前不能在 Bekki 内嵌播放，"
            "所以不会假装可以进入影院模式。你可以用卡片打开原网站。"
        )
        pending_action = None
    result_item = dict(selected)
    result_item.update(
        {
            "summary": str(card.get("summary") or ""),
            "description": str(card.get("summary") or ""),
            "content_type": "MEDIA_WATCH",
            "image_url": _media_watch_thumbnail(selected),
        }
    )
    print(
        "[CASPER MEDIA WATCH]",
        "mode=" + str(plan.get("selection_mode")),
        "sites=" + ",".join(plan.get("requested_sites") or ["cross_site"]),
        "playable=" + str(playable).lower(),
        "candidates=" + str(len(candidates)),
    )
    return {
        "status": "OK",
        "query": " | ".join(queries),
        "queries": queries,
        "plan": plan,
        "results": [result_item],
        "cards": card_list,
        "direct_reply": direct_reply,
        "pending_action": pending_action,
        "context": (
            "melchior response mode: MEDIA_WATCH\n"
            "The selected URL obeys the user's literal site condition. Inline "
            "playability is structural and does not imply uploader authorization."
        ),
        "discovery_type": "casper_browser_media_watch",
    }


def discussion_feed_controller(queries, user_request="", status_callback=None):
    """Browser-first cross-site discussion roundup, separate from news/claims."""
    import result_cards

    if isinstance(queries, str):
        queries = [queries]
    queries = [
        str(value).strip()[:240]
        for value in queries if str(value).strip()
    ][:3]
    all_candidates = []
    seen_urls = set()
    _status(status_callback, "Casper 正在发现相关讨论页面… 🌐")
    for query in queries:
        discovery = discover_web(query, count=8, status_callback=status_callback)
        if discovery.get("status") == "HUMAN_HANDOFF":
            return {
                "status": "HUMAN_HANDOFF",
                "query": " | ".join(queries),
                "pending_approval": {
                    "event": discovery.get("event", "captcha"),
                    "reason": "Background browser requires human control.",
                },
                "results": [],
                "cards": [],
            }
        for item in discovery.get("results", []):
            url = str(item.get("url") or "").strip()
            if url and url not in seen_urls:
                seen_urls.add(url)
                all_candidates.append(item)
    if not all_candidates:
        return {
            "status": "NO_RESULTS",
            "query": " | ".join(queries),
            "queries": queries,
            "results": [],
            "cards": [],
        }

    _status(status_callback, "Casper 正在选择不同来源的讨论… 🧭")
    selected = _select_discussion_sources(user_request, all_candidates)
    if selected is None:
        print("[CASPER DISCUSSION SELECT FALLBACK]", "discovery_order")
        selected = all_candidates[:6]
    if not selected:
        return {
            "status": "NO_RELEVANT_DISCUSSION",
            "query": " | ".join(queries),
            "queries": queries,
            "results": [],
            "inspected_results": all_candidates,
            "cards": [],
        }

    _status(status_callback, "Casper 正在读取帖子与论坛页面… 📖")
    inspected = []
    for candidate in selected[:6]:
        page = read_url(candidate.get("url", ""))
        enriched = dict(candidate)
        enriched.update(
            {
                "page_success": page.get("success", False),
                "page_content": page.get("content", ""),
                "page_error": page.get("error", ""),
                "reader_type": "casper_browser",
                "image_url": page.get("image_url", "") or candidate.get("image_url", ""),
                "published": page.get("published", "") or candidate.get("published", ""),
                "protected_event": page.get("protected_event"),
            }
        )
        inspected.append(enriched)

    _status(status_callback, "Casper 正在提取各来源的说法… 🧠")
    items = _extract_discussion_sources(user_request, inspected)
    if not items:
        return {
            "status": "NO_RELEVANT_DISCUSSION",
            "query": " | ".join(queries),
            "queries": queries,
            "results": inspected,
            "inspected_results": inspected,
            "cards": [],
        }

    by_index = {
        index: item for index, item in enumerate(inspected, start=1)
    }
    results = []
    for item in items:
        source = dict(by_index[item["source_index"]])
        source.update(
            {
                "summary": item["summary"],
                "description": item["summary"],
                "content_type": "DISCUSSION",
                "is_concrete_news": False,
                "discussion_stance": item["stance"],
                "discussion_source_kind": item["source_kind"],
                "discussion_relevance_score": item["relevance_score"],
                "evidence_level": item["evidence_level"],
            }
        )
        results.append(source)

    cards = result_cards.clean_cards(
        [
            {
                "type": "article",
                "title": item["source_title"] or item["domain"] or "讨论来源",
                "summary": item["summary"],
                "context_markdown": (
                    "### 该来源的主要说法\n\n"
                    + item["summary"]
                    + (
                        "\n\n" + "\n".join("- " + claim for claim in item["claims"])
                        if item["claims"] else ""
                    )
                ),
                "url": item["url"],
                "domain": item["domain"],
                "image": (
                    {
                        "url": item["image_url"],
                        "alt": item["source_title"],
                        "source_url": item["url"],
                        "label": "来源图片",
                        "kind": "media",
                    }
                    if item["image_url"] else None
                ),
                "metadata": {
                    "published_at": item["published_at"],
                    "captured_at": datetime.now().astimezone().isoformat(),
                    "evidence_level": item["evidence_level"],
                },
                "sections": [
                    {
                        "kind": "note",
                        "label": "来源性质",
                        "text": item["source_kind"],
                    },
                    {
                        "kind": "warning",
                        "label": "证据边界",
                        "text": item["uncertainty"] or "该页面的说法不等于事实已被证实。",
                    },
                ],
                "requirements": [],
            }
            for item in items[:6]
        ]
    )
    _status(status_callback, "Casper 正在归纳共同点与分歧… 🧩")
    direct_reply = _synthesize_discussion_feed(user_request, items)
    if cards:
        direct_reply += (
            "\n\n最相关的 " + str(len(cards)) + " 个讨论来源已放在下方卡片中。"
            if re.search(r"[\u3400-\u9fff]", str(user_request or ""))
            else "\n\nThe " + str(len(cards)) + " most relevant discussion sources are shown in the cards below."
        )
    feed = [
        {
            key: item.get(key)
            for key in (
                "source_index", "source_title", "domain", "published_at",
                "source_kind", "summary", "claims", "stance",
                "perspective_key", "uncertainty", "relevance_score",
                "evidence_level",
            )
        }
        for item in items
    ]
    print(
        "[CASPER DISCUSSION FEED]",
        len(feed), "sources", len(cards), "cards",
    )
    return {
        "status": "OK",
        "query": " | ".join(queries),
        "queries": queries,
        "results": results,
        "inspected_results": inspected,
        "cards": cards,
        "feed": feed,
        "direct_reply": direct_reply,
        "context": (
            "melchior response mode: DISCUSSION_FEED\n"
            "These are attributed public discussion viewpoints, not news and "
            "not independently confirmed facts. Do not run a consensus vote or "
            "convert repeated claims into truth.\n\n"
            + json.dumps(feed, ensure_ascii=False, indent=2)
        ),
        "discovery_type": "casper_browser_discussion",
    }


def news_feed_controller(queries, user_request="", status_callback=None):
    """Browser-first ranked news feed based on rendered article evidence."""
    import result_cards
    import tools

    if isinstance(queries, str):
        queries = [queries]
    queries = [str(value).strip()[:240] for value in queries if str(value).strip()][:3]
    all_candidates = []
    seen_urls = set()
    _status(status_callback, "Casper 正在后台浏览器中发现新闻… 🌐")
    for query in queries:
        discovery = discover_web(
            query,
            count=7,
            status_callback=status_callback,
        )
        if discovery.get("status") == "HUMAN_HANDOFF":
            return {
                "status": "HUMAN_HANDOFF",
                "query": " | ".join(queries),
                "pending_approval": {
                    "event": discovery.get("event", "captcha"),
                    "reason": "Background browser requires human control.",
                },
                "results": [],
                "cards": [],
            }
        for item in discovery.get("results", []):
            url = item.get("url", "")
            if url and url not in seen_urls:
                seen_urls.add(url)
                all_candidates.append(item)
    if not all_candidates:
        return {"status": "NO_RESULTS", "query": " | ".join(queries), "results": [], "cards": []}

    _status(status_callback, "Casper 正在选择并读取具体新闻文章… 📰")
    scored = tools.score_sources(" | ".join(queries), all_candidates)[:6]
    articles = []
    for candidate in scored:
        page = read_url(candidate.get("url", ""))
        if page.get("protected_event") == "captcha":
            return {
                "status": "HUMAN_HANDOFF",
                "query": " | ".join(queries),
                "pending_approval": {
                    "event": "captcha",
                    "reason": "A news source requested human verification.",
                    "url": candidate.get("url", ""),
                },
                "results": articles,
                "cards": [],
            }
        enriched = dict(candidate)
        enriched.update(
            {
                "page_success": page.get("success", False),
                "page_content": page.get("content", ""),
                "page_error": page.get("error"),
                "image_url": page.get("image_url", ""),
                "published": page.get("published", "") or candidate.get("published", ""),
                "reader_type": "casper_browser",
            }
        )
        articles.append(enriched)

    _status(status_callback, "Casper 正在识别具体事件与发布时间… 🧠")
    decisions = _extract_news_events(user_request or " | ".join(queries), articles)
    if decisions is None:
        return {
            "status": "LIMITED_EVIDENCE",
            "query": " | ".join(queries),
            "results": articles,
            "cards": [],
            "context": "News event extraction AI did not return a complete contract.",
        }
    for index, article in enumerate(articles, start=1):
        decision = decisions.get(index)
        if decision is None:
            article.update(
                {
                    "is_concrete_news": False,
                    "content_type": "OTHER",
                    "news_score": 0,
                    "event_title": "",
                    "event_summary": "",
                    "event_date": "",
                    "event_key": "",
                    "uncertainty": "News extraction omitted this source.",
                    "classification_reason": "Missing per-source AI decision.",
                }
            )
            continue
        article.update(
            {
                "is_concrete_news": decision["is_concrete_news"],
                "content_type": decision["content_type"],
                "news_score": decision["relevance_score"],
                "event_title": decision["event_title"],
                "event_summary": decision["summary"],
                "event_date": decision["event_date"],
                "event_key": decision["event_key"],
                "uncertainty": decision["uncertainty"],
                "classification_reason": decision["reason"],
                "published": (
                    decision.get("published_at")
                    or article.get("published", "")
                ),
            }
        )

    _status(status_callback, "Casper 正在合并重复事件并排序… 📚")
    selected = _curate_news_feed(user_request or " | ".join(queries), articles)
    if not selected:
        # Curation is helpful for merging duplicates, but it is not allowed to
        # turn already validated news into an empty feed.  Keep a bounded,
        # deterministic ranking when that compact AI step returns no usable
        # selection.
        selected = [
            index
            for index, _item in sorted(
                (
                    (index, item)
                    for index, item in enumerate(articles, start=1)
                    if item.get("is_concrete_news")
                ),
                key=lambda pair: (
                    int(pair[1].get("news_score", 0) or 0),
                    int(pair[1].get("source_score", 50) or 50),
                ),
                reverse=True,
            )[:5]
        ]
    selected_set = set(selected)
    ranked = [articles[index - 1] for index in selected]
    remaining = [item for index, item in enumerate(articles, start=1) if index not in selected_set]
    results = ranked
    cards = result_cards.clean_cards(
        [
            {
                "type": "news",
                "title": item.get("event_title") or item.get("title", ""),
                "summary": item.get("event_summary", ""),
                "url": item.get("url", ""),
                "domain": item.get("domain", ""),
                "image": (
                    {
                        "url": item.get("image_url", ""),
                        "alt": item.get("event_title") or item.get("title", ""),
                        "source_url": item.get("url", ""),
                    }
                    if item.get("image_url")
                    else None
                ),
                "metadata": {
                    "published_at": item.get("published", "") or item.get("event_date", ""),
                    "captured_at": datetime.now().astimezone().isoformat(),
                },
                "requirements": [],
            }
            for item in ranked
        ]
    )
    feed = [
        {
            "title": item.get("event_title", ""),
            "summary": item.get("event_summary", ""),
            "event_date": item.get("event_date", ""),
            "published_at": item.get("published", ""),
            "domain": item.get("domain", ""),
            "url": item.get("url", ""),
            "uncertainty": item.get("uncertainty", ""),
        }
        for item in ranked
    ]
    print("[CASPER NEWS FEED]", len(feed), "events", len(cards), "cards")
    return {
        "status": "OK" if feed else "NO_CONCRETE_NEWS",
        "query": " | ".join(queries),
        "queries": queries,
        "results": results,
        "inspected_results": ranked + remaining,
        "cards": cards,
        "feed": feed,
        "context": (
            "melchior response mode: NEWS_FEED\n"
            "Casper read rendered article pages and an AI extracted, deduplicated, "
            "and ranked the concrete events below. Use only this feed as news. "
            "Preserve uncertainty labels and do not combine separate events.\n\n"
            + json.dumps(feed, ensure_ascii=False, indent=2)
        ),
        "discovery_type": "casper_browser",
    }


def _extract_shopping_products_batch(user_request, plan, region, candidates):
    """Let AI classify rendered merchant pages and extract product evidence."""
    import tools

    packet = {
        "current_date": datetime.now().date().isoformat(),
        "original_user_request": str(user_request),
        "region": region,
        "shopping_plan": plan,
        "candidates": [
            {
                "index": index,
                "search_title": item.get("title", ""),
                "search_description": item.get("description", ""),
                "domain": item.get("domain", ""),
                "source_score": item.get("source_score", 50),
                "page_success": item.get("page_success", False),
                "page_error": item.get("page_error", ""),
                "page_content": str(item.get("page_content", ""))[:7500],
                "page_image_url": item.get("image_url", ""),
                "structured_product": item.get("structured_product", ""),
            }
            for index, item in enumerate(candidates[:12], start=1)
        ],
    }
    result = tools.run_ai_prompt(
        "prompts/casper_shopping_extract.txt",
        json.dumps(packet, ensure_ascii=False, indent=2),
        expect_json=True,
        num_ctx=8192,
        num_predict=2200,
        think=False,
        model_name="gemma4:12b",
    )
    items = result.get("items") if isinstance(result, dict) else None
    if not isinstance(items, list):
        return None
    output = {}
    requirements = plan.get("requirements", [])
    for value in items:
        if not isinstance(value, dict):
            continue
        try:
            index = int(value.get("index"))
            fit_score = int(value.get("fit_score", 0))
        except (TypeError, ValueError):
            continue
        if index < 1 or index > len(packet["candidates"]):
            continue
        page_type = str(value.get("page_type", "OTHER")).upper().strip()
        if page_type not in {"PRODUCT", "SEARCH", "CATEGORY", "ARTICLE", "OTHER"}:
            continue
        rows = value.get("requirements", [])
        if not isinstance(rows, list):
            rows = []
        clean_rows = []
        for row in rows:
            if not isinstance(row, dict):
                continue
            requirement = str(row.get("requirement", "")).strip()[:180]
            status = str(row.get("status", "UNKNOWN")).upper().strip()
            if requirement and status in {"MATCH", "MISMATCH", "UNKNOWN"}:
                clean_rows.append(
                    {
                        "requirement": requirement,
                        "status": status,
                        "evidence": str(row.get("evidence", "")).strip()[:300],
                    }
                )
        if page_type == "PRODUCT":
            labels = [row["requirement"] for row in clean_rows]
            if labels != requirements:
                continue
        candidate = packet["candidates"][index - 1]
        if page_type == "PRODUCT" and candidate.get("page_success") is not True:
            continue
        structured_name, structured_brand = _structured_product_identity(
            candidate.get("structured_product")
        )
        # Ground product identity and attributes only against the search result
        # for this URL and its primary Product schema. The full rendered body
        # may contain recommendation widgets for unrelated products.
        visible_text = " ".join(
            str(candidate.get(key) or "")
            for key in (
                "search_title", "search_description", "structured_product",
            )
        )
        visible_normalized = _normalized_brand(visible_text)

        def grounded_field(field_value):
            normalized = _normalized_brand(field_value)
            return bool(normalized and normalized in visible_normalized)

        brand = structured_brand or str(value.get("brand", "")).strip()[:100]
        if not structured_brand and brand and not _brand_appears_in_text(
            brand,
            structured_name + " " + str(candidate.get("search_title") or ""),
        ):
            brand = ""
        title = structured_name or str(value.get("title", "")).strip()[:240]
        if not title or not grounded_field(title):
            title = str(candidate.get("search_title") or "").strip()[:240]
        summary = str(value.get("summary", "")).strip()[:900]
        if not summary or not grounded_field(summary):
            summary = str(candidate.get("search_description") or "").strip()[:500]
        price = str(value.get("price", "")).strip()[:80]
        if price and not grounded_field(price):
            price = ""
        currency = str(value.get("currency", "")).strip()[:20]
        if currency and not grounded_field(currency):
            currency = ""
        stock = str(value.get("stock", "")).strip()[:100]
        if stock and not grounded_field(stock):
            stock = ""
        rating = str(value.get("rating", "")).strip()[:60]
        if rating and not grounded_field(rating):
            rating = ""
        review_count = str(value.get("review_count", "")).strip()[:60]
        if review_count and not grounded_field(review_count):
            review_count = ""

        popularity = value.get("popularity", {})
        if not isinstance(popularity, dict):
            popularity = {}
        popularity_status = str(popularity.get("status", "UNKNOWN")).upper().strip()
        if popularity_status not in {"HIGH", "MEDIUM", "LOW", "UNKNOWN"}:
            popularity_status = "UNKNOWN"
        popularity_evidence = str(popularity.get("evidence", "")).strip()[:300]
        if popularity_evidence and not grounded_field(popularity_evidence):
            popularity_evidence = ""
        review_total = _parse_compact_count(review_count)
        if review_total >= 1000:
            popularity_status = "HIGH"
            popularity_evidence = "review_count: " + review_count
        elif review_total >= 100:
            popularity_status = "MEDIUM"
            popularity_evidence = "review_count: " + review_count
        elif popularity_status in {"HIGH", "MEDIUM"} and not popularity_evidence:
            popularity_status = "UNKNOWN"
        brand_evidence = _verified_brand_evidence(
            brand,
            plan.get("verified_brand_evidence", []),
        )
        brand_requirement_labels = {
            "current cross-source brand trend evidence",
            "established brand evidence",
        }
        demand_requirement_label = "visible demand or review-count evidence"
        grounded_rows = []
        for row in clean_rows:
            requirement = row["requirement"]
            status = row["status"]
            evidence = row["evidence"]
            if requirement in brand_requirement_labels:
                if brand_evidence:
                    status = "MATCH"
                    evidence = "cross-source brand evidence: " + ", ".join(
                        brand_evidence.get("source_domains", [])
                    )
                else:
                    status, evidence = "UNKNOWN", ""
            elif requirement == demand_requirement_label and review_total >= 100:
                status = "MATCH"
                evidence = "review_count: " + review_count
            elif status in {"MATCH", "MISMATCH"} and (
                not evidence or not grounded_field(evidence)
            ):
                status, evidence = "UNKNOWN", ""
            elif evidence and not grounded_field(evidence):
                evidence = ""
            grounded_rows.append(
                {
                    "requirement": requirement,
                    "status": status,
                    "evidence": evidence,
                }
            )
        evidence_quality = str(
            value.get("evidence_quality", "LOW")
        ).upper().strip()
        if evidence_quality not in {"HIGH", "MEDIUM", "LOW"}:
            evidence_quality = "LOW"
        output[index] = {
            "page_type": page_type,
            "title": title,
            "summary": summary,
            "merchant": str(candidate.get("domain") or "").strip()[:100],
            "price": price,
            "currency": currency,
            "stock": stock,
            "brand": brand,
            "rating": rating,
            "review_count": review_count,
            "popularity_status": popularity_status,
            "popularity_evidence": popularity_evidence,
            "requirements": grounded_rows,
            "fit_score": max(0, min(100, fit_score)),
            "evidence_quality": evidence_quality,
            "reason": str(value.get("reason", "")).strip()[:500],
        }
    if len(output) != len(packet["candidates"]):
        return None
    return output


def _extract_shopping_products(user_request, plan, region, candidates):
    """Extract each rendered product independently to avoid batch truncation."""
    output = {}
    for index, candidate in enumerate(candidates[:6], start=1):
        try:
            decision = _extract_shopping_products_batch(
                user_request,
                plan,
                region,
                [candidate],
            )
        except Exception as error:
            print(
                "[CASPER SHOPPING EXTRACT ERROR]",
                "index=" + str(index),
                repr(error),
            )
            continue
        value = decision.get(1) if isinstance(decision, dict) else None
        print(
            "[CASPER SHOPPING EXTRACT]",
            "index=" + str(index),
            "valid=" + str(value is not None),
            "type=" + str(value.get("page_type", "") if value else ""),
        )
        if value is not None:
            output[index] = value
    return output or None


def _normalized_brand(value):
    return re.sub(r"[\W_]+", " ", str(value or "").casefold()).strip()


def _brand_appears_in_text(brand, text):
    normalized_brand = _normalized_brand(brand)
    normalized_text = _normalized_brand(text)
    if len(normalized_brand) < 2:
        return False
    if re.fullmatch(r"[a-z0-9 ]+", normalized_brand):
        return bool(
            re.search(
                r"(?:^|\s)" + re.escape(normalized_brand) + r"(?:$|\s)",
                normalized_text,
            )
        )
    return normalized_brand in normalized_text


def _evidence_domain_key(domain):
    """Collapse ordinary subdomains so one publisher counts only once."""
    host = str(domain or "").casefold().strip().removeprefix("www.")
    labels = [label for label in host.split(".") if label]
    if len(labels) < 2:
        return host
    public_second_level = {
        "co.uk", "org.uk", "com.au", "net.au", "co.jp", "co.kr",
        "com.cn", "com.hk", "co.nz", "co.in", "com.sg", "com.br",
    }
    suffix = ".".join(labels[-2:])
    return ".".join(labels[-3:]) if suffix in public_second_level and len(labels) >= 3 else suffix


def _popularity_signal_terms(requirement):
    groups = {
        "CURRENTLY_TRENDING": (
            "viral", "trending", "tiktok", "social media", "internet famous",
            "internet sensation", "went viral", "网红", "爆红", "社交媒体",
        ),
        "ESTABLISHED_BRAND": (
            "well known", "well-known", "established brand", "mainstream", "leading brand",
            "major brand", "iconic", "household name", "best known", "best-known",
            "trusted brand", "知名品牌", "主流品牌", "大牌", "领先品牌",
        ),
        "PROVEN_DEMAND": (
            "popular", "best selling", "best-selling", "bestselling", "best seller",
            "most reviewed", "highly reviewed", "top rated", "top-rated",
            "热门", "畅销", "热卖", "高评论",
        ),
    }
    if requirement in groups:
        return groups[requirement]
    return (
        groups["ESTABLISHED_BRAND"]
        + groups["PROVEN_DEMAND"]
        + (
            "best overall", "best for", "our pick", "top pick",
            "recommended", "recommendation", "editor s choice",
            "editors choice", "expert pick", "tested pick",
        )
    )


def _popularity_support_is_positive(support, requirement):
    normalized = _normalized_brand(support)
    negative_pattern = re.compile(
        r"(?:^|\s)(?:not|never|no longer|formerly|used to be|was once|were once)"
        r"(?:\s+\w+){0,5}\s+"
        r"(?:viral|trending|popular|established brand|mainstream|well known|iconic|"
        r"major(?: brand)?|leading(?: brand)?|trusted(?: brand)?)(?:$|\s)"
    )
    if negative_pattern.search(normalized) or any(
        term in normalized
        for term in (
            "unpopular", "unknown brand", "niche brand", "并不流行", "不再流行",
            "并非主流", "并不知名", "小众品牌",
        )
    ):
        return False
    terms = tuple(
        _normalized_brand(term)
        for term in _popularity_signal_terms(requirement)
    )
    if any(term and term in normalized for term in terms):
        return True
    if requirement in {"PROVEN_DEMAND", "NONE"}:
        return bool(
            re.search(
                r"(?:\b[1-9]\d{2,}\b|\b\d+(?:\.\d+)?[km]\b)\s+"
                r"(?:customer\s+)?reviews\b",
                normalized,
            )
            or re.search(
                r"(?:\b[1-9]\d{2,}\b|\b\d+(?:\.\d+)?[km]\b)\s+sold\b",
                normalized,
            )
        )
    return False


def _current_trend_support_is_current(support, source):
    normalized = _normalized_brand(support)
    current_year = str(datetime.now().year)
    material = " ".join(
        str(source.get(key) or "")
        for key in ("title", "description", "published")
    )
    material_normalized = _normalized_brand(material)
    past_pattern = re.compile(
        r"(?:^|\s)(?:was|were|formerly|used to)(?:\s+\w+){0,5}\s+"
        r"(?:viral|trending|popular)(?:$|\s)"
    )
    if past_pattern.search(normalized) or any(
        term in normalized for term in ("曾经网红", "曾经流行", "过去很火")
    ):
        return False
    support_years = set(re.findall(r"\b20\d{2}\b", support))
    if support_years and current_year not in support_years:
        return False
    years = set(re.findall(r"\b20\d{2}\b", material + " " + support))
    if years and current_year not in years:
        return False
    return bool(
        current_year in material
        or any(
            phrase in normalized
            for phrase in (
                "trending", "currently", "right now", "this year", "today",
                "is viral", "current viral", "当下", "目前", "今年", "正在流行",
            )
        )
    )


def _category_semantic_tokens(value):
    """Normalize simple inflections while preserving compound-category meaning."""
    stopwords = {"a", "an", "the", "and", "or", "of", "for", "with"}
    output = set()
    for raw in re.findall(r"[a-z0-9]+", str(value or "").casefold()):
        if raw in stopwords:
            continue
        token = raw
        if token.endswith("ies") and len(token) > 4:
            token = token[:-3] + "y"
        elif token.endswith("s") and len(token) > 3 and not token.endswith("ss"):
            token = token[:-1]
        for suffix in ("ing", "ed"):
            if token.endswith(suffix) and len(token) > len(suffix) + 3:
                token = token[:-len(suffix)]
                if len(token) > 3 and token[-1:] == token[-2:-1]:
                    token = token[:-1]
                break
        if token:
            output.add(token)
    return output


def _source_mentions_product_query(source, product_query):
    """Reject evidence that drops an integral compound-category token."""
    query_tokens = _category_semantic_tokens(product_query)
    if not query_tokens:
        return True
    material = " ".join(
        str(source.get(key) or "") for key in ("title", "description")
    ).casefold()
    return query_tokens.issubset(_category_semantic_tokens(material))


def _brand_support_excerpt(name, source, popularity_requirement):
    """Recover a short verbatim support window from an indexed source."""
    material = " ".join(
        str(source.get(key) or "").strip()
        for key in ("title", "description")
        if str(source.get(key) or "").strip()
    )
    if not material or not name:
        return ""
    match = re.search(re.escape(name), material, flags=re.IGNORECASE)
    if not match:
        return ""
    windows = []
    for radius in (180, 300, 500):
        start = max(0, match.start() - radius)
        end = min(len(material), match.end() + radius)
        windows.append(material[start:end].strip())
    for support in windows:
        if not _popularity_support_is_positive(support, popularity_requirement):
            continue
        if (
            popularity_requirement == "CURRENTLY_TRENDING"
            and not _current_trend_support_is_current(support, source)
        ):
            continue
        return support[:500]
    return ""


def _validate_brand_evidence(
    result,
    sources,
    minimum_sources,
    popularity_requirement="NONE",
    product_query="",
):
    """Bind model-proposed brand names to distinct visible search sources."""
    values = result.get("brands") if isinstance(result, dict) else None
    if not isinstance(values, list):
        return []
    by_index = {item["index"]: item for item in sources}
    blocked = {
        "cup", "cups", "mug", "mugs", "tumbler", "tumblers", "glass",
        "amazon", "walmart", "target", "ebay", "yami", "best seller",
    }
    output = []
    seen = set()
    for value in values[:8]:
        if not isinstance(value, dict):
            continue
        name = str(value.get("name") or "").strip()[:100]
        key = _canonical_brand_key(name)
        citations = value.get("source_indexes")
        compact_indexes = isinstance(citations, list)
        if not compact_indexes:
            citations = value.get("sources")
        if not name or key in blocked or key in seen or not isinstance(citations, list):
            continue
        grounded_sources = []
        grounded_domains = set()
        for citation in citations[:8]:
            try:
                source_index = citation if compact_indexes else citation.get("source_index")
                source = by_index.get(int(source_index))
            except (TypeError, ValueError):
                source = None
            if not source:
                continue
            material = source.get("title", "") + " " + source.get("description", "")
            material_normalized = _normalized_brand(material)
            support = (
                _brand_support_excerpt(name, source, popularity_requirement)
                if compact_indexes
                else str(citation.get("support") or "").strip()[:500]
            )
            support_normalized = _normalized_brand(support)
            domain = _evidence_domain_key(source.get("domain", ""))
            if (
                domain
                and domain not in grounded_domains
                and _source_mentions_product_query(source, product_query)
                and _brand_appears_in_text(name, material)
                and _brand_appears_in_text(name, support)
                and len(support_normalized) >= 4
                and support_normalized in material_normalized
                and _popularity_support_is_positive(
                    support,
                    popularity_requirement,
                )
                and (
                    popularity_requirement != "CURRENTLY_TRENDING"
                    or _current_trend_support_is_current(support, source)
                )
            ):
                grounded_domains.add(domain)
                grounded_sources.append((source, support))
        if len(grounded_domains) < minimum_sources:
            continue
        seen.add(key)
        output.append(
            {
                "name": name,
                "source_count": len(grounded_domains),
                "source_domains": sorted(grounded_domains),
                "evidence": [
                    {
                        "title": item.get("title", "")[:220],
                        "domain": _evidence_domain_key(item.get("domain", "")),
                        "url": item.get("url", "")[:1000],
                        "support": support[:240],
                    }
                    for item, support in grounded_sources[:4]
                ],
            }
        )
        if len(output) >= 6:
            break
    return output


def _recommendation_page_excerpt(content, limit=1800):
    """Keep distributed recommendation paragraphs instead of page chrome."""
    visible = re.sub(r"\s+", " ", str(content or "")).strip()
    if len(visible) <= limit:
        return visible
    marker = re.compile(
        r"best overall|our pick|top pick|also great|upgrade pick|budget pick|"
        r"best for|we recommend|recommended|editor(?:'s|s)? choice|tested pick",
        flags=re.IGNORECASE,
    )
    windows = []
    occupied = []
    for match in marker.finditer(visible):
        start = max(0, match.start() - 180)
        end = min(len(visible), match.end() + 420)
        if any(start < prior_end and end > prior_start for prior_start, prior_end in occupied):
            continue
        occupied.append((start, end))
        windows.append(visible[start:end].strip())
        if sum(len(value) for value in windows) >= limit:
            break
    if windows:
        return " … ".join(windows)[:limit]
    return visible[:limit]


def _enrich_recommendation_sources(sources, status_callback=None, limit=4):
    """Open independent recommendation pages before asking for brand indexes."""
    del status_callback
    enriched = []
    opened = 0
    for source in sources:
        current = dict(source)
        if opened < limit and _merchant_source_priority(source) < 0:
            try:
                page = read_url(source.get("url", ""))
            except Exception as error:
                print(
                    "[CASPER RECOMMENDATION SOURCE ERROR]",
                    source.get("domain", ""),
                    repr(error),
                )
                page = {}
            print(
                "[CASPER RECOMMENDATION SOURCE]",
                source.get("domain", ""),
                "success=" + str(bool(page.get("success"))),
                "length=" + str(len(str(page.get("content") or ""))),
            )
            opened += 1
            if page.get("success"):
                visible = _recommendation_page_excerpt(page.get("content"), 1800)
                if visible:
                    current["description"] = (
                        str(source.get("description") or "").strip()
                        + " "
                        + visible
                    ).strip()[:2200]
                    current["published"] = (
                        str(page.get("published") or "").strip()
                        or current.get("published", "")
                    )[:160]
                    current["page_read"] = True
        enriched.append(current)
    return enriched


def _is_independent_recommendation_source(source):
    """Keep editorial evidence separate from shopping/search storefronts."""
    host = str(source.get("domain") or "").casefold().strip().removeprefix("www.")
    first_label = host.split(".", 1)[0]
    if first_label in {"shop", "shopping", "store", "deals", "marketplace"}:
        return False
    return _merchant_source_priority(source) < 0


def _discover_popular_brands(
    user_request,
    plan,
    region,
    engine_plan,
    status_callback=None,
):
    """Discover current cross-source brand evidence without a built-in list."""
    import tools

    requirement = str(plan.get("popularity_requirement") or "NONE")
    product_query = str(plan.get("product_query") or "").strip()
    if not product_query:
        return []
    qualifiers = {
        "CURRENTLY_TRENDING": "viral trending brands",
        "ESTABLISHED_BRAND": "mainstream well-known brands",
        "PROVEN_DEMAND": "best-selling products expert reviews comparison",
        "NONE": "best recommendations expert reviews comparison roundup",
    }
    country = str(region.get("country_name") or region.get("country_code") or "")
    query = (
        product_query
        + " "
        + qualifiers.get(requirement, qualifiers["NONE"])
        + " "
        + str(datetime.now().year)
        + " "
        + country
    )[:260]
    _status(
        status_callback,
        "Casper 正在先查可信评测与推荐榜单… 📊"
        if requirement == "NONE"
        else "Casper 正在核实哪些品牌真正主流… 📊",
    )
    discovery = discover_web(
        query,
        count=10,
        status_callback=status_callback,
        multi_engine=True,
        country_code=region.get("country_code"),
        engine_plan=engine_plan,
    )
    if discovery.get("status") != "OK":
        return []
    sources = []
    seen_domains = set()
    for item in discovery.get("results", []):
        if not isinstance(item, dict):
            continue
        domain = str(item.get("domain") or "").casefold().removeprefix("www.")
        domain_key = _evidence_domain_key(domain)
        title = str(item.get("title") or "").strip()
        description = str(item.get("description") or "").strip()
        if not domain_key or domain_key in seen_domains or not (title or description):
            continue
        seen_domains.add(domain_key)
        sources.append(
            {
                "index": len(sources) + 1,
                "domain": domain,
                "title": title[:240],
                "description": description[:500],
                "url": str(item.get("url") or "")[:1000],
                "published": str(item.get("published") or "")[:80],
            }
        )
    if len(sources) < 2:
        return []

    if requirement == "NONE":
        _status(status_callback, "Casper 正在读取推荐榜单正文… 📖")
        sources = _enrich_recommendation_sources(
            sources,
            status_callback=status_callback,
            limit=4,
        )

    minimum_sources = 1 if requirement == "NONE" else 2
    packet = {
        "current_date": datetime.now().date().isoformat(),
        "shopping_region": region,
        "original_user_request": str(user_request)[:900],
        "product_query": product_query,
        "popularity_requirement": requirement,
        "minimum_sources_per_brand": minimum_sources,
        "sources": sources[:8],
    }
    for attempt in range(2):
        if attempt:
            packet["retry_instruction"] = (
                "Return only category-relevant brands visibly supported by "
                "minimum_sources_per_brand distinct source domains."
            )
        try:
            result = tools.run_ai_prompt(
                "prompts/casper_shopping_brand_evidence.txt",
                json.dumps(packet, ensure_ascii=False, separators=(",", ":")),
                expect_json=True,
                num_ctx=6144,
                num_predict=240,
                think=False,
                model_name="llama3.2:latest",
                json_schema={
                    "type": "object",
                    "properties": {
                        "brands": {
                            "type": "array",
                            "maxItems": 6,
                            "items": {
                                "type": "object",
                                "properties": {
                                    "name": {"type": "string"},
                                    "source_indexes": {
                                        "type": "array",
                                        "items": {"type": "integer"},
                                        "maxItems": 6,
                                    },
                                },
                                "required": ["name", "source_indexes"],
                            },
                        }
                    },
                    "required": ["brands"],
                },
            )
        except Exception as error:
            print("[CASPER BRAND EVIDENCE ERROR]", repr(error))
            result = None
        brands = _validate_brand_evidence(
            result,
            sources,
            minimum_sources,
            requirement,
            product_query,
        )
        if brands:
            print("[CASPER VERIFIED BRANDS]", json.dumps(brands, ensure_ascii=False))
            return brands
    return []


def _build_ai_recommendation_plan(user_request, recent_context, region):
    """Let one capable model own recommendation semantics and search intent."""
    import tools

    eligible_engines = _eligible_engine_catalog(region.get("country_code"))
    packet = {
        "current_date": datetime.now().date().isoformat(),
        "detected_region": region,
        "runtime_profile": {
            key: region.get(key)
            for key in (
                "country_code",
                "country_name",
                "location_name",
                "time_zone",
                "unit_system",
                "preferred_search_engines",
                "source",
                "confidence",
            )
        },
        "current_user_request": str(user_request)[:1200],
        "recent_context_for_reference_only": str(recent_context)[-1800:],
        "eligible_search_engines": eligible_engines,
    }
    eligible_ids = {
        str(item.get("id") or "") for item in eligible_engines
    }
    for attempt in range(2):
        attempt_packet = dict(packet)
        if attempt:
            attempt_packet["retry_instruction"] = (
                "Return the required JSON only. Re-read the exact current "
                "request and do not invent product features."
            )
        try:
            raw = tools.run_ai_prompt(
                "prompts/casper_product_recommendation_plan.txt",
                json.dumps(
                    attempt_packet,
                    ensure_ascii=False,
                    separators=(",", ":"),
                ),
                expect_json=True,
                num_ctx=4096,
                num_predict=1800,
                think=False,
                model_name="gemma4:12b",
            )
        except Exception as error:
            print(
                "[CASPER RECOMMENDATION PLAN ERROR]",
                "attempt=" + str(attempt + 1),
                repr(error),
            )
            # A model/runtime exception (especially Ollama HTTP 500) is not a
            # JSON-format error. Do not immediately hit the same GPU runner a
            # second time; a later user turn can retry after Ollama recovers.
            return None
        if not isinstance(raw, dict):
            continue
        topic = " ".join(str(raw.get("topic") or "").split()).strip()[:180]
        queries = []
        for value in raw.get("search_queries", []):
            query = " ".join(str(value or "").split()).strip()[:260]
            if query and query not in queries:
                queries.append(query)
            if len(queries) >= 2:
                break
        criteria = []
        for value in raw.get("criteria", []):
            criterion = " ".join(str(value or "").split()).strip()[:180]
            if criterion and criterion not in criteria:
                criteria.append(criterion)
            if len(criteria) >= 8:
                break
        audience_scope = str(raw.get("audience_scope") or "").upper().strip()
        audience = " ".join(
            str(raw.get("audience") or "").split()
        ).strip()[:180]
        # User-explicit audience words are a hard input fact.  The log that
        # motivated Stable V1 showed an "adult websites" request returned as
        # GENERAL_UNSPECIFIED, after which the auditor rejected adult content
        # for being adult.  Reconcile only explicit words from this turn.
        explicit_audience_match = re.search(
            r"成人|成年人|婴儿|宝宝|幼儿|儿童|老人|老年人|学生|"
            r"\badults?\b|\bbab(?:y|ies)\b|\btoddlers?\b|\bchildren\b|"
            r"\bkids?\b|\bseniors?\b|\bstudents?\b",
            str(user_request),
            flags=re.IGNORECASE,
        )
        if explicit_audience_match and audience_scope == "GENERAL_UNSPECIFIED":
            audience_scope = "EXPLICIT"
            if not audience or audience.casefold() == "general adult everyday users":
                audience = explicit_audience_match.group(0)
            print(
                "[CASPER AUDIENCE SCOPE RECONCILED]",
                explicit_audience_match.group(0),
            )
        policy = str(raw.get("count_policy") or "").upper().strip()
        try:
            target_count = int(raw.get("target_count"))
        except (TypeError, ValueError):
            target_count = 0
        requested_engines = tuple(
            str(value or "").strip() for value in raw.get("engines", [])
        )
        engine_policy = str(
            raw.get("engine_policy") or ""
        ).upper().strip()
        profile_engines = tuple(
            str(value or "").strip()
            for value in region.get("preferred_search_engines", [])[:2]
        )
        if not (
            len(profile_engines) == 2
            and len(set(profile_engines)) == 2
            and all(engine in eligible_ids for engine in profile_engines)
        ):
            profile_engines = tuple(
                engine
                for engine in ("google", "bing")
                if engine in eligible_ids
            )
        if len(profile_engines) != 2:
            profile_engines = _safe_engine_recovery_pair(
                region.get("country_code")
            )
        engines = (
            profile_engines
            if engine_policy == "PROFILE_DEFAULT"
            else requested_engines
        )
        reason = str(raw.get("reason") or "").strip()[:500]
        if audience_scope == "GENERAL_UNSPECIFIED":
            reason_key = reason.casefold()
            explicit_reason_markers = (
                "for adult use", "for adults", "adult-suitable",
                "explicit adult", "for babies", "for infants",
                "for toddlers", "for children", "for elderly",
                "for seniors", "for students", "for professionals",
            )
            if any(marker in reason_key for marker in explicit_reason_markers):
                audience_scope = "EXPLICIT"
                print(
                    "[CASPER AUDIENCE SCOPE RECONCILED]",
                    reason,
                )
        if (
            topic
            and queries
            and audience_scope in {"EXPLICIT", "GENERAL_UNSPECIFIED"}
            and audience
            and policy in {"USER_EXPLICIT", "AI_DECIDES"}
            and engine_policy in {"PROFILE_DEFAULT", "USER_EXPLICIT"}
            and 1 <= target_count <= 5
            and len(engines) == 2
            and len(set(engines)) == 2
            and all(engine in eligible_ids for engine in engines)
        ):
            plan = {
                "topic": topic,
                "search_queries": queries,
                "criteria": criteria,
                "audience_scope": audience_scope,
                "audience": audience,
                "count_policy": policy,
                "target_count": target_count,
                "engine_policy": engine_policy,
                "engines": engines,
                "reason": reason,
            }
            print(
                "[CASPER AI RECOMMENDATION PLAN]",
                json.dumps(plan, ensure_ascii=False),
            )
            return plan
    return None


def _accept_ai_recommendation_options(result, sources, excluded_titles=None):
    """Perform structural source binding without second-guessing AI semantics."""
    if not isinstance(result, dict) or not isinstance(result.get("items"), list):
        return [], ""
    by_index = {int(item["index"]): item for item in sources}
    accepted = []
    seen_titles = set()
    excluded_title_keys = {
        " ".join(str(value or "").split()).casefold()
        for value in (excluded_titles or [])
        if str(value or "").strip()
    }
    for value in result["items"][:8]:
        if not isinstance(value, dict):
            continue
        title = " ".join(str(value.get("title") or "").split()).strip()[:180]
        brand = " ".join(str(value.get("brand") or "").split()).strip()[:100]
        summary = " ".join(str(value.get("summary") or "").split()).strip()[:800]
        title_key = title.casefold()
        if (
            not title
            or not summary
            or not title_key
            or title_key in seen_titles
            or title_key in excluded_title_keys
        ):
            continue
        verification_queries = []
        for raw_query in value.get("verification_queries", [])[:2]:
            verification_query = " ".join(
                str(raw_query or "").split()
            ).strip()[:280]
            if (
                verification_query
                and verification_query not in verification_queries
            ):
                verification_queries.append(verification_query)
        if not verification_queries:
            continue
        resolved_sources = []
        resolved_indexes = set()
        for raw_index in value.get("source_indexes", [])[:8]:
            try:
                index = int(raw_index)
            except (TypeError, ValueError):
                continue
            source = by_index.get(index)
            if source and index not in resolved_indexes:
                resolved_indexes.add(index)
                resolved_sources.append(source)
        if not resolved_sources:
            continue
        seen_titles.add(title_key)
        accepted.append(
            {
                "title": title,
                "brand": brand,
                "summary": summary,
                "verification_queries": verification_queries,
                "url": str(resolved_sources[0].get("url") or "")[:1000],
                "domain": str(resolved_sources[0].get("domain") or "")[:180],
                "source_count": len(resolved_sources),
                "source_domains": [
                    _evidence_domain_key(source.get("domain", ""))
                    for source in resolved_sources
                ],
                "evidence": [
                    {
                        "title": str(source.get("title") or "")[:220],
                        "url": str(source.get("url") or "")[:1000],
                        "domain": _evidence_domain_key(source.get("domain", "")),
                    }
                    for source in resolved_sources
                ],
            }
        )
    reply = str(result.get("reply") or "").strip()[:5000]
    return accepted, reply


def _collect_recommendation_sources(
    search_queries,
    region,
    engine_plan,
    status_callback=None,
    existing_sources=None,
    limit=10,
):
    """Execute AI discovery queries and retain independent editorial leads."""
    sources = [dict(item) for item in (existing_sources or [])]
    seen_domains = {
        _evidence_domain_key(item.get("domain", ""))
        for item in sources
        if _evidence_domain_key(item.get("domain", ""))
    }
    last_status = "NO_RESULTS"
    search_ai_overviews = []
    for research_query in search_queries:
        discovery = discover_web(
            research_query,
            count=8,
            status_callback=status_callback,
            multi_engine=True,
            country_code=region.get("country_code"),
            engine_plan=engine_plan,
            minimum_results=5,
        )
        last_status = discovery.get("status", "NO_RESULTS")
        if discovery.get("status") != "OK":
            continue
        for value in discovery.get("ai_summaries", []):
            if not isinstance(value, dict):
                continue
            summary = " ".join(str(value.get("summary") or "").split()).strip()
            if summary and summary not in search_ai_overviews:
                search_ai_overviews.append(summary[:1800])
        for item in discovery.get("results", []):
            if not isinstance(item, dict):
                continue
            domain = str(item.get("domain") or "").casefold().removeprefix(
                "www."
            )
            domain_key = _evidence_domain_key(domain)
            if not domain_key or domain_key in seen_domains:
                continue
            source = {
                "index": len(sources) + 1,
                "domain": domain,
                "title": str(item.get("title") or "").strip()[:240],
                "description": str(item.get("description") or "").strip()[:500],
                "url": str(item.get("url") or "")[:1000],
                "published": str(item.get("published") or "")[:80],
                "discovery_engine": str(
                    item.get("discovery_engine") or ""
                )[:40],
            }
            if not _is_independent_recommendation_source(source):
                continue
            seen_domains.add(domain_key)
            sources.append(source)
            if len(sources) >= limit:
                break
        if len(sources) >= limit:
            break
    for index, source in enumerate(sources, start=1):
        source["index"] = index
    if sources and search_ai_overviews:
        # The overview is intentionally attached as a discovery lead only.
        # The independent verifier must still check the candidate against
        # candidate-local evidence before it can pass.
        sources[0]["search_ai_overview"] = "\n".join(
            search_ai_overviews
        )[:1800]
    return sources, last_status


def _ask_ai_for_recommendation_options(packet):
    """Ask the 12B recommendation model to discover exact candidate names."""
    import tools

    for attempt in range(2):
        attempt_packet = dict(packet)
        if attempt:
            attempt_packet["retry_instruction"] = (
                "Return the required JSON object only. Re-read every supplied "
                "source, include verification_queries for every candidate, "
                "and return an empty list rather than unsupported products."
            )
        try:
            raw = tools.run_ai_prompt(
                "prompts/casper_product_recommendation_options.txt",
                json.dumps(
                    attempt_packet,
                    ensure_ascii=False,
                    separators=(",", ":"),
                ),
                expect_json=True,
                num_ctx=6144,
                num_predict=1800,
                think=False,
                model_name="gemma4:12b",
            )
        except Exception as error:
            print(
                "[CASPER RECOMMENDATION OPTION ERROR]",
                "attempt=" + str(attempt + 1),
                repr(error),
            )
            return [], ""
        options, provisional_reply = _accept_ai_recommendation_options(
            raw,
            packet.get("sources", []),
            packet.get("excluded_titles", []),
        )
        if options:
            return options, provisional_reply
    return [], ""


def _candidate_verification_sources(
    option,
    region,
    engine_plan,
    status_callback=None,
):
    """Collect candidate-local search summaries without opening pages."""
    sources = []
    seen_domains = set()
    search_ai_overviews = []
    for verification_query in option.get("verification_queries", [])[:2]:
        discovery = discover_web(
            verification_query,
            count=5,
            status_callback=status_callback,
            multi_engine=True,
            country_code=region.get("country_code"),
            engine_plan=engine_plan,
            minimum_results=2,
        )
        if discovery.get("status") != "OK":
            continue
        for value in discovery.get("ai_summaries", []):
            if not isinstance(value, dict):
                continue
            summary = " ".join(str(value.get("summary") or "").split()).strip()
            if summary and summary not in search_ai_overviews:
                search_ai_overviews.append(summary[:1400])
        for item in discovery.get("results", []):
            if not isinstance(item, dict):
                continue
            domain = str(item.get("domain") or "").casefold().removeprefix(
                "www."
            )
            domain_key = _evidence_domain_key(domain)
            if (
                not domain_key
                or domain_key in seen_domains
                or _merchant_has_known_detail_contract(domain)
            ):
                continue
            source = {
                "index": len(sources) + 1,
                "domain": domain,
                "title": str(item.get("title") or "").strip()[:240],
                "description": str(item.get("description") or "").strip()[:500],
                "url": str(item.get("url") or "")[:1000],
                "published": str(item.get("published") or "")[:80],
            }
            if not source["url"] or not (source["title"] or source["description"]):
                continue
            seen_domains.add(domain_key)
            sources.append(source)
            if len(sources) >= 3:
                break
        if len(sources) >= 3:
            break

    if sources and search_ai_overviews:
        sources[0]["search_ai_overview"] = "\n".join(
            search_ai_overviews
        )[:1400]
    return sources


def _enrich_candidate_verification_sources(candidate, limit=1):
    """Open at most one candidate page after the auditor requests it."""
    enriched = []
    opened = 0
    for source in candidate.get("verification_sources", []):
        current = dict(source)
        if opened >= max(0, int(limit)) or not source.get("url"):
            enriched.append(current)
            continue
        try:
            page = read_url(source.get("url", ""))
        except Exception as error:
            print(
                "[CASPER RECOMMENDATION VERIFY SOURCE ERROR]",
                source.get("domain", ""),
                repr(error),
            )
            page = {}
        opened += 1
        print(
            "[CASPER RECOMMENDATION VERIFY SOURCE]",
            source.get("domain", ""),
            "success=" + str(bool(page.get("success"))),
            "length=" + str(len(str(page.get("content") or ""))),
        )
        if page.get("success"):
            excerpt = _recommendation_page_excerpt(page.get("content"), 1800)
            if excerpt:
                current["description"] = (
                    str(current.get("description") or "").strip()
                    + " "
                    + excerpt
                ).strip()[:2200]
                current["page_read"] = True
        enriched.append(current)
    updated = dict(candidate)
    updated["verification_sources"] = enriched
    updated["page_escalated"] = True
    return updated


def _accept_ai_recommendation_verdicts(result, candidates):
    """Enforce the audit shape while leaving semantic judgment to the AI."""
    if not isinstance(result, dict) or not isinstance(result.get("items"), list):
        return [], []
    by_id = {item["candidate_id"]: item for item in candidates}
    verdicts = {}
    for value in result.get("items", []):
        if not isinstance(value, dict):
            continue
        try:
            candidate_id = int(value.get("candidate_id"))
        except (TypeError, ValueError):
            continue
        candidate = by_id.get(candidate_id)
        if not candidate or candidate_id in verdicts:
            continue
        verdict = str(value.get("verdict") or "").upper().strip()
        if verdict not in {"PASS", "FAIL", "NEEDS_PAGE", "UNVERIFIED"}:
            continue
        source_map = {
            int(source["index"]): source
            for source in candidate.get("verification_sources", [])
        }
        cited = []
        cited_indexes = set()
        for raw_index in value.get("source_indexes", [])[:6]:
            try:
                source_index = int(raw_index)
            except (TypeError, ValueError):
                continue
            if source_index in source_map and source_index not in cited_indexes:
                cited_indexes.add(source_index)
                cited.append(source_map[source_index])
        checks = []
        seen_conditions = set()
        for raw_check in value.get("checks", [])[:16]:
            if not isinstance(raw_check, dict):
                continue
            condition = " ".join(
                str(raw_check.get("condition") or "").split()
            ).strip()[:180]
            status = str(raw_check.get("status") or "").upper().strip()
            if not condition or status not in {
                "SUPPORTED",
                "CONTRADICTED",
                "MISSING",
            }:
                continue
            condition_key = condition.casefold()
            if condition_key in seen_conditions:
                continue
            seen_conditions.add(condition_key)
            checks.append(
                {
                    "condition": condition,
                    "status": status,
                    "reason": " ".join(
                        str(raw_check.get("reason") or "").split()
                    ).strip()[:300],
                }
            )
        required_check_count = max(
            2,
            int(candidate.get("required_check_count") or 2),
        )
        required_condition_keys = {
            str(value).casefold().strip()
            for value in candidate.get("required_checks", [])
            if str(value).strip()
        }
        statuses = [item["status"] for item in checks]
        checks_complete = (
            len(checks) >= required_check_count
            and (
                not required_condition_keys
                or seen_conditions >= required_condition_keys
            )
            and all(status == "SUPPORTED" for status in statuses)
        )
        if "CONTRADICTED" in statuses:
            verdict = "FAIL"
        elif (
            "MISSING" in statuses
            or len(checks) < required_check_count
            or (
                required_condition_keys
                and not seen_conditions >= required_condition_keys
            )
            or (verdict == "PASS" and not cited)
        ):
            verdict = (
                "UNVERIFIED"
                if candidate.get("page_escalated")
                else "NEEDS_PAGE"
            )
        elif verdict == "PASS" and not checks_complete:
            verdict = (
                "UNVERIFIED"
                if candidate.get("page_escalated")
                else "NEEDS_PAGE"
            )
        verdicts[candidate_id] = {
            "verdict": verdict,
            "summary": " ".join(
                str(value.get("summary") or "").split()
            ).strip()[:900],
            "failed_conditions": [
                " ".join(str(item or "").split()).strip()[:180]
                for item in value.get("failed_conditions", [])[:8]
                if str(item or "").strip()
            ],
            "sources": cited,
            "checks": checks,
        }

    passed = []
    rejected = []
    for candidate in candidates:
        decision = verdicts.get(
            candidate["candidate_id"],
            {
                "verdict": "UNVERIFIED",
                "summary": "No valid AI verification verdict was returned.",
                "failed_conditions": ["verification evidence"],
                "sources": [],
            },
        )
        if decision["verdict"] != "PASS":
            rejected.append(
                {
                    "candidate_id": candidate["candidate_id"],
                    "title": candidate["title"],
                    "verdict": decision["verdict"],
                    "reason": decision["summary"],
                    "failed_conditions": decision["failed_conditions"],
                }
            )
            continue
        verified = dict(candidate)
        if decision["summary"]:
            verified["summary"] = decision["summary"]
        verification_domains = [
            _evidence_domain_key(source.get("domain", ""))
            for source in decision["sources"]
            if _evidence_domain_key(source.get("domain", ""))
        ]
        verified["verification_source_count"] = len(verification_domains)
        verified["verification_source_domains"] = verification_domains
        verified["verification_checks"] = [
            dict(check)
            for check in decision.get("checks", [])
            if isinstance(check, dict)
        ]
        verified["verification_evidence"] = [
            {
                "title": str(source.get("title") or "")[:220],
                "url": str(source.get("url") or "")[:1000],
                "domain": _evidence_domain_key(source.get("domain", "")),
            }
            for source in decision["sources"]
        ]
        passed.append(verified)
    return passed, rejected


def _run_recommendation_audit(candidates, user_request, plan):
    """Run one independent audit pass over supplied candidate evidence."""
    import tools

    packet = {
        "original_user_request": str(user_request)[:900],
        "topic": plan["topic"],
        "criteria": plan["criteria"],
        "audience_scope": plan["audience_scope"],
        "audience": plan["audience"],
        "page_escalation": any(
            bool(item.get("page_escalated")) for item in candidates
        ),
        "candidates": [
            {
                "candidate_id": item["candidate_id"],
                "title": item["title"],
                "brand": item["brand"],
                "required_checks": item.get("required_checks", []),
                "verification_sources": item["verification_sources"],
            }
            for item in candidates
        ],
    }
    for attempt in range(2):
        attempt_packet = dict(packet)
        if attempt:
            attempt_packet["retry_instruction"] = (
                "Return the required JSON only. Give every candidate_id one "
                "verdict and every required check one explicit status."
            )
        try:
            raw = tools.run_ai_prompt(
                "prompts/casper_product_recommendation_verify.txt",
                json.dumps(
                    attempt_packet,
                    ensure_ascii=False,
                    separators=(",", ":"),
                ),
                expect_json=True,
                num_ctx=6144,
                num_predict=1800,
                think=False,
                model_name="gemma4:12b",
            )
        except Exception as error:
            print(
                "[CASPER RECOMMENDATION VERIFY ERROR]",
                "attempt=" + str(attempt + 1),
                repr(error),
            )
            break
        passed, rejected = _accept_ai_recommendation_verdicts(raw, candidates)
        if passed or rejected:
            return passed, rejected
    return [], [
        {
            "candidate_id": item["candidate_id"],
            "title": item["title"],
            "verdict": "UNVERIFIED",
            "reason": "Verification model returned no valid verdict.",
            "failed_conditions": ["verification evidence"],
        }
        for item in candidates
    ]


def _verify_ai_recommendation_options(
    options,
    user_request,
    plan,
    region,
    engine_plan,
    status_callback=None,
):
    """Audit snippets first and read one page only for real evidence gaps."""

    candidates = []
    for candidate_id, option in enumerate(options, start=1):
        verification_sources = _candidate_verification_sources(
            option,
            region,
            engine_plan,
            status_callback=status_callback,
        )
        candidates.append(
            {
                "candidate_id": candidate_id,
                **option,
                "verification_sources": verification_sources,
                "required_checks": [
                    "category",
                    "audience",
                    *[
                        str(value)[:180]
                        for value in plan.get("criteria", [])
                        if str(value).strip()
                    ],
                ],
                "required_check_count": 2 + len(plan.get("criteria", [])),
                "page_escalated": False,
            }
        )
    passed, rejected = _run_recommendation_audit(
        candidates,
        user_request,
        plan,
    )
    needs_page_ids = {
        item.get("candidate_id")
        for item in rejected
        if item.get("verdict") == "NEEDS_PAGE"
    }
    if needs_page_ids:
        _status(
            status_callback,
            "搜索摘要证据不足，Casper 正在按需补读少量原网页… 📄",
        )
        escalated = [
            _enrich_candidate_verification_sources(item, limit=1)
            for item in candidates
            if item["candidate_id"] in needs_page_ids
        ]
        page_passed, page_rejected = _run_recommendation_audit(
            escalated,
            user_request,
            plan,
        )
        passed.extend(page_passed)
        rejected = [
            item
            for item in rejected
            if item.get("candidate_id") not in needs_page_ids
        ] + page_rejected
    print(
        "[CASPER RECOMMENDATION VERIFIED]",
        "passed=" + str(len(passed)),
        "rejected=" + str(len(rejected)),
        "page_escalations=" + str(len(needs_page_ids)),
    )
    return passed, rejected


def _build_ai_recommendation_recovery_queries(
    user_request,
    plan,
    region,
    verified,
    rejected,
):
    """Let AI decide how to search again after candidate verification fails."""
    import tools

    packet = {
        "original_user_request": str(user_request)[:900],
        "plan": plan,
        "region": region,
        "verified_titles": [item["title"] for item in verified],
        "rejected_candidates": rejected,
        "remaining_target": max(0, plan["target_count"] - len(verified)),
    }
    try:
        raw = tools.run_ai_prompt(
            "prompts/casper_product_recommendation_recovery.txt",
            json.dumps(packet, ensure_ascii=False, separators=(",", ":")),
            expect_json=True,
            num_ctx=4096,
            num_predict=1200,
            think=False,
            model_name="gemma4:12b",
        )
    except Exception as error:
        print("[CASPER RECOMMENDATION RECOVERY ERROR]", repr(error))
        return []
    if not isinstance(raw, dict):
        return []
    queries = []
    for value in raw.get("search_queries", [])[:2]:
        query = " ".join(str(value or "").split()).strip()[:280]
        if query and query not in queries:
            queries.append(query)
    if queries:
        print(
            "[CASPER RECOMMENDATION RECOVERY QUERIES]",
            json.dumps(queries, ensure_ascii=False),
        )
    return queries


def _build_ai_verified_recommendation_reply(user_request, plan, verified):
    """Create one overview while moving item detail into matching cards."""
    import tools

    if not verified:
        return ""
    packet = {
        "original_user_request": str(user_request)[:900],
        "target_count": plan["target_count"],
        "count_policy": plan["count_policy"],
        "verified_candidates": [
            {
                "title": item["title"],
                "brand": item["brand"],
                "summary": item["summary"],
                "verification_checks": item.get("verification_checks", []),
                "verification_source_domains": item.get(
                    "verification_source_domains", []
                ),
            }
            for item in verified
        ],
    }
    packet["bekki_final_persona"] = _load_bekki_light_persona()
    for attempt in range(2):
        try:
            raw = tools.run_ai_prompt(
                "prompts/casper_product_recommendation_final.txt",
                json.dumps(packet, ensure_ascii=False, separators=(",", ":")),
                expect_json=True,
                num_ctx=4096,
                num_predict=1600,
                think=False,
                model_name="gemma4:12b",
            )
        except Exception as error:
            print(
                "[CASPER RECOMMENDATION FINAL ERROR]",
                "attempt=" + str(attempt + 1),
                repr(error),
            )
            break
        if isinstance(raw, dict):
            by_title = {
                " ".join(str(item.get("title") or "").split()).casefold(): item
                for item in verified
                if str(item.get("title") or "").strip()
            }
            bound_count = 0
            raw_items = raw.get("items")
            if not isinstance(raw_items, list):
                raw_items = []
            for value in raw_items[: len(verified)]:
                if not isinstance(value, dict):
                    continue
                title_key = " ".join(
                    str(value.get("title") or "").split()
                ).casefold()
                candidate = by_title.get(title_key)
                if candidate is None:
                    continue
                context = " ".join(
                    str(value.get("context") or "").split()
                ).strip()[:900]
                raw_pros = value.get("pros")
                if not isinstance(raw_pros, list):
                    raw_pros = []
                raw_cons = value.get("cons")
                if not isinstance(raw_cons, list):
                    raw_cons = []
                pros = [
                    " ".join(str(item or "").split()).strip()[:240]
                    for item in raw_pros[:3]
                    if str(item or "").strip()
                ]
                cons = [
                    " ".join(str(item or "").split()).strip()[:240]
                    for item in raw_cons[:3]
                    if str(item or "").strip()
                ]
                if context:
                    candidate["card_summary"] = context
                if pros or cons:
                    candidate["presentation_sections"] = [
                        {"kind": "pros_cons", "pros": pros, "cons": cons}
                    ]
                if context or pros or cons:
                    bound_count += 1
            reply = _compact_recommendation_overview(
                user_request,
                raw.get("reply"),
                verified,
            )
            if reply:
                print(
                    "[CASPER RECOMMENDATION CARD CONTEXTS]",
                    "bound=" + str(bound_count),
                    "cards=" + str(len(verified)),
                )
                return reply
        packet["retry_instruction"] = "Return only the required JSON object."
    return _compact_recommendation_overview(user_request, "", verified)


def _compact_recommendation_overview(user_request, reply, verified):
    """Keep the message bubble global; candidate detail belongs to cards."""

    value = str(reply or "").strip()[:1200]
    normalized = " ".join(value.split()).casefold()
    repeats_candidate = any(
        " ".join(str(item.get("title") or "").split()).casefold() in normalized
        for item in verified
        if str(item.get("title") or "").strip()
    )
    list_like = bool(re.search(r"(?:^|\n)\s*(?:\d+[.)]|[-*])\s+", value))
    if value and not repeats_candidate and not list_like and len(value) <= 520:
        return value
    count = len(verified)
    chinese = bool(re.search(r"[\u3400-\u9fff]", str(user_request or "")))
    if chinese:
        return (
            f"我找到 {count} 款通过条件核验的选择。每款的匹配理由、"
            "优缺点、图片和来源已经合并在下方对应卡片中。"
        )
    return (
        f"I found {count} options that passed the requested checks. Each "
        "option's fit, pros and cons, image, and source are combined in its "
        "matching card below."
    )


def _build_recommendation_shortfall_reply(
    user_request,
    plan,
    rejected,
    source_count=0,
):
    """Return an actual answer when no candidate survives verification."""

    target_count = max(1, int(plan.get("target_count") or 1))
    unique_rejections = []
    seen_titles = set()
    for item in rejected or []:
        title = " ".join(str(item.get("title") or "").split()).strip()[:180]
        if not title or title.casefold() in seen_titles:
            continue
        seen_titles.add(title.casefold())
        reason = " ".join(str(item.get("reason") or "").split()).strip()[:420]
        failed = [
            " ".join(str(value or "").split()).strip()[:120]
            for value in item.get("failed_conditions", [])[:4]
            if str(value or "").strip()
        ]
        if not reason and failed:
            reason = ", ".join(failed)
        unique_rejections.append((title, reason))
        if len(unique_rejections) >= target_count:
            break

    chinese = bool(re.search(r"[\u3400-\u9fff]", str(user_request or "")))
    if chinese:
        lines = [
            "### 这次还没有足够的已验证推荐",
            "",
            f"你要 {target_count} 款，但这轮没有候选同时通过全部硬条件；"
            "因此我不会把评测文章标题冒充成产品答案。",
        ]
        if unique_rejections:
            lines.extend(["", "未通过的候选：", ""])
            for title, reason in unique_rejections:
                detail = reason or "现有证据不足以确认所有条件。"
                lines.append(f"- **{title}** — {detail}")
        else:
            lines.extend(
                ["", "候选生成结果不完整，暂时没有可安全列出的产品。"]
            )
        if source_count:
            lines.extend(
                [
                    "",
                    f"下方保留 {source_count} 条独立评测来源作为继续核验的线索；"
                    "它们不是已验证推荐，也不代表实时价格或库存。",
                ]
            )
    else:
        lines = [
            "### Not enough verified recommendations yet",
            "",
            f"You asked for {target_count}, but no candidate passed every hard "
            "requirement in this run. I will not present article titles as "
            "product recommendations.",
        ]
        if unique_rejections:
            lines.extend(["", "Candidates that did not pass:", ""])
            for title, reason in unique_rejections:
                detail = reason or (
                    "The available evidence did not verify every condition."
                )
                lines.append(f"- **{title}** — {detail}")
        else:
            lines.extend(
                ["", "Candidate generation was incomplete, so there is no safe list yet."]
            )
        if source_count:
            lines.extend(
                [
                    "",
                    f"The {source_count} independent review sources below are research "
                    "leads, not verified recommendations or live price/stock claims.",
                ]
            )
    return "\n".join(lines)[:5000]


def product_recommendation_controller(
    user_request,
    recent_context="",
    status_callback=None,
):
    """Run an AI-owned editorial recommendation flow, separate from shopping."""
    import result_cards
    import shopping_region
    import tools

    _status(status_callback, "Casper 正在让 AI 理解推荐主题… 🧭")
    # gpt-oss has already completed the main routing decision.  On the user's
    # 16 GB GPU, asking that 20B runner for another back-to-back generation can
    # terminate llama-server with CUDA shared-object initialization failure.
    # Release both routing residents before loading the already-required 12B
    # AI that owns recommendation planning and synthesis.
    for model_name in ("gemma4:12b", "llama3.2:latest"):
        try:
            tools.unload_model(model_name)
        except Exception as error:
            print(
                "[CASPER RECOMMENDATION MODEL UNLOAD SKIPPED]",
                model_name,
                repr(error),
            )
    region = shopping_region.detect_shopping_region()
    try:
        import location as runtime_location

        runtime_profile = runtime_location.detect_location()
    except (ImportError, AttributeError, OSError, TypeError, ValueError):
        runtime_profile = {}
    if not isinstance(region, dict):
        region = {}
    region = dict(region)
    for key in (
        "country_code",
        "country_name",
        "location_name",
        "time_zone",
        "unit_system",
        "preferred_search_engines",
        "source",
        "confidence",
    ):
        if not region.get(key) and runtime_profile.get(key):
            region[key] = runtime_profile[key]
    plan = _build_ai_recommendation_plan(user_request, recent_context, region)
    if not plan:
        try:
            tools.unload_model("gemma4:12b")
        except Exception as error:
            print("[CASPER RECOMMENDATION MODEL CLEANUP SKIPPED]", repr(error))
        return {
            "status": "PLANNING_FAILED",
            "results": [],
            "cards": [],
            "region": region,
        }
    engine_plan = plan["engines"]
    query = plan["search_queries"][0]
    _status(status_callback, "Casper 正在查找独立评测与推荐榜单… 📊")
    sources, last_discovery_status = _collect_recommendation_sources(
        plan["search_queries"],
        region,
        engine_plan,
        status_callback=status_callback,
        limit=6,
    )
    if not sources:
        try:
            tools.unload_model("gemma4:12b")
        except Exception as error:
            print("[CASPER RECOMMENDATION MODEL CLEANUP SKIPPED]", repr(error))
        return {
            "status": (
                "NO_RECOMMENDATION_SOURCES"
                if last_discovery_status == "OK"
                else last_discovery_status
            ),
            "query": query,
            "results": [],
            "cards": [],
            "region": region,
        }
    _status(status_callback, "Casper 正在根据搜索摘要生成候选… ✨")
    packet = {
        "current_date": datetime.now().date().isoformat(),
        "original_user_request": str(user_request)[:900],
        "topic": plan["topic"],
        "criteria": plan["criteria"],
        "audience_scope": plan["audience_scope"],
        "audience": plan["audience"],
        "count_policy": plan["count_policy"],
        "target_count": plan["target_count"],
        "sources": sources,
    }
    initial_options, _ = _ask_ai_for_recommendation_options(packet)
    _status(status_callback, "Casper 正在逐个反查候选是否符合条件… 🔎")
    verified, rejected = _verify_ai_recommendation_options(
        initial_options,
        user_request,
        plan,
        region,
        engine_plan,
        status_callback=status_callback,
    )
    attempted_titles = [item["title"] for item in initial_options]
    reading_sources = [dict(source) for source in sources]

    needs_recovery = (
        bool(rejected)
        or not verified
        or (
            plan["count_policy"] == "USER_EXPLICIT"
            and len(verified) < plan["target_count"]
        )
    )
    if needs_recovery:
        recovery_queries = _build_ai_recommendation_recovery_queries(
            user_request,
            plan,
            region,
            verified,
            rejected,
        )
        if recovery_queries:
            _status(status_callback, "Casper 正在自动补搜其他候选… 🔄")
            # Recovery is a fresh evidence batch. Seeding the collector with
            # pass-one sources suppresses every result from an already-seen
            # domain and previously made this second pass a silent no-op.
            recovery_sources, _ = _collect_recommendation_sources(
                recovery_queries,
                region,
                engine_plan,
                status_callback=status_callback,
                existing_sources=None,
                limit=6,
            )
            if recovery_sources:
                seen_reading_urls = {
                    str(source.get("url") or "").strip()
                    for source in reading_sources
                    if str(source.get("url") or "").strip()
                }
                for source in recovery_sources:
                    source_url = str(source.get("url") or "").strip()
                    if source_url and source_url not in seen_reading_urls:
                        reading_sources.append(dict(source))
                        seen_reading_urls.add(source_url)
                # Recovery candidate generation sees only evidence returned by
                # the new AI-created queries, so rejected products cannot
                # steer it back toward the same failed shortlist.
                recovery_sources = [dict(source) for source in recovery_sources]
                for index, source in enumerate(recovery_sources, start=1):
                    source["index"] = index
                recovery_packet = dict(packet)
                recovery_packet["sources"] = recovery_sources
                recovery_packet["excluded_titles"] = attempted_titles
                recovery_packet["remaining_target"] = max(
                    0,
                    plan["target_count"] - len(verified),
                )
                recovery_options, _ = _ask_ai_for_recommendation_options(
                    recovery_packet
                )
                if recovery_options:
                    recovered_verified, recovered_rejected = (
                        _verify_ai_recommendation_options(
                            recovery_options,
                            user_request,
                            plan,
                            region,
                            engine_plan,
                            status_callback=status_callback,
                        )
                    )
                    verified.extend(recovered_verified)
                    rejected.extend(recovered_rejected)

    options = verified[:plan["target_count"]]
    direct_reply = _build_ai_verified_recommendation_reply(
        user_request,
        plan,
        options,
    )
    try:
        tools.unload_model("gemma4:12b")
    except Exception as error:
        print("[CASPER RECOMMENDATION MODEL CLEANUP SKIPPED]", repr(error))
    print(
        "[CASPER AI RECOMMENDATION OPTIONS]",
        "selected=" + str(len(options)),
        "target=" + str(plan["target_count"]),
        "policy=" + plan["count_policy"],
        "rejected=" + str(len(rejected)),
    )
    cards = result_cards.clean_cards(
        [
            {
                "type": "article",
                "title": item["title"],
                "summary": item.get("card_summary") or item["summary"],
                "url": item["url"],
                "domain": item["domain"],
                "metadata": {
                    "brand": item["brand"],
                    "evidence_type": "independent_recommendation",
                    "source_count": item["source_count"],
                    "source_domains": item["source_domains"],
                    "verification_source_count": item.get(
                        "verification_source_count", 0
                    ),
                    "verification_source_domains": item.get(
                        "verification_source_domains", []
                    ),
                    "captured_at": datetime.now().astimezone().isoformat(),
                },
                "sections": item.get("presentation_sections", []),
                "requirements": [],
            }
            for item in options
        ]
    )[:8]
    if not cards and reading_sources:
        # A truncated/invalid candidate JSON must not erase the useful
        # independent sources already found.  Render them honestly as reading
        # leads, not as verified product recommendations.
        fallback_limit = min(5, max(1, int(plan.get("target_count") or 1)))
        cards = result_cards.clean_cards(
            [
                {
                    "type": "article",
                    "title": str(source.get("title") or source.get("domain") or "")[:180],
                    "summary": str(source.get("description") or "")[:600],
                    "url": str(source.get("url") or "")[:2048],
                    "domain": str(source.get("domain") or "")[:180],
                    "metadata": {
                        "evidence_type": "independent_reading_source",
                        "published_at": str(source.get("published") or "")[:160],
                        "captured_at": datetime.now().astimezone().isoformat(),
                    },
                    "requirements": [],
                }
                for source in reading_sources[:fallback_limit]
                if source.get("url") and (source.get("title") or source.get("domain"))
            ]
        )
        if cards:
            direct_reply = _build_recommendation_shortfall_reply(
                user_request,
                plan,
                rejected,
                source_count=len(cards),
            )
            print("[CASPER RECOMMENDATION SOURCE FALLBACK]", len(cards))
    if not direct_reply:
        direct_reply = _build_recommendation_shortfall_reply(
            user_request,
            plan,
            rejected,
            source_count=len(cards) if not options else 0,
        )
    card_context_label = (
        "Verified recommendation cards:"
        if options
        else "Independent reading-source cards (not verified recommendations):"
    )
    context = (
        "melchior response mode: RECOMMENDATION_RESEARCH\n"
        "evidence_route: independent_recommendation_sources\n"
        "These candidates were discovered from editorial recommendations and "
        "then checked against candidate-specific non-merchant evidence. "
        "This is not a purchase or inventory check. "
        "Do not claim a current price, stock state, or merchant availability. "
        "The AI owns topic interpretation, criteria, ranking, and count. "
        "Python only executed AI-created searches and bound source indexes. "
        "Give the recommendation first and explain only the supplied evidence.\n\n"
        + card_context_label
        + "\n"
        + json.dumps(cards, ensure_ascii=False, indent=2)
    )
    target_satisfied = bool(cards) and (
        plan["count_policy"] != "USER_EXPLICIT"
        or len(cards) >= plan["target_count"]
    )
    return {
        "status": "OK" if target_satisfied and options else (
            "PARTIAL_RECOMMENDATIONS" if options else (
                "LIMITED_RECOMMENDATION_EVIDENCE"
                if cards else "NO_VERIFIED_RECOMMENDATIONS"
            )
        ),
        "query": query,
        "results": options,
        "cards": cards,
        "region": region,
        "requirements": plan["criteria"],
        "recommendation_plan": plan,
        "context": context,
        "direct_reply": direct_reply,
        "evidence_route": "independent_recommendation_sources",
    }


def _verified_brand_evidence(brand, verified_brands):
    normalized = _canonical_brand_key(brand)
    if not normalized:
        return None
    for item in verified_brands or []:
        candidate = _canonical_brand_key(item.get("name"))
        if candidate and candidate == normalized:
            return item
    return None


def _canonical_brand_key(value):
    tokens = _normalized_brand(value).split()
    removable_suffixes = {
        "brand", "brands", "co", "company", "corp", "corporation",
        "inc", "llc", "ltd", "limited",
    }
    while len(tokens) > 1 and (
        tokens[-1] in removable_suffixes or tokens[-1].isdigit()
    ):
        tokens.pop()
    return " ".join(tokens)


def _parse_compact_count(value):
    text = str(value or "").casefold().replace(",", "").strip()
    match = re.search(r"(\d+(?:\.\d+)?)\s*([km]?)", text)
    if not match:
        return 0
    number = float(match.group(1))
    if match.group(2) == "k":
        number *= 1000
    elif match.group(2) == "m":
        number *= 1000000
    return int(number)


def _is_unrequested_bulk_or_disposable(user_request, item):
    request = str(user_request or "").casefold()
    if any(
        term in request
        for term in (
            "一次性", "纸杯", "塑料杯", "批量", "整箱", "整包", "套装",
            "disposable", "bulk", "multipack", "pack of", "case of",
        )
    ):
        return False
    material = " ".join(
        str(item.get(key) or "")
        for key in ("product_title", "product_summary", "title", "summary")
    ).casefold()
    return bool(
        re.search(r"\b(?:1[0-9]|[2-9][0-9]|[1-9][0-9]{2,})\s*[- ]?(?:pack|count|ct)\b", material)
        or re.search(r"\b(?:disposable|single[- ]use)\s+(?:plastic\s+|paper\s+)?cups?\b", material)
    )


def _is_explicitly_unavailable(item):
    stock = str(item.get("stock") or "").casefold().strip()
    return any(
        term in stock
        for term in ("out of stock", "sold out", "unavailable", "缺货", "无货")
    )


def _select_shopping_products(user_request, plan, products):
    """Deterministically rank grounded products and enforce brand diversity."""
    verified_brands = plan.get("verified_brand_evidence", [])
    popularity_requirement = str(
        plan.get("popularity_requirement") or "NONE"
    )
    hard_brand_gate = popularity_requirement in {
        "CURRENTLY_TRENDING",
        "ESTABLISHED_BRAND",
    }
    popularity_rank = {"HIGH": 3, "MEDIUM": 2, "UNKNOWN": 1, "LOW": 0}
    quality_rank = {"HIGH": 2, "MEDIUM": 1, "LOW": 0}
    plan_requirements = [
        str(value).strip()
        for value in plan.get("requirements", [])
        if str(value).strip()
    ]
    brand_evidence_requirements = {
        "current cross-source brand trend evidence",
        "established brand evidence",
        "visible demand or review-count evidence",
    }
    candidates = []
    for index, item in enumerate(products, start=1):
        if (
            item.get("page_type") != "PRODUCT"
            or not item.get("is_product_detail_url")
            or _is_explicitly_unavailable(item)
            or _is_unrequested_bulk_or_disposable(user_request, item)
        ):
            continue
        brand = str(item.get("brand") or "").strip()
        if not brand:
            continue
        brand_evidence = _verified_brand_evidence(brand, verified_brands)
        raw_brand_key = _canonical_brand_key(brand)
        verified_keys = {
            _canonical_brand_key(value.get("name"))
            for value in verified_brands
            if _canonical_brand_key(value.get("name"))
        }
        ambiguous_verified_prefix = any(
            raw_brand_key != verified_key
            and min(len(raw_brand_key), len(verified_key)) >= 3
            and (
                raw_brand_key.startswith(verified_key)
                or verified_key.startswith(raw_brand_key)
            )
            for verified_key in verified_keys
        )
        if not brand_evidence and ambiguous_verified_prefix:
            continue
        popularity_status = str(
            item.get("popularity_status") or "UNKNOWN"
        ).upper().strip()
        popularity_evidence = str(item.get("popularity_evidence") or "").strip()
        product_demand_grounded = (
            popularity_status in {"HIGH", "MEDIUM"}
            and bool(popularity_evidence)
        )
        if hard_brand_gate and not brand_evidence:
            continue
        # Generic recommendations also prefer demonstrated demand. Unknown,
        # niche products may not fill all three slots merely to hit a count.
        if not hard_brand_gate and not brand_evidence and not product_demand_grounded:
            continue
        requirement_statuses = {
            str(row.get("requirement") or "").strip(): str(
                row.get("status") or "UNKNOWN"
            ).upper().strip()
            for row in item.get("requirements", [])
            if isinstance(row, dict)
        }
        if any(
            (
                requirement in brand_evidence_requirements
                and not (
                    brand_evidence
                    or (
                        requirement == "visible demand or review-count evidence"
                        and product_demand_grounded
                    )
                )
            )
            or (
                requirement not in brand_evidence_requirements
                and requirement_statuses.get(requirement) != "MATCH"
            )
            for requirement in plan_requirements
        ):
            continue
        try:
            fit_score = max(0, min(100, int(item.get("fit_score", 0))))
        except (TypeError, ValueError):
            fit_score = 0
        try:
            source_score = int(item.get("source_score", 50) or 50)
        except (TypeError, ValueError):
            source_score = 50
        score = (
            int(bool(brand_evidence)),
            int((brand_evidence or {}).get("source_count", 0)),
            popularity_rank.get(popularity_status, 1),
            _parse_compact_count(item.get("review_count")),
            quality_rank.get(str(item.get("evidence_quality") or "LOW").upper(), 0),
            fit_score,
            source_score,
        )
        candidates.append((score, index, item, brand_evidence))

    candidates.sort(key=lambda value: value[0], reverse=True)
    selected = []
    seen_brands = set()
    for _score, index, item, brand_evidence in candidates:
        brand_key = _canonical_brand_key(
            (brand_evidence or {}).get("name") or item.get("brand")
        )
        if not brand_key or brand_key in seen_brands:
            continue
        seen_brands.add(brand_key)
        item["brand_evidence"] = brand_evidence or {}
        selected.append(index)
        if len(selected) >= 3:
            break
    return selected


def _balanced_shopping_candidates(scored, query_keys, limit=6):
    """Preserve cross-brand/query coverage after global source scoring."""
    ordered_keys = [key for key in query_keys if key]
    grouped = {key: [] for key in ordered_keys}
    ungrouped = []
    for item in scored or []:
        key = str(item.get("shopping_query_key") or "")
        if key in grouped:
            grouped[key].append(item)
        else:
            ungrouped.append(item)
    selected = []
    selected_urls = set()
    for round_index in range(2):
        for key in ordered_keys:
            values = grouped.get(key, [])
            if len(values) <= round_index:
                continue
            item = values[round_index]
            url = str(item.get("url") or "")
            if url and url not in selected_urls:
                selected.append(item)
                selected_urls.add(url)
            if len(selected) >= limit:
                return selected
    for item in list(scored or []) + ungrouped:
        url = str(item.get("url") or "")
        if not url or url in selected_urls:
            continue
        selected.append(item)
        selected_urls.add(url)
        if len(selected) >= limit:
            break
    return selected


def _merchant_source_priority(source):
    domain = str(source.get("domain") or "").casefold().removeprefix("www.")
    material = (
        str(source.get("title") or "")
        + " "
        + str(source.get("description") or "")
        + " "
        + str(source.get("url") or "")
    ).casefold()
    major_retailers = {
        "amazon.com", "walmart.com", "target.com", "costco.com", "rei.com",
        "dickssportinggoods.com", "academy.com", "macys.com", "nordstrom.com",
        "bestbuy.com",
    }
    strong_commerce_terms = (
        "official store", "official site", "online store", "shop online",
        "add to cart", "product page", "retailer", "storefront",
        "/products/", "/product/", "/shop/", "/store/", "/collections/",
    )
    weak_commerce_terms = ("buy ", "price", "in stock", "free shipping")
    score = 100 if domain in major_retailers else 0
    has_strong_commerce_signal = any(
        term in material for term in strong_commerce_terms
    )
    weak_commerce_count = sum(
        1 for term in weak_commerce_terms if term in material
    )
    has_commerce_signal = has_strong_commerce_signal or weak_commerce_count >= 2
    if has_commerce_signal:
        score += 25
    if (
        _merchant_has_known_detail_contract(domain)
        and _merchant_product_url(domain, source.get("url", ""))
    ):
        score += 20
    if domain not in major_retailers and not has_commerce_signal:
        score -= 80
    if domain.endswith((".gov", ".edu")):
        score -= 200
    if any(
        term in material
        for term in (
            "review", "comparison", "roundup", "best brands", "buying guide",
            "shopping guide", "best cups to buy", "news", "editorial",
        )
    ):
        score -= 100
    return score


def _discover_shopping_merchants(
    user_request,
    plan,
    region,
    status_callback=None,
    engine_plan=None,
    brand_evidence=None,
):
    """Let AI choose merchants only from domains Casper actually discovered."""
    import tools

    queries = plan.get("queries", [])
    verified_names = [
        str(item.get("name") or "").strip()
        for item in (brand_evidence or [])[:5]
        if str(item.get("name") or "").strip()
    ]
    core_query = (
        " ".join(verified_names)
        + " "
        + str(plan.get("product_query") or (queries[0] if queries else user_request))
    ).strip()
    country = str(region.get("country_name", "") or region.get("country_code", ""))
    discovery_query = (core_query + " buy online " + country).strip()[:240]
    discovery = discover_web(
        discovery_query,
        count=12,
        status_callback=status_callback,
        country_code=region.get("country_code"),
        engine_plan=engine_plan,
    )
    if discovery.get("status") == "HUMAN_HANDOFF":
        return {"status": "HUMAN_HANDOFF", "event": discovery.get("event", "captcha")}

    sources = []
    seen = set()
    for item in discovery.get("results", []):
        if not isinstance(item, dict):
            continue
        domain = str(item.get("domain", "")).lower().strip().removeprefix("www.")
        if not domain or domain in seen:
            continue
        seen.add(domain)
        sources.append(
            {
                "index": len(sources) + 1,
                "domain": domain,
                "title": str(item.get("title", ""))[:240],
                "description": str(item.get("description", ""))[:500],
                "url": str(item.get("url", ""))[:1000],
            }
        )
    if not sources:
        return {"status": "NO_RESULTS", "merchants": []}

    try:
        ai_sources = [
            {
                "index": item["index"],
                "domain": item["domain"],
                "title": item["title"][:180],
                "description": item["description"][:240],
            }
            for item in sources
        ]
        result = tools.run_ai_prompt(
            "prompts/casper_shopping_merchants.txt",
            json.dumps(
                {
                    "shopping_region": region,
                    "original_user_request": str(user_request),
                    "shopping_plan": {
                        "product_query": plan.get("product_query", ""),
                        "popularity_requirement": plan.get(
                            "popularity_requirement", "NONE"
                        ),
                    },
                    "verified_brand_names": verified_names,
                    "discovered_sources": ai_sources,
                },
                ensure_ascii=False,
                separators=(",", ":"),
            ),
            expect_json=True,
            num_ctx=4096,
            num_predict=160,
            think=False,
            model_name="llama3.2:latest",
            json_schema={
                "type": "object",
                "properties": {
                    "source_indexes": {
                        "type": "array",
                        "items": {"type": "integer"},
                        "maxItems": 4,
                    }
                },
                "required": ["source_indexes"],
            },
        )
    except Exception as error:
        print("[CASPER MERCHANT PLAN ERROR]", repr(error))
        result = None
    selected = result.get("source_indexes") if isinstance(result, dict) else None
    if not isinstance(selected, list):
        selected = []

    by_index = {item["index"]: item for item in sources}
    selected_indexes = []
    for value in selected[:6]:
        try:
            source_index = int(value)
        except (TypeError, ValueError):
            continue
        if source_index not in by_index or source_index in selected_indexes:
            continue
        if _merchant_source_priority(by_index[source_index]) < 0:
            continue
        selected_indexes.append(source_index)

    fallback_indexes = [
        item["index"]
        for item in sorted(
            sources,
            key=lambda item: (_merchant_source_priority(item), -item["index"]),
            reverse=True,
        )
        if _merchant_source_priority(item) >= 0
    ]
    # For mainstream/trending requests, broad verified retailers and official
    # stores rank before niche merchant guesses. AI still selects only from
    # discovered domains; Python supplies a bounded fallback on model failure.
    if plan.get("popularity_requirement") != "NONE":
        ordered_indexes = fallback_indexes + selected_indexes
    else:
        ordered_indexes = selected_indexes + fallback_indexes

    merchants = []
    selected_domains = set()
    for source_index in ordered_indexes:
        source = by_index.get(source_index)
        if source is None or source["domain"] in selected_domains:
            continue
        selected_domains.add(source["domain"])
        merchants.append(
            {
                "name": source["domain"],
                "domain": source["domain"],
                "reason": "Discovered merchant or official product source.",
            }
        )
        if len(merchants) >= 4:
            break
    return {
        "status": "OK" if merchants else "NO_VERIFIED_MERCHANTS",
        "merchants": merchants,
        "discovery_query": discovery_query,
        "discovered_sources": sources,
    }


def _exact_lookup_normalize(value):
    """Normalize only for structural source binding, never semantic matching."""
    return re.sub(r"[\W_]+", " ", str(value or "").casefold()).strip()


def _exact_purchase_plan_is_usable(
    value,
    user_request,
    recent_context,
    context_scope,
):
    """Validate the AI plan without deciding what the product means."""
    if not isinstance(value, dict):
        return False
    mode = str(value.get("lookup_mode") or "").upper().strip()
    if mode not in {"EXACT_PRODUCT", "OPEN_ENDED", "UNRESOLVED_REFERENCE"}:
        return False
    if mode != "EXACT_PRODUCT":
        return True

    source_scope = str(value.get("source_scope") or "").upper().strip()
    if source_scope == "CURRENT_REQUEST":
        source = str(user_request or "")
    elif source_scope == "RECENT_CONTEXT" and context_scope == "NEEDS_CONTEXT":
        source = str(recent_context or "")
    else:
        return False

    title = _exact_lookup_normalize(value.get("resolved_title"))
    phrase = _exact_lookup_normalize(value.get("source_phrase"))
    material = _exact_lookup_normalize(source)
    if len(title) < 3 or title != phrase or phrase not in material:
        return False
    brand = _exact_lookup_normalize(value.get("brand"))
    if brand and brand not in title:
        return False
    queries = value.get("search_queries")
    if not isinstance(queries, list) or not 1 <= len(queries) <= 3:
        return False
    return all(
        title in _exact_lookup_normalize(query)
        for query in queries
        if str(query or "").strip()
    ) and all(str(query or "").strip() for query in queries)


def _plan_exact_purchase_lookup(user_request, recent_context, region):
    """Let the 12B AI separate exact-item lookup from category shopping."""
    import tools

    context_scope = tools._shopping_context_scope(user_request)
    packet = {
        "current_request": str(user_request or "")[:1000],
        "context_scope": context_scope,
        "recent_context": (
            str(recent_context or "")[-2600:]
            if context_scope == "NEEDS_CONTEXT"
            else ""
        ),
        "runtime_profile": {
            "country_code": str(region.get("country_code") or "US"),
            "country_name": str(region.get("country_name") or "United States"),
            "units": str(region.get("units") or "US_CUSTOMARY"),
            "preferred_search_engines": ["google", "bing"],
        },
    }
    prompts = (
        "prompts/casper_exact_purchase_plan.txt",
        "prompts/casper_exact_purchase_plan_retry.txt",
    )
    for attempt, prompt_path in enumerate(prompts, start=1):
        attempt_packet = dict(packet)
        if attempt > 1:
            attempt_packet["retry_reason"] = (
                "The previous answer was invalid or did not copy an exact "
                "product identity from its declared source."
            )
        try:
            value = tools.run_ai_prompt(
                prompt_path,
                json.dumps(attempt_packet, ensure_ascii=False, indent=2),
                expect_json=True,
                num_ctx=4096,
                num_predict=600,
                think=False,
                model_name="gemma4:12b",
            )
        except Exception as error:
            print("[CASPER EXACT PURCHASE PLAN ERROR]", "attempt=" + str(attempt), repr(error))
            continue
        if _exact_purchase_plan_is_usable(
            value,
            user_request,
            recent_context,
            context_scope,
        ):
            plan = dict(value)
            plan["lookup_mode"] = str(plan.get("lookup_mode")).upper().strip()
            plan["context_scope"] = context_scope
            plan["resolved_title"] = str(plan.get("resolved_title") or "").strip()[:220]
            plan["brand"] = str(plan.get("brand") or "").strip()[:100]
            plan["search_queries"] = [
                re.sub(r"\s+", " ", str(query)).strip()[:260]
                for query in plan.get("search_queries", [])[:3]
                if str(query).strip()
            ]
            print(
                "[CASPER EXACT PURCHASE PLAN]",
                json.dumps(plan, ensure_ascii=False),
            )
            return plan
        print("[CASPER EXACT PURCHASE PLAN REJECTED]", "attempt=" + str(attempt))
    return {
        "lookup_mode": (
            "UNRESOLVED_REFERENCE"
            if context_scope == "NEEDS_CONTEXT"
            else "PLAN_UNAVAILABLE"
        ),
        "context_scope": context_scope,
        "resolved_title": "",
        "brand": "",
        "search_queries": [],
        "reason": "Exact-purchase classifier did not return a grounded contract.",
    }


def _accept_exact_purchase_candidates(raw, search_results):
    items = raw.get("items") if isinstance(raw, dict) else None
    if not isinstance(items, list):
        return []
    accepted = []
    used = set()
    for item in items[:6]:
        if not isinstance(item, dict):
            continue
        try:
            index = int(item.get("candidate_index"))
        except (TypeError, ValueError):
            continue
        if index < 1 or index > len(search_results) or index in used:
            continue
        claimed_identity = str(item.get("claimed_identity") or "").strip()[:240]
        merchant = str(item.get("merchant") or "").strip()[:120]
        if not claimed_identity or not merchant:
            continue
        used.add(index)
        candidate = dict(search_results[index - 1])
        candidate.update(
            {
                "candidate_id": len(accepted) + 1,
                "search_result_index": index,
                "claimed_identity": claimed_identity,
                "claimed_merchant": merchant,
                "proposal_reason": str(item.get("reason") or "").strip()[:400],
            }
        )
        accepted.append(candidate)
        if len(accepted) >= 4:
            break
    return accepted


def _accept_exact_purchase_audit(raw, valid_candidate_ids):
    items = raw.get("items") if isinstance(raw, dict) else None
    if not isinstance(items, list):
        return {}
    required = {"EXACT_IDENTITY", "REAL_PURCHASE_SOURCE", "PURCHASE_ENTRY"}
    output = {}
    for item in items:
        if not isinstance(item, dict):
            continue
        try:
            candidate_id = int(item.get("candidate_id"))
        except (TypeError, ValueError):
            continue
        if candidate_id not in valid_candidate_ids or candidate_id in output:
            continue
        verdict = str(item.get("verdict") or "").upper().strip()
        if verdict not in {"PASS", "REJECT", "NEEDS_PAGE", "UNVERIFIED"}:
            continue
        checks = item.get("checks")
        if not isinstance(checks, list):
            checks = []
        statuses = {}
        clean_checks = []
        for row in checks:
            if not isinstance(row, dict):
                continue
            condition = str(row.get("condition") or "").upper().strip()
            status = str(row.get("status") or "").upper().strip()
            if condition in required and status in {"SUPPORTED", "CONTRADICTED", "MISSING"}:
                statuses[condition] = status
                clean_checks.append(
                    {
                        "condition": condition,
                        "status": status,
                        "reason": str(row.get("reason") or "").strip()[:400],
                    }
                )
        if verdict == "PASS" and not all(
            statuses.get(condition) == "SUPPORTED" for condition in required
        ):
            verdict = "UNVERIFIED"
        output[candidate_id] = {
            "verdict": verdict,
            "listing_title": str(item.get("listing_title") or "").strip()[:240],
            "merchant": str(item.get("merchant") or "").strip()[:120],
            "summary": str(item.get("summary") or "").strip()[:700],
            "price": str(item.get("price") or "UNKNOWN").strip()[:80] or "UNKNOWN",
            "currency": str(item.get("currency") or "UNKNOWN").strip()[:30] or "UNKNOWN",
            "stock": str(item.get("stock") or "UNKNOWN").strip()[:100] or "UNKNOWN",
            "checks": clean_checks,
            "errors_found": [
                str(value).strip()[:300]
                for value in item.get("errors_found", [])[:6]
                if str(value).strip()
            ] if isinstance(item.get("errors_found"), list) else [],
            "reason": str(item.get("reason") or "").strip()[:500],
        }
    return output


def _reconcile_exact_purchase_identity(audits, candidates, target_plan):
    """Correct an audit that rejects an exact name merely for extra options."""
    target_key = _exact_lookup_normalize(target_plan.get("resolved_title"))
    if not target_key:
        return audits
    reconciled = dict(audits)
    for candidate in candidates:
        candidate_id = candidate.get("candidate_id")
        audit = reconciled.get(candidate_id)
        if not isinstance(audit, dict):
            continue
        identity_material = (
            str(candidate.get("title") or "") + " "
            + str(audit.get("listing_title") or "")
        )
        if target_key not in _exact_lookup_normalize(identity_material):
            continue
        exact_check = next(
            (
                row for row in audit.get("checks", [])
                if row.get("condition") == "EXACT_IDENTITY"
            ),
            None,
        )
        if not exact_check or exact_check.get("status") != "CONTRADICTED":
            continue
        exact_check["status"] = "SUPPORTED"
        exact_check["reason"] = (
            "The complete target name is present. Extra capacity, lid, color, "
            "or other unrequested option text does not change that identity."
        )
        statuses = {
            row.get("condition"): row.get("status")
            for row in audit.get("checks", [])
        }
        if all(
            statuses.get(condition) == "SUPPORTED"
            for condition in (
                "EXACT_IDENTITY",
                "REAL_PURCHASE_SOURCE",
                "PURCHASE_ENTRY",
            )
        ):
            audit["verdict"] = "PASS"
            audit["reason"] = (
                "The complete target product-line name and a real purchase "
                "entry are supported; only unrequested options were added."
            )
        print(
            "[CASPER EXACT IDENTITY RECONCILED]",
            str(candidate_id),
            target_plan.get("resolved_title", ""),
        )
    return reconciled


def _audit_exact_purchase_candidates(
    user_request,
    target_plan,
    candidates,
    ai_summaries,
    page_escalation=False,
):
    import tools

    packet_candidates = []
    for candidate in candidates:
        packet_candidates.append(
            {
                "candidate_id": candidate.get("candidate_id"),
                "claimed_identity": candidate.get("claimed_identity", ""),
                "claimed_merchant": candidate.get("claimed_merchant", ""),
                "domain": candidate.get("domain", ""),
                "search_title": candidate.get("title", ""),
                "search_description": candidate.get("description", ""),
                "page_success": candidate.get("page_success", False),
                "page_content": str(candidate.get("page_content", ""))[:7000],
                "structured_product": str(candidate.get("structured_product", ""))[:3000],
            }
        )
    try:
        raw = tools.run_ai_prompt(
            "prompts/casper_exact_purchase_audit.txt",
            json.dumps(
                {
                    "original_user_request": str(user_request or "")[:1000],
                    "target": {
                        "resolved_title": target_plan.get("resolved_title", ""),
                        "brand": target_plan.get("brand", ""),
                    },
                    "page_escalation": bool(page_escalation),
                    "search_engine_ai_summaries": ai_summaries,
                    "candidates": packet_candidates,
                },
                ensure_ascii=False,
                indent=2,
            ),
            expect_json=True,
            num_ctx=8192,
            num_predict=1400,
            think=False,
            model_name="gemma4:12b",
        )
    except Exception as error:
        print("[CASPER EXACT PURCHASE AUDIT ERROR]", repr(error))
        return {}
    accepted = _accept_exact_purchase_audit(
        raw,
        {int(item.get("candidate_id")) for item in candidates},
    )
    return _reconcile_exact_purchase_identity(
        accepted,
        candidates,
        target_plan,
    )


def _exact_purchase_lookup_controller(
    user_request,
    target_plan,
    region,
    status_callback=None,
):
    """Find purchase entries for one exact item without recommendation gates."""
    import result_cards
    import tools

    title = target_plan.get("resolved_title", "")
    queries = target_plan.get("search_queries", [])[:3]
    engine_plan = _search_engine_policy(
        region.get("country_code"),
        queries[0] if queries else title,
    )
    _status(status_callback, "Casper 正在查找这个确切商品的购买入口… 🛒")
    search_results = []
    ai_summaries = []
    seen_urls = set()
    protected_event = ""
    for query in queries:
        discovery = discover_web(
            query,
            count=8,
            status_callback=status_callback,
            country_code=region.get("country_code"),
            engine_plan=engine_plan,
            minimum_results=4,
        )
        if discovery.get("status") == "HUMAN_HANDOFF":
            protected_event = str(discovery.get("event") or "access_block")
            continue
        ai_summaries.extend(discovery.get("ai_summaries", []))
        for item in discovery.get("results", []):
            url = str(item.get("url") or "").strip()
            try:
                parsed = urlparse(url)
            except ValueError:
                continue
            if (
                parsed.scheme != "https"
                or not parsed.netloc
                or parsed.username
                or parsed.password
                or url in seen_urls
            ):
                continue
            seen_urls.add(url)
            search_results.append(item)
            if len(search_results) >= 14:
                break
        if len(search_results) >= 14:
            break
    if not search_results:
        return {
            "status": "HUMAN_HANDOFF" if protected_event else "NO_RESULTS",
            "query": " | ".join(queries),
            "results": [],
            "cards": [],
            "pending_approval": (
                {"event": protected_event, "reason": "Search requires human verification."}
                if protected_event else None
            ),
        }

    proposal_packet = {
        "original_user_request": str(user_request or "")[:1000],
        "target": {
            "resolved_title": title,
            "brand": target_plan.get("brand", ""),
        },
        "search_engine_ai_summaries": ai_summaries,
        "search_results": [
            {
                "index": index,
                "title": item.get("title", ""),
                "description": item.get("description", ""),
                "domain": item.get("domain", ""),
            }
            for index, item in enumerate(search_results, start=1)
        ],
    }
    try:
        raw_candidates = tools.run_ai_prompt(
            "prompts/casper_exact_purchase_candidates.txt",
            json.dumps(proposal_packet, ensure_ascii=False, indent=2),
            expect_json=True,
            num_ctx=6144,
            num_predict=800,
            think=False,
            model_name="gemma4:12b",
        )
    except Exception as error:
        print("[CASPER EXACT PURCHASE CANDIDATES ERROR]", repr(error))
        raw_candidates = None
    candidates = _accept_exact_purchase_candidates(raw_candidates, search_results)
    if not candidates:
        return {
            "status": "NO_EXACT_PURCHASE_CANDIDATES",
            "query": " | ".join(queries),
            "results": search_results,
            "cards": [],
            "region": region,
            "lookup_mode": "EXACT_PRODUCT",
        }

    _status(status_callback, "Casper 正在反向检查商品身份和购买入口… ✅")
    audits = _audit_exact_purchase_candidates(
        user_request,
        target_plan,
        candidates,
        ai_summaries,
        page_escalation=False,
    )
    needs_page = [
        candidate
        for candidate in candidates
        if audits.get(candidate.get("candidate_id"), {}).get("verdict") == "NEEDS_PAGE"
    ]
    escalated = []
    for candidate in needs_page:
        try:
            page = read_url(candidate.get("url", ""))
        except Exception as error:
            print("[CASPER EXACT PURCHASE PAGE ERROR]", repr(error))
            continue
        if page.get("protected_event") or not page.get("success"):
            continue
        enriched = dict(candidate)
        enriched.update(
            {
                "page_success": True,
                "page_content": page.get("content", ""),
                "structured_product": page.get("structured_product", ""),
                "image_url": page.get("image_url", ""),
                "url": page.get("final_url", "") or candidate.get("url", ""),
            }
        )
        escalated.append(enriched)
    if escalated:
        audits.update(
            _audit_exact_purchase_candidates(
                user_request,
                target_plan,
                escalated,
                ai_summaries,
                page_escalation=True,
            )
        )
        escalated_by_id = {item["candidate_id"]: item for item in escalated}
        candidates = [
            escalated_by_id.get(item["candidate_id"], item)
            for item in candidates
        ]

    card_pairs = []
    for candidate in candidates:
        audit = audits.get(candidate.get("candidate_id"), {})
        if audit.get("verdict") != "PASS":
            continue
        merchant = audit.get("merchant") or candidate.get("domain", "")
        listing_title = audit.get("listing_title") or title
        if merchant and _exact_lookup_normalize(merchant) not in _exact_lookup_normalize(listing_title):
            listing_title = title + " — " + merchant
        cleaned = result_cards.clean_cards(
            [
                {
                    "type": "product",
                    "title": listing_title,
                    "summary": audit.get("summary", ""),
                    "url": candidate.get("url", ""),
                    "domain": candidate.get("domain", ""),
                    "image": (
                        {
                            "url": candidate.get("image_url", ""),
                            "alt": title,
                            "source_url": candidate.get("url", ""),
                        }
                        if candidate.get("image_url") else None
                    ),
                    "metadata": {
                        "merchant": merchant,
                        "price": audit.get("price", "UNKNOWN"),
                        "currency": audit.get("currency", "UNKNOWN"),
                        "stock": audit.get("stock", "UNKNOWN"),
                        "brand": target_plan.get("brand", ""),
                        "lookup_mode": "EXACT_PRODUCT",
                        "captured_at": datetime.now().astimezone().isoformat(),
                    },
                    "requirements": [
                        {"requirement": row["condition"], "status": row["status"]}
                        for row in audit.get("checks", [])
                    ],
                }
            ]
        )
        if cleaned:
            card_pairs.append((cleaned[0], candidate, audit))
        if len(card_pairs) >= 3:
            break

    cards = [item[0] for item in card_pairs]
    accepted_results = [item[1] for item in card_pairs]
    print(
        "[CASPER EXACT PURCHASE VERIFIED]",
        "passed=" + str(len(cards)),
        "audited=" + str(len(candidates)),
    )
    return {
        "status": "OK" if cards else "NO_VERIFIED_PURCHASE_ENTRY",
        "query": " | ".join(queries),
        "queries": queries,
        "results": accepted_results,
        "inspected_results": candidates,
        "cards": cards,
        "region": region,
        "lookup_mode": "EXACT_PRODUCT",
        "resolved_title": title,
        "direct_reply": (
            "找到啦 🛒 我已经反向核实了这个商品的购买入口。"
            "点击下方商品卡片即可打开；未显示的价格或库存仍标为未知。"
        ),
        "context": (
            "melchior response mode: SHOPPING_RESEARCH\n"
            "shopping_lookup_mode: EXACT_PRODUCT\n"
            "The user asked where to buy one already identified product. "
            "Casper preserved the complete product identity, used search-engine "
            "summary text only as a lead, and independently audited each direct "
            "purchase entry. Present the verified merchants below. Price and "
            "stock may remain UNKNOWN; do not treat that as failure and do not "
            "invent them. Product links belong to card buttons; do not print raw URLs.\n\n"
            + json.dumps(cards, ensure_ascii=False, indent=2)
        ),
        "discovery_type": "casper_exact_purchase_lookup",
    }


def shopping_research_controller(
    user_request,
    recent_context="",
    status_callback=None,
):
    """Browser-first regional product research with AI-led comparison."""
    import decision_comparison
    import result_cards
    import shopping_region
    import tools

    _status(status_callback, "Casper 正在理解购买条件与地区商家… 🛍️")
    try:
        # Routing just used gpt-oss. Free it before the compact llama planning
        # phase so both models do not compete for the 16 GB GPU.
        tools.unload_model("gemma4:12b")
    except Exception as error:
        print("[CASPER MODEL UNLOAD SKIPPED] gemma4:12b", repr(error))
    region = shopping_region.detect_shopping_region()
    lookup_plan = _plan_exact_purchase_lookup(
        user_request,
        recent_context,
        region,
    )
    lookup_mode = lookup_plan.get("lookup_mode")
    if lookup_mode == "EXACT_PRODUCT":
        try:
            return _exact_purchase_lookup_controller(
                user_request,
                lookup_plan,
                region,
                status_callback=status_callback,
            )
        finally:
            try:
                tools.unload_model("gemma4:12b")
            except Exception as error:
                print("[CASPER MODEL UNLOAD SKIPPED] gemma4:12b", repr(error))
    if lookup_mode == "UNRESOLVED_REFERENCE":
        try:
            return {
                "status": "UNRESOLVED_PRODUCT_REFERENCE",
                "query": "",
                "results": [],
                "cards": [],
                "region": region,
                "context": (
                    "The shopping request refers to an earlier item, but the "
                    "exact product title could not be resolved safely. Ask the "
                    "user to name or paste the product title; do not fall back "
                    "to a generic category search."
                ),
            }
        finally:
            try:
                tools.unload_model("gemma4:12b")
            except Exception as error:
                print("[CASPER MODEL UNLOAD SKIPPED] gemma4:12b", repr(error))
    try:
        tools.unload_model("gemma4:12b")
    except Exception as error:
        print("[CASPER MODEL UNLOAD SKIPPED] gemma4:12b", repr(error))
    plan = tools.build_shopping_plan(
        user_request,
        recent_context,
        region,
        allow_category_translation_repair=True,
    )
    if plan.get("planning_failed") or not plan.get("queries"):
        return {
            "status": "PLANNING_FAILED",
            "query": "",
            "results": [],
            "cards": [],
            "region": region,
            "merchants": [],
        }
    engine_plan = _search_engine_policy(
        region.get("country_code"),
        plan.get("queries", [""])[0],
    )
    if not engine_plan:
        return {
            "status": "ENGINE_PLAN_UNAVAILABLE",
            "query": " | ".join(plan.get("queries", [])),
            "results": [],
            "cards": [],
            "region": region,
            "merchants": [],
        }

    verified_brands = _discover_popular_brands(
        user_request,
        plan,
        region,
        engine_plan,
        status_callback=status_callback,
    )
    plan["verified_brand_evidence"] = verified_brands
    if plan.get("popularity_requirement") in {
        "CURRENTLY_TRENDING",
        "ESTABLISHED_BRAND",
    } and not verified_brands:
        return {
            "status": "NO_BRAND_POPULARITY_EVIDENCE",
            "query": " | ".join(plan.get("queries", [])),
            "results": [],
            "cards": [],
            "region": region,
            "merchants": [],
        }
    merchants = plan.get("merchants", [])
    if plan.get("merchant_scope") != "exclusive":
        _status(status_callback, "Casper 正在确认本地区真实商家… 🧭")
        merchant_discovery = _discover_shopping_merchants(
            user_request,
            plan,
            region,
            status_callback=status_callback,
            engine_plan=engine_plan,
            brand_evidence=verified_brands,
        )
        if merchant_discovery.get("status") == "HUMAN_HANDOFF":
            return {
                "status": "HUMAN_HANDOFF",
                "pending_approval": {
                    "event": merchant_discovery.get("event", "captcha"),
                    "reason": "Merchant discovery requires human control.",
                },
                "results": [],
                "cards": [],
            }
        merchants = merchant_discovery.get("merchants", [])
        plan["merchants"] = merchants
        print(
            "[CASPER VERIFIED MERCHANTS]",
            json.dumps(merchants, ensure_ascii=False),
        )
    merchant_domains = [item.get("domain", "") for item in merchants if item.get("domain")]
    if verified_brands:
        product_query = str(plan.get("product_query") or "").strip()
        ranked_brands = sorted(
            verified_brands,
            key=lambda item: int(item.get("source_count", 0)),
            reverse=True,
        )
        search_brands = []
        seen_search_brand_keys = set()
        for item in ranked_brands:
            brand_key = _canonical_brand_key(item.get("name"))
            if not brand_key or brand_key in seen_search_brand_keys:
                continue
            seen_search_brand_keys.add(brand_key)
            search_brands.append(item)
            if len(search_brands) >= 3:
                break
        query_specs = [
            {
                "query_key": _canonical_brand_key(item.get("name")),
                "query": (
                    '"' + str(item.get("name") or "").strip() + '" '
                    + product_query + " product high review count"
                )[:220],
            }
            for item in search_brands
            if str(item.get("name") or "").strip()
        ]
    else:
        query_specs = [
            {"query_key": "query_" + str(index), "query": str(query)}
            for index, query in enumerate(plan.get("queries", [])[:3], start=1)
            if str(query).strip()
        ]
    queries = [item["query"] for item in query_specs]
    if not merchant_domains or not queries:
        return {
            "status": "NO_MERCHANTS",
            "query": " | ".join(queries),
            "results": [],
            "cards": [],
            "region": region,
            "merchants": merchants,
        }

    scoped_queries = []
    # Round-robin brand/query coverage inside each merchant. One brand cannot
    # consume the global candidate budget before the others are attempted.
    for domain in merchant_domains:
        for query_spec in query_specs:
            scoped_queries.append(
                {
                    "domain": domain,
                    "query_key": query_spec["query_key"],
                    "query": _merchant_discovery_query(
                        domain,
                        query_spec["query"],
                    ),
                }
            )
            if len(scoped_queries) >= 9:
                break
        if len(scoped_queries) >= 9:
            break
    _status(status_callback, "Casper 正在后台浏览器中寻找商品… 🌐")
    discovered = []
    seen_urls = set()
    domain_counts = {domain: 0 for domain in merchant_domains}
    query_counts = {item["query_key"]: 0 for item in query_specs}
    pair_counts = {}
    for scoped in scoped_queries:
        discovery = discover_web(
            scoped["query"],
            count=5,
            status_callback=status_callback,
            allowed_domains=[scoped["domain"]],
            country_code=region.get("country_code"),
            engine_plan=engine_plan,
        )
        print(
            "[CASPER SHOPPING DISCOVERY]",
            scoped["domain"],
            discovery.get("discovery_type", ""),
            "results=" + str(len(discovery.get("results", []))),
        )
        if discovery.get("status") == "HUMAN_HANDOFF":
            if plan.get("merchant_scope") == "exclusive" and not discovered:
                return {
                    "status": "HUMAN_HANDOFF",
                    "query": " | ".join(item["query"] for item in scoped_queries),
                    "pending_approval": {
                        "event": discovery.get("event", "captcha"),
                        "reason": "Background browser requires human control.",
                    },
                    "results": [],
                    "cards": [],
                }
            print(
                "[CASPER SHOPPING SEARCH SKIP PROTECTED]",
                scoped["domain"],
                discovery.get("event", "captcha"),
            )
            continue
        for item in discovery.get("results", []):
            url = item.get("url", "")
            domain = str(item.get("domain", "")).lower().strip()
            allowed = any(
                domain == merchant or domain.endswith("." + merchant)
                for merchant in merchant_domains
            )
            product_url = _merchant_product_url(scoped["domain"], url)
            scoped_domain = scoped["domain"]
            pair_key = (scoped["query_key"], scoped_domain)
            if (
                url
                and allowed
                and product_url
                and url not in seen_urls
                and domain_counts.get(scoped_domain, 0) < 6
                and query_counts.get(scoped["query_key"], 0) < 4
                and pair_counts.get(pair_key, 0) < 2
            ):
                seen_urls.add(url)
                item["is_product_detail_url"] = True
                item["shopping_query_key"] = scoped["query_key"]
                discovered.append(item)
                domain_counts[scoped_domain] = domain_counts.get(scoped_domain, 0) + 1
                query_counts[scoped["query_key"]] = (
                    query_counts.get(scoped["query_key"], 0) + 1
                )
                pair_counts[pair_key] = pair_counts.get(pair_key, 0) + 1
                if len(discovered) >= 12:
                    break
        if len(discovered) >= 12:
            break
    if not discovered:
        print("[CASPER SHOPPING DISCOVERY] no merchant candidates")
        return {
            "status": "NO_RESULTS",
            "query": " | ".join(item["query"] for item in scoped_queries),
            "results": [],
            "cards": [],
        }

    _status(status_callback, "Casper 正在读取具体商品页面… 📦")
    try:
        # Compact planning is complete. Release llama before the first gpt
        # source-ranking call so the two model runners do not overlap on a
        # 16 GB GPU.
        tools.unload_model("llama3.2:latest")
    except Exception as error:
        print("[CASPER MODEL UNLOAD SKIPPED] llama3.2:latest", repr(error))
    try:
        scored_value = tools.score_sources(user_request, discovered)
        if not isinstance(scored_value, list):
            raise TypeError("score_sources did not return a list")
        scored = scored_value[:12]
    except Exception as error:
        print("[CASPER SHOPPING SOURCE SCORE FALLBACK]", repr(error))
        scored = []
        for item in discovered[:12]:
            fallback = dict(item)
            fallback["source_score"] = 50
            scored.append(fallback)
    scored = _balanced_shopping_candidates(
        scored,
        [item["query_key"] for item in query_specs],
        limit=6,
    )
    products = []
    for candidate_index, candidate in enumerate(scored, start=1):
        try:
            page = read_url(candidate.get("url", ""))
        except Exception as error:
            print(
                "[CASPER SHOPPING READ ERROR]",
                "index=" + str(candidate_index),
                str(candidate.get("url") or "")[:300],
                repr(error),
            )
            continue
        print(
            "[CASPER SHOPPING READ]",
            candidate.get("domain", ""),
            "success=" + str(page.get("success", False)),
            "length=" + str(len(str(page.get("content", "")))),
            "error=" + str(page.get("error", ""))[:220],
        )
        protected_event = page.get("protected_event")
        exclusive_handoff = (
            plan.get("merchant_scope") == "exclusive"
            and protected_event in {"captcha", "access_block"}
        )
        if exclusive_handoff:
            handoff_url = page.get("final_url", "") or candidate.get("url", "")
            open_human_handoff(handoff_url)
            return {
                "status": "HUMAN_HANDOFF",
                "query": " | ".join(item["query"] for item in scoped_queries),
                "pending_approval": {
                    "event": protected_event or "captcha",
                    "reason": "The selected merchant requires user verification.",
                    "url": handoff_url,
                    "original_request": str(user_request),
                    "resume_after_user_confirmation": True,
                },
                "results": products,
                "cards": [],
            }
        if protected_event:
            # In a regional mix, one protected merchant must not block the
            # remaining verified merchants. Exclusive merchant requests still
            # hand control to the user above.
            print(
                "[CASPER SHOPPING SKIP PROTECTED]",
                candidate.get("domain", ""),
                protected_event,
            )
            continue
        enriched = dict(candidate)
        final_url = page.get("final_url", "") or candidate.get("url", "")
        final_is_product = _merchant_product_url(
            candidate.get("domain", ""),
            final_url,
        )
        if (
            final_is_product
            and not _merchant_has_known_detail_contract(
                candidate.get("domain", "")
            )
            and not str(page.get("structured_product") or "").strip()
        ):
            final_is_product = False
        enriched.update(
            {
                "page_success": page.get("success", False),
                "page_content": page.get("content", ""),
                "page_error": page.get("error"),
                "image_url": page.get("image_url", ""),
                "structured_product": page.get("structured_product", ""),
                "url": final_url,
                "is_product_detail_url": final_is_product,
                "reader_type": "casper_browser",
            }
        )
        products.append(enriched)

    if not products:
        return {
            "status": "NO_VERIFIED_PRODUCTS",
            "query": " | ".join(item["query"] for item in scoped_queries),
            "results": [],
            "cards": [],
            "region": region,
            "merchants": merchants,
        }

    _status(status_callback, "Casper 正在验证价格、图片与需求匹配… ✨")
    decisions = _extract_shopping_products(user_request, plan, region, products)
    if decisions is None:
        return {
            "status": "LIMITED_EVIDENCE",
            "query": " | ".join(item["query"] for item in scoped_queries),
            "results": [],
            "cards": [],
            "context": "Shopping extraction AI did not return a complete contract.",
        }
    validated_products = []
    for index, product in enumerate(products, start=1):
        decision = decisions.get(index)
        if decision is None:
            continue
        product.update(
            {
                "page_type": decision["page_type"],
                "product_title": decision["title"],
                "product_summary": decision["summary"],
                "merchant": decision["merchant"],
                "price": decision["price"],
                "currency": decision["currency"],
                "stock": decision["stock"],
                "brand": decision["brand"],
                "rating": decision["rating"],
                "review_count": decision["review_count"],
                "popularity_status": decision["popularity_status"],
                "popularity_evidence": decision["popularity_evidence"],
                "requirements": decision["requirements"],
                "fit_score": decision["fit_score"],
                "evidence_quality": decision["evidence_quality"],
                "shopping_reason": decision["reason"],
            }
        )
        # Known merchants must still end on one concrete product-detail page.
        # Redirects to a search/category page are not eligible for a card.
        if (
            product.get("page_type") == "PRODUCT"
            and product.get("is_product_detail_url")
            and str(product.get("product_title") or "").strip()
            and urlparse(str(product.get("url") or "")).scheme == "https"
        ):
            validated_products.append(product)

    products = validated_products

    _status(status_callback, "Casper 正在挑选三个可比较方案… ⚖️")
    selected = _select_shopping_products(user_request, plan, products)
    chosen = [products[index - 1] for index in selected]
    card_pairs = []
    for item in chosen:
        cleaned = result_cards.clean_cards(
            [
                {
                "type": "product",
                "title": item.get("product_title") or item.get("title", ""),
                "summary": item.get("product_summary", ""),
                "url": item.get("url", ""),
                "domain": item.get("domain", ""),
                "image": (
                    {
                        "url": item.get("image_url", ""),
                        "alt": item.get("product_title") or item.get("title", ""),
                        "source_url": item.get("url", ""),
                    }
                    if item.get("image_url")
                    else None
                ),
                "metadata": {
                    "merchant": item.get("merchant", ""),
                    "price": item.get("price", ""),
                    "currency": item.get("currency", ""),
                    "stock": item.get("stock", ""),
                    "rating": item.get("rating", ""),
                    "review_count": item.get("review_count", ""),
                    "brand": item.get("brand", ""),
                    "brand_evidence_source_count": (
                        item.get("brand_evidence", {}).get("source_count", 0)
                    ),
                    "brand_evidence_domains": (
                        item.get("brand_evidence", {}).get("source_domains", [])
                    ),
                    "captured_at": datetime.now().astimezone().isoformat(),
                },
                "requirements": item.get("requirements", []),
                }
            ]
        )
        if cleaned:
            card_pairs.append((cleaned[0], item))
    cards = [card for card, _item in card_pairs]
    chosen = [item for _card, item in card_pairs]

    if not cards:
        return {
            "status": "NO_VERIFIED_PRODUCTS",
            "query": " | ".join(item["query"] for item in scoped_queries),
            "queries": [item["query"] for item in scoped_queries],
            "requirements": plan.get("requirements", []),
            "region": region,
            "merchants": merchants,
            "results": [],
            "inspected_results": products,
            "cards": [],
            "verified_brand_evidence": verified_brands,
        }

    options = []
    for index, (card, item) in enumerate(card_pairs, start=1):
        options.append(
            {
                "option_id": "option_" + str(index),
                "title": card.get("title", ""),
                "summary": card.get("summary", ""),
                "domain": card.get("domain", ""),
                "source_score": item.get("source_score", 50),
                "metadata": {
                    **card.get("metadata", {}),
                    "brand": item.get("brand", ""),
                    "popularity_status": item.get("popularity_status", "UNKNOWN"),
                    "popularity_evidence": item.get("popularity_evidence", ""),
                    "fit_score": item.get("fit_score", 0),
                },
                "requirements": card.get("requirements", []),
            }
        )
    try:
        comparison = decision_comparison.compare_options(
            options,
            plan.get("requirements", []),
            lambda prompt, input_text: tools.run_ai_prompt(
                prompt,
                input_text,
                expect_json=True,
                num_ctx=6144,
                num_predict=900,
                think=False,
                model_name="gemma4:12b",
            ),
            preference_profile=plan.get("preference_profile", {}),
        )
        comparison_context = decision_comparison.prompt_context(
            comparison,
            {option["option_id"]: option["title"] for option in options},
        )
    except Exception as error:
        print("[CASPER SHOPPING COMPARISON SKIPPED]", repr(error))
        comparison = {}
        comparison_context = (
            "The optional comparison model was unavailable. Present only the "
            "verified card fields and do not infer missing pros or cons."
        )
    print("[CASPER SHOPPING]", len(cards), "product cards")
    return {
        "status": "OK" if len(cards) >= 3 else "PARTIAL_VERIFIED_PRODUCTS",
        "query": " | ".join(item["query"] for item in scoped_queries),
        "queries": [item["query"] for item in scoped_queries],
        "requirements": plan.get("requirements", []),
        "preference_profile": plan.get("preference_profile", {}),
        "region": region,
        "merchants": merchants,
        "merchant_scope": plan.get("merchant_scope", "regional_mix"),
        "results": chosen,
        "inspected_results": products,
        "cards": cards,
        "comparison": comparison,
        "verified_brand_evidence": verified_brands,
        "context": (
            "melchior response mode: SHOPPING_RESEARCH\n"
            "Casper read the selected merchant product pages. Product links are "
            "owned by the card buttons; do not print raw URLs. Compare every "
            "card, preserve UNKNOWN evidence, and use the validated comparison.\n\n"
            "Cross-source brand evidence:\n"
            + json.dumps(verified_brands, ensure_ascii=False, indent=2)
            + "\n\n"
            "Product cards:\n"
            + json.dumps(cards, ensure_ascii=False, indent=2)
            + "\n\n"
            + comparison_context
        ),
        "discovery_type": "casper_browser",
    }


def _try_search_summary_fact_answer(
    query,
    user_request,
    fact_scope,
    discovery,
):
    """Propose from search summaries, then let a separate AI challenge it."""
    import tools

    source_scope_text = " ".join([
        str(user_request or ""),
        str(
            ((fact_scope or {}).get("entity_scope") or {}).get(
                "included_scope", ""
            )
            if isinstance((fact_scope or {}).get("entity_scope"), dict)
            else ""
        ),
    ])
    strict_official_only = bool(re.search(
        r"(?:(?:只|仅)(?:接受|使用|采用|限于|限)?[^。；;\n]{0,40}官方|"
        r"official[^.;\n]{0,40}(?:only|exclusively)|"
        r"(?:only|exclusively)[^.;\n]{0,40}official)",
        source_scope_text,
        re.IGNORECASE,
    ))
    if strict_official_only:
        # Search snippets do not prove that an account/page is the entity's
        # official publisher.  Open the candidate page and apply both source
        # validators instead of accepting an encyclopedia consensus as
        # "official" evidence.
        print(
            "[CASPER SEARCH SUMMARY SKIPPED]",
            "reason=strict_official_source_scope",
        )
        return None

    sources = []
    for index, item in enumerate(discovery.get("results", [])[:7], start=1):
        if not isinstance(item, dict):
            continue
        sources.append(
            {
                "index": index,
                "title": str(item.get("title") or "")[:300],
                "description": str(item.get("description") or "")[:900],
                "domain": str(item.get("domain") or "")[:180],
                "published": str(item.get("published") or "")[:100],
                "url": str(item.get("url") or "")[:1000],
            }
        )
    if len(sources) < 2:
        return None
    overview_values = []
    for value in discovery.get("ai_summaries", []):
        if not isinstance(value, dict):
            continue
        summary = " ".join(str(value.get("summary") or "").split()).strip()
        if summary:
            overview_values.append(
                {
                    "engine": str(value.get("engine") or "")[:40],
                    "summary": summary[:2200],
                }
            )
    evidence = {
        "current_date": datetime.now().date().isoformat(),
        "original_user_request": str(user_request or query)[:1000],
        "retrieval_query": str(query)[:500],
        "fact_scope": fact_scope,
        "google_ai_overviews": overview_values,
        "search_results": sources,
    }
    evidence["bekki_final_persona"] = _load_bekki_light_persona()
    try:
        proposal = tools.run_ai_prompt(
            "prompts/casper_search_summary_answer.txt",
            json.dumps(evidence, ensure_ascii=False, separators=(",", ":")),
            expect_json=True,
            num_ctx=4096,
            num_predict=900,
            think=False,
            model_name="gemma4:12b",
        )
    except Exception as error:
        print("[CASPER SEARCH SUMMARY PROPOSAL ERROR]", repr(error))
        return None
    if not isinstance(proposal, dict) or not str(
        proposal.get("answer") or ""
    ).strip():
        return None
    audit_packet = dict(evidence)
    audit_packet["first_ai_proposal"] = proposal
    try:
        audit = tools.run_ai_prompt(
            "prompts/casper_search_summary_audit.txt",
            json.dumps(
                audit_packet,
                ensure_ascii=False,
                separators=(",", ":"),
            ),
            expect_json=True,
            num_ctx=4096,
            num_predict=1000,
            think=False,
            model_name="gemma4:12b",
        )
    except Exception as error:
        print("[CASPER SEARCH SUMMARY AUDIT ERROR]", repr(error))
        return None
    if not isinstance(audit, dict):
        return None
    answer = str(audit.get("answer") or "").strip()[:5000]
    verdict = str(audit.get("verdict") or "").upper().strip()
    valid_indexes = {item["index"] for item in sources}
    cited_indexes = set()
    for raw_index in audit.get("source_indexes", [])[:7]:
        try:
            source_index = int(raw_index)
        except (TypeError, ValueError):
            continue
        if source_index in valid_indexes:
            cited_indexes.add(source_index)
    checks = {}
    for value in audit.get("checks", [])[:8]:
        if not isinstance(value, dict):
            continue
        condition = str(value.get("condition") or "").upper().strip()
        status = str(value.get("status") or "").upper().strip()
        if condition and status in {"SUPPORTED", "MISSING", "CONTRADICTED"}:
            checks[condition] = status
    required_checks = {
        "DIRECTLY_ANSWERS",
        "TIME_SCOPE_SUPPORTED",
        "SOURCE_AGREEMENT",
        "NO_CONTRADICTION",
    }
    accepted = (
        verdict == "ACCEPT"
        and bool(answer)
        and len(cited_indexes) >= 2
        and set(checks) >= required_checks
        and all(checks[name] == "SUPPORTED" for name in required_checks)
    )
    print(
        "[CASPER SEARCH SUMMARY AUDIT]",
        "accepted=" + str(accepted),
        "sources=" + str(len(cited_indexes)),
        "errors=" + str(len(audit.get("errors_found", []))),
    )
    if not accepted:
        return None
    cited_sources = [
        item for item in sources if item["index"] in cited_indexes
    ]
    return {
        "answer": answer,
        "source_indexes": sorted(cited_indexes),
        "sources": cited_sources,
        "audit": audit,
        "proposal": proposal,
    }


def _native_fixed_fact_platform(requested_sites):
    """Return a site-native fact adapter only for an exact supported scope."""

    import source_scope

    sites = source_scope.normalize_domains(list(requested_sites or []))
    if len(sites) != 1:
        return ""
    if source_scope.domain_matches(sites[0], "bilibili.com"):
        return "bilibili"
    return ""


def _normalized_official_identity_text(value):
    """Normalize layout punctuation while preserving exact Unicode letters."""

    return re.sub(
        r"[^\w]+", "", str(value or "").casefold(), flags=re.UNICODE
    ).replace("_", "")


def _native_official_entity_expression(query, entity_name=""):
    """Return one literal entity expression for native account discovery."""

    value = " ".join(str(entity_name or "").split()).strip()
    if value:
        quoted_value = re.findall(r"['\"“]([^'\"”]{2,160})['\"”]", value)
        if quoted_value:
            return " ".join(quoted_value[0].split())[:160]
        value = re.split(r"[（(]", value, maxsplit=1)[0].strip()
        if value:
            return value[:160]
    text = str(query or "")
    quoted = re.findall(r'["“]([^"”]{2,160})["”]', text)
    if quoted:
        return " ".join(quoted[0].split())[:160]
    text = re.sub(r"(?<!\w)site\s*:\s*[^\s]+", " ", text, flags=re.I)
    tokens = [
        token.strip(" \t\r\n:：,，、-_")
        for token in re.split(r"\s+", text)
        if token.strip(" \t\r\n:：,，、-_")
    ]
    ignored = {
        "bilibili", "b站", "哔哩哔哩", "官方", "官方账号", "官方资料",
        "当前", "目前", "成员", "成员名单", "简介", "介绍", "核实", "验证",
    }
    for token in tokens:
        if token.casefold() not in ignored and 2 <= len(token) <= 160:
            return token[:160]
    return ""


def _canonical_bilibili_publisher_url(value):
    try:
        parsed = urlparse(str(value or "").strip())
        port = parsed.port
    except ValueError:
        return ""
    publisher_id = str(parsed.path or "").strip("/")
    if (
        str(parsed.scheme or "").casefold() != "https"
        or
        str(parsed.hostname or "").casefold() != "space.bilibili.com"
        or port not in {None, 443}
        or not publisher_id.isdigit()
    ):
        return ""
    return "https://space.bilibili.com/" + publisher_id


def _bilibili_official_profile_proof(candidate, entity_expression):
    """Bind one real /upuser card to the requested entity without AI judgment."""

    if not isinstance(candidate, dict):
        return None
    if (
        str(candidate.get("source_kind") or "") != "profile_result"
        or candidate.get("profile_result_matched") is not True
    ):
        return None
    url = _canonical_bilibili_publisher_url(candidate.get("url"))
    if not url:
        return None
    profile_name = " ".join(str(
        candidate.get("profile_name") or candidate.get("title")
        or candidate.get("author") or ""
    ).split()).strip()[:160]
    expected = _normalized_official_identity_text(entity_expression)
    actual = _normalized_official_identity_text(profile_name)
    allowed_names = {
        expected,
        expected + "official",
        expected + "官方",
        "official" + expected,
        "官方" + expected,
    }
    if not expected or actual not in allowed_names:
        return None
    verified_badge = candidate.get("profile_verified") is True
    explicit_marker = bool(re.search(
        r"(?:官方|official)", profile_name,
        flags=re.IGNORECASE,
    ))
    if not verified_badge and not explicit_marker:
        return None
    return {
        "publisher_name": profile_name,
        "publisher_url": url,
        "official_identity_verified": True,
        "official_identity_basis": (
            "bilibili_upuser_exact_entity_and_verified_badge"
            if verified_badge else
            "bilibili_upuser_exact_entity_and_official_marker"
        ),
        "entity_expression": str(entity_expression or "")[:160],
    }


def _bilibili_candidate_owned_by_identity(candidate, identity):
    """Require a video author URL or exact name to match the proven account."""

    if not isinstance(candidate, dict) or not isinstance(identity, dict):
        return False
    author_url = _canonical_bilibili_publisher_url(
        candidate.get("author_url")
    )
    publisher_url = _canonical_bilibili_publisher_url(
        identity.get("publisher_url")
    )
    if author_url and publisher_url and author_url == publisher_url:
        return True
    author = _normalized_official_identity_text(candidate.get("author"))
    publisher = _normalized_official_identity_text(
        identity.get("publisher_name")
    )
    return bool(author and publisher and author == publisher)


def _bilibili_publisher_video_keyword(native_query, identity):
    """Keep only the audited subject words for one publisher-local search."""

    text = re.sub(
        r"(?<!\w)site\s*:\s*[^\s]+", " ", str(native_query or ""),
        flags=re.IGNORECASE,
    )
    for value in (
        identity.get("publisher_name"),
        identity.get("entity_expression"),
    ):
        literal = " ".join(str(value or "").split()).strip()
        if literal:
            text = re.sub(re.escape(literal), " ", text, flags=re.IGNORECASE)
    text = re.sub(
        r"(?:bilibili|b\s*站|哔哩哔哩|official|官方账号|官方资料|官方|"
        r"请|重新|搜索|查找|核实|验证|账号|视频)",
        " ",
        text,
        flags=re.IGNORECASE,
    )
    if re.search(r"(?:成员|member|roster)", text, flags=re.IGNORECASE):
        # A publisher-local search already supplies the account boundary.
        # Keep the literal roster facet instead of sending dates, account
        # labels, and question wording that can hide the relevant upload.
        return "成员"
    text = re.sub(
        r"(?:分别)?(?:是|有|包括)?谁(?:们)?|是什么|有哪些|多少|"
        r"现在|当前|目前",
        " ",
        text,
        flags=re.IGNORECASE,
    )
    text = " ".join(
        value for value in re.split(r"[^\w\u3400-\u9fff]+", text)
        if value
    ).strip()
    return text[:80]


def _bilibili_publisher_video_page_urls(identity, native_query):
    """Build bounded pages under the already proven numeric publisher UID."""

    publisher_url = _canonical_bilibili_publisher_url(
        identity.get("publisher_url")
    )
    if not publisher_url:
        return []
    keyword = _bilibili_publisher_video_keyword(native_query, identity)
    urls = []
    if keyword:
        urls.append(
            publisher_url + "/search/video?keyword=" + quote(keyword)
        )
    urls.append(publisher_url + "/upload/video")
    return urls


def _bilibili_publisher_video_page_is_bound(value, publisher_url):
    """Accept only video-list routes below the exact proven publisher UID."""

    publisher_url = _canonical_bilibili_publisher_url(publisher_url)
    if not publisher_url:
        return False
    try:
        expected = urlparse(publisher_url)
        actual = urlparse(str(value or "").strip())
        actual_port = actual.port
    except ValueError:
        return False
    publisher_id = str(expected.path or "").strip("/")
    allowed_paths = {
        "/" + publisher_id + "/search/video",
        "/" + publisher_id + "/upload/video",
        "/" + publisher_id + "/video",
    }
    return (
        actual.scheme.casefold() == "https"
        and str(actual.hostname or "").casefold() == "space.bilibili.com"
        and actual_port in {None, 443}
        and actual.path.rstrip("/") in allowed_paths
    )


def _open_bilibili_publisher_video_page(target_url, publisher_url):
    """Open one exact publisher-local video route in the managed browser."""

    import social_browser
    from playwright.sync_api import (
        sync_playwright,
        TimeoutError as PlaywrightTimeoutError,
    )

    if not _bilibili_publisher_video_page_is_bound(
        target_url, publisher_url
    ):
        return ""
    social_browser.ensure_social_browser()
    with sync_playwright() as playwright:
        browser = playwright.chromium.connect_over_cdp(
            social_browser.CDP_URL
        )
        if not browser.contexts:
            raise RuntimeError(
                "Bekki social browser has no usable context."
            )
        context = browser.contexts[0]
        page = context.new_page()
        managed_browser.keep_page_background(context, page)
        social_browser._apply_bilibili_browser_identity(
            browser, context, page
        )
        try:
            try:
                page.goto(
                    target_url,
                    wait_until="domcontentloaded",
                    timeout=8000,
                )
            except PlaywrightTimeoutError:
                print(
                    "[CASPER BILIBILI PUBLISHER NAVIGATION CONTINUES]",
                    target_url,
                )
            page.wait_for_timeout(3500)
            opened_url = str(page.url or "").strip()
            if not _bilibili_publisher_video_page_is_bound(
                opened_url, publisher_url
            ):
                page.close(run_before_unload=False)
                print(
                    "[CASPER BILIBILI PUBLISHER PAGE REJECTED]",
                    "url=" + opened_url[:240],
                )
                return ""
            return opened_url
        except Exception:
            try:
                page.close(run_before_unload=False)
            except Exception:
                pass
            raise


def _discover_bilibili_verified_publisher_videos(
    identity,
    native_query,
):
    """Discover videos inside the exact Bilibili account proven above."""

    import social_browser

    if (
        not isinstance(identity, dict)
        or identity.get("official_identity_verified") is not True
    ):
        return []
    publisher_url = _canonical_bilibili_publisher_url(
        identity.get("publisher_url")
    )
    if not publisher_url:
        return []
    for target_url in _bilibili_publisher_video_page_urls(
        identity, native_query
    )[:2]:
        opened_url = ""
        try:
            opened_url = _open_bilibili_publisher_video_page(
                target_url, publisher_url
            )
            if not opened_url:
                continue
            time.sleep(2)
            page = social_browser.inspect_active_social_page(
                "bilibili",
                expected_url=opened_url,
            )
        except Exception as error:
            print(
                "[CASPER BILIBILI PUBLISHER VIDEO ERROR]",
                repr(error),
            )
            continue
        finally:
            if opened_url:
                try:
                    social_browser.close_social_search(opened_url)
                except Exception as error:
                    print(
                        "[CASPER BILIBILI PUBLISHER TAB CLOSE ERROR]",
                        repr(error),
                    )
        candidates = []
        for raw in (
            page.get("post_candidates", [])
            if isinstance(page, dict) else []
        ):
            if not isinstance(raw, dict):
                continue
            candidate = dict(raw)
            if (
                candidate.get("source_kind") != "result_card"
                or candidate.get("dom_card_matched") is not True
                or "/video/" not in str(candidate.get("url") or "")
            ):
                continue
            candidate["author"] = str(
                identity.get("publisher_name") or ""
            )[:160]
            candidate["author_url"] = publisher_url
            candidate["official_publisher_page_bound"] = True
            candidate[
                "official_publisher_video_discovery_version"
            ] = BILIBILI_OFFICIAL_PUBLISHER_VIDEO_DISCOVERY_VERSION
            candidates.append(candidate)
            if len(candidates) >= 30:
                break
        print(
            "[CASPER BILIBILI PUBLISHER VIDEO DISCOVERY]",
            "route=" + str(urlparse(target_url).path),
            "candidates=" + str(len(candidates)),
            "publisher=" + publisher_url.rsplit("/", 1)[-1],
        )
        if candidates:
            return candidates
    return []


def _discover_native_fixed_fact_candidates(
    query,
    requested_sites,
    official_only=False,
    count=7,
    status_callback=None,
    entity_name="",
):
    """Use a selected site's own search UI without changing fact semantics."""

    import social_browser
    import source_scope

    platform = _native_fixed_fact_platform(requested_sites)
    if not platform:
        return None
    site = source_scope.normalize_domains(list(requested_sites or []))[0]
    native_query = source_scope.native_site_query(query, site)
    if not native_query:
        return {
            "status": "NO_RESULTS",
            "results": [],
            "discovery_type": "site_native_fact",
            "platform": platform,
        }
    def run_native_search(search_query, search_kind, profiles):
        opened_url = ""
        try:
            opened = social_browser.open_social_search(
                platform,
                search_query,
                selection_mode="RELEVANCE",
                search_kind=search_kind,
            )
            opened_url = str(opened.get("url") or "")
            time.sleep(2)
            page = social_browser.inspect_active_social_page(
                platform,
                expected_url=opened_url,
                include_profile_candidates=profiles,
            )
            return page.get("post_candidates", [])
        except Exception as error:
            print("[CASPER NATIVE FACT SEARCH ERROR]", platform, repr(error))
            return []
        finally:
            try:
                social_browser.close_social_search(opened_url)
            except Exception as error:
                print("[CASPER NATIVE FACT TAB CLOSE ERROR]", repr(error))

    identity = None
    if official_only:
        entity_expression = _native_official_entity_expression(
            native_query, entity_name
        )
        if not entity_expression:
            return {
                "status": "LIMITED_EVIDENCE",
                "results": [],
                "discovery_type": "site_native_fact",
                "platform": platform,
                "official_identity_status": "ENTITY_EXPRESSION_MISSING",
            }
        _status(status_callback, "Casper 正在核对 B 站官方账号身份… 🪪")
        profile_candidates = run_native_search(
            entity_expression, "profile", True
        )
        proofs = [
            proof
            for proof in (
                _bilibili_official_profile_proof(item, entity_expression)
                for item in (
                    profile_candidates
                    if isinstance(profile_candidates, list) else []
                )
            )
            if proof is not None
        ]
        unique_publishers = {
            proof["publisher_url"]: proof for proof in proofs
        }
        if len(unique_publishers) != 1:
            print(
                "[CASPER BILIBILI OFFICIAL IDENTITY]",
                "status=UNVERIFIED",
                "matches=" + str(len(unique_publishers)),
                "entity=" + repr(entity_expression),
            )
            return {
                "status": "LIMITED_EVIDENCE",
                "results": [],
                "discovery_type": "site_native_fact",
                "platform": platform,
                "native_query": native_query,
                "official_identity_status": "UNVERIFIED",
            }
        identity = next(iter(unique_publishers.values()))
        print(
            "[CASPER BILIBILI OFFICIAL IDENTITY]",
            "status=VERIFIED",
            "publisher=" + repr(identity["publisher_name"]),
            "basis=" + identity["official_identity_basis"],
        )

    _status(status_callback, "Casper 正在使用 B 站站内搜索… 📺")
    raw_candidates = []
    if identity is not None:
        raw_candidates = _discover_bilibili_verified_publisher_videos(
            identity, native_query
        )
    if not raw_candidates:
        raw_candidates = run_native_search(native_query, "all", False)

    content_results = []
    seen_urls = set()
    for candidate in raw_candidates if isinstance(raw_candidates, list) else []:
        if not isinstance(candidate, dict):
            continue
        url = str(candidate.get("url") or "").strip()
        try:
            domain = str(urlparse(url).hostname or "").lower().removeprefix("www.")
        except ValueError:
            continue
        if (
            not url
            or url in seen_urls
            or not source_scope.domain_matches(domain, site)
        ):
            continue
        visible_text = " ".join(
            str(candidate.get("visible_text") or "").split()
        ).strip()[:1400]
        title = " ".join(
            str(candidate.get("title") or visible_text).split()
        ).strip()[:300]
        if not title or not visible_text:
            continue
        row = {
            "title": title,
            "description": str(
                candidate.get("description") or visible_text
            )[:1400],
            "domain": domain,
            "url": url,
            "published": str(candidate.get("published") or "")[:100],
            "source_score": 100,
            "native_platform": platform,
            "native_visible_text": visible_text,
            "native_source_kind": str(
                candidate.get("source_kind") or ""
            )[:80],
            "official_only": bool(official_only),
            "author": str(candidate.get("author") or "")[:160],
            "author_url": str(candidate.get("author_url") or "")[:2000],
            "official_publisher_page_bound": (
                candidate.get("official_publisher_page_bound") is True
            ),
            "official_publisher_video_discovery_version": (
                candidate.get(
                    "official_publisher_video_discovery_version"
                )
            ),
        }
        if official_only:
            if not _bilibili_candidate_owned_by_identity(candidate, identity):
                continue
            row.update(identity)
        content_results.append(row)
        seen_urls.add(url)
        if len(seen_urls) >= 30:
            break
    limit = max(1, min(int(count or 7), 12))
    results = content_results[:limit]
    print(
        "[CASPER NATIVE FACT SEARCH]",
        "platform=" + platform,
        "query=" + repr(native_query[:220]),
        "candidates=" + str(len(results)),
    )
    return {
        "status": "OK" if results else "NO_RESULTS",
        "results": results,
        "discovery_type": "site_native_fact",
        "platform": platform,
        "native_query": native_query,
        "official_identity": identity,
        "official_identity_status": (
            "VERIFIED" if identity is not None else "NOT_REQUIRED"
        ),
    }


def _read_native_fact_candidate(candidate):
    """Read only the selected native result; return None for normal web rows."""

    platform = str(candidate.get("native_platform") or "").strip()
    if platform != "bilibili":
        return None
    import social_browser

    url = str(candidate.get("url") or "").strip()
    try:
        hostname = str(urlparse(url).hostname or "").lower()
    except ValueError:
        hostname = ""
    if hostname == "space.bilibili.com":
        # Profile pages are not video documents. The normal rendered reader is
        # bounded to this exact URL and lets the official-source validator
        # inspect the account name, badges, and profile description together.
        return read_url(url)
    target = {
        "platform": platform,
        "url": url,
        "post_url": url,
        "source_url": url,
        "post_title": str(candidate.get("title") or "")[:300],
        "visible_text": str(candidate.get("native_visible_text") or "")[:1400],
        "evidence_level": "native_search_candidate",
    }
    best_detail = {}
    best_visual_detail = {}
    last_error = None
    for attempt in range(2):
        try:
            details = social_browser.inspect_social_post_details([target])
            detail = details[0] if isinstance(details, list) and details else {}
        except Exception as error:
            last_error = error
            detail = {}
        evidence_level = str(detail.get("evidence_level") or "")
        content = str(detail.get("visible_text") or "").strip()[:MAX_PAGE_TEXT]
        visual_frames = [
            str(value or "").strip()
            for value in detail.get("visual_frames", [])[:2]
            if str(value or "").strip()
        ] if (
            evidence_level == "opened_multimodal"
            and isinstance(detail.get("visual_frames"), list)
        ) else []
        best_evidence_level = str(best_detail.get("evidence_level") or "")
        best_content = str(best_detail.get("visible_text") or "").strip()
        score = (
            (100000 if evidence_level.startswith("opened_") else 0)
            + min(len(content), MAX_PAGE_TEXT)
        )
        best_score = (
            (100000 if best_evidence_level.startswith("opened_") else 0)
            + min(len(best_content), MAX_PAGE_TEXT)
        )
        if score > best_score:
            best_detail = detail
        best_visual_frames = (
            best_visual_detail.get("visual_frames", [])
            if isinstance(best_visual_detail.get("visual_frames"), list)
            else []
        )
        if len(visual_frames) > len(best_visual_frames):
            best_visual_detail = detail
        if evidence_level.startswith("opened_") and content and visual_frames:
            break
        if attempt == 0:
            print(
                "[CASPER BILIBILI DETAIL RETRY]",
                "reason=missing_bound_visual_evidence",
                "url=" + url[:240],
            )
            time.sleep(0.25)
    detail = dict(best_detail)
    if best_visual_detail:
        detail["visual_frames"] = best_visual_detail.get("visual_frames", [])
        detail["visual_assets"] = best_visual_detail.get("visual_assets", [])
        if str(detail.get("evidence_level") or "").startswith("opened_"):
            detail["evidence_level"] = "opened_multimodal"
    evidence_level = str(detail.get("evidence_level") or "")
    content = str(detail.get("visible_text") or "").strip()[:MAX_PAGE_TEXT]
    opened = evidence_level.startswith("opened_")
    page_images = [
        str(value or "").strip()
        for value in detail.get("visual_frames", [])[:2]
        if str(value or "").strip()
    ] if (
        evidence_level == "opened_multimodal"
        and isinstance(detail.get("visual_frames"), list)
    ) else []
    page_image_labels = [
        str(value.get("label") or "当前视频视觉证据")[:80]
        for value in detail.get("visual_assets", [])[:len(page_images)]
        if isinstance(value, dict)
    ] if isinstance(detail.get("visual_assets"), list) else []
    return {
        "success": bool(opened and content),
        "reader_type": "bilibili_native_fact",
        "content": content if opened else "",
        "page_images": page_images,
        "page_image_labels": page_image_labels,
        "final_url": str(detail.get("url") or url)[:2048],
        "published": str(detail.get("visible_time_text") or "")[:160],
        "error": (
            None if opened and content else
            repr(last_error)[:1000] if last_error is not None else
            "Native result page was not readable."
        ),
    }


def fact_lookup_controller(
    query,
    user_request="",
    status_callback=None,
    risk="low",
    requested_sites=None,
    official_only=False,
):
    """Browser-first current fact lookup with automatic source substitution."""
    import json
    import source_scope
    import tools

    requested_sites = source_scope.normalize_domains(
        list(requested_sites or [])
    )
    source_contract = {
        "source_scope": (
            source_scope.SOURCE_FIXED_SITES
            if requested_sites else source_scope.SOURCE_OPEN_WEB
        ),
        "requested_sites": requested_sites,
        "official_only": bool(official_only and requested_sites),
    }

    _status(status_callback, "Casper 正在确认事实时间范围… 🧭")
    fact_scope = _plan_fact_intent_scope(user_request or query, query)
    if fact_scope is None:
        return {
            "status": "LIMITED_EVIDENCE",
            "query": query,
            "results": [],
            "answers": [],
            "fact_scope": None,
            "source_contract": source_contract,
            "context": (
                "Casper could not obtain a valid AI temporal-intent contract. "
                "Do not guess or substitute a historical period."
            ),
        }
    entity_scope = _plan_fact_entity_scope(user_request or query, query)
    if entity_scope is None:
        return {
            "status": "LIMITED_EVIDENCE",
            "query": query,
            "results": [],
            "answers": [],
            "fact_scope": fact_scope,
            "entity_scope": None,
            "source_contract": source_contract,
            "context": (
                "Casper could not obtain a valid AI entity-scope contract. "
                "Do not broaden, narrow, or translate the request by guess."
            ),
        }
    fact_scope = dict(fact_scope)
    fact_scope["entity_scope"] = entity_scope
    query_scope_audit = _audit_fact_search_query(
        user_request or query,
        query,
        entity_scope,
    )
    if query_scope_audit is None:
        return {
            "status": "LIMITED_EVIDENCE",
            "query": query,
            "results": [],
            "answers": [],
            "fact_scope": fact_scope,
            "entity_scope": entity_scope,
            "query_scope_audit": None,
            "source_contract": source_contract,
            "context": (
                "Casper could not obtain a valid independent AI search-query "
                "scope audit. The unreviewed query was not executed."
            ),
        }
    proposed_query = query
    query = source_scope.constrain_query(
        query_scope_audit["approved_search_query"],
        requested_sites,
    )
    print(
        "[CASPER FACT ENTITY SCOPE]",
        json.dumps(entity_scope, ensure_ascii=False),
    )
    print(
        "[CASPER FACT QUERY SCOPE AUDIT]",
        json.dumps(query_scope_audit, ensure_ascii=False),
    )
    if query != proposed_query:
        print(
            "[CASPER FACT QUERY REWRITTEN]",
            repr(proposed_query),
            "->",
            repr(query),
        )
    print("[CASPER FACT SCOPE]", json.dumps(fact_scope, ensure_ascii=False))
    if requested_sites:
        print(
            "[CASPER FIXED SOURCE]",
            "sites=" + ",".join(requested_sites),
            "official_only=" + str(source_contract["official_only"]),
        )

    def run_external_fallback(results, answers, resolution=None, gap_plan=None):
        """Ask External AI only after bounded browser evidence is incomplete."""
        if requested_sites:
            # An external model is not one of the literal websites selected by
            # the user. Missing fixed-site evidence must remain missing.
            return {
                "status": "SKIPPED",
                "reason": "fixed_source_scope",
                "requested_sites": requested_sites,
            }
        from nerv import external_fact_fallback

        snapshot = {
            "status": "LIMITED_EVIDENCE",
            "query": query,
            "results": results if isinstance(results, list) else [],
            "answers": answers if isinstance(answers, list) else [],
            "resolution": resolution,
            "gap_plan": gap_plan,
            "fact_scope": fact_scope,
            "query_scope_audit": query_scope_audit,
        }
        return external_fact_fallback.attempt(
            user_request=user_request or query,
            query=query,
            search_result=snapshot,
            fact_scope=fact_scope,
            risk=risk,
            status_callback=status_callback,
        )

    def discover_fact_candidates(search_query, count):
        language_boundaries = entity_scope.get(
            "source_language_boundaries", []
        )
        literal_entity_expression = next(
            (
                str(value.get("source_expression") or "").strip()
                for value in language_boundaries
                if isinstance(value, dict)
                and str(value.get("source_expression") or "").strip()
            ),
            "",
        )
        native = _discover_native_fixed_fact_candidates(
            search_query,
            requested_sites,
            official_only=source_contract["official_only"],
            count=count,
            status_callback=status_callback,
            entity_name=(
                literal_entity_expression
                or entity_scope.get("target_entity")
                or ""
            ),
        )
        if native is not None:
            return native
        return discover_web(
            search_query,
            count=count,
            status_callback=status_callback,
            allowed_domains=requested_sites,
        )

    _status(status_callback, "Casper 正在后台浏览器中搜索… 🌐")
    discovery = discover_fact_candidates(query, 7)
    if discovery.get("status") == "HUMAN_HANDOFF":
        return {
            "status": "HUMAN_HANDOFF",
            "query": query,
            "pending_approval": {
                "event": discovery.get("event", "captcha"),
                "reason": "Background browser requires human control.",
            },
            "results": [],
            "source_contract": source_contract,
            "context": "Casper stopped because the browser requested human verification.",
        }
    candidates = discovery.get("results", [])
    if not candidates:
        fallback = run_external_fallback([], [])
        if fallback.get("status") == "HUMAN_HANDOFF":
            return {
                "status": "HUMAN_HANDOFF",
                "query": query,
                "pending_approval": fallback.get("pending_approval"),
                "results": [],
                "source_contract": source_contract,
                "answers": [],
                "external_ai_fallback": fallback,
                "context": "External AI fallback requires user login.",
            }
        if fallback.get("status") in {
            "VERIFIED", "CURRENT_REFERENCE", "CERTIFIED"
        }:
            answer = str(fallback.get("answer") or "").strip()
            answer_status = {
                "VERIFIED": "EXTERNAL_AI_POLICY_VERIFIED",
                "CURRENT_REFERENCE": "EXTERNAL_AI_CURRENT_REFERENCE",
                "CERTIFIED": "EXTERNAL_AI_HIGH_IMPACT_CERTIFIED",
            }[fallback["status"]]
            return {
                "status": "OK",
                "query": query,
                "results": [],
                "answers": [
                    {
                        "index": 0,
                        "answer": answer,
                        "accepted": True,
                        "answer_status": answer_status,
                    }
                ],
                "fact_scope": fact_scope,
                "source_contract": source_contract,
                "direct_reply": answer,
                "external_ai_fallback": fallback,
                "discovery_type": "external_ai_fact_fallback",
                "context": (
                    "Bounded web discovery returned no usable result. "
                    "A locally governed low-impact External-AI fallback was "
                    "accepted and persisted with explicit provenance."
                ),
            }
        return {
            "status": "NO_RESULTS",
            "query": query,
            "results": [],
            "answers": [],
            "fact_scope": fact_scope,
            "external_ai_fallback": fallback,
            "source_contract": source_contract,
        }

    if str(risk or "low").casefold() != "high":
        _status(status_callback, "Casper 正在让独立 AI 检查搜索总结… 🧠")
        summary_answer = _try_search_summary_fact_answer(
            query,
            user_request,
            fact_scope,
            discovery,
        )
        if summary_answer:
            answer = summary_answer["answer"]
            context = (
                "melchior response mode: FACT_LOOKUP\n"
                "A first AI proposed an answer from Google AI Overview and "
                "search snippets. A separate adversarial AI accepted a "
                "corrected answer only after checking directness, time scope, "
                "source agreement, and contradictions. No source page was "
                "opened because the summary audit passed.\n\n"
                + json.dumps(summary_answer, ensure_ascii=False, indent=2)
            )
            return {
                "status": "OK",
                "query": query,
                "results": summary_answer["sources"],
                "answers": [
                    {
                        "index": 0,
                        "answer": answer,
                        "accepted": True,
                        "answer_status": "SUMMARY_AUDITED",
                    }
                ],
                "fact_scope": fact_scope,
                "source_contract": source_contract,
                "context": context,
                "direct_reply": answer,
                "summary_audit": summary_answer["audit"],
                "discovery_type": "casper_search_summary_audited",
            }

    _status(status_callback, "Casper 正在选择并读取权威页面… 📚")
    candidates = tools.score_sources(query, candidates)
    read_results = []
    answers = []
    seen_urls = set()

    def process_candidates(candidate_list):
        """Execute candidates; semantic acceptance remains owned by AI."""
        for candidate in candidate_list:
            url = candidate.get("url", "")
            if not url or url in seen_urls:
                continue
            seen_urls.add(url)
            page = _read_native_fact_candidate(candidate)
            if page is None:
                page = read_url(url)
            if page.get("protected_event") == "captcha":
                print("[CASPER BROWSER CAPTCHA]", candidate.get("domain", ""))
                return {
                    "status": "HUMAN_HANDOFF",
                    "query": query,
                    "pending_approval": {
                        "event": "captcha",
                        "reason": "A source requested human verification.",
                        "url": url,
                    },
                    "results": read_results,
                    "answers": answers,
                    "source_contract": source_contract,
                    "context": (
                        "Casper stopped immediately because a source presented "
                        "a CAPTCHA. Human control is required."
                    ),
                }

            enriched = dict(candidate)
            enriched.update(
                {
                    "page_success": page.get("success", False),
                    "page_content": page.get("content", ""),
                    "page_error": page.get("error"),
                    "reader_type": "casper_browser",
                }
            )
            read_results.append(enriched)
            extraction_source = dict(enriched)
            page_images = [
                str(value or "").strip()
                for value in page.get("page_images", [])[:2]
                if str(value or "").strip()
            ] if isinstance(page.get("page_images"), list) else []
            if page_images:
                page_image_labels = [
                    str(value or "")[:80]
                    for value in page.get("page_image_labels", [])[:2]
                    if str(value or "").strip()
                ] if isinstance(page.get("page_image_labels"), list) else []
                extraction_source["page_images"] = page_images
                extraction_source["page_image_labels"] = page_image_labels
                # Keep the exact opened-source frames available until the
                # post-reply Knowledge gate either rejects them or caches only
                # the selected public evidence assets.
                enriched["page_images"] = page_images
                enriched["page_image_labels"] = page_image_labels
            extracted = tools.extract_answers(query, [extraction_source])
            extracted_item = extracted[0] if extracted else {}
            answer = extracted_item.get("answer")
            validation = None
            temporal_validation = None
            if answer not in (None, "", [], {}):
                temporal_validation = _validate_temporal_scope(
                    query,
                    enriched,
                    answer,
                    fact_scope,
                )
                if (
                    isinstance(temporal_validation, dict)
                    and temporal_validation.get("time_scope_match") is True
                ):
                    validation = _validate_candidate_answer(
                        query,
                        enriched,
                        answer,
                        user_request=user_request or query,
                        fact_scope=fact_scope,
                    )
            accepted = bool(
                temporal_validation
                and temporal_validation.get("time_scope_match") is True
                and validation
                and validation.get("accepted") is True
            )
            answers.append(
                {
                    "index": len(read_results),
                    "answer": answer,
                    "evidence": (
                        extracted_item.get("evidence")
                        if isinstance(extracted_item.get("evidence"), dict)
                        else {}
                    ),
                    "accepted": accepted,
                    "validation_reason": (
                        validation.get("reason", "")
                        if isinstance(validation, dict)
                        else ""
                    ),
                    "temporal_validation": temporal_validation,
                    "temporal_alternative_accepted": False,
                    "temporal_alternative_validation": None,
                }
            )
            if accepted:
                return None
        return None

    handoff = process_candidates(candidates)
    if handoff is not None:
        return handoff

    gap_plan = None
    if not _has_answer(answers) and read_results:
        _status(status_callback, "Casper 正在分析证据缺口… 🧩")
        gap_plan = _plan_evidence_gap(
            query,
            read_results,
            answers,
            fact_scope,
            user_request=user_request or query,
        )

    if (
        isinstance(gap_plan, dict)
        and gap_plan.get("action") == "RESEARCH_AGAIN"
    ):
        _status(status_callback, "Casper 正在进行一次补充调查… 🔎")
        follow_up_query_set = gap_plan.get("follow_up_queries", [])[:2]
        for follow_up_query in follow_up_query_set:
            follow_up_audit = _audit_fact_search_query(
                user_request or query,
                follow_up_query,
                entity_scope,
                query_role="FOCUSED_FOLLOW_UP",
                query_set=follow_up_query_set,
                gap_plan=gap_plan,
            )
            if follow_up_audit is None:
                print("[CASPER FACT FOLLOW-UP QUERY REJECTED] invalid_audit")
                continue
            reviewed_follow_up_query = follow_up_audit[
                "approved_search_query"
            ]
            if reviewed_follow_up_query != follow_up_query:
                print(
                    "[CASPER FACT FOLLOW-UP QUERY REWRITTEN]",
                    repr(follow_up_query),
                    "->",
                    repr(reviewed_follow_up_query),
                )
            follow_up_query = reviewed_follow_up_query
            follow_up_query = source_scope.constrain_query(
                follow_up_query,
                requested_sites,
            )
            follow_up_discovery = discover_fact_candidates(
                follow_up_query,
                5,
            )
            if follow_up_discovery.get("status") == "HUMAN_HANDOFF":
                return {
                    "status": "HUMAN_HANDOFF",
                    "query": query,
                    "pending_approval": {
                        "event": follow_up_discovery.get("event", "captcha"),
                        "reason": "Background browser requires human control.",
                    },
                    "results": read_results,
                    "answers": answers,
                    "source_contract": source_contract,
                    "context": "Casper stopped during bounded follow-up research.",
                }
            follow_up_candidates = follow_up_discovery.get("results", [])
            if not follow_up_candidates:
                continue
            follow_up_candidates = tools.score_sources(
                follow_up_query,
                follow_up_candidates,
            )
            handoff = process_candidates(follow_up_candidates)
            if handoff is not None:
                return handoff
            if _has_answer(answers):
                break

    resolution = None
    if not _has_answer(answers) and read_results:
        _status(status_callback, "Casper 正在判断该事实是否尚未产生… 🧭")
        resolution = _resolve_combined_fact(
            query,
            read_results,
            answers,
            fact_scope,
            user_request=user_request or query,
        )
        if (
            isinstance(resolution, dict)
            and resolution.get("accepted") is True
            and resolution.get("answer")
        ):
            answers.append(
                {
                    "index": 0,
                    "answer": resolution["answer"],
                    "answer_status": resolution["answer_status"],
                    "accepted": True,
                }
            )

    external_fallback = None
    if not _has_answer(answers):
        external_fallback = run_external_fallback(
            read_results,
            answers,
            resolution=resolution,
            gap_plan=gap_plan,
        )
        if external_fallback.get("status") == "HUMAN_HANDOFF":
            return {
                "status": "HUMAN_HANDOFF",
                "query": query,
                "pending_approval": external_fallback.get("pending_approval"),
                "results": read_results,
                "answers": answers,
                "fact_scope": fact_scope,
                "source_contract": source_contract,
                "external_ai_fallback": external_fallback,
                "context": "External AI fallback requires user login.",
            }
        if external_fallback.get("status") in {
            "VERIFIED", "CURRENT_REFERENCE", "CERTIFIED"
        }:
            answer_status = {
                "VERIFIED": "EXTERNAL_AI_POLICY_VERIFIED",
                "CURRENT_REFERENCE": "EXTERNAL_AI_CURRENT_REFERENCE",
                "CERTIFIED": "EXTERNAL_AI_HIGH_IMPACT_CERTIFIED",
            }[external_fallback["status"]]
            answers.append(
                {
                    "index": 0,
                    "answer": str(external_fallback.get("answer") or "").strip(),
                    "accepted": True,
                    "answer_status": answer_status,
                    "knowledge_id": external_fallback.get("knowledge_id"),
                }
            )

    exact_answer = _has_answer(answers)
    temporal_fallback = None
    if not exact_answer and str(risk or "low").casefold() == "low":
        _validate_temporal_alternative_candidates(
            query,
            user_request or query,
            fact_scope,
            answers,
            read_results,
        )
        temporal_fallback = _build_temporal_evidence_fallback(
            user_request or query,
            fact_scope,
            answers,
            read_results,
            source_contract,
        )
        if temporal_fallback is not None:
            print(
                "[CASPER TEMPORAL EVIDENCE FALLBACK]",
                "requested=" + repr(
                    temporal_fallback.get("requested_period")
                ),
                "source=" + repr(
                    (
                        temporal_fallback.get("selected_evidence") or {}
                    ).get("source_period")
                ),
                "knowledge_eligible=False",
            )
    has_answer = bool(exact_answer or temporal_fallback)
    accepted_answer = _accepted_answer_text(answers)
    if not accepted_answer and temporal_fallback is not None:
        accepted_answer = str(temporal_fallback.get("reply") or "").strip()
    context = (
        "melchior response mode: FACT_LOOKUP\n"
        "Casper used its managed background browser for discovery and rendered "
        "page reading. Follow the AI fact resolver's answer and "
        "response_instruction exactly.\n\n"
        "Binding fact intent scope:\n"
        + json.dumps(fact_scope, ensure_ascii=False, indent=2)
        + "\n\nBinding entity-scope search audit:\n"
        + json.dumps(query_scope_audit, ensure_ascii=False, indent=2)
        + "\n\n"
        "Extracted answers:\n"
        + json.dumps(answers, ensure_ascii=False, indent=2)
        + "\n\nCombined evidence resolution:\n"
        + json.dumps(resolution, ensure_ascii=False, indent=2)
        + "\n\nEvidence gap plan:\n"
        + json.dumps(gap_plan, ensure_ascii=False, indent=2)
        + "\n\nExternal AI fallback:\n"
        + json.dumps(external_fallback, ensure_ascii=False, indent=2)
        + "\n\nDisplay-only temporal evidence fallback:\n"
        + json.dumps(temporal_fallback, ensure_ascii=False, indent=2)
        + "\n\nBrowser sources:\n"
        + json.dumps(tools._source_summary(read_results), ensure_ascii=False, indent=2)
    )
    return {
        "status": "OK" if has_answer else "LIMITED_EVIDENCE",
        "query": query,
        "results": read_results,
        "answers": answers,
        "resolution": resolution,
        "gap_plan": gap_plan,
        "fact_scope": fact_scope,
        "entity_scope": entity_scope,
        "query_scope_audit": query_scope_audit,
        "external_ai_fallback": external_fallback,
        "temporal_evidence_fallback": temporal_fallback,
        "source_contract": source_contract,
        "context": context,
        "direct_reply": accepted_answer,
        "answer_kind": (
            "EXACT_FACT"
            if exact_answer else
            "TEMPORAL_EVIDENCE_FALLBACK"
            if temporal_fallback is not None else
            "NONE"
        ),
        "target_scope_answered": bool(exact_answer),
        "knowledge_capture_eligible": bool(exact_answer),
        "discovery_type": "casper_browser",
    }
