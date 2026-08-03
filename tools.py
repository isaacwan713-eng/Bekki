import os

import requests

from dotenv import load_dotenv


load_dotenv()

BRAVE_API_KEY = os.getenv("BRAVE_API_KEY")
BRAVE_SEARCH_URL = "https://api.search.brave.com/res/v1/web/search"
OLLAMA_URL = "http://localhost:11434/api/generate"


def search(query):
    if not BRAVE_API_KEY:
        return "Search failed: BRAVE_API_KEY is missing."

    headers = {
        "Accept": "application/json",
        "Accept-Encoding": "gzip",
        "X-Subscription-Token": BRAVE_API_KEY
    }

    params = {
        "q": query,
        "count": 5
    }

    try:
        response = requests.get(
            BRAVE_SEARCH_URL,
            headers=headers,
            params=params,
            timeout=15
        )
        response.raise_for_status()
        data = response.json()

    except requests.RequestException as error:
        return f"Search failed: {error}"

    results = data.get("web", {}).get("results", [])

    if not results:
        return "No search results found."

    search_text = "Current Search Results:\n\n"

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


def should_search(user_message):
    with open("prompts/search.txt","r",encoding= "UTF-8") as file:
        search_prompt = file.read()
        #print(search_prompt[:30])
        #print(file.name)

    #print(repr(search_prompt))

    prompt = (search_prompt + "\n\nUser:|n"+user_message)
    #print(repr(prompt))

    payload = {
        "model" : "gpt-oss:20b",
        "prompt" : prompt,
        "stream" : False,
        "options" : {
            "temperature" : 0
        }
    }
    #print("====ROUTER PROMPT====")
    #print(prompt)
    #print("=====================")
    response = requests.post(OLLAMA_URL,json = payload)
    #decision = response.json()["response"].strip().upper()
    raw_decision = response.json()["response"]
    #print(repr(raw_decision))
    decision = raw_decision.strip().upper()

    print(decision)

    return decision == "SEARCH"