import json
import os
import re
from datetime import datetime
from urllib.parse import urlparse
from bs4 import BeautifulSoup
from urllib.parse import urlparse
import context as context_manager
import memory
import document
import vision
import sys
import requests
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
OLLAMA_URL = "http://localhost:11434/api/generate"
MODEL_NAME = "gpt-oss:20b"
SEARCH_BUDGETS = (3, 5, 7, 10)


def get_domain(url):
    return urlparse(url).netloc.lower().replace("www.", "")


def search(query, count=5):
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
            }
        )

    return search_results


def call_model(prompt, num_ctx=8192, num_predict=2048):
    payload = {
        "model": MODEL_NAME,
        "prompt": prompt,
        "stream": False,
        "think": "low",
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
):
    with open(resource_path(prompt_path), "r", encoding="utf-8") as file:
        system_prompt = file.read()

    prompt = system_prompt + "\n\n" + input_text

    raw_output = call_model(
        prompt,
        num_ctx=num_ctx,
        num_predict=num_predict,
    )

    if not expect_json:
        return raw_output.strip()

    try:
        return json.loads(raw_output)
    except json.JSONDecodeError as error:
        print("AI JSON ERROR:", prompt_path, error)
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


def is_confirmation(message):
    decision = ai_decision("prompts/confirm.txt", message)
    print("CONFIRM:", repr(decision))
    return decision.startswith("CONFIRM")


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
        }
        for item in results
    ]

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

        item["is_concrete_news"] = bool(
            decision.get("is_concrete_news", False)
        )
        item["content_type"] = str(
            decision.get("content_type", "OTHER")
        )

        try:
            item["news_score"] = max(
                0,
                min(100, int(decision.get("news_score", 0))),
            )
        except (TypeError, ValueError):
            item["news_score"] = 0

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


def news_feed_controller(query, status_callback=None):
    """Return a weighted current-news feed. Never run 3→5→7 here."""
    _status(status_callback, "正在搜索新闻… 🔍")
    search_results = search(query, count=10)

    if not isinstance(search_results, list):
        return {
            "status": "ERROR",
            "query": query,
            "context": "News search failed: " + str(search_results),
        }

    if not search_results:
        return {
            "status": "NO_RESULTS",
            "query": query,
            "context": "No current news results were found for: " + query,
        }

    _status(status_callback, "正在按来源排序… 📚")
    scored_results = score_sources(query, search_results)
    ranked_results = _deduplicate_headlines(rank_news_results(query, scored_results))

    feed_items = _source_summary(ranked_results)
    context = (
        "MAGI response mode: NEWS_FEED\n"
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
        "query": query,
        "results": ranked_results,
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
        "MAGI response mode: FACT_LOOKUP\n"
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


