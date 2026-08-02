import sys
import requests
import json
import os

import memory
import tools

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
)
app = QApplication(sys.argv)
window = QWidget()
window.setWindowTitle("Bekki AI")
window.resize(420,560)

title = QLabel("Bekki")
chat_box = QTextEdit()
chat_box.setReadOnly(True)
input_box = QLineEdit()
send_button = QPushButton("Send")


conversation = []

def get_ai_response(search_result = None):
    print("receivce search result:" ,search_result)
    conversation_text = "\n".join(conversation)
    temporary_context = memory.get_temporary_context(memory_data)

    search_context = ""
    if search_result is not None:
        search_context = (
            "\n\nCurrent Search Results:\n\n"
            +search_result
        )
    prompt = (system_prompt + "\n\n" + temporary_context + search_context + "\n\n" +conversation_text)
    print(prompt)
    url = "http://localhost:11434/api/generate"
    payload = {
        "model" : "gpt-oss:20b",
        "prompt" : prompt,
        "stream" : False,
    }
    response = requests.post(url,json = payload)
    ai_output = response.json()["response"]

    print("AI RAW OUTPUT:")
    print(ai_output)
    result = json.loads(ai_output)
    memory.handle_memory(
        memory_data,
        result["memory"]
    )
    return result["reply"]

    ##print(response.json())
    ##return response.json()["response"]

def save_message(role,message):
    conversation.append(f"{role} : {message}")

def display_message(role,message):
    chat_box.append(f"{role} : {message}")
def send_message():
    message = input_box.text()

    save_message("You",message)

    if not message:
        return

    search_result = None
    if message.startswith("/search "):
        ##query = message.split(" ",1)[1]
        ##search_result  = tools.search(query)
        print("Search command detected")
        query = message.split(" ",1)[1]
        print(query)
        search_result = tools.search(query)
        print(search_result)

    
    response = get_ai_response(search_result)

    save_message("Bekki",response)

    
    display_message("You", message)
    display_message("Bekki",response)
    input_box.clear()

send_button.clicked.connect(send_message)
input_box.returnPressed.connect(send_message)
layout = QVBoxLayout()
layout.addWidget(title)
layout.addWidget(chat_box)
layout.addWidget(input_box)
layout.addWidget(send_button)

window.setLayout(layout)

window.show()
sys.exit(app.exec())