"""About window (version, updates, what's new) and the feedback form."""
from __future__ import annotations

import sys
from pathlib import Path
from typing import Callable

from PySide6.QtCore import QUrl, Qt
from PySide6.QtGui import QDesktopServices, QGuiApplication, QPixmap
from PySide6.QtWidgets import (QCheckBox, QComboBox, QDialog, QHBoxLayout, QLabel, QLineEdit,
                               QPlainTextEdit, QPushButton, QVBoxLayout)

import feedback
from i18n import tr
from version import APP_VERSION


def resource_path(relative: str) -> Path:
    """A bundled file: next to the sources, or inside the .app (PyInstaller)."""
    base = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent.parent))
    return base / relative


def open_url(url: str) -> None:
    QDesktopServices.openUrl(QUrl(url))


class AboutDialog(QDialog):
    def __init__(self, parent, check_updates: Callable[[], None], whats_new: Callable[[], None],
                 send_feedback: Callable[[], None], info: Callable[[], str]):
        super().__init__(parent)
        self.setWindowTitle(tr("About Xbox MIDI Bridge", "За Xbox MIDI Bridge"))
        self._info = info
        lay = QVBoxLayout(self)
        lay.setSpacing(12)

        head = QHBoxLayout()
        icon = QLabel()
        pm = QPixmap(str(resource_path("assets/icon.png")))
        if not pm.isNull():
            icon.setPixmap(pm.scaled(72, 72, Qt.KeepAspectRatio, Qt.SmoothTransformation))
        head.addWidget(icon)
        col = QVBoxLayout()
        title = QLabel("Xbox MIDI Bridge")
        title.setStyleSheet("font-size: 20px; font-weight: 700;")
        self.version_label = QLabel(tr("Version {}", "Версия {}").format(APP_VERSION))
        self.version_label.setStyleSheet("font-size: 14px;")
        sub = QLabel(tr("Made with Claude Code · MIT license", "Направено с Claude Code · MIT лиценз"))
        sub.setObjectName("muted")
        col.addWidget(title)
        col.addWidget(self.version_label)
        col.addWidget(sub)
        head.addLayout(col, 1)
        lay.addLayout(head)

        blurb = QLabel(tr("Turns an Xbox or PlayStation controller into MIDI. Made for Lightkey, works with "
                          "any MIDI app.",
                          "Превръща Xbox или PlayStation контролер в MIDI. Направено за Lightkey, работи с "
                          "всяка MIDI програма."))
        blurb.setWordWrap(True)
        lay.addWidget(blurb)

        row1 = QHBoxLayout()
        self.check_btn = QPushButton(tr("Check for updates", "Провери за обновления"))
        self.news_btn = QPushButton(tr("What's new", "Какво е новото"))
        row1.addWidget(self.check_btn)
        row1.addWidget(self.news_btn)
        lay.addLayout(row1)
        self.check_btn.clicked.connect(check_updates)
        self.news_btn.clicked.connect(whats_new)

        ideas = QLabel(tr("<b>Ideas, wishes, problems?</b> Tell what you would like to change. "
                          "You and everyone else can see and vote for the wishes on GitHub.",
                          "<b>Идеи, желания, проблеми?</b> Кажи какво би искал да се промени. "
                          "Желанията се виждат и могат да се гласуват от всички в GitHub."))
        ideas.setWordWrap(True)
        lay.addWidget(ideas)
        row2 = QHBoxLayout()
        self.feedback_btn = QPushButton(tr("Send feedback…", "Изпрати отзив…"))
        self.feedback_btn.setDefault(True)
        self.wishes_btn = QPushButton(tr("See wishes & problems", "Виж желания и проблеми"))
        self.star_btn = QPushButton(tr("★ Project on GitHub", "★ Проектът в GitHub"))
        row2.addWidget(self.feedback_btn)
        row2.addWidget(self.wishes_btn)
        row2.addWidget(self.star_btn)
        lay.addLayout(row2)
        self.feedback_btn.clicked.connect(send_feedback)
        self.wishes_btn.clicked.connect(lambda: open_url(feedback.WISHES_URL))
        self.star_btn.clicked.connect(lambda: open_url(feedback.REPO_URL))

        lay.addWidget(QLabel(tr("Info for support (copy it into a bug report):",
                                "Информация за поддръжка (копирай я в доклад за проблем):")))
        self.info_box = QPlainTextEdit(info())
        self.info_box.setReadOnly(True)
        self.info_box.setMaximumHeight(86)
        lay.addWidget(self.info_box)
        bottom = QHBoxLayout()
        copy = QPushButton(tr("Copy info", "Копирай информацията"))
        copy.clicked.connect(lambda: QGuiApplication.clipboard().setText(self.info_box.toPlainText()))
        close = QPushButton(tr("Close", "Затвори"))
        close.clicked.connect(self.close)
        bottom.addWidget(copy)
        bottom.addStretch()
        bottom.addWidget(close)
        lay.addLayout(bottom)
        self.setMinimumWidth(500)

    def showEvent(self, e):
        self.info_box.setPlainText(self._info())  # the controller may have changed since last time
        super().showEvent(e)


class FeedbackDialog(QDialog):
    """Write a wish / bug / question; it opens GitHub's form with the text filled in."""

    KINDS = (("idea", "Wish or idea", "Желание или идея"),
             ("bug", "Something doesn't work", "Нещо не работи"),
             ("other", "Question or other", "Въпрос или друго"))

    def __init__(self, parent, info: Callable[[], str]):
        super().__init__(parent)
        self.setWindowTitle(tr("Send feedback", "Изпрати отзив"))
        self._info = info
        lay = QVBoxLayout(self)
        lay.setSpacing(10)

        row = QHBoxLayout()
        row.addWidget(QLabel(tr("What is it about?", "За какво е?")))
        self.kind = QComboBox()
        for key, en, bg in self.KINDS:
            self.kind.addItem(tr(en, bg), key)
        row.addWidget(self.kind, 1)
        lay.addLayout(row)

        self.title = QLineEdit()
        self.title.setPlaceholderText(tr("A short title, e.g. “Tap tempo button”", "Кратко заглавие, напр. „Бутон за такт“"))
        lay.addWidget(self.title)
        self.details = QPlainTextEdit()
        self.details.setPlaceholderText(tr("Describe it the way you would explain it to a friend. English or "
                                           "Bulgarian is fine.",
                                           "Опиши го, както би го обяснил на приятел. Може на български или "
                                           "на английски."))
        self.details.setMinimumHeight(140)
        lay.addWidget(self.details, 1)

        self.include = QCheckBox(tr("Include technical info (helps to understand the problem)",
                                    "Включи техническа информация (помага да се разбере проблемът)"))
        self.include.setChecked(True)
        lay.addWidget(self.include)
        self.info_box = QPlainTextEdit(info())
        self.info_box.setReadOnly(True)
        self.info_box.setMaximumHeight(78)
        lay.addWidget(self.info_box)
        self.include.toggled.connect(self.info_box.setVisible)

        note = QLabel(tr("<b>How it works:</b> your browser opens on GitHub with this text filled in; you read it "
                         "and press “Submit new issue”. You need a free GitHub account, and <b>the text is public</b>. "
                         "Nothing is sent from the app itself.",
                         "<b>Как работи:</b> браузърът ти се отваря в GitHub с попълнен този текст; ти го "
                         "прочиташ и натискаш „Submit new issue“. Нужен е безплатен акаунт в GitHub, а "
                         "<b>текстът е публичен</b>. От самото приложение не се изпраща нищо."))
        note.setWordWrap(True)
        note.setObjectName("muted")
        lay.addWidget(note)
        self.status = QLabel()
        self.status.setWordWrap(True)
        lay.addWidget(self.status)

        buttons = QHBoxLayout()
        self.copy_btn = QPushButton(tr("Copy text", "Копирай текста"))
        self.send_btn = QPushButton(tr("Open on GitHub", "Отвори в GitHub"))
        self.send_btn.setDefault(True)
        cancel = QPushButton(tr("Cancel", "Откажи"))
        buttons.addWidget(self.copy_btn)
        buttons.addStretch()
        buttons.addWidget(cancel)
        buttons.addWidget(self.send_btn)
        lay.addLayout(buttons)
        self.copy_btn.clicked.connect(self._copy)
        self.send_btn.clicked.connect(self._send)
        cancel.clicked.connect(self.reject)
        self.setMinimumWidth(520)

    def text(self) -> tuple[str, str, str, str | None]:
        return (self.kind.currentData(), self.title.text(), self.details.toPlainText(),
                self._info() if self.include.isChecked() else None)

    def url(self) -> tuple[str, bool]:
        kind, title, details, info = self.text()
        return feedback.build_issue_url(kind, title, details, info)

    def _copy(self) -> None:
        _, title, details, info = self.text()
        QGuiApplication.clipboard().setText("\n\n".join(p for p in (title, details, info) if p))
        self.status.setText(tr("Copied.", "Копирано."))

    def _send(self) -> None:
        if not (self.title.text().strip() or self.details.toPlainText().strip()):
            self.status.setText(tr("Write something first.", "Първо напиши нещо."))
            return
        url, shortened = self.url()
        if shortened:  # too long for a link: keep the full text on the clipboard to paste
            self._copy()
            self.status.setText(tr("The text is long, so GitHub gets the beginning. The full text is on your "
                                   "clipboard: paste it into the form.",
                                   "Текстът е дълъг, затова в GitHub отива началото. Целият е в клипборда: "
                                   "постави го във формуляра."))
        open_url(url)
        if not shortened:
            self.accept()
