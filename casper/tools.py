import json
import os
import re
import social_browser
from datetime import datetime, timedelta
from urllib.parse import urlparse
from bs4 import BeautifulSoup
from urllib.parse import urlparse
import context as context_manager
import memory
import document
import vision
import result_cards
import decision_comparison
import shopping_region
import media_watch
import sys
import requests
import webbrowser
import time
from urllib.parse import quote, urlparse
from dotenv import load_dotenv
from io import BytesIO
from pypdf import PdfReader

def resource_path(relative_path):
    base_path = getattr(sys, "_MEIPASS", os.path.abspath("."))
    return os.path.join(base_path, relative_path)


def config_path(relative_path):
    if getattr(sys, "frozen", False):
        external_path = os.path.join(
            os.path.dirname(sys.executable),
            relative_path,
        )
        if os.path.exists(external_path):
            return external_path

    return resource_path(relative_path)
load_dotenv(config_path(".env"))

import model_runtime

BRAVE_API_KEY = os.getenv("BRAVE_API_KEY", "").strip()
BRAVE_SEARCH_URL = "https://api.search.brave.com/res/v1/web/search"
BRAVE_IMAGE_SEARCH_URL = "https://api.search.brave.com/res/v1/images/search"
OLLAMA_URL = model_runtime.OLLAMA_URL
MODEL_NAME = "gemma4:12b"
SEARCH_BUDGETS = (3, 5, 7, 10)


def _explicit_shopping_merchant(user_message, region=None):
    """Preserve a merchant explicitly named by the user as a hard constraint."""
    text = str(user_message or "").casefold()
    country_code = str((region or {}).get("country_code", "")).upper()

    amazon_domains = {
        "CA": "amazon.ca",
        "CN": "amazon.cn",
        "DE": "amazon.de",
        "ES": "amazon.es",
        "FR": "amazon.fr",
        "GB": "amazon.co.uk",
        "IN": "amazon.in",
        "IT": "amazon.it",
        "JP": "amazon.co.jp",
    }

    named_merchants = (
        (("amazon", "亚马逊"), "Amazon", amazon_domains.get(country_code, "amazon.com")),
        (("walmart", "沃尔玛"), "Walmart", "walmart.com"),
        (("target",), "Target", "target.com"),
        (("ebay",), "eBay", "ebay.com"),
        (("taobao", "淘宝"), "Taobao", "taobao.com"),
        (("tmall", "天猫"), "Tmall", "tmall.com"),
        (("jd.com", "京东"), "JD", "jd.com"),
    )

    occurrences = []
    for aliases, name, domain in named_merchants:
        for alias in aliases:
            if re.search(r"[\u3400-\u9fff]", alias):
                matches = re.finditer(re.escape(alias), text)
            else:
                matches = re.finditer(
                    rf"(?<![a-z0-9]){re.escape(alias)}(?![a-z0-9])",
                    text,
                    flags=re.IGNORECASE,
                )
            for match in matches:
                right = text[match.end():match.end() + 32]
                if alias == "target" and re.match(
                    r"\s+(?:audience|market|customer|customers|demographic|"
                    r"group|age|price|budget|use|user|users)\b",
                    right,
                    flags=re.IGNORECASE,
                ):
                    continue
                occurrences.append(
                    {
                        "start": match.start(),
                        "end": match.end(),
                        "name": name,
                        "domain": domain,
                    }
                )
    if not occurrences:
        return None

    # Keep conjunctions inside a clause so a leading negation applies to the
    # whole merchant list. Contrast words and punctuation begin a new clause.
    clause_marks = re.sub(
        r"但是|而是|但|\bbut\b|\bhowever\b",
        lambda match: "," * len(match.group(0)),
        text,
        flags=re.IGNORECASE,
    )
    delimiters = "，,。；;！？!?"

    def clause_bounds(position):
        start = max(clause_marks.rfind(mark, 0, position) for mark in delimiters) + 1
        ends = [
            found
            for mark in delimiters
            if (found := clause_marks.find(mark, position)) >= 0
        ]
        return start, min(ends) if ends else len(text)

    grouped = {}
    for item in sorted(occurrences, key=lambda row: row["start"]):
        grouped.setdefault(clause_bounds(item["start"]), []).append(item)

    positive = []
    chinese_negator = (
        r"(?:不要|不想|别|拒绝|避开|排除|除了|不选|不用|不考虑)"
        r"\s*(?:(?:在|从|用|选|去|买|要)\s*)*$"
    )
    english_negator = (
        r"(?:do\s+not|don['’]?t|not|no|avoid|exclude|except|anything\s+but)"
        r"\s*(?:(?:use|choose|want|shop\s+at|buy\s+from)\s+)*$"
    )
    for (clause_start, clause_end), items in grouped.items():
        first = items[0]
        last = items[-1]
        prefix = text[clause_start:first["start"]]
        suffix = text[last["end"]:clause_end]
        clause_is_negative = bool(
            re.search(chinese_negator, prefix, flags=re.IGNORECASE)
            or re.search(english_negator, prefix, flags=re.IGNORECASE)
            or re.match(
                r"\s*(?:都\s*)?(?:除外|之外|不要|不选|不用)",
                suffix,
                flags=re.IGNORECASE,
            )
            or re.match(
                r"\s*(?:are\s+)?(?:excluded|not\s+wanted)\b",
                suffix,
                flags=re.IGNORECASE,
            )
        )
        if clause_is_negative:
            continue
        for item in items:
            local_left = text[max(clause_start, item["start"] - 36):item["start"]]
            local_right = text[item["end"]:min(clause_end, item["end"] + 24)]
            if (
                re.search(chinese_negator, local_left, flags=re.IGNORECASE)
                or re.search(english_negator, local_left, flags=re.IGNORECASE)
                or re.match(
                    r"\s*(?:除外|之外|不要|不选|不用)",
                    local_right,
                    flags=re.IGNORECASE,
                )
            ):
                continue
            positive.append(item)

    unique = {}
    for item in positive:
        unique.setdefault(item["name"].casefold(), item)
    if len(unique) != 1:
        return None
    merchant = next(iter(unique.values()))
    return {
        "name": merchant["name"],
        "domain": merchant["domain"],
        "reason": "The user explicitly requested this merchant.",
    }


def _merchant_search_scope(domain):
    """Bias discovery toward merchant product-detail URLs."""
    domain = str(domain).lower().removeprefix("www.")
    if domain.startswith("amazon."):
        return "site:" + domain + "/dp/"
    if domain == "walmart.com":
        return "site:walmart.com/ip/"
    if domain == "target.com":
        return "site:target.com/p/"
    if domain == "ebay.com":
        return "site:ebay.com/itm/"
    if domain == "jd.com":
        return "site:item.jd.com"
    return "site:" + domain


def _is_merchant_product_url(domain, url):
    """Reject search/category pages for merchants with known URL contracts."""
    domain = str(domain).lower().removeprefix("www.")
    try:
        parsed = urlparse(str(url))
    except ValueError:
        return False
    host = parsed.netloc.lower().removeprefix("www.")
    path = parsed.path

    if domain.startswith("amazon.") or host.startswith("amazon."):
        return bool(re.search(r"/(?:dp|gp/product)/[A-Z0-9]{10}(?:[/?]|$)", path, re.I))
    if domain == "walmart.com":
        return "/ip/" in path
    if domain == "target.com":
        return "/p/" in path
    if domain == "ebay.com":
        return "/itm/" in path
    if domain == "taobao.com":
        return host == "item.taobao.com" and path.endswith("item.htm")
    if domain == "tmall.com":
        return host == "detail.tmall.com" and path.endswith("item.htm")
    if domain == "jd.com":
        return host == "item.jd.com" and bool(re.search(r"/\d+\.html$", path))
    return True


def _has_specific_product_identity(title, description):
    """Reject collection pages that happen to resemble merchant product URLs."""
    title_text = BeautifulSoup(
        str(title), "html.parser"
    ).get_text(" ", strip=True)
    description_text = BeautifulSoup(
        str(description), "html.parser"
    ).get_text(" ", strip=True)
    combined = (title_text + " " + description_text).lower()

    collection_signals = (
        "best sellers",
        "new releases",
        "shop by category",
        "shop products",
        "great selection",
        "baby products store",
        "search results",
        "featured products",
    )
    if any(signal in combined for signal in collection_signals):
        return False

    # "$25 to $50", "$25-$50", and similar ranges describe filters rather
    # than the price of one item.
    if re.search(
        r"[$€£¥]\s*\d+(?:\.\d+)?\s*(?:to|[-–—])\s*[$€£¥]?\s*\d+",
        title_text,
        re.I,
    ):
        return False

    return bool(title_text and len(title_text) >= 12)


def _has_readable_product_evidence(item):
    """Require a successfully read product page, not a block or CAPTCHA page."""
    if not isinstance(item, dict) or not item.get("page_success"):
        return False
    content = str(item.get("page_content", "")).strip()
    lowered = content.lower()
    if len(content) < 500:
        return False
    blocked_signals = (
        "robot check",
        "enter the characters you see below",
        "sorry, we just need to make sure you're not a robot",
        "captcha",
        "access denied",
    )
    return not any(signal in lowered for signal in blocked_signals)


def get_domain(url):
    return urlparse(url).netloc.lower().replace("www.", "")


def _extract_search_image(result):
    """Keep only a real HTTPS image URL returned by the search provider."""
    if not isinstance(result, dict):
        return ""

    candidates = []
    for field in ("thumbnail", "image"):
        value = result.get(field)
        if isinstance(value, str):
            candidates.append(value)
        elif isinstance(value, dict):
            candidates.extend(
                value.get(key, "")
                for key in ("src", "url", "original")
            )

    for candidate in candidates:
        if not isinstance(candidate, str):
            continue
        candidate = candidate.strip()
        try:
            parsed = urlparse(candidate)
        except ValueError:
            continue
        if (
            parsed.scheme.lower() == "https"
            and parsed.netloc
            and not parsed.username
            and not parsed.password
        ):
            return candidate[:2048]

    return ""


def search(query, count=5, freshness=None):
    if not BRAVE_API_KEY:
        return "Search failed: BRAVE_API_KEY is missing."

    headers = {
        "Accept": "application/json",
        "Accept-Encoding": "gzip",
        "X-Subscription-Token": BRAVE_API_KEY,
    }

    params = {
        "q": query,
        "count": count,
    }
    if freshness:
        params["freshness"] = freshness

    try:
        response = requests.get(
            BRAVE_SEARCH_URL,
            headers=headers,
            params=params,
            timeout=15,
        )
        response.raise_for_status()
        data = response.json()
    except requests.RequestException as error:
        return f"Search failed: {error}"

    results = data.get("web", {}).get("results", [])
    if not results:
        return []

    search_results = []
    for result in results:
        url = result.get("url", "")
        search_results.append(
            {
                "title": result.get("title", "No title"),
                "description": result.get("description", "No description"),
                "url": url,
                "domain": get_domain(url),
                "published": result.get("age", None),
                "image_url": _extract_search_image(result),
            }
        )

    return search_results


def _image_match_tokens(value):
    ignored = {
        "amazon", "walmart", "com", "home", "kitchen", "shop", "store",
        "product", "photo", "official", "online", "buy", "with", "and",
    }
    return {
        token
        for token in re.findall(r"[a-z0-9]+", str(value).lower())
        if len(token) >= 4 and token not in ignored
    }


def search_product_image(product_title):
    """Return a relevant product photo, never a generic merchant logo."""
    if not BRAVE_API_KEY:
        return ""
    clean_title = BeautifulSoup(
        str(product_title), "html.parser"
    ).get_text(" ", strip=True)
    clean_title = re.sub(
        r"^(amazon|walmart)(\.com)?\s*:\s*",
        "",
        clean_title,
        flags=re.IGNORECASE,
    )
    title_tokens = 'REDACTED'
    if not title_tokens:
        return ""
    image_query = '"' + clean_title[:150] + '" product photo -logo'
    try:
        response = requests.get(
            BRAVE_IMAGE_SEARCH_URL,
            headers={
                "Accept": "application/json",
                "Accept-Encoding": "gzip",
                "X-Subscription-Token": BRAVE_API_KEY,
            },
            params={"q": image_query, "count": 10, "safesearch": "strict"},
            timeout=15,
        )
        response.raise_for_status()
        results = response.json().get("results", [])
    except (requests.RequestException, ValueError) as error:
        print("[PRODUCT IMAGE SEARCH FAILED]", repr(error))
        return ""

    for item in results:
        if not isinstance(item, dict):
            continue
        result_title = str(item.get("title", ""))
        result_tokens = 'REDACTED'
        overlap = len(title_tokens & result_tokens)
        required_overlap = 1 if len(title_tokens) <= 3 else 2
        if "logo" in result_title.lower() or overlap < required_overlap:
            continue
        thumbnail = item.get("thumbnail", {})
        candidates = []
        if isinstance(thumbnail, str):
            candidates.append(thumbnail)
        elif isinstance(thumbnail, dict):
            candidates.extend(thumbnail.get(key, "") for key in ("src", "url"))
        properties = item.get("properties", {})
        if isinstance(properties, dict):
            candidates.extend(properties.get(key, "") for key in ("url", "src"))
        for candidate in candidates:
            if not isinstance(candidate, str):
                continue
            candidate = candidate.strip()
            try:
                parsed = urlparse(candidate)
            except ValueError:
                continue
            if (
                parsed.scheme.lower() == "https"
                and parsed.netloc
                and "logo" not in parsed.path.lower()
            ):
                return candidate[:2048]
    return ""

def call_model(
    prompt,
    num_ctx=8192,
    num_predict=2048,
    think="low",
    model_name=None,
    response_format=None,
    images=None,
    system_prompt=None,
):
    return model_runtime.generate(
        prompt,
        num_ctx=num_ctx,
        num_predict=num_predict,
        think=think,
        model_name=model_name or MODEL_NAME,
        response_format=response_format,
        images=images,
        system_prompt=system_prompt,
        stage="tools.call_model",
    )

def unload_model(
    model_name=MODEL_NAME
):
    return model_runtime.unload_model(model_name)


def wait_for_model_unloaded(model_name, timeout_seconds=10):
    """Wait until Ollama no longer reports a model in GPU/CPU memory."""
    return model_runtime.wait_for_model_unloaded(model_name, timeout_seconds)

def run_ai_prompt(
    prompt_path,
    input_text,
    expect_json=False,
    num_ctx=8192,
    num_predict=2048,
    think="low",
    model_name=None,
    json_schema=None,
    images=None,
    invalid_json_handler=None,
):
    with open(resource_path(prompt_path), "r", encoding="utf-8") as file:
        system_prompt = file.read()

    raw_output = call_model(
        input_text,
        num_ctx=num_ctx,
        num_predict=num_predict,
        think=think,
        model_name=model_name,
        # Parsing JSON and asking Ollama to constrain generation are separate
        # choices. Some gpt-oss routing prompts return an empty response when
        # format=json is forced, so only explicitly schema-bound calls use it.
        response_format=json_schema if expect_json and json_schema else None,
        images=images,
        system_prompt=system_prompt,
    )

    if not expect_json:
        return raw_output.strip()

    candidate = raw_output.strip()

    # Local models occasionally wrap otherwise valid JSON in a Markdown
    # code fence. Python owns format recovery; semantic content still comes
    # entirely from the model.
    if candidate.startswith("```"):
        first_newline = candidate.find("\n")
        if first_newline >= 0:
            candidate = candidate[first_newline + 1:]
        if candidate.rstrip().endswith("```"):
            candidate = candidate.rstrip()[:-3].rstrip()

    try:
        return json.loads(candidate)
    except json.JSONDecodeError as first_error:
        # Recover one leading/trailing prose fragment without trying to repair
        # malformed JSON values or invent missing structure.
        starts = [
            index for index in (candidate.find("{"), candidate.find("["))
            if index >= 0
        ]
        if starts:
            start = min(starts)
            try:
                value, _ = json.JSONDecoder().raw_decode(candidate[start:])
                return value
            except json.JSONDecodeError:
                pass

        print("AI JSON ERROR:", prompt_path, first_error)
        print("BROKEN OUTPUT:", repr(raw_output))
        if callable(invalid_json_handler):
            try:
                recovered = invalid_json_handler(raw_output)
            except Exception as recovery_error:
                print(
                    "[AI JSON RECOVERY ERROR]",
                    prompt_path,
                    repr(recovery_error),
                )
            else:
                if recovered is not None:
                    print("[AI JSON STRUCTURAL RECOVERY]", prompt_path)
                    return recovered
        return None


def ai_decision(
    prompt_path,
    user_message,
    conversation_context=""
):
    document_context = "NO DOCUMENT ATTACHED"
    print("[tools document]",document.has_document(),document.get_current_document())
    if document.has_document():
        current_document  = (
            document.get_current_document()
        )
        document_context = ("An active local document is currently loaded.\n"
                            +"File name: " + 
                            str(current_document.get("file_name", "")) 
                            + "\n"
                            + "The user may be asking about this document."
        )
    image_context = "NO IMAGE ATTACHED"
    if vision.has_image():
        current_image = (vision.get_current_image())
        image_context = ("An active image is currently loaded.\n"
                         "File name: " + str(current_image.get("file_name", ""))
                         +"\nThe user may be asking about this image."
        )
    memory_data = memory.initialize_memory()
    long_term_context = memory.get_long_term_context(memory_data)
    conversation_state = (
        context_manager.load_context()
    )

    context_state_text = json.dumps(
        conversation_state,
        ensure_ascii=False,
        indent=2
    )

    input_text = (
        "Current conversation state:\n"
        + context_state_text
        + "\n\nCurrent long-term memory:\n"
        + long_term_context
        + "\n\nCurrent document context:\n"
        + document_context
        + "\n\nCurrent image context:\n"
        + image_context
        + "\n\nRecent conversation:\n"
        + conversation_context
        + "\n\nCurrent user message:\n"
        + user_message
    )

    decision = run_ai_prompt(
        prompt_path,
        input_text,
        expect_json=False,
        num_ctx=4096,
        num_predict=128,
    )

    print(
        "FINAL PROMPT LENGTH:",
        len(input_text)
    )

    return decision.strip().upper()


def should_search(
    user_message,
    conversation_context=""
):
    decision = ai_decision(
        "prompts/search.txt",
        user_message,
        conversation_context
    )

    print("SEARCH:", repr(decision))

    return decision.startswith("SEARCH")


def is_confirmation(message, pending_action=None, recent_context=""):
    """Classify only the current reply against one explicit pending action."""
    pending = pending_action if isinstance(pending_action, dict) else None
    input_data = {
        "current_user_message": str(message),
        "pending_action": pending,
        "recent_conversation": str(recent_context)[-2000:],
    }
    payload = json.dumps(input_data, ensure_ascii=False, separators=(",", ":"))
    attempts = (
        ("prompts/confirm.txt", "llama3.2:latest", 240, 2048),
        ("prompts/confirm_retry.txt", "gemma4:12b", 800, 4096),
    )
    decision = ""
    for prompt_path, model_name, output_budget, context_budget in attempts:
        raw = run_ai_prompt(
            prompt_path,
            payload,
            expect_json=False,
            num_ctx=context_budget,
            num_predict=output_budget,
            think=False,
            model_name=model_name,
        )
        decision = str(raw or "").strip().upper()
        if decision in {"CONFIRM", "NOT_CONFIRM"}:
            break
    print("CONFIRM:", repr(decision))
    return decision == "CONFIRM"


def decide_tools(
    message,
    conversation_context=""
):
    if should_search(
        message,
        conversation_context
    ):
        return "search"

    return "chat"


def build_search_query(
    user_message,
    conversation_context=""
):
    current_date = (
        datetime.now()
        .date()
        .isoformat()
    )

    conversation_state = (
        context_manager.load_context()
    )

    context_state_text = json.dumps(
        conversation_state,
        ensure_ascii=False,
        indent=2
    )

    input_text = (
        "Current date:\n"
        + current_date
        + "\n\nCurrent conversation state:\n"
        + context_state_text
        + "\n\nRecent conversation:\n"
        + conversation_context
        + "\n\nCurrent user message:\n"
        + user_message
    )

    query = run_ai_prompt(
        "prompts/search_query.txt",
        input_text,
        expect_json=False,
        num_ctx=4096,
        num_predict=256,
        think=False,
        model_name="gemma4:12b",
    ).strip()

    print(
        "BUILT SEARCH QUERY:",
        repr(query)
    )

    return query or user_message


def _resolved_news_window(user_message, today=None):
    """Resolve an explicit recent-month request into one bounded date window."""
    current = today or datetime.now().date()
    text = " ".join(str(user_message or "").split()).casefold()
    months = None
    match = re.search(
        r"(?:最近|近|过去)\s*([一二两三四五六七八九十\d]+)\s*个?月",
        text,
    )
    if match:
        token = match.group(1)
        chinese_numbers = {
            "一": 1, "二": 2, "两": 2, "三": 3, "四": 4, "五": 5,
            "六": 6, "七": 7, "八": 8, "九": 9, "十": 10,
        }
        try:
            months = int(token)
        except ValueError:
            months = chinese_numbers.get(token)
    elif re.search(r"(?:这|最近|近|过去)\s*(?:几|数)\s*个?月", text):
        months = 4
    else:
        english = re.search(r"(?:last|past|recent)\s+(\d+)\s+months?", text)
        if english:
            months = int(english.group(1))
        elif re.search(r"(?:last|past|recent)\s+(?:few|several)\s+months?", text):
            months = 4
    if months is None:
        return None
    months = max(1, min(12, int(months)))
    return current - timedelta(days=31 * months), current


def build_news_queries(user_message, conversation_context=""):
    """Ask AI for complementary discovery queries for one news feed."""
    resolved_window = _resolved_news_window(user_message)
    window_text = (
        resolved_window[0].isoformat() + " through " + resolved_window[1].isoformat()
        if resolved_window
        else "No additional relative-date window was resolved."
    )
    input_text = (
        "Current date:\n"
        + datetime.now().date().isoformat()
        + "\n\nAuthoritative resolved news window:\n"
        + window_text
        + "\n\nRecent conversation:\n"
        + conversation_context
        + "\n\nCurrent user message:\n"
        + user_message
    )
    result = run_ai_prompt(
        "prompts/news_query.txt",
        input_text,
        expect_json=True,
        num_ctx=4096,
        num_predict=320,
        think=False,
        model_name="gemma4:12b",
    )
    values = result.get("queries", []) if isinstance(result, dict) else []
    queries = []
    for value in values:
        query = " ".join(str(value).split()).strip()[:220]
        if query and query not in queries:
            queries.append(query)
        if len(queries) >= 2:
            break
    if not queries:
        subject = " ".join(str(user_message or "").split()).strip()[:150]
        queries = [
            subject + " recent events",
            subject + " authoritative announcements",
        ]
    if resolved_window:
        start_date, end_date = resolved_window
        invalid_year = any(
            int(year) < start_date.year or int(year) > end_date.year
            for query in queries
            for year in re.findall(r"\b(?:19|20)\d{2}\b", query)
        )
        date_anchor = start_date.isoformat() + " " + end_date.isoformat()
        if invalid_year:
            print(
                "[NEWS QUERY WINDOW RECOVERY]",
                "discarded_out_of_window_year",
            )
            subject = " ".join(str(user_message or "").split()).strip()[:150]
            queries = [
                subject + " " + date_anchor + " recent events",
                subject + " " + date_anchor + " authoritative announcements",
            ]
        else:
            queries = [
                (query[:170].rstrip() + " " + date_anchor).strip()
                for query in queries
            ]
    print("[NEWS QUERIES]", json.dumps(queries, ensure_ascii=False))
    return queries


def build_discussion_queries(user_message, conversation_context=""):
    """Ask AI for complementary cross-site discussion discovery queries.

    DISCUSSION_FEED is deliberately separate from both NEWS_FEED and the
    platform-native SOCIAL_RESEARCH browser.  These queries may therefore
    discover Q&A pages, forum threads, fan discussions, blogs, and supported
    or unsupported social sites through ordinary web search.
    """

    packet = {
        "current_date": datetime.now().date().isoformat(),
        "current_user_message": str(user_message or "")[:1200],
        "recent_conversation_for_reference_only": str(
            conversation_context or ""
        )[-1200:],
    }
    schema = {
        "type": "object",
        "properties": {
            "queries": {
                "type": "array",
                "items": {"type": "string"},
                "minItems": 2,
                "maxItems": 3,
            }
        },
        "required": ["queries"],
        "additionalProperties": False,
    }
    result = run_ai_prompt(
        "prompts/discussion_query.txt",
        json.dumps(packet, ensure_ascii=False, separators=(",", ":")),
        expect_json=True,
        num_ctx=4096,
        num_predict=420,
        think=False,
        model_name="gemma4:12b",
        json_schema=schema,
    )
    values = result.get("queries", []) if isinstance(result, dict) else []
    queries = []
    for value in values:
        query = " ".join(str(value or "").split()).strip()[:220]
        if query and query.casefold() not in {
            existing.casefold() for existing in queries
        }:
            queries.append(query)
        if len(queries) >= 3:
            break
    if len(queries) < 2:
        # This fallback preserves the user's wording instead of inventing a
        # site or a factual conclusion.  It runs only after the AI has already
        # selected DISCUSSION_FEED and failed the query-shape contract.
        subject = " ".join(str(user_message or "").split()).strip()[:170]
        queries = [
            (subject + " 讨论 观点").strip(),
            (subject + " 原因 时间线 不同说法").strip(),
        ]
    print("[DISCUSSION QUERIES]", json.dumps(queries, ensure_ascii=False))
    return queries


def build_media_watch_plan(user_message):
    """Extract a media subject while Python preserves literal site conditions."""

    requested_sites = media_watch.extract_requested_sites(user_message)
    fallback_mode = media_watch.selection_mode(user_message)
    fallback_subject = media_watch.fallback_topic(
        user_message,
        requested_sites=requested_sites,
    )
    schema = {
        "type": "object",
        "properties": {
            "topic": {"type": "string", "minLength": 1},
            "selection_mode": {
                "type": "string",
                "enum": ["EXACT", "RANDOM_ONE"],
            },
            "content_kind": {
                "type": "string",
                "enum": [
                    "SERIES", "MOVIE", "EPISODE", "LIVE", "VIDEO", "CATEGORY",
                ],
            },
            "episode_hint": {
                "anyOf": [{"type": "string"}, {"type": "null"}],
            },
        },
        "required": [
            "topic", "selection_mode", "content_kind", "episode_hint",
        ],
        "additionalProperties": False,
    }
    packet = {
        "current_user_message": str(user_message or "")[:1400],
        "python_detected_selection_mode": fallback_mode,
        "literal_requested_sites_owned_by_python": requested_sites,
    }
    try:
        raw = run_ai_prompt(
            "prompts/media_watch_plan.txt",
            json.dumps(packet, ensure_ascii=False, separators=(",", ":")),
            expect_json=True,
            num_ctx=3072,
            num_predict=260,
            think=False,
            model_name="gemma4:12b",
            json_schema=schema,
        )
    except Exception as error:
        print("[MEDIA WATCH PLAN FALLBACK]", repr(error))
        raw = {}
    topic = " ".join(str((raw or {}).get("topic") or "").split()).strip()[:180]
    if not topic:
        topic = fallback_subject
    # Selection mode and site scope are hard user-intent contracts.  The model
    # extracts the subject but cannot relax or invent either condition.
    content_kind = str((raw or {}).get("content_kind") or "").upper().strip()
    if content_kind not in {
        "SERIES", "MOVIE", "EPISODE", "LIVE", "VIDEO", "CATEGORY",
    }:
        content_kind = "CATEGORY" if fallback_mode == "RANDOM_ONE" else "VIDEO"
    episode_hint = (raw or {}).get("episode_hint")
    episode_hint = (
        " ".join(str(episode_hint).split()).strip()[:100]
        if episode_hint is not None else None
    )
    plan = {
        "topic": topic,
        "selection_mode": fallback_mode,
        "content_kind": content_kind,
        "episode_hint": episode_hint or None,
        "requested_sites": requested_sites,
        "site_scope_explicit": bool(requested_sites),
    }
    print("[MEDIA WATCH PLAN]", json.dumps(plan, ensure_ascii=False))
    return plan


def _claim_anchor_tokens(claim):
    """Return numeric/date facts that a fact-check query must not discard."""
    text = str(claim or "")
    anchors = []
    patterns = (
        r"\b\d{4}-\d{2}-\d{2}\b",
        r"\b\d{1,3}\s*(?:[-–—:]|\bto\b)\s*\d{1,3}\b",
        r"\b(?:19|20)\d{2}\b",
    )
    for pattern in patterns:
        for match in re.finditer(pattern, text, flags=re.IGNORECASE):
            value = re.sub(r"\s+", " ", match.group(0)).strip()
            if value and value not in anchors:
                anchors.append(value)
    return anchors


def _normalized_anchor(value):
    return re.sub(r"(?:\s+|[-–—:]|\bto\b)", "", str(value).casefold())


def _query_preserves_claim_anchors(query, claim):
    query_text = str(query or "")
    compact_query = _normalized_anchor(query_text)
    return all(
        _normalized_anchor(anchor) in compact_query
        for anchor in _claim_anchor_tokens(claim)
    )


def _anchored_claim_query(claim):
    compact_claim = " ".join(str(claim or "").split()).strip()[:700]
    return (compact_claim + " official source").strip()


def build_claim_query(claim):
    input_text = (
        "Current date:\n"
        + datetime.now().date().isoformat()
        + "\n\nClaim to verify:\n"
        + claim
    )

    query = run_ai_prompt(
        "prompts/claim_query.txt",
        input_text,
        expect_json=False,
        num_ctx=4096,
        num_predict=128,
        think=False,
        model_name="gemma4:12b",
    ).strip()

    if query and not _query_preserves_claim_anchors(query, claim):
        missing = [
            anchor for anchor in _claim_anchor_tokens(claim)
            if _normalized_anchor(anchor) not in _normalized_anchor(query)
        ]
        print(
            "[CLAIM QUERY ANCHOR RECOVERY]",
            "missing=" + json.dumps(missing, ensure_ascii=False),
        )
        query = _anchored_claim_query(claim)

    query = query or _anchored_claim_query(claim)
    print("BUILT CLAIM QUERY:", repr(query))
    return query


def score_sources(query, search_results):
    if not search_results:
        return []

    source_text = ""
    for index, result in enumerate(search_results, start=1):
        source_text += (
            f"\nSource {index}\n"
            f"Title: {result['title']}\n"
            f"Description: {result['description']}\n"
            f"URL: {result['url']}\n"
            f"Domain: {result['domain']}\n"
        )

    input_text = (
        "User question:\n"
        + query
        + "\n\nSearch results:\n"
        + source_text
    )

    result = run_ai_prompt(
        "prompts/source_score.txt",
        input_text,
        expect_json=True,
        num_ctx=8192,
        num_predict=1024,
        think=False,
        model_name="gemma4:12b",
    )

    scores = result.get("scores", []) if isinstance(result, dict) else []

    for score_item in scores:
        index = score_item.get("index")
        if not isinstance(index, int):
            continue
        if index < 1 or index > len(search_results):
            continue

        search_results[index - 1]["source_score"] = score_item.get("score", 50)
        search_results[index - 1]["source_reason"] = score_item.get("reason", "")

    for item in search_results:
        item.setdefault("source_score", 50)
        item.setdefault("source_reason", "No AI score returned.")

    search_results.sort(
        key=lambda item: item["source_score"],
        reverse=True,
    )

    return search_results


def extract_answers(query, search_results):
    answers = []

    for index, result in enumerate(
        search_results,
        start=1
    ):
        page_content = result.get(
            "page_content",
            ""
        )

        input_text = (
            "User question:\n"
            + query
            + "\n\nSource:\n"
            + f"Title: {result['title']}\n"
            + f"Description: {result['description']}\n"
            + f"URL: {result['url']}\n"
            + f"Domain: {result['domain']}\n"
            + f"Source Score: {result.get('source_score', 50)}\n"
            + f"Page Content:\n{page_content}\n"
        )

        result_ai = run_ai_prompt(
            "prompts/extract_single.txt",
            input_text,
            expect_json=True,
            num_ctx=8192,
            num_predict=512,
            think=False,
            model_name="gemma4:12b",
        )

        if result_ai is None:
            answer = None

        else:
            answer = result_ai.get(
                "answer"
            )

        answers.append({
            "index": index,
            "answer": answer
        })

    return answers


def find_consensus(query, answers):
    input_text = (
        "User question:\n"
        + query
        + "\n\nExtracted answers:\n"
        + json.dumps(answers, ensure_ascii=False, indent=2)
    )

    result = run_ai_prompt(
        "prompts/consensus.txt",
        input_text,
        expect_json=True,
        num_ctx=4096,
        num_predict=512,
        think=False,
        model_name="gemma4:12b",
    )

    if not isinstance(result, dict):
        return {
            "consensus": False,
            "canonical_answer": None,
            "votes": 0,
            "need_more_sources": True,
            "reason": "Consensus AI failed.",
        }

    return result


def _status(callback, text):
    if callback:
        callback(text)

def _source_summary(results):
    return [
        {
            "title": item.get("title", ""),
            "description": item.get("description", ""),
            "domain": item.get("domain", ""),
            "url": item.get("url", ""),
            "published": item.get("published", ""),
            "source_score": item.get("source_score", 50),
            "source_reason": item.get("source_reason", ""),
            "is_concrete_news": item.get(
                "is_concrete_news",
                False,
            ),
            "content_type": item.get(
                "content_type",
                "OTHER",
            ),
            "news_score": item.get("news_score", 0),
            "feed_score": item.get("feed_score", 0),
            "image_url": item.get("image_url", ""),
            "page_success": item.get("page_success", False),
            "reader_type": item.get("reader_type", ""),
            "page_error": item.get("page_error", ""),
        }
        for item in results
    ]


def _has_extracted_answer(answers):
    return any(
        isinstance(item, dict)
        and item.get("answer") not in (None, "", [], {})
        for item in (answers or [])
    )

def _deduplicate_headlines(results):
    """Remove exact/near-exact headline duplicates without merging stories."""
    unique_results = []
    seen_titles = set()
    seen_urls = set()

    for item in results:
        url = item.get("url", "").strip().lower()
        title = item.get("title", "").strip().lower()
        title_key = re.sub(r"[^a-z0-9\\u4e00-\\u9fff]+", "", title)

        if url and url in seen_urls:
            continue
        if title_key and title_key in seen_titles:
            continue

        if url:
            seen_urls.add(url)
        if title_key:
            seen_titles.add(title_key)
        unique_results.append(item)

    return unique_results


def rank_news_results(query, search_results):
    candidate_text = ""

    for index, item in enumerate(search_results, start=1):
        candidate_text += (
            f"\nCandidate {index}\n"
            f"Title: {item.get('title', '')}\n"
            f"Description: {item.get('description', '')}\n"
            f"Domain: {item.get('domain', '')}\n"
            f"URL: {item.get('url', '')}\n"
            f"Published: {item.get('published', '')}\n"
            f"Source score: {item.get('source_score', 50)}\n"
        )

    result = run_ai_prompt(
        "prompts/news_rank.txt",
        "User news request:\n"
        + query
        + "\n\nCandidates:\n"
        + candidate_text,
        expect_json=True,
        num_ctx=8192,
        num_predict=1024,
        think=False,
        model_name="gemma4:12b",
    )

    decisions = result.get("items", []) if isinstance(result, dict) else []
    decision_map = {
        item.get("index"): item
        for item in decisions
        if isinstance(item, dict)
    }

    classified = []

    for index, source in enumerate(search_results, start=1):
        item = dict(source)
        decision = decision_map.get(index, {})

        content_type = str(
            decision.get("content_type", "OTHER")
        ).upper().strip()
        item["content_type"] = content_type

        try:
            item["news_score"] = max(
                0,
                min(100, int(decision.get("news_score", 0))),
            )
        except (TypeError, ValueError):
            item["news_score"] = 0

        item["is_concrete_news"] = (
            bool(decision.get("is_concrete_news", False))
            and content_type == "NEWS"
            and item["news_score"] >= 55
        )

        item["feed_score"] = round(
            item.get("source_score", 50) * 0.45
            + item["news_score"] * 0.55
        )
        classified.append(item)

    classified.sort(
        key=lambda item: (
            item["is_concrete_news"],
            item["feed_score"],
        ),
        reverse=True,
    )

    return classified


def news_feed_controller(queries, status_callback=None):
    """Return a weighted current-news feed. Never run 3→5→7 here."""
    _status(status_callback, "正在搜索新闻… 🔍")
    if isinstance(queries, str):
        queries = [queries]
    queries = [str(value).strip() for value in queries if str(value).strip()][:2]
    search_results = []
    search_errors = []
    for query in queries:
        found = search(query, count=7, freshness="pw")
        if isinstance(found, list):
            search_results.extend(found)
        else:
            search_errors.append(str(found))
    search_results = _deduplicate_headlines(search_results)[:14]
    combined_query = " | ".join(queries)

    if not search_results and search_errors:
        return {
            "status": "ERROR",
            "query": combined_query,
            "context": "News search failed: " + "; ".join(search_errors),
        }

    if not search_results:
        return {
            "status": "NO_RESULTS",
            "query": combined_query,
            "context": "No current news results were found for: " + combined_query,
        }

    _status(status_callback, "正在按来源排序… 📚")
    scored_results = score_sources(combined_query, search_results)
    ranked_results = _deduplicate_headlines(
        rank_news_results(combined_query, scored_results)
    )

    feed_items = _source_summary(ranked_results)
    cards = result_cards.clean_cards(
        [
            {
                "type": "news",
                "title": item.get("title", ""),
                "summary": item.get("description", ""),
                "url": item.get("url", ""),
                "domain": item.get("domain", ""),
                "image": (
                    {
                        "url": item.get("image_url", ""),
                        "alt": item.get("title", ""),
                        "source_url": item.get("url", ""),
                    }
                    if item.get("image_url")
                    else None
                ),
                "metadata": {
                    "published_at": item.get("published") or "",
                    "captured_at": datetime.now().astimezone().isoformat(),
                },
                "requirements": [],
            }
            for item in ranked_results
            if item.get("is_concrete_news")
            and item.get("url")
            and item.get("title")
        ][:4]
    )
    print(
        "[NEWS CARDS]",
        len(cards),
    )
    context = (
        "melchior response mode: NEWS_FEED\n"
        "The user requested a broad current-news digest.\n"
        "Present the following items as a concise ranked feed.\n"
        "Keep their source names and dates when available.\n"
        "Write the news digest only from items where "
        "is_concrete_news is True.\n"
        "Keep every other source as a clikcable link source,"
        "but do not describe it as news.\n"
        "Do not turn one article into a verified universal fact.\n\n"
        "Ranked news items:\n"
        + json.dumps(feed_items, ensure_ascii=False, indent=2)
    )

    return {
        "status": "OK",
        "query": combined_query,
        "queries": queries,
        "results": ranked_results,
        "cards": cards,
        "context": context,
    }


def _shopping_context_scope(user_message):
    """Allow prior shopping text only for an explicitly referential turn."""
    text = re.sub(r"\s+", " ", str(user_message or "")).casefold().strip()
    reference_patterns = (
        r"(?:这|那)(?:个|些|几|三|款|种|一个|几个)(?:里|面)?",
        r"第(?:一|二|三|四|五|六|七|八|九|十|一个|二个|三个)个|"
        r"最后一个|前一个|后一个",
        r"刚才|上一个|上一轮|之前(?:的|那|推荐|提到|说|看|找)|"
        r"前面(?:的|那|推荐|提到|说|看|找)|同样|一样|换成|改成",
        r"\b(?:that|these|those|them|it|same|previous|former|latter)\b",
        r"\bthis\s+(?:one|product|option|item|brand)\b",
        r"\b(?:instead|cheaper one|more expensive one|the three)\b",
    )
    return (
        "NEEDS_CONTEXT"
        if any(re.search(pattern, text, re.IGNORECASE) for pattern in reference_patterns)
        else "CURRENT_ONLY"
    )


def _shopping_popularity_requirement(user_message):
    """Normalize only an explicit popularity/brand-position constraint."""
    text = re.sub(r"\s+", " ", str(user_message or "")).casefold().strip()
    chinese_popularity = (
        r"(?:网红|爆红|爆款|主流|大牌|知名|名牌|热门|流行|畅销|热卖)"
    )
    text = re.sub(
        rf"(?:不要|不想|不是|并非|没那么|别|拒绝|避开|排除|不考虑|无需|不|非)"
        rf"\s*(?:(?:是|想|要|买|推荐|选择|考虑|很|太|那么|特别|真的|非常)\s*){{0,4}}"
        rf"{chinese_popularity}(?:牌子|品牌)?",
        " ",
        text,
    )
    text = re.sub(
        rf"{chinese_popularity}(?:牌子|品牌)?"
        rf"[^，,。；;！？!?但而]{{0,8}}"
        rf"(?:除外|不要(?:了|的)?(?=[，,。；;！？!?\s]|$))",
        " ",
        text,
    )
    english_popularity = (
        r"(?:viral|trending|mainstream|popular|well[- ]known|"
        r"established(?:\s+brand)?|best[- ]selling|best\s+seller|"
        r"internet[- ]famous)"
    )
    text = re.sub(
        rf"(?<![a-z])(?:do\s+not|don['’]?t|anything\s+but|not|no|without|avoid|exclude)"
        rf"\s+(?:(?:longer|really|want|buy|recommend|choose|consider|too|very|particularly)\s+){{0,4}}"
        rf"{english_popularity}(?:\s+brands?)?(?![a-z])",
        " ",
        text,
        flags=re.IGNORECASE,
    )
    text = re.sub(
        rf"(?<![a-z])(?:non[- ]?|un){english_popularity}(?![a-z])",
        " ",
        text,
        flags=re.IGNORECASE,
    )
    text = re.sub(
        rf"(?<![a-z]){english_popularity}(?:\s+brands?)?"
        rf"(?:\s+(?!(?:but|however|except)\b)[a-z][a-z-]*){{0,3}}"
        rf"\s+(?:excluded|not\s+wanted)(?![a-z])",
        " ",
        text,
        flags=re.IGNORECASE,
    )
    groups = (
        (
            "CURRENTLY_TRENDING",
            ("网红", "爆红", "爆款", "viral", "trending", "internet-famous"),
        ),
        (
            "ESTABLISHED_BRAND",
            ("主流", "大牌", "知名", "名牌", "mainstream", "well-known", "established brand"),
        ),
        (
            "PROVEN_DEMAND",
            ("热门", "流行", "畅销", "热卖", "popular", "best-selling", "best seller"),
        ),
    )
    for requirement, phrases in groups:
        for phrase in phrases:
            if re.search(r"[\u3400-\u9fff]", phrase):
                matched = phrase in text
            else:
                pattern = re.escape(phrase).replace(r"\ ", r"[-\s]+")
                matched = bool(
                    re.search(
                        rf"(?<![a-z0-9]){pattern}(?![a-z0-9])",
                        text,
                        flags=re.IGNORECASE,
                    )
                )
            if matched:
                return requirement, phrase
    return "NONE", ""


def _shopping_category_candidate(value, user_message, region, popularity):
    """Strip search/popularity wording and keep a compact English category."""
    text = re.sub(r"\s+", " ", str(value or "")).strip(" -_.,")
    if not text:
        return ""

    request_text = str(user_message or "").casefold()
    person_meaning_is_explicit = bool(
        re.search(
            r"明星|艺人|偶像|韩国|韩流|\b(?:celebrity|influencer|korean|k-pop)\b",
            request_text,
            re.IGNORECASE,
        )
    )
    if popularity != "NONE" and not person_meaning_is_explicit:
        text = re.sub(
            r"\b(?:netred|internet[- ]?celebrity|online celebrity|"
            r"social media celebrity|celebrity|k[- ]?pop star|"
            r"social media star|influencer)\b",
            " ",
            text,
            flags=re.IGNORECASE,
        )
        text = re.sub(
            r"\b(?:korean|k[- ]?pop)\b",
            " ",
            text,
            flags=re.IGNORECASE,
        )

    text = re.sub(
        r"\b(?:currently\s+trending|internet[- ]?famous|viral|trending|"
        r"mainstream|well[- ]known|established|popular|best[- ]selling|"
        r"best seller|high review count|top[- ]rated|best rated|trusted)\b",
        " ",
        text,
        flags=re.IGNORECASE,
    )
    text = re.sub(r"\bbrands?\b", " ", text, flags=re.IGNORECASE)
    text = re.sub(r"\b20\d{2}\b", " ", text)
    country_name = str((region or {}).get("country_name") or "").strip()
    if country_name:
        text = re.sub(
            rf"\b{re.escape(country_name)}\b",
            " ",
            text,
            flags=re.IGNORECASE,
        )
    text = re.sub(r"\s+", " ", text).strip(" -_.,")

    country_code = str((region or {}).get("country_code") or "").upper().strip()
    if country_code in {"US", "CA", "GB", "AU", "NZ", "IE"}:
        if re.search(r"[\u3400-\u9fff]", text):
            return ""
        latin_words = re.findall(r"[A-Za-z]{2,}", text)
        if not latin_words:
            return ""
        generic = {"brand", "brands", "item", "items", "product", "products"}
        if all(word.casefold() in generic for word in latin_words):
            return ""
    return text[:160]


def _shopping_requirement_in_search_material(requirement, material):
    requirement_text = re.sub(
        r"[^\w\u3400-\u9fff]+", " ", str(requirement or "").casefold()
    ).strip()
    material_text = re.sub(
        r"[^\w\u3400-\u9fff]+", " ", str(material or "").casefold()
    ).strip()
    if not requirement_text or not material_text:
        return False
    return f" {requirement_text} " in f" {material_text} "


def _shopping_number_tokens(value):
    output = set()
    for raw in re.findall(r"\d+(?:[.,]\d+)?", str(value or "")):
        normalized = raw.replace(",", "")
        if "." in normalized:
            normalized = normalized.rstrip("0").rstrip(".")
        output.add(normalized or "0")
    return output


def _shopping_constraint_tokens(value):
    text = str(value or "").casefold()
    replacements = (
        (r"美元", " usd "),
        (r"欧元", " eur "),
        (r"英镑", " gbp "),
        (r"人民币|元", " cny "),
        (r"毫升", " ml "),
        (r"千克|公斤", " kg "),
        (r"克", " g "),
        (r"盎司", " oz "),
        (r"磅", " lb "),
        (r"小时", " hr "),
        (r"分钟", " min "),
        (r"以下|以内|不超过|至多", " under "),
        (r"以上|至少|不少于", " over "),
        (r"升", " l "),
        (r"\$|\b(?:usd|us dollars?|dollars?)\b", " usd "),
        (r"€|\b(?:eur|euros?)\b", " eur "),
        (r"£|\b(?:gbp|pounds? sterling)\b", " gbp "),
        (r"¥|￥|\b(?:cny|rmb|yuan)\b", " cny "),
        (r"\b(?:milliliters?|millilitres?)\b", " ml "),
        (r"\b(?:liters?|litres?)\b", " l "),
        (r"\b(?:ounces?)\b", " oz "),
        (r"\b(?:kilograms?)\b", " kg "),
        (r"\b(?:grams?)\b", " g "),
        (r"\b(?:pounds?|lbs?)\b", " lb "),
        (r"\b(?:hours?|hrs?)\b", " hr "),
        (r"\b(?:minutes?|mins?)\b", " min "),
        (r"\b(?:less than|below|no more than|at most|maximum|max)\b", " under "),
        (r"\b(?:more than|above|at least|minimum)\b", " over "),
    )
    for pattern, replacement in replacements:
        text = re.sub(pattern, replacement, text, flags=re.IGNORECASE)
    text = re.sub(r"\d+(?:[.,]\d+)?", " ", text)
    stopwords = {
        "a", "an", "the", "of", "or", "and", "approximately", "about",
        "around", "capacity", "size", "budget", "price", "target",
    }
    return {
        token
        for token in re.findall(r"[a-z]+", text)
        if token not in stopwords
    }


def _shopping_requirement_is_grounded_in_plan(
    requirement,
    source_phrase,
    search_material,
):
    exact_match = _shopping_requirement_in_search_material(
        requirement, search_material
    )
    requirement_numbers = _shopping_number_tokens(requirement)
    if not requirement_numbers:
        return exact_match
    if not requirement_numbers.issubset(_shopping_number_tokens(search_material)):
        return False
    if not requirement_numbers.issubset(_shopping_number_tokens(source_phrase)):
        return False
    requirement_tokens = _shopping_constraint_tokens(requirement)
    search_tokens = _shopping_constraint_tokens(search_material)
    source_tokens = _shopping_constraint_tokens(source_phrase)
    if not requirement_tokens.issubset(search_tokens):
        return False
    critical = {
        "usd", "eur", "gbp", "cny", "ml", "l", "oz", "kg", "g", "lb",
        "hr", "min", "under", "over",
    }
    return (requirement_tokens & critical).issubset(source_tokens & critical)


def _shopping_source_is_popularity_only(source_phrase):
    cleaned = re.sub(
        r"网红|爆红|爆款|主流|大牌|知名|名牌|热门|流行|畅销|热卖|"
        r"\b(?:viral|trending|mainstream|well-known|established|popular|"
        r"best-selling|best seller|internet-famous)\b",
        " ",
        str(source_phrase or ""),
        flags=re.IGNORECASE,
    )
    cleaned = re.sub(r"牌子|品牌|brands?", " ", cleaned, flags=re.IGNORECASE)
    return not re.sub(r"[\W_]+", "", cleaned, flags=re.UNICODE)


def _shopping_non_popularity_source_material(user_message):
    text = re.sub(r"\s+", " ", str(user_message or "").casefold()).strip()
    text = re.sub(
        r"(?:网红|爆红|爆款|主流|大牌|知名|名牌|热门|流行|畅销|热卖)"
        r"(?:牌子|品牌)?",
        " ",
        text,
    )
    text = re.sub(
        r"\b(?:internet-famous|viral|trending|mainstream|well-known|"
        r"established brand|popular|best-selling|best seller)\b",
        " ",
        text,
        flags=re.IGNORECASE,
    )
    return re.sub(r"\s+", " ", text).strip()


def _shopping_search_has_unowned_popularity_drift(
    value,
    user_message,
    popularity,
):
    if popularity == "NONE":
        return False
    search_text = str(value or "").casefold()
    request_text = str(user_message or "").casefold()
    person_meaning_is_explicit = bool(
        re.search(
            r"明星|艺人|偶像|韩国|韩流|\b(?:celebrity|influencer|korean|k-pop)\b",
            request_text,
            re.IGNORECASE,
        )
    )
    if not person_meaning_is_explicit and re.search(
        r"\b(?:netred|internet[- ]?celebrity|online celebrity|"
        r"social media celebrity|celebrity|k[- ]?pop(?: star)?|"
        r"korean|social media star|influencer)\b",
        search_text,
        re.IGNORECASE,
    ):
        return True
    if (
        re.search(r"\bred\b", search_text)
        and "红" not in _shopping_non_popularity_source_material(user_message)
        and not re.search(r"\bred\b", request_text)
    ):
        return True
    return False


def _shopping_category_verification_is_usable(
    raw,
    user_message,
    category,
    context_scope="CURRENT_ONLY",
    recent_context="",
):
    if not isinstance(raw, dict):
        return False
    if str(raw.get("verdict") or "").strip().upper() != "MATCH":
        return False
    if str(raw.get("constraints_verdict") or "").strip().upper() != "COMPLETE":
        return False
    missing_constraints = raw.get("unrepresented_constraint_source_phrases")
    if not isinstance(missing_constraints, list) or missing_constraints:
        return False
    echoed_category = re.sub(
        r"\s+", " ", str(raw.get("english_category") or "").casefold()
    ).strip()
    expected_category = re.sub(
        r"\s+", " ", str(category or "").casefold()
    ).strip()
    if not echoed_category or echoed_category != expected_category:
        return False
    source_phrase = re.sub(
        r"\s+", " ", str(raw.get("source_category_phrase") or "").casefold()
    ).strip()
    source_scope = str(
        raw.get("source_category_scope") or ""
    ).strip().upper()
    current_source_material = _shopping_non_popularity_source_material(
        user_message
    )
    recent_source_material = _shopping_non_popularity_source_material(
        recent_context
    )
    if source_scope == "CURRENT_REQUEST":
        source_material = current_source_material
    elif source_scope == "RECENT_CONTEXT" and context_scope == "NEEDS_CONTEXT":
        source_material = recent_source_material
    else:
        return False
    compact_source = re.sub(
        r"[^\w\u3400-\u9fff]+", "", source_phrase
    )
    source_length_ok = bool(re.search(r"[\u3400-\u9fff]", compact_source)) or (
        len(compact_source) >= 2
    )
    if (
        not source_phrase
        or source_phrase not in source_material
        or _shopping_source_is_popularity_only(source_phrase)
        or not source_length_ok
    ):
        return False
    if re.fullmatch(
        r"(?:给我|帮我|推荐|找|搜索|购买|买|三个|三款|产品|商品|"
        r"recommend|find|search|buy|three|products?|items?)",
        source_phrase,
        flags=re.IGNORECASE,
    ):
        return False
    return True


def _shopping_semantic_tokens(value):
    tokens = []
    for token in re.findall(r"[a-z]+", str(value or "").casefold()):
        if token.endswith("s") and len(token) > 3 and not token.endswith("ss"):
            token = token[:-1]
        tokens.append(token)
    tokens.extend(re.findall(r"[\u3400-\u9fff]+", str(value or "")))
    return set(tokens)


def _shopping_hard_constraint_number_tokens(user_message):
    text = str(user_message or "")
    text = re.sub(
        r"(?<!\d)\d+\s*(?:个|款|种|件|台|部|双|只)"
        r"(?!\s*(?:装|套|包))|"
        r"\b\d+\s+(?:different\s+)?(?:products?|items?|options?|candidates?)\b",
        " ",
        text,
        flags=re.IGNORECASE,
    )
    return _shopping_number_tokens(text)


def _shopping_raw_category_is_grounded(
    raw,
    user_message,
    region,
    popularity,
):
    if not isinstance(raw, dict):
        return False
    country_code = str((region or {}).get("country_code") or "").upper().strip()
    if country_code not in {"US", "CA", "GB", "AU", "NZ", "IE"}:
        return True
    category = _shopping_category_candidate(
        raw.get("product_query"), user_message, region, popularity
    )
    category_tokens = _shopping_semantic_tokens(category)
    if not category_tokens:
        return False
    queries = raw.get("queries") if isinstance(raw.get("queries"), list) else []
    search_material = " ".join(
        [str(raw.get("product_query") or "")] + [str(value) for value in queries]
    )
    source_material = _shopping_non_popularity_source_material(user_message)
    covered_tokens = set()
    covered_constraint_numbers = set()
    required_constraint_numbers = _shopping_hard_constraint_number_tokens(
        user_message
    )
    values = raw.get("requirements")
    if not isinstance(values, list):
        return False
    for value in values[:12]:
        if isinstance(value, dict):
            requirement = str(value.get("requirement") or "").strip()[:120]
            source_phrase = re.sub(
                r"\s+", " ", str(value.get("source_phrase") or "").casefold()
            ).strip()
            source_owned = bool(
                source_phrase and source_phrase in source_material
            )
        else:
            requirement = str(value or "").strip()[:120]
            source_phrase = requirement
            source_owned = bool(
                requirement
                and requirement.casefold() in source_material
            )
        popularity_only_source = _shopping_source_is_popularity_only(
            source_phrase
        )
        generic_requirement = requirement.casefold() in {
                "brand", "brands", "category", "normalized category",
                "product category", "size", "feature", "quality",
            }
        ungrounded_number = _requirement_has_ungrounded_number(
            requirement, user_message
        )
        plan_grounded = _shopping_requirement_is_grounded_in_plan(
                requirement,
                source_phrase,
                search_material,
            )
        source_numbers = _shopping_number_tokens(source_phrase)
        if source_owned and source_numbers and (
            popularity_only_source
            or generic_requirement
            or ungrounded_number
            or not plan_grounded
        ):
            return False
        if (
            not requirement
            or not source_owned
            or popularity_only_source
            or generic_requirement
            or ungrounded_number
            or not plan_grounded
        ):
            continue
        covered_tokens.update(_shopping_semantic_tokens(requirement))
        covered_constraint_numbers.update(source_numbers)
    return (
        category_tokens.issubset(covered_tokens)
        and required_constraint_numbers.issubset(covered_constraint_numbers)
    )


def _shopping_query_contract_is_usable(
    raw,
    user_message,
    region,
    popularity,
    recent_context="",
):
    if not isinstance(raw, dict):
        return False
    queries = raw.get("queries")
    product_query = str(raw.get("product_query") or "").strip()
    if (
        not isinstance(queries, list)
        or not 1 <= len(queries) <= 3
        or not product_query
        or any(not isinstance(value, str) or not value.strip() for value in queries)
    ):
        return False

    if any(
        _shopping_search_has_unowned_popularity_drift(
            value,
            user_message,
            popularity,
        )
        for value in [product_query] + [str(item) for item in queries]
    ):
        return False

    country_code = str((region or {}).get("country_code") or "").upper().strip()
    latin_search_markets = {"US", "CA", "GB", "AU", "NZ", "IE"}
    if country_code in latin_search_markets:
        values = [product_query] + [str(value) for value in queries]
        for index, value in enumerate(values):
            latin_words = re.findall(r"[A-Za-z]{2,}", value)
            cjk_characters = len(re.findall(r"[\u3400-\u9fff]", value))
            if (
                len(latin_words) < (1 if index == 0 else 2)
                or cjk_characters
            ):
                return False

        category = _shopping_category_candidate(
            product_query,
            user_message,
            region,
            popularity,
        )
        category_tokens = _shopping_semantic_tokens(category)
        if not category_tokens:
            return False
        for query in queries:
            if not category_tokens.issubset(
                _shopping_semantic_tokens(query)
            ):
                return False

    current_year = str(datetime.now().year)
    request_text = (
        str(user_message or "") + "\n" + str(recent_context or "")
    )
    allowed_query_numbers = _shopping_hard_constraint_number_tokens(
        user_message
    ) | _shopping_hard_constraint_number_tokens(recent_context) | {current_year}
    for value in [product_query] + [str(item) for item in queries]:
        if _shopping_number_tokens(value) - allowed_query_numbers:
            return False
        for year in re.findall(r"\b20\d{2}\b", value):
            if year != current_year and year not in request_text:
                return False

    if popularity != "NONE":
        material = " ".join([product_query] + [str(value) for value in queries]).casefold()
        popularity_terms = (
            "popular", "viral", "trending", "mainstream", "well-known",
            "established brand", "best-selling", "best seller", "high review",
        )
        if not any(term in material for term in popularity_terms):
            return False
    return True


def _requirement_has_ungrounded_number(
    requirement,
    user_message,
    recent_context="",
):
    return bool(
        _shopping_number_tokens(requirement)
        - _shopping_number_tokens(
            str(user_message or "") + "\n" + str(recent_context or "")
        )
    )


def _recover_shopping_popularity_plan(
    primary_raw,
    retry_raw,
    user_message,
    region,
    popularity,
    recent_context="",
):
    """Recover a verified category consensus from two unusable plans."""
    if not isinstance(primary_raw, dict) or not isinstance(retry_raw, dict):
        return None
    categories = [
        _shopping_category_candidate(
            raw.get("product_query"), user_message, region, popularity
        )
        for raw in (primary_raw, retry_raw)
    ]
    if not all(categories):
        return None
    normalized_categories = [
        re.sub(r"\s+", " ", value.casefold()).strip() for value in categories
    ]
    if normalized_categories[0] != normalized_categories[1]:
        return None
    category = categories[1]
    constraint_source_material = " ".join(
        value
        for value in (
            _shopping_non_popularity_source_material(user_message),
            _shopping_non_popularity_source_material(recent_context),
        )
        if value
    )

    # Recovery never merges one attempt's constraint into the other. A hard
    # constraint must be independently present and query-grounded in both.
    if primary_raw.get("localized_constraints") or retry_raw.get("localized_constraints"):
        return None

    def constraint_map(raw):
        raw_search_material = " ".join(
            str(value)
            for value in (
                [raw.get("product_query", "")]
                + (
                    raw.get("queries")
                    if isinstance(raw.get("queries"), list)
                    else []
                )
            )
        )
        output = {}
        values = raw.get("requirements")
        if not isinstance(values, list):
            return output
        for value in values:
            if not isinstance(value, dict):
                continue
            requirement = str(value.get("requirement") or "").strip()[:120]
            source_phrase = re.sub(
                r"\s+", " ", str(value.get("source_phrase") or "").casefold()
            ).strip()
            if (
                not requirement
                or not source_phrase
                or source_phrase not in constraint_source_material
                or _shopping_source_is_popularity_only(source_phrase)
                or _requirement_has_ungrounded_number(
                    requirement,
                    user_message,
                    recent_context,
                )
                or not _shopping_requirement_is_grounded_in_plan(
                    requirement,
                    source_phrase,
                    raw_search_material,
                )
            ):
                continue
            normalized = requirement.casefold()
            if normalized in {
                "brand", "brands", "category", "normalized category",
                "product category", "size", "feature", "quality",
            }:
                continue
            if _shopping_requirement_in_search_material(requirement, category):
                continue
            count_only = bool(
                re.search(
                    r"三个(?:不同)?(?:产品|商品|选项|候选|杯子|杯款)?|三款|"
                    r"\b(?:three|3)\s+(?:different\s+)?"
                    r"(?:products?|options?|candidates?|items?|cups?)\b",
                    (requirement + " " + source_phrase).casefold(),
                )
            )
            if count_only:
                continue
            key = (
                re.sub(r"\s+", " ", requirement.casefold()).strip(),
                source_phrase,
            )
            output[key] = {
                "requirement": requirement,
                "source_phrase": source_phrase,
            }
        return output

    primary_constraints = constraint_map(primary_raw)
    retry_constraints = constraint_map(retry_raw)
    if set(primary_constraints) != set(retry_constraints):
        return None
    consensus_rows = [
        retry_constraints[key]
        for key in retry_constraints
        if key in primary_constraints
    ]
    covered_repair_numbers = set()
    for row in consensus_rows:
        covered_repair_numbers.update(
            _shopping_number_tokens(row.get("source_phrase"))
        )
    if not (
        _shopping_hard_constraint_number_tokens(user_message)
        | _shopping_hard_constraint_number_tokens(recent_context)
    ).issubset(
        covered_repair_numbers
    ):
        return None
    repair_constraints = [
        row["requirement"] for row in consensus_rows
    ]

    base = " ".join([category] + list(dict.fromkeys(repair_constraints)))
    year = str(datetime.now().year)
    country = str(
        (region or {}).get("country_name")
        or (region or {}).get("country_code")
        or ""
    ).strip()
    qualifiers = {
        "CURRENTLY_TRENDING": f"viral trending brands {year}",
        "ESTABLISHED_BRAND": "mainstream well-known established brands",
        "PROVEN_DEMAND": "best-selling high review count",
        "NONE": "best rated high review count",
    }
    query = " ".join(
        value for value in (base, qualifiers.get(popularity, ""), country) if value
    )
    repaired = dict(retry_raw)
    repaired["product_query"] = category
    repaired["queries"] = [re.sub(r"\s+", " ", query).strip()[:220]]
    repaired["requirements"] = consensus_rows[:12]
    repaired["localized_constraints"] = []
    repaired["_python_grounded_category"] = category
    return repaired


def build_shopping_plan(
    user_message,
    recent_context="",
    region=None,
    allow_category_translation_repair=False,
):
    """Build a current-turn-grounded product plan with bounded context use."""
    explicit_merchant = _explicit_shopping_merchant(user_message, region)
    context_scope = _shopping_context_scope(user_message)
    reference_context = (
        str(recent_context)[-800:]
        if context_scope == "NEEDS_CONTEXT"
        else ""
    )
    popularity_requirement, popularity_phrase = (
        _shopping_popularity_requirement(user_message)
    )
    planning_packet = {
        "current_date": datetime.now().date().isoformat(),
        "shopping_region": region or {},
        "current_request": str(user_message)[:900],
        "context_scope": context_scope,
        "explicit_merchant": explicit_merchant,
        "popularity_requirement": popularity_requirement,
        "popularity_phrase": popularity_phrase,
    }
    if context_scope == "NEEDS_CONTEXT":
        planning_packet["recent_context_for_reference"] = str(recent_context)[-1400:]
    print("[SHOPPING PLAN CONTEXT]", context_scope)

    def call_planner(
        prompt_path,
        packet,
        num_ctx,
        num_predict,
        json_schema=None,
    ):
        try:
            return run_ai_prompt(
                prompt_path,
                json.dumps(packet, ensure_ascii=False, separators=(",", ":")),
                expect_json=True,
                num_ctx=num_ctx,
                num_predict=num_predict,
                think=False,
                model_name="llama3.2:latest",
                json_schema=json_schema,
            )
        except Exception as error:
            print("[SHOPPING PLAN MODEL ERROR]", prompt_path, repr(error))
            return None

    def plan_is_usable(candidate):
        if not _shopping_query_contract_is_usable(
            candidate,
            user_message,
            region,
            popularity_requirement,
            reference_context,
        ):
            return False
        if isinstance(candidate, dict) and candidate.get(
            "_python_grounded_category"
        ):
            return True
        if context_scope != "CURRENT_ONLY":
            return True
        return _shopping_raw_category_is_grounded(
            candidate,
            user_message,
            region,
            popularity_requirement,
        )

    def semantic_plan_is_usable(candidate, stage):
        if not plan_is_usable(candidate):
            return False
        verification = call_planner(
            "prompts/shopping_category_verify.txt",
            {
                "current_request": str(user_message)[:900],
                "current_request_without_popularity": (
                    _shopping_non_popularity_source_material(user_message)
                )[:900],
                "context_scope": context_scope,
                "recent_context_for_reference": (
                    reference_context
                ),
                "candidate_english_category": candidate.get(
                    "product_query", ""
                ),
                "candidate_queries": candidate.get("queries", []),
                "candidate_requirements": candidate.get(
                    "requirements", []
                ),
                "popularity_requirement": popularity_requirement,
            },
            2048,
            220,
        )
        verified = _shopping_category_verification_is_usable(
            verification,
            user_message,
            candidate.get("product_query", ""),
            context_scope,
            reference_context,
        )
        if not verified:
            print("[SHOPPING PLAN SEMANTIC REJECTED]", stage)
        return verified

    def translated_category_repair():
        """Translate one intact source category before rebuilding a safe query."""
        translation = call_planner(
            "prompts/shopping_category_translate.txt",
            {
                "current_request": str(user_message)[:900],
                "current_request_without_popularity": (
                    _shopping_non_popularity_source_material(user_message)
                )[:900],
                "context_scope": context_scope,
                "recent_context_for_reference": reference_context,
                "shopping_region": region or {},
                "popularity_requirement": popularity_requirement,
            },
            2048,
            260,
            json_schema={
                "type": "object",
                "properties": {
                    "source_category_scope": {
                        "type": "string",
                        "enum": ["CURRENT_REQUEST", "RECENT_CONTEXT"],
                    },
                    "source_category_phrase": {"type": "string"},
                    "english_category": {"type": "string"},
                    "constraints": {
                        "type": "array",
                        "maxItems": 8,
                        "items": {
                            "type": "object",
                            "properties": {
                                "source_phrase": {"type": "string"},
                                "english_requirement": {"type": "string"},
                            },
                            "required": [
                                "source_phrase",
                                "english_requirement",
                            ],
                        },
                    },
                },
                "required": [
                    "source_category_scope",
                    "source_category_phrase",
                    "english_category",
                    "constraints",
                ],
            },
        )
        if not isinstance(translation, dict):
            return None
        source_scope = str(
            translation.get("source_category_scope") or ""
        ).strip().upper()
        if source_scope == "CURRENT_REQUEST":
            source_material = _shopping_non_popularity_source_material(
                user_message
            )
        elif source_scope == "RECENT_CONTEXT" and context_scope == "NEEDS_CONTEXT":
            source_material = _shopping_non_popularity_source_material(
                reference_context
            )
        else:
            return None
        source_phrase = re.sub(
            r"\s+",
            " ",
            str(translation.get("source_category_phrase") or "").casefold(),
        ).strip()
        category = re.sub(
            r"\s+",
            " ",
            str(translation.get("english_category") or ""),
        ).strip()[:120]
        if (
            not source_phrase
            or source_phrase not in source_material
            or _shopping_source_is_popularity_only(source_phrase)
            or not category
            or re.search(r"[\u3400-\u9fff]", category)
            or not re.search(r"[A-Za-z]", category)
        ):
            return None
        rows = [{"requirement": category, "source_phrase": source_phrase}]
        query_requirements = []
        values = translation.get("constraints")
        if not isinstance(values, list):
            return None
        for value in values[:8]:
            if not isinstance(value, dict):
                return None
            owned_phrase = re.sub(
                r"\s+",
                " ",
                str(value.get("source_phrase") or "").casefold(),
            ).strip()
            requirement = re.sub(
                r"\s+",
                " ",
                str(value.get("english_requirement") or ""),
            ).strip()[:120]
            if (
                not owned_phrase
                or owned_phrase not in source_material
                or _shopping_source_is_popularity_only(owned_phrase)
                or not requirement
                or re.search(r"[\u3400-\u9fff]", requirement)
            ):
                return None
            rows.append(
                {
                    "requirement": requirement,
                    "source_phrase": owned_phrase,
                }
            )
            query_requirements.append(requirement)
        qualifiers = {
            "CURRENTLY_TRENDING": "viral trending brands",
            "ESTABLISHED_BRAND": "mainstream well-known established brands",
            "PROVEN_DEMAND": "best-selling high review count",
            "NONE": "best rated high review count",
        }
        country = str(
            (region or {}).get("country_name")
            or (region or {}).get("country_code")
            or ""
        ).strip()
        query = " ".join(
            value
            for value in (
                category,
                " ".join(query_requirements),
                qualifiers.get(popularity_requirement, ""),
                country,
            )
            if value
        )
        return {
            "product_query": category,
            "queries": [re.sub(r"\s+", " ", query).strip()[:220]],
            "requirements": rows,
            "localized_constraints": [],
            "_python_grounded_category": category,
        }

    primary_raw = call_planner(
        "prompts/shopping_query.txt", planning_packet, 4096, 700
    )
    raw = primary_raw
    accepted = semantic_plan_is_usable(primary_raw, "primary")
    retry_raw = None
    if not accepted:
        print("[SHOPPING PLAN RETRY] compact current-turn retry")
        retry_packet = {
            key: value
            for key, value in planning_packet.items()
            if key != "recent_context_for_reference"
        }
        if context_scope == "NEEDS_CONTEXT":
            retry_packet["recent_context_for_reference"] = str(recent_context)[-800:]
        retry_raw = call_planner(
            "prompts/shopping_query_retry.txt", retry_packet, 3072, 600
        )
        raw = retry_raw
        accepted = semantic_plan_is_usable(retry_raw, "retry")

    if not accepted and allow_category_translation_repair:
        translated = translated_category_repair()
        if translated is not None and semantic_plan_is_usable(
            translated, "category_translation"
        ):
            raw = translated
            accepted = True
            print("[SHOPPING PLAN CATEGORY TRANSLATION] grounded repair")
        elif translated is not None:
            print("[SHOPPING PLAN CATEGORY TRANSLATION REJECTED]")

    if not accepted:
        repaired = _recover_shopping_popularity_plan(
            primary_raw,
            retry_raw,
            user_message,
            region,
            popularity_requirement,
            reference_context,
        )
        if repaired is not None and semantic_plan_is_usable(repaired, "repair"):
            raw = repaired
            accepted = True
            print("[SHOPPING PLAN REPAIR] grounded category consensus")
        elif repaired is not None:
            print("[SHOPPING PLAN REPAIR REJECTED] category verification")

    planning_failed = not accepted
    if planning_failed:
        raw = {}

    # AI-suggested merchants are never trusted for a regional mix. Casper
    # discovers real domains later. Only a merchant explicitly present in the
    # current request may constrain the search.
    merchant_scope = "exclusive" if explicit_merchant else "regional_mix"
    clean_merchants = [explicit_merchant] if explicit_merchant else []

    product_query = str(raw.get("product_query") or "").strip()[:160]
    queries = raw.get("queries", [])
    if not isinstance(queries, list):
        queries = []
    queries = [str(value).strip()[:220] for value in queries if str(value).strip()][:3]
    popularity_terms = (
        "popular", "viral", "trending", "mainstream", "well-known",
        "established brand", "best-selling", "best seller", "high review",
    )
    if queries and not any(
        term in " ".join(queries).casefold() for term in popularity_terms
    ):
        queries[0] = (
            queries[0] + " best-selling high review count established brand"
        )[:220]
    if not queries or not product_query:
        planning_failed = True

    raw_requirements = raw.get("requirements", [])
    if not isinstance(raw_requirements, list):
        raw_requirements = []
    constraint_ownership_text = "\n".join(
        value
        for value in (str(user_message or ""), reference_context)
        if value
    )
    request_normalized = re.sub(
        r"\s+", " ", constraint_ownership_text.casefold()
    ).strip()
    constraint_source_material = " ".join(
        value
        for value in (
            _shopping_non_popularity_source_material(user_message),
            _shopping_non_popularity_source_material(reference_context),
        )
        if value
    )
    product_query_normalized = re.sub(
        r"\s+", " ", product_query.casefold()
    ).strip()
    search_material = " ".join([product_query] + queries)
    category_requirement = str(
        raw.get("_python_grounded_category") or ""
    ).strip()[:120]
    requirements = [category_requirement] if category_requirement else []
    for value in raw_requirements[:12]:
        if isinstance(value, dict):
            requirement = str(value.get("requirement") or "").strip()[:120]
            source_phrase = re.sub(
                r"\s+", " ", str(value.get("source_phrase") or "").casefold()
            ).strip()
            source_owned = bool(
                source_phrase and source_phrase in constraint_source_material
            )
            popularity_only_source = _shopping_source_is_popularity_only(
                source_phrase
            )
        else:
            requirement = str(value or "").strip()[:120]
            source_phrase = ""
            requirement_normalized = re.sub(
                r"\s+", " ", requirement.casefold()
            ).strip()
            source_owned = bool(
                requirement_normalized
                and (
                    requirement_normalized in constraint_source_material
                    or requirement_normalized in product_query_normalized
                )
            )
            popularity_only_source = False
        multipack_requested = bool(
            re.search(
                r"三件套|三只装|三个同款|\b(?:3[- ]?pack|three[- ]pack|pack of 3)\b",
                request_normalized,
            )
        )
        count_only_requirement = bool(
            re.search(
                r"三个(?:不同)?(?:产品|商品|选项|候选|杯子|杯款)?|三款|"
                r"\b(?:three|3)\s+(?:different\s+)?(?:products?|options?|candidates?|items?|cups?)\b",
                (requirement + " " + source_phrase).casefold(),
            )
        )
        if count_only_requirement and not multipack_requested:
            continue
        if popularity_only_source:
            continue
        if popularity_requirement != "NONE":
            raw_popularity, _raw_phrase = _shopping_popularity_requirement(
                requirement + " " + source_phrase
            )
            if raw_popularity != "NONE":
                requirement = re.sub(
                    r"网红|爆红|爆款|主流|大牌|知名|热门|流行|畅销|热卖|"
                    r"\b(?:viral|trending|mainstream|well-known|established|popular|"
                    r"best-selling|best seller)\b",
                    " ",
                    requirement,
                    flags=re.IGNORECASE,
                )
                requirement = re.sub(r"\s+", " ", requirement).strip(" -_.,")
                if requirement.casefold() in {"", "brand", "brands", "品牌", "牌子"}:
                    continue
        if (
            requirement
            and source_owned
            and requirement.casefold() not in {
                "brand", "brands", "category", "normalized category",
                "product category", "size", "feature", "quality",
            }
            and _shopping_requirement_is_grounded_in_plan(
                requirement,
                source_phrase or requirement,
                search_material,
            )
            and not _requirement_has_ungrounded_number(
                requirement,
                user_message,
                reference_context,
            )
            and requirement not in requirements
        ):
            requirements.append(requirement)
        if len(requirements) >= 8:
            break
    hard_popularity_requirements = {
        "CURRENTLY_TRENDING": "current cross-source brand trend evidence",
        "ESTABLISHED_BRAND": "established brand evidence",
        "PROVEN_DEMAND": "visible demand or review-count evidence",
    }
    hard_requirement = hard_popularity_requirements.get(popularity_requirement)
    if hard_requirement and hard_requirement not in requirements:
        requirements.append(hard_requirement)

    localized_constraints = raw.get("localized_constraints", [])
    if not isinstance(localized_constraints, list):
        localized_constraints = []
    clean_localized_constraints = []
    for item in localized_constraints[:10]:
        if not isinstance(item, dict):
            continue
        original = str(item.get("original", "")).strip()[:100]
        search_value = str(item.get("search_value", "")).strip()[:100]
        display_value = str(item.get("display_value", "")).strip()[:140]
        kind = str(item.get("kind", "")).strip().casefold()[:40]
        if (
            not original
            or not search_value
            or kind not in {
                "price", "currency", "capacity", "volume", "length",
                "size", "weight", "temperature", "duration", "unit",
            }
            or original.casefold() not in constraint_source_material
            or not _shopping_requirement_is_grounded_in_plan(
                search_value,
                original,
                search_material,
            )
        ):
            continue
        clean_localized_constraints.append(
            {
                "kind": kind,
                "original": original,
                "search_value": search_value,
                "display_value": display_value or original,
                "reason": str(item.get("reason", "")).strip()[:180],
            }
        )

    # Soft ranking preferences must also be owned by the current request. The
    # planner may not invent or copy an old premium/value profile.
    request_preferences = str(user_message or "").casefold()
    clean_profile = {
        "shopping_style": "unknown",
        "price_sensitivity": "unknown",
        "brand_strategy": "unknown",
        "reason": "",
    }
    if re.search(
        r"便宜|实惠|性价比|预算|低价|\b(?:cheap|cheaper|budget|affordable|value)\b",
        request_preferences,
    ):
        clean_profile.update(
            {
                "shopping_style": "value_first",
                "price_sensitivity": "high",
                "brand_strategy": "trusted_value",
                "reason": "explicit current-request value preference",
            }
        )
    elif re.search(
        r"高端|高级|品质优先|质量最好|\b(?:premium|luxury|quality-first|best quality)\b",
        request_preferences,
    ):
        clean_profile.update(
            {
                "shopping_style": "quality_first",
                "price_sensitivity": "low",
                "brand_strategy": "premium_reliable",
                "reason": "explicit current-request quality preference",
            }
        )
    if popularity_requirement in {"CURRENTLY_TRENDING", "ESTABLISHED_BRAND"}:
        clean_profile["brand_strategy"] = "established_only"
        if not clean_profile["reason"]:
            clean_profile["reason"] = "explicit current-request brand popularity"

    return {
        "planning_failed": planning_failed,
        "context_scope": context_scope,
        "merchant_scope": merchant_scope,
        "merchants": clean_merchants,
        "product_query": product_query,
        "queries": queries,
        "requirements": requirements,
        "localized_constraints": clean_localized_constraints,
        "popularity_requirement": popularity_requirement,
        "popularity_phrase": popularity_phrase,
        "selection_policy": "PROVEN_DEMAND_FIRST",
        "preference_profile": clean_profile,
    }


def shopping_research_controller(
    user_message,
    recent_context="",
    status_callback=None,
):
    """Return product cards; never render a merchant web page inside Bekki."""
    _status(status_callback, "正在整理购买条件… 🛍️")
    region = shopping_region.detect_shopping_region()
    print("[SHOPPING REGION]", json.dumps(region, ensure_ascii=False))
    shopping_plan = build_shopping_plan(user_message, recent_context, region)
    merchant_scope = shopping_plan["merchant_scope"]
    merchants = shopping_plan["merchants"]
    queries = shopping_plan["queries"]
    requirements = shopping_plan["requirements"]
    preference_profile = shopping_plan["preference_profile"]
    merchant_domains = [merchant["domain"] for merchant in merchants]
    print("[SHOPPING MERCHANT SCOPE]", merchant_scope)
    print("[SHOPPING MERCHANTS]", json.dumps(merchants, ensure_ascii=False))
    print("[SHOPPING QUERIES]", json.dumps(queries, ensure_ascii=False))

    if not merchant_domains:
        return {
            "status": "NO_MERCHANTS",
            "query": " | ".join(queries),
            "results": [],
            "cards": [],
            "context": (
                "The shopping-site selector did not return a valid merchant "
                "for the detected region. Do not show ordinary web pages as products."
            ),
        }

    site_scope = " OR ".join(
        _merchant_search_scope(domain)
        for domain in merchant_domains
    )
    queries = ["(" + site_scope + ") " + query for query in queries]
    print("[SHOPPING SCOPED QUERIES]", json.dumps(queries, ensure_ascii=False))

    _status(status_callback, "正在寻找符合条件的商品… 🔎")
    candidates = []
    seen_urls = set()
    errors = []

    for query in queries:
        if len(candidates) >= 15:
            break
        found = search(query, count=8)
        if not isinstance(found, list):
            errors.append(str(found))
            continue
        for item in found:
            url = str(item.get("url", "")).strip()
            domain = str(item.get("domain", "")).lower().strip()
            allowed = any(
                domain == merchant_domain
                or domain.endswith("." + merchant_domain)
                for merchant_domain in merchant_domains
            )
            if not allowed:
                continue
            if not _is_merchant_product_url(domain, url):
                print("[SHOPPING REJECTED NON-PRODUCT URL]", url)
                continue
            if not _has_specific_product_identity(
                item.get("title", ""),
                item.get("description", ""),
            ):
                print(
                    "[SHOPPING REJECTED COLLECTION PAGE]",
                    item.get("title", ""),
                    url,
                )
                continue
            if not url or url in seen_urls:
                continue
            seen_urls.add(url)
            candidates.append(item)
            if len(candidates) >= 15:
                break

    if not candidates:
        return {
            "status": "ERROR" if errors else "NO_RESULTS",
            "query": " | ".join(queries),
            "results": [],
            "cards": [],
            "context": (
                "No product candidates were found. "
                + ("; ".join(errors) if errors else "")
            ).strip(),
        }

    _status(status_callback, "正在评估购物网站… 🛡️")
    candidates = score_sources(user_message, candidates)

    _status(status_callback, "正在读取商品详情与销量证据… 📦")
    candidates = read_search_results(candidates[:8])
    candidates = [
        item for item in candidates
        if _has_readable_product_evidence(item)
    ]
    if not candidates:
        return {
            "status": "NO_VERIFIED_PRODUCTS",
            "query": " | ".join(queries),
            "results": [],
            "cards": [],
            "context": (
                "No product page supplied enough readable evidence for brand, "
                "price, popularity, and the user's requested specifications. "
                "Do not recommend or invent substitute products."
            ),
        }

    extraction_input = {
        "user_request": user_message,
        "requirements": requirements,
        "preference_profile": preference_profile,
        "region": region,
        "merchants": merchants,
        "candidates": [
            {
                "index": index,
                "title": BeautifulSoup(
                    str(item.get("title", "")), "html.parser"
                ).get_text(" ", strip=True)[:260],
                "description": BeautifulSoup(
                    str(item.get("description", "")), "html.parser"
                ).get_text(" ", strip=True)[:360],
                "domain": item.get("domain", ""),
                "source_score": item.get("source_score", 50),
                "page_content": str(item.get("page_content", ""))[:1800],
            }
            for index, item in enumerate(candidates[:8], start=1)
        ],
    }

    _status(status_callback, "正在比较商品条件… ✨")
    extracted = run_ai_prompt(
        "prompts/shopping_extract.txt",
        json.dumps(extraction_input, ensure_ascii=False, indent=2),
        expect_json=True,
        num_ctx=8192,
        num_predict=3200,
        think=False,
        model_name=MODEL_NAME,
    )

    extracted_items = extracted.get("items", []) if isinstance(extracted, dict) else []
    if not isinstance(extracted_items, list):
        extracted_items = []

    popularity_order = {
        "HIGH": 3,
        "MEDIUM": 2,
        "UNKNOWN": 1,
        "LOW": 0,
    }

    def extracted_priority(item):
        if not isinstance(item, dict):
            return (-1, -1, -1)
        popularity = item.get("popularity", {})
        if not isinstance(popularity, dict):
            popularity = {}
        popularity_rank = popularity_order.get(
            str(popularity.get("status", "UNKNOWN")).upper(), 1
        )
        rows = item.get("requirements", [])
        if not isinstance(rows, list):
            rows = []
        matches = sum(
            1 for row in rows
            if isinstance(row, dict)
            and str(row.get("status", "")).upper() == "MATCH"
        )
        brand_reliability = str(
            item.get("brand_reliability", "UNKNOWN")
        ).upper().strip()
        brand_rank = {"HIGH": 2, "MEDIUM": 1, "UNKNOWN": 0}.get(
            brand_reliability, 0
        )
        try:
            profile_fit = max(0, min(100, int(item.get("profile_fit", 0))))
        except (TypeError, ValueError):
            profile_fit = 0
        return (popularity_rank, profile_fit, brand_rank, matches)

    extracted_items.sort(key=extracted_priority, reverse=True)

    # A second compact AI selection path prevents a truncated rich comparison
    # from collapsing the entire shopping result to zero cards.
    if not extracted_items:
        compact_candidates = extraction_input["candidates"][:8]
        compact = run_ai_prompt(
            "prompts/shopping_select.txt",
            json.dumps(compact_candidates, ensure_ascii=False),
            expect_json=True,
            num_ctx=4096,
            num_predict=320,
            think=False,
            model_name="llama3.2:latest",
        )
        indexes = compact.get("indexes", []) if isinstance(compact, dict) else []
        if isinstance(indexes, list):
            extracted_items = [
                {
                    "index": value,
                    "page_type": "PRODUCT",
                    "merchant": "",
                    "price": "",
                    "requirements": [
                        {"label": requirement, "status": "UNKNOWN"}
                        for requirement in requirements
                    ],
                }
                for value in indexes[:3]
            ]

    cards = []
    selected_results = []
    used_indexes = set()

    for extracted_item in extracted_items:
        if not isinstance(extracted_item, dict):
            continue
        if str(extracted_item.get("page_type", "")).upper().strip() != "PRODUCT":
            continue
        try:
            candidate_index = int(extracted_item.get("index")) - 1
        except (TypeError, ValueError):
            continue
        if (
            candidate_index < 0
            or candidate_index >= len(candidates)
            or candidate_index in used_indexes
        ):
            continue

        candidate = candidates[candidate_index]

        if not _has_specific_product_identity(
            candidate.get("title", ""),
            candidate.get("description", ""),
        ):
            continue

        popularity = extracted_item.get("popularity", {})
        if not isinstance(popularity, dict):
            popularity = {}
        popularity_status = str(
            popularity.get("status", "UNKNOWN")
        ).upper().strip()
        if popularity_status not in popularity_order:
            popularity_status = "UNKNOWN"
        # Explicitly low-demand products are not shopping recommendations.
        if popularity_status == "LOW":
            continue

        used_indexes.add(candidate_index)
        selected_results.append(candidate)

        requirement_rows = extracted_item.get("requirements", [])
        if not isinstance(requirement_rows, list):
            requirement_rows = []
        safe_requirements = []
        for row in requirement_rows[:8]:
            if not isinstance(row, dict):
                continue
            label = str(row.get("label", "")).strip()[:100]
            status = str(row.get("status", "UNKNOWN")).upper().strip()
            if label and status in {"MATCH", "MISMATCH", "UNKNOWN"}:
                safe_requirements.append({"label": label, "status": status})

        if requirements:
            normalize_requirement = lambda value: re.sub(
                r"\s+", " ", str(value).strip().casefold()
            )
            requirement_statuses = {
                normalize_requirement(row["label"]): row["status"]
                for row in safe_requirements
            }
            expected_requirements = {
                normalize_requirement(requirement)
                for requirement in requirements
            }
            if any(
                requirement_statuses.get(requirement) != "MATCH"
                for requirement in expected_requirements
            ):
                continue

        clean_title = BeautifulSoup(
            str(candidate.get("title", "")), "html.parser"
        ).get_text(" ", strip=True)
        clean_summary = BeautifulSoup(
            str(candidate.get("description", "")), "html.parser"
        ).get_text(" ", strip=True)
        # A web-result thumbnail often represents the merchant brand instead
        # of the item (for example an Amazon logo). Product cards therefore
        # use a separate exact-title image lookup with relevance validation.
        image_url = search_product_image(clean_title) if len(cards) < 3 else ""
        visible_candidate_text = " ".join(
            (
                clean_title,
                clean_summary,
                str(candidate.get("page_content", "")),
            )
        ).lower()
        extracted_price = str(extracted_item.get("price", "")).strip()[:80]
        # Price is evidence, not decoration. Never display a value that the
        # selected search result did not actually contain.
        if extracted_price and extracted_price.lower() not in visible_candidate_text:
            extracted_price = ""

        extracted_brand = str(extracted_item.get("brand", "")).strip()[:80]
        if extracted_brand and extracted_brand.lower() not in visible_candidate_text:
            extracted_brand = ""

        brand_reliability = str(
            extracted_item.get("brand_reliability", "UNKNOWN")
        ).upper().strip()
        if not extracted_brand or brand_reliability not in {"HIGH", "MEDIUM"}:
            brand_reliability = "UNKNOWN"
        if not extracted_brand or brand_reliability == "UNKNOWN":
            continue
        try:
            profile_fit = max(
                0, min(100, int(extracted_item.get("profile_fit", 0)))
            )
        except (TypeError, ValueError):
            profile_fit = 0

        popularity_evidence = str(
            popularity.get("evidence", "")
        ).strip()[:180]
        if (
            popularity_evidence
            and popularity_evidence.lower() not in visible_candidate_text
        ):
            popularity_evidence = ""
            popularity_status = "UNKNOWN"

        if popularity_status not in {"HIGH", "MEDIUM"} or not popularity_evidence:
            continue

        cards.append(
            {
                "type": "product",
                "title": clean_title[:180],
                "summary": clean_summary[:500],
                "url": candidate.get("url", ""),
                "domain": candidate.get("domain", ""),
                "image": (
                    {
                        "url": image_url,
                        "alt": clean_title[:180],
                        "source_url": candidate.get("url", ""),
                    }
                    if image_url
                    else None
                ),
                "metadata": {
                    "merchant": str(extracted_item.get("merchant", ""))[:100],
                    "price": extracted_price,
                    "brand": extracted_brand,
                    "brand_reliability": brand_reliability,
                    "profile_fit": profile_fit,
                    "popularity_status": popularity_status,
                    "popularity_evidence": popularity_evidence,
                    "captured_at": datetime.now().astimezone().isoformat(),
                },
                "requirements": safe_requirements,
            }
        )
        if len(cards) >= 3:
            break

    cards = result_cards.clean_cards(cards)
    print("[SHOPPING CARDS]", len(cards))

    decision_options = []
    for index, card in enumerate(cards[:3], start=1):
        result = (
            selected_results[index - 1]
            if index - 1 < len(selected_results)
            else {}
        )
        decision_options.append(
            {
                "option_id": "option_" + str(index),
                "title": card.get("title", ""),
                "summary": card.get("summary", ""),
                "domain": card.get("domain", ""),
                "source_score": result.get("source_score", 50),
                "metadata": card.get("metadata", {}),
                "requirements": card.get("requirements", []),
            }
        )

    comparison = decision_comparison.compare_options(
        decision_options,
        requirements,
        lambda prompt_path, input_text: run_ai_prompt(
            prompt_path,
            input_text,
            expect_json=True,
            num_ctx=8192,
            num_predict=1400,
            think=False,
            model_name="llama3.2:latest",
        ),
        preference_profile=preference_profile,
    )
    comparison_context = decision_comparison.prompt_context(
        comparison,
        {
            option["option_id"]: option["title"]
            for option in decision_options
        },
    )
    print(
        "[DECISION COMPARISON]",
        json.dumps(comparison, ensure_ascii=False),
    )

    context = (
        "melchior response mode: SHOPPING_RESEARCH\n"
        "Bekki is presenting products as structured cards inside the app.\n"
        "Write only a short recommendation or comparison based on these cards.\n"
        "Do not output, repeat, or format any URL in the reply.\n"
        "Do not claim a requirement matches unless its card status is MATCH.\n"
        "UNKNOWN means the product page must be checked by the user.\n"
        "The explicit View product button owns external navigation.\n\n"
        "Product cards:\n"
        + json.dumps(cards, ensure_ascii=False, indent=2)
        + "\n\n"
        + comparison_context
    )

    return {
        "status": "OK" if cards else "NO_PRODUCT_CARDS",
        "query": " | ".join(queries),
        "queries": queries,
        "requirements": requirements,
        "preference_profile": preference_profile,
        "region": region,
        "merchants": merchants,
        "merchant_scope": merchant_scope,
        "results": selected_results,
        "cards": cards,
        "comparison": comparison,
        "context": context,
    }


def fact_lookup_controller(query, status_callback=None):
    """Look up one current fact without the incremental 3→5→7 loop."""
    _status(status_callback, "正在查找权威信息… 🔍")
    search_results = search(query, count=7)

    if not isinstance(search_results, list):
        return {
            "status": "ERROR",
            "query": query,
            "context": "Fact lookup failed: " + str(search_results),
        }

    if not search_results:
        return {
            "status": "NO_RESULTS",
            "query": query,
            "context": "No current result was found for: " + query,
        }

    _status(status_callback, "正在选择权威来源… 📚")
    candidates = score_sources(query, search_results)[:3]

    _status(status_callback, "正在读取结果… 📄")
    read_results = read_search_results(candidates)
    answers = extract_answers(query, read_results)

    context = (
        "melchior response mode: FACT_LOOKUP\n"
        "The user requested one current fact, not claim verification.\n"
        "Answer directly from the strongest available evidence. State uncertainty "
        "instead of inventing a value.\n\n"
        "Extracted answers:\n"
        + json.dumps(answers, ensure_ascii=False, indent=2)
        + "\n\nSources consulted:\n"
        + json.dumps(
            _source_summary(read_results),
            ensure_ascii=False,
            indent=2,
        )
    )

    return {
        "status": "OK",
        "query": query,
        "results": read_results,
        "answers": answers,
        "context": context,
    }


SOCIAL_PLATFORM_NAMES = {
    "bilibili": "哔哩哔哩 (Bilibili)",
    "youtube": "YouTube",
    "xiaohongshu": "小红书",
    "instagram": "Instagram",
    "reddit": "Reddit",
    "x": "X (formerly Twitter)",
}

# Small, explicit alias groups are allowed to bridge a user's named entity to
# the same identity as it appears in platform-native titles. These are not
# inferred from arbitrary page text. They are activated only when the current
# request/query already contains one member of the group.
SOCIAL_VERIFIED_ENTITY_ALIASES = (
    {
        "canonical": "Karina",
        "aliases": ("Karina", "柳智敏", "柚卡", "柚小卡", "纯柚"),
    },
)

# Keep the detail-introduction pass inside the existing 8K model context so a
# 16 GB GPU can leave practical headroom for a foreground game. Search-card
# text carries identity and metrics; opened-page text supplies a bounded
# excerpt for richer descriptions.
SOCIAL_INTRO_SEARCH_TEXT_CHARS = 500
SOCIAL_INTRO_DETAIL_TEXT_CHARS = 1300
SOCIAL_INTRO_USER_REQUEST_CHARS = 500
# Text-heavy Reddit posts share a two-post text-only pass; multimodal platforms
# remain isolated per post and never send more than two images in one request.
SOCIAL_INTRO_BATCH_SIZE = 2

_SOCIAL_QUERY_SCHEMA = {
    "type": "object",
    "properties": {
        "query": {"type": "string"},
        "selection_mode": {
            "type": "string",
            "enum": ["RECENT", "RELEVANCE"],
        },
        "recency_days": {
            "anyOf": [
                {"type": "integer", "minimum": 1, "maximum": 3650},
                {"type": "null"},
            ]
        },
        "ranking_mode": {
            "type": "string",
            "enum": ["DEFAULT", "DISCUSSION", "POPULARITY", "PRICE"],
        },
        "fallback_query": {
            "anyOf": [{"type": "string"}, {"type": "null"}]
        },
    },
    "required": ["query", "selection_mode", "recency_days"],
    "additionalProperties": False,
}

_SOCIAL_EVIDENCE_SCHEMA = {
    "type": "object",
    "properties": {
        "page_summary": {"type": "string"},
        "recent_post_count": {"type": "integer", "minimum": 0},
        "items": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "title": {"type": "string"},
                    "author": {
                        "anyOf": [{"type": "string"}, {"type": "null"}]
                    },
                    "time": {
                        "anyOf": [{"type": "string"}, {"type": "null"}]
                    },
                    "engagement": {
                        "anyOf": [{"type": "string"}, {"type": "null"}]
                    },
                    "relevance_score": {
                        "type": "integer", "minimum": 0, "maximum": 100
                    },
                    "relevance_reason": {"type": "string", "maxLength": 240},
                    "kind": {
                        "type": "string",
                        "enum": [
                            "discussion", "rumor", "repost", "opinion", "other"
                        ],
                    },
                },
                "required": [
                    "title", "author", "time", "engagement",
                    "relevance_score", "relevance_reason", "kind"
                ],
                "additionalProperties": False,
            },
            "maxItems": 12,
        },
        "excluded_count": {"type": "integer", "minimum": 0},
        "warnings": {"type": "array", "items": {"type": "string"}},
    },
    "required": [
        "page_summary", "recent_post_count", "items", "excluded_count", "warnings"
    ],
    "additionalProperties": False,
}

_SOCIAL_VISUAL_SCHEMA = {
    "type": "object",
    "properties": {
        "frames_analyzed": {"type": "integer", "minimum": 0, "maximum": 3},
        "visual_summary": {"type": "string"},
        "observations": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "post_title": {"type": "string"},
                    "description": {"type": "string", "maxLength": 320},
                    "relevance": {"type": "string", "maxLength": 220},
                    "visible_text": {
                        "type": "array",
                        "items": {"type": "string", "maxLength": 100},
                        "maxItems": 4,
                        "uniqueItems": True,
                    },
                    "confidence": {
                        "type": "string",
                        "enum": ["high", "medium", "low"],
                    },
                },
                "required": [
                    "post_title",
                    "description",
                    "relevance",
                    "visible_text",
                    "confidence",
                ],
                "additionalProperties": False,
            },
            "maxItems": 3,
        },
        "warnings": {"type": "array", "items": {"type": "string"}},
    },
    "required": [
        "frames_analyzed", "visual_summary", "observations", "warnings"
    ],
    "additionalProperties": False,
}

_SOCIAL_POST_DETAIL_SCHEMA = {
    "type": "object",
    "properties": {
        "items": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "post_title": {"type": "string"},
                    "primary_subject": {
                        "anyOf": [{"type": "string"}, {"type": "null"}]
                    },
                    "primary_subject_evidence": {
                        "anyOf": [{"type": "string"}, {"type": "null"}]
                    },
                    "content_summary": {"type": "string", "maxLength": 600},
                    "textual_findings": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "properties": {
                                "finding": {"type": "string", "maxLength": 260},
                                "evidence_quote": {"type": "string", "maxLength": 240},
                            },
                            "required": ["finding", "evidence_quote"],
                            "additionalProperties": False,
                        },
                        "maxItems": 4,
                    },
                    "image_summary": {"type": "string", "maxLength": 420},
                    "visual_findings": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "properties": {
                                "finding": {"type": "string", "maxLength": 240},
                                "visible_basis": {"type": "string", "maxLength": 180},
                                "confidence": {
                                    "type": "string",
                                    "enum": ["high", "medium", "low"],
                                },
                            },
                            "required": ["finding", "visible_basis", "confidence"],
                            "additionalProperties": False,
                        },
                        "maxItems": 4,
                    },
                    "price_observations": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "properties": {
                                "raw_amount": {"type": "string", "maxLength": 40},
                                "normalized_amount": {
                                    "anyOf": [
                                        {"type": "number", "minimum": 0},
                                        {"type": "null"},
                                    ]
                                },
                                "currency": {
                                    "anyOf": [{"type": "string"}, {"type": "null"}]
                                },
                                "price_type": {
                                    "type": "string",
                                    "enum": [
                                        "displayed", "asking", "sold",
                                        "per_person", "unknown"
                                    ],
                                },
                                "item_binding": {
                                    "anyOf": [{"type": "string"}, {"type": "null"}]
                                },
                                "evidence_basis": {"type": "string", "maxLength": 180},
                                "confidence": {
                                    "type": "string",
                                    "enum": ["high", "medium", "low"],
                                },
                            },
                            "required": [
                                "raw_amount", "normalized_amount", "currency",
                                "price_type", "item_binding", "evidence_basis",
                                "confidence"
                            ],
                            "additionalProperties": False,
                        },
                        "maxItems": 10,
                    },
                    "answer_relevance": {"type": "string", "maxLength": 320},
                    "scope_match": {
                        "type": "object",
                        "properties": {
                            "decision": {
                                "type": "string",
                                "enum": ["INCLUDE", "EXCLUDE", "UNCERTAIN"],
                            },
                            "entity_match": {
                                "type": "string",
                                "enum": [
                                    "EXACT", "COMPATIBLE_VARIANT",
                                    "NOT_APPLICABLE", "NONE", "UNKNOWN"
                                ],
                            },
                            "category_match": {
                                "type": "string",
                                "enum": [
                                    "EXACT", "COMPATIBLE_VARIANT",
                                    "NOT_APPLICABLE", "NONE", "UNKNOWN"
                                ],
                            },
                            "relation_match": {
                                "type": "string",
                                "enum": [
                                    "EXACT", "COMPATIBLE_VARIANT",
                                    "NOT_APPLICABLE", "NONE", "UNKNOWN"
                                ],
                            },
                            "evidence": {"type": "string", "maxLength": 240},
                            "reason": {"type": "string", "maxLength": 240},
                        },
                        "required": [
                            "decision", "entity_match", "category_match",
                            "relation_match", "evidence", "reason"
                        ],
                        "additionalProperties": False,
                    },
                    "uncertainty": {"type": "string", "maxLength": 320},
                },
                "required": [
                    "post_title", "primary_subject",
                    "primary_subject_evidence", "content_summary",
                    "textual_findings", "image_summary", "visual_findings",
                    "price_observations",
                    "answer_relevance", "scope_match", "uncertainty",
                ],
                "additionalProperties": False,
            },
            "maxItems": 2,
        }
    },
    "required": ["items"],
    "additionalProperties": False,
}

_SOCIAL_SYNTHESIS_SCHEMA = {
    "type": "object",
    "properties": {
        "answer": {"type": "string", "maxLength": 2200},
        "findings": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "post_title": {"type": "string"},
                    "finding": {"type": "string", "maxLength": 360},
                },
                "required": ["post_title", "finding"],
                "additionalProperties": False,
            },
            "maxItems": 7,
        },
        "limitations": {
            "type": "array",
            "items": {"type": "string", "maxLength": 300},
            "maxItems": 4,
        },
        "confidence": {
            "type": "string",
            "enum": ["high", "medium", "low"],
        },
    },
    "required": ["answer", "findings", "limitations", "confidence"],
    "additionalProperties": False,
}


def _social_query_matches_platform(query, platforms):
    query = str(query or "").strip()
    # The model owns platform-language adaptation while Python preserves the
    # bounded query as an opaque search term. Proper names and IDs remain
    # literal even when generic intent words are adapted for Reddit/X.
    return bool(query)


def _preserve_social_query_facets(user_message, query, platforms):
    """Keep problem/limitation intent when Reddit query text is compressed."""

    query = " ".join(str(query or "").split()).strip()[:160]
    if "reddit" not in platforms or not query:
        return query
    source = str(user_message or "").casefold()
    problem_requested = bool(re.search(
        r"问题|缺陷|局限|故障|痛点|困难|problems?|issues?|limitations?|failures?",
        source,
    ))
    facet_present = bool(re.search(
        r"\b(?:problems?|issues?|limitations?|failures?|challenges?)\b|"
        r"问题|缺陷|局限|故障|痛点|困难",
        query.casefold(),
    ))
    if not problem_requested or facet_present:
        return query
    community_match = re.search(
        r"(?<![A-Za-z0-9_])r/[A-Za-z0-9_]{2,32}", query,
        flags=re.IGNORECASE,
    )
    if community_match:
        prefix = query[:community_match.start()].rstrip()
        suffix = query[community_match.start():]
        return (prefix + " problems " + suffix).strip()[:160]
    return (query + " problems")[:160]


def _social_ranking_intent(user_message):
    text = str(user_message or "").casefold()
    price_request = bool(re.search(
        r"卡价|价格|价钱|售价|标价|均价|最贵|price|pricing|asking\s+price|cost",
        text,
    ))
    ranked_request = bool(re.search(
        r"\btop\s*\d+\b|前\s*\d+|排行|排名|最高|最贵|highest|most\s+expensive",
        text,
    ))
    if price_request and ranked_request:
        return "PRICE"
    if re.search(
        r"讨论最多|最多讨论|评论最多|最多评论|most\s+discussed|"
        r"most\s+comments?|highest\s+comment",
        text,
    ):
        return "DISCUSSION"
    if re.search(
        r"最热门|最火|互动最多|热度最高|most\s+popular|"
        r"highest\s+engagement|\btop\s+posts?\b",
        text,
    ):
        return "POPULARITY"
    return "DEFAULT"


def _social_narrative_language(user_message):
    """Return an explicit display-language contract for social AI output."""
    return (
        "Chinese"
        if re.search(r"[\u3400-\u9fff]", str(user_message or ""))
        else "the same language as the user request"
    )


def _verified_social_entity_aliases(*values):
    """Return only configured alias groups activated by the current request."""

    request_text = " ".join(str(value or "") for value in values).casefold()
    groups = []
    for group in SOCIAL_VERIFIED_ENTITY_ALIASES:
        aliases = [
            str(value or "").strip()
            for value in group.get("aliases", ())
            if str(value or "").strip()
        ]
        if not aliases or not any(alias.casefold() in request_text for alias in aliases):
            continue
        groups.append(
            {
                "canonical": str(group.get("canonical") or aliases[0]),
                "aliases": aliases,
            }
        )
    return groups


def _social_title_verified_alias(title, alias_groups):
    """Return the active alias visibly present in a post title, if any."""

    title_text = str(title or "").casefold()
    for group in alias_groups if isinstance(alias_groups, list) else []:
        for alias in group.get("aliases", []):
            if str(alias or "").casefold() in title_text:
                return str(alias)
    return ""


def build_social_query_plan(user_message, platforms):
    """Use one AI call to choose both social terms and result scope."""

    previous_plan = {}
    for attempt in (1, 2):
        packet = {
            "user_message": user_message,
            "platforms": platforms,
        }
        if attempt == 2:
            packet["recovery_instruction"] = (
                "The previous plan was empty or invalid. Create one concise "
                "platform-native search query. Preserve literal proper names "
                "and IDs, but adapt generic intent words to the language used "
                "by the selected platform. Choose "
                "RECENT only for an explicit user time/freshness request; "
                "otherwise choose RELEVANCE."
            )
            packet["previous_rejected_plan"] = previous_plan
            print("[SOCIAL QUERY RETRY]", platforms)
        raw_result = run_ai_prompt(
            "prompts/social_query.txt",
            json.dumps(packet, ensure_ascii=False),
            expect_json=True,
            num_ctx=2048,
            num_predict=180,
            think=False,
            model_name="gemma4:12b",
            json_schema=_SOCIAL_QUERY_SCHEMA,
        )
        if isinstance(raw_result, dict):
            query = _preserve_social_query_facets(
                user_message,
                str(raw_result.get("query", "")).strip()[:160],
                platforms,
            )
            selection_mode = str(
                raw_result.get("selection_mode") or "RELEVANCE"
            ).strip().upper()
            if selection_mode not in {"RECENT", "RELEVANCE"}:
                selection_mode = ""
            recency_days = raw_result.get("recency_days")
            deterministic_ranking = _social_ranking_intent(user_message)
            ranking_mode = (
                deterministic_ranking
                if deterministic_ranking != "DEFAULT"
                else str(raw_result.get("ranking_mode") or "DEFAULT").strip().upper()
            )
            if ranking_mode not in {
                "DEFAULT", "DISCUSSION", "POPULARITY", "PRICE"
            }:
                ranking_mode = "DEFAULT"
            fallback_query = _preserve_social_query_facets(
                user_message,
                str(raw_result.get("fallback_query") or "").strip()[:160],
                platforms,
            )
            if selection_mode == "RECENT":
                try:
                    recency_days = min(max(int(recency_days or 7), 1), 3650)
                except (TypeError, ValueError):
                    recency_days = 7
            else:
                recency_days = None
            previous_plan = {
                "query": query,
                "selection_mode": selection_mode,
                "recency_days": recency_days,
            }
            if ranking_mode != "DEFAULT":
                previous_plan["ranking_mode"] = ranking_mode
            if fallback_query and fallback_query.casefold() != query.casefold():
                previous_plan["fallback_query"] = fallback_query
            if _social_query_matches_platform(query, platforms):
                if selection_mode in {"RECENT", "RELEVANCE"}:
                    return previous_plan
    raise RuntimeError(
        "Reliable social-query AI did not produce a platform-native query plan."
    )


def build_social_query(user_message, platforms):
    """Compatibility wrapper returning only the AI-authored search query."""

    return build_social_query_plan(user_message, platforms)["query"]


def _resolve_social_post_date(value, current_date):
    text = str(value or "").strip().lower()
    if not text:
        return None
    if any(token in text for token in (
        "刚刚", "分钟前", "小时前", "今天", "just now", "minutes ago",
        "minute ago", "hours ago", "hour ago", "today",
    )):
        return current_date
    if "昨天" in text or text == "yesterday":
        return current_date - timedelta(days=1)
    if "前天" in text:
        return current_date - timedelta(days=2)
    match = re.search(r"(\d+)\s*天前", text)
    if not match:
        match = re.search(r"(\d+)\s*days?\s*ago", text)
    if match:
        return current_date - timedelta(days=int(match.group(1)))
    # Reddit commonly renders compact relative timestamps without the word
    # "ago" (for example 4d, 12h, 30m).
    match = re.search(r"(?<!\w)(\d+)\s*([dhm])(?!\w)", text)
    if match:
        amount = int(match.group(1))
        unit = match.group(2)
        if unit == "d":
            return current_date - timedelta(days=amount)
        return current_date
    match = re.search(
        r"(?<!\d)(\d{4})[-/.年](\d{1,2})[-/.月](\d{1,2})(?:日)?(?!\d)",
        text,
    )
    if match:
        try:
            return datetime(
                int(match.group(1)), int(match.group(2)), int(match.group(3))
            ).date()
        except ValueError:
            return None
    month_names = {
        "jan": 1, "january": 1, "feb": 2, "february": 2,
        "mar": 3, "march": 3, "apr": 4, "april": 4, "may": 5,
        "jun": 6, "june": 6, "jul": 7, "july": 7,
        "aug": 8, "august": 8, "sep": 9, "september": 9,
        "oct": 10, "october": 10, "nov": 11, "november": 11,
        "dec": 12, "december": 12,
    }
    month_match = re.search(
        r"(?<![a-z])(" + "|".join(month_names) + r")\s+"
        r"(\d{1,2})(?:,?\s+(\d{4}))?(?!\d)",
        text,
    )
    if month_match:
        month = month_names[month_match.group(1)]
        day = int(month_match.group(2))
        years = (
            (int(month_match.group(3)),)
            if month_match.group(3)
            else (current_date.year, current_date.year - 1)
        )
        for year in years:
            try:
                candidate = datetime(year, month, day).date()
            except ValueError:
                return None
            if month_match.group(3) or candidate <= current_date:
                return candidate
        return None
    match = re.search(
        r"(?<!\d)(\d{1,2})(?:[-/.月])(\d{1,2})(?:日)?(?!\d)",
        text,
    )
    if not match:
        return None
    month, day = int(match.group(1)), int(match.group(2))
    for year in (current_date.year, current_date.year - 1):
        try:
            candidate = datetime(year, month, day).date()
        except ValueError:
            return None
        if candidate <= current_date:
            return candidate
    return None


def _requested_youtube_handles(*values):
    """Return explicit YouTube @handles from the current request/query."""

    handles = []
    seen = set()
    for value in values:
        for match in re.findall(
            r"(?<![A-Za-z0-9._-])@([A-Za-z0-9][A-Za-z0-9._-]{1,29})",
            str(value or ""),
            flags=re.IGNORECASE,
        ):
            normalized = "@" + match.casefold()
            if normalized in seen:
                continue
            seen.add(normalized)
            handles.append(normalized)
    return handles


def filter_youtube_channel_scope(recent_items, post_details, requested_handles):
    """Keep @handle requests bound to the opened video's actual channel."""

    requested = {
        ("@" + str(value or "").strip().lstrip("@")).casefold()
        for value in requested_handles if str(value or "").strip()
    }
    if not requested:
        return recent_items, post_details, [], 0
    details_by_title = {
        str(item.get("post_title") or "").strip().casefold(): item
        for item in post_details if isinstance(item, dict)
        and str(item.get("post_title") or "").strip()
    }
    kept_items = []
    kept_titles = set()
    warnings = []
    dropped = 0
    requested_display = ", ".join(sorted(requested))
    for raw_item in recent_items if isinstance(recent_items, list) else []:
        if not isinstance(raw_item, dict):
            continue
        item = dict(raw_item)
        title = str(item.get("title") or "").strip()
        title_key = title.casefold()
        detail = details_by_title.get(title_key, {})
        actual = str(
            detail.get("youtube_channel_handle") or ""
        ).strip().casefold()
        if actual and not actual.startswith("@"):
            actual = "@" + actual
        evidence_level = str(detail.get("evidence_level") or "").strip()
        if not actual and evidence_level.startswith("opened"):
            try:
                source_path = urlparse(
                    str(detail.get("source_url") or "")
                ).path.rstrip("/")
            except ValueError:
                source_path = ""
            source_match = re.fullmatch(
                r"/@([A-Za-z0-9][A-Za-z0-9._-]{1,29})/"
                r"(?:shorts|videos|streams)",
                source_path,
                flags=re.IGNORECASE,
            )
            source_handle = (
                "@" + source_match.group(1).casefold()
                if source_match else ""
            )
            # A video opened from an exact channel-owned tab inherits that
            # tab's handle boundary when the player DOM omits its handle. A
            # general /results page never receives this fallback.
            if source_handle in requested:
                actual = source_handle
        if actual not in requested:
            dropped += 1
            warnings.append(
                "《" + title + "》的实际频道账号为 "
                + (actual or "不可验证") + "，与用户指定的 "
                + requested_display + " 不一致，已排除。"
            )
            continue
        actual_author = str(detail.get("youtube_author") or "").strip()[:160]
        item["author"] = actual_author or actual
        item["author_source"] = (
            "opened_youtube_video" if actual_author
            else "youtube_channel_tab"
        )
        item["youtube_channel_handle"] = actual
        kept_items.append(item)
        kept_titles.add(title_key)
    kept_details = [
        item for item in post_details if isinstance(item, dict)
        and str(item.get("post_title") or "").strip().casefold() in kept_titles
    ]
    if dropped:
        print(
            "[SOCIAL YOUTUBE CHANNEL FILTER]",
            "requested=" + requested_display,
            "excluded=" + str(dropped),
        )
    return kept_items, kept_details, warnings[:6], dropped


def reconcile_social_detail_dates(
    recent_items,
    post_details,
    selection_mode="RECENT",
    recency_days=7,
    current_date=None,
):
    """Make an opened note's visible date authoritative over search inference."""

    if current_date is None:
        current_day = datetime.now().date()
    elif hasattr(current_date, "year") and not isinstance(current_date, str):
        current_day = current_date
    else:
        current_day = datetime.strptime(str(current_date), "%Y-%m-%d").date()
    selection_mode = str(selection_mode or "RECENT").strip().upper()
    try:
        recency_days = min(max(int(recency_days or 7), 1), 3650)
    except (TypeError, ValueError):
        recency_days = 7
    earliest = current_day - timedelta(days=recency_days - 1)
    details_by_title = {
        str(item.get("post_title") or "").strip().casefold(): item
        for item in post_details if isinstance(item, dict)
        and str(item.get("post_title") or "").strip()
    }
    kept_items = []
    kept_titles = set()
    warnings = []
    dropped = 0
    for raw_item in recent_items if isinstance(recent_items, list) else []:
        if not isinstance(raw_item, dict):
            continue
        item = dict(raw_item)
        title_key = str(item.get("title") or "").strip().casefold()
        detail = details_by_title.get(title_key, {})
        visible_time = str(detail.get("visible_time_text") or "").strip()[:80]
        if visible_time:
            resolved = _resolve_social_post_date(visible_time, current_day)
            previous = str(item.get("resolved_date") or "").strip()
            if resolved is None:
                if selection_mode == "RECENT":
                    dropped += 1
                    warnings.append(
                        "《" + str(item.get("title") or "")
                        + "》详情可见日期无法可靠解析，已从近期结果排除。"
                    )
                    continue
            else:
                corrected = resolved.isoformat()
                item["time"] = visible_time
                item["resolved_date"] = corrected
                item["date_verification_required"] = False
                item["date_source"] = (
                    "opened_post"
                    if str(detail.get("evidence_level") or "").startswith("opened")
                    else "search_card_visible"
                )
                detail["resolved_date"] = corrected
                if previous and previous != corrected:
                    item["date_conflict_corrected"] = True
                    warnings.append(
                        "《" + str(item.get("title") or "") + "》以帖子可见日期 "
                        + visible_time + " 覆盖搜索页推算日期 " + previous + "。"
                    )
                if (
                    selection_mode == "RECENT"
                    and not earliest <= resolved <= current_day
                ):
                    dropped += 1
                    warnings.append(
                        "《" + str(item.get("title") or "") + "》帖子可见日期为 "
                        + corrected + "，不在最近 " + str(recency_days)
                        + " 天内，已排除。"
                    )
                    continue
        elif (
            selection_mode == "RECENT"
            and (
                item.get("date_verification_required")
                or not str(item.get("resolved_date") or "").strip()
            )
        ):
            dropped += 1
            warnings.append(
                "《" + str(item.get("title") or "")
                + "》未能从打开的详情页读取发布日期，无法验证近期范围，"
                "已排除。"
            )
            continue
        youtube_author = str(detail.get("youtube_author") or "").strip()[:160]
        if youtube_author:
            item["author"] = youtube_author
            item["author_source"] = "opened_youtube_video"
        kept_items.append(item)
        kept_titles.add(title_key)
    kept_details = [
        item for item in post_details if isinstance(item, dict)
        and str(item.get("post_title") or "").strip().casefold() in kept_titles
    ]
    if dropped:
        print("[SOCIAL DETAIL DATE FILTER]", "excluded=" + str(dropped))
    return kept_items, kept_details, warnings[:6], dropped


def _nonnegative_int(value):
    try:
        return max(int(value or 0), 0)
    except (TypeError, ValueError):
        return 0

def extract_social_evidence(
    page_text,
    recency_days=7,
    current_date=None,
    selection_mode="RECENT",
    user_message="",
    query="",
    ranking_mode="DEFAULT",
    platforms=None,
):
    """Filter visible social evidence by AI-selected time or relevance scope."""

    if current_date is None:
        current_day = datetime.now().date()
    elif hasattr(current_date, "year") and not isinstance(current_date, str):
        current_day = current_date
    else:
        current_day = datetime.strptime(
            str(current_date), "%Y-%m-%d"
        ).date()
    selection_mode = str(selection_mode or "RECENT").strip().upper()
    if selection_mode not in {"RECENT", "RELEVANCE"}:
        selection_mode = "RECENT"
    if selection_mode == "RECENT":
        recency_days = min(max(int(recency_days or 7), 1), 3650)
    else:
        recency_days = None
    ranking_mode = str(ranking_mode or "DEFAULT").strip().upper()
    if ranking_mode not in {"DEFAULT", "DISCUSSION", "POPULARITY", "PRICE"}:
        ranking_mode = "DEFAULT"
    platforms = [
        str(value or "").strip().lower()
        for value in (platforms if isinstance(platforms, list) else [])
        if str(value or "").strip()
    ]
    defer_youtube_detail_date = (
        selection_mode == "RECENT" and "youtube" in platforms
    )
    verified_aliases = _verified_social_entity_aliases(user_message, query)

    input_text = (
        "Current date: " + current_day.isoformat()
        + "\nPlatforms: " + json.dumps(platforms, ensure_ascii=False)
        + "\nSelection mode: " + selection_mode
        + "\nRequested recency window: "
        + (str(recency_days) + " days" if recency_days else "none")
        + "\nUser request: " + str(user_message or "")[:1000]
        + "\nSearch query: " + str(query or "")[:240]
        + "\nVerified entity aliases for this request: "
        + json.dumps(verified_aliases, ensure_ascii=False)
        + (
            "\nYouTube date policy: `New` is a badge, not a publication "
            "timestamp. When a relevant YouTube card has no visible date, "
            "return time as null and keep it as a provisional candidate; "
            "the caller will open the video and verify its publication date. "
            "Never infer an author from the query, title, hashtag, or @mention."
            if "youtube" in platforms else ""
        )
        + "\n\nVisible social-page text:\n"
        + page_text[:18000]
    )

    evidence = run_ai_prompt(
        "prompts/social_extract.txt",
        input_text,
        expect_json=True,
        num_ctx=8192,
        num_predict=1400,
        think=False,
        model_name="gemma4:12b",
        json_schema=_SOCIAL_EVIDENCE_SCHEMA,
    )

    if not isinstance(evidence, dict):
        return {
            "page_summary": "",
            "recent_post_count": 0,
            "selected_post_count": 0,
            "items": [],
            "excluded_count": 0,
            "selection_mode": selection_mode,
            "recency_days": recency_days,
            "warnings": [
                "页面内容无法被可靠地结构化提取。",
            ],
        }

    raw_items = evidence.get("items", [])
    if not isinstance(raw_items, list):
        raw_items = []
    earliest = (
        current_day - timedelta(days=recency_days - 1)
        if selection_mode == "RECENT" else None
    )
    items = []
    seen = set()
    dropped = 0
    deferred_dates = 0
    for source_order, raw_item in enumerate(raw_items):
        if not isinstance(raw_item, dict):
            dropped += 1
            continue
        title = str(raw_item.get("title") or "").strip()[:300]
        resolved = _resolve_social_post_date(
            raw_item.get("time"), current_day
        )
        if not title:
            dropped += 1
            continue
        date_verification_required = bool(
            selection_mode == "RECENT"
            and resolved is None
            and defer_youtube_detail_date
        )
        if (
            selection_mode == "RECENT"
            and (
                (resolved is None and not date_verification_required)
                or (
                    resolved is not None
                    and not earliest <= resolved <= current_day
                )
            )
        ):
            dropped += 1
            continue
        if date_verification_required:
            deferred_dates += 1
        author = str(raw_item.get("author") or "").strip()[:160] or None
        identity = (title.casefold(), str(author or "").casefold())
        if identity in seen:
            dropped += 1
            continue
        seen.add(identity)
        relevance_score = min(
            max(_nonnegative_int(raw_item.get("relevance_score", 50)), 0),
            100,
        )
        relevance_reason = str(
            raw_item.get("relevance_reason") or ""
        ).strip()[:240]
        matched_alias = _social_title_verified_alias(title, verified_aliases)
        if matched_alias:
            relevance_score = max(relevance_score, 90)
            canonical = str(verified_aliases[0].get("canonical") or "").strip()
            relevance_reason = (
                "标题中的“" + matched_alias + "”是当前请求实体"
                + (" “" + canonical + "”" if canonical else "")
                + "的已验证别名。"
            )[:240]
        items.append(
            {
                "title": title,
                "author": author,
                "time": str(raw_item.get("time") or "").strip()[:80] or None,
                "resolved_date": resolved.isoformat() if resolved else None,
                "date_verification_required": date_verification_required,
                "engagement": (
                    str(raw_item.get("engagement") or "").strip()[:80] or None
                ),
                "relevance_score": relevance_score,
                "relevance_reason": relevance_reason,
                "kind": str(raw_item.get("kind") or "other").lower().strip()
                if str(raw_item.get("kind") or "other").lower().strip()
                in {"discussion", "rumor", "repost", "opinion", "other"}
                else "other",
                "_source_order": source_order,
            }
        )
        if len(items) >= 12:
            break

    warnings = evidence.get("warnings", [])
    if not isinstance(warnings, list):
        warnings = []
    warnings = [str(item)[:240] for item in warnings if str(item).strip()]
    if dropped:
        if selection_mode == "RECENT":
            warnings.append(
                "已按可解析日期排除 " + str(dropped)
                + " 条过期、无日期、无效或重复内容。"
            )
        else:
            warnings.append(
                "已排除 " + str(dropped) + " 条无效或重复内容；"
                "旧帖和无日期帖子不会仅因时间被排除。"
            )
    if deferred_dates:
        warnings.append(
            "有 " + str(deferred_dates)
            + " 条 YouTube 候选在搜索卡片中没有可解析日期；"
            "仅在打开视频并验证发布日期后才会保留。"
        )
    page_summary = str(evidence.get("page_summary", ""))[:700]
    if not items:
        if selection_mode == "RECENT":
            page_summary = (
                "最近 " + str(recency_days)
                + " 天内没有可通过可见日期验证的社媒帖子。"
            )
        else:
            page_summary = "没有找到与问题关联度足够且内容可可靠读取的社媒帖子。"
    if selection_mode == "RELEVANCE":
        items.sort(
            key=lambda item: (
                -item["relevance_score"],
                _parse_social_metric(item.get("engagement")) is None,
                -(_parse_social_metric(item.get("engagement")) or 0),
                item["_source_order"],
            )
        )
    elif ranking_mode == "PRICE":
        # Search-grid interaction is not a price signal. In a recent price
        # request, prioritize semantic identity/relevance until opened-post
        # price observations can perform the real price ordering.
        items.sort(
            key=lambda item: (
                -item["relevance_score"],
                item["_source_order"],
            )
        )
    else:
        # Within an explicitly requested recent window, the visible interaction
        # number remains the secondary presentation order used by v1.3.9.5.
        items.sort(
            key=lambda item: (
                _parse_social_metric(item.get("engagement")) is None,
                -(_parse_social_metric(item.get("engagement")) or 0),
                item["_source_order"],
            )
        )
    for item in items:
        item.pop("_source_order", None)
    filtered = {
        "page_summary": page_summary,
        "recent_post_count": len(items),
        "selected_post_count": len(items),
        "items": items[:7],
        "excluded_count": _nonnegative_int(
            evidence.get("excluded_count")
        ) + dropped,
        "selection_mode": selection_mode,
        "recency_days": recency_days,
        "warnings": warnings[:5],
    }
    print(
        "[SOCIAL EVIDENCE]",
        json.dumps(filtered, ensure_ascii=False, indent=2),
    )
    return filtered


def extract_social_visual_evidence(
    visual_frames,
    user_message,
    recent_items,
    platforms,
):
    frames = [
        str(frame)
        for frame in visual_frames
        if isinstance(frame, str) and frame.strip()
    ][:3]
    allowed_titles = [
        str(item.get("title") or "").strip()
        for item in recent_items
        if isinstance(item, dict) and str(item.get("title") or "").strip()
    ]
    empty = {
        "frames_analyzed": 0,
        "visual_summary": "",
        "observations": [],
        "warnings": [],
    }
    if not frames:
        empty["warnings"] = ["社媒页面没有可读取的图片画面。"]
        return empty
    if not allowed_titles:
        empty["warnings"] = [
            "没有通过时间验证的近期帖子，因此图片未纳入近期证据。"
        ]
        return empty
    packet = {
        "current_user_request": str(user_message)[:800],
        "required_narrative_language": _social_narrative_language(user_message),
        "platforms": platforms,
        "verified_recent_post_titles": allowed_titles,
        "instruction": (
            "Analyze only images visibly attached to one of the supplied "
            "verified recent post titles."
        ),
    }
    try:
        raw = run_ai_prompt(
            "prompts/social_visual_extract.txt",
            json.dumps(packet, ensure_ascii=False),
            expect_json=True,
            num_ctx=4096,
            num_predict=1400,
            think=False,
            model_name="gemma4:12b",
            json_schema=_SOCIAL_VISUAL_SCHEMA,
            images=frames,
        )
    except Exception as error:
        print(
            "[SOCIAL VISUAL EVIDENCE SKIPPED]",
            type(error).__name__,
            repr(error),
        )
        empty["warnings"] = [
            "搜索页图片理解暂时不可用；已继续读取帖子、截图和文字证据。"
        ]
        return empty
    if not isinstance(raw, dict):
        empty["warnings"] = ["社媒图片无法被可靠地结构化理解。"]
        return empty
    title_map = {title.casefold(): title for title in allowed_titles}
    observations = []
    rejected_observations = 0
    for item in raw.get("observations", []):
        if not isinstance(item, dict):
            rejected_observations += 1
            continue
        title = str(item.get("post_title") or "").strip()
        canonical_title = title_map.get(title.casefold())
        description = str(item.get("description") or "").strip()[:500]
        if not canonical_title or not description:
            rejected_observations += 1
            continue
        visible_text = item.get("visible_text", [])
        if not isinstance(visible_text, list):
            visible_text = []
        confidence = str(item.get("confidence") or "low").lower().strip()
        if confidence not in {"high", "medium", "low"}:
            confidence = "low"
        observations.append(
            {
                "post_title": canonical_title,
                "description": description,
                "relevance": str(item.get("relevance") or "").strip()[:360],
                "visible_text": [
                    str(text)[:180] for text in visible_text[:6]
                    if str(text).strip()
                ],
                "confidence": confidence,
            }
        )
    warnings = raw.get("warnings", [])
    if not isinstance(warnings, list):
        warnings = []
    result = {
        "frames_analyzed": len(frames),
        "visual_summary": (
            "从 " + str(len(frames)) + " 个可见页面画面中提取了 "
            + str(len(observations)) + " 条与近期帖子可靠对应的图片观察。"
            if observations else ""
        ),
        "observations": observations[:6],
        "warnings": [
            str(item)[:240] for item in warnings[:4] if str(item).strip()
        ],
    }
    if not observations:
        result["warnings"].append(
            "图片未能与通过时间验证的近期帖子可靠对应。"
        )
    elif rejected_observations:
        result["warnings"].append(
            "已排除 " + str(rejected_observations)
            + " 条无法与近期帖子标题可靠对应的图片描述。"
        )
    print(
        "[SOCIAL VISUAL EVIDENCE]",
        json.dumps(result, ensure_ascii=False, indent=2),
    )
    return result


def _social_match_text(value):
    return re.sub(r"[^0-9a-z\u3400-\u9fff]+", "", str(value or "").casefold())


_SOCIAL_SCOPE_MATCH_VALUES = {
    "EXACT", "COMPATIBLE_VARIANT", "NOT_APPLICABLE", "NONE", "UNKNOWN"
}


def _normalize_social_scope_match(value, answer_relevance=""):
    """Normalize the model's hard relevance verdict, with legacy fail-safes."""

    negative_text = str(answer_relevance or "").casefold()
    explicit_negative = bool(re.search(
        r"(?:与.{0,40}(?:无关|不相关|没有直接关联)|"
        r"不包含任何关于|无法提供关于用户要求|"
        r"\bunrelated\b|\bnot\s+relevant\b|does\s+not\s+relate)",
        negative_text,
    ))
    if not isinstance(value, dict):
        # Old fixtures/build integrations predate the structured scope gate.
        # They remain compatible, while an explicit textual "unrelated"
        # verdict can no longer leak into cards.
        return {
            "decision": "EXCLUDE" if explicit_negative else "INCLUDE",
            "entity_match": "NONE" if explicit_negative else "NOT_APPLICABLE",
            "category_match": "NONE" if explicit_negative else "NOT_APPLICABLE",
            "relation_match": "NONE" if explicit_negative else "NOT_APPLICABLE",
            "evidence": "",
            "reason": str(answer_relevance or "")[:240],
            "legacy_inferred": True,
        }
    decision = str(value.get("decision") or "UNCERTAIN").strip().upper()
    if decision not in {"INCLUDE", "EXCLUDE", "UNCERTAIN"}:
        decision = "UNCERTAIN"
    dimensions = {}
    for field in ("entity_match", "category_match", "relation_match"):
        status = str(value.get(field) or "UNKNOWN").strip().upper()
        dimensions[field] = (
            status if status in _SOCIAL_SCOPE_MATCH_VALUES else "UNKNOWN"
        )
    if explicit_negative:
        decision = "EXCLUDE"
    if decision == "INCLUDE" and any(
        status in {"NONE", "UNKNOWN"} for status in dimensions.values()
    ):
        decision = "EXCLUDE"
    return {
        "decision": decision,
        **dimensions,
        "evidence": _collapse_repeated_social_tokens(
            value.get("evidence"), 240
        ),
        "reason": _collapse_repeated_social_tokens(value.get("reason"), 240),
        "legacy_inferred": False,
    }


def filter_social_scope_matches(
    recent_items,
    post_details,
    introductions,
):
    """Drop semantically adjacent recommendations before synthesis/cards."""

    intro_by_title = {
        str(item.get("post_title") or "").strip().casefold(): item
        for item in introductions if isinstance(item, dict)
    }
    detail_titles = {
        str(item.get("post_title") or "").strip().casefold()
        for item in post_details if isinstance(item, dict)
        and str(item.get("post_title") or "").strip()
    }
    kept_items = []
    kept_titles = set()
    removed = []
    for item in recent_items if isinstance(recent_items, list) else []:
        if not isinstance(item, dict):
            continue
        title = str(item.get("title") or "").strip()
        title_key = title.casefold()
        intro = intro_by_title.get(title_key)
        scope = _normalize_social_scope_match(
            intro.get("scope_match") if isinstance(intro, dict) else None,
            (
                intro.get("answer_relevance")
                or intro.get("suitability_note")
                or ""
            ) if isinstance(intro, dict) else "",
        ) if isinstance(intro, dict) else None
        # Production introductions always carry scope_match. If the model
        # failed to understand a result, keep only an already high-confidence
        # exact search extraction; otherwise fail closed rather than display a
        # recommendation-shelf neighbour.
        if not isinstance(scope, dict):
            if title_key not in detail_titles:
                kept_items.append(item)
                kept_titles.add(title_key)
                continue
            positive_reason = bool(re.search(
                r"明确|直接|高度|完全匹配|\bexact(?:ly)?\b|"
                r"\bdirect(?:ly)?\b|\bhighly\s+relevant\b",
                str(item.get("relevance_reason") or "").casefold(),
            ))
            if (
                _nonnegative_int(item.get("relevance_score")) < 90
                and not positive_reason
            ):
                removed.append(title)
                continue
        elif str(scope.get("decision") or "").upper() != "INCLUDE":
            removed.append(title)
            continue
        kept_items.append(item)
        kept_titles.add(title_key)
    kept_details = [
        item for item in post_details if isinstance(item, dict)
        and str(item.get("post_title") or "").strip().casefold() in kept_titles
    ]
    kept_introductions = [
        item for item in introductions if isinstance(item, dict)
        and str(item.get("post_title") or "").strip().casefold() in kept_titles
    ]
    if removed:
        print(
            "[SOCIAL HARD RELEVANCE FILTER]",
            "excluded=" + str(len(removed)),
            json.dumps(removed[:7], ensure_ascii=False),
        )
    return kept_items, kept_details, kept_introductions, removed


def _social_visual_metric_evidence(metric, value, proof, has_frame):
    """Accept a screenshot metric only with an explicit icon/label binding."""

    if not has_frame or _parse_social_metric(value) is None:
        return False
    value_key = _social_match_text(value)
    proof_text = str(proof or "").strip().casefold()
    proof_key = _social_match_text(proof_text)
    if not value_key or value_key not in proof_key:
        return False
    markers = {
        "likes": ("点赞", "like", "heart", "心形"),
        "comments": ("评论", "comment", "bubble", "气泡"),
        "shares": ("分享", "转发", "share", "arrow", "箭头"),
    }
    if metric == "shares" and any(
        marker in proof_text
        for marker in ("收藏", "collect", "bookmark", "star", "星形")
    ):
        return False
    return any(marker in proof_text for marker in markers.get(metric, ()))


def match_social_post_candidates(recent_items, candidates):
    """Bind DOM post links to AI-extracted items using the exact visible title."""

    matched = []
    used_urls = set()
    for item in recent_items if isinstance(recent_items, list) else []:
        if not isinstance(item, dict):
            continue
        title = str(item.get("title") or "").strip()
        title_key = _social_match_text(title)
        if not title_key:
            continue
        for candidate in candidates if isinstance(candidates, list) else []:
            if not isinstance(candidate, dict):
                continue
            url = str(candidate.get("url") or "").strip()
            visible_key = _social_match_text(candidate.get("visible_text"))
            if not url or url in used_urls or title_key not in visible_key:
                continue
            matched.append({**candidate, "post_title": title})
            used_urls.add(url)
            break
        if len(matched) >= 7:
            break
    return matched


def _requested_reddit_communities(*values):
    communities = []
    for value in values:
        communities.extend(
            re.findall(
                r"(?<![A-Za-z0-9_])r/([A-Za-z0-9_]{2,32})",
                str(value or ""),
                flags=re.IGNORECASE,
            )
        )
    return {value.casefold() for value in communities}


def _reddit_post_community(value):
    try:
        path = urlparse(str(value or "")).path
    except ValueError:
        return ""
    match = re.search(
        r"(?:^|/)r/([A-Za-z0-9_]{2,32})/comments/",
        path,
        flags=re.IGNORECASE,
    )
    return match.group(1).casefold() if match else ""


def _within_reddit_community_scope(item, communities):
    if not communities or not isinstance(item, dict):
        return True
    if str(item.get("platform") or "").strip().lower() != "reddit":
        return True
    return _reddit_post_community(item.get("url")) in communities


_REPEATED_SOCIAL_TOKEN = re.compile(
    r"(?P<open>[\"“‘']?)(?P<token>[\w\u3400-\u9fff][\w\u3400-\u9fff.·_-]{0,23})"
    r"(?P<close>[\"”’']?)"
    r"(?:(?:\s*[,，、;；]\s*)[\"“‘']?(?P=token)[\"”’']?){2,}",
    flags=re.IGNORECASE,
)


def _collapse_repeated_social_tokens(value, limit):
    """Collapse OCR/model runaways such as ``杰妮、杰妮、杰妮...``."""

    text = " ".join(str(value or "").split()).strip()

    def replace(match):
        return (
            str(match.group("open") or "")
            + str(match.group("token") or "")
            + str(match.group("close") or "")
            + "（重复项已省略）"
        )

    for _ in range(3):
        collapsed = _REPEATED_SOCIAL_TOKEN.sub(replace, text)
        if collapsed == text:
            break
        text = collapsed
    return text[: max(int(limit or 0), 0)]


def _compact_social_introduction_text(value, limit):
    """Normalize whitespace and enforce one prompt-only character budget."""

    return _collapse_repeated_social_tokens(value, limit)


def _normalize_social_price_amount(value):
    text = str(value or "").strip().casefold().replace(",", "")
    match = re.search(r"(?<!\d)(\d+(?:\.\d+)?)\s*([kmw万千]?)(?!\d)", text)
    if not match:
        return None
    number = float(match.group(1))
    multiplier = {
        "": 1,
        "k": 1000,
        "千": 1000,
        "w": 10000,
        "万": 10000,
        "m": 1000000,
    }.get(match.group(2), 1)
    result = number * multiplier
    return int(result) if result.is_integer() else round(result, 2)


def _explicit_social_price_currency(*values):
    text = " ".join(str(value or "") for value in values).casefold()
    if re.search(r"(?:\busd\b|美元|美金|\d\s*刀|\$\s*\d)", text):
        return "USD"
    if re.search(r"(?:\bmyr\b|\brm\s*\d|马币)", text):
        return "MYR"
    if re.search(r"(?:\bcny\b|\brmb\b|人民币|\d\s*元)", text):
        return "CNY"
    if re.search(r"(?:\bkrw\b|韩元|₩\s*\d)", text):
        return "KRW"
    if re.search(r"(?:\beur\b|欧元|€\s*\d)", text):
        return "EUR"
    if re.search(r"(?:\bgbp\b|英镑|£\s*\d)", text):
        return "GBP"
    return None


def _price_observations_from_text(value):
    text = " ".join(str(value or "").split()).strip()
    if not text:
        return []
    patterns = (
        r"\$\s*\d+(?:\.\d+)?\s*[kmw万千]?",
        r"(?:USD|RMB|CNY|MYR|RM|EUR|GBP|KRW)\s*\d+(?:\.\d+)?\s*[kmw万千]?",
        r"\d+(?:\.\d+)?\s*[kmw万千]?\s*(?:美元|美金|刀|元|马币|韩元|欧元|英镑|🍞|👝)",
    )
    raw_values = []
    for pattern in patterns:
        raw_values.extend(
            match.group(0).strip()
            for match in re.finditer(pattern, text, flags=re.IGNORECASE)
        )
    # Marketplace shorthand often omits a currency entirely: ``330💼出`` or
    # ``卡价 250`` still communicates an asking/displayed number. Keep this
    # deliberately contextual so dates, likes and comment counts do not turn
    # into prices merely because they are numeric.
    contextual_patterns = (
        r"(?<![\d.])(\d+(?:\.\d+)?\s*[kmw万千]?)\s*(?=💼|🍞|👝|出(?:售)?|/\s*张|一张|each\b)",
        r"(?:卡价|均价|售价|标价|价格|price|asking\s+price)\s*[:：]?\s*"
        r"(\d+(?:\.\d+)?\s*[kmw万千]?)",
        r"(?:^|[，,；;\s])均\s*[:：]?\s*"
        r"(\d+(?:\.\d+)?\s*[kmw万千]?)(?:\s*/\s*(?:1|张))?",
    )
    for pattern in contextual_patterns:
        raw_values.extend(
            match.group(1).strip()
            for match in re.finditer(pattern, text, flags=re.IGNORECASE)
        )
    observations = []
    seen = set()
    for raw in raw_values:
        key = raw.casefold().replace(" ", "")
        if key in seen:
            continue
        seen.add(key)
        raw_position = text.casefold().find(raw.casefold())
        nearby = text[
            max(raw_position - 18, 0): raw_position + len(raw) + 18
        ] if raw_position >= 0 else text[:40]
        if re.search(r"(?:已售|sold\b|成交)", nearby, flags=re.IGNORECASE):
            price_type = "sold"
        elif re.search(
            r"(?:出(?:售)?|卖|asking|offer|💼|🍞|👝)",
            nearby,
            flags=re.IGNORECASE,
        ):
            price_type = "asking"
        elif "人均" in nearby:
            price_type = "per_person"
        else:
            price_type = "displayed"
        observations.append(
            {
                "raw_amount": raw,
                "normalized_amount": _normalize_social_price_amount(raw),
                "currency": _explicit_social_price_currency(raw),
                "price_type": price_type,
                "item_binding": None,
                "evidence_basis": nearby.strip() or raw,
                "confidence": "high",
                "_origin": "text_parser",
            }
        )
    return observations[:10]


def _clean_social_price_observations(
    items,
    source_text,
    has_images,
    excluded_metric_values=None,
):
    candidates = [
        {**item, "_origin": "model"}
        for item in items[:10]
        if isinstance(item, dict)
    ] if isinstance(items, list) else []
    candidates.extend(_price_observations_from_text(source_text))
    source_key = _social_match_text(source_text)
    excluded_metrics = {
        parsed
        for parsed in (
            _parse_social_metric(value)
            for value in (excluded_metric_values or [])
        )
        if parsed is not None
    }
    cleaned = []
    seen = set()
    valid_types = {"displayed", "asking", "sold", "per_person", "unknown"}
    for item in candidates:
        if not isinstance(item, dict):
            continue
        raw = str(item.get("raw_amount") or "").strip()[:40]
        basis = str(item.get("evidence_basis") or "").strip()[:180]
        normalized = _normalize_social_price_amount(raw)
        if not raw or normalized is None:
            continue
        raw_key = _social_match_text(raw)
        basis_key = _social_match_text(basis)
        if not raw_key:
            continue
        text_grounded = raw_key in source_key
        visual_grounded = bool(has_images and basis_key and raw_key in basis_key)
        if not text_grounded and not visual_grounded:
            continue
        currency = _explicit_social_price_currency(raw, basis)
        if normalized in excluded_metrics and currency is None:
            # A search-grid interaction number can sit directly beside the
            # next duplicated title (for example ``8 出Karina小卡``), or near a
            # title containing ``卡价``. Accept the collision only when the
            # original captured text visibly binds that exact amount to an
            # unambiguous price marker. A model-authored evidence_basis alone
            # cannot override a known engagement value.
            escaped_raw = re.escape(raw).replace(r"\ ", r"\s*")
            grounded_price_binding = bool(
                re.search(
                    (
                        r"(?:卡价|均价|售价|标价|价格|price|asking(?:\s+price)?)"
                        r"\s*[:：]?\s*" + escaped_raw
                        + r"|" + escaped_raw
                        + r"\s*(?:💼|🍞|👝|/\s*张|一张|each\b)"
                    ),
                    str(source_text or ""),
                    flags=re.IGNORECASE,
                )
            )
            if not grounded_price_binding:
                continue
        price_type = str(item.get("price_type") or "unknown").strip().lower()
        if price_type not in valid_types:
            price_type = "unknown"
        binding = str(item.get("item_binding") or "").strip()[:160] or None
        confidence = str(item.get("confidence") or "low").strip().lower()
        if confidence not in {"high", "medium", "low"}:
            confidence = "low"
        key = (raw_key, _social_match_text(binding), price_type)
        if key in seen:
            continue
        seen.add(key)
        cleaned.append(
            {
                "raw_amount": raw,
                "normalized_amount": normalized,
                "currency": currency,
                "currency_unknown": currency is None,
                "price_type": price_type,
                "item_binding": binding,
                "evidence_basis": basis or raw,
                "confidence": confidence,
            }
        )
        if len(cleaned) >= 10:
            break
    return cleaned


def extract_social_post_introductions(
    user_message,
    recent_items,
    post_details,
    visual_evidence,
):
    """Create grounded introductions from opened post text and bounded vision."""

    if not post_details:
        return []
    detail_by_title = {
        str(item.get("post_title") or "").strip().casefold(): item
        for item in post_details[:7] if isinstance(item, dict)
    }
    recent_by_title = {
        str(item.get("title") or "").strip().casefold(): item
        for item in recent_items[:7] if isinstance(item, dict)
    }
    introductions = []
    seen_introduction_titles = set()
    details = [item for item in post_details[:7] if isinstance(item, dict)]
    batches = []
    index = 0
    while index < len(details):
        current = details[index]
        if str(current.get("platform") or "").strip() == "reddit":
            batch = [current]
            if (
                index + 1 < len(details)
                and str(details[index + 1].get("platform") or "").strip()
                == "reddit"
            ):
                batch.append(details[index + 1])
            batches.append(batch)
            index += len(batch)
        else:
            batches.append([current])
            index += 1
    for batch in batches:
        batch_titles = {
            str(item.get("post_title") or "").strip().casefold()
            for item in batch
        }
        batch_images = []
        compact_details = []
        for item in batch:
            detail_frames = []
            raw_frames = item.get("visual_frames", [])
            if (
                isinstance(raw_frames, list)
                and str(item.get("platform") or "").strip() != "reddit"
            ):
                detail_frames.extend(raw_frames)
            if str(item.get("platform") or "").strip() != "reddit":
                detail_frames.append(item.get("visual_frame"))
            visual_image_numbers = []
            for raw_frame in detail_frames:
                visual_frame = str(raw_frame or "").strip()
                if not visual_frame or visual_frame in batch_images:
                    continue
                batch_images.append(visual_frame)
                visual_image_numbers.append(len(batch_images))
                if len(visual_image_numbers) >= 2:
                    break
            compact_details.append(
                {
                    "post_title": item.get("post_title", ""),
                    "evidence_level": str(
                        item.get("evidence_level") or "opened_multimodal"
                    ),
                    # Keep the singular field for old tests and prompt packet
                    # readers.  v1.10.37 can additionally bind a main-content
                    # crop and a wider page frame to this same post.
                    "visual_image_number": (
                        visual_image_numbers[0] if visual_image_numbers else None
                    ),
                    "visual_image_numbers": visual_image_numbers,
                    "visual_asset_labels": [
                        str(asset.get("label") or "")[:40]
                        for asset in item.get("visual_assets", [])[:2]
                        if isinstance(asset, dict)
                    ],
                    "search_visible_text": _compact_social_introduction_text(
                        item.get("search_visible_text"),
                        SOCIAL_INTRO_SEARCH_TEXT_CHARS,
                    ),
                    "visible_text": _compact_social_introduction_text(
                        item.get("visible_text"),
                        SOCIAL_INTRO_DETAIL_TEXT_CHARS,
                    ),
                }
            )
        packet = {
            "user_request": str(user_message)[:SOCIAL_INTRO_USER_REQUEST_CHARS],
            "verified_entity_aliases": _verified_social_entity_aliases(
                user_message
            ),
            "required_narrative_language": _social_narrative_language(
                user_message
            ),
            "verified_recent_items": [
                item for key, item in recent_by_title.items()
                if key in batch_titles
            ],
            "opened_post_details": compact_details,
            "visual_evidence": {
                "observations": [
                    item for item in visual_evidence.get("observations", [])
                    if isinstance(item, dict)
                    and str(item.get("post_title") or "").strip().casefold()
                    in batch_titles
                ]
            },
        }
        packet_text = json.dumps(packet, ensure_ascii=False)
        print(
            "[SOCIAL INTRO PROMPT BATCH]",
            "posts=" + str(len(batch)),
            "chars=" + str(len(packet_text)),
            "images=" + str(len(batch_images)),
            "num_ctx=8192",
        )
        price_response_mode = _social_ranking_intent(user_message) == "PRICE"
        introduction_schema = _SOCIAL_POST_DETAIL_SCHEMA
        if price_response_mode:
            # Keep the ten useful price slots while bounding the narrative
            # fields. This prevents an image-heavy card grid from spending the
            # entire response budget before closing its JSON object.
            introduction_schema = json.loads(
                json.dumps(_SOCIAL_POST_DETAIL_SCHEMA)
            )
            item_properties = introduction_schema["properties"]["items"][
                "items"
            ]["properties"]
            item_properties["content_summary"]["maxLength"] = 280
            item_properties["textual_findings"]["maxItems"] = 1
            item_properties["image_summary"]["maxLength"] = 280
            item_properties["visual_findings"]["maxItems"] = 2
            item_properties["answer_relevance"]["maxLength"] = 180
            item_properties["uncertainty"]["maxLength"] = 180
        try:
            introduction_num_predict = (
                1500
                if price_response_mode
                else 1200
            )
            raw = run_ai_prompt(
                "prompts/social_post_introduction.txt",
                packet_text,
                expect_json=True,
                num_ctx=8192,
                num_predict=introduction_num_predict,
                think=False,
                model_name="gemma4:12b",
                json_schema=introduction_schema,
                images=batch_images or None,
            )
        except Exception as error:
            print(
                "[SOCIAL INTRO BATCH SKIPPED]",
                "posts=" + str(len(batch)),
                type(error).__name__,
                repr(error),
            )
            # Vision output can occasionally end in malformed JSON. Preserve
            # the post's textual understanding with one bounded text-only
            # retry; a second failure still falls back to deterministic search
            # evidence without affecting another post.
            if not batch_images:
                continue
            retry_packet = json.loads(packet_text)
            for retry_detail in retry_packet.get("opened_post_details", []):
                retry_detail["visual_image_number"] = None
                retry_detail["visual_image_numbers"] = []
            try:
                print(
                    "[SOCIAL UNDERSTANDING RETRY]",
                    "posts=" + str(len(batch)),
                    "mode=text_only",
                )
                raw = run_ai_prompt(
                    "prompts/social_post_introduction.txt",
                    json.dumps(retry_packet, ensure_ascii=False),
                    expect_json=True,
                    num_ctx=8192,
                    num_predict=1000,
                    think=False,
                    model_name="gemma4:12b",
                    json_schema=introduction_schema,
                )
                # The retry has no visual evidence. Do not accept image claims
                # merely because the original detail had screenshots.
                for detail in batch:
                    detail = dict(detail)
                    detail["visual_frame"] = ""
                    detail["visual_frames"] = []
                    detail_by_title[
                        str(detail.get("post_title") or "").strip().casefold()
                    ] = detail
            except Exception as retry_error:
                print(
                    "[SOCIAL UNDERSTANDING RETRY FAILED]",
                    type(retry_error).__name__,
                    repr(retry_error),
                )
                continue
        if not isinstance(raw, dict):
            continue
        # Xiaohongshu may expose three original images plus one body capture.
        # Analyze the remaining pair in a second isolated pass so no model
        # request ever carries more than two images on the 16 GB GPU.
        if (
            len(batch) == 1
            and str(batch[0].get("platform") or "").strip() == "xiaohongshu"
        ):
            all_frames = [
                str(value or "").strip()
                for value in batch[0].get("visual_frames", [])
                if str(value or "").strip()
            ] if isinstance(batch[0].get("visual_frames"), list) else []
            extra_images = all_frames[2:4]
            if extra_images:
                extra_packet = json.loads(packet_text)
                extra_detail = extra_packet["opened_post_details"][0]
                extra_detail["visual_image_number"] = 1
                extra_detail["visual_image_numbers"] = list(
                    range(1, len(extra_images) + 1)
                )
                extra_detail["visual_asset_labels"] = [
                    str(asset.get("label") or "")[:40]
                    for asset in batch[0].get("visual_assets", [])[2:4]
                    if isinstance(asset, dict)
                ]
                extra_packet["visual_pass"] = (
                    "remaining post images/body capture; merge with the first pass"
                )
                try:
                    print(
                        "[SOCIAL INTRO VISUAL CONTINUATION]",
                        "posts=1",
                        "images=" + str(len(extra_images)),
                        "num_ctx=8192",
                    )
                    extra_raw = run_ai_prompt(
                        "prompts/social_post_introduction.txt",
                        json.dumps(extra_packet, ensure_ascii=False),
                        expect_json=True,
                        num_ctx=8192,
                        num_predict=900,
                        think=False,
                        model_name="gemma4:12b",
                        json_schema=introduction_schema,
                        images=extra_images,
                    )
                except Exception as error:
                    print(
                        "[SOCIAL INTRO VISUAL CONTINUATION SKIPPED]",
                        type(error).__name__, repr(error),
                    )
                    extra_raw = {}
                base_items = {
                    str(value.get("post_title") or "").strip().casefold(): value
                    for value in raw.get("items", []) if isinstance(value, dict)
                }
                for extra_item in (
                    extra_raw.get("items", [])
                    if isinstance(extra_raw, dict) else []
                ):
                    if not isinstance(extra_item, dict):
                        continue
                    base_item = base_items.get(
                        str(extra_item.get("post_title") or "").strip().casefold()
                    )
                    if not base_item:
                        continue
                    for field in (
                        "textual_findings", "visual_findings", "price_observations"
                    ):
                        existing = base_item.get(field, [])
                        incoming = extra_item.get(field, [])
                        if isinstance(existing, list) and isinstance(incoming, list):
                            base_item[field] = existing + incoming
                    extra_summary = str(extra_item.get("image_summary") or "").strip()
                    if extra_summary:
                        base_item["image_summary"] = " ".join(
                            value for value in (
                                str(base_item.get("image_summary") or "").strip(),
                                extra_summary,
                            ) if value
                        )[:420]
        for item in raw.get("items", []):
            if not isinstance(item, dict):
                continue
            title = str(item.get("post_title") or "").strip()
            title_key = title.casefold()
            if title_key not in batch_titles or title_key in seen_introduction_titles:
                continue
            detail = detail_by_title.get(title.casefold())
            if not detail:
                continue
            source_text = "\n".join(
                (
                    str(detail.get("search_visible_text") or ""),
                    str(detail.get("visible_text") or ""),
                )
            )
            source_key = _social_match_text(source_text)
            raw_textual_findings = item.get("textual_findings", [])
            if not isinstance(raw_textual_findings, list):
                raw_textual_findings = []
            legacy_quotes = item.get("evidence_quotes", [])
            if not isinstance(legacy_quotes, list):
                legacy_quotes = []
            if not raw_textual_findings:
                legacy_summary = str(
                    item.get("content_summary")
                    or item.get("introduction")
                    or ""
                ).strip()
                raw_textual_findings = [
                    {
                        "finding": legacy_summary or str(quote or ""),
                        "evidence_quote": quote,
                    }
                    for quote in legacy_quotes[:4]
                ]
            textual_findings = []
            quotes = []
            for raw_finding in raw_textual_findings[:4]:
                if not isinstance(raw_finding, dict):
                    continue
                finding = _collapse_repeated_social_tokens(
                    raw_finding.get("finding"), 260
                )
                quote = str(
                    raw_finding.get("evidence_quote") or ""
                ).strip()[:240]
                quote = str(quote or "").strip()[:240]
                quote_key = _social_match_text(quote)
                if finding and quote_key and quote_key in source_key:
                    textual_findings.append(
                        {"finding": finding, "evidence_quote": quote}
                    )
                    quotes.append(quote)
            introduction = _collapse_repeated_social_tokens(
                item.get("content_summary")
                or item.get("introduction")
                or "",
                600,
            )
            if introduction and not quotes:
                introduction = ""
            name = str(
                item.get("primary_subject")
                or item.get("restaurant_name")
                or ""
            ).strip()[:160]
            name_evidence = str(
                item.get("primary_subject_evidence")
                or item.get("restaurant_name_evidence")
                or ""
            ).strip()[:240]
            if (
                not name
                or not name_evidence
                or _social_match_text(name_evidence) not in source_key
                or _social_match_text(name) not in _social_match_text(name_evidence)
            ):
                name = ""
                name_evidence = ""
            has_detail_images = bool(
                detail.get("visual_frames") or detail.get("visual_frame")
            )
            raw_visual_findings = item.get("visual_findings", [])
            if not isinstance(raw_visual_findings, list):
                raw_visual_findings = []
            visual_findings = []
            if has_detail_images:
                for raw_finding in raw_visual_findings[:4]:
                    if not isinstance(raw_finding, dict):
                        continue
                    finding = _collapse_repeated_social_tokens(
                        raw_finding.get("finding"), 240
                    )
                    basis = _collapse_repeated_social_tokens(
                        raw_finding.get("visible_basis"), 180
                    )
                    confidence = str(
                        raw_finding.get("confidence") or "low"
                    ).strip().lower()
                    if confidence not in {"high", "medium", "low"}:
                        confidence = "low"
                    if finding and basis:
                        visual_findings.append(
                            {
                                "finding": finding,
                                "visible_basis": basis,
                                "confidence": confidence,
                            }
                        )
            image_summary = _collapse_repeated_social_tokens(
                item.get("image_summary")
                or item.get("visual_description")
                or "",
                420,
            ) if has_detail_images else ""
            answer_relevance = _collapse_repeated_social_tokens(
                item.get("answer_relevance")
                or item.get("suitability_note")
                or "",
                320,
            )
            scope_match = _normalize_social_scope_match(
                item.get("scope_match"), answer_relevance
            )
            recent = recent_by_title.get(title_key, {})
            price_observations = _clean_social_price_observations(
                item.get("price_observations", []),
                source_text,
                has_detail_images,
                excluded_metric_values=(recent.get("engagement"),),
            )

            # Legacy model fixtures may still contain labeled metrics.  Keep
            # the old validator for compatibility, but the v1.10.37 prompt no
            # longer asks the model to read them. Search-grid interaction is
            # handled deterministically elsewhere.
            raw_metrics = item.get("engagement", {})
            raw_metric_evidence = item.get("engagement_evidence", {})
            metrics = {}
            metric_evidence = {}
            for metric in ("likes", "comments", "shares"):
                raw_value = (
                    raw_metrics.get(metric) if isinstance(raw_metrics, dict) else None
                )
                raw_proof = (
                    raw_metric_evidence.get(metric)
                    if isinstance(raw_metric_evidence, dict) else None
                )
                value = str(raw_value).strip()[:80] if raw_value is not None else ""
                proof = str(raw_proof).strip()[:180] if raw_proof is not None else ""
                value_key = _social_match_text(value)
                proof_key = _social_match_text(proof)
                if (
                    value_key and proof_key
                    and value_key in proof_key
                    and proof_key in source_key
                ) or _social_visual_metric_evidence(
                    metric,
                    value,
                    proof,
                    bool(detail.get("visual_frame")),
                ):
                    metrics[metric] = value
                    metric_evidence[metric] = proof
                else:
                    metrics[metric] = None
                    metric_evidence[metric] = None
            legacy_restaurant_name = str(
                item.get("restaurant_name") or ""
            ).strip()[:160]
            if legacy_restaurant_name != name:
                legacy_restaurant_name = ""
            introductions.append(
                {
                    "post_title": title,
                    "primary_subject": name or None,
                    "primary_subject_evidence": name_evidence or None,
                    "content_summary": introduction,
                    "textual_findings": textual_findings,
                    "image_summary": image_summary,
                    "visual_findings": visual_findings,
                    "price_observations": price_observations,
                    "answer_relevance": answer_relevance,
                    "scope_match": scope_match,
                    "evidence_level": str(
                        detail.get("evidence_level") or (
                            "opened_multimodal" if has_detail_images else "opened_text"
                        )
                    ),
                    # Compatibility aliases for existing UI and tests.
                    "restaurant_name": legacy_restaurant_name or None,
                    "restaurant_name_evidence": (
                        name_evidence if legacy_restaurant_name else None
                    ),
                    "introduction": introduction,
                    "visual_description": image_summary,
                    "evidence_quotes": quotes[:5],
                    "visible_features": [
                        value["finding"] for value in textual_findings[:3]
                    ] + [
                        value["finding"] for value in visual_findings[:2]
                    ],
                    "suitability_note": answer_relevance,
                    "uncertainty": _collapse_repeated_social_tokens(
                        item.get("uncertainty"), 320
                    ),
                    "engagement": metrics,
                    "engagement_evidence": metric_evidence,
                }
            )
            seen_introduction_titles.add(title_key)
    return introductions


def _parse_social_metric(value):
    """Parse a visible social count without assigning an absent metric label."""
    text = str(value or "").strip().lower().replace(",", "")
    match = re.search(r"(\d+(?:\.\d+)?)\s*([kmw万千]?)", text)
    if not match:
        return None
    number = float(match.group(1))
    multiplier = {
        "": 1,
        "k": 1000,
        "千": 1000,
        "w": 10000,
        "万": 10000,
        "m": 1000000,
    }.get(match.group(2), 1)
    return max(int(round(number * multiplier)), 0)


def _labeled_social_metrics(value):
    text = str(value or "").strip()
    patterns = {
        "likes": (
            r"(\d+(?:\.\d+)?\s*[kmw万千]?)\s*(?:votes?|upvotes?|likes?|点赞|赞)",
        ),
        "comments": (
            r"(\d+(?:\.\d+)?\s*[kmw万千]?)\s*(?:comments?|replies|评论|回复)",
        ),
        "shares": (
            r"(\d+(?:\.\d+)?\s*[kmw万千]?)\s*(?:shares?|reposts?|转发|分享)",
        ),
    }
    output = {}
    for field, field_patterns in patterns.items():
        output[field] = None
        for pattern in field_patterns:
            match = re.search(pattern, text, flags=re.IGNORECASE)
            if match:
                output[field] = match.group(1).strip()
                break
    return output


def _social_metrics_for_post(recent, intro, ranking_mode="DEFAULT"):
    ranking_mode = str(ranking_mode or "DEFAULT").strip().upper()
    displays = {}
    values = {}
    raw_metrics = intro.get("engagement", {}) if isinstance(intro, dict) else {}
    generic_display = str(recent.get("engagement") or "").strip()[:80]
    labeled_from_search = _labeled_social_metrics(generic_display)
    for metric in ("likes", "comments", "shares"):
        raw_display = (
            raw_metrics.get(metric) if isinstance(raw_metrics, dict) else None
        )
        display = (
            str(raw_display).strip()[:80] if raw_display is not None else ""
        )
        if not display and labeled_from_search.get(metric):
            display = labeled_from_search[metric]
        parsed = _parse_social_metric(display)
        displays[metric] = display or None
        values[metric] = parsed
    generic_value = (
        None
        if any(labeled_from_search.values())
        else _parse_social_metric(generic_display)
    )
    # The search grid's single visible interaction number is the primary social
    # ranking signal. It is never renamed to likes/comments/shares. Explicitly
    # labeled detail-page metrics remain available as facts and as a fallback
    # only when the search grid has no usable number.
    labeled_total = sum(value for value in values.values() if value is not None)
    labeled_count = sum(value is not None for value in values.values())
    if ranking_mode == "DISCUSSION":
        rank_score = values.get("comments")
        if rank_score is None:
            rank_score = generic_value
    elif ranking_mode == "PRICE":
        price_values = []
        for observation in (
            intro.get("price_observations", [])
            if isinstance(intro, dict) else []
        ):
            if not isinstance(observation, dict):
                continue
            try:
                price_values.append(float(observation.get("normalized_amount")))
            except (TypeError, ValueError):
                continue
        rank_score = max(price_values) if price_values else None
    elif ranking_mode == "POPULARITY":
        rank_score = (
            generic_value
            if generic_value is not None
            else values.get("likes")
            if values.get("likes") is not None
            else labeled_total if labeled_count else None
        )
    else:
        rank_score = (
            generic_value
            if generic_value is not None
            else labeled_total if labeled_count else None
        )
    return {
        "display": displays,
        "numeric": values,
        "search_visible_interaction": (
            generic_display if generic_value is not None else None
        ),
        "rank_score": rank_score,
        "known_metric_count": labeled_count + (generic_value is not None),
    }


def build_social_post_summaries(
    recent_items,
    introductions,
    selection_mode="RECENT",
    ranking_mode="DEFAULT",
):
    """Create five-to-seven compact post summaries for the final response."""
    selection_mode = str(selection_mode or "RECENT").strip().upper()
    intro_by_title = {
        str(item.get("post_title") or "").strip().casefold(): item
        for item in introductions if isinstance(item, dict)
    }
    summaries = []
    for source_order, item in enumerate(
        recent_items[:7] if isinstance(recent_items, list) else []
    ):
        if not isinstance(item, dict):
            continue
        title = str(item.get("title") or "").strip()
        if not title:
            continue
        intro = intro_by_title.get(title.casefold(), {})
        intro_scope = _normalize_social_scope_match(
            intro.get("scope_match"),
            intro.get("answer_relevance") or intro.get("suitability_note"),
        )
        if intro and intro_scope["decision"] != "INCLUDE":
            continue
        description = str(intro.get("introduction") or "").strip()[:360]
        visual_description = str(
            intro.get("visual_description") or ""
        ).strip()[:240]
        if visual_description:
            description = (
                (description + " ") if description else ""
            ) + "图片可见：" + visual_description
        if not description:
            description = str(
                item.get("relevance_reason") or ""
            ).strip()[:360]
        if not description:
            description = "已读取该帖的标题和页面信息；额外正文摘要暂不可用。"
        price_observations = [
            value for value in intro.get("price_observations", [])[:10]
            if isinstance(value, dict)
        ]
        if (
            str(ranking_mode or "DEFAULT").strip().upper() == "PRICE"
            and not price_observations
        ):
            price_observations = _clean_social_price_observations(
                [],
                title,
                False,
                excluded_metric_values=(item.get("engagement"),),
            )
        metric_intro = dict(intro)
        metric_intro["price_observations"] = price_observations
        metrics = _social_metrics_for_post(item, metric_intro, ranking_mode)
        summaries.append(
            {
                "post_title": title,
                "description": description,
                "primary_subject": intro.get("primary_subject"),
                "textual_findings": [
                    value for value in intro.get("textual_findings", [])[:4]
                    if isinstance(value, dict)
                ],
                "visual_findings": [
                    value for value in intro.get("visual_findings", [])[:4]
                    if isinstance(value, dict)
                ],
                "price_observations": price_observations,
                "answer_relevance": str(
                    intro.get("answer_relevance") or ""
                ).strip()[:320],
                "scope_match": intro.get("scope_match"),
                "uncertainty": str(
                    intro.get("uncertainty") or ""
                ).strip()[:320],
                "understanding_available": bool(
                    intro.get("content_summary")
                    or intro.get("textual_findings")
                    or intro.get("image_summary")
                    or intro.get("visual_findings")
                    or price_observations
                ),
                "evidence_level": str(
                    intro.get("evidence_level") or "search_only"
                ),
                "author": item.get("author"),
                "published_at": item.get("resolved_date"),
                "likes": metrics["display"]["likes"],
                "comments": metrics["display"]["comments"],
                "shares": metrics["display"]["shares"],
                "search_visible_interaction": metrics[
                    "search_visible_interaction"
                ],
                "relevance_score": min(
                    max(_nonnegative_int(item.get("relevance_score")), 0), 100
                ),
                "relevance_reason": str(
                    item.get("relevance_reason") or ""
                ).strip()[:240],
                "_rank_score": metrics["rank_score"],
                "_source_order": source_order,
            }
        )
    if selection_mode == "RELEVANCE" and str(
        ranking_mode or "DEFAULT"
    ).strip().upper() == "DEFAULT":
        summaries.sort(
            key=lambda item: (
                -item["relevance_score"],
                item["_rank_score"] is None,
                -(item["_rank_score"] or 0),
                item["_source_order"],
            )
        )
    else:
        summaries.sort(
            key=lambda item: (
                item["_rank_score"] is None,
                -(item["_rank_score"] or 0),
                item["_source_order"],
            )
        )
    for item in summaries:
        item.pop("_rank_score", None)
        item.pop("_source_order", None)
    print("[SOCIAL POST SUMMARIES]", len(summaries))
    return summaries


def synthesize_social_research_reply(
    user_message,
    query,
    evidence,
    summaries,
    platforms,
    selection_mode,
    ranking_mode="DEFAULT",
    cards=None,
):
    """Answer the exact request by comparing only grounded post findings."""

    summaries = summaries if isinstance(summaries, list) else []
    ranking_mode_value = str(ranking_mode or "DEFAULT").strip().upper()
    if ranking_mode_value != "PRICE" and not any(
        isinstance(item, dict) and item.get("understanding_available")
        for item in summaries
    ):
        return ""
    valid_titles = {
        str(item.get("post_title") or "").strip().casefold(): str(
            item.get("post_title") or ""
        ).strip()
        for item in summaries if isinstance(item, dict)
        and str(item.get("post_title") or "").strip()
    }
    compact_posts = []
    for item in summaries[:7]:
        if not isinstance(item, dict):
            continue
        compact_posts.append(
            {
                "post_title": str(item.get("post_title") or "")[:300],
                "author": item.get("author"),
                "published_at": item.get("published_at"),
                "search_visible_interaction": item.get(
                    "search_visible_interaction"
                ),
                "likes": item.get("likes"),
                "comments": item.get("comments"),
                "shares": item.get("shares"),
                "relevance_score": item.get("relevance_score"),
                "evidence_level": (
                    str(item.get("evidence_level") or "search_only")
                ),
                "primary_subject": item.get("primary_subject"),
                "content_summary": str(item.get("description") or "")[:500],
                "textual_findings": [
                    {
                        "finding": str(value.get("finding") or "")[:260],
                        "evidence_quote": str(
                            value.get("evidence_quote") or ""
                        )[:240],
                    }
                    for value in item.get("textual_findings", [])[:4]
                    if isinstance(value, dict)
                ],
                "visual_findings": [
                    {
                        "finding": str(value.get("finding") or "")[:240],
                        "visible_basis": str(
                            value.get("visible_basis") or ""
                        )[:180],
                        "confidence": value.get("confidence"),
                    }
                    for value in item.get("visual_findings", [])[:4]
                    if isinstance(value, dict)
                ],
                "price_observations": [
                    {
                        "raw_amount": value.get("raw_amount"),
                        "normalized_amount": value.get("normalized_amount"),
                        "currency": value.get("currency"),
                        "currency_unknown": value.get("currency_unknown"),
                        "price_type": value.get("price_type"),
                        "item_binding": value.get("item_binding"),
                        "evidence_basis": value.get("evidence_basis"),
                    }
                    for value in item.get("price_observations", [])[:10]
                    if isinstance(value, dict)
                ],
                "answer_relevance": str(
                    item.get("answer_relevance") or ""
                )[:320],
                "uncertainty": str(item.get("uncertainty") or "")[:320],
            }
        )
    cards = cards if isinstance(cards, list) else []
    if ranking_mode_value == "PRICE":
        price_observations = [
            observation
            for post in compact_posts
            for observation in post.get("price_observations", [])
            if isinstance(observation, dict)
            and observation.get("raw_amount")
            and observation.get("normalized_amount") is not None
        ]
        chinese = bool(re.search(r"[\u3400-\u9fff]", str(user_message or "")))
        if not price_observations:
            reply = (
                "这次可可靠读取的相关帖子中没有发现可验证的价格数字。"
                "搜索页显示的互动数不会被当作价格，因此本次不生成价格排名。"
                if chinese else
                "No verifiable price values were found in the readable posts. "
                "Search-page engagement is not treated as a price, so no "
                "price ranking is produced."
            )
        else:
            unknown_currency_count = sum(
                bool(value.get("currency_unknown"))
                for value in price_observations
            )
            unbound_count = sum(
                not str(value.get("item_binding") or "").strip()
                for value in price_observations
            )
            if chinese:
                reply = (
                    "在这次可验证的帖子样本中，共读取到 "
                    + str(len(price_observations))
                    + " 个价格数字。具体数值、对应对象、图片和原帖链接"
                    "已放在各自卡片中。"
                )
                if unknown_currency_count:
                    reply += (
                        "其中 " + str(unknown_currency_count)
                        + " 个未显示币种，已按原始数字保留。"
                    )
                if unbound_count:
                    reply += (
                        "另有 " + str(unbound_count)
                        + " 个价格无法可靠对应到具体卡片。"
                    )
            else:
                reply = (
                    "This verified sample contains "
                    + str(len(price_observations))
                    + " visible price values. Each value, item binding, image, "
                    "and original-post link is kept in its matching card."
                )
                if unknown_currency_count:
                    reply += (
                        " " + str(unknown_currency_count)
                        + " values do not show a currency and remain in their "
                        "original notation."
                    )
                if unbound_count:
                    reply += (
                        " " + str(unbound_count)
                        + " values could not be reliably bound to a specific item."
                    )
        print(
            "[SOCIAL PRICE SYNTHESIS]",
            "posts=" + str(len(compact_posts)),
            "prices=" + str(len(price_observations)),
            "cards=" + str(len(cards)),
        )
        return reply
    packet = {
        "user_request": str(user_message or "")[:700],
        "search_query": str(query or "")[:200],
        "verified_entity_aliases": _verified_social_entity_aliases(
            user_message, query
        ),
        "required_narrative_language": _social_narrative_language(user_message),
        "platforms": [
            value for value in platforms if value in SOCIAL_PLATFORM_NAMES
        ],
        "selection_mode": str(selection_mode or "RELEVANCE").upper(),
        "ranking_mode": str(ranking_mode or "DEFAULT").upper(),
        "page_summary": str(
            (evidence if isinstance(evidence, dict) else {}).get(
                "page_summary"
            ) or ""
        )[:500],
        "grounded_posts": compact_posts,
    }
    packet_text = json.dumps(packet, ensure_ascii=False)
    print(
        "[SOCIAL SYNTHESIS PROMPT]",
        "posts=" + str(len(compact_posts)),
        "chars=" + str(len(packet_text)),
        "num_ctx=8192",
    )
    try:
        raw = run_ai_prompt(
            "prompts/social_synthesis.txt",
            packet_text,
            expect_json=True,
            num_ctx=8192,
            num_predict=1000,
            think=False,
            model_name="gemma4:12b",
            json_schema=_SOCIAL_SYNTHESIS_SCHEMA,
        )
    except Exception as error:
        print(
            "[SOCIAL SYNTHESIS FALLBACK]",
            type(error).__name__,
            repr(error),
        )
        return ""
    if not isinstance(raw, dict):
        return ""
    answer = str(raw.get("answer") or "").strip()[:2200]
    if not answer:
        return ""
    if ranking_mode_value == "DISCUSSION":
        ranked_comments = [
            (
                str(item.get("post_title") or "").strip(),
                str(item.get("comments") or "").strip(),
            )
            for item in compact_posts
            if str(item.get("post_title") or "").strip()
            and str(item.get("comments") or "").strip()
        ]
        if ranked_comments:
            lead = (
                "在这次可验证的 " + str(len(compact_posts))
                + " 条帖子样本中，按可见评论数从高到低为："
                + "；".join(
                    "《" + title + "》" + comments + " 条评论"
                    for title, comments in ranked_comments[:7]
                ) + "。"
            )
            answer = lead + "\n\n" + answer
    elif ranking_mode_value in {"POPULARITY", "PRICE"}:
        answer = (
            "以下结论仅限这次可验证的 " + str(len(compact_posts))
            + " 条帖子样本。\n\n" + answer
        )
    card_by_title = {}
    for card in cards:
        if not isinstance(card, dict):
            continue
        metadata = card.get("metadata")
        if not isinstance(metadata, dict):
            metadata = {}
        for card_title in (card.get("title"), metadata.get("post_title")):
            title_key = str(card_title or "").strip().casefold()
            if title_key:
                card_by_title[title_key] = card
    findings = []
    seen_titles = set()
    for value in raw.get("findings", [])[:7]:
        if not isinstance(value, dict):
            continue
        requested_title = str(value.get("post_title") or "").strip()
        title = valid_titles.get(requested_title.casefold())
        finding = str(value.get("finding") or "").strip()[:360]
        if not title or not finding or title.casefold() in seen_titles:
            continue
        findings.append((title, finding))
        seen_titles.add(title.casefold())
        matching_card = card_by_title.get(title.casefold())
        if matching_card is not None:
            sections = matching_card.get("sections")
            if not isinstance(sections, list):
                sections = []
                matching_card["sections"] = sections
            if len(sections) < 8 and not any(
                isinstance(section, dict)
                and str(section.get("label") or "") == "本次结论"
                for section in sections
            ):
                sections.append(
                    {
                        "kind": "fit",
                        "label": "本次结论",
                        "text": finding,
                    }
                )
    limitations = [
        str(value).strip()[:300]
        for value in raw.get("limitations", [])[:4]
        if str(value).strip()
    ]
    aggregate_request = (
        str(ranking_mode or "DEFAULT").upper()
        in {"DISCUSSION", "POPULARITY", "PRICE"}
        or bool(re.search(r"\btop\s*\d+\b|前\s*\d+|排名", str(user_message), re.I))
    )
    opened_count = sum(
        str(item.get("evidence_level") or "")
        in {"opened_multimodal", "opened_text"}
        for item in compact_posts
    )
    confidence = str(raw.get("confidence") or "unknown").lower()
    if aggregate_request and opened_count < 3:
        confidence = "low"
        sample_warning = "可可靠打开的相关帖子少于 3 条，不能据此代表整体讨论趋势。"
        if not any("少于 3" in value or "样本" in value for value in limitations):
            limitations.append(sample_warning)
    lines = [answer]
    if findings and not cards:
        lines.extend(["", "主要依据："])
        for title, finding in findings:
            lines.append("- 《" + title + "》：" + finding)
    if limitations:
        lines.extend(["", "需要注意："])
        for limitation in limitations:
            lines.append("- " + limitation)
    print(
        "[SOCIAL SYNTHESIS]",
        "findings=" + str(len(findings)),
        "limitations=" + str(len(limitations)),
        "confidence=" + confidence,
    )
    return "\n".join(lines).strip()


def render_social_research_reply(
    evidence,
    summaries,
    cards,
    recency_days=None,
    platforms=None,
    selection_mode=None,
    ranking_mode="DEFAULT",
    bundle_card_context=False,
):
    """Render already AI-extracted social summaries without dropping items."""
    summaries = summaries if isinstance(summaries, list) else []
    cards = cards if isinstance(cards, list) else []
    if not isinstance(evidence, dict):
        evidence = {}
    if platforms is None:
        platforms = evidence.get("platforms") or ["xiaohongshu"]
    platforms = [
        value for value in platforms if value in SOCIAL_PLATFORM_NAMES
    ] or ["xiaohongshu"]
    platform_label = "、".join(
        SOCIAL_PLATFORM_NAMES[value] for value in platforms
    )
    selection_mode = str(
        selection_mode
        or evidence.get("selection_mode")
        or ("RECENT" if recency_days is not None else "RELEVANCE")
    ).strip().upper()
    if selection_mode not in {"RECENT", "RELEVANCE"}:
        selection_mode = "RELEVANCE"
    ranking_mode = str(ranking_mode or "DEFAULT").strip().upper()
    if selection_mode == "RECENT":
        recency_days = min(max(int(recency_days or 7), 1), 3650)
    else:
        recency_days = None
    if not summaries:
        if selection_mode == "RECENT":
            return (
                platform_label + "最近 " + str(recency_days)
                + " 天内没有找到日期和内容都能可靠读取的相关帖子。"
            )
        return (
            "在 " + platform_label
            + " 没有找到与问题关联度足够且内容可可靠读取的帖子。"
        )
    page_summary = str(evidence.get("page_summary") or "").strip()
    if selection_mode == "RECENT":
        lines = [
            platform_label + "最近 " + str(recency_days) + " 天内找到 "
            + str(len(summaries)) + " 条可验证日期的相关帖子。"
        ]
    else:
        lines = [
            "在 " + platform_label + " 找到 " + str(len(summaries))
            + " 条与问题相关且内容可可靠读取的帖子。"
        ]
    if page_summary:
        lines.append(page_summary)
    if ranking_mode == "DISCUSSION":
        lines.append(
            "以下仅按这次可验证样本的可见评论数排列，不代表整个社区。"
        )
    elif ranking_mode == "PRICE":
        lines.append(
            "以下按帖子中可读到的标价数值排列；未显示币种时会明确保留为未知。"
        )
    elif selection_mode == "RELEVANCE":
        lines.append(
            "以下按与问题的语义关联度排列；互动数只作补充，不决定顺序。"
        )
    elif any(
        item.get("search_visible_interaction") is not None
        for item in summaries if isinstance(item, dict)
    ):
        lines.append(
            "以下按搜索页可见互动从多到少排列；该数值的具体类型未标注，"
            "不拆分为点赞、评论或分享。"
        )
    if bundle_card_context and cards:
        lines.append("")
        if ranking_mode == "DISCUSSION":
            lines.append(
                "评论数最高的 " + str(len(cards))
                + " 条样本已整理为下方独立卡片。"
            )
        elif ranking_mode == "PRICE":
            lines.append(
                "含可读价格证据的 " + str(len(cards))
                + " 条帖子已整理为下方独立卡片。"
            )
        elif selection_mode == "RELEVANCE":
            lines.append(
                "关联度最高的 " + str(len(cards))
                + " 条帖子已整理为下方独立卡片。"
            )
        else:
            lines.append(
                "筛选出的 " + str(len(cards)) + " 条帖子已整理为下方独立卡片。"
            )
        lines.append("每张卡片依次包含对应说明、图片与原帖链接，不在正文重复。")
        lines.append("详情页没有显示的点赞、评论或转发数据会保留为未知。")
        reply = "\n".join(lines).strip()
        print("[SOCIAL DIRECT REPLY]", len(summaries), "summaries", len(cards), "cards")
        return reply
    lines.append("")
    for index, item in enumerate(summaries[:7], start=1):
        if not isinstance(item, dict):
            continue
        title = str(item.get("post_title") or "未命名帖子").strip()
        description = str(item.get("description") or "").strip()
        metadata = []
        author = str(item.get("author") or "").strip()
        published_at = str(item.get("published_at") or "").strip()
        if author:
            metadata.append("作者 " + author)
        if published_at:
            metadata.append(published_at)
        metric_labels = (
            ("likes", "点赞"),
            ("comments", "评论"),
            ("shares", "转发/分享"),
        )
        for field, label in metric_labels:
            value = item.get(field)
            if value is not None and str(value).strip():
                metadata.append(label + " " + str(value).strip())
        generic = item.get("search_visible_interaction")
        if generic is not None and str(generic).strip():
            metadata.append("搜索页可见互动 " + str(generic).strip())
        suffix = "（" + "；".join(metadata) + "）" if metadata else ""
        lines.append(
            str(index) + ". 《" + title + "》：" + description + suffix
        )
    lines.append("")
    if cards:
        if ranking_mode == "DISCUSSION":
            lines.append(
                "评论数最高的 " + str(len(cards))
                + " 条样本已放在下方卡片中。"
            )
        elif ranking_mode == "PRICE":
            lines.append(
                "含可读价格证据的 " + str(len(cards))
                + " 条帖子已放在下方卡片中。"
            )
        elif selection_mode == "RELEVANCE":
            lines.append(
                "关联度最高的 " + str(len(cards))
                + " 条已经放在下方卡片中。"
            )
        else:
            lines.append(
                "最高的 " + str(len(cards)) + " 条已经放在下方卡片中。"
            )
    else:
        lines.append(
            "这次没有帖子同时取得可绑定的页面和互动依据，因此不生成卡片。"
        )
    lines.append("详情页没有显示的点赞、评论或转发数据会保留为未知。")
    reply = "\n".join(lines).strip()
    print("[SOCIAL DIRECT REPLY]", len(summaries), "summaries", len(cards), "cards")
    return reply


def build_social_cards(
    recent_items,
    post_details,
    introductions,
    visual_evidence,
    selection_mode="RECENT",
    ranking_mode="DEFAULT",
    include_unranked=False,
    max_cards=3,
):
    """Rank grounded posts by the active social selection contract."""

    selection_mode = str(selection_mode or "RECENT").strip().upper()

    recent_by_title = {
        str(item.get("title") or "").strip().casefold(): item
        for item in recent_items if isinstance(item, dict)
    }
    intro_by_title = {
        str(item.get("post_title") or "").strip().casefold(): item
        for item in introductions if isinstance(item, dict)
    }
    visual_by_title = {
        str(item.get("post_title") or "").strip().casefold(): item
        for item in visual_evidence.get("observations", [])
        if isinstance(item, dict)
    }
    ranked_candidates = []
    for source_order, detail in enumerate(
        post_details if isinstance(post_details, list) else []
    ):
        if not isinstance(detail, dict):
            continue
        post_title = str(detail.get("post_title") or "").strip()
        recent = recent_by_title.get(post_title.casefold(), {})
        intro = intro_by_title.get(post_title.casefold(), {})
        visual = visual_by_title.get(post_title.casefold(), {})
        intro_scope = _normalize_social_scope_match(
            intro.get("scope_match"),
            intro.get("answer_relevance") or intro.get("suitability_note"),
        )
        if intro and intro_scope["decision"] != "INCLUDE":
            continue
        restaurant_name = str(intro.get("restaurant_name") or "").strip()
        primary_subject = str(
            intro.get("primary_subject") or restaurant_name or ""
        ).strip()
        summary_parts = []
        introduction = str(intro.get("introduction") or "").strip()
        if introduction:
            summary_parts.append(introduction)
        visual_description = str(
            intro.get("visual_description") or visual.get("description") or ""
        ).strip()
        if visual_description:
            summary_parts.append("图片可见：" + visual_description)
        if not summary_parts:
            relevance_reason = str(
                recent.get("relevance_reason") or ""
            ).strip()[:360]
            summary_parts.append(
                relevance_reason
                or "已验证该社交媒体帖子的页面与链接；额外介绍暂不可用。"
            )
        facts = {}
        if recent.get("author"):
            facts["作者"] = recent["author"]
        if recent.get("resolved_date"):
            facts["发布日期"] = recent["resolved_date"]
        if restaurant_name:
            facts["餐厅名称"] = restaurant_name
        elif primary_subject:
            facts["主要对象"] = primary_subject
        prices = [
            value for value in intro.get("price_observations", [])[:10]
            if isinstance(value, dict) and value.get("raw_amount")
        ]
        if (
            str(ranking_mode or "DEFAULT").strip().upper() == "PRICE"
            and not prices
        ):
            prices = _clean_social_price_observations(
                [],
                post_title,
                False,
                excluded_metric_values=(recent.get("engagement"),),
            )
        metric_intro = dict(intro)
        metric_intro["price_observations"] = prices
        metrics = _social_metrics_for_post(recent, metric_intro, ranking_mode)
        metric_labels = {
            "likes": "点赞",
            "comments": "评论",
            "shares": "转发/分享",
        }
        for metric, label in metric_labels.items():
            if metrics["display"][metric]:
                facts[label] = metrics["display"][metric]
        if metrics["search_visible_interaction"]:
            facts["搜索页可见互动"] = metrics["search_visible_interaction"]
        if str(ranking_mode or "").strip().upper() == "PRICE":
            prices.sort(
                key=lambda value: -float(value.get("normalized_amount") or 0)
            )
        price_labels = []
        if prices:
            for value in prices[:8]:
                label = str(value.get("raw_amount") or "").strip()
                qualifiers = []
                price_type = str(value.get("price_type") or "unknown")
                if price_type == "asking":
                    qualifiers.append("求售价")
                elif price_type == "sold":
                    qualifiers.append("已成交价")
                elif price_type == "per_person":
                    qualifiers.append("人均")
                if value.get("currency_unknown"):
                    qualifiers.append("币种未注明")
                if qualifiers:
                    label += "（" + "；".join(qualifiers) + "）"
                if label:
                    price_labels.append(label)
            if price_labels:
                facts["帖子标价"] = "、".join(price_labels)
        sections = []
        if facts:
            sections.append({"kind": "facts", "items": facts})
        if price_labels:
            sections.append(
                {
                    "kind": "note",
                    "label": "价格证据",
                    "text": "、".join(price_labels),
                }
            )
        textual_findings = [
            value for value in intro.get("textual_findings", [])[:4]
            if isinstance(value, dict) and value.get("finding")
        ]
        if textual_findings:
            sections.append(
                {
                    "kind": "note",
                    "label": "贴文证据",
                    "text": "；".join(
                        str(value.get("finding") or "")
                        for value in textual_findings
                    ),
                }
            )
        visual_findings = [
            value for value in intro.get("visual_findings", [])[:4]
            if isinstance(value, dict) and value.get("finding")
        ]
        if visual_findings:
            sections.append(
                {
                    "kind": "note",
                    "label": "图片观察",
                    "text": "；".join(
                        str(value.get("finding") or "")
                        for value in visual_findings
                    ),
                }
            )
        answer_relevance = str(
            intro.get("answer_relevance")
            or intro.get("suitability_note")
            or ""
        ).strip()
        if answer_relevance:
            sections.append(
                {
                    "kind": "fit",
                    "label": "与本次问题的关系",
                    "text": answer_relevance,
                }
            )
        sections.append(
            {
                "kind": "warning",
                "label": "信息性质",
                "text": (
                    "仅成功读取搜索结果卡片，正文和餐厅/商品身份尚未确认。"
                    if str(detail.get("evidence_level") or "") == "search_only"
                    else intro.get("uncertainty")
                    or "来自社交媒体用户分享，尚未独立核实。"
                ),
            }
        )
        image_url = str(detail.get("image_url") or "").strip()
        platform = str(detail.get("platform") or "").strip()
        asset_limit = 1 if platform == "reddit" else 4 if platform == "xiaohongshu" else 2
        visual_assets = [
            value for value in detail.get("visual_assets", [])[:asset_limit]
            if isinstance(value, dict)
        ] if isinstance(detail.get("visual_assets"), list) else []
        if not visual_assets:
            local_image_paths = [
                str(value).strip()
                for value in detail.get("local_image_paths", [])[:asset_limit]
                if str(value).strip()
            ] if isinstance(detail.get("local_image_paths"), list) else []
            visual_assets = [
                {
                    "local_path": local_path,
                    "kind": "search_preview" if str(
                        detail.get("evidence_level") or ""
                    ) == "search_only" else "media",
                    "label": "搜索结果预览" if str(
                        detail.get("evidence_level") or ""
                    ) == "search_only" else "图片 " + str(index + 1),
                }
                for index, local_path in enumerate(local_image_paths)
            ]
        images = [
            {
                "local_path": str(asset.get("local_path") or "").strip(),
                "url": "",
                "alt": visual_description or post_title,
                "source_url": detail.get("post_url") or detail.get("url", ""),
                "kind": str(asset.get("kind") or "media"),
                "label": str(asset.get("label") or "图片"),
            }
            for asset in visual_assets
            if str(asset.get("local_path") or "").strip()
        ]
        if not images and image_url.lower().startswith("https://"):
            images.append(
                {
                    "url": image_url,
                    "alt": visual_description or post_title,
                    "source_url": detail.get("post_url") or detail.get("url", ""),
                    "kind": "search_preview",
                    "label": "搜索结果预览",
                }
            )
        card_url = str(
            detail.get("post_url") or detail.get("url") or ""
        ).strip()
        evidence_level = str(
            detail.get("evidence_level") or "search_only"
        ).strip()
        link_target = (
            "post"
            if result_cards.is_concrete_social_post_url(card_url)
            else "search"
        )
        card = {
            "type": "social_post",
            "title": restaurant_name or post_title,
            "summary": " ".join(summary_parts)[:600],
            "url": card_url,
            "domain": SOCIAL_PLATFORM_NAMES.get(
                detail.get("platform"), detail.get("platform", "")
            ),
            "image": images[0] if images else None,
            "images": images,
            "metadata": {
                "author": recent.get("author"),
                "published_at": recent.get("resolved_date"),
                "price": price_labels[0] if price_labels else None,
                "post_title": post_title,
                "evidence_level": evidence_level,
                "link_target": link_target,
            },
            "sections": sections,
            "requirements": [],
        }
        relevance_score = min(
            max(_nonnegative_int(recent.get("relevance_score")), 0), 100
        )
        if (
            selection_mode == "RELEVANCE"
            or metrics["rank_score"] is not None
            or include_unranked
        ):
            ranked_candidates.append(
                {
                    "card": card,
                    "post_title": post_title,
                    "rank_score": metrics["rank_score"],
                    "relevance_score": relevance_score,
                    "known_metric_count": metrics["known_metric_count"],
                    "source_order": source_order,
                    "metrics": metrics,
                }
            )
    if selection_mode == "RELEVANCE" and str(
        ranking_mode or "DEFAULT"
    ).strip().upper() == "DEFAULT":
        ranked_candidates.sort(
            key=lambda item: (
                -item["relevance_score"],
                item["rank_score"] is None,
                -(item["rank_score"] or 0),
                -item["known_metric_count"],
                item["source_order"],
            )
        )
        rank_log = "[SOCIAL RELEVANCE RANK]"
    else:
        ranked_candidates.sort(
            key=lambda item: (
                item["rank_score"] is None,
                -(item["rank_score"] or 0),
                -item["known_metric_count"],
                item["source_order"],
            )
        )
        rank_log = (
            "[SOCIAL PRICE RANK]"
            if str(ranking_mode or "").strip().upper() == "PRICE"
            else "[SOCIAL DISCUSSION RANK]"
            if str(ranking_mode or "").strip().upper() == "DISCUSSION"
            else "[SOCIAL ENGAGEMENT RANK]"
        )
    print(
        rank_log,
        json.dumps(
            [
                {
                    "post_title": item["post_title"],
                    "relevance_score": item["relevance_score"],
                    "visible_total": item["rank_score"],
                    "likes": item["metrics"]["display"]["likes"],
                    "comments": item["metrics"]["display"]["comments"],
                    "shares": item["metrics"]["display"]["shares"],
                    "search_visible_interaction": item["metrics"][
                        "search_visible_interaction"
                    ],
                }
                for item in ranked_candidates[:7]
            ],
            ensure_ascii=False,
        )
    )
    try:
        max_cards = min(max(int(max_cards or 3), 1), 5)
    except (TypeError, ValueError):
        max_cards = 3
    cleaned = result_cards.clean_cards(
        [item["card"] for item in ranked_candidates[:max_cards]]
    )
    print("[SOCIAL CARDS]", len(cleaned))
    return cleaned

def social_research_controller(
    user_message,
    platforms,
    status_callback=None,
    recency_days=None,
):
    """Search an authorized social page and return unverified discussion evidence."""

    platforms = [
        platform
        for platform in platforms
        if platform in SOCIAL_PLATFORM_NAMES
    ]

    if not platforms:
        return {
            "status": "NO_PLATFORM",
            "query": "",
            "results": [],
            "context": "No supported social platform was selected.",
        }

    _status(status_callback, "正在整理社媒关键词… 💬")
    try:
        query_plan = build_social_query_plan(user_message, platforms)
        query = query_plan["query"]
        selection_mode = query_plan["selection_mode"]
        planned_recency_days = query_plan["recency_days"]
        ranking_mode = str(
            query_plan.get("ranking_mode")
            or _social_ranking_intent(user_message)
        ).strip().upper()
        if ranking_mode not in {
            "DEFAULT", "DISCUSSION", "POPULARITY", "PRICE"
        }:
            ranking_mode = "DEFAULT"
        fallback_query = str(
            query_plan.get("fallback_query") or ""
        ).strip()[:160]
        # A non-null caller value is an explicit compatibility contract used
        # by older integrations and tests. Normal production calls leave it
        # null so the existing social-query AI owns this semantic decision.
        if recency_days is not None:
            selection_mode = "RECENT"
            planned_recency_days = min(
                max(int(recency_days or 7), 1), 3650
            )
        recency_days = planned_recency_days
    except Exception as error:
        print("[SOCIAL QUERY ERROR]", repr(error))
        return {
            "status": "QUERY_UNAVAILABLE",
            "query": "",
            "results": [],
            "context": (
                "MELCHIOR response mode: SOCIAL_RESEARCH\n"
                "The reliable AI could not create a platform-native query."
            ),
        }
    print(
        "[SOCIAL QUERY PLAN]",
        json.dumps(
            {
                "platforms": platforms,
                "query": query,
                "selection_mode": selection_mode,
                "recency_days": recency_days,
                "ranking_mode": ranking_mode,
                "fallback_query": fallback_query or None,
            },
            ensure_ascii=False,
        ),
    )

    page_texts = []
    visual_frames = []
    post_candidates = []
    opened_searches = []
    results = []

    for platform in platforms:
        _status(
            status_callback,
            "正在搜索 "
            + SOCIAL_PLATFORM_NAMES[platform]
            + "… 🔎",
        )

        try:
            open_kwargs = {"selection_mode": selection_mode}
            if ranking_mode != "DEFAULT":
                open_kwargs.update(
                    {
                        "ranking_mode": ranking_mode,
                        "recency_days": recency_days,
                    }
                )
            opened = social_browser.open_social_search(
                platform,
                query,
                **open_kwargs,
            )
            opened_searches.append(
                {"platform": platform, "url": opened.get("url", "")}
            )

            # Give a social SPA a brief moment to render its visible posts.
            time.sleep(2)

            page = social_browser.inspect_active_social_page(
                platform
                ,expected_url=opened.get("url", ""),
            )

            visible_text = page.get("visible_text", "").strip()

            if visible_text:
                page_texts.append(
                    "\n\n===== "
                    + SOCIAL_PLATFORM_NAMES[platform]
                    + " =====\n"
                    + visible_text
                )
            page_frames = page.get("visual_frames", [])
            if isinstance(page_frames, list):
                for frame in page_frames:
                    if isinstance(frame, str) and frame.strip():
                        visual_frames.append(frame)
                    if len(visual_frames) >= 3:
                        break
            candidates = page.get("post_candidates", [])
            if isinstance(candidates, list):
                post_candidates.extend(candidates)

            results.append(
                {
                    "domain": SOCIAL_PLATFORM_NAMES.get(platform,""),
                    "url": page.get(
                        "url",
                        opened.get("url", ""),
                    ),
                    "source_score": 100,
                    "is_concrete_news": False,
                    "content_type": "SOCIAL_DISCUSSION",
                }
            )

        except Exception as error:
            print(
                "[SOCIAL RESEARCH ERROR]",
                platform,
                repr(error),
            )
    if not page_texts:
        social_browser.close_social_browser()
        return {
            "status": "NO_READABLE_SOCIAL_PAGE",
            "query": query,
            "results": results,
            "context": (
                "MELCHIOR response mode: SOCIAL_RESEARCH\n"
                "The social search page could not be read."
            ),
        }
    evidence = extract_social_evidence(
        "\n".join(page_texts),
        recency_days=recency_days,
        selection_mode=selection_mode,
        user_message=user_message,
        query=query,
        ranking_mode=ranking_mode,
        platforms=platforms,
    )
    evidence["platforms"] = list(platforms)
    if (
        not evidence.get("items")
        and fallback_query
        and fallback_query.casefold() != query.casefold()
    ):
        print(
            "[SOCIAL QUERY LANGUAGE RETRY]",
            json.dumps(
                {"previous": query, "retry": fallback_query},
                ensure_ascii=False,
            ),
        )
        social_browser.close_social_browser()
        page_texts = []
        visual_frames = []
        post_candidates = []
        opened_searches = []
        results = []
        for platform in platforms:
            try:
                open_kwargs = {"selection_mode": selection_mode}
                if ranking_mode != "DEFAULT":
                    open_kwargs.update(
                        {
                            "ranking_mode": ranking_mode,
                            "recency_days": recency_days,
                        }
                    )
                opened = social_browser.open_social_search(
                    platform,
                    fallback_query,
                    **open_kwargs,
                )
                opened_searches.append(
                    {"platform": platform, "url": opened.get("url", "")}
                )
                time.sleep(2)
                page = social_browser.inspect_active_social_page(
                    platform,
                    expected_url=opened.get("url", ""),
                )
                visible_text = str(page.get("visible_text") or "").strip()
                if visible_text:
                    page_texts.append(
                        "\n\n===== "
                        + SOCIAL_PLATFORM_NAMES[platform]
                        + " =====\n"
                        + visible_text
                    )
                for frame in page.get("visual_frames", [])[:3]:
                    if isinstance(frame, str) and frame.strip():
                        visual_frames.append(frame)
                candidates = page.get("post_candidates", [])
                if isinstance(candidates, list):
                    post_candidates.extend(candidates)
                results.append(
                    {
                        "domain": SOCIAL_PLATFORM_NAMES.get(platform, ""),
                        "url": page.get("url", opened.get("url", "")),
                        "source_score": 100,
                        "is_concrete_news": False,
                        "content_type": "SOCIAL_DISCUSSION",
                    }
                )
            except Exception as error:
                print("[SOCIAL RETRY ERROR]", platform, repr(error))
        if page_texts:
            query = fallback_query
            evidence = extract_social_evidence(
                "\n".join(page_texts),
                recency_days=recency_days,
                selection_mode=selection_mode,
                user_message=user_message,
                query=query,
                ranking_mode=ranking_mode,
                platforms=platforms,
            )
            evidence["platforms"] = list(platforms)
    _status(status_callback, "正在理解社媒图片… 👀")
    visual_overview_pending = bool(
        visual_frames and ranking_mode != "PRICE"
    )
    if visual_frames and ranking_mode == "PRICE":
        # The overview screenshots do not own post-specific price evidence.
        # Skip this optional vision call so a transient CUDA/model-load failure
        # cannot prevent the subsequent title-bound post screenshots, text, and
        # price cards from being collected.
        print(
            "[SOCIAL VISUAL OVERVIEW SKIPPED]",
            "reason=price_mode_post_bound_evidence",
        )
        visual_evidence = {
            "frames_analyzed": 0,
            "visual_summary": "",
            "observations": [],
            "warnings": [
                "价格检索直接使用逐帖截图和文字证据，已跳过搜索页总览图片理解。"
            ],
        }
    else:
        visual_evidence = {
            "frames_analyzed": 0,
            "visual_summary": "",
            "observations": [],
            "warnings": [],
        }
        if visual_overview_pending:
            print(
                "[SOCIAL VISUAL OVERVIEW DEFERRED]",
                "reason=prefer_post_bound_evidence",
            )
    evidence["visual_evidence"] = visual_evidence
    print("[SOCIAL POST CANDIDATES]", len(post_candidates))
    verified_titles = [
        item.get("title", "")
        for item in evidence.get("items", []) if isinstance(item, dict)
    ]
    title_targets = []
    for opened in opened_searches:
        try:
            title_targets.extend(
                social_browser.resolve_social_post_targets(
                    opened.get("platform", ""),
                    verified_titles,
                    expected_url=opened.get("url", ""),
                )
            )
        except Exception as error:
            print("[SOCIAL TITLE RESOLVE ERROR]", repr(error))
    reddit_communities = (
        _requested_reddit_communities(user_message, query)
        if "reddit" in platforms else set()
    )
    if reddit_communities:
        title_targets = [
            item for item in title_targets
            if _within_reddit_community_scope(item, reddit_communities)
        ]
        post_candidates = [
            item for item in post_candidates
            if _within_reddit_community_scope(item, reddit_communities)
        ]
        print(
            "[SOCIAL REDDIT SCOPE]",
            "communities=" + ",".join(sorted(reddit_communities)),
            "targets=" + str(len(title_targets)),
            "candidates=" + str(len(post_candidates)),
        )
    print("[SOCIAL TITLE LOCATED]", len(title_targets))
    fallback_matches = match_social_post_candidates(
        evidence.get("items", []), post_candidates
    )
    matched_posts = list(title_targets)
    matched_titles = {
        str(item.get("post_title") or "").strip().casefold()
        for item in matched_posts
    }
    for item in fallback_matches:
        title_key = str(item.get("post_title") or "").strip().casefold()
        if title_key and title_key not in matched_titles:
            matched_posts.append(item)
            matched_titles.add(title_key)
        if len(matched_posts) >= 7:
            break
    if reddit_communities:
        allowed_titles = {
            str(item.get("post_title") or "").strip().casefold()
            for item in matched_posts if isinstance(item, dict)
            and str(item.get("post_title") or "").strip()
        }
        original_items = [
            item for item in evidence.get("items", [])
            if isinstance(item, dict)
        ]
        evidence["items"] = [
            item for item in original_items
            if str(item.get("title") or "").strip().casefold()
            in allowed_titles
        ]
        removed = len(original_items) - len(evidence["items"])
        evidence["recent_post_count"] = len(evidence["items"])
        evidence["selected_post_count"] = len(evidence["items"])
        if removed:
            evidence["excluded_count"] = _nonnegative_int(
                evidence.get("excluded_count")
            ) + removed
            evidence.setdefault("warnings", []).append(
                "已排除 " + str(removed)
                + " 条不属于用户指定 Reddit 版块的结果。"
            )
        allowed_visual_titles = {
            str(item.get("title") or "").strip().casefold()
            for item in evidence["items"]
        }
        if isinstance(visual_evidence, dict):
            visual_evidence["observations"] = [
                item for item in visual_evidence.get("observations", [])
                if isinstance(item, dict)
                and str(item.get("post_title") or "").strip().casefold()
                in allowed_visual_titles
            ]
    print("[SOCIAL POST MATCHES]", len(matched_posts))
    _status(status_callback, "正在读取推荐帖介绍… 📝")
    try:
        post_details = social_browser.inspect_social_post_details(matched_posts)
    except Exception as error:
        print("[SOCIAL POST DETAILS ERROR]", repr(error))
        post_details = []
    print("[SOCIAL POST OPENED]", len(post_details))
    print(
        "[SOCIAL DETAIL FRAMES]",
        sum(
            bool(str(item.get("visual_frame") or "").strip())
            for item in post_details if isinstance(item, dict)
        ),
    )
    if not post_details:
        post_details = [
            {
                **item,
                "search_visible_text": item.get("visible_text", ""),
                "visible_text": item.get("visible_text", ""),
            }
            for item in matched_posts
        ]
    print("[SOCIAL POST DETAILS]", len(post_details))
    recent_items = [
        item for item in evidence.get("items", [])
        if isinstance(item, dict)
    ]
    (
        recent_items,
        post_details,
        detail_date_warnings,
        detail_date_dropped,
    ) = reconcile_social_detail_dates(
        recent_items,
        post_details,
        selection_mode=selection_mode,
        recency_days=recency_days,
    )
    evidence["items"] = recent_items
    evidence["recent_post_count"] = len(recent_items)
    evidence["selected_post_count"] = len(recent_items)
    if detail_date_dropped:
        evidence["excluded_count"] = _nonnegative_int(
            evidence.get("excluded_count")
        ) + detail_date_dropped
    if detail_date_warnings:
        evidence.setdefault("warnings", []).extend(detail_date_warnings)
        evidence["warnings"] = evidence["warnings"][:8]
    if "youtube" in platforms:
        requested_youtube_handles = _requested_youtube_handles(
            user_message, query
        )
        (
            recent_items,
            post_details,
            youtube_channel_warnings,
            youtube_channel_dropped,
        ) = filter_youtube_channel_scope(
            recent_items,
            post_details,
            requested_youtube_handles,
        )
        if youtube_channel_dropped:
            evidence["excluded_count"] = _nonnegative_int(
                evidence.get("excluded_count")
            ) + youtube_channel_dropped
        if youtube_channel_warnings:
            evidence.setdefault("warnings", []).extend(
                youtube_channel_warnings
            )
            evidence["warnings"] = evidence["warnings"][:8]
        evidence["items"] = recent_items
        evidence["recent_post_count"] = len(recent_items)
        evidence["selected_post_count"] = len(recent_items)
    grounded_title_keys = {
        str(item.get("post_title") or "").strip().casefold()
        for item in post_details if isinstance(item, dict)
        and str(item.get("post_title") or "").strip()
    }
    grounded_recent_items = [
        item for item in recent_items
        if str(item.get("title") or "").strip().casefold()
        in grounded_title_keys
    ] if grounded_title_keys else recent_items
    if grounded_title_keys and len(grounded_recent_items) != len(recent_items):
        print(
            "[SOCIAL GROUNDED ITEM FILTER]",
            "selected=" + str(len(grounded_recent_items)),
            "excluded=" + str(len(recent_items) - len(grounded_recent_items)),
        )
    post_bound_evidence = any(
        (
            any(
                bool(str(frame or "").strip())
                for frame in item.get("visual_frames", [])
            )
            if isinstance(item.get("visual_frames"), list) else False
        )
        or bool(str(item.get("visual_frame") or "").strip())
        or any(
            bool(
                str(asset.get("frame") or "").strip()
                or str(asset.get("local_path") or "").strip()
            )
            for asset in (
                item.get("visual_assets", [])
                if isinstance(item.get("visual_assets"), list) else []
            )
            if isinstance(asset, dict)
        )
        for item in post_details if isinstance(item, dict)
    )
    if visual_overview_pending:
        if post_bound_evidence:
            print(
                "[SOCIAL VISUAL OVERVIEW SKIPPED]",
                "reason=post_bound_evidence_available",
            )
            visual_evidence = {
                "frames_analyzed": 0,
                "visual_summary": "",
                "observations": [],
                "warnings": [
                    "已使用逐帖截图理解内容，未重复分析搜索结果总览。"
                ],
            }
        else:
            try:
                visual_evidence = extract_social_visual_evidence(
                    visual_frames,
                    user_message,
                    grounded_recent_items,
                    platforms,
                )
            except Exception as error:
                print(
                    "[SOCIAL VISUAL OVERVIEW ERROR]",
                    type(error).__name__,
                    repr(error),
                )
                visual_evidence = {
                    "frames_analyzed": 0,
                    "visual_summary": "",
                    "observations": [],
                    "warnings": [
                        "搜索页图片理解失败；已继续读取帖子、截图和文字证据。"
                    ],
                }
    evidence["visual_evidence"] = visual_evidence
    social_browser.close_social_browser()
    try:
        introductions = extract_social_post_introductions(
            user_message,
            grounded_recent_items,
            post_details,
            visual_evidence,
        )
    except Exception as error:
        print(
            "[SOCIAL INTRODUCTIONS FALLBACK]",
            type(error).__name__,
            repr(error),
        )
        introductions = []
    (
        grounded_recent_items,
        post_details,
        introductions,
        scope_removed_titles,
    ) = filter_social_scope_matches(
        grounded_recent_items,
        post_details,
        introductions,
    )
    if scope_removed_titles:
        removed_count = len(scope_removed_titles)
        evidence["excluded_count"] = _nonnegative_int(
            evidence.get("excluded_count")
        ) + removed_count
        evidence.setdefault("warnings", []).append(
            "已排除 " + str(removed_count)
            + " 条仅因推荐位置相邻、但主体/类别/联名关系不匹配的内容。"
        )
        evidence["warnings"] = evidence["warnings"][:8]
    evidence["items"] = grounded_recent_items
    evidence["recent_post_count"] = len(grounded_recent_items)
    evidence["selected_post_count"] = len(grounded_recent_items)
    post_summaries = build_social_post_summaries(
        grounded_recent_items,
        introductions,
        selection_mode=selection_mode,
        ranking_mode=ranking_mode,
    )
    evidence["post_summaries"] = post_summaries
    cards = build_social_cards(
        grounded_recent_items,
        post_details,
        introductions,
        visual_evidence,
        selection_mode=selection_mode,
        ranking_mode=ranking_mode,
        include_unranked=ranking_mode not in {"PRICE", "DISCUSSION"},
        max_cards=5,
    )
    direct_reply = synthesize_social_research_reply(
        user_message,
        query,
        evidence,
        post_summaries,
        platforms,
        selection_mode,
        ranking_mode=ranking_mode,
        cards=cards,
    )
    if (
        direct_reply
        and cards
        and "各自卡片" not in direct_reply
        and "matching card" not in direct_reply.casefold()
    ):
        if ranking_mode == "DISCUSSION":
            card_message = (
                "评论数最高的 " + str(len(cards))
                + " 条样本已放在下方卡片中。"
            )
        elif ranking_mode == "PRICE":
            card_message = (
                "含可读价格证据的 " + str(len(cards))
                + " 条帖子已放在下方卡片中。"
            )
        else:
            card_message = (
                "最相关的 " + str(len(cards))
                + " 条帖子已放在下方卡片中。"
            )
        direct_reply += "\n\n" + card_message
    if not direct_reply:
        direct_reply = render_social_research_reply(
            evidence,
            post_summaries,
            cards,
            recency_days,
            platforms=platforms,
            selection_mode=selection_mode,
            ranking_mode=ranking_mode,
            bundle_card_context=bool(cards),
        )
    for detail in post_details:
        url = str(detail.get("url") or "").strip()
        if url:
            results.append(
                {
                    "domain": SOCIAL_PLATFORM_NAMES.get(
                        detail.get("platform"), detail.get("platform", "")
                    ),
                    "url": url,
                    "source_score": 100,
                    "is_concrete_news": False,
                    "content_type": "SOCIAL_POST",
                }
            )

    if selection_mode == "RECENT":
        scope_context = (
            "The requested time window is the last "
            + str(recency_days) + " days. Do not use items outside it.\n"
            "Within that window, validated visible engagement may be used "
            "for presentation order.\n"
        )
        card_context = (
            "Then identify the supplied cards as the posts with the highest "
            "validated visible engagement."
        )
    else:
        scope_context = (
            "The user did not request a time window. Evidence is selected and "
            "ordered by AI-judged semantic relevance to the exact request. "
            "Do not exclude a post merely because it is old or undated. "
            "Visible engagement is secondary and must not control order.\n"
        )
        card_context = (
            "Then identify the supplied cards as the posts with the highest "
            "semantic relevance to the exact request."
        )
    context = (
        "MELCHIOR response mode: SOCIAL_RESEARCH\n"
        "This is filtered visible discussion from a user-authorized"
        "social-media search page.\n"
        + scope_context
        + "Describe only what people are discussing.\n"
        "Social posts and rumors are not confirmed facts.\n"
        "Do not use prior conversation as evidence.\n\n"
        "Briefly describe every supplied post_summary (five to seven when "
        "available). "
        + card_context
        + " If fewer than three cards are "
        "supplied, present only those; never pad the list. Missing likes, "
        "comments, or shares remain unknown. A generic search-grid interaction "
        "number is not necessarily a like count.\n\n"
        "Filtered social evidence:\n"
        + json.dumps(evidence,ensure_ascii=False,indent=2,)
        + "\n\nGrounded social recommendation cards:\n"
        + json.dumps(cards, ensure_ascii=False, indent=2)
    )

    return {
        "status": "OK",
        "query": query,
        "selection_mode": selection_mode,
        "ranking_mode": ranking_mode,
        "recency_days": recency_days,
        "results": results,
        "visual_frame_count": len(visual_frames),
        "visual_evidence": visual_evidence,
        "social_post_summaries": post_summaries,
        "cards": cards,
        "direct_reply": direct_reply,
        "context": context,
    }



def search_controller(query, status_callback=None, evidence_budgets=None):
    """Orchestrates search. AI judges meaning; Python controls the flow."""

    budgets = tuple(evidence_budgets or SEARCH_BUDGETS)
    budgets = tuple(
        sorted({max(1, min(10, int(value))) for value in budgets})
    ) or SEARCH_BUDGETS

    # =====================================================
    # 1. Search
    # =====================================================

    _status(
        status_callback,
        "正在搜索… 🔍"
    )

    search_results = search(
        query,
        count=max(budgets)
    )

    if not isinstance(
        search_results,
        list
    ):
        return {
            "status": "ERROR",
            "query": query,
            "message": search_results,
            "context": (
                "Search failed: "
                + str(search_results)
            ),
        }

    if not search_results:
        return {
            "status": "NO_RESULTS",
            "query": query,
            "message": "No search results found.",
            "context": (
                "No search results were found for: "
                + query
            ),
        }


    # =====================================================
    # 2. Score Sources
    # =====================================================

    _status(
        status_callback,
        "正在评估来源… 📚"
    )

    scored_results = score_sources(
        query,
        search_results
    )

    if not scored_results:
        return {
            "status": "NO_RESULTS",
            "query": query,
            "message": "No usable search results found.",
            "context": (
                "Search returned results, "
                "but none could be evaluated."
            ),
        }


    # =====================================================
    # 3. Incremental Evidence Collection
    # =====================================================

    processed_results = []
    all_answers = []

    judgment = None
    budget_used = 0


    for budget in budgets:

        target_budget = min(
            budget,
            len(scored_results)
        )

        # 已经处理到了几条
        processed_count = len(
            processed_results
        )

        # 只拿这一轮新增的来源
        new_results = scored_results[
            processed_count:target_budget
        ]

        # ---------------------------------------------
        # 没有新的来源可处理
        # ---------------------------------------------

        if not new_results:
            break


        # ---------------------------------------------
        # Read only new pages
        # ---------------------------------------------

        _status(
            status_callback,
            (
                "正在读取网页… "
                f"{processed_count + 1}"
                f"-{target_budget}"
            )
        )

        read_results = read_search_results(
            new_results
        )


        # ---------------------------------------------
        # Extract only new evidence
        # ---------------------------------------------

        _status(
            status_callback,
            (
                "正在提取证据… "
                f"{processed_count + 1}"
                f"-{target_budget}"
            )
        )

        new_answers = extract_answers(
            query,
            read_results
        )


        # ---------------------------------------------
        # 防止 Extract AI 返回数量异常
        # ---------------------------------------------

        if len(new_answers) != len(
            read_results
        ):
            print(
                "EXTRACT COUNT MISMATCH:",
                len(new_answers),
                "expected:",
                len(read_results)
            )

            normalized_answers = []

            answer_map = {
                item.get("index"): item.get(
                    "answer"
                )
                for item in new_answers
                if isinstance(item, dict)
            }

            for local_index in range(
                1,
                len(read_results) + 1
            ):
                normalized_answers.append({
                    "index": local_index,
                    "answer": answer_map.get(
                        local_index
                    )
                })

            new_answers = normalized_answers


        # =================================================
        # 4. Convert local indexes → global indexes
        # =================================================

        global_answers = []

        for local_index, answer_item in enumerate(
            new_answers,
            start=1
        ):
            global_index = (
                processed_count
                + local_index
            )

            global_answers.append({
                "index": global_index,
                "answer": answer_item.get(
                    "answer"
                )
            })


        # ---------------------------------------------
        # 累积已经处理过的证据
        # ---------------------------------------------

        processed_results.extend(
            read_results
        )

        all_answers.extend(
            global_answers
        )

        budget_used = len(
            processed_results
        )


        # =================================================
        # 5. Evidence Judgment
        # =================================================

        _status(
            status_callback,
            (
                "正在核对证据… "
                f"{budget_used}/"
                f"{len(scored_results)}"
            )
        )

        judgment = find_consensus(
            query,
            all_answers
        )


        # ---------------------------------------------
        # AI 认为证据已经够了
        # ---------------------------------------------

        if not judgment.get(
            "need_more_sources",
            False
        ):
            break


        # ---------------------------------------------
        # 已经没有更多来源
        # ---------------------------------------------

        if budget_used >= len(
            scored_results
        ):
            break


    # =====================================================
    # 6. Fallback Judgment
    # =====================================================

    if judgment is None:
        judgment = {
            "consensus": False,
            "canonical_answer": None,
            "votes": 0,
            "need_more_sources": True,
            "reason": (
                "No evidence judgment was produced."
            ),
        }


    # =====================================================
    # 7. Final Status
    # =====================================================

    status = (
        "INSUFFICIENT_EVIDENCE"
        if judgment.get(
            "need_more_sources",
            False
        )
        else "OK"
    )


    # =====================================================
    # 8. Sources Summary
    # =====================================================

    source_summary = [
        {
            "title": item.get(
                "title",
                ""
            ),
            "domain": item.get(
                "domain",
                ""
            ),
            "url": item.get(
                "url",
                ""
            ),
            "source_score": item.get(
                "source_score",
                50
            ),
            "page_success": item.get(
                "page_success",
                False
            ),
            "reader_type": item.get
            ("reader_type", 
             ""),
        }
        for item in processed_results
    ]


    # =====================================================
    # 9. Context for Main AI
    # =====================================================

    search_context = (
        "Search query:\n"
        + query

        + "\n\nSearch status:\n"
        + status

        + "\n\nEvidence budget used:\n"
        + str(budget_used)

        + "\n\nEvidence judgment:\n"
        + json.dumps(
            judgment,
            ensure_ascii=False,
            indent=2
        )

        + "\n\nExtracted evidence:\n"
        + json.dumps(
            all_answers,
            ensure_ascii=False,
            indent=2
        )

        + "\n\nSources consulted:\n"
        + json.dumps(
            source_summary,
            ensure_ascii=False,
            indent=2
        )
    )


    # =====================================================
    # 10. Return
    # =====================================================

    return {
        "status": status,
        "query": query,
        "budget_used": budget_used,
        "results": processed_results,
        "answers": all_answers,
        "judgment": judgment,
        "context": search_context,
    }

def read_pdf(pdf_bytes):
    try:
        reader = PdfReader(
            BytesIO(pdf_bytes)
        )

        text_parts = []

        for page in reader.pages:
            page_text = page.extract_text()

            if page_text:
                text_parts.append(
                    page_text
                )

        text = "\n".join(
            text_parts
        ).strip()

        text = text[:15000]

        if len(text) < 100:
            return {
                "success": False,
                "reader_type": "pdf",
                "content": text,
                "error": (
                    "PDF contains too little "
                    "extractable text."
                )
            }

        return {
            "success": True,
            "reader_type": "pdf",
            "content": text,
            "error": None
        }

    except Exception as error:
        return {
            "success": False,
            "reader_type": "pdf",
            "content": "",
            "error": str(error)
        }

def read_page_with_browser(url):
    from playwright.sync_api import sync_playwright
    import managed_browser

    try:
        managed_browser.ensure_browser()
        with sync_playwright() as playwright:
            browser = playwright.chromium.connect_over_cdp(
                managed_browser.CDP_URL
            )
            if not browser.contexts:
                raise RuntimeError("Bekki Browser has no usable context.")
            page = browser.contexts[0].new_page()
            try:
                page.goto(
                    url,
                    wait_until="networkidle",
                    timeout=30000
                )
                page.wait_for_timeout(1500)

                # Amazon sometimes presents a normal Continue shopping
                # interstitial before the product page. It is not a CAPTCHA;
                # follow the visible navigation once, then read the page.
                if "amazon." in urlparse(url).netloc.lower():
                    continue_controls = page.get_by_text(
                        "Continue shopping",
                        exact=True,
                    )
                    if continue_controls.count() > 0:
                        try:
                            continue_controls.first.click(timeout=5000)
                            page.wait_for_load_state(
                                "domcontentloaded", timeout=15000
                            )
                            page.wait_for_timeout(1800)
                        except Exception as continue_error:
                            print(
                                "[AMAZON CONTINUE FAILED]",
                                repr(continue_error),
                            )

                text = page.locator("body").inner_text()
            finally:
                page.close(run_before_unload=False)

            text = text.strip()
            print("[BROWSER PREVIEW]",repr(text[:500]))

            text = text[:15000]

            if len(text) < 300:
                return {
                    "success": False,
                    "reader_type": "browser",
                    "content": text,
                    "error": (
                        "Browser returned too little "
                        "usable content."
                    )
                }

            return {
                "success": True,
                "reader_type": "browser",
                "content": text,
                "error": None
            }

    except Exception as error:
        return {
            "success": False,
            "reader_type": "browser",
            "content": "",
            "error": str(error)
        }

def read_page(url):
    headers = {
        "User-Agent": (
            "Mozilla/5.0 "
            "(Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 "
            "(KHTML, like Gecko) "
            "Chrome/151.0 Safari/537.36"
        )
    }

    try:
        response = requests.get(
            url,
            headers=headers,
            timeout=15
        )

        response.raise_for_status()

    except requests.RequestException as error:
        return {
            "success": False,
            "url": url,
            "reader_type": "browser_needed",
            "content": "",
            "error": str(error)
        }

    content_type = response.headers.get(
        "Content-Type",
        ""
    ).lower()

    # PDF
    if "application/pdf" in content_type:
        pdf_result = read_pdf(
            response.content
            )
        return {
            "success": pdf_result["success"],
            "url": url,
            "reader_type": "pdf",
            "content": pdf_result["content"],
            "error": pdf_result["error"]
        }

    # 非 HTML
    if "text/html" not in content_type:
        return {
            "success": False,
            "url": url,
            "reader_type": "unsupported",
            "content": "",
            "error": (
                "Unsupported content type: "
                + content_type
            )
        }

    soup = BeautifulSoup(
        response.text,
        "html.parser"
    )

    for tag in soup([
        "script",
        "style",
        "noscript",
        "nav",
        "footer"
    ]):
        tag.decompose()

    text = soup.get_text(
        separator="\n",
        strip=True
    )

    text = text[:15000]

    # 页面虽然返回 HTML，但内容太少
    if len(text) < 300:
        return {
            "success": False,
            "url": url,
            "reader_type": "browser_needed",
            "content": text,
            "error": (
                "HTML content too short; "
                "page may require JavaScript."
            )
        }

    return {
        "success": True,
        "url": url,
        "reader_type": "html",
        "content": text,
        "error": None
    }




def read_search_results(search_results):
    enriched_results = []

    for index, result in enumerate(
        search_results,
        start=1
    ):
        # -----------------------------------------
        # Level 1: HTML / PDF Reader
        # -----------------------------------------

        page = read_page(
            result["url"]
        )

        # -----------------------------------------
        # Level 2: Browser fallback
        # -----------------------------------------

        if (
            not page["success"]
            and page.get("reader_type")
            == "browser_needed"
        ):
            print(
                f"[BROWSER FALLBACK {index}]",
                result.get("domain")
            )

            browser_page = (
                read_page_with_browser(
                    result["url"]
                )
            )

            if browser_page["success"]:
                page = browser_page
            else:
                page = {
                    "success": False,
                    "url": result["url"],
                    "reader_type": "browser",
                    "content": browser_page.get("content", ""),
                    "error": browser_page.get(
                        "error",
                        "Browser fallback failed."
                    )
                }

        # -----------------------------------------
        # Save result
        # -----------------------------------------

        new_result = result.copy()

        new_result["page_success"] = (
            page["success"]
        )

        new_result["page_content"] = (
            page["content"]
        )

        new_result["page_error"] = (
            page["error"]
        )

        new_result["reader_type"] = (
            page["reader_type"]
        )

        print(
            f"[READ {index}]",
            result.get("domain"),
            "type=",
            page["reader_type"],
            "success=",
            page["success"],
            "length=",
            len(page["content"]),
            "error=",
            page["error"]
        )

        enriched_results.append(
            new_result
        )

    return enriched_results

def decide_document_mode(
    user_message
):
    decision = ai_decision(
        "prompts/document.txt",
        user_message
    )

    decision = decision.strip().upper()

    print(
        "[DOCUMENT MODE]",
        decision
    )

    if decision == "OVERVIEW":
        return "overview"

    return "retrieval"

if __name__ == "__main__":
    tests = [
        "这个文件说了些什么？",
        "这个文件是谁创建的？",
        "大概跟我说说这里面都是啥",
        "第7页主要写了什么？",
    ]
