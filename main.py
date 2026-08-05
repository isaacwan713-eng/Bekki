import sys
import requests
import json
import os

import memory
import tools

from PySide6.QtCore import QTimer,Qt

from ui import MessageWidget



memory_data = memory.initialize_memory()


print(memory_data)

with open("prompts/system.txt","r",encoding="utf-8") as file:
    system_prompt = file.read()
    ##print(system_prompt)

from PySide6.QtWidgets import (
        QApplication,
        QLabel,
        QLineEdit,
        QMainWindow,
        QPushButton,
        QTextEdit,
        QVBoxLayout,
        QWidget,
        QHBoxLayout,
        QScrollArea,
)
app = QApplication(sys.argv)
window = QWidget()
window.setWindowTitle("Bekki AI")
window.resize(420,560)

title = QLabel("Bekki")
chat_scroll = QScrollArea()
chat_scroll.setWidgetResizable(True)

chat_container = QWidget()
chat_layout = QVBoxLayout()

chat_container.setLayout(chat_layout)
chat_scroll.setWidget(chat_container)
input_box = QLineEdit()
input_box.setPlaceholderText("和 Bekki 聊点什么吧…")
input_box.setMinimumHeight(42)

input_box.setStyleSheet(
    """
    QLineEdit {
        background-color: #ffffff;
        border: 1px solid #dddddd;
        border-radius: 14px;
        padding: 0 14px;
        font-size: 14px;
    }

    QLineEdit:focus {
        border: 1px solid #ff8fbd;
    }
    """
)
send_button = QPushButton("➤")
send_button.setFixedSize(42, 42)

send_button.setStyleSheet(
    """
    QPushButton {
        background-color: #ff8fbd;
        color: white;
        border: none;
        border-radius: 21px;
        font-size: 18px;
        font-weight: bold;
    }

    QPushButton:hover {
        background-color: #ff72ac;
    }

    QPushButton:pressed {
        background-color: #e85f98;
    }
    """
)

status_label = QLabel("")
status_label.setStyleSheet(
    """
    QLabel {
        color: #888888;
        font-size: 12px;
        padding : 4px
        }
    """
)


conversation = []

def get_ai_response(search_result=None, action_context=None):
    print("receive search result:", search_result)

    conversation_text = "\n".join(conversation)
    temporary_context = memory.get_temporary_context(memory_data)

    search_context = ""

    if search_result is not None:
        search_context = (
            "\n\nCurrent Search Results:\n\n"
            + search_result
        )

    action_text = ""

    if action_context is not None:
        action_text = (
            "\n\nCurrent Action Context:\n\n"
            + action_context
        )

    prompt = (
        system_prompt
        + "\n\n"
        + temporary_context
        + search_context
        + action_text
        + "\n\n"
        + conversation_text
    )

    prompt += (
    "\n\nReturn the final answer now as ONE valid JSON object only. "
    "Do not output thinking. "
    "Do not stop after reasoning. "
    "Output the final JSON now."
    )

    ai_output = tools.call_model(
    prompt,
    num_ctx=16384,
    num_predict=4096
    )

    print("AI RAW OUTPUT:")
    print(ai_output)

    try:
        result = json.loads(ai_output)

    except json.JSONDecodeError as error:
        print("JSON Parse Error:", error)
        print("Broken AI Output:", repr(ai_output))
        return "呜，刚才回复格式坏掉了，再试一次吧 🥺"

    if action_context is not None:
        result["pending_action"] = None
        memory.clear_pending_action()

    elif result.get("pending_action"):
        memory.save_pending_action(
            result["pending_action"]
        )

    memory.handle_memory(
        memory_data,
        result.get("memory")
    )

    return result.get(
        "reply",
        "呜，豆豆这次没有生成正常回复，请再试一次 🥺"
    )

    ##print(response.json())
    ##return response.json()["response"]



def save_message(role,message):
    conversation.append(f"{role} : {message}")

def display_message(role, message):
    widget = MessageWidget(role, message)
    chat_layout.addWidget(widget)

    QTimer.singleShot(
        0,
        lambda: chat_scroll.verticalScrollBar().setValue(
            chat_scroll.verticalScrollBar().maximum()
        )
    )


def set_status(text):
    status_label.setText(text)
    QApplication.processEvents()




def send_message():
    message = input_box.text()

    if not message:
        return

    save_message("You",message)

    set_status("Bekki 正在思考。。。")

    pending = memory.loading_pending_action()
    print(pending)
    search_result = None
    action_context = None
    tool = tools.decide_tools(message)
    print("SELECTED TOOL:", repr(tool))
    if pending and tools.is_confirmation(message):
        if pending.get("type") == "search":
            set_status("Bekki 正在思考。。。")
            search_result = tools.search(pending["query"]
                                         )

        action_context = (
            "The user confirmed the pending search. "
            "The search has already been completed. "
            "Answer the pending query directly using the current search results. "
            "Do not say that you will search. "
            "Do not ask for confirmation again. "
            + "Pending query: "
            + pending["query"]
        )


        memory.clear_pending_action()


    elif tool == "search":
        set_status("Bekki 正在思考。。。")
        search_result = tools.search(message)
    print("SEARCH RESULT TYPE:", type(search_result))
    print("SEARCH RESULT VALUE:", repr(search_result))


    #if not message:
    #    return

    #search_result = None
    #if tools.should_search(message):
    #    search_result = tools.search(message)

    response = get_ai_response(search_result,action_context)

    save_message("Bekki",response)

    
    display_message("You", message)
    display_message("Bekki",response)
    set_status("完成！！！")
    QTimer.singleShot(1500,lambda:set_status(""))
    input_box.clear()

send_button.clicked.connect(send_message)
input_box.returnPressed.connect(send_message)
layout = QVBoxLayout()
layout.setContentsMargins(16, 16, 16, 16)
layout.setSpacing(10)
input_layout = QHBoxLayout()
input_layout.addWidget(input_box)
input_layout.addWidget(send_button)
#widget = MessageWidget("Bekki","Hello")
layout.addWidget(title)
#layout.addWidget(widget)
layout.addWidget(chat_scroll)
layout.addWidget(status_label)
layout.addLayout(input_layout)

window.setLayout(layout)

window.show()
sys.exit(app.exec())