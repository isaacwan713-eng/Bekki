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

def call_model(prompt):
    url = "http://localhost:11434/api/generate"
    payload = {
            "model" : "gpt-oss:20b",
            "prompt" : prompt,
            "stream" : False,
            "options" : {
                "temperature" : 0
            }
    }

    response = requests.post(url,json = payload)

    return response.json()["response"]

def  ai_decision(prompt_path,user_message):
    with open(prompt_path,"r",encoding= "utf-8") as file:
        system_prompt = file.read()

    prompt = (system_prompt + "\n\nUser:\n" + user_message)

    raw_decision = call_model(prompt)
    return raw_decision.strip().upper()



def should_search(user_message):
    decision = ai_decision("prompts/search.txt",user_message)

    print("SEARCH",decision)

    return decision == "SEARCH"

def is_confirmation(message):

    decision = ai_decision("prompts/confirm.txt",message)
    print("CONFIRM" , decision)

    return decision == "CONFIRM"  

def decide_tools(message):
    if should_search(message):
        return "search"

    return "chat"    
