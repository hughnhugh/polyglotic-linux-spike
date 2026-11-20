"""570: a full-screen window, focused - a video or a game beneath - that
writes each key and click it gets to POLYGLOTIC_BENEATH_LOG."""

import os
import sys

from PySide6.QtGui import QColor, QPainter
from PySide6.QtWidgets import QApplication, QWidget

LOG = os.environ["POLYGLOTIC_BENEATH_LOG"]


def said(line: str) -> None:
    with open(LOG, "a") as log:
        log.write(line + "\n")


class Beneath(QWidget):
    def paintEvent(self, _event: object) -> None:
        QPainter(self).fillRect(self.rect(), QColor(20, 40, 80))

    def keyPressEvent(self, event) -> None:  # type: ignore[no-untyped-def]
        said(f"key {event.key()} mods {int(event.modifiers().value)}")

    def mousePressEvent(self, event) -> None:  # type: ignore[no-untyped-def]
        p = event.globalPosition().toPoint()
        said(f"click {p.x()},{p.y()}")


app = QApplication(sys.argv[:1])
window = Beneath()
window.showFullScreen()
window.activateWindow()
said(f"shown {QApplication.platformName()} {window.width()}x{window.height()}")
sys.exit(app.exec())
