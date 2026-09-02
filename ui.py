# Bekki AI
# Created by YW49
# Copyright (c) 2026 YW49. All rights reserved.

import base64
import json
import os
import sys
import re
import math
import weakref
import localization as i18n
import image_loader
import message_markdown
import result_cards
import social_video
import ui_preferences
import shiboken6
from datetime import datetime

os.environ.setdefault("QT_API", "pyside6")

WEBVIEW2_AUDIO_AUTOPLAY_FLAG = "--autoplay-policy=no-user-gesture-required"


def _enable_inline_webview2_audio_policy():
    """Allow sound only in WebViews Bekki creates after an explicit play click."""

    if sys.platform != "win32":
        return False
    variable = "WEBVIEW2_ADDITIONAL_BROWSER_ARGUMENTS"
    current = str(os.environ.get(variable) or "").strip()
    arguments = current.split()
    if WEBVIEW2_AUDIO_AUTOPLAY_FLAG not in arguments:
        os.environ[variable] = " ".join(
            value
            for value in (current, WEBVIEW2_AUDIO_AUTOPLAY_FLAG)
            if value
        )
    return WEBVIEW2_AUDIO_AUTOPLAY_FLAG in str(
        os.environ.get(variable) or ""
    ).split()


INLINE_WEBVIEW2_AUDIO_POLICY_ENABLED = _enable_inline_webview2_audio_policy()
if INLINE_WEBVIEW2_AUDIO_POLICY_ENABLED:
    print(
        "[INLINE VIDEO AUDIO POLICY]",
        "enabled=true",
        "flag=" + WEBVIEW2_AUDIO_AUTOPLAY_FLAG,
    )

from PySide6.QtCore import (
    Qt,
    QBuffer,
    QEvent,
    QIODevice,
    QPoint,
    QPropertyAnimation,
    QTimer,
    QUrl,
    Signal,
)
from PySide6.QtGui import (
    QColor,
    QDesktopServices,
    QFont,
    QFontMetrics,
    QIcon,
    QKeySequence,
    QPainter,
    QPainterPath,
    QPixmap,
    QImage,
    QShortcut,
    QTextDocument,
    QTextOption,
)
from PySide6.QtWidgets import (
    QApplication,
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QFontComboBox,
    QFormLayout,
    QFrame,
    QGraphicsDropShadowEffect,
    QGraphicsOpacityEffect,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPlainTextEdit,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
    QGridLayout,
    QMenu,
    QMessageBox,
    QSpinBox,
    QWidgetAction,
)

try:
    if sys.platform != "win32":
        raise ImportError("Edge WebView2 inline playback is Windows-only")
    from qtwebview2 import QtWebView2Widget
    from qtwebview2 import DictJsBridge
    INLINE_WEBVIEW2_AVAILABLE = True
    INLINE_WEBVIEW2_IMPORT_ERROR = ""
except Exception as error:
    # The Edge player is optional at import time so a missing runtime or
    # Python bridge never prevents Bekki from starting. Source links remain.
    QtWebView2Widget = None
    DictJsBridge = None
    INLINE_WEBVIEW2_AVAILABLE = False
    INLINE_WEBVIEW2_IMPORT_ERROR = repr(error)

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

MESSAGE_CONTENT_WIDTH = 350
MESSAGE_CONTENT_MAX_WIDTH = 760
MESSAGE_RESPONSIVE_WIDTH_RATIO = 0.72
EVIDENCE_CONTENT_WIDTH = 332
RESULT_CARD_WIDTH_OFFSET = 10
RESULT_CARD_HORIZONTAL_CHROME = 28
SOCIAL_POST_LINK_LABEL = "打开原帖  ↗"
MESSAGE_BUBBLE_MIN_WIDTH = 82
MESSAGE_BUBBLE_HORIZONTAL_CHROME = 28
MESSAGE_BUBBLE_VERTICAL_CHROME = 24
MESSAGE_BUBBLE_NATURAL_WIDTH_SAFETY = 14
MESSAGE_BUBBLE_WRAP_WIDTH_SAFETY = 8

_ACTIVE_VIDEO_CARD_REF = None


def _qt_object_is_alive(value):
    """Return false for Python wrappers whose underlying Qt object is gone."""

    if value is None:
        return False
    try:
        return bool(shiboken6.isValid(value))
    except (RuntimeError, TypeError):
        return False


def _safe_qt_call(value, method_name, *args):
    """Best-effort cleanup call that tolerates already-destroyed Qt children."""

    if not _qt_object_is_alive(value):
        return False
    try:
        getattr(value, method_name)(*args)
        return True
    except Exception:
        return False


def _claim_active_video_card(card):
    """Give one card exclusive playback and stop any previous card."""

    global _ACTIVE_VIDEO_CARD_REF
    previous = (
        _ACTIVE_VIDEO_CARD_REF()
        if isinstance(_ACTIVE_VIDEO_CARD_REF, weakref.ReferenceType)
        else None
    )
    if previous is not None and previous is not card:
        if _qt_object_is_alive(previous):
            try:
                previous_contract = getattr(previous, "_video_contract", None) or {}
                current_contract = getattr(card, "_video_contract", None) or {}
                previous_id = str(
                    previous_contract.get("video_id") or "unknown"
                )
                current_id = str(current_contract.get("video_id") or "unknown")
                previous._stop_inline_video()
                if bool(getattr(previous, "_video_active", False)):
                    print(
                        "[INLINE VIDEO SWITCH]",
                        "previous=" + previous_id,
                        "current=" + current_id,
                        "stopped=false",
                    )
                    return False
                print(
                    "[INLINE VIDEO SWITCH]",
                    "previous=" + previous_id,
                    "current=" + current_id,
                    "stopped=true",
                )
            except Exception as error:
                print("[INLINE VIDEO WEBVIEW2] stale_card_cleanup", repr(error))
                return False
        else:
            print("[INLINE VIDEO WEBVIEW2] stale_card_released")
        _ACTIVE_VIDEO_CARD_REF = None
    if not _qt_object_is_alive(card):
        return False
    _ACTIVE_VIDEO_CARD_REF = weakref.ref(card)
    return True


def _release_active_video_card(card):
    global _ACTIVE_VIDEO_CARD_REF
    current = (
        _ACTIVE_VIDEO_CARD_REF()
        if isinstance(_ACTIVE_VIDEO_CARD_REF, weakref.ReferenceType)
        else None
    )
    if current is card or current is None or not _qt_object_is_alive(current):
        _ACTIVE_VIDEO_CARD_REF = None


def _release_active_video_card_ref(card_ref):
    """Clear the global slot when Qt destroys a card before Python releases it."""

    global _ACTIVE_VIDEO_CARD_REF
    current = (
        _ACTIVE_VIDEO_CARD_REF()
        if isinstance(_ACTIVE_VIDEO_CARD_REF, weakref.ReferenceType)
        else None
    )
    destroyed = card_ref() if isinstance(card_ref, weakref.ReferenceType) else None
    if current is destroyed or current is None or not _qt_object_is_alive(current):
        _ACTIVE_VIDEO_CARD_REF = None


def _inline_video_user_data_folder():
    """Keep the shared Edge player session under Bekki's preserved data tree."""

    launcher = sys.executable if getattr(sys, "frozen", False) else sys.argv[0]
    application_root = os.path.dirname(os.path.abspath(launcher))
    profile_path = os.path.join(
        application_root,
        "data",
        "webview2_video_profile",
    )
    try:
        os.makedirs(profile_path, exist_ok=True)
    except OSError as error:
        print("[INLINE VIDEO WEBVIEW2] profile_unavailable", repr(error))
        return None
    return profile_path


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


class AppearanceDialog(QDialog):
    """Small live-preview editor for chat typography and Bekki's avatar."""

    def __init__(self, preferences, parent=None):
        super().__init__(parent)
        self._original = ui_preferences.normalize_preferences(preferences)
        self._avatar_path = self._original.get("avatar_path", "")
        self.setWindowTitle(i18n.t("appearance"))
        self.setModal(True)
        self.setMinimumWidth(410)
        self.setStyleSheet(
            f"""
            QDialog {{ background-color: {COLORS['canvas']}; }}
            QLabel {{ color: {COLORS['text']}; font-family: {UI_FONT}; }}
            QFontComboBox, QSpinBox {{
                background: white;
                border: 1px solid {COLORS['line']};
                border-radius: 9px;
                color: {COLORS['text']};
                min-height: 32px;
                padding: 0 8px;
            }}
            QPushButton {{
                background: white;
                border: 1px solid {COLORS['line']};
                border-radius: 9px;
                color: {COLORS['blue_dark']};
                min-height: 32px;
                padding: 0 12px;
            }}
            QPushButton:hover {{ background: {COLORS['blue_soft']}; }}
            """
        )

        title = QLabel(i18n.t("appearance_title"))
        title.setStyleSheet(
            f"font-family:{UI_FONT};font-size:18px;font-weight:750;color:{COLORS['blue_dark']};"
        )
        subtitle = QLabel(i18n.t("appearance_subtitle"))
        subtitle.setWordWrap(True)
        subtitle.setStyleSheet(
            f"font-family:{UI_FONT};font-size:11px;color:{COLORS['muted']};"
        )

        self.font_combo = QFontComboBox()
        self.font_combo.setCurrentFont(QFont(self._original["font_family"]))
        self.font_size = QSpinBox()
        self.font_size.setRange(11, 20)
        self.font_size.setSuffix(" pt")
        self.font_size.setValue(self._original["font_size"])

        form = QFormLayout()
        form.setLabelAlignment(Qt.AlignLeft)
        form.setFormAlignment(Qt.AlignTop)
        form.setHorizontalSpacing(14)
        form.setVerticalSpacing(10)
        form.addRow(i18n.t("chat_font"), self.font_combo)
        form.addRow(i18n.t("chat_font_size"), self.font_size)

        self.avatar_preview = QLabel()
        self.avatar_preview.setFixedSize(72, 72)
        self.avatar_preview.setAlignment(Qt.AlignCenter)
        self.avatar_preview.setStyleSheet(
            "background:#eaf6ff;border:1px solid #d7eafb;border-radius:36px;"
        )
        choose_avatar = QPushButton(i18n.t("choose_avatar"))
        choose_avatar.clicked.connect(self._choose_avatar)
        default_avatar = QPushButton(i18n.t("default_avatar"))
        default_avatar.clicked.connect(self._use_default_avatar)
        avatar_buttons = QVBoxLayout()
        avatar_buttons.setContentsMargins(0, 0, 0, 0)
        avatar_buttons.setSpacing(7)
        avatar_buttons.addWidget(choose_avatar)
        avatar_buttons.addWidget(default_avatar)
        avatar_row = QHBoxLayout()
        avatar_row.setSpacing(12)
        avatar_row.addWidget(self.avatar_preview)
        avatar_row.addLayout(avatar_buttons)
        avatar_row.addStretch()

        preview_label = QLabel(i18n.t("preview"))
        preview_label.setStyleSheet(
            f"font-family:{UI_FONT};font-size:11px;font-weight:700;color:{COLORS['muted']};"
        )
        self.text_preview = QLabel(i18n.t("appearance_preview_text"))
        self.text_preview.setWordWrap(True)
        self.text_preview.setStyleSheet(
            "background:white;border:1px solid #dce9f6;border-radius:14px;"
            "color:#35465a;padding:10px 13px;"
        )

        reset_button = QPushButton(i18n.t("restore_defaults"))
        reset_button.clicked.connect(self._restore_defaults)
        standard_button = QDialogButtonBox.StandardButton
        buttons = QDialogButtonBox(
            standard_button.Save | standard_button.Cancel
        )
        buttons.button(standard_button.Save).setText(i18n.t("save"))
        buttons.button(standard_button.Cancel).setText(i18n.t("cancel"))
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        button_row = QHBoxLayout()
        button_row.addWidget(reset_button)
        button_row.addStretch()
        button_row.addWidget(buttons)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 18, 20, 18)
        layout.setSpacing(12)
        layout.addWidget(title)
        layout.addWidget(subtitle)
        layout.addLayout(form)
        layout.addLayout(avatar_row)
        layout.addWidget(preview_label)
        layout.addWidget(self.text_preview)
        layout.addLayout(button_row)

        self.font_combo.currentFontChanged.connect(self._refresh_preview)
        self.font_size.valueChanged.connect(self._refresh_preview)
        self._refresh_preview()

    def _default_avatar_path(self):
        return resource_path("assets/bekki_avatar.jpeg")

    def _refresh_preview(self, *_args):
        family = self.font_combo.currentFont().family()
        size = self.font_size.value()
        self.text_preview.setFont(QFont(family, size))
        avatar_path = self._avatar_path or self._default_avatar_path()
        avatar = create_round_avatar(avatar_path, 72)
        if avatar.isNull():
            self.avatar_preview.setPixmap(QPixmap())
            self.avatar_preview.setText("🩵")
        else:
            self.avatar_preview.setText("")
            self.avatar_preview.setPixmap(avatar)

    def _choose_avatar(self):
        selected, _ = QFileDialog.getOpenFileName(
            self,
            i18n.t("choose_avatar"),
            "",
            "Images (*.png *.jpg *.jpeg *.webp)",
        )
        if selected:
            if QPixmap(selected).isNull():
                QMessageBox.warning(
                    self,
                    i18n.t("appearance"),
                    i18n.t("invalid_avatar"),
                )
                return
            self._avatar_path = selected
            _AVATAR_CACHE.clear()
            self._refresh_preview()

    def _use_default_avatar(self):
        self._avatar_path = ""
        _AVATAR_CACHE.clear()
        self._refresh_preview()

    def _restore_defaults(self):
        defaults = ui_preferences.normalize_preferences({})
        self.font_combo.setCurrentFont(QFont(defaults["font_family"]))
        self.font_size.setValue(defaults["font_size"])
        self._use_default_avatar()

    def preferences(self):
        avatar_path = self._avatar_path
        if avatar_path:
            avatar_path = ui_preferences.persist_avatar(avatar_path)
        return ui_preferences.normalize_preferences({
            "font_family": self.font_combo.currentFont().family(),
            "font_size": self.font_size.value(),
            "avatar_path": avatar_path,
        })

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


class ModernMessageEdit(QPlainTextEdit):
    """Auto-growing multiline input: Enter sends, Shift+Enter adds a line."""

    sendRequested = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        # Keep two complete text rows visible at all times. This prevents the
        # editor from scrolling the first row away as soon as wrapping begins.
        self._minimum_editor_height = 68
        self._maximum_editor_height = 132
        self.setMinimumHeight(self._minimum_editor_height)
        self.setMaximumHeight(self._maximum_editor_height)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self.setTabChangesFocus(True)
        self.setLineWrapMode(QPlainTextEdit.WidgetWidth)
        self.setWordWrapMode(QTextOption.WrapAtWordBoundaryOrAnywhere)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.textChanged.connect(self._schedule_height_adjustment)
        QTimer.singleShot(0, self._adjust_height)

    def _schedule_height_adjustment(self):
        QTimer.singleShot(0, self._adjust_height)

    def _visual_line_count(self):
        """Estimate wrapped display lines using the editor's real font width."""
        available_width = max(80, self.viewport().width() - 8)
        metrics = QFontMetrics(self.font())
        total_lines = 0

        for logical_line in self.toPlainText().split("\n"):
            if not logical_line:
                total_lines += 1
                continue

            line_width = 0
            line_count = 1
            for character in logical_line:
                character_width = max(1, metrics.horizontalAdvance(character))
                if line_width and line_width + character_width > available_width:
                    line_count += 1
                    line_width = character_width
                else:
                    line_width += character_width
            total_lines += line_count

        return max(1, total_lines)

    def _adjust_height(self):
        line_height = max(18, QFontMetrics(self.font()).lineSpacing())
        content_height = self._visual_line_count() * line_height + 22
        target_height = max(
            self._minimum_editor_height,
            min(self._maximum_editor_height, content_height),
        )
        if self.height() != target_height:
            self.setFixedHeight(target_height)
        self.setVerticalScrollBarPolicy(
            Qt.ScrollBarAsNeeded
            if content_height > self._maximum_editor_height
            else Qt.ScrollBarAlwaysOff
        )

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._schedule_height_adjustment()

    def keyPressEvent(self, event):
        if event.key() in {Qt.Key_Return, Qt.Key_Enter}:
            if event.modifiers() & Qt.ShiftModifier:
                super().keyPressEvent(event)
            else:
                event.accept()
                self.sendRequested.emit()
            return
        super().keyPressEvent(event)

    def contextMenuEvent(self, event):
        menu = ModernMenu(self, width=224)
        cursor = self.textCursor()
        selected = cursor.hasSelection()
        menu.add_compact_item(
            i18n.t("undo"), "Ctrl+Z", self.undo, self.document().isUndoAvailable()
        )
        menu.add_compact_item(
            i18n.t("redo"), "Ctrl+Y", self.redo, self.document().isRedoAvailable()
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

        def delete_selection():
            delete_cursor = self.textCursor()
            delete_cursor.removeSelectedText()

        menu.add_compact_item(
            i18n.t("delete"), "Delete", delete_selection,
            selected and not self.isReadOnly(), danger=True
        )
        menu.addSeparator()
        menu.add_compact_item(
            i18n.t("select_all"), "Ctrl+A", self.selectAll,
            bool(self.toPlainText())
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


def _chat_font_values(preferences):
    value = ui_preferences.normalize_preferences(preferences)
    family = re.sub(
        r"[^0-9A-Za-z \-\u3400-\u9fff]",
        "",
        value["font_family"],
    ).strip() or ui_preferences.DEFAULTS["font_family"]
    return family, value["font_size"]


def _build_markdown_document(
    markdown,
    highlights=None,
    family=None,
    size=13,
    color="#35465a",
    text_width=None,
):
    """Build the same document used for both rendering and exact measurement."""

    decorated = message_markdown.apply_highlights(markdown, highlights)
    safe_markdown = message_markdown.sanitize_markdown(decorated)
    document = QTextDocument()
    document.setDocumentMargin(0)
    document.setDefaultFont(QFont(family or "Segoe UI Variable", int(size or 13)))
    document.setDefaultStyleSheet(
        "html,body{margin:0;padding:0;color:" + color + ";}"
        "p{margin:0 0 7px 0;}"
        "h1,h2,h3,h4{color:#344b63;margin:6px 0 5px 0;font-weight:700;}"
        "h1{font-size:18px;}h2{font-size:16px;}h3{font-size:14px;}h4{font-size:13px;}"
        "ul,ol{margin-top:3px;margin-bottom:7px;margin-left:18px;}"
        "li{margin-bottom:3px;}"
        "a{color:#347fc3;text-decoration:none;}"
        "code{font-family:'Cascadia Code','Consolas',monospace;"
        "background:#eaf4ff;color:#356f9f;}"
        "blockquote{color:#607d99;border-left:3px solid #b8d7f2;margin-left:4px;}"
        "table{border-collapse:collapse;margin:5px 0;}"
        "th,td{border:1px solid #d7e7f5;padding:4px;}"
    )
    try:
        dialect = getattr(QTextDocument, "MarkdownDialectGitHub", None)
        if dialect is None:
            feature_enum = getattr(QTextDocument, "MarkdownFeature", None)
            dialect = getattr(feature_enum, "MarkdownDialectGitHub", None)
        if dialect is None:
            document.setMarkdown(safe_markdown)
        else:
            document.setMarkdown(safe_markdown, dialect)
    except (AttributeError, TypeError):
        document.setMarkdown(safe_markdown)
    if text_width is not None:
        document.setTextWidth(max(1.0, float(text_width)))
    return document


def _markdown_to_rich_text(markdown, highlights=None, family=None, size=13, color="#35465a"):
    """Render Bekki's safe Markdown subset through Qt's native document engine."""

    document = _build_markdown_document(
        markdown,
        highlights=highlights,
        family=family,
        size=size,
        color=color,
    )
    return document.toHtml()


def _measure_markdown_bubble(
    markdown,
    highlights=None,
    family=None,
    size=13,
    color="#35465a",
    dynamic_width=False,
    maximum_width=None,
):
    """Return a stable outer bubble size without QLabel.heightForWidth()."""

    maximum_width = max(
        MESSAGE_BUBBLE_MIN_WIDTH,
        int(maximum_width or MESSAGE_CONTENT_WIDTH),
    )
    bubble_width = maximum_width
    if dynamic_width:
        natural_document = _build_markdown_document(
            markdown,
            highlights=highlights,
            family=family,
            size=size,
            color=color,
        )
        natural_width = math.ceil(max(0.0, natural_document.idealWidth()))
        bubble_width = min(
            maximum_width,
            max(
                MESSAGE_BUBBLE_MIN_WIDTH,
                natural_width
                + MESSAGE_BUBBLE_HORIZONTAL_CHROME
                + MESSAGE_BUBBLE_NATURAL_WIDTH_SAFETY,
            ),
        )

    content_width = max(
        40,
        bubble_width
        - MESSAGE_BUBBLE_HORIZONTAL_CHROME
        - (MESSAGE_BUBBLE_WRAP_WIDTH_SAFETY if dynamic_width else 0),
    )
    measured_document = _build_markdown_document(
        markdown,
        highlights=highlights,
        family=family,
        size=size,
        color=color,
        text_width=content_width,
    )
    document_height = measured_document.documentLayout().documentSize().height()
    bubble_height = max(
        42,
        math.ceil(document_height) + MESSAGE_BUBBLE_VERTICAL_CHROME,
    )
    return bubble_width, bubble_height


def _responsive_message_content_width(viewport_width):
    """Scale the conversation column while keeping long text comfortable."""

    try:
        viewport_width = int(viewport_width)
    except (TypeError, ValueError):
        viewport_width = MESSAGE_CONTENT_WIDTH
    responsive_width = round(
        max(0, viewport_width) * MESSAGE_RESPONSIVE_WIDTH_RATIO
    )
    return min(
        MESSAGE_CONTENT_MAX_WIDTH,
        max(MESSAGE_CONTENT_WIDTH, responsive_width),
    )


def _result_card_width(message_width):
    return max(340, int(message_width) + RESULT_CARD_WIDTH_OFFSET)


def _open_safe_markdown_link(value):
    url = QUrl(str(value or "").strip())
    if url.scheme().lower() == "https" and url.host():
        QDesktopServices.openUrl(url)


def _set_markdown_label(label, markdown, highlights=None, family=None, size=13, color="#35465a"):
    label.setTextFormat(Qt.RichText)
    label.setWordWrap(True)
    label.setTextInteractionFlags(
        Qt.TextSelectableByMouse | Qt.LinksAccessibleByMouse
    )
    label.setOpenExternalLinks(False)
    if not getattr(label, "_bekki_markdown_link_connected", False):
        label.linkActivated.connect(_open_safe_markdown_link)
        label._bekki_markdown_link_connected = True
    label.setText(
        _markdown_to_rich_text(
            markdown,
            highlights=highlights,
            family=family,
            size=size,
            color=color,
        )
    )


class HeaderWidget(QWidget):
    def __init__(self):
        super().__init__()
        self._language_handler = None
        self._task_handler = None
        self._settings_handler = None
        self._fullscreen_handler = None

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

        self.settings_button = QPushButton("⚙")
        self.settings_button.setFixedSize(28, 28)
        self.settings_button.setCursor(Qt.PointingHandCursor)
        self.settings_button.setToolTip(i18n.t("appearance"))
        self.settings_button.setStyleSheet(
            """
            QPushButton {
                background-color: #f5f2ff;
                border: 1px solid #e4dcf7;
                border-radius: 14px;
                color: #7d71a8;
                font-size: 14px;
            }
            QPushButton:hover { background-color: #ece6ff; color: #675991; }
            """
        )

        self.fullscreen_button = QPushButton("⛶")
        self.fullscreen_button.setFixedSize(28, 28)
        self.fullscreen_button.setCursor(Qt.PointingHandCursor)
        self.fullscreen_button.setToolTip(i18n.t("fullscreen_enter"))
        self.fullscreen_button.setStyleSheet(
            """
            QPushButton {
                background-color: #eef8ff;
                border: 1px solid #d4e8f8;
                border-radius: 14px;
                color: #558bb7;
                font-size: 15px;
            }
            QPushButton:hover { background-color: #dff1ff; color: #3378af; }
            QPushButton:pressed { background-color: #d2e9fb; }
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
        title_layout.addWidget(self.fullscreen_button)
        title_layout.addWidget(self.settings_button)
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

    def connect_settings(self, handler):
        self._settings_handler = handler
        self.settings_button.clicked.connect(handler)

    def connect_fullscreen_toggle(self, handler):
        self._fullscreen_handler = handler
        self.fullscreen_button.clicked.connect(handler)

    def set_fullscreen_state(self, enabled):
        self.fullscreen_button.setText("❐" if enabled else "⛶")
        self.fullscreen_button.setToolTip(
            i18n.t("fullscreen_exit" if enabled else "fullscreen_enter")
        )

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
        self.settings_button.setToolTip(i18n.t("appearance"))
        self.set_fullscreen_state(self.window().isFullScreen())

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


class RemoteResultImage(QLabel):
    """Asynchronously loaded result-card image."""

    def __init__(
        self,
        card_type="article",
        fit_mode="cover",
        display_width=None,
    ):
        super().__init__()

        self._current_url = ""
        self._open_target = ""
        self._open_target_is_local = False
        self._image_job = None
        self._fit_mode = "contain" if fit_mode == "contain" else "cover"
        self._source_pixmap = QPixmap()
        self._display_width = max(int(display_width or 430), 220)
        self._compact_placeholder = False

        if self._fit_mode == "contain":
            self.setFixedSize(self._display_width, 240)
        else:
            self.setFixedSize(96, 86)

        self.setAlignment(
            Qt.AlignCenter
        )

        icons = {
            "product": "◈",
            "social_post": "▧",
            "news": "◫",
            "place": "⌖",
            "person": "◉",
            "provider": "✚",
            "service": "◇",
            "article": "↗",
        }

        self.setText(
            icons.get(
                card_type,
                "↗",
            )
        )

        self.setStyleSheet(
            f"""
            QLabel {{
                color: #72a9d8;
                background-color: #edf6ff;
                border: 1px solid #d7e9f8;
                border-radius: 13px;
                font-family: {UI_FONT};
                font-size: 22px;
                font-weight: 600;
            }}
            """
        )

    def load_path(self, path):
        if not isinstance(path, str) or not path.strip():
            return
        path = os.path.abspath(path.strip())
        image = QImage(path)
        if image.isNull():
            print("[RESULT IMAGE FAILED]", path, "Qt could not decode local image.")
            return
        self._current_url = "local:" + path
        self._open_target = path
        self._open_target_is_local = True
        self._apply_image(image)

    def load_url(
        self,
        url,
    ):
        if not isinstance(
            url,
            str,
        ):
            return

        url = url.strip()

        if not url:
            return

        self._current_url = url
        self._open_target = url
        self._open_target_is_local = False

        self._image_job = (
            image_loader.load_image_async(
                url,
                self._on_loaded,
                self._on_failed,
            )
        )

    def _on_loaded(
        self,
        url,
        content,
    ):
        # Ignore an old request if this card
        # has already been reused.
        if url != self._current_url:
            return

        image = QImage()

        if not image.loadFromData(
            content
        ):
            self._on_failed(
                url,
                "Qt could not decode image.",
            )
            return

        self._apply_image(image)
        self._image_job = None

    def _apply_image(self, image):
        pixmap = QPixmap.fromImage(image)

        if pixmap.isNull():
            self._on_failed(
                self._current_url,
                "Image pixmap is empty.",
            )
            return

        self._source_pixmap = pixmap
        self._resize_contain_surface()
        self.setPixmap(self._rounded_cover(self._source_pixmap))

        self.setText("")

        self.setStyleSheet(
            """
            QLabel {
                background-color: #edf6ff;
                border: 1px solid #d7e9f8;
                border-radius: 13px;
            }
            """
        )

        self.setCursor(Qt.PointingHandCursor)

    def set_display_width(self, width):
        """Resize a bound screenshot/cover when the chat column reflows."""

        if self._fit_mode != "contain":
            return
        try:
            width = max(int(width), 220)
        except (TypeError, ValueError):
            return
        if width == self._display_width and self.width() == width:
            return
        self._display_width = width
        if self._compact_placeholder and self._source_pixmap.isNull():
            self.setFixedSize(self._display_width, 118)
            self.updateGeometry()
            return
        self._resize_contain_surface()
        if not self._source_pixmap.isNull():
            self.setPixmap(self._rounded_cover(self._source_pixmap))
        self.updateGeometry()

    def _resize_contain_surface(self):
        if self._fit_mode != "contain":
            return
        target_height = 240
        if not self._source_pixmap.isNull() and self._source_pixmap.width() > 0:
            target_height = round(
                self._display_width
                * self._source_pixmap.height()
                / self._source_pixmap.width()
            )
            responsive_height_cap = max(520, round(self._display_width * 1.05))
            target_height = min(
                max(target_height, 120),
                responsive_height_cap,
            )
        self.setFixedSize(self._display_width, target_height)

    def mousePressEvent(self, event):
        if self._open_target:
            target = (
                QUrl.fromLocalFile(self._open_target)
                if self._open_target_is_local
                else QUrl(self._open_target)
            )
            QDesktopServices.openUrl(target)
        super().mousePressEvent(event)

    def _on_failed(
        self,
        url,
        error,
    ):
        if url != self._current_url:
            return

        print(
            "[RESULT IMAGE FAILED]",
            url,
            error,
        )

        # Keep the placeholder visible.
        self._image_job = None

    def _rounded_cover(
        self,
        source_pixmap,
    ):
        target_size = self.size()

        if self._fit_mode == "contain":
            scaled = source_pixmap.scaled(
                target_size,
                Qt.KeepAspectRatio,
                Qt.SmoothTransformation,
            )
            rounded = QPixmap(target_size)
            rounded.fill(QColor("#edf6ff"))
            painter = QPainter(rounded)
            painter.setRenderHint(QPainter.Antialiasing, True)
            path = QPainterPath()
            path.addRoundedRect(
                0, 0, target_size.width(), target_size.height(), 13, 13
            )
            painter.setClipPath(path)
            painter.drawPixmap(
                (target_size.width() - scaled.width()) // 2,
                (target_size.height() - scaled.height()) // 2,
                scaled,
            )
            painter.end()
            return rounded

        scaled = source_pixmap.scaled(
            target_size,
            Qt.KeepAspectRatioByExpanding,
            Qt.SmoothTransformation,
        )

        x_offset = max(
            0,
            (
                scaled.width()
                - target_size.width()
            )
            // 2,
        )

        y_offset = max(
            0,
            (
                scaled.height()
                - target_size.height()
            )
            // 2,
        )

        cropped = scaled.copy(
            x_offset,
            y_offset,
            target_size.width(),
            target_size.height(),
        )

        rounded = QPixmap(
            target_size
        )

        rounded.fill(
            Qt.transparent
        )

        painter = QPainter(
            rounded
        )

        painter.setRenderHint(
            QPainter.Antialiasing,
            True,
        )

        path = QPainterPath()

        path.addRoundedRect(
            0,
            0,
            target_size.width(),
            target_size.height(),
            13,
            13,
        )

        painter.setClipPath(
            path
        )

        painter.drawPixmap(
            0,
            0,
            cropped,
        )

        painter.end()

        return rounded

class ResultImagePlaceholder(QFrame):
    """Placeholder used until a remote image is loaded."""

    def __init__(
        self,
        card_type="article",
    ):
        super().__init__()

        self.setFixedSize(
            96,
            86,
        )
        self.setObjectName(
            "resultImagePlaceholder"
        )

        icons = {
            "product": "◈",
            "social_post": "▧",
            "news": "◫",
            "place": "⌖",
            "person": "◉",
            "provider": "✚",
            "service": "◇",
            "article": "↗",
        }

        icon = QLabel(
            icons.get(
                card_type,
                "↗",
            )
        )
        icon.setAlignment(
            Qt.AlignCenter
        )
        icon.setStyleSheet(
            f"""
            QLabel {{
                color: #72a9d8;
                background: transparent;
                border: none;
                font-family: {UI_FONT};
                font-size: 22px;
                font-weight: 600;
            }}
            """
        )

        layout = QVBoxLayout()
        layout.setContentsMargins(
            0,
            0,
            0,
            0,
        )
        layout.addWidget(icon)
        self.setLayout(layout)

        self.setStyleSheet(
            """
            QFrame#resultImagePlaceholder {
                background-color: #edf6ff;
                border: 1px solid #d7e9f8;
                border-radius: 13px;
            }
            """
        )




class ResultCard(QFrame):
    """One ordered context -> graph(s) -> link evidence block."""

    def __init__(self, card):
        super().__init__()
        self.card = card if isinstance(card, dict) else {}
        self._evidence_block = message_markdown.evidence_block(self.card)
        self.url = str(self._evidence_block["link"].get("url") or "")
        card_type = str(self.card.get("type") or "article").lower()
        self._video_contract = social_video.social_video_contract(self.url)
        self._video_view = None
        self._video_core = None
        self._video_js_bridge = None
        self._video_event_bindings = []
        self._video_wsgi_app = None
        self._video_active = False
        self._theater_active = False
        self._video_wrapper_loaded = False
        self._companion_enabled = False
        self._companion_messages = []
        self._normal_video_content_width = EVIDENCE_CONTENT_WIDTH
        card_ref = weakref.ref(self)
        self.destroyed.connect(
            lambda *_args, current_ref=card_ref:
                _release_active_video_card_ref(current_ref)
        )

        self.setObjectName("resultCard")
        self.setStyleSheet(
            f"""
            QFrame#resultCard {{
                background-color: #fbfdff;
                border: 1px solid #dce9f6;
                border-radius: 15px;
            }}
            QLabel {{
                background: transparent;
                border: none;
                font-family: {UI_FONT};
            }}
            """
        )

        context_label = QLabel()
        context_label.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
        context_label.setMaximumWidth(EVIDENCE_CONTENT_WIDTH)
        self.context_label = context_label
        _set_markdown_label(
            context_label,
            self._evidence_block.get("context_markdown", ""),
            family="Segoe UI Variable",
            size=11,
            color="#4b647c",
        )

        graph_items = self._evidence_block.get("graphs", [])
        render_items = graph_items or [{}]
        graph_widgets = []
        graph_labels = []
        for index, image_data in enumerate(render_items, start=1):
            image = RemoteResultImage(
                card_type,
                fit_mode="contain",
                display_width=EVIDENCE_CONTENT_WIDTH,
            )
            local_path = str(image_data.get("local_path") or "").strip()
            image_url = str(image_data.get("url") or "").strip()
            if local_path:
                image.load_path(local_path)
            elif image_url:
                image.load_url(image_url)
            else:
                image.setFixedSize(EVIDENCE_CONTENT_WIDTH, 118)
                image._compact_placeholder = True
                image.setToolTip("当前来源没有可验证的预览图片")
            graph_widgets.append(image)
            if graph_items:
                label = str(image_data.get("label") or "图片 " + str(index)).strip()
            else:
                label = "图片（暂无可验证预览）"
            graph_labels.append(label)
        self.graph_widgets = graph_widgets

        self.video_host = QFrame()
        self.video_host.setObjectName("inlineVideoHost")
        self.video_host.setVisible(False)
        self.video_host.setStyleSheet(
            """
            QFrame#inlineVideoHost {
                background-color: #080b10;
                border: 1px solid #caddec;
                border-radius: 13px;
            }
            """
        )
        self.video_host_layout = QVBoxLayout(self.video_host)
        self.video_host_layout.setContentsMargins(0, 0, 0, 0)
        self.video_host_layout.setSpacing(0)

        metadata = self.card.get("metadata")
        if not isinstance(metadata, dict):
            metadata = {}
        source_text = (
            " · ".join(
                str(value).strip()
                for value in (metadata.get("merchant"), metadata.get("brand"))
                if str(value or "").strip()
            )
            or str(metadata.get("author") or "").strip()
            or str(self.card.get("domain") or "").strip()
        )
        source_label = QLabel(source_text)
        source_label.setWordWrap(True)
        source_label.setStyleSheet(
            f"color:#7da1c2;font-family:{UI_FONT};font-size:9px;font-weight:600;"
        )

        fallback_link_label = (
            SOCIAL_POST_LINK_LABEL if card_type == "social_post" else "查看来源  ↗"
        )
        open_button = QPushButton(
            str(self._evidence_block["link"].get("label") or fallback_link_label)
        )
        open_button.setVisible(bool(self.url))
        open_button.setCursor(Qt.PointingHandCursor)
        open_button.setStyleSheet(
            f"""
            QPushButton {{
                background-color: #eaf5ff;
                border: 1px solid #cfe5f8;
                border-radius: 9px;
                color: #3e82bd;
                font-family: {UI_FONT};
                font-size: 10px;
                font-weight: 700;
                padding: 6px 10px;
            }}
            QPushButton:hover {{
                background-color: #dcefff;
                border-color: #a9d1f1;
            }}
            """
        )
        open_button.clicked.connect(self._open_source)

        self.play_button = QPushButton("在 Bekki 播放  ▶")
        self.play_button.setVisible(
            bool(self._video_contract) and INLINE_WEBVIEW2_AVAILABLE
        )
        self.play_button.setCursor(Qt.PointingHandCursor)
        self.play_button.setToolTip("在当前卡片内播放；不会打开新页面")
        self.play_button.setStyleSheet(
            f"""
            QPushButton {{
                background-color: #eef8ff;
                border: 1px solid #c9e3f7;
                border-radius: 9px;
                color: #347fbe;
                font-family: {UI_FONT};
                font-size: 10px;
                font-weight: 700;
                padding: 6px 10px;
            }}
            QPushButton:hover {{
                background-color: #dcefff;
                border-color: #9fcbed;
            }}
            QPushButton:pressed {{ background-color: #cfe7fa; }}
            """
        )
        self.play_button.clicked.connect(self._toggle_inline_video)

        self.theater_button = QPushButton("影院模式  ▣")
        self.theater_button.setVisible(
            bool(self._video_contract) and INLINE_WEBVIEW2_AVAILABLE
        )
        self.theater_button.setCursor(Qt.PointingHandCursor)
        self.theater_button.setToolTip("在 Bekki 页面内放大当前视频")
        self.theater_button.setStyleSheet(
            f"""
            QPushButton {{
                background-color: #172231;
                border: 1px solid #30455e;
                border-radius: 9px;
                color: #d8edff;
                font-family: {UI_FONT};
                font-size: 10px;
                font-weight: 700;
                padding: 6px 10px;
            }}
            QPushButton:hover {{
                background-color: #213247;
                border-color: #5a84aa;
            }}
            QPushButton:pressed {{ background-color: #101923; }}
            """
        )
        self.theater_button.clicked.connect(self._toggle_theater_mode)

        layout = QVBoxLayout()
        layout.setContentsMargins(10, 9, 10, 9)
        layout.setSpacing(6)

        # This explicit order is the core contract: context first, every graph
        # owned by that context next, and the matching link last.
        layout.addWidget(context_label)
        layout.addWidget(self.video_host, 0, Qt.AlignHCenter)
        graph_label_widgets = []
        for label_text, image in zip(graph_labels, graph_widgets):
            graph_label = QLabel(label_text)
            graph_label.setStyleSheet(
                f"color:#6e91b1;font-family:{UI_FONT};font-size:9px;"
                "font-weight:700;padding-top:3px;"
            )
            graph_label_widgets.append(graph_label)
            layout.addWidget(graph_label)
            layout.addWidget(image, 0, Qt.AlignHCenter)
        self.graph_label_widgets = graph_label_widgets

        footer = QHBoxLayout()
        footer.setContentsMargins(0, 2, 0, 0)
        footer.setSpacing(6)
        footer.addWidget(source_label, 1)
        footer.addWidget(self.play_button, 0, Qt.AlignRight)
        footer.addWidget(self.theater_button, 0, Qt.AlignRight)
        footer.addWidget(open_button, 0, Qt.AlignRight)
        layout.addLayout(footer)

        self.setLayout(layout)
        self.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Preferred)
        self.set_content_width(MESSAGE_CONTENT_WIDTH)

    def set_content_width(self, message_width):
        """Keep context, graphs, and link inside one responsive evidence card."""

        card_width = _result_card_width(message_width)
        content_width = max(
            220,
            card_width - RESULT_CARD_HORIZONTAL_CHROME,
        )
        self._normal_video_content_width = content_width
        self.setFixedWidth(card_width)
        self.context_label.setFixedWidth(content_width)
        for image in self.graph_widgets:
            image.set_display_width(content_width)
        self._resize_video_surface(content_width)
        self.context_label.updateGeometry()
        if self.layout() is not None:
            self.layout().invalidate()
        self.updateGeometry()

    def _video_surface_size(self, content_width):
        if self._video_contract and self._video_contract.get("is_short"):
            width = min(max(int(content_width), 220), 405)
            return width, min(round(width * 16 / 9), 720)
        width = max(int(content_width), 220)
        return width, min(max(round(width * 9 / 16), 180), 430)

    def _resize_video_surface(self, content_width):
        if self._theater_active:
            return
        width, height = self._video_surface_size(content_width)
        _safe_qt_call(self.video_host, "setFixedSize", width, height)
        if self._video_view is not None:
            _safe_qt_call(self._video_view, "setFixedSize", width, height)

    def _toggle_inline_video(self):
        if self._video_active:
            self._stop_inline_video()
        else:
            self._start_inline_video()

    def _toggle_theater_mode(self):
        window = self.window()
        if self._theater_active:
            handler = getattr(window, "exit_theater_mode", None)
            if callable(handler):
                handler(self)
            return
        if not self._video_active:
            self._start_inline_video()
        if not self._video_active:
            return
        card_ref = weakref.ref(self)

        def enter():
            card = card_ref()
            if card is None or not _qt_object_is_alive(card) or not card._video_active:
                return
            handler = getattr(card.window(), "enter_theater_mode", None)
            if callable(handler):
                handler(card)

        QTimer.singleShot(0, enter)

    def _theater_video_surface_size(self, available_width, available_height):
        """Fit the video in Bekki's theater layer without distorting its ratio."""

        available_width = max(280, int(available_width))
        available_height = max(180, int(available_height))
        if self._video_contract and self._video_contract.get("is_short"):
            height = min(available_height, 820)
            width = max(220, round(height * 9 / 16))
            if width > available_width:
                width = available_width
                height = round(width * 16 / 9)
            return width, height
        width = min(available_width, round(available_height * 16 / 9))
        height = round(width * 9 / 16)
        return width, height

    def _attach_video_host_to_theater(
        self,
        theater_layout,
        available_width,
        available_height,
    ):
        if not self._video_active or not _qt_object_is_alive(self.video_host):
            return False
        own_layout = self.layout()
        try:
            theater_parent = theater_layout.parentWidget()
        except (AttributeError, RuntimeError):
            theater_parent = None
        if (
            own_layout is None
            or not _qt_object_is_alive(own_layout)
            or not _qt_object_is_alive(theater_parent)
        ):
            return False
        own_layout.removeWidget(self.video_host)
        theater_layout.addWidget(self.video_host, 0, Qt.AlignCenter)
        self._theater_active = True
        self.theater_button.setText("退出影院  ▣")
        self._resize_theater_surface(available_width, available_height)
        self._schedule_inline_geometry_refresh()
        return True

    def _resize_theater_surface(self, available_width, available_height):
        if not self._theater_active:
            return
        width, height = self._theater_video_surface_size(
            available_width,
            available_height,
        )
        _safe_qt_call(self.video_host, "setFixedSize", width, height)
        if self._video_view is not None:
            _safe_qt_call(self._video_view, "setFixedSize", width, height)

    def _restore_video_host_from_theater(self):
        if not self._theater_active:
            return
        parent_widget = None
        if _qt_object_is_alive(self.video_host):
            try:
                parent_widget = self.video_host.parentWidget()
            except RuntimeError:
                parent_widget = None
        parent_layout = (
            parent_widget.layout()
            if _qt_object_is_alive(parent_widget)
            else None
        )
        if parent_layout is not None:
            _safe_qt_call(parent_layout, "removeWidget", self.video_host)
        own_layout = self.layout()
        if _qt_object_is_alive(own_layout) and _qt_object_is_alive(self.video_host):
            own_layout.insertWidget(1, self.video_host, 0, Qt.AlignHCenter)
        self._theater_active = False
        _safe_qt_call(self.theater_button, "setText", "影院模式  ▣")
        self._resize_video_surface(self._normal_video_content_width)
        self._schedule_inline_geometry_refresh()

    def _start_inline_video(self):
        """Create the shared Edge player only after a deliberate click."""

        if (
            self._video_active
            or not self._video_contract
            or not INLINE_WEBVIEW2_AVAILABLE
        ):
            return
        wrapper_url = social_video.webview_wrapper_url(self._video_contract)
        wsgi_app = social_video.webview_wsgi_app(self._video_contract)
        if not wrapper_url or wsgi_app is None:
            return

        if not _claim_active_video_card(self):
            return
        self._video_active = True
        for label in self.graph_label_widgets:
            label.setVisible(False)
        for image in self.graph_widgets:
            image.setVisible(False)

        try:
            js_bridge = DictJsBridge()
            card_ref = weakref.ref(self)

            @js_bridge.bind_js_api_func
            def bekki_companion_event(payload):
                card = card_ref()
                if card is None or not _qt_object_is_alive(card):
                    return False
                return card._on_companion_bridge_message(payload)

            view = QtWebView2Widget(
                url=wrapper_url,
                debug=False,
                context_menus=False,
                background_color="#080b10",
                handle_new_window=False,
                lazyload=True,
                user_data_folder=_inline_video_user_data_folder(),
                no_local_storage=False,
                wsgi_app=wsgi_app,
                wsgi_host_name=social_video.WEBVIEW_WRAPPER_HOST,
                wsgi_executor=2,
                init_settings_hook=self._configure_inline_webview,
                js_apis=js_bridge,
                fullscreen_support=True,
                parent=self.video_host,
            )
        except Exception as error:
            print("[INLINE VIDEO WEBVIEW2] create_failed", repr(error))
            self._video_active = False
            for label in self.graph_label_widgets:
                label.setVisible(True)
            for image in self.graph_widgets:
                image.setVisible(True)
            _release_active_video_card(self)
            return
        view.setContextMenuPolicy(Qt.NoContextMenu)
        view.setStyleSheet(
            "background-color:#080b10;border:none;border-radius:13px;"
        )
        width, height = self._video_surface_size(
            max(220, self.width() - RESULT_CARD_HORIZONTAL_CHROME)
        )
        view.setFixedSize(width, height)
        self._video_view = view
        self._video_js_bridge = js_bridge
        self._video_wsgi_app = wsgi_app
        view.bridge.initialization_done.connect(
            self._on_inline_webview_initialization
        )
        view.bridge.domContentLoaded.connect(self._on_inline_webview_loaded)
        self.video_host_layout.addWidget(view, 0, Qt.AlignCenter)
        self.video_host.setVisible(True)
        self.play_button.setText("停止播放  ■")
        self._schedule_inline_geometry_refresh()

    def _execute_inline_script(self, script):
        """Run one fixed-shape command in Bekki's verified wrapper document."""

        if (
            not self._video_active
            or not self._video_wrapper_loaded
            or self._video_core is None
        ):
            return False
        try:
            self._video_core.ExecuteScriptAsync(str(script))
            return True
        except Exception as error:
            print("[COMPANION WATCH SCRIPT ERROR]", repr(error))
            return False

    def _set_companion_overlay(self, enabled, reset=False):
        self._companion_enabled = bool(enabled)
        if reset:
            self._companion_messages = []
        commands = []
        if reset:
            commands.append("window.BekkiCompanion.reset();")
        commands.append(
            "window.BekkiCompanion.setEnabled("
            + ("true" if self._companion_enabled else "false")
            + ");"
        )
        return self._execute_inline_script(
            "if(window.BekkiCompanion){" + "".join(commands) + "}"
        )

    def _set_companion_busy(self, busy):
        value = "true" if bool(busy) else "false"
        return self._execute_inline_script(
            "if(window.BekkiCompanion){window.BekkiCompanion.setBusy("
            + value
            + ");}"
        )

    def _remember_companion_message(self, role, text):
        role = str(role or "").strip().upper()
        clean = re.sub(r"\s+", " ", str(text or "")).strip()[:320]
        if role not in {"YOU", "BEKKI"} or not clean:
            return ""
        self._companion_messages.append({"role": role, "text": clean})
        self._companion_messages = self._companion_messages[-8:]
        return clean

    def _append_companion_message(self, role, text):
        clean = self._remember_companion_message(role, text)
        if not clean:
            return False
        return self._execute_inline_script(
            "if(window.BekkiCompanion){window.BekkiCompanion.addMessage("
            + json.dumps(str(role or "").strip().upper(), ensure_ascii=False)
            + ","
            + json.dumps(clean, ensure_ascii=False)
            + ");}"
        )

    def companion_history(self):
        return [dict(item) for item in self._companion_messages[-8:]]

    def _on_companion_bridge_message(self, payload):
        """Accept only bounded events delivered by qtwebview2's typed API."""

        if isinstance(payload, str):
            try:
                payload = json.loads(payload)
            except (TypeError, ValueError, json.JSONDecodeError):
                return False
        if not isinstance(payload, dict):
            return False
        message_type = str(payload.get("type") or "").strip()
        if message_type not in {"companion_message", "companion_close"}:
            return False
        handler = getattr(self.window(), "handle_companion_web_message", None)
        if callable(handler):
            return bool(handler(self, payload))
        return False

    def _configure_inline_webview(self, core_webview):
        """Bind one WebView2 control to its verified wrapper and no popups."""

        contract = self._video_contract
        if not self._video_active:
            # A superseded WebView can finish initialization after its card was
            # stopped. Quarantine that late control instead of allowing it to
            # load or regain audio behind the newly selected player.
            try:
                core_webview.IsMuted = True
            except Exception:
                pass
            try:
                core_webview.Stop()
            except Exception:
                pass
            print("[INLINE VIDEO WEBVIEW2] stale_initialization_stopped")
            return

        def navigation_starting(_sender, args):
            target = str(getattr(args, "Uri", "") or "")
            if not social_video.allowed_webview_navigation(target, contract):
                args.Cancel = True
                print("[INLINE VIDEO WEBVIEW2] navigation_blocked", target[:240])

        def new_window_requested(_sender, args):
            args.Handled = True
            print(
                "[INLINE VIDEO WEBVIEW2] popup_blocked",
                str(getattr(args, "Uri", "") or "")[:240],
            )

        def download_starting(_sender, args):
            args.Cancel = True
            print("[INLINE VIDEO WEBVIEW2] download_blocked")

        def audio_state_changed(_sender, _args):
            self._ensure_inline_video_audio("state_changed")

        core_webview.NavigationStarting += navigation_starting
        core_webview.NewWindowRequested += new_window_requested
        core_webview.DownloadStarting += download_starting
        self._video_core = core_webview
        self._video_event_bindings = [
            ("NavigationStarting", navigation_starting),
            ("NewWindowRequested", new_window_requested),
            ("DownloadStarting", download_starting),
        ]
        try:
            core_webview.IsMutedChanged += audio_state_changed
            self._video_event_bindings.append(
                ("IsMutedChanged", audio_state_changed)
            )
        except Exception:
            pass
        try:
            core_webview.IsDocumentPlayingAudioChanged += audio_state_changed
            self._video_event_bindings.append(
                ("IsDocumentPlayingAudioChanged", audio_state_changed)
            )
        except Exception:
            pass
        self._ensure_inline_video_audio("initialized")

    def _ensure_inline_video_audio(self, reason):
        """Unmute the shared WebView2 output after an explicit play action."""

        core_webview = self._video_core
        if core_webview is None or not self._video_active:
            return
        platform = str(self._video_contract.get("platform") or "unknown")
        video_id = str(self._video_contract.get("video_id") or "unknown")
        try:
            core_webview.IsMuted = False
            muted = bool(core_webview.IsMuted)
        except Exception as error:
            print(
                "[INLINE VIDEO AUDIO]",
                "platform=" + platform,
                "video_id=" + video_id,
                "reason=" + str(reason),
                "unmute_failed=" + repr(error),
            )
            return
        try:
            playing = bool(core_webview.IsDocumentPlayingAudio)
        except Exception:
            playing = False
        print(
            "[INLINE VIDEO AUDIO]",
            "platform=" + platform,
            "video_id=" + video_id,
            "reason=" + str(reason),
            "muted=" + str(muted).lower(),
            "playing=" + str(playing).lower(),
        )

    def _schedule_inline_audio_enable(self):
        """Reassert audio after the cross-origin player finishes booting."""

        card_ref = weakref.ref(self)

        def enable_audio(reason):
            card = card_ref()
            if (
                card is not None
                and _qt_object_is_alive(card)
                and card._video_active
            ):
                card._ensure_inline_video_audio(reason)

        QTimer.singleShot(250, lambda: enable_audio("player_loaded_250ms"))
        QTimer.singleShot(1000, lambda: enable_audio("player_loaded_1000ms"))
        QTimer.singleShot(2500, lambda: enable_audio("player_loaded_2500ms"))

    def _detach_inline_webview_events(self):
        core_webview = self._video_core
        bindings = list(self._video_event_bindings)
        self._video_core = None
        self._video_event_bindings = []
        if core_webview is None:
            return
        for event_name, handler in bindings:
            try:
                if event_name == "NavigationStarting":
                    core_webview.NavigationStarting -= handler
                elif event_name == "NewWindowRequested":
                    core_webview.NewWindowRequested -= handler
                elif event_name == "DownloadStarting":
                    core_webview.DownloadStarting -= handler
                elif event_name == "IsMutedChanged":
                    core_webview.IsMutedChanged -= handler
                elif event_name == "IsDocumentPlayingAudioChanged":
                    core_webview.IsDocumentPlayingAudioChanged -= handler
            except Exception:
                pass

    def _on_inline_webview_initialization(self, success, error_message):
        platform = str(self._video_contract.get("platform") or "unknown")
        print(
            "[INLINE VIDEO WEBVIEW2]",
            "platform=" + platform,
            "ready=" + str(bool(success)).lower(),
            ("error=" + str(error_message or "")) if not success else "",
        )
        if not success and self._video_active:
            QTimer.singleShot(0, self._stop_inline_video)

    def _on_inline_webview_loaded(self):
        if not self._video_active:
            return
        platform = str(self._video_contract.get("platform") or "unknown")
        print("[INLINE VIDEO WEBVIEW2] wrapper_loaded platform=" + platform)
        self._video_wrapper_loaded = True
        remembered = self.companion_history()
        self._execute_inline_script(
            "if(window.BekkiCompanion){window.BekkiCompanion.reset();"
            "window.BekkiCompanion.setEnabled("
            + ("true" if self._companion_enabled else "false")
            + ");}"
        )
        for item in remembered:
            self._execute_inline_script(
                "if(window.BekkiCompanion){window.BekkiCompanion.addMessage("
                + json.dumps(item["role"], ensure_ascii=False)
                + ","
                + json.dumps(item["text"], ensure_ascii=False)
                + ");}"
            )
        self._schedule_inline_audio_enable()

    def _stop_inline_video(self, refresh=True):
        """Stop audio immediately, dispose the player, and restore its cover."""

        if self._theater_active:
            handler = getattr(self.window(), "exit_theater_mode", None)
            if callable(handler):
                handler(self)
            else:
                self._restore_video_host_from_theater()

        view = self._video_view
        core_webview = self._video_core
        self._video_view = None
        self._video_wsgi_app = None
        self._video_js_bridge = None
        self._video_active = False
        self._video_wrapper_loaded = False
        self._companion_enabled = False
        self._companion_messages = []
        if core_webview is not None:
            native_stop = True
            try:
                # Stop and mute the native control before detaching callbacks
                # or scheduling QObject deletion.  WebView2 teardown is
                # asynchronous; this prevents the previous card from emitting
                # audio while the next card is being initialized.
                core_webview.IsMuted = True
            except Exception as error:
                print("[INLINE VIDEO WEBVIEW2] mute_on_stop_failed", repr(error))
            try:
                core_webview.Stop()
            except Exception as error:
                native_stop = False
                print("[INLINE VIDEO WEBVIEW2] stop_failed", repr(error))
            print(
                "[INLINE VIDEO STOP]",
                "platform=" + str(
                    (self._video_contract or {}).get("platform") or "unknown"
                ),
                "video_id=" + str(
                    (self._video_contract or {}).get("video_id") or "unknown"
                ),
                "native_stop=" + str(native_stop).lower(),
            )
        self._detach_inline_webview_events()
        if _qt_object_is_alive(view):
            try:
                view.load_url("about:blank")
            except Exception:
                pass
            _safe_qt_call(self.video_host_layout, "removeWidget", view)
            _safe_qt_call(view, "close")
            _safe_qt_call(view, "deleteLater")
        _safe_qt_call(self.video_host, "setVisible", False)
        for label in self.graph_label_widgets:
            _safe_qt_call(label, "setVisible", True)
        for image in self.graph_widgets:
            _safe_qt_call(image, "setVisible", True)
        _safe_qt_call(self.play_button, "setText", "在 Bekki 播放  ▶")
        _release_active_video_card(self)
        if refresh and view is not None:
            self._schedule_inline_geometry_refresh()

    def _schedule_inline_geometry_refresh(self):
        if _qt_object_is_alive(self):
            QTimer.singleShot(0, self._refresh_inline_geometry)

    def _refresh_inline_geometry(self):
        current = self
        for _index in range(4):
            if not _qt_object_is_alive(current):
                break
            try:
                current_layout = current.layout()
            except RuntimeError:
                break
            if current_layout is not None:
                _safe_qt_call(current_layout, "invalidate")
            _safe_qt_call(current, "updateGeometry")
            try:
                current = current.parentWidget()
            except RuntimeError:
                break
            if current is None:
                break

    def _open_source(self):
        target = QUrl(self.url)
        if target.scheme().lower() == "https" and target.host():
            QDesktopServices.openUrl(target)


class ResultCardList(QWidget):
    """Stack each result as its own image-and-text row."""

    def __init__(self):
        super().__init__()

        self._cards = []
        self._content_width = MESSAGE_CONTENT_WIDTH
        self.card_layout = QVBoxLayout()
        self.card_layout.setContentsMargins(
            0,
            4,
            0,
            0,
        )
        self.card_layout.setSpacing(7)

        self.card_host = QVBoxLayout()
        self.card_host.setContentsMargins(0, 0, 0, 0)

        self.card_layout.addLayout(self.card_host)

        self.setLayout(
            self.card_layout
        )
        self.setFixedWidth(_result_card_width(self._content_width))
        self.setVisible(False)

    def set_cards(self, cards):
        self._cards = (
            cards
            if isinstance(cards, list)
            else []
        )

        while self.card_host.count():
            item = self.card_host.takeAt(0)

            widget = item.widget()

            if widget is not None:
                if isinstance(widget, ResultCard):
                    widget._stop_inline_video(refresh=False)
                widget.deleteLater()

        self._cards = [card for card in self._cards[:5] if isinstance(card, dict)]
        self._render_cards()
        self.setVisible(bool(self._cards))
        if self.layout() is not None:
            self.layout().invalidate()
        self.updateGeometry()

    def set_content_width(self, message_width):
        try:
            message_width = max(MESSAGE_CONTENT_WIDTH, int(message_width))
        except (TypeError, ValueError):
            message_width = MESSAGE_CONTENT_WIDTH
        self._content_width = message_width
        self.setFixedWidth(_result_card_width(message_width))
        for index in range(self.card_host.count()):
            card = self.card_host.itemAt(index).widget()
            if isinstance(card, ResultCard):
                card.set_content_width(message_width)
        if self.layout() is not None:
            self.layout().invalidate()
        self.updateGeometry()

    def _render_cards(self):
        while self.card_host.count():
            item = self.card_host.takeAt(0)
            widget = item.widget()
            if widget is not None:
                if isinstance(widget, ResultCard):
                    widget._stop_inline_video(refresh=False)
                widget.deleteLater()

        for card in self._cards:
            card_widget = ResultCard(card)
            card_widget.set_content_width(self._content_width)
            self.card_host.addWidget(card_widget)

    def find_card_by_url(self, url):
        """Return the live result card that owns ``url``, if it still exists."""

        target = str(url or "").strip()
        if not target:
            return None
        for index in range(self.card_host.count()):
            card = self.card_host.itemAt(index).widget()
            if (
                isinstance(card, ResultCard)
                and _qt_object_is_alive(card)
                and str(card.url or "").strip() == target
            ):
                return card
        return None


class MessageWidget(QWidget):
    def __init__(
        self,
        sender,
        text,
        sources=None,
        highlights=None,
        cards=None,
        preferences=None,
    ):
        super().__init__()

        is_user = sender.lower() in {"you", "user", "isaac"}
        self._is_user_message = is_user
        self._preferences = ui_preferences.normalize_preferences(preferences)
        self._content_width = MESSAGE_CONTENT_WIDTH
        outer_layout = QHBoxLayout()
        outer_layout.setContentsMargins(2, 6, 2, 6)
        outer_layout.setSpacing(9)

        avatar_label = QLabel()
        avatar_label.setFixedSize(42, 42)
        self.avatar_label = avatar_label

        self._plain_text = str(text)
        self._highlights = highlights or []
        self._sources = []
        self._card_urls = set()
        self._geometry_refresh_pending = False
        self.bubble = QLabel()
        self.bubble.setWordWrap(True)
        self.bubble.setAlignment(Qt.AlignLeft | Qt.AlignTop)
        self.bubble.setTextInteractionFlags(
            Qt.TextSelectableByMouse | Qt.LinksAccessibleByMouse
        )
        self.bubble.setOpenExternalLinks(False)
        self.bubble.setMaximumWidth(self._content_width)
        self.bubble.setSizePolicy(
            QSizePolicy.Fixed,
            QSizePolicy.Fixed,
        )
        self._render_text()

        name_label = QLabel(sender)
        self.name_label = name_label
        message_layout = QVBoxLayout()
        self.message_layout = message_layout
        message_layout.setContentsMargins(0, 0, 0, 0)
        message_layout.setSpacing(3)
        self.result_cards = ResultCardList()
        self.source_cards = ResultCardList()

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
            # A stable width lets QLabel calculate the full wrapped height
            # when the short thinking text is replaced by a longer reply.
            self.bubble.setFixedWidth(self._content_width)
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
            message_layout.addWidget(
                self.result_cards,
                0,
                Qt.AlignLeft,)
            message_layout.addWidget(
                self.source_cards,
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

        if cards:
            self.set_cards(cards)

        if sources:
            self.set_sources(sources)

        self.apply_preferences(self._preferences)
        QTimer.singleShot(0, self._fit_bubble_height)

    def apply_preferences(self, preferences):
        self._preferences = ui_preferences.normalize_preferences(preferences)
        family, size = _chat_font_values(self._preferences)
        if self._is_user_message:
            name_color = "#a16d86"
            bubble_style = """
                background-color: #f9dce8;
                border: 1px solid #f2cedd;
                color: #3d3440;
            """
        else:
            name_color = "#4f86bd"
            bubble_style = """
                background-color: #ffffff;
                border: 1px solid #dce9f6;
                color: #35465a;
            """
        self.name_label.setStyleSheet(
            f'color:{name_color};font-family:"{family}";font-size:10px;font-weight:700;'
        )
        self.bubble.setStyleSheet(
            f"""
            QLabel {{
                {bubble_style}
                border-radius: 17px;
                font-family: "{family}";
                font-size: {size}px;
                padding: 9px 13px;
            }}
            """
        )
        self._render_text()
        if not self._is_user_message:
            avatar_path = ui_preferences.resolved_avatar_path(
                self._preferences,
                resource_path("assets/bekki_avatar.jpeg"),
            )
            avatar = create_round_avatar(avatar_path, 42)
            if avatar.isNull():
                self.avatar_label.setPixmap(QPixmap())
                self.avatar_label.setText("🩵")
                self.avatar_label.setAlignment(Qt.AlignCenter)
            else:
                self.avatar_label.setText("")
                self.avatar_label.setPixmap(avatar)
        self._fit_bubble_height()

    def set_text(self, text):
        self._plain_text = str(text)
        self._render_text()
        self._fit_bubble_height()

    def set_highlights(self, highlights):
        self._highlights = highlights or []
        self._render_text()
        self._fit_bubble_height()

    def _fit_bubble_height(self):
        """Size rich Markdown from its document layout, not QLabel heuristics."""

        family, size = _chat_font_values(self._preferences)
        color = "#3d3440" if self._is_user_message else "#35465a"
        width, height = _measure_markdown_bubble(
            self._plain_text,
            highlights=self._highlights,
            family=family,
            size=size,
            color=color,
            dynamic_width=self._is_user_message,
            maximum_width=self._content_width,
        )
        self.bubble.setFixedSize(width, height)
        self.bubble.updateGeometry()
        self._schedule_geometry_refresh()

    def set_available_width(self, viewport_width):
        """Reflow this message when the conversation viewport changes size."""

        content_width = _responsive_message_content_width(viewport_width)
        if content_width == self._content_width:
            return
        self._content_width = content_width
        self.bubble.setMaximumWidth(content_width)
        self.result_cards.set_content_width(content_width)
        self.source_cards.set_content_width(content_width)
        self._fit_bubble_height()

    def _schedule_geometry_refresh(self):
        """Let the result signal return before recalculating the whole message."""

        if self._geometry_refresh_pending:
            return
        self._geometry_refresh_pending = True
        QTimer.singleShot(0, self._finish_geometry_refresh)

    def _finish_geometry_refresh(self):
        self._geometry_refresh_pending = False
        self.message_layout.invalidate()
        if self.layout() is not None:
            self.layout().invalidate()
        self.adjustSize()
        self.updateGeometry()

    def set_cards(self, cards):
        cards = [value for value in (cards or []) if isinstance(value, dict)]
        self._card_urls = {
            str(card.get("url") or "").strip()
            for card in cards
            if str(card.get("url") or "").strip()
        }
        self.result_cards.set_cards(cards)
        # Rebuild source evidence after cards so duplicate URLs never appear as
        # detached links below the result that already owns them.
        self.set_sources(self._sources)
        self._schedule_geometry_refresh()

    def _render_text(self):
        family, size = _chat_font_values(self._preferences)
        _set_markdown_label(
            self.bubble,
            self._plain_text,
            highlights=self._highlights,
            family=family,
            size=size,
            color="#3d3440" if self._is_user_message else "#35465a",
        )

    def set_sources(self, sources):
        self._sources = [
            value for value in (sources or []) if isinstance(value, dict)
        ]
        bound_source_cards = result_cards.cards_from_sources(
            self._sources,
            exclude_urls=self._card_urls,
            limit=5,
        )
        self.source_cards.set_cards(bound_source_cards)
        self._schedule_geometry_refresh()

    def find_card_by_url(self, url):
        """Resolve an action target inside either owned card collection."""

        return (
            self.result_cards.find_card_by_url(url)
            or self.source_cards.find_card_by_url(url)
        )

class ChatArea(QWidget):
    def __init__(self, show_welcome=True, preferences=None):
        super().__init__()
        self._preferences = ui_preferences.normalize_preferences(preferences)
        self._responsive_resize_pending = False

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

    def add_message(self, role, message, sources=None, highlights=None,cards=None,):
        widget = MessageWidget(
            role,
            message,
            sources=sources,
            highlights=highlights,
            cards=cards,
            preferences=self._preferences,
        )
        widget.set_available_width(self.scroll.viewport().width())
        self.message_layout.addWidget(widget)
        self.scroll_to_bottom()
        return widget

    def apply_preferences(self, preferences):
        self._preferences = ui_preferences.normalize_preferences(preferences)
        for index in range(self.message_layout.count()):
            widget = self.message_layout.itemAt(index).widget()
            if isinstance(widget, MessageWidget):
                widget.apply_preferences(self._preferences)
        self.scroll_to_bottom()

    def scroll_to_bottom(self):
        QTimer.singleShot(
            0,
            lambda: self.scroll.verticalScrollBar().setValue(
                self.scroll.verticalScrollBar().maximum()
            ),
        )

    def resizeEvent(self, event):
        super().resizeEvent(event)
        if self._responsive_resize_pending:
            return
        self._responsive_resize_pending = True
        QTimer.singleShot(0, self._apply_responsive_message_widths)

    def _apply_responsive_message_widths(self):
        self._responsive_resize_pending = False
        viewport_width = self.scroll.viewport().width()
        for index in range(self.message_layout.count()):
            widget = self.message_layout.itemAt(index).widget()
            if isinstance(widget, MessageWidget):
                widget.set_available_width(viewport_width)
        self.message_layout.invalidate()
        self.container.updateGeometry()

    def clear_messages(self):
        while self.message_layout.count():
            item = self.message_layout.takeAt(0)
            if item.widget() is not None:
                item.widget().deleteLater()

    def find_card_by_url(self, url):
        """Prefer the newest matching card when a reply triggers a UI action."""

        for index in range(self.message_layout.count() - 1, -1, -1):
            widget = self.message_layout.itemAt(index).widget()
            if isinstance(widget, MessageWidget):
                card = widget.find_card_by_url(url)
                if card is not None:
                    return card
        return None


class InputArea(QWidget):
    def __init__(self, preferences=None):
        super().__init__()
        self._desktop_handlers = None
        self._preferences = ui_preferences.normalize_preferences(preferences)

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

        self.input_box = ModernMessageEdit()
        self.input_box.setPlaceholderText(i18n.t("input_placeholder"))
        self.input_box.setMinimumHeight(68)
        self.input_box.setStyleSheet(
            f"""
            QPlainTextEdit {{
                background-color: #ffffff;
                border: 1px solid #d4e1ef;
                border-radius: 24px;
                color: #334155;
                font-family: {UI_FONT};
                font-size: 13px;
                padding: 7px 14px;
            }}
            QPlainTextEdit:focus {{
                border: 1px solid #77b6f3;
            }}
            QPlainTextEdit:disabled {{
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
        input_layout.addWidget(self.attach_button, 0, Qt.AlignBottom)
        input_layout.addWidget(self.desktop_button, 0, Qt.AlignBottom)
        input_layout.addWidget(self.input_box, 1)
        input_layout.addWidget(self.send_button, 0, Qt.AlignBottom)

        layout = QVBoxLayout()
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(4)
        layout.addWidget(self.attachment_bar)
        layout.addWidget(self.status_label)
        layout.addLayout(input_layout)
        self.setLayout(layout)
        self.apply_preferences(self._preferences)

    def apply_preferences(self, preferences):
        self._preferences = ui_preferences.normalize_preferences(preferences)
        family, size = _chat_font_values(self._preferences)
        self.input_box.setFont(QFont(family, size))
        self.input_box.setStyleSheet(
            f"""
            QPlainTextEdit {{
                background-color: #ffffff;
                border: 1px solid #d4e1ef;
                border-radius: 24px;
                color: #334155;
                font-family: "{family}";
                font-size: {size}px;
                padding: 7px 14px;
            }}
            QPlainTextEdit:focus {{ border: 1px solid #77b6f3; }}
            QPlainTextEdit:disabled {{
                background-color: #f4f6f9;
                color: #9ba7b4;
            }}
            """
        )
        self.input_box._schedule_height_adjustment()

    def get_text(self):
        return self.input_box.toPlainText().strip()

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
        self.input_box.sendRequested.connect(handler)

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

        self.ui_preferences = ui_preferences.load_preferences()
        self._windowed_geometry = None
        self._windowed_was_maximized = False
        self.header = HeaderWidget()
        self.chat = ChatArea(
            show_welcome=show_welcome,
            preferences=self.ui_preferences,
        )
        self.input_area = InputArea(preferences=self.ui_preferences)
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

        # Theater mode is a layer inside the Bekki window.  The active card's
        # existing video host is moved here, so playback position and audio do
        # not restart and no browser window or second Qt window is opened.
        self._theater_card_ref = None
        self._companion_watch_handler = None
        self._companion_watch_enabled = False
        self._companion_watch_generation = 0
        self._companion_watch_inflight = False
        self._companion_watch_inflight_kind = ""
        self._companion_watch_last_signature = None
        self._companion_watch_auto_count = 0
        self._companion_watch_pending_message = ""
        self._companion_watch_timer = QTimer(self)
        self._companion_watch_timer.setSingleShot(True)
        self._companion_watch_timer.timeout.connect(
            self._request_automatic_companion_reaction
        )
        self.theater_overlay = QFrame(self)
        self.theater_overlay.setObjectName("theaterOverlay")
        self.theater_overlay.setAttribute(Qt.WA_StyledBackground, True)
        self.theater_overlay.setStyleSheet(
            f"""
            QFrame#theaterOverlay {{
                background-color: #080d14;
                border: none;
            }}
            QFrame#theaterToolbar {{
                background-color: #111b27;
                border: 1px solid #213449;
                border-radius: 12px;
            }}
            QLabel#theaterTitle {{
                color: #e9f5ff;
                font-family: {UI_FONT};
                font-size: 12px;
                font-weight: 700;
            }}
            QPushButton {{
                background-color: #172638;
                border: 1px solid #34516d;
                border-radius: 9px;
                color: #d9edff;
                font-family: {UI_FONT};
                font-size: 10px;
                font-weight: 700;
                padding: 7px 11px;
            }}
            QPushButton:hover {{
                background-color: #21364d;
                border-color: #5f91bd;
            }}
            """
        )
        theater_layout = QVBoxLayout(self.theater_overlay)
        theater_layout.setContentsMargins(18, 14, 18, 18)
        theater_layout.setSpacing(12)

        theater_toolbar = QFrame()
        theater_toolbar.setObjectName("theaterToolbar")
        theater_toolbar_layout = QHBoxLayout(theater_toolbar)
        theater_toolbar_layout.setContentsMargins(12, 8, 10, 8)
        theater_toolbar_layout.setSpacing(8)
        self.theater_title = QLabel("Bekki 影院模式")
        self.theater_title.setObjectName("theaterTitle")
        self.theater_title.setTextInteractionFlags(Qt.TextSelectableByMouse)
        theater_toolbar_layout.addWidget(self.theater_title, 1)
        self.theater_companion_button = QPushButton("Bekki 陪看  ○")
        self.theater_companion_button.setToolTip(
            "在视频右下角打开可输入、可回复的陪看对话框"
        )
        self.theater_fullscreen_button = QPushButton("Bekki 全屏  ⛶")
        self.theater_stop_button = QPushButton("停止播放  ■")
        self.theater_exit_button = QPushButton("退出影院  ×")
        theater_toolbar_layout.addWidget(self.theater_companion_button)
        theater_toolbar_layout.addWidget(self.theater_fullscreen_button)
        theater_toolbar_layout.addWidget(self.theater_stop_button)
        theater_toolbar_layout.addWidget(self.theater_exit_button)
        theater_layout.addWidget(theater_toolbar)

        self.theater_video_host = QFrame()
        self.theater_video_host.setObjectName("theaterVideoHost")
        self.theater_video_host.setStyleSheet(
            "QFrame#theaterVideoHost{background:#05080c;border:none;}"
        )
        self.theater_video_layout = QVBoxLayout(self.theater_video_host)
        self.theater_video_layout.setContentsMargins(0, 0, 0, 0)
        self.theater_video_layout.setSpacing(0)
        self.theater_video_layout.setAlignment(Qt.AlignCenter)
        theater_layout.addWidget(self.theater_video_host, 1)
        self.theater_overlay.setGeometry(self.rect())
        self.theater_overlay.setVisible(False)

        self.theater_fullscreen_button.clicked.connect(self.toggle_fullscreen)
        self.theater_companion_button.clicked.connect(
            self._toggle_companion_watch
        )
        self.theater_stop_button.clicked.connect(self._stop_theater_playback)
        self.theater_exit_button.clicked.connect(
            lambda _checked=False: self.exit_theater_mode()
        )

        self.header.connect_history_toggle(
            self.toggle_sidebar
        )

        self.header.connect_task_toggle(
            self.toggle_task_drawer
        )

        self.header.connect_settings(
            self.open_appearance_settings
        )

        self.header.connect_fullscreen_toggle(
            self.toggle_fullscreen
        )

        self._fullscreen_shortcut = QShortcut(
            QKeySequence("F11"),
            self,
        )
        self._fullscreen_shortcut.setContext(Qt.ApplicationShortcut)
        self._fullscreen_shortcut.activated.connect(self.toggle_fullscreen)
        self._exit_fullscreen_shortcut = QShortcut(
            QKeySequence("Esc"),
            self,
        )
        self._exit_fullscreen_shortcut.setContext(Qt.ApplicationShortcut)
        self._exit_fullscreen_shortcut.activated.connect(
            self._exit_fullscreen_if_active
        )

    def toggle_fullscreen(self):
        """Toggle the entire Bekki workspace without losing window geometry."""

        if self.isFullScreen():
            if self._windowed_was_maximized:
                self.showMaximized()
            else:
                saved_geometry = self._windowed_geometry
                self.showNormal()
                if saved_geometry is not None:
                    self.setGeometry(saved_geometry)
        else:
            self._windowed_geometry = self.geometry()
            self._windowed_was_maximized = self.isMaximized()
            self.showFullScreen()
        QTimer.singleShot(0, self._sync_fullscreen_ui)

    def _exit_fullscreen_if_active(self):
        if self.theater_overlay.isVisible():
            self.exit_theater_mode()
            return
        if self.isFullScreen():
            self.toggle_fullscreen()

    def _sync_fullscreen_ui(self):
        if _qt_object_is_alive(self.header):
            self.header.set_fullscreen_state(self.isFullScreen())
        if _qt_object_is_alive(self.theater_fullscreen_button):
            self.theater_fullscreen_button.setText(
                "退出全屏  ⛶" if self.isFullScreen() else "Bekki 全屏  ⛶"
            )

    def _active_theater_card(self):
        card = self._theater_card_ref() if self._theater_card_ref else None
        if isinstance(card, ResultCard) and _qt_object_is_alive(card):
            return card
        return None

    def _theater_available_size(self):
        width = self.theater_video_host.width()
        height = self.theater_video_host.height()
        if width < 280:
            width = max(280, self.width() - 48)
        if height < 180:
            height = max(180, self.height() - 104)
        return width, height

    def connect_companion_watch(self, handler):
        """Connect the bounded background model used only by theater mode."""

        self._companion_watch_handler = handler

    def companion_watch_active(self):
        return bool(
            self._companion_watch_enabled
            and self._active_theater_card() is not None
        )

    def _toggle_companion_watch(self):
        if self._companion_watch_enabled:
            self._stop_companion_watch()
        else:
            self._start_companion_watch()

    def _start_companion_watch(self):
        card = self._active_theater_card()
        if card is None or not card._video_active:
            return False
        self._companion_watch_generation += 1
        self._companion_watch_enabled = True
        self._companion_watch_inflight = False
        self._companion_watch_inflight_kind = ""
        self._companion_watch_last_signature = None
        self._companion_watch_auto_count = 0
        self._companion_watch_pending_message = ""
        self.theater_companion_button.setText("Bekki 陪看  ●")
        card._set_companion_overlay(True, reset=True)
        card._append_companion_message("BEKKI", "我在这儿，边看边聊吧～")
        self._schedule_companion_reaction(8_000)
        print(
            "[COMPANION WATCH]",
            "active=true",
            "generation=" + str(self._companion_watch_generation),
        )
        return True

    def _stop_companion_watch(self):
        was_active = self._companion_watch_enabled
        self._companion_watch_timer.stop()
        self._companion_watch_generation += 1
        self._companion_watch_enabled = False
        self._companion_watch_inflight = False
        self._companion_watch_inflight_kind = ""
        self._companion_watch_last_signature = None
        self._companion_watch_auto_count = 0
        self._companion_watch_pending_message = ""
        if _qt_object_is_alive(self.theater_companion_button):
            self.theater_companion_button.setText("Bekki 陪看  ○")
        card = self._active_theater_card()
        if card is not None:
            card._set_companion_overlay(False)
            card._set_companion_busy(False)
        if was_active:
            print("[COMPANION WATCH] active=false")

    def _schedule_companion_reaction(self, delay_ms=30_000):
        if self._companion_watch_enabled and self._active_theater_card() is not None:
            self._companion_watch_timer.start(max(1000, int(delay_ms)))

    def _ensure_companion_reaction(self, delay_ms=6000):
        """Keep an earlier proactive deadline instead of postponing it."""

        if not self._companion_watch_timer.isActive():
            self._schedule_companion_reaction(delay_ms)

    def _capture_companion_frame(self, card, request_kind):
        """Capture the native WebView2 surface without opening another window."""

        if card is None or not _qt_object_is_alive(card.video_host):
            return None, None
        host = card.video_host
        try:
            top_left = host.mapToGlobal(QPoint(0, 0))
            center = host.mapToGlobal(host.rect().center())
            screen = QApplication.screenAt(center) or self.screen()
            geometry = screen.geometry()
            pixmap = screen.grabWindow(
                0,
                top_left.x() - geometry.x(),
                top_left.y() - geometry.y(),
                host.width(),
                host.height(),
            )
        except (AttributeError, RuntimeError):
            pixmap = QPixmap()
        if pixmap.isNull():
            try:
                pixmap = host.grab()
            except RuntimeError:
                return None, None
        image = pixmap.toImage()
        if image.isNull() or image.width() < 80 or image.height() < 80:
            return None, None
        is_answer = str(request_kind or "").strip().upper() == "USER_MESSAGE"
        max_width, max_height = (1280, 720) if is_answer else (960, 540)
        jpeg_quality = 84 if is_answer else 72
        if image.width() > max_width or image.height() > max_height:
            image = image.scaled(
                max_width,
                max_height,
                Qt.KeepAspectRatio,
                Qt.SmoothTransformation,
            )
        signature = self._companion_frame_signature(image)
        buffer = QBuffer()
        if not buffer.open(QIODevice.WriteOnly):
            return None, None
        try:
            if not image.save(buffer, "JPG", jpeg_quality):
                return None, None
            encoded = base64.b64encode(bytes(buffer.data())).decode("ascii")
        finally:
            buffer.close()
        print(
            "[COMPANION WATCH FRAME]",
            "kind=" + str(request_kind or "unknown"),
            "size=" + str(image.width()) + "x" + str(image.height()),
            "jpeg_kb=" + str(round(len(encoded) * 3 / 4 / 1024)),
        )
        return encoded, signature

    @staticmethod
    def _companion_frame_signature(image):
        """Return a tiny perceptual signature from above the chat overlay."""

        sample_height = max(1, round(image.height() * 0.68))
        sample = image.copy(0, 0, image.width(), sample_height).scaled(
            8,
            8,
            Qt.IgnoreAspectRatio,
            Qt.SmoothTransformation,
        )
        values = []
        for y in range(8):
            for x in range(8):
                color = sample.pixelColor(x, y)
                values.append(
                    round(
                        (color.red() * 0.299)
                        + (color.green() * 0.587)
                        + (color.blue() * 0.114)
                    )
                )
        average = sum(values) / max(1, len(values))
        signature = 0
        for index, value in enumerate(values):
            if value >= average:
                signature |= 1 << index
        return signature

    def _request_automatic_companion_reaction(self):
        if self._companion_watch_inflight:
            self._schedule_companion_reaction(3500)
            return
        self._request_companion_frame("AUTO_REACTION")

    def _request_companion_frame(self, request_kind, message=""):
        card = self._active_theater_card()
        if not self._companion_watch_enabled or card is None:
            return False
        request_kind = str(request_kind or "").strip().upper()
        if request_kind not in {"AUTO_REACTION", "USER_MESSAGE"}:
            return False
        if self._companion_watch_inflight:
            if request_kind == "USER_MESSAGE":
                self._companion_watch_pending_message = str(message or "")[:320]
            return False
        image_base64, signature = self._capture_companion_frame(card, request_kind)
        if not image_base64:
            if request_kind == "USER_MESSAGE":
                card._append_companion_message(
                    "BEKKI",
                    "这一幕我暂时没看清，不过我还在陪你看～",
                )
                card._set_companion_busy(False)
            self._schedule_companion_reaction(8000)
            return False
        if (
            request_kind == "AUTO_REACTION"
            and self._companion_watch_last_signature is not None
            and (signature ^ self._companion_watch_last_signature).bit_count() < 7
        ):
            self._schedule_companion_reaction(15_000)
            return False
        if request_kind == "AUTO_REACTION":
            self._companion_watch_last_signature = signature
        payload = {
            "request_kind": request_kind,
            "message": str(message or "")[:320],
            "image_base64": image_base64,
            "video_title": str(card.card.get("title") or "")[:220],
            "platform": str(card._video_contract.get("platform") or "")[:40],
            "video_url": str(card._video_contract.get("source_url") or "")[:2048],
            "generation": self._companion_watch_generation,
            "is_first_reaction": (
                request_kind == "AUTO_REACTION"
                and self._companion_watch_auto_count == 0
            ),
            "history": card.companion_history(),
        }
        handler = self._companion_watch_handler
        accepted = bool(callable(handler) and handler(payload))
        if not accepted:
            if request_kind == "USER_MESSAGE":
                card._append_companion_message(
                    "BEKKI",
                    "我现在正忙着处理另一件事，等一下再陪你聊～",
                )
                card._set_companion_busy(False)
            self._schedule_companion_reaction(5000)
            return False
        self._companion_watch_inflight = True
        self._companion_watch_inflight_kind = request_kind
        if request_kind == "USER_MESSAGE":
            card._set_companion_busy(True)
        return True

    def handle_companion_web_message(self, card, payload):
        """Route wrapper input to the current theater session only."""

        current = self._active_theater_card()
        if (
            not self._companion_watch_enabled
            or current is None
            or card is not current
            or not isinstance(payload, dict)
        ):
            return False
        message_type = str(payload.get("type") or "").strip()
        if message_type == "companion_close":
            self._stop_companion_watch()
            return True
        if message_type != "companion_message":
            return False
        message = re.sub(r"\s+", " ", str(payload.get("text") or "")).strip()[:320]
        if not message:
            card._set_companion_busy(False)
            return False
        card._remember_companion_message("YOU", message)
        if self._companion_watch_inflight:
            self._companion_watch_pending_message = message
            return True
        return self._request_companion_frame("USER_MESSAGE", message)

    def deliver_companion_watch_reply(self, payload):
        """Display a worker reply only in the theater session that requested it."""

        card = self._active_theater_card()
        if not isinstance(payload, dict) or card is None:
            return False
        if (
            not self._companion_watch_enabled
            or int(payload.get("generation") or -1)
            != self._companion_watch_generation
            or str(payload.get("video_url") or "")
            != str(card._video_contract.get("source_url") or "")
        ):
            return False
        request_kind = str(payload.get("request_kind") or "").strip().upper()
        self._companion_watch_inflight = False
        self._companion_watch_inflight_kind = ""
        reply = re.sub(r"\s+", " ", str(payload.get("reply") or "")).strip()[:180]
        if bool(payload.get("should_show")) and reply:
            card._append_companion_message("BEKKI", reply)
            if request_kind == "AUTO_REACTION":
                self._companion_watch_auto_count += 1
        pending = self._companion_watch_pending_message
        self._companion_watch_pending_message = ""
        if pending:
            QTimer.singleShot(
                80,
                lambda text=pending: self._request_companion_frame(
                    "USER_MESSAGE",
                    text,
                ),
            )
        else:
            card._set_companion_busy(False)
            if request_kind == "AUTO_REACTION":
                self._schedule_companion_reaction(24_000)
            else:
                # Direct conversation must not push the original proactive
                # deadline farther into the future.
                self._ensure_companion_reaction(6000)
        return True

    def companion_watch_failed(self, payload):
        card = self._active_theater_card()
        if not isinstance(payload, dict) or card is None:
            return False
        if (
            not self._companion_watch_enabled
            or int(payload.get("generation") or -1)
            != self._companion_watch_generation
        ):
            return False
        request_kind = str(payload.get("request_kind") or "").strip().upper()
        self._companion_watch_inflight = False
        self._companion_watch_inflight_kind = ""
        if request_kind == "USER_MESSAGE":
            card._append_companion_message("BEKKI", "刚刚走神了一下，再问我一次吧～")
        elif request_kind == "AUTO_REACTION":
            # A failed first look must be allowed to retry even if the video
            # happens to remain on the same frame.
            self._companion_watch_last_signature = None
        pending = self._companion_watch_pending_message
        self._companion_watch_pending_message = ""
        if pending:
            QTimer.singleShot(
                80,
                lambda text=pending: self._request_companion_frame(
                    "USER_MESSAGE",
                    text,
                ),
            )
        else:
            card._set_companion_busy(False)
            if request_kind == "AUTO_REACTION":
                self._schedule_companion_reaction(8000)
            else:
                self._ensure_companion_reaction(6000)
        return True

    def enter_theater_mode(self, card):
        """Move one already-authorized inline player into Bekki's theater."""

        if (
            not isinstance(card, ResultCard)
            or not _qt_object_is_alive(card)
            or not card._video_active
            or not card._video_contract
        ):
            return False
        current = self._active_theater_card()
        if current is not None and current is not card:
            # A theater switch is a playback switch, not a plain theater exit.
            # Fully destroy the old player before attaching the next one.
            current._stop_inline_video()
        self._stop_companion_watch()
        self._theater_card_ref = weakref.ref(card)
        self.theater_title.setText(
            "Bekki 影院模式 · "
            + re.sub(r"\s+", " ", str(card.card.get("title") or "正在播放")).strip()[:90]
        )
        self.theater_overlay.setGeometry(self.rect())
        self.theater_overlay.setVisible(True)
        self.theater_overlay.raise_()
        width, height = self._theater_available_size()
        if not card._attach_video_host_to_theater(
            self.theater_video_layout,
            width,
            height,
        ):
            self._theater_card_ref = None
            self.theater_overlay.setVisible(False)
            return False
        self.theater_overlay.setFocus(Qt.OtherFocusReason)
        QTimer.singleShot(0, self._sync_theater_geometry)
        print(
            "[INLINE VIDEO THEATER]",
            "platform=" + str(card._video_contract.get("platform") or "unknown"),
            "video_id=" + str(card._video_contract.get("video_id") or "unknown"),
            "active=true",
        )
        return True

    def exit_theater_mode(self, card=None):
        """Return the player to its source card without stopping playback."""

        current = self._active_theater_card()
        if card is not None and current is not None and card is not current:
            return False
        self._stop_companion_watch()
        target = current or (card if isinstance(card, ResultCard) else None)
        if target is not None and _qt_object_is_alive(target):
            target._restore_video_host_from_theater()
        self._theater_card_ref = None
        if _qt_object_is_alive(self.theater_overlay):
            self.theater_overlay.setVisible(False)
        if target is not None and _qt_object_is_alive(target):
            target.setFocus(Qt.OtherFocusReason)
        target_id = (
            str((target._video_contract or {}).get("video_id") or "unknown")
            if target is not None and _qt_object_is_alive(target)
            else "unknown"
        )
        print("[INLINE VIDEO THEATER] video_id=" + target_id, "active=false")
        return True

    def _stop_theater_playback(self):
        card = self._active_theater_card()
        if card is not None:
            card._stop_inline_video()
        else:
            self.theater_overlay.setVisible(False)

    def _sync_theater_geometry(self):
        if not _qt_object_is_alive(self.theater_overlay):
            return
        self.theater_overlay.setGeometry(self.rect())
        if not self.theater_overlay.isVisible():
            return
        self.theater_overlay.raise_()
        card = self._active_theater_card()
        if card is not None:
            width, height = self._theater_available_size()
            card._resize_theater_surface(width, height)

    def enter_theater_for_url(self, url):
        """Start and enlarge the newest result card matching a backend action."""

        card = self.chat.find_card_by_url(url)
        if card is None or card._video_contract is None:
            print("[INLINE VIDEO THEATER] target_not_found", str(url or "")[:220])
            return False
        if card._theater_active:
            return True
        card._toggle_theater_mode()
        return True

    def perform_ui_action(self, action):
        """Execute a closed, backend-authored UI action on Qt's main thread."""

        if not isinstance(action, dict):
            return False
        action_type = str(action.get("type") or "").strip()
        if action_type == "enter_theater_mode":
            return self.enter_theater_for_url(action.get("url"))
        print("[UI ACTION IGNORED]", action_type[:80])
        return False

    def changeEvent(self, event):
        super().changeEvent(event)
        if event.type() == QEvent.WindowStateChange:
            QTimer.singleShot(0, self._sync_fullscreen_ui)
            QTimer.singleShot(0, self._sync_theater_geometry)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        QTimer.singleShot(0, self._sync_theater_geometry)

    def closeEvent(self, event):
        card = self._active_theater_card()
        if card is not None:
            card._stop_inline_video(refresh=False)
        super().closeEvent(event)

    def open_appearance_settings(self):
        dialog = AppearanceDialog(self.ui_preferences, self)
        if dialog.exec() != QDialog.Accepted:
            return
        try:
            preferences = dialog.preferences()
            self.ui_preferences = ui_preferences.save_preferences(preferences)
        except (OSError, ValueError) as error:
            QMessageBox.warning(
                self,
                i18n.t("appearance"),
                i18n.t("appearance_save_failed", error=str(error)),
            )
            return
        self.apply_ui_preferences(self.ui_preferences)

    def apply_ui_preferences(self, preferences):
        self.ui_preferences = ui_preferences.normalize_preferences(preferences)
        _AVATAR_CACHE.clear()
        self.chat.apply_preferences(self.ui_preferences)
        self.input_area.apply_preferences(self.ui_preferences)
        self.input_area.set_status(i18n.t("appearance_saved"))
        QTimer.singleShot(2200, lambda: self.input_area.set_status(""))

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
        cards= None
    ):
        return self.chat.add_message(
            role,
            message,
            sources=sources,
            highlights = highlights,
            cards= cards,
        )

    def add_welcome_message(
        self,
        message=None,
    ):
        self.chat.add_welcome_message(
            message
        )

    def clear_chat(self):
        card = self._active_theater_card()
        if card is not None:
            card._stop_inline_video(refresh=False)
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
            if not self.isFullScreen() and not self.isMaximized():
                self.resize(
                    680,
                    self.height(),
                )

        else:
            self.sidebar.setVisible(
                False
            )
            if not self.isFullScreen() and not self.isMaximized():
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
            if not self.isFullScreen() and not self.isMaximized():
                self.resize(
                    720,
                    self.height(),
                )

        else:
            self.task_drawer.setVisible(
                False
            )
            if not self.isFullScreen() and not self.isMaximized():
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
