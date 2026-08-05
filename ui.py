from PySide6.QtCore import Qt
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

class MessageWidget(QWidget):
    def __init__(self, sender, text):
        super().__init__()

        is_user = sender.lower() in ["you", "user", "isaac"]

        outer_layout = QHBoxLayout()
        outer_layout.setContentsMargins(4, 6, 4, 6)
        outer_layout.setSpacing(8)

        avatar_label = QLabel()
        avatar_label.setFixedSize(38, 38)

        bubble = QLabel(text)
        bubble.setWordWrap(True)
        bubble.setTextInteractionFlags(
            Qt.TextSelectableByMouse
        )
        bubble.setMaximumWidth(380)
        bubble.setSizePolicy(
            QSizePolicy.Maximum,
            QSizePolicy.Preferred
        )

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

            bubble.setStyleSheet(
                """
                QLabel {
                    background-color: #ffd8e8;
                    color: #222222;
                    border-radius: 14px;
                    padding: 12px 14px;
                    font-size: 14px;
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
                bubble,
                alignment=Qt.AlignRight
            )

            outer_layout.addStretch()
            outer_layout.addLayout(message_layout)
            outer_layout.addWidget(
                avatar_label,
                alignment=Qt.AlignTop
            )

        else:
            bubble.setStyleSheet(
                """
                QLabel {
                    background-color: #ffffff;
                    color: #222222;
                    border: 1px solid #e6edf5;
                    border-radius: 14px;
                    padding: 10px 12px;
                    font-size: 14px;
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
                bubble,
                alignment=Qt.AlignLeft
            )

            outer_layout.addWidget(
                avatar_label,
                alignment=Qt.AlignTop
            )
            outer_layout.addLayout(message_layout)
            outer_layout.addStretch()

        self.setLayout(outer_layout)
        self.setMaximumWidth(380)