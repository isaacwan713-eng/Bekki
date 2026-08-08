import os
import json
import requests
from dotenv import load_dotenv
from urllib.parse import urlparse

load_dotenv()

BRAVE_API_KEY = os.getenv("BRAVE_API_KEY")

BRAVE_SEARCH_URL = "https://api.search.brave.com/res/v1/web/search"
OLLAMA_URL = "http://localhost:11434/api/generate"

MODEL_NAME = "gpt-oss:20b"


def get_domain(url):

    return urlparse(url).netloc.lower().replace("www.", "")



def search(query):
    if not BRAVE_API_KEY:
        return "Search failed: BRAVE_API_KEY is missing."

    headers = {
        "Accept": "application/json",
        "Accept-Encoding": "gzip",
        "X-Subscription-Token": BRAVE_API_KEY,
    }

    params = {
        "q": query,
        "count": 5,
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
        title = result.get("title", "No title")
        description = result.get("description", "No description")
        url = result.get("url", "")
        domain = get_domain(url)

        search_results.append({
            "title": title,
            "description": description,
            "url": url,
            "domain": domain,
        })

    return search_results


def score_sources(query, search_results):
    if not search_results:
        return []

    source_text = ""

    for index, result in enumerate(
        search_results,
        start=1
    ):
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
        num_predict=1024
    )
    print("\n===== SOURCE SCORE RAW =====")
    print(result)
    print("============================\n")

    if result is None:
        return search_results

    scores = result.get(
        "scores",
        []
    )

    for score_item in scores:
        index = score_item.get("index")

        if not isinstance(index, int):
            continue

        if (
            index < 1
            or index > len(search_results)
        ):
            continue

        search_results[index - 1][
            "source_score"
        ] = score_item.get(
            "score",
            50
        )

        search_results[index - 1][
            "source_reason"
        ] = score_item.get(
            "reason",
            ""
        )

    for search_result in search_results:
        if "source_score" not in search_result:
            search_result["source_score"] = 50
            search_result["source_reason"] = (
                "No AI score returned."
            )

    search_results.sort(
        key=lambda item: item[
            "source_score"
        ],
        reverse=True
    )
    print("\n===== SOURCE SCORE FINAL =====")

    for item in search_results:
        print(
            item.get("source_score"),
            item.get("title")
        )

    print("==============================\n")

    return search_results

def call_model(
    prompt,
    num_ctx=8192,
    num_predict=2048
):
    payload = {
        "model": "gpt-oss:20b",
        "prompt": prompt,
        "stream": False,
        "think": "low",
        "options": {
            "temperature": 0,
            "num_ctx": num_ctx,
            "num_predict": num_predict
        }
    }

    response = requests.post(
        OLLAMA_URL,
        json=payload,
        timeout=180
    )

    response.raise_for_status()

    data = response.json()

    print("DONE REASON:", data.get("done_reason"))
    print("THINKING:", repr(data.get("thinking", "")))
    print("RESPONSE:", repr(data.get("response", "")))

    return data.get("response", "").strip()

def run_ai_prompt(
    prompt_path,
    input_text,
    expect_json=False,
    num_ctx=8192,
    num_predict=2048
):
    with open(
        prompt_path,
        "r",
        encoding="utf-8"
    ) as file:
        system_prompt = file.read()

    prompt = (
        system_prompt
        + "\n\n"
        + input_text
    )

    raw_output = call_model(
        prompt,
        num_ctx=num_ctx,
        num_predict=num_predict
    )

    if not expect_json:
        return raw_output.strip()

    try:
        return json.loads(raw_output)

    except json.JSONDecodeError as error:
        print(
            "AI JSON ERROR:",
            prompt_path,
            error
        )

        print(
            "BROKEN OUTPUT:",
            repr(raw_output)
        )

        return None

def ai_decision(prompt_path, user_message):
    with open(
        prompt_path,
        "r",
        encoding="utf-8",
    ) as file:
        router_prompt = file.read()

    prompt = (
        router_prompt
        + "\n\nUser:\n"
        + user_message
    )

    raw_decision = call_model(
        prompt
    )
    print("FINAL PROMPT LENGTH:", len(prompt))
    return raw_decision.strip().upper()



def should_search(user_message):
    decision = ai_decision(
        "prompts/search.txt",
        user_message,
    )

    print("SEARCH:", repr(decision))

    # 容忍模型输出：
    # SEARCH
    # SEARCH\n
    # SEARCH - current information is required
    return decision.startswith("SEARCH")


def is_confirmation(message):
    decision = ai_decision(
        "prompts/confirm.txt",
        message,
    )

    print("CONFIRM:", repr(decision))

    return decision.startswith("CONFIRM")


def decide_tools(message):
    if should_search(message):
        return "search"

    return "chat"

def build_search_query(user_message):
    with open(
        "prompts/search_query.txt",
        "r",
        encoding="utf-8"
    ) as file:
        query_prompt = file.read()

    prompt = (
        query_prompt
        + "\n\nCurrent date: 2026-08-06"
        + "\n\nUser:\n"
        + user_message
    )

    query = call_model(prompt).strip()

    print("BUILT SEARCH QUERY:", repr(query))

    if not query:
        return user_message

    return query

def format_search_results(search_results):

    if not search_results:
        return "No search results found."

    search_text = ""

    for index, result in enumerate(search_results, start=1):

        search_text += (
            f"{index}. {result['title']}\n"
            f"{result['description']}\n"
            f"Source: {result['url']}\n\n"
        )

    return search_text


def extract_answers(
    query,
    search_results
):
    if not search_results:
        return []

    source_text = ""

    for index, result in enumerate(
        search_results,
        start=1
    ):
        source_text += (
            f"\nSource {index}\n"
            f"Title: {result['title']}\n"
            f"Description: {result['description']}\n"
            f"URL: {result['url']}\n"
            f"Domain: {result['domain']}\n"
            f"Source Score: {result.get('source_score', 50)}\n"
        )

    input_text = (
        "User question:\n"
        + query
        + "\n\nSearch results:\n"
        + source_text
    )

    result = run_ai_prompt(
        "prompts/extract.txt",
        input_text,
        expect_json=True,
        num_ctx=8192,
        num_predict=1024
    )

    print("\n===== EXTRACT RAW =====")
    print(result)
    print("=======================\n")

    if result is None:
        return []

    answers = result.get(
        "answers",
        []
    )

    return answers

def find_consensus(query, answers):

    input_text = (
        "User question:\n"
        + query
        + "\n\nExtracted answers:\n"
        + json.dumps(
            answers,
            ensure_ascii=False,
            indent=2
        )
    )

    result = run_ai_prompt(
        "prompts/consensus.txt",
        input_text,
        expect_json=True,
        num_ctx=4096,
        num_predict=512
    )

    if result is None:
        return {
            "consensus": False,
            "canonical_answer": None,
            "votes": 0,
            "need_more_sources": True,
            "reason": "Consensus AI failed."
        }

    return result