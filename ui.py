import os
import sys
from PySide6.QtCore import Qt, QPropertyAnimation, QTimer
from PySide6.QtGui import QIcon, QPainter, QPainterPath, QPixmap
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

def resource_path(relative_path):
    base_path = getattr(sys, "_MEIPASS", os.path.abspath("."))
    return os.path.join(base_path, relative_path)


UI_FONT = '"Microsoft YaHei UI", "Segoe UI"'
_AVATAR_CACHE = {}


def create_round_avatar(path, size=42):
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

        title_label = QLabel("🩵  Bekki")
        title_label.setStyleSheet(
            f"""
            QLabel {{
                color: #4c9df2;
                font-family: {UI_FONT};
                font-size: 25px;
                font-weight: 700;
            }}
            """
        )

        version_badge = QLabel("V1")
        version_badge.setAlignment(Qt.AlignCenter)
        version_badge.setFixedHeight(23)
        version_badge.setStyleSheet(
            f"""
            QLabel {{
                background-color: #eef6ff;
                border: 1px solid #d7e9fb;
                border-radius: 11px;
                color: #5d97cf;
                font-family: {UI_FONT};
                font-size: 10px;
                font-weight: 700;
                padding: 0 9px;
            }}
            """
        )

        subtitle = QLabel("Your Personal AI Companion")
        subtitle.setStyleSheet(
            f"""
            QLabel {{
                color: #8290a2;
                font-family: {UI_FONT};
                font-size: 11px;
            }}
            """
        )

        divider = QFrame()
        divider.setFrameShape(QFrame.HLine)
        divider.setStyleSheet("color: #dce7f1;")

        title_layout = QHBoxLayout()
        title_layout.setContentsMargins(0, 0, 0, 0)
        title_layout.addWidget(title_label)
        title_layout.addStretch()
        title_layout.addWidget(version_badge)

        layout = QVBoxLayout()
        layout.setContentsMargins(20, 13, 20, 8)
        layout.setSpacing(3)
        layout.addLayout(title_layout)
        layout.addWidget(subtitle)
        layout.addSpacing(2)
        layout.addWidget(divider)
        self.setLayout(layout)


class MessageWidget(QWidget):
    def __init__(self, sender, text):
        super().__init__()

        is_user = sender.lower() in {"you", "user", "isaac"}
        outer_layout = QHBoxLayout()
        outer_layout.setContentsMargins(2, 6, 2, 6)
        outer_layout.setSpacing(9)

        avatar_label = QLabel()
        avatar_label.setFixedSize(42, 42)

        self.bubble = QLabel(text)
        self.bubble.setWordWrap(True)
        self.bubble.setTextInteractionFlags(
            Qt.TextSelectableByMouse
        )
        self.bubble.setMaximumWidth(286)
        self.bubble.setSizePolicy(
            QSizePolicy.Minimum,
            QSizePolicy.Preferred,
        )

        name_label = QLabel(sender)
        message_layout = QVBoxLayout()
        message_layout.setContentsMargins(0, 0, 0, 0)
        message_layout.setSpacing(3)

        if is_user:
            name_label.setAlignment(Qt.AlignRight)
            name_label.setStyleSheet(
                f"""
                QLabel {{
                    color: #a16d86;
                    font-family: {UI_FONT};
                    font-size: 10px;
                    font-weight: 700;
                }}
                """
            )
            self.bubble.setStyleSheet(
                f"""
                QLabel {{
                    background-color: #f9dce8;
                    border: 1px solid #f2cedd;
                    border-radius: 17px;
                    color: #3d3440;
                    font-family: {UI_FONT};
                    font-size: 13px;
                    padding: 9px 13px;
                }}
                """
            )
            avatar_label.setText("🙂")
            avatar_label.setAlignment(Qt.AlignCenter)
            avatar_label.setStyleSheet(
                """
                QLabel {
                    background-color: #fff6f9;
                    border-radius: 21px;
                    color: #f3a6c1;
                    font-size: 22px;
                }
                """
            )

            message_layout.addWidget(name_label)
            message_layout.addWidget(
                self.bubble,
                0,
                Qt.AlignRight,
            )
            outer_layout.addStretch()
            outer_layout.addLayout(message_layout)
            outer_layout.addWidget(
                avatar_label,
                alignment=Qt.AlignTop,
            )
        else:
            name_label.setStyleSheet(
                f"""
                QLabel {{
                    color: #4f86bd;
                    font-family: {UI_FONT};
                    font-size: 10px;
                    font-weight: 700;
                }}
                """
            )
            self.bubble.setStyleSheet(
                f"""
                QLabel {{
                    background-color: #ffffff;
                    border: 1px solid #dce9f6;
                    border-radius: 17px;
                    color: #35465a;
                    font-family: {UI_FONT};
                    font-size: 13px;
                    padding: 9px 13px;
                }}
                """
            )
            avatar = create_round_avatar(
                resource_path("assets/bekki_avatar.jpeg"),
                42,
            )
            if avatar.isNull():
                avatar_label.setText("🩵")
                avatar_label.setAlignment(Qt.AlignCenter)
            else:
                avatar_label.setPixmap(avatar)

            avatar_label.setStyleSheet(
                """
                QLabel {
                    background-color: #eaf6ff;
                    border: 1px solid #d7eafb;
                    border-radius: 21px;
                }
                """
            )

            message_layout.addWidget(name_label)
            message_layout.addWidget(
                self.bubble,
                0,
                Qt.AlignLeft,
            )
            outer_layout.addWidget(
                avatar_label,
                alignment=Qt.AlignTop,
            )
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
        self.scroll.setHorizontalScrollBarPolicy(
            Qt.ScrollBarAlwaysOff
        )
        self.scroll.setStyleSheet(
            """
            QScrollArea {
                background: transparent;
                border: none;
            }
            QScrollBar:vertical {
                background: transparent;
                margin: 5px 1px;
                width: 7px;
            }
            QScrollBar::handle:vertical {
                background: #c5d6e8;
                border-radius: 3px;
                min-height: 30px;
            }
            QScrollBar::handle:vertical:hover {
                background: #9dbde0;
            }
            QScrollBar::add-line:vertical,
            QScrollBar::sub-line:vertical {
                height: 0;
            }
            QScrollBar::add-page:vertical,
            QScrollBar::sub-page:vertical {
                background: transparent;
            }
            """
        )

        self.container = QWidget()
        self.container.setStyleSheet("background: transparent;")
        self.message_layout = QVBoxLayout()
        self.message_layout.setAlignment(Qt.AlignTop)
        self.message_layout.setContentsMargins(3, 4, 3, 4)
        self.message_layout.setSpacing(2)
        self.container.setLayout(self.message_layout)
        self.scroll.setWidget(self.container)

        layout = QVBoxLayout()
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self.scroll)
        self.setLayout(layout)
        self.add_welcome_message()

    def add_welcome_message(self):
        self.add_message(
            "Bekki",
            "👋 嗨～我是 Bekki 🩵\n\n"
            "今天想聊点什么呀？\n"
            "我可以搜索、读文件、看图片，\n"
            "也会记住重要的事情 ✨",
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

        self.attachment_bar = QFrame()
        self.attachment_bar.setVisible(False)
        self.attachment_bar.setStyleSheet(
            f"""
            QFrame {{
                background-color: #f4f8fe;
                border: 1px solid #d8e8fa;
                border-radius: 12px;
            }}
            """
        )

        self.attachment_label = QLabel()
        self.attachment_label.setStyleSheet(
            f"""
            QLabel {{
                background: transparent;
                border: none;
                color: #4d627b;
                font-family: {UI_FONT};
                font-size: 12px;
                padding: 4px;
            }}
            """
        )

        self.document_close_button = QPushButton("×")
        self.document_close_button.setFixedSize(27, 27)
        self.document_close_button.setToolTip("移除当前附件")
        self.document_close_button.setStyleSheet(
            """
            QPushButton {
                background: transparent;
                border: none;
                border-radius: 13px;
                color: #7f91a6;
                font-size: 18px;
            }
            QPushButton:hover {
                background-color: #e1edf9;
                color: #4b91d9;
            }
            QPushButton:pressed {
                background-color: #d2e4f5;
            }
            QPushButton:disabled {
                color: #bbc5cf;
            }
            """
        )

        attachment_layout = QHBoxLayout(self.attachment_bar)
        attachment_layout.setContentsMargins(10, 4, 6, 4)
        attachment_layout.setSpacing(6)
        attachment_layout.addWidget(self.attachment_label)
        attachment_layout.addStretch()
        attachment_layout.addWidget(self.document_close_button)

        self.status_label = QLabel()
        self.status_label.setVisible(False)
        self.status_label.setStyleSheet(
            f"""
            QLabel {{
                color: #7890a8;
                font-family: {UI_FONT};
                font-size: 11px;
                padding: 2px 5px;
            }}
            """
        )

        self.input_box = QLineEdit()
        self.input_box.setPlaceholderText("和 Bekki 聊点什么吧…")
        self.input_box.setMinimumHeight(44)
        self.input_box.setStyleSheet(
            f"""
            QLineEdit {{
                background-color: #ffffff;
                border: 1px solid #d4e1ef;
                border-radius: 21px;
                color: #334155;
                font-family: {UI_FONT};
                font-size: 13px;
                padding: 0 15px;
            }}
            QLineEdit:focus {{
                border: 1px solid #77b6f3;
            }}
            QLineEdit:disabled {{
                background-color: #f4f6f9;
                color: #9ba7b4;
            }}
            """
        )

        # Avoid emoji icons here: Windows renders the paperclip like an old
        # toolbar glyph. A simple plus reads as "add attachment" and matches
        # the modern rounded input treatment.
        self.attach_button = QPushButton("＋")
        self.attach_button.setFixedSize(42, 42)
        self.attach_button.setToolTip("添加文件或图片")
        self.attach_button.setStyleSheet(
            """
            QPushButton {
                background: transparent;
                border: none;
                border-radius: 21px;
                color: #6c8094;
                font-size: 25px;
                font-weight: 300;
            }
            QPushButton:hover {
                background-color: #eaf4ff;
                color: #4b9be4;
            }
            QPushButton:pressed {
                background-color: #dcecfb;
            }
            QPushButton:disabled {
                color: #bbc4ce;
            }
            """
        )

        self.send_button = QPushButton("➤")
        self.send_button.setFixedSize(44, 44)
        self.send_button.setToolTip("发送")
        self.send_button.setStyleSheet(
            """
            QPushButton {
                background-color: #68acf0;
                border: none;
                border-radius: 22px;
                color: white;
                font-size: 18px;
                font-weight: 700;
            }
            QPushButton:hover {
                background-color: #559ee8;
            }
            QPushButton:pressed {
                background-color: #438bd5;
            }
            QPushButton:disabled {
                background-color: #bad0e6;
            }
            """
        )

        input_layout = QHBoxLayout()
        input_layout.setContentsMargins(0, 0, 0, 0)
        input_layout.setSpacing(7)
        input_layout.addWidget(self.attach_button)
        input_layout.addWidget(self.input_box)
        input_layout.addWidget(self.send_button)

        layout = QVBoxLayout()
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(4)
        layout.addWidget(self.attachment_bar)
        layout.addWidget(self.status_label)
        layout.addLayout(input_layout)
        self.setLayout(layout)

    def get_text(self):
        return self.input_box.text().strip()

    def clear(self):
        self.input_box.clear()

    def set_status(self, text):
        self.status_label.setText(
            "Bekki · " + text
            if text else ""
        )
        self.status_label.setVisible(bool(text))

    def set_busy(self, busy):
        self.input_box.setEnabled(not busy)
        self.send_button.setEnabled(not busy)
        self.attach_button.setEnabled(not busy)
        self.document_close_button.setEnabled(not busy)

    def focus_input(self):
        self.input_box.setFocus()

    def connect_send(self, handler):
        self.send_button.clicked.connect(handler)
        self.input_box.returnPressed.connect(handler)

    def connect_attach(self, handler):
        self.attach_button.clicked.connect(handler)

    def set_document(self, file_name):
        self.attachment_label.setText("📄  " + file_name)
        self.attachment_bar.setVisible(True)

    def set_image(self, file_name):
        self.attachment_label.setText("🖼️  " + file_name)
        self.attachment_bar.setVisible(True)

    def clear_document(self):
        self.attachment_label.clear()
        self.attachment_bar.setVisible(False)

    def connect_document_close(self, handler):
        self.document_close_button.clicked.connect(handler)


class BekkiWindow(QWidget):
    def __init__(self):
        super().__init__()

        self.setObjectName("mainWindow")
        self.setWindowTitle("Bekki AI")
        self.setWindowIcon(QIcon(resource_path("assets/bekki.ico")))
        self.resize(440, 620)
        self.setMinimumSize(400, 540)
        self.setStyleSheet(
            """
            #mainWindow {
                background-color: #f7faff;
            }
            """
        )

        self.header = HeaderWidget()
        self.chat = ChatArea()
        self.input_area = InputArea()

        layout = QVBoxLayout()
        layout.setContentsMargins(16, 12, 16, 16)
        layout.setSpacing(8)
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

    def connect_attach(self, handler):
        self.input_area.connect_attach(handler)

    def set_document(self, file_name):
        self.input_area.set_document(file_name)

    def set_image(self, file_name):
        self.input_area.set_image(file_name)

    def clear_document(self):
        self.input_area.clear_document()

    def connect_document_close(self, handler):
        self.input_area.connect_document_close(handler)