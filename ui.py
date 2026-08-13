# Bekki AI
# Created by YW49
# Copyright (c) 2026 YW49. All rights reserved.

import os
import sys
import html
import localization as i18n
from datetime import datetime
from PySide6.QtCore import (
    Qt,
    QPropertyAnimation,
    QTimer,
    QUrl,
)
from PySide6.QtGui import (
    QColor,
    QDesktopServices,
    QFontMetrics,
    QIcon,
    QPainter,
    QPainterPath,
    QPixmap,
)
from PySide6.QtWidgets import (
    QApplication,
    QFrame,
    QGraphicsDropShadowEffect,
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
    QWidgetAction,
)

def resource_path(relative_path):
    base_path = getattr(sys, "_MEIPASS", os.path.abspath("."))
    return os.path.join(base_path, relative_path)


UI_FONT = '"Segoe UI Variable", "Microsoft YaHei UI", "Segoe UI"'
_AVATAR_CACHE = {}

COLORS = {
    "canvas": "#f7faff",
    "surface": "#ffffff",
    "surface_soft": "#f2f7fd",
    "line": "#dce8f5",
    "text": "#26384d",
    "muted": "#71849a",
    "blue": "#5ba6ef",
    "blue_dark": "#377fbe",
    "blue_soft": "#eaf5ff",
    "pink": "#f4cfe0",
    "pink_soft": "#fff1f7",
    "danger": "#c96d8e",
}


class ModernMenu(QMenu):
    """Borderless Bekki popup used instead of the native Windows menu."""

    def __init__(self, parent=None, width=272):
        super().__init__(parent)
        self._menu_width = width
        self.setWindowFlags(
            self.windowFlags()
            | Qt.FramelessWindowHint
            | Qt.NoDropShadowWindowHint
        )
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setStyleSheet(
            f"""
            QMenu {{
                background-color: {COLORS['surface']};
                border: 1px solid {COLORS['line']};
                border-radius: 16px;
                padding: 8px;
            }}
            QMenu::separator {{
                height: 1px;
                background-color: {COLORS['line']};
                margin: 5px 10px;
            }}
            """
        )

    def add_modern_item(self, title, subtitle, handler, tone="blue"):
        action = QWidgetAction(self)
        button = QPushButton(title + "\n" + subtitle)
        button.setCursor(Qt.PointingHandCursor)
        button.setFixedWidth(self._menu_width - 18)
        button.setMinimumHeight(58)
        button.setStyleSheet(
            f"""
            QPushButton {{
                background: transparent;
                border: none;
                border-radius: 11px;
                color: {COLORS['text']};
                font-family: {UI_FONT};
                font-size: 12px;
                font-weight: 600;
                line-height: 1.35;
                padding: 9px 12px;
                text-align: left;
            }}
            QPushButton:hover {{
                background-color: {COLORS['blue_soft'] if tone == 'blue' else COLORS['pink_soft']};
                color: {COLORS['blue_dark'] if tone == 'blue' else COLORS['danger']};
            }}
            QPushButton:pressed {{ background-color: #deefff; }}
            """
        )

        def activate():
            self.close()
            handler()

        button.clicked.connect(activate)
        action.setDefaultWidget(button)
        self.addAction(action)
        return action

    def add_compact_item(self, title, shortcut, handler, enabled=True, danger=False):
        action = QWidgetAction(self)
        label = title + (("    " + shortcut) if shortcut else "")
        button = QPushButton(label)
        button.setCursor(Qt.PointingHandCursor if enabled else Qt.ArrowCursor)
        button.setEnabled(enabled)
        button.setFixedWidth(self._menu_width - 18)
        button.setFixedHeight(38)
        button.setStyleSheet(
            f"""
            QPushButton {{
                background: transparent;
                border: none;
                border-radius: 9px;
                color: {COLORS['danger'] if danger else COLORS['text']};
                font-family: {UI_FONT};
                font-size: 12px;
                font-weight: 500;
                padding: 0 11px;
                text-align: left;
            }}
            QPushButton:hover {{
                background-color: {COLORS['pink_soft'] if danger else COLORS['blue_soft']};
                color: {COLORS['danger'] if danger else COLORS['blue_dark']};
            }}
            QPushButton:disabled {{ color: #b8c3cf; }}
            """
        )

        def activate():
            self.close()
            handler()

        button.clicked.connect(activate)
        action.setDefaultWidget(button)
        self.addAction(action)
        return action


class ModernLineEdit(QLineEdit):
    """Line edit with a compact Bekki-styled editing menu."""

    def contextMenuEvent(self, event):
        menu = ModernMenu(self, width=224)
        selected = self.hasSelectedText()
        menu.add_compact_item(
            i18n.t("undo"), "Ctrl+Z", self.undo, self.isUndoAvailable()
        )
        menu.add_compact_item(
            i18n.t("redo"), "Ctrl+Y", self.redo, self.isRedoAvailable()
        )
        menu.addSeparator()
        menu.add_compact_item(
            i18n.t("cut"), "Ctrl+X", self.cut, selected and not self.isReadOnly()
        )
        menu.add_compact_item(i18n.t("copy"), "Ctrl+C", self.copy, selected)
        menu.add_compact_item(
            i18n.t("paste"),
            "Ctrl+V",
            self.paste,
            bool(QApplication.clipboard().text()) and not self.isReadOnly(),
        )
        menu.add_compact_item(
            i18n.t("delete"), "Delete", lambda: self.insert(""),
            selected and not self.isReadOnly(), danger=True
        )
        menu.addSeparator()
        menu.add_compact_item(
            i18n.t("select_all"), "Ctrl+A", self.selectAll, bool(self.text())
        )
        menu.exec(event.globalPos())


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
        self._language_handler = None
        self._task_handler = None

        brand_mark = QLabel("♥")
        brand_mark.setAlignment(Qt.AlignCenter)
        brand_mark.setFixedSize(36, 36)
        brand_mark.setStyleSheet(
            f"""
            QLabel {{
                background: qlineargradient(
                    x1:0, y1:0, x2:1, y2:1,
                    stop:0 #73c4ff,
                    stop:1 #8d9cff
                );
                border: 1px solid #d9eaff;
                border-radius: 18px;
                color: white;
                font-family: {UI_FONT};
                font-size: 16px;
                font-weight: 700;
            }}
            """
        )

        title_label = QLabel("Bekki")
        title_label.setStyleSheet(
            f"""
            QLabel {{
                color: #347fc3;
                font-family: {UI_FONT};
                font-size: 27px;
                font-weight: 750;
                letter-spacing: -0.4px;
            }}
            """
        )

        brand_layout = QHBoxLayout()
        brand_layout.setContentsMargins(0, 0, 0, 0)
        brand_layout.setSpacing(10)
        brand_layout.addWidget(brand_mark)
        brand_layout.addWidget(title_label)

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
        self.history_button.setToolTip(i18n.t("history_toggle"))
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

        self.task_button = QPushButton("✓")
        self.task_button.setFixedSize(28,28)
        self.task_button.setCursor(
            Qt.PointingHandCursor
        )
        self.task_button.setToolTip(i18n.t("tasks"))
        self.task_button.setStyleSheet(
            """
            QPushButton {
                background-color: #f0f9f6;
                border: 1px solid #d4ece3;
                border-radius: 14px;
                color: #58a489;
                font-size: 13px;
                font-weight: 700;
            }

            QPushButton:hover {
                background-color: #def3eb;
                border-color: #acd9c8;
            }

            QPushButton:pressed {
                background-color: #d1ebdf;
            }
            """
        )

        self.language_button = QPushButton(i18n.badge())
        self.language_button.setFixedSize(32, 28)
        self.language_button.setCursor(Qt.PointingHandCursor)
        self.language_button.setToolTip(i18n.t("language"))
        self.language_button.setStyleSheet(
            f"""
            QPushButton {{
                background-color: #fff2f8;
                border: 1px solid #f0d8e4;
                border-radius: 14px;
                color: #a96786;
                font-family: {UI_FONT};
                font-size: 10px;
                font-weight: 700;
            }}
            QPushButton:hover {{ background-color: #ffe7f2; }}
            """
        )
        self.language_button.clicked.connect(self.show_language_menu)

        divider = QFrame()
        divider.setFrameShape(QFrame.HLine)
        divider.setStyleSheet("color: #e2ebf5;")

        title_layout = QHBoxLayout()
        title_layout.setContentsMargins(0, 0, 0, 0)
        title_layout.addLayout(brand_layout)
        title_layout.addStretch()
        title_layout.addWidget(self.task_button)
        title_layout.addWidget(self.language_button)
        title_layout.addWidget(self.history_button)
        title_layout.addWidget(version_badge)

        layout = QVBoxLayout()
        layout.setContentsMargins(20, 14, 20, 7)
        layout.setSpacing(8)
        layout.addLayout(title_layout)
        layout.addWidget(divider)
        self.setLayout(layout)

    def connect_history_toggle(self, handler):
        self.history_button.clicked.connect(handler)

    def connect_language_change(self, handler):
        self._language_handler = handler

    def show_language_menu(self):
        menu = ModernMenu(self.language_button, width=220)
        for code, name in i18n.SUPPORTED_LANGUAGES.items():
            menu.add_compact_item(
                name,
                "✓" if code == i18n.get_language() else "",
                lambda selected=code: self.select_language(selected),
            )
        menu.exec(
            self.language_button.mapToGlobal(
                self.language_button.rect().bottomLeft()
            )
        )

    def select_language(self, language):
        if i18n.set_language(language):
            self.apply_language()
            if self._language_handler:
                self._language_handler(language)

    def apply_language(self):
        self.language_button.setText(i18n.badge())
        self.language_button.setToolTip(i18n.t("language"))
        self.history_button.setToolTip(i18n.t("history_toggle"))
        self.task_button.setToolTip(i18n.t("tasks"))

    def connect_task_toggle(self
                            ,handler,
                            ):
        self._task_handler = handler
        self.task_button.clicked.connect(
            handler
        )


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

        self.title_label = QLabel(i18n.t("chats"))
        self.title_label.setStyleSheet(f"font-family: {UI_FONT}; font-size: 13px; font-weight: 700; color: #4d8fcb;")

        self.new_button = QPushButton(i18n.t("new_chat"))
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

        self.clear_button = QPushButton(i18n.t("clear_chat"))
        self.reset_button = QPushButton(i18n.t("reset_context"))
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
        layout.addWidget(self.title_label)
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

    def apply_language(self):
        self.title_label.setText(i18n.t("chats"))
        self.new_button.setText(i18n.t("new_chat"))
        self.clear_button.setText(i18n.t("clear_chat"))
        self.reset_button.setText(i18n.t("reset_context"))

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

            full_title = str(session.get("title") or i18n.t("new_chat_title"))
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
            delete_button.setToolTip(i18n.t("delete_chat"))
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
    def __init__(self, sender, text, sources=None, highlights=None):
        super().__init__()

        is_user = sender.lower() in {"you", "user", "isaac"}
        outer_layout = QHBoxLayout()
        outer_layout.setContentsMargins(2, 6, 2, 6)
        outer_layout.setSpacing(9)

        avatar_label = QLabel()
        avatar_label.setFixedSize(42, 42)

        self._plain_text = str(text)
        self._highlights = highlights or []
        self.bubble = QLabel()
        self.bubble.setWordWrap(True)
        self.bubble.setTextInteractionFlags(
            Qt.TextSelectableByMouse
        )
        self.bubble.setMaximumWidth(286)
        self.bubble.setSizePolicy(
            QSizePolicy.Minimum,
            QSizePolicy.Preferred,
        )
        self._render_text()

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
        self._plain_text = str(text)
        self._render_text()
        self.bubble.adjustSize()
        self.bubble.updateGeometry()

    def set_highlights(self, highlights):
        self._highlights = highlights or []
        self._render_text()
        self.bubble.adjustSize()
        self.bubble.updateGeometry()

    def _render_text(self):
        styles = {
            "important": "font-weight:700;color:#347fc3;",
            "warning": "font-weight:700;color:#b87532;",
            "critical": "font-weight:700;color:#bd5877;",
            "technical": "font-family:'Cascadia Code','Consolas',monospace;background-color:#eaf4ff;color:#356f9f;",
        }
        ranges = []
        for item in self._highlights[:8]:
            if not isinstance(item, dict):
                continue
            value = str(item.get("text", ""))
            style = str(item.get("style", ""))
            start = self._plain_text.find(value) if value else -1
            end = start + len(value)
            if start < 0 or style not in styles:
                continue
            if any(start < old_end and end > old_start for old_start, old_end, _ in ranges):
                continue
            ranges.append((start, end, style))
        ranges.sort(key=lambda value: value[0])
        parts, cursor = [], 0
        for start, end, style in ranges:
            parts.append(html.escape(self._plain_text[cursor:start]))
            parts.append('<span style="' + styles[style] + '">' + html.escape(self._plain_text[start:end]) + "</span>")
            cursor = end
        parts.append(html.escape(self._plain_text[cursor:]))
        self.bubble.setTextFormat(Qt.RichText if ranges else Qt.PlainText)
        self.bubble.setText("".join(parts).replace("\n", "<br>") if ranges else self._plain_text)

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
                i18n.t("more_sources"),
            )

            def show_source_menu():
                menu = ModernMenu(self, width=300)
                for source in hidden_sources:
                    url = source["url"]
                    domain = source.get("domain", "") or url
                    content_type = source.get(
                        "content_type",
                        "",
                    )

                    subtitle = (
                        content_type
                        if content_type and content_type != "NEWS"
                        else i18n.t("source_open")
                    )
                    menu.add_modern_item(
                        domain,
                        subtitle,
                        lambda target=url: QDesktopServices.openUrl(QUrl(target)),
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

    def add_message(self, role, message, sources=None, highlights=None):
        widget = MessageWidget(role, message, sources, highlights)
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
        self._desktop_handlers = None

        self.attachment_bar = QFrame()
        self.attachment_bar.setVisible(False)
        self.attachment_bar.setStyleSheet(
            f"""
            QFrame {{
                background-color: {COLORS['surface']};
                border: 1px solid {COLORS['line']};
                border-radius: 18px;
            }}
            """
        )

        self.attachment_type = QLabel("IMAGE")
        self.attachment_type.setFixedHeight(20)
        self.attachment_type.setAlignment(Qt.AlignCenter)
        self.attachment_type.setStyleSheet(
            f"""
            QLabel {{
                background-color: {COLORS['blue_soft']};
                border: none;
                border-radius: 10px;
                color: {COLORS['blue_dark']};
                font-family: {UI_FONT};
                font-size: 9px;
                font-weight: 700;
                padding: 0 8px;
            }}
            """
        )

        self.attachment_label = QLabel()
        self.attachment_label.setTextInteractionFlags(Qt.TextSelectableByMouse)
        self.attachment_label.setStyleSheet(
            f"""
            QLabel {{
                background: transparent;
                border: none;
                color: {COLORS['text']};
                font-family: {UI_FONT};
                font-size: 13px;
                font-weight: 600;
                padding: 0;
            }}
            """
        )

        self.attachment_subtitle = QLabel(i18n.t("added"))
        self.attachment_subtitle.setStyleSheet(
            f"""
            QLabel {{
                background: transparent;
                border: none;
                color: {COLORS['muted']};
                font-family: {UI_FONT};
                font-size: 10px;
            }}
            """
        )

        self.image_preview = QLabel()
        self.image_preview.setFixedSize(112, 74)
        self.image_preview.setAlignment(Qt.AlignCenter)
        self.image_preview.setVisible(False)
        self.image_preview.setStyleSheet(
            """
            QLabel {
                background-color: #edf5fd;
                border: none;
                border-radius: 13px;
                padding: 3px;
            }
            """
        )

        self.document_close_button = QPushButton("×")
        self.document_close_button.setFixedSize(27, 27)
        self.document_close_button.setToolTip(i18n.t("remove_attachment"))
        self.document_close_button.setStyleSheet(
            """
            QPushButton {
                background: #f3f7fc;
                border: 1px solid #e1eaf4;
                border-radius: 13px;
                color: #8293a7;
                font-size: 16px;
            }
            QPushButton:hover {
                background-color: #fff0f6;
                border-color: #f3d2df;
                color: #c96d8e;
            }
            QPushButton:pressed {
                background-color: #d2e4f5;
            }
            QPushButton:disabled {
                color: #bbc5cf;
            }
            """
        )

        attachment_text_layout = QVBoxLayout()
        attachment_text_layout.setContentsMargins(0, 0, 0, 0)
        attachment_text_layout.setSpacing(3)
        attachment_heading = QHBoxLayout()
        attachment_heading.setContentsMargins(0, 0, 0, 0)
        attachment_heading.setSpacing(7)
        attachment_heading.addWidget(self.attachment_type, 0, Qt.AlignLeft)
        attachment_heading.addStretch()
        attachment_text_layout.addLayout(attachment_heading)
        attachment_text_layout.addWidget(self.attachment_label)
        attachment_text_layout.addWidget(self.attachment_subtitle)

        attachment_layout = QHBoxLayout(self.attachment_bar)
        attachment_layout.setContentsMargins(9, 9, 9, 9)
        attachment_layout.setSpacing(11)
        attachment_layout.addWidget(self.image_preview)
        attachment_layout.addLayout(attachment_text_layout, 1)
        attachment_layout.addWidget(self.document_close_button, 0, Qt.AlignTop)

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

        self.input_box = ModernLineEdit()
        self.input_box.setPlaceholderText(i18n.t("input_placeholder"))
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
        self.attach_button.setToolTip(i18n.t("attach"))
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

        self.desktop_button = QPushButton("◫")
        self.desktop_button.setFixedSize(42, 42)
        self.desktop_button.setToolTip(i18n.t("desktop"))
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

        self.send_button = QPushButton("↑")
        self.send_button.setFixedSize(44, 44)
        self.send_button.setToolTip(i18n.t("send"))
        self.send_button.setCursor(Qt.PointingHandCursor)
        self.send_button.setStyleSheet(
            f"""
            QPushButton {{
                background: qlineargradient(
                    x1:0, y1:0, x2:1, y2:1,
                    stop:0 #62b7f7,
                    stop:1 #7e8ff5
                );
                border: 1px solid #87bff0;
                border-radius: 14px;
                color: white;
                font-family: {UI_FONT};
                font-size: 23px;
                font-weight: 600;
                padding: 0 0 3px 0;
            }}
            QPushButton:hover {{
                background: qlineargradient(
                    x1:0, y1:0, x2:1, y2:1,
                    stop:0 #50aaf0,
                    stop:1 #6f7fe8
                );
                border-color: #75ade2;
            }}
            QPushButton:pressed {{
                background-color: #588bd8;
                padding-top: 2px;
            }}
            QPushButton:disabled {{
                background-color: #d7e4f1;
                border-color: #d7e4f1;
                color: #f7fbff;
            }}
            """
        )

        send_shadow = QGraphicsDropShadowEffect(self.send_button)
        send_shadow.setBlurRadius(18)
        send_shadow.setOffset(0, 4)
        send_shadow.setColor(QColor(76, 139, 209, 72))
        self.send_button.setGraphicsEffect(send_shadow)

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
        self._desktop_handlers = (screen_handler, window_handler, snip_handler)
        menu = ModernMenu(self.desktop_button)
        menu.add_modern_item(
            i18n.t("screen"),
            i18n.t("screen_desc"),
            screen_handler,
        )
        menu.add_modern_item(
            i18n.t("window"),
            i18n.t("window_desc"),
            window_handler,
        )
        menu.add_modern_item(
            i18n.t("snip"),
            i18n.t("snip_desc"),
            snip_handler,
            tone="pink",
        )
        self.desktop_button.setMenu(menu)

    def apply_language(self):
        self.input_box.setPlaceholderText(i18n.t("input_placeholder"))
        self.attach_button.setToolTip(i18n.t("attach"))
        self.desktop_button.setToolTip(i18n.t("desktop"))
        self.send_button.setToolTip(i18n.t("send"))
        self.document_close_button.setToolTip(i18n.t("remove_attachment"))
        if self._desktop_handlers:
            self.connect_desktop_read(*self._desktop_handlers)

    def set_document(self, file_name):
        self.image_preview.clear()
        self.image_preview.setVisible(False)
        self.attachment_type.setText("DOCUMENT")
        self.attachment_label.setText(file_name)
        self.attachment_subtitle.setText(i18n.t("document_ready"))
        self.attachment_bar.setVisible(True)

    def set_image(self, file_name, file_path=None):
        self.attachment_type.setText(
            "SCREENSHOT" if "screenshot" in file_name.lower() else "IMAGE"
        )
        self.attachment_label.setText(file_name)
        self.attachment_subtitle.setText(i18n.t("image_ready"))

        preview = QPixmap(file_path) if file_path else QPixmap()
        if preview.isNull():
            self.image_preview.clear()
            self.image_preview.setVisible(False)
        else:
            self.image_preview.setPixmap(
                preview.scaled(
                    106,
                    68,
                    Qt.KeepAspectRatioByExpanding,
                    Qt.SmoothTransformation,
                )
            )
            self.image_preview.setVisible(True)

        self.attachment_bar.setVisible(True)

    def clear_document(self):
        self.image_preview.clear()
        self.image_preview.setVisible(False)
        self.attachment_label.clear()
        self.attachment_subtitle.clear()
        self.attachment_bar.setVisible(False)

    def connect_document_close(self, handler):
        self.document_close_button.clicked.connect(handler)


class TaskCard(QFrame):
    """One pending task displayed inside the task drawer."""

    def __init__(
        self,
        task,
        complete_handler=None,
        delete_handler=None,
    ):
        super().__init__()

        self.task = task
        self.task_id = str(
            task.get("id", "")
        )

        self.setObjectName("taskCard")
        self.setStyleSheet(
            f"""
            QFrame#taskCard {{
                background-color: #ffffff;
                border: 1px solid #dce9f6;
                border-radius: 14px;
            }}

            QLabel {{
                border: none;
                background: transparent;
                font-family: {UI_FONT};
            }}
            """
        )

        title = QLabel(
            str(
                task.get(
                    "title",
                    i18n.t("untitled_task"),
                )
            )
        )

        title.setWordWrap(True)
        title.setStyleSheet(
            f"""
            QLabel {{
                color: #344b63;
                font-family: {UI_FONT};
                font-size: 12px;
                font-weight: 700;
            }}
            """
        )

        due_label = QLabel(
            self._due_text(
                task.get("due_at")
            )
        )

        due_label.setStyleSheet(
            f"""
            QLabel {{
                color: #7290ad;
                font-family: {UI_FONT};
                font-size: 10px;
            }}
            """
        )

        recurrence = str(
            task.get(
                "recurrence",
                "NONE",
            )
        ).upper()

        recurrence_label = QLabel(
            self._recurrence_text(
                recurrence
            )
        )

        recurrence_label.setVisible(
            recurrence != "NONE"
        )

        recurrence_label.setStyleSheet(
            f"""
            QLabel {{
                color: #9b6f8c;
                background-color: #fff0f7;
                border: 1px solid #f2d8e5;
                border-radius: 8px;
                font-family: {UI_FONT};
                font-size: 9px;
                font-weight: 700;
                padding: 2px 7px;
            }}
            """
        )

        complete_button = QPushButton("✓")
        complete_button.setFixedSize(27, 27)
        complete_button.setCursor(
            Qt.PointingHandCursor
        )
        complete_button.setToolTip(
            i18n.t("complete_task")
        )
        complete_button.setStyleSheet(
            """
            QPushButton {
                background-color: #eaf8f3;
                border: 1px solid #cceade;
                border-radius: 13px;
                color: #53a486;
                font-size: 13px;
                font-weight: 700;
            }

            QPushButton:hover {
                background-color: #d9f2e8;
                border-color: #9ed8c2;
            }

            QPushButton:pressed {
                background-color: #ccebdd;
            }
            """
        )

        delete_button = QPushButton("×")
        delete_button.setFixedSize(27, 27)
        delete_button.setCursor(
            Qt.PointingHandCursor
        )
        delete_button.setToolTip(
            i18n.t("delete_task")
        )
        delete_button.setStyleSheet(
            """
            QPushButton {
                background-color: #fff3f7;
                border: 1px solid #f2d9e3;
                border-radius: 13px;
                color: #b97691;
                font-size: 15px;
                font-weight: 600;
            }

            QPushButton:hover {
                background-color: #ffe5ef;
                border-color: #eabbd0;
            }

            QPushButton:pressed {
                background-color: #f8d9e6;
            }
            """
        )

        if complete_handler:
            complete_button.clicked.connect(
                lambda checked=False:
                complete_handler(
                    self.task_id
                )
            )

        if delete_handler:
            delete_button.clicked.connect(
                lambda checked=False:
                delete_handler(
                    self.task_id
                )
            )

        metadata_layout = QHBoxLayout()
        metadata_layout.setContentsMargins(
            0,
            0,
            0,
            0,
        )
        metadata_layout.setSpacing(6)
        metadata_layout.addWidget(
            due_label
        )
        metadata_layout.addStretch()
        metadata_layout.addWidget(
            recurrence_label
        )

        button_layout = QHBoxLayout()
        button_layout.setContentsMargins(
            0,
            0,
            0,
            0,
        )
        button_layout.setSpacing(6)
        button_layout.addStretch()
        button_layout.addWidget(
            complete_button
        )
        button_layout.addWidget(
            delete_button
        )

        layout = QVBoxLayout()
        layout.setContentsMargins(
            12,
            11,
            10,
            9,
        )
        layout.setSpacing(7)
        layout.addWidget(title)
        layout.addLayout(
            metadata_layout
        )
        layout.addLayout(
            button_layout
        )

        self.setLayout(layout)

    def _due_text(self, value):
        if not isinstance(value, str):
            return i18n.t(
                "task_time_unknown"
            )

        try:
            due_at = (
                datetime.fromisoformat(
                    value.replace(
                        "Z",
                        "+00:00",
                    )
                )
            )

        except ValueError:
            return i18n.t(
                "task_time_unknown"
            )

        local_due_at = (
            due_at.astimezone()
        )

        current_time = (
            datetime.now().astimezone()
        )

        prefix = "◷ "

        if local_due_at < current_time:
            prefix = "● "

        return (
            prefix
            + local_due_at.strftime(
                "%Y-%m-%d  %H:%M"
            )
        )

    def _recurrence_text(
        self,
        recurrence,
    ):
        keys = {
            "DAILY": "recurrence_daily",
            "WEEKLY": "recurrence_weekly",
            "MONTHLY": "recurrence_monthly",
        }

        key = keys.get(
            recurrence
        )

        return (
            i18n.t(key)
            if key
            else ""
        )


class TaskDrawer(QFrame):
    """Modern right-side panel for pending tasks."""

    def __init__(self):
        super().__init__()

        self._complete_handler = None
        self._delete_handler = None
        self._tasks = []

        self.setObjectName(
            "taskDrawer"
        )

        self.setFixedWidth(260)

        self.setStyleSheet(
            f"""
            QFrame#taskDrawer {{
                background-color: #f9fbff;
                border: 1px solid #dce8f5;
                border-radius: 18px;
            }}

            QScrollArea {{
                background: transparent;
                border: none;
            }}

            QScrollArea > QWidget >
            QWidget {{
                background: transparent;
            }}
            """
        )

        self.title_label = QLabel(
            i18n.t("tasks")
        )

        self.title_label.setStyleSheet(
            f"""
            QLabel {{
                color: #4587c2;
                font-family: {UI_FONT};
                font-size: 15px;
                font-weight: 750;
            }}
            """
        )

        self.count_label = QLabel("0")
        self.count_label.setAlignment(
            Qt.AlignCenter
        )
        self.count_label.setFixedSize(
            24,
            24,
        )
        self.count_label.setStyleSheet(
            f"""
            QLabel {{
                color: #6e9bc4;
                background-color: #edf6ff;
                border: 1px solid #d4e8fa;
                border-radius: 12px;
                font-family: {UI_FONT};
                font-size: 10px;
                font-weight: 700;
            }}
            """
        )

        title_layout = QHBoxLayout()
        title_layout.setContentsMargins(
            0,
            0,
            0,
            0,
        )
        title_layout.addWidget(
            self.title_label
        )
        title_layout.addStretch()
        title_layout.addWidget(
            self.count_label
        )

        self.empty_label = QLabel(
            i18n.t("no_pending_tasks")
        )
        self.empty_label.setAlignment(
            Qt.AlignCenter
        )
        self.empty_label.setWordWrap(
            True
        )
        self.empty_label.setStyleSheet(
            f"""
            QLabel {{
                color: #91a7bb;
                font-family: {UI_FONT};
                font-size: 11px;
                padding: 30px 12px;
            }}
            """
        )

        self.task_container = QWidget()

        self.task_layout = QVBoxLayout()
        self.task_layout.setContentsMargins(
            0,
            0,
            0,
            0,
        )
        self.task_layout.setSpacing(8)
        self.task_layout.addStretch()

        self.task_container.setLayout(
            self.task_layout
        )

        scroll_area = QScrollArea()
        scroll_area.setWidgetResizable(
            True
        )
        scroll_area.setHorizontalScrollBarPolicy(
            Qt.ScrollBarAlwaysOff
        )
        scroll_area.setWidget(
            self.task_container
        )

        layout = QVBoxLayout()
        layout.setContentsMargins(
            12,
            14,
            12,
            12,
        )
        layout.setSpacing(10)
        layout.addLayout(
            title_layout
        )
        layout.addWidget(
            self.empty_label
        )
        layout.addWidget(
            scroll_area,
            1,
        )

        self.setLayout(layout)
        self.setVisible(False)

    def set_tasks(self, tasks):
        self._tasks = (
            tasks
            if isinstance(tasks, list)
            else []
        )

        while (
            self.task_layout.count()
            > 1
        ):
            item = (
                self.task_layout.takeAt(
                    0
                )
            )

            widget = item.widget()

            if widget is not None:
                widget.deleteLater()

        for task in self._tasks:
            card = TaskCard(
                task,
                self._complete_handler,
                self._delete_handler,
            )

            self.task_layout.insertWidget(
                self.task_layout.count() - 1,
                card,
            )

        self.count_label.setText(
            str(len(self._tasks))
        )

        self.empty_label.setVisible(
            not self._tasks
        )

    def connect_complete(
        self,
        handler,
    ):
        self._complete_handler = handler
        self.set_tasks(self._tasks)

    def connect_delete(
        self,
        handler,
    ):
        self._delete_handler = handler
        self.set_tasks(self._tasks)

    def apply_language(self):
        self.title_label.setText(
            i18n.t("tasks")
        )

        self.empty_label.setText(
            i18n.t(
                "no_pending_tasks"
            )
        )

        self.set_tasks(self._tasks)


class BekkiWindow(QWidget):
    def __init__(
        self,
        show_welcome=True,
    ):
        super().__init__()

        self.setObjectName(
            "mainWindow"
        )
        self.setWindowTitle(
            "Bekki AI"
        )
        self.setWindowIcon(
            QIcon(
                resource_path(
                    "assets/bekki.ico"
                )
            )
        )
        self.resize(680, 620)
        self.setMinimumSize(
            440,
            540,
        )
        self.setStyleSheet(
            """
            #mainWindow {
                background-color: #f7faff;
            }
            """
        )

        self.header = HeaderWidget()
        self.chat = ChatArea(
            show_welcome=show_welcome
        )
        self.input_area = InputArea()
        self.sidebar = HistorySidebar()
        self.task_drawer = TaskDrawer()

        main_layout = QVBoxLayout()
        main_layout.setContentsMargins(
            0,
            0,
            0,
            0,
        )
        main_layout.setSpacing(8)
        main_layout.addWidget(
            self.header
        )
        main_layout.addWidget(
            self.chat
        )
        main_layout.addWidget(
            self.input_area
        )

        main_panel = QWidget()
        main_panel.setLayout(
            main_layout
        )

        root_layout = QHBoxLayout()
        root_layout.setContentsMargins(
            12,
            12,
            16,
            16,
        )
        root_layout.setSpacing(10)
        root_layout.addWidget(
            self.sidebar
        )
        root_layout.addWidget(
            main_panel,
            1,
        )
        root_layout.addWidget(
            self.task_drawer
        )

        self.setLayout(
            root_layout
        )

        self.header.connect_history_toggle(
            self.toggle_sidebar
        )

        self.header.connect_task_toggle(
            self.toggle_task_drawer
        )

    def connect_language_change(
        self,
        handler,
    ):
        self.header.connect_language_change(
            handler
        )

    def apply_language(self):
        self.header.apply_language()
        self.sidebar.apply_language()
        self.task_drawer.apply_language()
        self.input_area.apply_language()

    def get_message(self):
        return (
            self.input_area.get_text()
        )

    def clear_input(self):
        self.input_area.clear()

    def set_status(self, text):
        self.input_area.set_status(
            text
        )

    def set_busy(self, busy):
        self.input_area.set_busy(
            busy
        )

    def focus_input(self):
        self.input_area.focus_input()

    def add_message(
        self,
        role,
        message,
        sources=None,
        highlights=None,
    ):
        return self.chat.add_message(
            role,
            message,
            sources,
            highlights,
        )

    def add_welcome_message(
        self,
        message=None,
    ):
        self.chat.add_welcome_message(
            message
        )

    def clear_chat(self):
        self.chat.clear_messages()

    def toggle_sidebar(self):
        opening = (
            not self.sidebar.isVisible()
        )

        if opening:
            self.task_drawer.setVisible(
                False
            )
            self.sidebar.setVisible(
                True
            )
            self.resize(
                680,
                self.height(),
            )

        else:
            self.sidebar.setVisible(
                False
            )
            self.resize(
                440,
                self.height(),
            )

    def toggle_task_drawer(self):
        opening = (
            not self.task_drawer.isVisible()
        )

        if opening:
            self.sidebar.setVisible(
                False
            )
            self.task_drawer.setVisible(
                True
            )
            self.resize(
                720,
                self.height(),
            )

        else:
            self.task_drawer.setVisible(
                False
            )
            self.resize(
                440,
                self.height(),
            )

    def set_tasks(self, task_items):
        self.task_drawer.set_tasks(
            task_items
        )

    def connect_task_complete(
        self,
        handler,
    ):
        self.task_drawer.connect_complete(
            handler
        )

    def connect_task_delete(
        self,
        handler,
    ):
        self.task_drawer.connect_delete(
            handler
        )

    def set_sessions(
        self,
        sessions,
        active_session_id,
    ):
        self.sidebar.set_sessions(
            sessions,
            active_session_id,
        )

    def connect_new_chat(
        self,
        handler,
    ):
        self.sidebar._new_handler = (
            handler
        )

    def connect_session_select(
        self,
        handler,
    ):
        self.sidebar._select_handler = (
            handler
        )

    def connect_delete_chat(
        self,
        handler,
    ):
        self.sidebar._delete_handler = (
            handler
        )

    def connect_clear_chat(
        self,
        handler,
    ):
        self.sidebar._clear_handler = (
            handler
        )

    def connect_reset_context(
        self,
        handler,
    ):
        self.sidebar._reset_context_handler = (
            handler
        )

    def connect_send(
        self,
        handler,
    ):
        self.input_area.connect_send(
            handler
        )

    def connect_attach(
        self,
        handler,
    ):
        self.input_area.connect_attach(
            handler
        )

    def connect_desktop_read(
        self,
        screen_handler,
        window_handler,
        snip_handler,
    ):
        self.input_area.connect_desktop_read(
            screen_handler,
            window_handler,
            snip_handler,
        )

    def set_document(
        self,
        file_name,
    ):
        self.input_area.set_document(
            file_name
        )

    def set_image(
        self,
        file_name,
        file_path=None,
    ):
        self.input_area.set_image(
            file_name,
            file_path,
        )

    def clear_document(self):
        self.input_area.clear_document()

    def connect_document_close(
        self,
        handler,
    ):
        self.input_area.connect_document_close(
            handler
        )
