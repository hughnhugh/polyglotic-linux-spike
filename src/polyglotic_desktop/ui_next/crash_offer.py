"""The offer after an improper exit: send its content-free crash details?

Shown once per improper exit, beside the app and never in front of
captioning (modeless). Its three choices: Send, which hands the exact text
to Report a problem; Don't send; and See what's sent, which shows that
exact text first (polyglotic-hq 1009). Nothing is sent from here: a
report goes only when the learner sends it from Report a problem.
"""

from collections.abc import Callable

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QShowEvent
from PySide6.QtWidgets import (
    QApplication,
    QDialog,
    QHBoxLayout,
    QLabel,
    QPlainTextEdit,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from polyglotic_desktop.ui_next import style
from polyglotic_desktop.ui_next.controls import label

OFFER_WIDTH = 460
"""The offer's width (px at 100 % text, 360-640): its sentence in two lines."""
PREVIEW_HEIGHT = 220
"""The shown details' least height (px at 100 % text, 120-400): a screenful."""
ANY_WIDTH = 16_777_215
"""Qt's QWIDGETSIZE_MAX: a widget's maximum width with no limit set."""


def _tr(text: str) -> str:
    return QApplication.translate("CrashOffer", text)


def balanced_width(words: QLabel, room: int) -> int:
    """The narrowest width at which `words` take as many lines as they do in
    `room`: their lines as even as they go (CSS's `text-wrap: balance`), so
    the last is never one word on its own - English's question at 100 %
    left "it?" alone (polyglotic-hq 1009). In any language and at any text
    size, and the words themselves unchanged. A label whose lines keep to
    a measure (`copying.Measured`) is balanced within it."""
    lines = words.heightForWidth(room)
    if lines <= 0:
        return room  # nothing wraps
    narrow, wide = room // 2, room  # 2+ lines never fit in under half the room
    while narrow < wide:
        middle = (narrow + wide) // 2
        if words.heightForWidth(middle) <= lines:
            wide = middle
        else:
            narrow = middle + 1
    return wide


def _button(text: str, name: str, kind: str) -> QPushButton:
    button = QPushButton(text)
    button.setObjectName(name)
    button.setProperty("kind", kind)
    button.setCursor(Qt.CursorShape.PointingHandCursor)
    return button


class CrashOffer(QDialog):
    """Modeless offer whose preview is exactly the attachment to be sent."""

    send_wanted = Signal(str)

    def __init__(self, report: str, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._report = report
        self.setObjectName("CrashOffer")
        self.setWindowTitle(_tr("Polyglotic closed unexpectedly"))
        self.setModal(False)
        layout = self._column = QVBoxLayout(self)
        self.message = label(
            _tr(
                "Polyglotic closed unexpectedly last time. Send the crash details "
                "to help fix it?"
            ),
            wrap=True,
        )
        self.message.setObjectName("crash_offer.message")
        layout.addWidget(self.message)
        self.preview = QPlainTextEdit(report)
        self.preview.setObjectName("crash_offer.preview")
        self.preview.setAccessibleName(_tr("See what's sent"))
        self.preview.setReadOnly(True)
        self.preview.setMinimumHeight(style.px(PREVIEW_HEIGHT))
        self.preview.setVisible(False)
        layout.addWidget(self.preview, 1)
        buttons = QHBoxLayout()
        self.see = _button(_tr("See what's sent"), "crash_offer.see", "ghost")
        self.dismiss = _button(_tr("Don't send"), "crash_offer.dismiss", "ghost")
        self.send = _button(_tr("Send"), "crash_offer.send", "primary")
        buttons.addWidget(self.see)
        buttons.addStretch(1)
        buttons.addWidget(self.dismiss)
        buttons.addWidget(self.send)
        layout.addLayout(buttons)
        self.send.setDefault(True)
        self.send.clicked.connect(self._send)
        self.dismiss.clicked.connect(self.close)
        self.see.clicked.connect(self.show_details)

    def showEvent(self, event: QShowEvent) -> None:
        """Sized once it has its window's stylesheet (`MainWindow` gives a
        dialog over it the sheet when Qt has polished it), so its padding
        and text are the ones measured."""
        super().showEvent(event)
        self._fit()

    def show_details(self) -> None:
        """See what's sent: the exact text, before anything goes."""
        self.preview.setVisible(True)
        self.see.setEnabled(False)
        self._fit()

    def _fit(self) -> None:
        """As wide as `OFFER_WIDTH` at this text size, or as its buttons
        need if that's wider (a long language at 200 %); as tall as its
        words wrap to at that width. A window doesn't grow for a label's
        wrapped lines by itself: the UI lab saw the question clipped at
        200 % and German's See what's sent cut (polyglotic-hq 1009). The
        question's lines balanced within it (`balanced_width`)."""
        layout = self._column
        self.message.setMaximumWidth(ANY_WIDTH)  # balanced afresh below
        layout.activate()
        width = max(style.px(OFFER_WIDTH), layout.minimumSize().width())
        self.setFixedWidth(width)
        margins = layout.contentsMargins()
        room = width - margins.left() - margins.right()
        self.message.setMaximumWidth(balanced_width(self.message, room))
        layout.activate()
        height = (
            layout.totalHeightForWidth(width)
            if layout.hasHeightForWidth()
            else layout.sizeHint().height()
        )
        self.setMinimumHeight(height)
        self.resize(width, height)

    def _send(self) -> None:
        self.send_wanted.emit(self._report)
        self.close()


def offer_previous_crash(
    report: str | None,
    parent: QWidget,
    report_problem: Callable[[str], None],
) -> CrashOffer | None:
    """Show the modeless offer only when the failed run left evidence."""
    if report is None:
        return None
    offer = CrashOffer(report, parent)
    offer.send_wanted.connect(report_problem)
    offer.show()
    return offer
