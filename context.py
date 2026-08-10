import json
from pathlib import Path
from datetime import datetime


CONTEXT_FILE = Path("data/context.json")


DEFAULT_CONTEXT = {
    "current_topic": None,
    "entities": [],
    "date_context": None,
    "current_goal": None,
    "last_user_intent": None,
    "open_references": {}
}


def load_context():
    if not CONTEXT_FILE.exists():
        return DEFAULT_CONTEXT.copy()

    try:
        with open(
            CONTEXT_FILE,
            "r",
            encoding="utf-8"
        ) as file:
            data = json.load(file)

        if not isinstance(data, dict):
            return DEFAULT_CONTEXT.copy()

        return data

    except Exception as error:
        print(
            "[CONTEXT LOAD ERROR]",
            error
        )

        return DEFAULT_CONTEXT.copy()


def save_context(context):
    CONTEXT_FILE.parent.mkdir(
        parents=True,
        exist_ok=True
    )

    with open(
        CONTEXT_FILE,
        "w",
        encoding="utf-8"
    ) as file:
        json.dump(
            context,
            file,
            ensure_ascii=False,
            indent=2
        )


def clear_context():
    save_context(
        DEFAULT_CONTEXT.copy()
    )


def update_context(
    recent_conversation,
    current_user_message,
    latest_reply
):
    # Local import avoids circular import
    from tools import run_ai_prompt

    previous_context = load_context()

    current_date = (datetime.now()).date().isoformat()

    input_text = (
        "Current date: "
        + current_date
        +"\n\nPrevious conversation state:\n"
        + json.dumps(
            previous_context,
            ensure_ascii=False,
            indent=2
        )
        + "\n\nRecent conversation:\n"
        + recent_conversation
        + "\n\nCurrent user message:\n"
        + current_user_message
        + "\n\nBekki's latest reply:\n"
        + latest_reply
    )

    result = run_ai_prompt(
        "prompts/context.txt",
        input_text,
        expect_json=True,
        num_ctx=4096,
        num_predict=512
    )

    if not isinstance(result, dict):
        print(
            "[CONTEXT UPDATE FAILED]",
            result
        )
        return previous_context

    new_context = {
        "current_topic": result.get(
            "current_topic"
        ),
        "entities": result.get(
            "entities",
            []
        ),
        "date_context": result.get(
            "date_context"
        ),
        "current_goal": result.get(
            "current_goal"
        ),
        "last_user_intent": result.get(
            "last_user_intent"
        ),
        "open_references": result.get(
            "open_references",
            {}
        )
    }

    save_context(new_context)

    print(
        "\n===== CONTEXT STATE ====="
    )

    print(
        json.dumps(
            new_context,
            ensure_ascii=False,
            indent=2
        )
    )

    print(
        "=========================\n"
    )

    return new_context


