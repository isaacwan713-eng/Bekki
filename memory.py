import json
import os
from datetime import datetime, timedelta


DATA_FOLDER = "data"
TEMPORARY_FILE = os.path.join(DATA_FOLDER, "temporary.json")
TASK_FILE = os.path.join(DATA_FOLDER, "task.json")
PROFILE_FILE = os.path.join(DATA_FOLDER, "profile.json")
PENDING_FILE = os.path.join(DATA_FOLDER, "pending.json")


def create_json_file(file_path, default_data):
    if not os.path.exists(file_path):
        with open(file_path, "w", encoding="utf-8") as file:
            json.dump(default_data, file, ensure_ascii=False, indent=4)


def load_json_file(file_path, default_data=None):
    try:
        with open(file_path, "r", encoding="utf-8") as file:
            return json.load(file)
    except (FileNotFoundError, json.JSONDecodeError):
        return default_data


def save_json_file(file_path, data):
    with open(file_path, "w", encoding="utf-8") as file:
        json.dump(data, file, ensure_ascii=False, indent=4)


def initialize_memory():
    os.makedirs(DATA_FOLDER, exist_ok=True)

    create_json_file(TEMPORARY_FILE, [])
    create_json_file(TASK_FILE, [])
    create_json_file(
        PROFILE_FILE,
        {
            "profile": {},
            "preference": {},
            "relationships": {},
        },
    )
    create_json_file(PENDING_FILE, {})

    memory_data = {
        "temporary": load_json_file(TEMPORARY_FILE, []),
        "tasks": load_json_file(TASK_FILE, []),
        "profile": load_json_file(
            PROFILE_FILE,
            {
                "profile": {},
                "preference": {},
                "relationships": {},
            },
        ),
    }

    clean_expired_temporary(memory_data)
    return memory_data


def add_temporary(memory_data, content):
    created_at = datetime.now()
    expires_at = created_at + timedelta(hours=24)

    new_memory = {
        "content": content,
        "created_at": created_at.isoformat(),
        "expires_at": expires_at.isoformat(),
    }

    memory_data["temporary"].append(new_memory)
    save_json_file(TEMPORARY_FILE, memory_data["temporary"])


def handle_memory(memory_data, memory_info):
    if not memory_info or not isinstance(memory_info, dict):
        return

    if memory_info.get("type") != "temporary":
        return

    new_content = memory_info.get("content")
    if not new_content:
        return

    for existing_memory in memory_data["temporary"]:
        if existing_memory.get("content") == new_content:
            return

    add_temporary(memory_data, new_content)


def clean_expired_temporary(memory_data):
    current_time = datetime.now()
    valid_memories = []

    for item in memory_data.get("temporary", []):
        expires_at_text = item.get("expires_at")
        if not expires_at_text:
            continue

        try:
            expires_at = datetime.fromisoformat(expires_at_text)
        except ValueError:
            continue

        if expires_at > current_time:
            valid_memories.append(item)

    memory_data["temporary"] = valid_memories
    save_json_file(TEMPORARY_FILE, valid_memories)


def get_temporary_context(memory_data):
    memories = memory_data.get("temporary", [])

    if not memories:
        return "Current Temporary Memory:\n\nNone"

    lines = ["Current Temporary Memory:", ""]
    lines.extend(
        f"- {item.get('content', '')}"
        for item in memories
        if item.get("content")
    )
    return "\n".join(lines)


def save_pending_action(action):
    os.makedirs(DATA_FOLDER, exist_ok=True)
    save_json_file(PENDING_FILE, action or {})


def loading_pending_action():
    pending = load_json_file(PENDING_FILE, {})
    return pending if isinstance(pending, dict) else {}


def clear_pending_action():
    save_json_file(PENDING_FILE, {})