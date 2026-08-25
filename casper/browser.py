"""Casper-managed background browser for public web research."""

import os
import base64
import hashlib
import socket
import subprocess
import sys
import time
import json
import re
from datetime import datetime
from functools import lru_cache
from pathlib import Path
from urllib.parse import parse_qs, parse_qsl, quote, unquote, urljoin, urlparse


CDP_PORT = 9224
CDP_URL = f"http://127.0.0.1:{CDP_PORT}"
MAX_PAGE_TEXT = 15000
_browser_process = None

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
    if sys.platform == "win32":
        base = Path(os.environ.get("LOCALAPPDATA", str(Path.home())))
        path = base / "Bekki"
    elif sys.platform == "darwin":
        path = Path.home() / "Library" / "Application Support" / "Bekki"
    else:
        path = Path.home() / ".local" / "share" / "Bekki"
    path.mkdir(parents=True, exist_ok=True)
    return path


def _profile_dir():
    path = _app_data_dir() / "casper_browser_profile"
    path.mkdir(parents=True, exist_ok=True)
    return path


def _edge_executable():
    candidates = []
    if sys.platform == "win32":
        for variable in ("PROGRAMFILES(X86)", "PROGRAMFILES", "LOCALAPPDATA"):
            root = os.environ.get(variable)
            if root:
                candidates.append(
                    Path(root) / "Microsoft" / "Edge" / "Application" / "msedge.exe"
                )
    elif sys.platform == "darwin":
        candidates.append(
            Path("/Applications/Microsoft Edge.app/Contents/MacOS/Microsoft Edge")
        )

    for candidate in candidates:
        if candidate.exists():
            return str(candidate)
    raise RuntimeError("Microsoft Edge was not found for Casper Browser.")


def _cdp_ready():
    try:
        with socket.create_connection(("127.0.0.1", CDP_PORT), timeout=0.5):
            return True
    except OSError:
        return False


def ensure_browser():
    """Start a separate headless Edge profile owned by Casper."""
    global _browser_process
    if _cdp_ready():
        return

    command = [
        _edge_executable(),
        f"--remote-debugging-port={CDP_PORT}",
        "--remote-debugging-address=127.0.0.1",
        f"--user-data-dir={_profile_dir()}",
        "--no-first-run",
        "--no-default-browser-check",
        "--disable-background-networking",
        "--headless=new",
        "--window-size=1280,900",
    ]
    _browser_process = subprocess.Popen(
        command,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )

    deadline = time.time() + 12
    while time.time() < deadline:
        if _cdp_ready():
            return
        time.sleep(0.25)
    raise RuntimeError("Casper Browser did not start.")


def _stop_casper_browser():
    """Close only Casper's CDP browser so its profile can be reopened visibly."""
    global _browser_process
    if _cdp_ready():
        try:
            from playwright.sync_api import sync_playwright

            with sync_playwright() as playwright:
                browser = playwright.chromium.connect_over_cdp(CDP_URL)
                browser.close()
        except Exception as error:
            print("[CASPER BROWSER CLOSE ERROR]", repr(error))
    if _browser_process is not None and _browser_process.poll() is None:
        try:
            _browser_process.terminate()
            _browser_process.wait(timeout=5)
        except Exception as error:
            print("[CASPER BROWSER TERMINATE ERROR]", repr(error))
    _browser_process = None
    deadline = time.time() + 8
    while _cdp_ready() and time.time() < deadline:
        time.sleep(0.2)


def open_human_handoff(url):
    """Reopen Casper's persistent profile visibly for user verification."""
    global _browser_process
    target = str(url).strip()
    parsed = urlparse(target)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise ValueError("Human handoff requires a public web URL.")
    _stop_casper_browser()
    command = [
        _edge_executable(),
        f"--remote-debugging-port={CDP_PORT}",
        "--remote-debugging-address=127.0.0.1",
        f"--user-data-dir={_profile_dir()}",
        "--no-first-run",
        "--no-default-browser-check",
        "--start-maximized",
        target,
    ]
    _browser_process = subprocess.Popen(
        command,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    deadline = time.time() + 12
    while time.time() < deadline:
        if _cdp_ready():
            print("[CASPER HUMAN HANDOFF OPENED]", parsed.netloc)
            return True
        time.sleep(0.25)
    raise RuntimeError("Visible Casper Browser did not start.")


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


def _has_answer(answers):
    """Keep browser result validation inside Casper, not private V1 tools."""
    return any(
        isinstance(item, dict)
        and item.get("accepted", True) is True
        and item.get("answer") not in (None, "", [], {})
        for item in (answers or [])
    )


def _validate_candidate_answer(query, source, answer):
    """Ask AI whether one extracted value actually answers the query."""
    import tools

    result = tools.run_ai_prompt(
        "prompts/fact_candidate_validate.txt",
        json.dumps(
            {
                "query": query,
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
        num_predict=220,
        think=False,
        model_name="gemma3:12b",
    )
    if not isinstance(result, dict) or not isinstance(result.get("accepted"), bool):
        return None
    return {
        "accepted": result["accepted"],
        "reason": str(result.get("reason", ""))[:400],
    }


def _plan_fact_intent_scope(user_request, query):
    """Let AI bind the original request to one temporal intent contract."""
    import tools

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
            model_name="gemma3:12b",
        )

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

    result = run("prompts/fact_intent_scope.txt")
    if not valid(result):
        result = run("prompts/fact_intent_scope_retry.txt", result)
    if not valid(result):
        return None
    normalized = {
        "scope_type": str(result["scope_type"]).upper().strip(),
        "requested_period": result["requested_period"].strip()[:240],
        "allow_previous_period": result["allow_previous_period"],
        "reason": result["reason"].strip()[:400],
    }
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
        model_name="gemma3:12b",
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


def _resolve_combined_fact(query, read_results, answers, fact_scope):
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
        model_name="gemma3:12b",
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
            model_name="gemma3:12b",
        )

    if not judgment_contract_complete(result):
        return None

    status = str(result["answer_status"]).upper().strip()
    judgment = {
        "answer_status": status,
        "reason": str(result["reason"]).strip()[:500],
    }
    answer_input = {
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
        model_name="gemma3:12b",
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
            model_name="gemma3:12b",
        )

    if not answer_contract_complete(answer_result):
        return None

    return {
        "answer_status": status,
        "answer": answer_result["answer"].strip()[:1000],
        "reason": judgment["reason"],
        "response_instruction": answer_result[
            "response_instruction"
        ].strip()[:500],
    }


def _plan_evidence_gap(query, read_results, answers, fact_scope):
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
        model_name="gemma3:12b",
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
        model_name="gemma3:12b",
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
        model_name="gemma3:12b",
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
        model_name="gemma3:12b",
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
                model_name="gemma3:12b",
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
                model_name="gemma3:12b",
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
                model_name="gemma3:12b",
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
            model_name="gemma3:12b",
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
    """Summarize only the candidates that survived second-stage verification."""
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
                num_predict=1200,
                think=False,
                model_name="gemma3:12b",
            )
        except Exception as error:
            print(
                "[CASPER RECOMMENDATION FINAL ERROR]",
                "attempt=" + str(attempt + 1),
                repr(error),
            )
            break
        if isinstance(raw, dict):
            reply = str(raw.get("reply") or "").strip()[:5000]
            if reply:
                return reply
        packet["retry_instruction"] = "Return only the required JSON object."
    return "\n".join(
        item["title"] + "：" + item["summary"] for item in verified
    )[:5000]


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
    for model_name in ("gemma3:12b", "llama3.2:latest"):
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
            tools.unload_model("gemma3:12b")
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
            tools.unload_model("gemma3:12b")
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
            expanded_sources, _ = _collect_recommendation_sources(
                recovery_queries,
                region,
                engine_plan,
                status_callback=status_callback,
                existing_sources=sources,
                limit=9,
            )
            new_sources = expanded_sources[len(sources):]
            if new_sources:
                # Recovery candidate generation sees only evidence returned by
                # the new AI-created queries. Old niche sources remain useful
                # for deduplication during discovery but cannot steer the
                # second candidate pass back toward already rejected products.
                recovery_sources = [dict(source) for source in new_sources]
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
        tools.unload_model("gemma3:12b")
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
                "summary": item["summary"],
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
                "requirements": [],
            }
            for item in options
        ]
    )[:8]
    if not cards and sources:
        # A truncated/invalid candidate JSON must not erase the useful
        # independent sources already found.  Render them honestly as reading
        # leads, not as verified product recommendations.
        cards = result_cards.clean_cards(
            [
                {
                    "type": "article",
                    "title": str(source.get("title") or source.get("domain") or "")[:180],
                    "summary": str(source.get("description") or "")[:600],
                    "url": str(source.get("url") or "")[:2048],
                    "domain": str(source.get("domain") or "")[:180],
                    "metadata": {
                        "published_at": str(source.get("published") or "")[:160],
                        "captured_at": datetime.now().astimezone().isoformat(),
                    },
                    "requirements": [],
                }
                for source in sources[:5]
                if source.get("url") and (source.get("title") or source.get("domain"))
            ]
        )
        if cards:
            direct_reply = (
                "这次候选推荐的结构化输出没有完整通过校验；"
                "我先保留已经找到的独立评测与推荐来源，避免整条结果消失。"
            )
            print("[CASPER RECOMMENDATION SOURCE FALLBACK]", len(cards))
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
        "Recommendation cards:\n"
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
        "direct_reply": direct_reply if cards else "",
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
                model_name="gemma3:12b",
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
            model_name="gemma3:12b",
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
            model_name="gemma3:12b",
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
        tools.unload_model("gemma3:12b")
    except Exception as error:
        print("[CASPER MODEL UNLOAD SKIPPED] gemma3:12b", repr(error))
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
                tools.unload_model("gemma3:12b")
            except Exception as error:
                print("[CASPER MODEL UNLOAD SKIPPED] gemma3:12b", repr(error))
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
                tools.unload_model("gemma3:12b")
            except Exception as error:
                print("[CASPER MODEL UNLOAD SKIPPED] gemma3:12b", repr(error))
    try:
        tools.unload_model("gemma3:12b")
    except Exception as error:
        print("[CASPER MODEL UNLOAD SKIPPED] gemma3:12b", repr(error))
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
                model_name="gemma3:12b",
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
            model_name="gemma3:12b",
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
            model_name="gemma3:12b",
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


def fact_lookup_controller(
    query,
    user_request="",
    status_callback=None,
    risk="low",
):
    """Browser-first current fact lookup with automatic source substitution."""
    import json
    import tools

    _status(status_callback, "Casper 正在确认事实时间范围… 🧭")
    fact_scope = _plan_fact_intent_scope(user_request or query, query)
    if fact_scope is None:
        return {
            "status": "LIMITED_EVIDENCE",
            "query": query,
            "results": [],
            "answers": [],
            "fact_scope": None,
            "context": (
                "Casper could not obtain a valid AI temporal-intent contract. "
                "Do not guess or substitute a historical period."
            ),
        }
    print("[CASPER FACT SCOPE]", json.dumps(fact_scope, ensure_ascii=False))

    _status(status_callback, "Casper 正在后台浏览器中搜索… 🌐")
    discovery = discover_web(
        query,
        count=7,
        status_callback=status_callback,
    )
    if discovery.get("status") == "HUMAN_HANDOFF":
        return {
            "status": "HUMAN_HANDOFF",
            "query": query,
            "pending_approval": {
                "event": discovery.get("event", "captcha"),
                "reason": "Background browser requires human control.",
            },
            "results": [],
            "context": "Casper stopped because the browser requested human verification.",
        }
    candidates = discovery.get("results", [])
    if not candidates:
        return {"status": "NO_RESULTS", "query": query, "results": []}

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
            extracted = tools.extract_answers(query, [enriched])
            answer = extracted[0].get("answer") if extracted else None
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
                    "accepted": accepted,
                    "validation_reason": (
                        validation.get("reason", "")
                        if isinstance(validation, dict)
                        else ""
                    ),
                    "temporal_validation": temporal_validation,
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
        gap_plan = _plan_evidence_gap(query, read_results, answers, fact_scope)

    if (
        isinstance(gap_plan, dict)
        and gap_plan.get("action") == "RESEARCH_AGAIN"
    ):
        _status(status_callback, "Casper 正在进行一次补充调查… 🔎")
        for follow_up_query in gap_plan.get("follow_up_queries", [])[:2]:
            follow_up_discovery = discover_web(
                follow_up_query,
                count=5,
                status_callback=status_callback,
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
        )
        if isinstance(resolution, dict) and resolution.get("answer"):
            answers.append(
                {
                    "index": 0,
                    "answer": resolution["answer"],
                    "answer_status": resolution["answer_status"],
                    "accepted": True,
                }
            )

    has_answer = _has_answer(answers)
    context = (
        "melchior response mode: FACT_LOOKUP\n"
        "Casper used its managed background browser for discovery and rendered "
        "page reading. Follow the AI fact resolver's answer and "
        "response_instruction exactly.\n\n"
        "Binding fact intent scope:\n"
        + json.dumps(fact_scope, ensure_ascii=False, indent=2)
        + "\n\n"
        "Extracted answers:\n"
        + json.dumps(answers, ensure_ascii=False, indent=2)
        + "\n\nCombined evidence resolution:\n"
        + json.dumps(resolution, ensure_ascii=False, indent=2)
        + "\n\nEvidence gap plan:\n"
        + json.dumps(gap_plan, ensure_ascii=False, indent=2)
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
        "context": context,
        "discovery_type": "casper_browser",
    }
