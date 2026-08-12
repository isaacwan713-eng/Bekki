# Bekki AI
# Created by YW49
# Copyright (c) 2026 YW49. All rights reserved.

import os
import sys
from PySide6.QtCore import (
    Qt,
    QPropertyAnimation,
    QTimer,
    QUrl,
)
from PySide6.QtGui import (
    QDesktopServices,
    QFontMetrics,
    QIcon,
    QPainter,
    QPainterPath,
    QPixmap,
)
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
    QGridLayout,
    QMenu,
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

        self.history_button = QPushButton("☰")
        self.history_button.setFixedSize(28, 28)
        self.history_button.setCursor(Qt.PointingHandCursor)
        self.history_button.setToolTip("显示 / 隐藏聊天记录")
        self.history_button.setStyleSheet(
            """
            QPushButton {
                background-color: #eef6ff;
                border: 1px solid #d7e9fb;
                border-radius: 14px;
                color: #5d97cf;
                font-size: 15px;
            }
            QPushButton:hover { background-color: #dceeff; }
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
        title_layout.addWidget(self.history_button)
        title_layout.addWidget(version_badge)

        layout = QVBoxLayout()
        layout.setContentsMargins(20, 13, 20, 8)
        layout.setSpacing(3)
        layout.addLayout(title_layout)
        layout.addWidget(subtitle)
        layout.addSpacing(2)
        layout.addWidget(divider)
        self.setLayout(layout)

    def connect_history_toggle(self, handler):
        self.history_button.clicked.connect(handler)


class HistorySidebar(QFrame):
    """GPT-style session list, kept deliberately compact for Bekki."""
    def __init__(self):
        super().__init__()
        self._select_handler = None
        self._new_handler = None
        self._delete_handler = None
        self._clear_handler = None
        self._reset_context_handler = None
        self.setFixedWidth(190)
        self.setStyleSheet(
            f"""
            QFrame {{
                background-color: #f1f7ff;
                border: 1px solid #dceaf8;
                border-radius: 16px;
            }}
            QLabel {{ font-family: {UI_FONT}; color: #54718f; }}
            """
        )

        title = QLabel("Chats")
        title.setStyleSheet(f"font-family: {UI_FONT}; font-size: 13px; font-weight: 700; color: #4d8fcb;")

        self.new_button = QPushButton("＋  New chat")
        self.new_button.setCursor(Qt.PointingHandCursor)
        self.new_button.setStyleSheet(
            f"""QPushButton {{ background:#ffffff; border:1px solid #c9e1f7;
            border-radius:11px; color:#397db8; font-family:{UI_FONT}; font-weight:700;
            padding:9px; text-align:left; }} QPushButton:hover {{ background:#e7f4ff; }}"""
        )
        self.new_button.clicked.connect(lambda: self._new_handler and self._new_handler())

        self.scroll = QScrollArea()
        self.scroll.setWidgetResizable(True)
        self.scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.scroll.setStyleSheet("QScrollArea { border: none; background: transparent; }")
        self.list_container = QWidget()
        self.list_layout = QVBoxLayout(self.list_container)
        self.list_layout.setContentsMargins(0, 0, 0, 0)
        self.list_layout.setSpacing(4)
        self.list_layout.setAlignment(Qt.AlignTop)
        self.scroll.setWidget(self.list_container)

        self.clear_button = QPushButton("Clear current chat")
        self.reset_button = QPushButton("Reset current context")
        for button in (self.clear_button, self.reset_button):
            button.setCursor(Qt.PointingHandCursor)
            button.setStyleSheet(
                f"""QPushButton {{ background:transparent; border:none; color:#7191af;
                font-family:{UI_FONT}; font-size:10px; padding:6px; text-align:left; }}
                QPushButton:hover {{ color:#3f7fb8; background:#e4f2ff; border-radius:8px; }}"""
            )
        self.clear_button.clicked.connect(lambda: self._clear_handler and self._clear_handler())
        self.reset_button.clicked.connect(lambda: self._reset_context_handler and self._reset_context_handler())

        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 14, 12, 12)
        layout.setSpacing(9)
        layout.addWidget(title)
        layout.addWidget(self.new_button)
        layout.addWidget(self.scroll, 1)
        layout.addWidget(self.clear_button)
        layout.addWidget(self.reset_button)

        creator_label = QLabel("Created by YW49  🩵")
        creator_label.setAlignment(Qt.AlignCenter)
        creator_label.setStyleSheet(
            f"color:#8ba5bd; font-family:{UI_FONT}; font-size:9px; padding-top:4px;"
        )
        layout.addWidget(creator_label)

    def set_handlers(self, select_handler, new_handler, clear_handler, reset_context_handler):
        self._select_handler = select_handler
        self._new_handler = new_handler
        self._clear_handler = clear_handler
        self._reset_context_handler = reset_context_handler

    def set_sessions(self, sessions, active_session_id):
        while self.list_layout.count():
            item = self.list_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()

        for session in sessions:
            session_id = session.get("id")
            row = QWidget()
            row.setSizePolicy(
                QSizePolicy.Expanding,
                QSizePolicy.Fixed,
            )
            row_layout = QHBoxLayout(row)
            row_layout.setContentsMargins(0, 0, 0, 0)
            row_layout.setSpacing(3)

            full_title = str(session.get("title") or "New chat")
            button = QPushButton()
            button.setMinimumWidth(0)
            button.setSizePolicy(
                QSizePolicy.Ignored,
                QSizePolicy.Fixed,
            )
            button.setText(
                QFontMetrics(button.font()).elidedText(
                    full_title,
                    Qt.ElideRight,
                    108,
                )
            )
            button.setCursor(Qt.PointingHandCursor)
            button.setToolTip(full_title)
            active = session_id == active_session_id
            button.setStyleSheet(
                f"""QPushButton {{ background:{'#dcefff' if active else 'transparent'};
                border:{'1px solid #bfdcf6' if active else '1px solid transparent'};
                border-radius:10px; color:{'#347ab7' if active else '#5d7892'};
                font-family:{UI_FONT}; font-size:11px; padding:9px; text-align:left; }}
                QPushButton:hover {{ background:#e5f2ff; color:#347ab7; }}"""
            )
            button.clicked.connect(lambda checked=False, target=session_id: self._select_handler and self._select_handler(target))

            delete_button = QPushButton("×")
            delete_button.setFixedSize(25, 25)
            delete_button.setSizePolicy(
                QSizePolicy.Fixed,
                QSizePolicy.Fixed,
            )
            delete_button.setCursor(Qt.PointingHandCursor)
            delete_button.setToolTip("Delete this chat")
            delete_button.setStyleSheet(
                f"""QPushButton {{ background:transparent; border:1px solid transparent;
                border-radius:12px; color:#9ab0c4; font-family:{UI_FONT}; font-size:15px;
                padding:0; }} QPushButton:hover {{ background:#ffeaf1;
                border-color:#f4cbd9; color:#c66f8f; }}"""
            )
            delete_button.clicked.connect(
                lambda checked=False, target=session_id:
                self._delete_handler and self._delete_handler(target)
            )

            row_layout.addWidget(button, 1)
            row_layout.addWidget(delete_button)
            self.list_layout.addWidget(row)


class MessageWidget(QWidget):
    def __init__(self, sender, text, sources=None):
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
        self.source_layout = QGridLayout()
        self.source_layout.setContentsMargins(0, 2, 0, 0)
        self.source_layout.setSpacing(4)

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
            message_layout.addLayout(self.source_layout)
            self.source_layout.setAlignment(Qt.AlignRight)            
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

        if sources:
            self.set_sources(sources)

    def set_text(self, text):
        self.bubble.setText(text)
        self.bubble.adjustSize()
        self.bubble.updateGeometry()
    def set_sources(self, sources):
        while self.source_layout.count():
            item = self.source_layout.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.deleteLater()

        valid_sources = [
            item for item in sources
            if item.get("url")
        ]

        concrete_sources = [
            item for item in valid_sources
            if item.get("is_concrete_news", True)
        ]
        link_sources = [
            item for item in valid_sources
            if not item.get("is_concrete_news", True)
        ]

        # Keep Fact Check compact and show up to four concrete sources directly.
        visible_sources = concrete_sources[:4]
        hidden_sources = concrete_sources[4:] + link_sources

        def make_badge(label, tooltip):
            badge = QPushButton(label)
            badge.setFixedSize(30, 30)
            badge.setToolTip(tooltip)
            badge.setCursor(Qt.PointingHandCursor)
            badge.setStyleSheet(
                f"""
                QPushButton {{
                    background-color: #edf6ff;
                    border: 1px solid #bcdcf7;
                    border-radius: 15px;
                    color: #3e7eb8;
                    font-family: {UI_FONT};
                    font-size: 8px;
                    font-weight: 700;
                    padding: 0;
                }}
                QPushButton:hover {{
                    background-color: #d9edff;
                    border-color: #78afe2;
                    color: #276da9;
                }}
                """
            )
            return badge

        for index, source in enumerate(visible_sources):
            url = source["url"]
            domain = source.get("domain", "")
            label = (
                domain.lower()
                .replace("www.", "")
                .split(".")[0]
                .upper()[:4]
                or "↗"
            )

            badge = make_badge(
                label,
                "打开来源：" + (domain or url),
            )
            badge.clicked.connect(
                lambda checked=False, target=url:
                QDesktopServices.openUrl(QUrl(target))
            )
            self.source_layout.addWidget(
                badge,
                0,
                index,
            )

        if hidden_sources:
            more_badge = make_badge(
                "↗ +" + str(len(hidden_sources)),
                "查看其余来源",
            )

            def show_source_menu():
                menu = QMenu(self)
                menu.setStyleSheet(
                    f"""
                    QMenu {{
                        background-color: #fffafd;
                        border: 1px solid #d5e6f8;
                        border-radius: 12px;
                        color: #425b74;
                        font-family: {UI_FONT};
                        font-size: 12px;
                        padding: 6px;
                    }}
                    QMenu::item {{
                        background: transparent;
                        border-radius: 8px;
                        padding: 9px 18px;
                    }}
                    QMenu::item:selected {{
                        background-color: #eaf5ff;
                        color: #347bb8;
                    }}
                    """
                )
                for source in hidden_sources:
                    url = source["url"]
                    domain = source.get("domain", "") or url
                    content_type = source.get(
                        "content_type",
                        "",
                    )

                    title = domain
                    if content_type and content_type != "NEWS":
                        title += " · " + content_type

                    action = menu.addAction(title)
                    action.triggered.connect(
                        lambda checked=False, target=url:
                        QDesktopServices.openUrl(QUrl(target))
                    )

                menu.exec(
                    more_badge.mapToGlobal(
                        more_badge.rect().bottomLeft()
                    )
                )

            more_badge.clicked.connect(show_source_menu)
            self.source_layout.addWidget(
                more_badge,
                0,
                len(visible_sources),
            )

        self.adjustSize()
        self.updateGeometry()

class ChatArea(QWidget):
    def __init__(self, show_welcome=True):
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
        if show_welcome:
            self.add_welcome_message()

    def add_welcome_message(self, message=None):
        self.add_message(
            "Bekki",
            message or (
                "👋 嗨～我是 Bekki 🩵\n\n"
                "今天想聊点什么呀？\n"
                "我可以搜索、读文件、看图片，\n"
                "也会记住重要的事情 ✨"
            ),
        )

    def add_message(self, role, message, sources=None):
        widget = MessageWidget(role, message, sources)
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

    def clear_messages(self):
        while self.message_layout.count():
            item = self.message_layout.takeAt(0)
            if item.widget() is not None:
                item.widget().deleteLater()


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

        self.image_preview = QLabel()
        self.image_preview.setFixedSize(104, 68)
        self.image_preview.setAlignment(Qt.AlignCenter)
        self.image_preview.setVisible(False)
        self.image_preview.setStyleSheet(
            """
            QLabel {
                background-color: #eaf3fc;
                border: 1px solid #d2e5f7;
                border-radius: 9px;
                padding: 2px;
            }
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
        attachment_layout.addWidget(self.image_preview)
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

        self.desktop_button = QPushButton("▣")
        self.desktop_button.setFixedSize(42, 42)
        self.desktop_button.setToolTip("读取当前桌面")
        self.desktop_button.setCursor(Qt.PointingHandCursor)
        self.desktop_button.setStyleSheet(
            """
            QPushButton {
                background: transparent;
                border: none;
                border-radius: 21px;
                color: #6c9bc8;
                font-size: 19px;
                padding: 0;
            }
            QPushButton:hover {
                background-color: #e8f4ff;
                color: #3f86c7;
            }
            QPushButton:disabled { color: #c8d5e1; }
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
        input_layout.addWidget(self.desktop_button)
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
        self.desktop_button.setEnabled(not busy)
        self.document_close_button.setEnabled(not busy)

    def focus_input(self):
        self.input_box.setFocus()

    def connect_send(self, handler):
        self.send_button.clicked.connect(handler)
        self.input_box.returnPressed.connect(handler)

    def connect_attach(self, handler):
        self.attach_button.clicked.connect(handler)

    def connect_desktop_read(self, screen_handler, window_handler, snip_handler):
        menu = QMenu(self.desktop_button)
        menu.setStyleSheet(
            f"""
            QMenu {{ background:#fffafd; border:1px solid #d5e6f8;
            border-radius:10px; color:#425b74; font-family:{UI_FONT};
            font-size:11px; padding:5px; }}
            QMenu::item {{ padding:8px 18px; border-radius:7px; }}
            QMenu::item:selected {{ background:#eaf5ff; color:#347bb8; }}
            """
        )
        screen_action = menu.addAction("▣  读取主显示器")
        window_action = menu.addAction("▢  读取当前活动窗口")
        snip_action = menu.addAction("✂  截图并读取")
        screen_action.triggered.connect(screen_handler)
        window_action.triggered.connect(window_handler)
        snip_action.triggered.connect(snip_handler)
        self.desktop_button.setMenu(menu)

    def set_document(self, file_name):
        self.image_preview.clear()
        self.image_preview.setVisible(False)
        self.attachment_label.setText("📄  " + file_name)
        self.attachment_bar.setVisible(True)

    def set_image(self, file_name, file_path=None):
        self.attachment_label.setText("🖼️  " + file_name)

        preview = QPixmap(file_path) if file_path else QPixmap()
        if preview.isNull():
            self.image_preview.clear()
            self.image_preview.setVisible(False)
        else:
            self.image_preview.setPixmap(
                preview.scaled(
                    100,
                    64,
                    Qt.KeepAspectRatio,
                    Qt.SmoothTransformation,
                )
            )
            self.image_preview.setVisible(True)

        self.attachment_bar.setVisible(True)

    def clear_document(self):
        self.image_preview.clear()
        self.image_preview.setVisible(False)
        self.attachment_label.clear()
        self.attachment_bar.setVisible(False)

    def connect_document_close(self, handler):
        self.document_close_button.clicked.connect(handler)


class BekkiWindow(QWidget):
    def __init__(self, show_welcome=True):
        super().__init__()

        self.setObjectName("mainWindow")
        self.setWindowTitle("Bekki AI")
        self.setWindowIcon(QIcon(resource_path("assets/bekki.ico")))
        self.resize(680, 620)
        self.setMinimumSize(440, 540)
        self.setStyleSheet(
            """
            #mainWindow {
                background-color: #f7faff;
            }
            """
        )

        self.header = HeaderWidget()
        self.chat = ChatArea(show_welcome=show_welcome)
        self.input_area = InputArea()
        self.sidebar = HistorySidebar()

        main_layout = QVBoxLayout()
        main_layout.setContentsMargins(0, 0, 0, 0)
        main_layout.setSpacing(8)
        main_layout.addWidget(self.header)
        main_layout.addWidget(self.chat)
        main_layout.addWidget(self.input_area)

        main_panel = QWidget()
        main_panel.setLayout(main_layout)

        root_layout = QHBoxLayout()
        root_layout.setContentsMargins(12, 12, 16, 16)
        root_layout.setSpacing(10)
        root_layout.addWidget(self.sidebar)
        root_layout.addWidget(main_panel, 1)
        self.setLayout(root_layout)

        self.header.connect_history_toggle(self.toggle_sidebar)

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

    def add_message(self, role, message, sources=None):
        return self.chat.add_message(role, message, sources)

    def add_welcome_message(self, message=None):
        self.chat.add_welcome_message(message)

    def clear_chat(self):
        self.chat.clear_messages()

    def toggle_sidebar(self):
        self.sidebar.setVisible(not self.sidebar.isVisible())
        self.resize(680 if self.sidebar.isVisible() else 440, self.height())

    def set_sessions(self, sessions, active_session_id):
        self.sidebar.set_sessions(sessions, active_session_id)

    def connect_new_chat(self, handler):
        self.sidebar._new_handler = handler

    def connect_session_select(self, handler):
        self.sidebar._select_handler = handler

    def connect_delete_chat(self, handler):
        self.sidebar._delete_handler = handler

    def connect_clear_chat(self, handler):
        self.sidebar._clear_handler = handler

    def connect_reset_context(self, handler):
        self.sidebar._reset_context_handler = handler

    def connect_send(self, handler):
        self.input_area.connect_send(handler)

    def connect_attach(self, handler):
        self.input_area.connect_attach(handler)

    def connect_desktop_read(self, screen_handler, window_handler, snip_handler):
        self.input_area.connect_desktop_read(
            screen_handler,
            window_handler,
            snip_handler,
        )

    def set_document(self, file_name):
        self.input_area.set_document(file_name)

    def set_image(self, file_name, file_path=None):
        self.input_area.set_image(file_name, file_path)

    def clear_document(self):
        self.input_area.clear_document()

    def connect_document_close(self, handler):
        self.input_area.connect_document_close(handler)