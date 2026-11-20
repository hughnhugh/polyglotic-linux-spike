"""A stand-in for a full-screen game or video (547's spike).

Run with QT_QPA_PLATFORM=xcb (an X11 game, e.g. under Proton) or
QT_QPA_PLATFORM=wayland (a native Wayland app). Paints the whole screen one
colour (red for X11, blue for Wayland) and prints one JSON line per event:
shown, active or not, presses (so a click that passed through the caption
window is seen here), the pointer's enter and moves.
"""

from __future__ import annotations

import json
import os
import sys
import time

if os.environ.get("GITHUB_ACTIONS") != "true" or not sys.platform.startswith("linux"):
    sys.exit("547's probes run only on GitHub's Linux runners")

from PySide6.QtCore import QEvent, QSocketNotifier, Qt
from PySide6.QtGui import QColor, QGuiApplication, QPainter
from PySide6.QtWidgets import QApplication, QWidget

T0 = time.monotonic()


def log(event: str, **fields: object) -> None:
    print(json.dumps({"t": round(time.monotonic() - T0, 3), "who": "fullscreen", "ev": event, **fields}), flush=True)


class Full(QWidget):
    def __init__(self, colour: QColor) -> None:
        super().__init__()
        self.colour = colour
        self.setMouseTracking(True)
        self.setWindowTitle("fullscreen547")
        self.moves = 0

    def paintEvent(self, _event: object) -> None:
        p = QPainter(self)
        p.fillRect(self.rect(), self.colour)
        p.end()

    def changeEvent(self, event: QEvent) -> None:
        if event.type() == QEvent.Type.ActivationChange:
            log("active", value=self.isActiveWindow())
        if event.type() == QEvent.Type.WindowStateChange:
            log("state", fullscreen=self.isFullScreen())
        super().changeEvent(event)

    def enterEvent(self, event: object) -> None:
        log("enter")

    def mousePressEvent(self, event: object) -> None:
        pos = event.globalPosition().toPoint()  # type: ignore[attr-defined]
        log("press", x=pos.x(), y=pos.y())

    def mouseMoveEvent(self, event: object) -> None:
        pos = event.position().toPoint()  # type: ignore[attr-defined]
        self.moves += 1
        log("move", x=pos.x(), y=pos.y())


def main() -> None:
    app = QApplication(sys.argv[:1])
    platform = QGuiApplication.platformName()
    colour = QColor(0, 0, 255) if platform.startswith("wayland") else QColor(255, 0, 0)
    win = Full(colour)
    win.showFullScreen()
    win.activateWindow()
    win.raise_()
    log("shown", platform=platform, size=[win.width(), win.height()])

    def command() -> None:
        line = sys.stdin.readline().strip()
        if line == "quit":
            app.quit()
        elif line == "activate":
            win.activateWindow()
            win.raise_()
        log("did", what=line, active=win.isActiveWindow(), fullscreen=win.isFullScreen())

    notifier = QSocketNotifier(sys.stdin.fileno(), QSocketNotifier.Type.Read)
    notifier.activated.connect(command)
    app.exec()


if __name__ == "__main__":
    main()
