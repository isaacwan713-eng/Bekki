import json
import os
import re
import social_browser
from datetime import datetime
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
import sys
import requests
import webbrowser
import time
from urllib.parse import quote, urlparse
from dotenv import load_dotenv
from io import BytesIO
from pypdf import PdfReader
from playwright.sync_api import sync_playwright

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

BRAVE_API_KEY = os.getenv("BRAVE_API_KEY")
BRAVE_SEARCH_URL = "https://api.search.brave.com/res/v1/web/search"
BRAVE_IMAGE_SEARCH_URL = "https://api.search.brave.com/res/v1/images/search"
OLLAMA_URL = "http://localhost:11434/api/generate"
MODEL_NAME = "gpt-oss:20b"
SEARCH_BUDGETS = (3, 5, 7, 10)


def _explicit_shopping_merchant(user_message, region=None):
    """Preserve a merchant explicitly named by the user as a hard constraint."""
    text = str(user_message).lower()
    country_code = str((region or {}).get("country_code", "")).upper()

    if "amazon" in text or "亚马逊" in text:
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
        return {
            "name": "Amazon",
            "domain": amazon_domains.get(country_code, "amazon.com"),
            "reason": "The user explicitly requested Amazon.",
        }

    named_merchants = (
        (("walmart", "沃尔玛"), "Walmart", "walmart.com"),
        (("target",), "Target", "target.com"),
        (("ebay",), "eBay", "ebay.com"),
        (("taobao", "淘宝"), "Taobao", "taobao.com"),
        (("tmall", "天猫"), "Tmall", "tmall.com"),
        (("jd.com", "京东"), "JD", "jd.com"),
    )
    for aliases, name, domain in named_merchants:
        if any(alias in text for alias in aliases):
            return {
                "name": name,
                "domain": domain,
                "reason": "The user explicitly requested this merchant.",
            }
    return None


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
    title_tokens = _image_match_tokens(clean_title)
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
        result_tokens = _image_match_tokens(result_title)
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
):
    payload = {
        "model": model_name or MODEL_NAME,
        "prompt": prompt,
        "stream": False,
        "think": think,
        "options": {
            "temperature": 0,
            "num_ctx": num_ctx,
            "num_predict": num_predict,
        },
    }

    response = requests.post(
        OLLAMA_URL,
        json=payload,
        timeout=180,
    )
    response.raise_for_status()

    data = response.json()

    print("DONE REASON:", data.get("done_reason"))
    print("THINKING:", repr(data.get("thinking", "")))
    print("RESPONSE:", repr(data.get("response", "")))

    return data.get("response", "").strip()

def unload_model(
    model_name=MODEL_NAME
):
    response = requests.post(
        OLLAMA_URL,
        json={
            "model": model_name,
            "keep_alive": 0,
        },
        timeout=30,
    )

    response.raise_for_status()

    print(
        "[MODEL UNLOADED]",
        model_name,
    )

def run_ai_prompt(
    prompt_path,
    input_text,
    expect_json=False,
    num_ctx=8192,
    num_predict=2048,
    think="low",
    model_name=None,
):
    with open(resource_path(prompt_path), "r", encoding="utf-8") as file:
        system_prompt = file.read()

    prompt = system_prompt + "\n\n" + input_text

    raw_output = call_model(
        prompt,
        num_ctx=num_ctx,
        num_predict=num_predict,
        think=think,
        model_name=model_name,
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
    # Device approvals are rendered with an explicit instruction to reply
    # "继续". Handle a small exact allowlist locally so a tiny confirmation
    # does not depend on a generative model finishing before its token limit.
    # This shortcut is intentionally unavailable without a stored approval.
    if pending and pending.get("type") == "device_action_approval":
        normalized = re.sub(r"[\s，。！？、,.!?]+", "", str(message)).lower()
        if normalized in {
            "继续",
            "继续吧",
            "确认",
            "确认执行",
            "执行",
            "同意",
            "可以",
            "是",
            "yes",
            "confirm",
            "continue",
            "proceed",
        }:
            print("CONFIRM: 'CONFIRM' [EXPLICIT DEVICE APPROVAL]")
            return True
    input_data = {
        "current_user_message": str(message),
        "pending_action": pending,
        "recent_conversation": str(recent_context)[-2000:],
    }
    decision = run_ai_prompt(
        "prompts/confirm.txt",
        json.dumps(input_data, ensure_ascii=False, indent=2),
        expect_json=False,
        num_ctx=2048,
        num_predict=24,
        think=False,
    )
    decision = str(decision).strip().upper()
    if decision not in {"CONFIRM", "NOT_CONFIRM"}:
        # A second AI judgment uses only the essential fields. Python detects
        # transport failure but does not infer confirmation from user wording.
        decision = run_ai_prompt(
            "prompts/confirm.txt",
            json.dumps(
                {
                    "current_user_message": str(message),
                    "pending_action": input_data["pending_action"],
                    "recent_conversation": "",
                },
                ensure_ascii=False,
            ),
            expect_json=False,
            num_ctx=1024,
            num_predict=24,
            think=False,
        )
        decision = str(decision).strip().upper()
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
    ).strip()

    print(
        "BUILT SEARCH QUERY:",
        repr(query)
    )

    return query or user_message


def build_news_queries(user_message, conversation_context=""):
    """Ask AI for complementary discovery queries for one news feed."""
    input_text = (
        "Current date:\n"
        + datetime.now().date().isoformat()
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
        queries = [user_message.strip()[:220]]
    print("[NEWS QUERIES]", json.dumps(queries, ensure_ascii=False))
    return queries


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
    ).strip()

    print("BUILT CLAIM QUERY:", repr(query))
    return query or claim


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
            num_predict=512
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


def build_shopping_plan(user_message, recent_context="", region=None):
    """Let AI preserve the user's shopping constraints and form search queries."""
    explicit_merchant = _explicit_shopping_merchant(user_message, region)
    memory_data = memory.initialize_memory()
    profile_context = memory.get_long_term_context(memory_data)
    conversation_state = context_manager.load_context()
    planning_input = (
        "Shopping region:\n"
        + json.dumps(region or {}, ensure_ascii=False, indent=2)
        + "\n\nRecent conversation:\n"
        + str(recent_context)[-5000:]
        + "\n\nResolved current conversation state:\n"
        + json.dumps(conversation_state, ensure_ascii=False, indent=2)[-4500:]
        + "\n\nLong-term user profile and preferences:\n"
        + str(profile_context)[-3500:]
        + "\n\nCurrent shopping request:\n"
        + str(user_message)
    )
    raw = run_ai_prompt(
        "prompts/shopping_query.txt",
        planning_input,
        expect_json=True,
        num_ctx=8192,
        num_predict=1800,
        think=False,
        model_name=MODEL_NAME,
    )

    if not isinstance(raw, dict):
        print("[SHOPPING PLAN RETRY] compact AI retry")
        raw = run_ai_prompt(
            "prompts/shopping_query_retry.txt",
            planning_input[-7500:],
            expect_json=True,
            num_ctx=8192,
            num_predict=1600,
            think=False,
            model_name=MODEL_NAME,
        )

    if not isinstance(raw, dict):
        raw = {}

    merchant_scope = str(raw.get("merchant_scope", "regional_mix")).lower().strip()
    if merchant_scope not in {"exclusive", "regional_mix"}:
        merchant_scope = "regional_mix"

    merchants = raw.get("merchants", [])
    if not isinstance(merchants, list):
        merchants = []
    clean_merchants = []
    seen_domains = set()
    for merchant in merchants[:4]:
        if not isinstance(merchant, dict):
            continue
        domain = str(merchant.get("domain", "")).lower().strip()
        domain = domain.removeprefix("www.").rstrip(".")
        if (
            not re.fullmatch(r"[a-z0-9.-]+\.[a-z]{2,}", domain)
            or domain in seen_domains
        ):
            continue
        seen_domains.add(domain)
        clean_merchants.append(
            {
                "name": str(merchant.get("name", "")).strip()[:80],
                "domain": domain,
                "reason": str(merchant.get("reason", "")).strip()[:220],
            }
        )
    if merchant_scope == "exclusive":
        clean_merchants = clean_merchants[:1]

    # An explicitly named website is a deterministic user constraint. The AI
    # still builds the semantic product query, but malformed AI output must not
    # silently erase the requested merchant and prevent search from starting.
    if explicit_merchant is not None:
        merchant_scope = "exclusive"
        clean_merchants = [explicit_merchant]

    queries = raw.get("queries", [])
    if not isinstance(queries, list):
        queries = []
    queries = [str(value).strip()[:220] for value in queries if str(value).strip()][:3]
    if not queries:
        queries = [str(user_message).strip()[:220]]

    # Keep the AI's progressive core -> compatibility -> value/popularity
    # queries intact. The user's raw sentence is context, not a merchant query;
    # inserting it here previously displaced the most useful third query.
    if len(queries) < 3:
        core_query = queries[0] if queries else str(user_message).strip()
        popular_query = (
            core_query
            + " best seller high review count trusted brand"
        )[:220]
        if popular_query not in queries:
            queries.append(popular_query)

    requirements = raw.get("requirements", [])
    if not isinstance(requirements, list):
        requirements = []
    requirements = [
        str(value).strip()[:100]
        for value in requirements
        if str(value).strip()
    ][:8]

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
        if not original or not search_value:
            continue
        clean_localized_constraints.append(
            {
                "kind": str(item.get("kind", "other")).strip()[:40],
                "original": original,
                "search_value": search_value,
                "display_value": display_value or original,
                "reason": str(item.get("reason", "")).strip()[:180],
            }
        )

    preference_profile = raw.get("preference_profile", {})
    if not isinstance(preference_profile, dict):
        preference_profile = {}
    allowed_profile_values = {
        "shopping_style": {"quality_first", "balanced", "value_first", "unknown"},
        "price_sensitivity": {"low", "medium", "high", "unknown"},
        "brand_strategy": {
            "premium_reliable", "trusted_value", "established_only", "balanced"
        },
    }
    clean_profile = {}
    for field, allowed in allowed_profile_values.items():
        value = str(preference_profile.get(field, "unknown")).lower().strip()
        clean_profile[field] = value if value in allowed else "unknown"
    clean_profile["reason"] = str(
        preference_profile.get("reason", "")
    ).strip()[:240]

    return {
        "merchant_scope": merchant_scope,
        "merchants": clean_merchants,
        "queries": queries,
        "requirements": requirements,
        "localized_constraints": clean_localized_constraints,
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
    "xiaohongshu": "小红书",
    "instagram": "Instagram",
    "x": "X (formerly Twitter)",
}


def build_social_query(user_message, platforms):
    raw_result = run_ai_prompt(
        "prompts/social_query.txt",
        json.dumps(
            {
                "user_message": user_message,
                "platforms": platforms,
            },
            ensure_ascii=False,
        ),
        expect_json=True,
        num_ctx=2048,
        num_predict=120,
        think=False,
        model_name="llama3.2:latest",
        )
    

    if isinstance(raw_result, dict):
        query = str(raw_result.get("query", "")).strip()
        if query:
            return query[:160]

    return user_message.strip()[:160]

def extract_social_evidence(
    page_text,
    recency_days=7,
):
    """Keep only recent, visible, unverified social discussion items."""

    current_date = datetime.now().date().isoformat()

    input_text = (
        "Current date: " + current_date
        + "\nRequested recency window: "
        + str(recency_days)
        + " days\n\nVisible social-page text:\n"
        + page_text[:18000]
    )

    evidence = run_ai_prompt(
        "prompts/social_extract.txt",
        input_text,
        expect_json=True,
        num_ctx=8192,
        num_predict=1400,
        think=False,
        model_name="llama3.2:latest",
    )
    print(
        "[SOCIAL EVIDENCE]",
        json.dumps(
            evidence,
            ensure_ascii=False,
            indent=2,
        ),
    )

    if not isinstance(evidence, dict):
        return {
            "page_summary": "",
            "recent_post_count": 0,
            "items": [],
            "excluded_count": 0,
            "warnings": [
                "页面内容无法被可靠地结构化提取。",
            ],
        }

    items = evidence.get("items", [])
    if not isinstance(items, list):
        items = []

    try:
        recent_post_count = max(
            int(evidence.get("recent_post_count", 0) or 0),
            0,
        )
    except (TypeError, ValueError):
        recent_post_count = 0

    try:
        excluded_count = max(
            int(evidence.get("excluded_count", 0) or 0),
            0,
        )
    except (TypeError, ValueError):
        excluded_count = 0

    warnings = evidence.get("warnings", [])
    if not isinstance(warnings, list):
        warnings = []

    return {
        "page_summary": str(
            evidence.get("page_summary", "")
        )[:700],
        "recent_post_count": recent_post_count,
        "items": items[:5],
        "excluded_count": excluded_count,
        "warnings": warnings[:4],
    }

def social_research_controller(
    user_message,
    platforms,
    status_callback=None,
    recency_days=7,
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
    query = build_social_query(user_message, platforms)
    print("[SOCIAL QUERY]", platforms, repr(query))

    page_texts = []
    results = []

    for platform in platforms:
        _status(
            status_callback,
            "正在搜索 "
            + SOCIAL_PLATFORM_NAMES[platform]
            + "… 🔎",
        )

        try:
            opened = social_browser.open_social_search(
                platform,
                query,
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
    social_browser.close_social_browser()
    if not page_texts:
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
        recency_days=recency_days,)

    context = (
        "MELCHIOR response mode: SOCIAL_RESEARCH\n"
        "This is filtered visible discussion from a user-authorized"
        "social-media search page.\n"
        "The requested time window is the last "
        + str(recency_days)
        + " days.\n"
        "Describe only what people are discussing.\n"
        "Social posts and rumors are not confirmed facts.\n"
        "Do not use prior conversation as evidence.\n\n"
        "Filtered social evidence:\n"
        + json.dumps(evidence,ensure_ascii=False,indent=2,)
    )

    return {
        "status": "OK",
        "query": query,
        "results": results,
        "context": context,
    }



def search_controller(query, status_callback=None):
    """Orchestrates search. AI judges meaning; Python controls the flow."""

    # =====================================================
    # 1. Search
    # =====================================================

    _status(
        status_callback,
        "正在搜索… 🔍"
    )

    search_results = search(
        query,
        count=max(SEARCH_BUDGETS)
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


    for budget in SEARCH_BUDGETS:

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
    try:
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(
                headless=True
            )

            context = browser.new_context(
                user_agent=(
                    "Mozilla/5.0 "
                    "(Windows NT 10.0; Win64; x64) "
                    "AppleWebKit/537.36 "
                    "(KHTML, like Gecko) "
                    "Chrome/151.0 Safari/537.36"
                    ),
            viewport = {
                "width": 1280,
                "height": 900
            }
            )

            page = context.new_page()

            page.goto(
                url,
                wait_until="networkidle",
                timeout=30000
            )

            page.wait_for_timeout(1500)

            # Amazon sometimes presents a normal Continue shopping interstitial
            # before the product page. It is not a CAPTCHA; follow the visible
            # navigation once, then read the resulting product page.
            if "amazon." in urlparse(url).netloc.lower():
                continue_controls = page.get_by_text(
                    "Continue shopping",
                    exact=True,
                )
                if continue_controls.count() > 0:
                    try:
                        continue_controls.first.click(timeout=5000)
                        page.wait_for_load_state("domcontentloaded", timeout=15000)
                        page.wait_for_timeout(1800)
                    except Exception as continue_error:
                        print(
                            "[AMAZON CONTINUE FAILED]",
                            repr(continue_error),
                        )

            text = page.locator(
                "body"
            ).inner_text()

            browser.close()

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


