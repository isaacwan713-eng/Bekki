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
            "profile": [],
            "preference": [],
            "relationships": [],
        },
    )
    create_json_file(PENDING_FILE, {})

    memory_data = {
        "temporary": load_json_file(TEMPORARY_FILE, []),
        "tasks": load_json_file(TASK_FILE, []),
        "profile": load_json_file(
            PROFILE_FILE,
            {
                "profile": [],
                "preference": [],
                "relationships": [],
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

def judge_long_term_memory(
    category,
    content,
    existing_memories
):
    from tools import run_ai_prompt

    input_text = (
        "Memory category:\n"
        + category
        + "\n\nExisting memories:\n"
        + json.dumps(
            existing_memories,
            ensure_ascii=False,
            indent=2
        )
        + "\n\nNew candidate:\n"
        + json.dumps(
            {
                "type": category,
                "content": content,
            },
            ensure_ascii=False,
            indent=2
        )
    )

    result = run_ai_prompt(
        "prompts/memory_judge.txt",
        input_text,
        expect_json=True,
        num_ctx=4096,
        num_predict=256,
    )

    if not isinstance(result, dict):
        return {
            "action": "IGNORE",
            "target_index": None,
            "content": None,
        }

    return result

def add_long_term_memory(
    memory_data,
    category,
    content
):
    profile_data = memory_data["profile"]

    if category not in profile_data:
        return

    memories = profile_data[category]

    judgment = judge_long_term_memory(
        category,
        content,
        memories
    )

    action = str(
        judgment.get("action", "IGNORE")
    ).upper()

    new_content = judgment.get(
        "content"
    )

    target_index = judgment.get(
        "target_index"
    )

    print(
        "[MEMORY JUDGE]",
        judgment
    )


    # ==========================================
    # IGNORE
    # ==========================================

    if action == "IGNORE":
        return


    # ==========================================
    # ADD
    # ==========================================

    if action == "ADD":

        if not new_content:
            return

        current_time = (
            datetime.now().isoformat()
        )

        memories.append(
            {
                "content": new_content,
                "created_at": current_time,
                "updated_at": current_time,
            }
        )


    # ==========================================
    # UPDATE
    # ==========================================

    elif action == "UPDATE":

        if (
            not isinstance(target_index, int)
            or target_index < 0
            or target_index >= len(memories)
            or not new_content
        ):
            return

        old_memory = memories[
            target_index
        ]

        memories[target_index] = {
            "content": new_content,

            "created_at": old_memory.get(
                "created_at",
                datetime.now().isoformat()
            ),

            "updated_at":
                datetime.now().isoformat(),
        }

    else:
        return


    save_json_file(
        PROFILE_FILE,
        profile_data
    )

def handle_memory(
    memory_data,
    memory_info
):
    if (
        not memory_info
        or not isinstance(memory_info, dict)
    ):
        return

    memory_type = memory_info.get(
        "type"
    )

    content = memory_info.get(
        "content"
    )

    if not content:
        return


    # ==============================================
    # Temporary
    # ==============================================

    if memory_type == "temporary":

        for existing_memory in memory_data[
            "temporary"
        ]:
            if (
                existing_memory.get("content")
                == content
            ):
                return

        add_temporary(
            memory_data,
            content
        )

        return


    # ==============================================
    # Long-term
    # ==============================================

    if memory_type in {
        "profile",
        "preference",
        "relationships",
    }:
        add_long_term_memory(
            memory_data,
            memory_type,
            content
        )

        return


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

def get_long_term_context(memory_data):
    profile_data = memory_data.get(
        "profile",
        {}
    )

    lines = [
        "Current Long-term Memory:",
        ""
    ]

    found_memory = False

    for category in [
        "profile",
        "preference",
        "relationships",
    ]:
        memories = profile_data.get(
            category,
            []
        )

        if not memories:
            continue

        found_memory = True

        lines.append(
            f"[{category}]"
        )

        for item in memories:
            content = item.get(
                "content",
                ""
            )

            if content:
                lines.append(
                    f"- {content}"
                )

        lines.append("")

    if not found_memory:
        return (
            "Current Long-term Memory:\n\n"
            "None"
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