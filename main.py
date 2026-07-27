import sys
import requests
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

def get_ai_response():

    prompt = "\n".join(conversation)
    url = "http://localhost:11434/api/generate"
    payload = {
        "model" : "gpt-oss:20b",
        "prompt" : prompt,
        "stream" : False,
    }
    response = requests.post(url,json = payload)

    print(response.json())
    return response.json()["response"]

def send_message():
    message = input_box.text()

    conversation.append(f"You: {message}")

    if not message:
        return
    
    response = get_ai_response()

    conversation.append(f"Bekki: {response}")

    
    chat_box.append(f"You: {message}")
    chat_box.append(f"Bekki:{response}")
    input_box.clear()

send_button.clicked.connect(send_message)
layout = QVBoxLayout()
layout.addWidget(title)
layout.addWidget(chat_box)
layout.addWidget(input_box)
layout.addWidget(send_button)

window.setLayout(layout)

window.show()
sys.exit(app.exec())