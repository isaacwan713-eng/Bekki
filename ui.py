from PySide6.QtCore import Qt,QPropertyAnimation,QParallelAnimationGroup,QPoint
from PySide6.QtGui import (
    QPixmap,
    QPainter,
    QPainterPath
)
from PySide6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
    QFrame,
    QPushButton,
    QGraphicsOpacityEffect,
)


def create_round_avatar(path, size=40):
    pixmap = QPixmap(path)

    if pixmap.isNull():
        return QPixmap()

    pixmap = pixmap.scaled(
        size,
        size,
        Qt.KeepAspectRatioByExpanding,
        Qt.SmoothTransformation
    )

    rounded = QPixmap(size, size)
    rounded.fill(Qt.transparent)

    painter = QPainter(rounded)
    painter.setRenderHint(QPainter.Antialiasing)

    path_circle = QPainterPath()
    path_circle.addEllipse(0, 0, size, size)

    painter.setClipPath(path_circle)
    painter.drawPixmap(0, 0, pixmap)
    painter.end()

    return rounded

class HeaderWidget(QWidget):

    def __init__(self):
        super().__init__()

        layout = QVBoxLayout()
        layout.setContentsMargins(
            20,
            12,
            20,
            10)
        layout.setSpacing(4)

        words = QLabel("🩵 Bekki")
        settings_button = QPushButton("⚙")
        settings_button.setFixedSize(34, 34)

        settings_button.setStyleSheet("""
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
        """)

        title = QHBoxLayout()
        title.addWidget(words)
        title.addStretch()
        title.addWidget(settings_button)
        line = QFrame()
        line.setFrameShape(QFrame.HLine)
        line.setFrameShadow(QFrame.Sunken)

        subtitle = QLabel(
            "Your Personal AI Companion"
        )

        words.setStyleSheet("""
            QLabel {
                font-size: 24px;
                font-weight: bold;
                color: #4da6ff;
                font-family = "Segoe UI Bold"
            }
        """)

        subtitle.setStyleSheet("""
            QLabel {
                font-size: 12px;
                color: #888888;
            }
        """)

        layout.addLayout(title)
        layout.addWidget(subtitle)
        layout.addWidget(line)


        self.setLayout(layout)

class MessageWidget(QWidget):
    def __init__(self, sender, text):
        super().__init__()

        is_user = sender.lower() in ["you", "user", "isaac"]

        outer_layout = QHBoxLayout()
        outer_layout.setContentsMargins(4, 6, 4, 6)
        outer_layout.setSpacing(8)

        avatar_label = QLabel()
        avatar_label.setFixedSize(38, 38)

        self.bubble = QLabel(text)
        self.bubble.adjustSize()
        self.bubble.setWordWrap(True)
        self.bubble.setTextInteractionFlags(
            Qt.TextSelectableByMouse
        )
        self.bubble.setMaximumWidth(280)
        self.bubble.setSizePolicy(
            QSizePolicy.Minimum,
            QSizePolicy.Preferred
        )
        self.bubble.adjustSize()

        name_label = QLabel(sender)
        name_label.setStyleSheet(
            """
            QLabel {
                color: #666666;
                font-size: 11px;
                font-weight: bold;
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
                    border-radius: 19px;
                    font-size: 22px;
                }
                """
            )

            message_layout.addWidget(name_label)
            message_layout.addWidget(
                self.bubble,
                0,
                Qt.AlignRight
            )

            outer_layout.addStretch()
            outer_layout.addLayout(message_layout)
            outer_layout.addWidget(
                avatar_label,
                alignment=Qt.AlignTop
            )

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

            pixmap = QPixmap(
                "assets/bekki_avatar.jpeg"
            )

            if not pixmap.isNull():
                avatar_label.setPixmap(
                    pixmap.scaled(
                        38,
                        38,
                        Qt.KeepAspectRatioByExpanding,
                        Qt.SmoothTransformation
                    )
                )
            else:
                avatar_label.setText("💙")
                avatar_label.setAlignment(Qt.AlignCenter)

            avatar_label.setStyleSheet(
                """
                QLabel {
                    border-radius: 19px;
                    background-color: #dff3ff;
                }
                """
            )
            avatar = create_round_avatar("assets/bekki_avatar.jpeg",40)
            if not avatar.isNull():
                avatar_label.setPixmap(avatar)
            else:
                avatar_label.setText("💙")
                avatar_label.setAlignment(Qt.AlignCenter)

            message_layout.addWidget(name_label)
            message_layout.addWidget(
                self.bubble,
                0,
                Qt.AlignLeft
            )

            outer_layout.addWidget(
                avatar_label,
                alignment=Qt.AlignTop
            )
            outer_layout.addLayout(message_layout)
            outer_layout.addStretch()

        self.setLayout(outer_layout)
        effect = QGraphicsOpacityEffect(self)
        self.setGraphicsEffect(effect)

        self.animation = QPropertyAnimation(effect,b"opacity")
        self.animation.animation.setDuration(220)
        self.animation.setStartValue(0.0)
        self.animation.setEndValue(1.0)

        #start_pos = self.pos() + QPoint(0, 8)
        #end_pos = self.pos()

        #move_animation = QPropertyAnimation(self,b"pos")
        #move_animation.setDuration(220)
        #move_animation.setStartValue(start_pos)
        #move_animation.setEndValue(end_pos)

        #self.animation = QParallelAnimationGroup(self)
        #self.animation.addAnimation(opacity_animation)
        #self.animation.addAnimation(move_animation)

        self.animation.start()

        #self.setMaximumWidth(380)
    def set_text(self, text):
        self.bubble.setText(text)

