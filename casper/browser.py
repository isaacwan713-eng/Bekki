"""Casper-managed background browser for public web research."""

import os
import base64
import socket
import subprocess
import sys
import time
import json
import re
from datetime import datetime
from pathlib import Path
from urllib.parse import parse_qs, quote, unquote, urlparse


CDP_PORT = 9224
CDP_URL = f"http://127.0.0.1:{CDP_PORT}"
MAX_PAGE_TEXT = 15000
_browser_process = None


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


def _clean_result(title, description, url):
    url = _unwrap_bing_url(url)
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
    return {
        "scope_type": str(result["scope_type"]).upper().strip(),
        "requested_period": result["requested_period"].strip()[:240],
        "allow_previous_period": result["allow_previous_period"],
        "reason": result["reason"].strip()[:400],
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
                "page_content": str(item.get("page_content", ""))[:1800],
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
        num_ctx=16384,
        num_predict=420,
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
            num_ctx=16384,
            num_predict=420,
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
                "page_content": str(item.get("page_content", ""))[:1200],
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
        num_ctx=16384,
        num_predict=500,
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


def search_web(query, count=7):
    """Discover public results through the managed browser, not Brave API."""
    from playwright.sync_api import (
        sync_playwright,
        TimeoutError,
        Error as PlaywrightError,
    )

    ensure_browser()
    target = "https://www.bing.com/search?q=" + quote(str(query))

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
            cards = page.locator("li.b_algo")
            for index in range(min(cards.count(), max(int(count), 1) * 2)):
                card = cards.nth(index)
                link = card.locator("h2 a").first
                if link.count() == 0:
                    continue
                url = link.get_attribute("href") or ""
                title = link.inner_text(timeout=3000)
                snippets = card.locator(".b_caption p")
                description = (
                    snippets.first.inner_text(timeout=3000)
                    if snippets.count()
                    else ""
                )
                item = _clean_result(title, description, url)
                if not item or item["url"] in seen:
                    continue
                seen.add(item["url"])
                results.append(item)
                if len(results) >= count:
                    break
            return {"status": "OK" if results else "NO_RESULTS", "results": results}
        finally:
            page.close()


def discover_web(
    query,
    count=7,
    status_callback=None,
    allowed_domains=None,
):
    """Discover URLs; any Brave use is URL discovery only."""
    result = search_web(query, count=count)
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

    browser_results = [
        item for item in result.get("results", [])
        if isinstance(item, dict) and in_scope(item)
    ]
    if result.get("status") == "HUMAN_HANDOFF":
        result["discovery_type"] = "casper_browser"
        return result
    if browser_results:
        result["results"] = browser_results[: max(int(count), 1)]
        result["status"] = "OK"
        result["discovery_type"] = "casper_browser"
        return result

    import tools

    _status(
        status_callback,
        "后台浏览器未发现候选链接，正在使用备用发现通道… 🔄",
    )
    print("[CASPER DISCOVERY FALLBACK]", repr(str(query)[:240]))
    found = tools.search(query, count=count)
    if not isinstance(found, list):
        return {
            "status": "NO_RESULTS",
            "results": [],
            "discovery_type": "none",
        }
    fallback_results = [
        item for item in found
        if isinstance(item, dict) and in_scope(item)
    ]
    return {
        "status": "OK" if fallback_results else "NO_RESULTS",
        "results": fallback_results[: max(int(count), 1)],
        "discovery_type": "brave_url_discovery_only",
    }


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
                "page_content": str(item.get("page_content", ""))[:6500],
            }
            for index, item in enumerate(articles[:12], start=1)
        ],
    }
    result = tools.run_ai_prompt(
        "prompts/casper_news_extract.txt",
        json.dumps(packet, ensure_ascii=False, indent=2),
        expect_json=True,
        num_ctx=32768,
        num_predict=2400,
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
        content_type = str(value.get("content_type", "OTHER")).upper().strip()
        concrete = value.get("is_concrete_news") is True
        if content_type not in {
            "NEWS", "AGGREGATOR", "TEAM_PAGE", "SCHEDULE", "ROSTER",
            "BACKGROUND", "OTHER",
        }:
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
    if len(decisions) != len(packet["articles"]):
        return None
    return decisions


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
        num_ctx=16384,
        num_predict=900,
    )
    selected = result.get("selected") if isinstance(result, dict) else None
    if not isinstance(selected, list):
        return None
    valid_indices = {item["source_index"] for item in candidates}
    output = []
    seen = set()
    for value in selected:
        if not isinstance(value, dict):
            continue
        try:
            index = int(value.get("source_index"))
        except (TypeError, ValueError):
            continue
        if index not in valid_indices or index in seen:
            continue
        seen.add(index)
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
    scored = tools.score_sources(" | ".join(queries), all_candidates)[:12]
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
        decision = decisions[index]
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
            }
        )

    _status(status_callback, "Casper 正在合并重复事件并排序… 📚")
    selected = _curate_news_feed(user_request or " | ".join(queries), articles)
    if selected is None:
        selected = []
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
        num_ctx=32768,
        num_predict=3600,
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
        popularity = value.get("popularity", {})
        if not isinstance(popularity, dict):
            popularity = {}
        popularity_status = str(popularity.get("status", "UNKNOWN")).upper().strip()
        if popularity_status not in {"HIGH", "MEDIUM", "LOW", "UNKNOWN"}:
            popularity_status = "UNKNOWN"
        output[index] = {
            "page_type": page_type,
            "title": str(value.get("title", "")).strip()[:240],
            "summary": str(value.get("summary", "")).strip()[:900],
            "merchant": str(value.get("merchant", "")).strip()[:100],
            "price": str(value.get("price", "")).strip()[:80],
            "currency": str(value.get("currency", "")).strip()[:20],
            "stock": str(value.get("stock", "")).strip()[:100],
            "brand": str(value.get("brand", "")).strip()[:100],
            "rating": str(value.get("rating", "")).strip()[:60],
            "review_count": str(value.get("review_count", "")).strip()[:60],
            "popularity_status": popularity_status,
            "popularity_evidence": str(popularity.get("evidence", "")).strip()[:300],
            "requirements": clean_rows,
            "fit_score": max(0, min(100, fit_score)),
            "evidence_quality": str(value.get("evidence_quality", "LOW")).upper().strip(),
            "reason": str(value.get("reason", "")).strip()[:500],
        }
    if len(output) != len(packet["candidates"]):
        return None
    return output


def _extract_shopping_products(user_request, plan, region, candidates):
    """Extract each rendered product independently to avoid batch truncation."""
    output = {}
    for index, candidate in enumerate(candidates[:8], start=1):
        decision = _extract_shopping_products_batch(
            user_request,
            plan,
            region,
            [candidate],
        )
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


def _select_shopping_products(user_request, plan, products):
    """Let AI choose up to three distinct products for comparison."""
    import tools

    candidates = [
        {
            "source_index": index,
            "title": item.get("product_title", ""),
            "summary": item.get("product_summary", ""),
            "merchant": item.get("merchant", ""),
            "domain": item.get("domain", ""),
            "price": item.get("price", ""),
            "currency": item.get("currency", ""),
            "stock": item.get("stock", ""),
            "brand": item.get("brand", ""),
            "rating": item.get("rating", ""),
            "review_count": item.get("review_count", ""),
            "popularity_status": item.get("popularity_status", "UNKNOWN"),
            "popularity_evidence": item.get("popularity_evidence", ""),
            "requirements": item.get("requirements", []),
            "fit_score": item.get("fit_score", 0),
            "source_score": item.get("source_score", 50),
            "evidence_quality": item.get("evidence_quality", "LOW"),
            "has_product_image": bool(item.get("image_url")),
            "is_product_detail_url": bool(item.get("is_product_detail_url")),
        }
        for index, item in enumerate(products, start=1)
        if item.get("page_type") == "PRODUCT"
    ]
    if not candidates:
        return []
    result = tools.run_ai_prompt(
        "prompts/casper_shopping_select.txt",
        json.dumps(
            {
                "original_user_request": str(user_request),
                "requirements": plan.get("requirements", []),
                "preference_profile": plan.get("preference_profile", {}),
                "candidates": candidates,
            },
            ensure_ascii=False,
            indent=2,
        ),
        expect_json=True,
        num_ctx=16384,
        num_predict=1000,
    )
    selected = result.get("selected") if isinstance(result, dict) else None
    if not isinstance(selected, list):
        return None
    valid = {item["source_index"] for item in candidates}
    output = []
    seen = set()
    for value in selected:
        if not isinstance(value, dict):
            continue
        try:
            index = int(value.get("source_index"))
        except (TypeError, ValueError):
            continue
        if index in valid and index not in seen:
            seen.add(index)
            output.append(index)
        if len(output) >= 3:
            break
    return output


def _discover_shopping_merchants(user_request, plan, region, status_callback=None):
    """Let AI choose merchants only from domains Casper actually discovered."""
    import tools

    queries = plan.get("queries", [])
    core_query = queries[0] if queries else str(user_request)
    country = str(region.get("country_name", "") or region.get("country_code", ""))
    discovery_query = (core_query + " buy online " + country).strip()[:240]
    discovery = discover_web(
        discovery_query,
        count=12,
        status_callback=status_callback,
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

    result = tools.run_ai_prompt(
        "prompts/casper_shopping_merchants.txt",
        json.dumps(
            {
                "shopping_region": region,
                "original_user_request": str(user_request),
                "shopping_plan": plan,
                "discovered_sources": sources,
            },
            ensure_ascii=False,
            indent=2,
        ),
        expect_json=True,
        num_ctx=8192,
        num_predict=900,
    )
    selected = result.get("merchants") if isinstance(result, dict) else None
    if not isinstance(selected, list):
        return {"status": "INVALID_AI_CONTRACT", "merchants": []}

    by_index = {item["index"]: item for item in sources}
    merchants = []
    selected_domains = set()
    for value in selected[:4]:
        if not isinstance(value, dict):
            continue
        try:
            source_index = int(value.get("source_index"))
        except (TypeError, ValueError):
            continue
        source = by_index.get(source_index)
        if source is None or source["domain"] in selected_domains:
            continue
        selected_domains.add(source["domain"])
        merchants.append(
            {
                "name": str(value.get("name", "")).strip()[:80] or source["domain"],
                "domain": source["domain"],
                "reason": str(value.get("reason", "")).strip()[:220],
            }
        )
    return {
        "status": "OK" if merchants else "NO_VERIFIED_MERCHANTS",
        "merchants": merchants,
        "discovery_query": discovery_query,
        "discovered_sources": sources,
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
    region = shopping_region.detect_shopping_region()
    plan = tools.build_shopping_plan(user_request, recent_context, region)
    merchants = plan.get("merchants", [])
    if plan.get("merchant_scope") != "exclusive":
        _status(status_callback, "Casper 正在确认本地区真实商家… 🧭")
        merchant_discovery = _discover_shopping_merchants(
            user_request,
            plan,
            region,
            status_callback=status_callback,
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
    queries = plan.get("queries", [])
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
    # Interleave merchants so one blocked or noisy domain cannot consume the
    # entire candidate budget before the other AI-selected sources are tried.
    for query in queries[:3]:
        for domain in merchant_domains:
            scoped_queries.append(
                {
                    "domain": domain,
                    "query": _merchant_discovery_query(domain, query),
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
    for scoped in scoped_queries:
        discovery = discover_web(
            scoped["query"],
            count=5,
            status_callback=status_callback,
            allowed_domains=[scoped["domain"]],
        )
        print(
            "[CASPER SHOPPING DISCOVERY]",
            scoped["domain"],
            discovery.get("discovery_type", ""),
            "results=" + str(len(discovery.get("results", []))),
        )
        if discovery.get("status") == "HUMAN_HANDOFF":
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
        for item in discovery.get("results", []):
            url = item.get("url", "")
            domain = str(item.get("domain", "")).lower().strip()
            allowed = any(
                domain == merchant or domain.endswith("." + merchant)
                for merchant in merchant_domains
            )
            product_url = _merchant_product_url(scoped["domain"], url)
            scoped_domain = scoped["domain"]
            if (
                url
                and allowed
                and product_url
                and url not in seen_urls
                and domain_counts.get(scoped_domain, 0) < 4
            ):
                seen_urls.add(url)
                item["is_product_detail_url"] = True
                discovered.append(item)
                domain_counts[scoped_domain] = domain_counts.get(scoped_domain, 0) + 1
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
    scored = tools.score_sources(user_request, discovered)[:12]
    products = []
    for candidate in scored:
        page = read_url(candidate.get("url", ""))
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
        if protected_event == "captcha" or exclusive_handoff:
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
        enriched = dict(candidate)
        final_url = page.get("final_url", "") or candidate.get("url", "")
        final_is_product = _merchant_product_url(
            candidate.get("domain", ""),
            final_url,
        )
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
        ):
            validated_products.append(product)

    products = validated_products

    _status(status_callback, "Casper 正在挑选三个可比较方案… ⚖️")
    selected = _select_shopping_products(user_request, plan, products)
    if selected is None:
        selected = []
    chosen = [products[index - 1] for index in selected]
    cards = result_cards.clean_cards(
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
                    "captured_at": datetime.now().astimezone().isoformat(),
                },
                "requirements": item.get("requirements", []),
            }
            for item in chosen
        ]
    )

    options = []
    for index, (card, item) in enumerate(zip(cards, chosen), start=1):
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
    comparison = decision_comparison.compare_options(
        options,
        plan.get("requirements", []),
        lambda prompt, input_text: tools.run_ai_prompt(
            prompt,
            input_text,
            expect_json=True,
            num_ctx=8192,
            num_predict=1400,
        ),
        preference_profile=plan.get("preference_profile", {}),
    )
    comparison_context = decision_comparison.prompt_context(
        comparison,
        {option["option_id"]: option["title"] for option in options},
    )
    print("[CASPER SHOPPING]", len(cards), "product cards")
    return {
        "status": "OK" if cards else "NO_VERIFIED_PRODUCTS",
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
        "context": (
            "melchior response mode: SHOPPING_RESEARCH\n"
            "Casper read the selected merchant product pages. Product links are "
            "owned by the card buttons; do not print raw URLs. Compare every "
            "card, preserve UNKNOWN evidence, and use the validated comparison.\n\n"
            "Product cards:\n"
            + json.dumps(cards, ensure_ascii=False, indent=2)
            + "\n\n"
            + comparison_context
        ),
        "discovery_type": "casper_browser",
    }


def fact_lookup_controller(query, user_request="", status_callback=None):
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
