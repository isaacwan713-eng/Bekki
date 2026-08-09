from PySide6.QtCore import Qt, QTimer, QPropertyAnimation
from PySide6.QtGui import QPainter, QPainterPath, QPixmap
from PySide6.QtWidgets import (
    QFrame,
    QGraphicsOpacityEffect,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)


_AVATAR_CACHE = {}


def create_round_avatar(path, size=40):
    cache_key = (path, size)
    if cache_key in _AVATAR_CACHE:
        return _AVATAR_CACHE[cache_key]

    pixmap = QPixmap(path)
    if pixmap.isNull():
        return QPixmap()

    pixmap = pixmap.scaled(
        size,
        size,
        Qt.KeepAspectRatioByExpanding,
        Qt.SmoothTransformation,
    )

    rounded = QPixmap(size, size)
    rounded.fill(Qt.transparent)

    painter = QPainter(rounded)
    painter.setRenderHint(QPainter.Antialiasing)

    circle = QPainterPath()
    circle.addEllipse(0, 0, size, size)
    painter.setClipPath(circle)
    painter.drawPixmap(0, 0, pixmap)
    painter.end()

    _AVATAR_CACHE[cache_key] = rounded
    return rounded


class HeaderWidget(QWidget):
    def __init__(self):
        super().__init__()

        title_label = QLabel("🩵 Bekki")
        title_label.setStyleSheet(
            """
            QLabel {
                font-family: "Segoe UI";
                font-size: 24px;
                font-weight: 700;
                color: #4da6ff;
            }
            """
        )

        self.settings_button = QPushButton("⚙")
        self.settings_button.setFixedSize(34, 34)
        self.settings_button.setStyleSheet(
            """
            QPushButton {
                border: none;
                border-radius: 17px;
                background: transparent;
                color: #9c8ec2;
                font-size: 18px;
            }
            QPushButton:hover {
                background: #eef5ff;
                color: #5aa8ff;
            }
            QPushButton:pressed {
                background: #dcecff;
            }
            """
        )

        title_layout = QHBoxLayout()
        title_layout.addWidget(title_label)
        title_layout.addStretch()
        title_layout.addWidget(self.settings_button)

        subtitle = QLabel("Your Personal AI Companion")
        subtitle.setStyleSheet(
            """
            QLabel {
                font-family: "Segoe UI";
                font-size: 12px;
                color: #888888;
            }
            """
        )

        line = QFrame()
        line.setFrameShape(QFrame.HLine)
        line.setFrameShadow(QFrame.Sunken)

        layout = QVBoxLayout()
        layout.setContentsMargins(20, 12, 20, 10)
        layout.setSpacing(4)
        layout.addLayout(title_layout)
        layout.addWidget(subtitle)
        layout.addWidget(line)
        self.setLayout(layout)


class MessageWidget(QWidget):
    def __init__(self, sender, text):
        super().__init__()

        is_user = sender.lower() in {"you", "user", "isaac"}

        outer_layout = QHBoxLayout()
        outer_layout.setContentsMargins(4, 6, 4, 6)
        outer_layout.setSpacing(8)

        avatar_label = QLabel()
        avatar_label.setFixedSize(40, 40)

        self.bubble = QLabel(text)
        self.bubble.setWordWrap(True)
        self.bubble.setTextInteractionFlags(Qt.TextSelectableByMouse)
        self.bubble.setMaximumWidth(280)
        self.bubble.setSizePolicy(QSizePolicy.Minimum, QSizePolicy.Preferred)

        name_label = QLabel(sender)
        name_label.setStyleSheet(
            """
            QLabel {
                color: #666666;
                font-family: "Segoe UI";
                font-size: 11px;
                font-weight: 600;
            }
            """
        )

        message_layout = QVBoxLayout()
        message_layout.setContentsMargins(0, 0, 0, 0)
        message_layout.setSpacing(4)

        if is_user:
            name_label.setAlignment(Qt.AlignRight)
            self.bubble.setStyleSheet(
                """
                QLabel {
                    background-color: #f7dce8;
                    color: #202124;
                    border: none;
                    border-radius: 16px;
                    padding: 9px 13px;
                    font-family: "Segoe UI";
                    font-size: 13px;
                }
                """
            )

            avatar_label.setText("🙂")
            avatar_label.setAlignment(Qt.AlignCenter)
            avatar_label.setStyleSheet(
                """
                QLabel {
                    background-color: #f2f2f2;
                    border-radius: 20px;
                    font-size: 22px;
                }
                """
            )

            message_layout.addWidget(name_label)
            message_layout.addWidget(self.bubble, 0, Qt.AlignRight)
            outer_layout.addStretch()
            outer_layout.addLayout(message_layout)
            outer_layout.addWidget(avatar_label, alignment=Qt.AlignTop)
        else:
            self.bubble.setStyleSheet(
                """
                QLabel {
                    background-color: #f7dce8;
                    color: #3f5fa7;
                    border: none;
                    border-radius: 16px;
                    padding: 9px 13px;
                    font-family: "Yu Gothic UI";
                    font-size: 13px;
                }
                """
            )

            avatar = create_round_avatar("assets/bekki_avatar.jpeg", 40)
            if not avatar.isNull():
                avatar_label.setPixmap(avatar)
            else:
                avatar_label.setText("💙")
                avatar_label.setAlignment(Qt.AlignCenter)

            message_layout.addWidget(name_label)
            message_layout.addWidget(self.bubble, 0, Qt.AlignLeft)
            outer_layout.addWidget(avatar_label, alignment=Qt.AlignTop)
            outer_layout.addLayout(message_layout)
            outer_layout.addStretch()

        self.setLayout(outer_layout)

        effect = QGraphicsOpacityEffect(self)
        self.setGraphicsEffect(effect)
        self.animation = QPropertyAnimation(effect, b"opacity")
        self.animation.setDuration(180)
        self.animation.setStartValue(0.0)
        self.animation.setEndValue(1.0)
        self.animation.start()

    def set_text(self, text):
        self.bubble.setText(text)
        self.bubble.adjustSize()
        self.bubble.updateGeometry()


class ChatArea(QWidget):
    def __init__(self):
        super().__init__()

        self.scroll = QScrollArea()
        self.scroll.setWidgetResizable(True)

        self.container = QWidget()
        self.message_layout = QVBoxLayout()
        self.message_layout.setAlignment(Qt.AlignTop)
        self.message_layout.setSpacing(2)
        self.container.setLayout(self.message_layout)
        self.scroll.setWidget(self.container)

        self.scroll.setStyleSheet(
            """
            QScrollArea {
                border: none;
                background: transparent;
            }
            QScrollBar:vertical {
                background: transparent;
                width: 8px;
                margin: 4px 2px 4px 2px;
            }
            QScrollBar::handle:vertical {
                background: #cfd6df;
                border-radius: 4px;
                min-height: 28px;
            }
            QScrollBar::handle:vertical:hover {
                background: #aeb8c5;
            }
            QScrollBar::add-line:vertical,
            QScrollBar::sub-line:vertical {
                height: 0px;
            }
            QScrollBar::add-page:vertical,
            QScrollBar::sub-page:vertical {
                background: transparent;
            }
            QWidget {
                background: transparent;
            }
            """
        )

        layout = QVBoxLayout()
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self.scroll)
        self.setLayout(layout)

        self.add_welcome_message()

    def add_welcome_message(self):
        self.add_message(
            "Bekki",
            "👋 嗨～\n\n"
            "我是 Bekki 🩵\n"
            "今天想聊点什么呀？\n\n"
            "我可以帮你：\n"
            "• 搜索最新信息\n"
            "• 回答问题\n"
            "• 记住重要事情\n"
            "• 陪你聊天 ✨",
        )

    def add_message(self, role, message):
        widget = MessageWidget(role, message)
        self.message_layout.addWidget(widget)
        self.scroll_to_bottom()
        return widget

    def scroll_to_bottom(self):
        QTimer.singleShot(
            0,
            lambda: self.scroll.verticalScrollBar().setValue(
                self.scroll.verticalScrollBar().maximum()
            ),
        )


class InputArea(QWidget):
    def __init__(self):
        super().__init__()

        self.status_label = QLabel("")
        self.status_label.setStyleSheet(
            """
            QLabel {
                color: #888888;
                font-family: "Segoe UI";
                font-size: 12px;
                padding: 4px;
            }
            """
        )

        self.input_box = QLineEdit()
        self.input_box.setPlaceholderText("和 Bekki 聊点什么吧…")
        self.input_box.setMinimumHeight(42)
        self.input_box.setStyleSheet(
            """
            QLineEdit {
                background-color: #ffffff;
                border: 1px solid #dfe3e8;
                border-radius: 18px;
                padding: 0 14px;
                font-family: "Segoe UI";
                font-size: 13px;
            }
            QLineEdit:focus {
                border: 1px solid #8ebff5;
            }
            QLineEdit:disabled {
                background-color: #f5f6f8;
                color: #9aa0a6;
            }
            """
        )

        self.send_button = QPushButton("➤")
        self.send_button.setFixedSize(40, 40)
        self.send_button.setStyleSheet(
            """
            QPushButton {
                background-color: #6caef2;
                color: white;
                border: none;
                border-radius: 20px;
                font-size: 17px;
                font-weight: 600;
            }
            QPushButton:hover {
                background-color: #5a9ee5;
            }
            QPushButton:pressed {
                background-color: #4d8fd4;
            }
            QPushButton:disabled {
                background-color: #b9cde2;
            }
            """
        )

        input_layout = QHBoxLayout()
        input_layout.setContentsMargins(0, 0, 0, 0)
        input_layout.addWidget(self.input_box)
        input_layout.addWidget(self.send_button)

        layout = QVBoxLayout()
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(4)
        layout.addWidget(self.status_label)
        layout.addLayout(input_layout)
        self.setLayout(layout)

    def get_text(self):
        return self.input_box.text().strip()

    def clear(self):
        self.input_box.clear()

    def set_status(self, text):
        self.status_label.setText(text)

    def set_busy(self, busy):
        self.input_box.setEnabled(not busy)
        self.send_button.setEnabled(not busy)

    def focus_input(self):
        self.input_box.setFocus()

    def connect_send(self, handler):
        self.send_button.clicked.connect(handler)
        self.input_box.returnPressed.connect(handler)


class BekkiWindow(QWidget):
    def __init__(self):
        super().__init__()

        self.setObjectName("mainWindow")
        self.setWindowTitle("Bekki AI")
        self.resize(420, 560)
        self.setStyleSheet(
            """
            #mainWindow {
                background-color: #f6f8fb;
            }
            """
        )

        self.header = HeaderWidget()
        self.chat = ChatArea()
        self.input_area = InputArea()

        layout = QVBoxLayout()
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(10)
        layout.addWidget(self.header)
        layout.addWidget(self.chat)
        layout.addWidget(self.input_area)
        self.setLayout(layout)

    def get_message(self):
        return self.input_area.get_text()

    def clear_input(self):
        self.input_area.clear()

    def set_status(self, text):
        self.input_area.set_status(text)

    def set_busy(self, busy):
        self.input_area.set_busy(busy)

    def focus_input(self):
        self.input_area.focus_input()

    def add_message(self, role, message):
        return self.chat.add_message(role, message)

    def connect_send(self, handler):
        self.input_area.connect_send(handler)