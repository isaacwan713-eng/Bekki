import os

import requests
from dotenv import load_dotenv


load_dotenv()

BRAVE_API_KEY = os.getenv("BRAVE_API_KEY")

BRAVE_SEARCH_URL = "https://api.search.brave.com/res/v1/web/search"
OLLAMA_URL = "http://localhost:11434/api/generate"

MODEL_NAME = "gpt-oss:20b"


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
        return "No search results found."

    # 不需要在这里再写 Current Search Results，
    # 因为 main.py 的 get_ai_response() 已经会加标题。
    search_text = ""

    for index, result in enumerate(results, start=1):
        title = result.get("title", "No title")
        description = result.get("description", "No description")
        url = result.get("url", "")

        search_text += (
            f"{index}. {title}\n"
            f"{description}\n"
            f"Source: {url}\n\n"
        )

    return search_text


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