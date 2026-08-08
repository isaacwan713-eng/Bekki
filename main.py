import sys
import json

import memory
import tools

from PySide6.QtCore import QThread
from PySide6.QtWidgets import QApplication

from ui import BekkiWindow
from worker import AIWorker


# =========================================================
# App Data
# =========================================================

memory_data = memory.initialize_memory()

conversation = []

current_thread = None
current_worker = None


# =========================================================
# System Prompt
# =========================================================

with open(
    "prompts/system.txt",
    "r",
    encoding="utf-8",
) as file:

    system_prompt = file.read()


# =========================================================
# AI Response
# =========================================================

def get_ai_response(
    message,
    search_result=None,
    action_context=None,
):

    conversation_text = "\n".join(
        conversation
    )

    temporary_context = (
        memory.get_temporary_context(
            memory_data
        )
    )

    # -----------------------------------------------------
    # Search Context
    # -----------------------------------------------------

    search_context = ""

    if search_result is not None:

        if isinstance(
            search_result,
            list,
        ):

            formatted_results = (
                tools.format_search_results(
                    search_result
                )
            )

        else:

            formatted_results = str(
                search_result
            )

        search_context = (
            "\n\n"
            "############################"
            "\nCurrent Search Results"
            "\n############################\n"
            + formatted_results
        )

    # -----------------------------------------------------
    # Action Context
    # -----------------------------------------------------

    action_text = ""

    if action_context is not None:

        action_text = (
            "\n\n"
            "############################"
            "\nCurrent Action Context"
            "\n############################\n"
            + action_context
        )

    # -----------------------------------------------------
    # Final Prompt
    # -----------------------------------------------------

    prompt = (
        system_prompt

        + "\n\n############################"
        + "\nCurrent User Message"
        + "\n############################\n"
        + message

        + action_text

        + search_context

        + "\n\n############################"
        + "\nCurrent Temporary Memory"
        + "\n############################\n"
        + temporary_context

        + "\n\n############################"
        + "\nRecent Conversation"
        + "\n############################\n"
        + conversation_text
    )

    prompt += (
        "\n\n"
        "Return the final answer now as ONE "
        "valid JSON object only. "
        "Do not output thinking. "
        "Do not stop after reasoning. "
        "Output the final JSON now."
    )

    ai_output = tools.call_model(
        prompt,
        num_ctx=16384,
        num_predict=4096,
    )

    print(
        "AI RAW OUTPUT:"
    )

    print(
        ai_output
    )

    # -----------------------------------------------------
    # Parse JSON
    # -----------------------------------------------------

    try:

        result = json.loads(
            ai_output
        )

    except json.JSONDecodeError as error:

        print(
            "JSON Parse Error:",
            error,
        )

        print(
            "Broken AI Output:",
            repr(ai_output),
        )

        return (
            "呜，刚才回复格式坏掉了，"
            "再试一次吧 🥺"
        )

    # -----------------------------------------------------
    # Pending Action
    # -----------------------------------------------------

    if action_context is not None:

        result["pending_action"] = None

        memory.clear_pending_action()

    elif result.get(
        "pending_action"
    ):

        memory.save_pending_action(
            result["pending_action"]
        )

    # -----------------------------------------------------
    # Memory
    # -----------------------------------------------------

    memory.handle_memory(
        memory_data,
        result.get("memory"),
    )

    # -----------------------------------------------------
    # Reply
    # -----------------------------------------------------

    return result.get(
        "reply",
        "呜，豆豆这次没有生成正常回复，"
        "请再试一次 🥺",
    )


# =========================================================
# Conversation
# =========================================================

def save_message(
    role,
    message,
):

    conversation.append(
        f"{role} : {message}"
    )


# =========================================================
# Search Pipeline
# =========================================================

def run_search_pipeline(query):

    # ==========================================
    # 1. Brave Search
    # ==========================================

    search_results = tools.search(query)

    if not isinstance(search_results, list):
        return search_results

    if not search_results:
        return []


    # ==========================================
    # 2. AI Source Scoring
    # ==========================================

    search_results = tools.score_sources(
        query,
        search_results
    )

    print("\n===== SOURCE SCORES =====")

    for result in search_results:
        print(
            result.get("source_score"),
            result.get("title")
        )

    print("=========================\n")


    # ==========================================
    # 3. Take Top 3 Sources
    # ==========================================

    top_results = search_results[:3]


    # ==========================================
    # 4. Extract Answers
    # ==========================================

    answers = tools.extract_answers(
    query,
    top_results)

    consensus = tools.find_consensus(
        query,
        answers)

    print("\n===== CONSENSUS =====")
    print(consensus)
    print("=====================\n")


    # ==========================================
    # 5. Current version still returns results
    # ==========================================

    return search_results

def run_ai_task(
    message,
    search_result,
    action_context,
):

    return get_ai_response(
        message,
        search_result,
        action_context,
    )


# =========================================================
# Send Message
# =========================================================

def send_message():

    global current_thread
    global current_worker

    message = window.get_message()

    if not message:
        return

    window.clear_input()

    save_message(
        "You",
        message,
    )

    window.add_message(
        "You",
        message,
    )

    thinking_widget = (
        window.add_message(
            "Bekki",
            "正在思考… ✨",
        )
    )

    # -----------------------------------------------------
    # Pending
    # -----------------------------------------------------

    pending = (
        memory.loading_pending_action()
    )

    search_result = None
    action_context = None

    pending_confirmed = False

    if pending:

        pending_confirmed = (
            tools.is_confirmation(
                message
            )
        )

    # -----------------------------------------------------
    # Confirmed Pending Search
    # -----------------------------------------------------

    if (
        pending_confirmed
        and pending.get("type")
        == "search"
    ):

        thinking_widget.set_text(
            "正在搜索… 🔍"
        )

        query = pending["query"]

        search_result = (
            run_search_pipeline(
                query
            )
        )

        action_context = (
            "The user confirmed the pending search. "
            "The search has already been completed. "
            "Answer the pending query directly using "
            "the current search results. "
            "Pending query: "
            + query
        )

        memory.clear_pending_action()

    # -----------------------------------------------------
    # Normal Router
    # -----------------------------------------------------

    else:

        tool = tools.decide_tools(
            message
        )

        if tool == "search":

            thinking_widget.set_text(
                "正在搜索… 🔍"
            )

            search_query = (
                tools.build_search_query(
                    message
                )
            )

            search_result = (
                run_search_pipeline(
                    search_query
                )
            )

    # -----------------------------------------------------
    # Worker Thread
    # -----------------------------------------------------

    current_thread = QThread()

    current_worker = AIWorker(
        lambda: run_ai_task(
            message,
            search_result,
            action_context,
        )
    )

    current_worker.moveToThread(
        current_thread
    )

    current_thread.started.connect(
        current_worker.run
    )

    current_worker.finished.connect(
        thinking_widget.set_text
    )

    current_worker.finished.connect(
        lambda text: save_message(
            "Bekki",
            text,
        )
    )

    current_worker.finished.connect(
        current_thread.quit
    )

    current_worker.finished.connect(
        current_worker.deleteLater
    )

    current_thread.finished.connect(
        current_thread.deleteLater
    )

    # -----------------------------------------------------
    # Error
    # -----------------------------------------------------

    current_worker.failed.connect(
        lambda error:
        thinking_widget.set_text(
            "呜，刚才处理失败了："
            + error
        )
    )

    current_worker.failed.connect(
        current_thread.quit
    )

    current_worker.failed.connect(
        current_worker.deleteLater
    )

    current_thread.start()


# =========================================================
# Start Application
# =========================================================

app = QApplication(
    sys.argv
)

window = BekkiWindow()

window.connect_send(
    send_message
)

window.show()

sys.exit(
    app.exec()
)