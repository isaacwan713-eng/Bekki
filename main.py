import json
import sys
from unittest import result

import memory
import tools
import document
import vision
import os

from PySide6.QtCore import QObject, QThread, Slot
from PySide6.QtWidgets import QApplication,QFileDialog
import document

from ui import BekkiWindow
from worker import AIWorker
import context as context_manager


MAX_RECENT_MESSAGES = 6

memory_data = memory.initialize_memory()
conversation = []

current_thread = None
current_worker = None


with open("prompts/system.txt", "r", encoding="utf-8") as file:
    system_prompt = file.read()

def parse_ai_result(ai_output):
    try:
        result = json.loads(ai_output)
        return result, None

    except json.JSONDecodeError as strict_error:
        try:
            result, end_index = (
                json.JSONDecoder()
                .raw_decode(ai_output.lstrip())
            )

            if (
                isinstance(result, dict)
                and isinstance(result.get("reply"), str)
                and result["reply"].strip()
            ):
                trailing_text = ai_output.lstrip()[end_index:].strip()

                print(
                    "[AI JSON RECOVERED]",
                    "ignored_trailing_chars=",
                    len(trailing_text),
                )

                # 尾部损坏时只保留回复，
                # 不保存不完整的 memory/action。
                return {
                    "reply": result["reply"],
                    "memory": None,
                    "pending_action": None,
                }, strict_error

        except json.JSONDecodeError:
            pass

        return None, strict_error

def get_ai_response(message, search_result=None, action_context=None,image_context=None):
    # Keep the prompt responsive as a conversation gets longer.
    recent_conversation = conversation[-MAX_RECENT_MESSAGES:]
    conversation_text = "\n".join(recent_conversation)
    temporary_context = memory.get_temporary_context(memory_data)
    long_term_context = memory.get_long_term_context(memory_data)

    search_context = ""
    if search_result is not None:
        if isinstance(search_result, dict):
            formatted_results = search_result.get("context", "")
        else:
            formatted_results = str(search_result)

        search_context = (
            "\n\n############################"
            "\nSearch Evidence"
            "\n############################\n"
            + formatted_results
        )

    action_text = ""
    if action_context is not None:
        action_text = (
            "\n\n############################"
            "\nCurrent Action Context"
            "\n############################\n"
            + action_context
        )

    conversation_state = context_manager.load_context()
    context_state_text = json.dumps(
        conversation_state,
        ensure_ascii=False,
        indent=2)

    document_context = ""

    if document.has_document():
        document_context = (
            "\n\n############################"
            "\nCurrent Document Context"
            "\n############################\n"
            + document.get_document_context(message)
        )

    image_context_text = ""
    if image_context:
        image_context_text = (
            "\n\n############################"
            "\nCurrent Image Context"
            "\n############################\n"
            + image_context
        ) 

    prompt = (
        system_prompt
        + "\n\n############################"
        + "\nCurrent User Message"
        + "\n############################\n"
        + message
        + action_text
        + search_context
        + "\n\n############################"
        + "\nCurrent Document Context"
        + "\n############################\n"
        + document_context
        + "\n\n############################"
        + "\nCurrent Image Context"
        + "\n############################\n"
        + image_context_text
        + "\n\n############################"
        + "\nCurrent Temporary Memory"
        + "\n############################\n"
        + temporary_context
        + "\n\n############################"
        + "\nCurrent Long-term Memory"
        + "\n############################\n"
        + long_term_context
        + "\n\n############################"
        + "\nCurrent Conversation State"
        + context_state_text
        + "\nRecent Conversation"
        + "\n############################\n"
        + conversation_text
        + "\n\nReturn the final answer now as ONE valid JSON object only. "
        + "Do not output thinking. "
        + "Do not stop after reasoning. "
        + "Output the final JSON now."
    )

    ai_output = tools.call_model(
        prompt,
        num_ctx=16384,
        num_predict=4096,
    )

    print("AI RAW OUTPUT:")
    print(ai_output)

    result, parse_error = parse_ai_result(ai_output)
    if result is None:
        print("[AI JSON ERROR]", parse_error)
        return "呜，刚才回复格式坏掉了，再试一次吧 🥺"

    if action_context is not None:
        result["pending_action"] = None
        memory.clear_pending_action()
    elif result.get("pending_action"):
        memory.save_pending_action(result["pending_action"])

    memory.handle_memory(memory_data, result.get("memory"))

    reply = result.get(
        "reply",
        "呜，豆豆这次没有生成正常回复，请再试一次 🥺",
    )
    print("[debug]")

    recent_conversation = "\n".join(conversation[-MAX_RECENT_MESSAGES:])
    context_manager.update_context(
        recent_conversation = recent_conversation,
        current_user_message = message,
        latest_reply = reply
    )
    print("[DEBUG] AFTER CONTEXT UPDATE")
    print("[DEBUG] RETURNING REPLY:", repr(reply))
    return reply


def save_message(role, message):
    conversation.append(f"{role} : {message}")


def process_request(message, status_callback):
    """Runs the complete request pipeline in the worker thread."""

    status_callback("正在判断问题… ✨")

    pending = memory.loading_pending_action()
    search_result = None
    action_context = None
    image_context = None

    pending_confirmed = False
    if pending:
        pending_confirmed = tools.is_confirmation(message)

    if pending_confirmed and pending.get("type") == "search":
        query = pending.get("query", "")

        try:
            search_result = tools.search_controller(
                query,
                status_callback,
            )

            action_context = (
                "The user confirmed the pending search. "
                "The search has already been completed. "
                "Answer the pending query directly using the current search evidence. "
                "Pending query: "
                + query
            )
        finally:

            memory.clear_pending_action()

    else:
        recent_context = "\n".join(conversation[-MAX_RECENT_MESSAGES:])
        tool = tools.decide_tools(message, recent_context)

        if tool == "search":
            status_callback("正在整理搜索问题… 🔍")
            recent_context = "\n".join(conversation[-MAX_RECENT_MESSAGES:])
            search_query = tools.build_search_query(message, recent_context)
            search_result = tools.search_controller(
                search_query,
                status_callback=status_callback,
            )
        if vision.has_image():
            status_callback("正在切换视觉模型… 👀")
            tools.unload_model()
            image_context = vision.analyze_image(
                message,
                status_callback=status_callback,
            )

    status_callback("正在生成回复… 💭")
    return get_ai_response(
        message,
        search_result,
        action_context,
        image_context
    )



def clear_worker_references():
    global current_thread, current_worker
    current_thread = None
    current_worker = None

class RequestUIBridge(QObject):

    def __init__(self):
        super().__init__()
        self.thinking_widget = None

    def set_thinking_widget(self, widget):
        self.thinking_widget = widget

    @Slot(str)
    def on_status(self, text):
        if self.thinking_widget is not None:
            self.thinking_widget.set_text(text)

        window.set_status(text)

    @Slot(str)
    def on_finished(self, reply):
        if self.thinking_widget is not None:
            self.thinking_widget.set_text(reply)

        save_message("Bekki", reply)

        window.set_status("")
        window.set_busy(False)
        window.focus_input()

    @Slot(str)
    def on_failed(self, error):
        if self.thinking_widget is not None:
            self.thinking_widget.set_text(
                "呜，刚才处理失败了：" + error
            )

        window.set_status("")
        window.set_busy(False)
        window.focus_input()

def send_message():
    global current_thread, current_worker

    # Only one request at a time for now. This keeps conversation, memory and
    # pending actions deterministic while the UI remains responsive.
    if current_thread is not None:
        return

    message = window.get_message()
    if not message:
        return

    window.clear_input()
    window.set_busy(True)

    save_message("You", message)
    window.add_message("You", message)

    thinking_widget = window.add_message(
        "Bekki",
        "正在思考… ✨",
    )
    ui_bridge.set_thinking_widget(thinking_widget)

    current_thread = QThread()
    current_worker = AIWorker(
        lambda status_callback: process_request(
            message,
            status_callback,
        )
    )

    current_worker.moveToThread(current_thread)

    current_thread.started.connect(current_worker.run)

    current_worker.status.connect(ui_bridge.on_status)

    current_worker.finished.connect(ui_bridge.on_finished)

    current_worker.finished.connect(current_thread.quit)
    current_worker.finished.connect(current_worker.deleteLater)

    current_worker.failed.connect(ui_bridge.on_failed)
    current_worker.failed.connect(current_thread.quit)
    current_worker.failed.connect(current_worker.deleteLater)

    current_thread.finished.connect(current_thread.deleteLater)
    current_thread.finished.connect(clear_worker_references)

    current_thread.start()

def attach_file():
    file_path, _ = QFileDialog.getOpenFileName(
        window,
        "Choose a file",
        "",
        (
            "Supported Files "
            "(*.pdf *.docx *.txt *.md "
            "*.csv *.xlsx "
            "*.png *.jpg *.jpeg *.webp);;"
            "Documents "
            "(*.pdf *.docx *.txt *.md "
            "*.csv *.xlsx);;"
            "Images "
            "(*.png *.jpg *.jpeg *.webp);;"
            "PDF Files (*.pdf);;"
            "Word Documents (*.docx);;"
            "CSV Files (*.csv);;"
            "Excel Workbooks (*.xlsx);;"
            "Text Files (*.txt *.md)"
        ),
    )

    if not file_path:
        return

    extension = os.path.splitext(
        file_path
    )[1].lower()

    window.set_status(
        "正在读取文件… 📎"
    )

    # ==========================================
    # Image
    # ==========================================

    if extension in (
        vision.SUPPORTED_IMAGE_EXTENSIONS
    ):
        result = vision.load_image(
            file_path
        )

        if not result.get("success"):
            window.set_status("")

            window.add_message(
                "Bekki",
                "图片读取失败了 🥺\n"
                + str(
                    result.get(
                        "error",
                        "Unknown error",
                    )
                ),
            )

            return

        # Replace the previous document only
        # after the image is fully validated.
        document.clear_document()

        window.set_status("")
        window.set_image(
            result["file_name"]
        )

        window.add_message(
            "Bekki",
            "🖼️ 已加载图片：\n"
            + result["file_name"]
            + "\n\n现在可以直接问我"
            + "这张图片里的内容啦 ✨",
        )

        window.focus_input()
        return

    # ==========================================
    # Document
    # ==========================================

    result = document.load_document(
        file_path
    )

    print(
        "[MAIN DOCUMENT]",
        document.has_document(),
        document.get_current_document(),
    )

    if not result.get("success"):
        window.set_status("")

        window.add_message(
            "Bekki",
            "文件读取失败了 🥺\n"
            + str(
                result.get(
                    "error",
                    "Unknown error",
                )
            ),
        )

        return

    # Replace the previous image only after
    # the document has loaded successfully.
    vision.clear_image()

    window.set_status("")
    window.set_document(
        result["file_name"]
    )

    window.add_message(
        "Bekki",
        "📎 已加载文件：\n"
        + result["file_name"]
        + "\n\n现在可以直接问我"
        + "这个文件里的内容啦 ✨",
    )

    window.focus_input()

def remove_document():
    document.clear_document()
    vision.clear_image()
    window.clear_document()

    window.set_status("")

    window.focus_input()

app = QApplication(sys.argv)

window = BekkiWindow()
ui_bridge = RequestUIBridge()

window.connect_send(
    send_message
)

window.connect_attach(
    attach_file
)

window.connect_document_close(
    remove_document
)

window.show()
window.focus_input()

sys.exit(app.exec())