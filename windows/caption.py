"""A stand-in for Polyglotic's caption window (547's spike, not the app's code).

Frameless, translucent, always on top, never takes focus - the flags the
app's caption window uses (Tool | Frameless | StaysOnTop |
DoesNotAcceptFocus) - plus, by option, X11's override-redirect
(Qt.X11BypassWindowManagerHint) and click-through
(Qt.WindowTransparentForInput, the app's "locked").

The left half is painted 50 % green, the right half solid green, so a
picture of the screen shows whether the window is on top and translucent.

It prints one JSON line per event (enter, leave, press, the pointer's
position as Qt reads it from the X server) and reads commands on stdin:
raise, lock, unlock, bypass, quit.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time

if os.environ.get("GITHUB_ACTIONS") != "true" or not sys.platform.startswith("linux"):
    sys.exit("547's probes run only on GitHub's Linux runners")

from PySide6.QtCore import QSocketNotifier, Qt, QTimer
from PySide6.QtGui import QColor, QCursor, QFont, QGuiApplication, QPainter
from PySide6.QtWidgets import QApplication, QWidget

T0 = time.monotonic()


def log(event: str, **fields: object) -> None:
    print(json.dumps({"t": round(time.monotonic() - T0, 3), "who": "caption", "ev": event, **fields}), flush=True)


class Caption(QWidget):
    def __init__(self, bypass: bool, through: bool) -> None:
        flags = (
            Qt.WindowType.Tool
            | Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowStaysOnTopHint
            | Qt.WindowType.WindowDoesNotAcceptFocus
        )
        if bypass:
            flags |= Qt.WindowType.X11BypassWindowManagerHint
        if through:
            flags |= Qt.WindowType.WindowTransparentForInput
        super().__init__(None, flags)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating)
        self.setMouseTracking(True)
        self.setWindowTitle("caption547")

    def paintEvent(self, _event: object) -> None:
        p = QPainter(self)
        w, h = self.width(), self.height()
        p.fillRect(0, 0, w // 2, h, QColor(0, 255, 0, 128))
        p.fillRect(w // 2, 0, w - w // 2, h, QColor(0, 255, 0, 255))
        p.setPen(QColor(0, 0, 0))
        p.setFont(QFont("DejaVu Sans", 20))
        p.drawText(self.rect(), Qt.AlignmentFlag.AlignCenter, "caption 547")
        p.end()

    def enterEvent(self, event: object) -> None:
        log("enter")

    def leaveEvent(self, event: object) -> None:
        log("leave")

    def mousePressEvent(self, event: object) -> None:
        pos = event.globalPosition().toPoint()  # type: ignore[attr-defined]
        log("press", x=pos.x(), y=pos.y())

    def mouseMoveEvent(self, event: object) -> None:
        pos = event.globalPosition().toPoint()  # type: ignore[attr-defined]
        log("move", x=pos.x(), y=pos.y())

    def input_spot(self) -> None:
        """Locked but for one small spot: the X input shape cut to a 60x40
        corner (top right) through libXext, so the rest passes clicks on and
        the spot alone still takes the pointer - a stand-in for an unlock
        spot that a Wayland window beneath can't hide."""
        import ctypes

        class XRectangle(ctypes.Structure):
            _fields_ = [("x", ctypes.c_short), ("y", ctypes.c_short),
                        ("width", ctypes.c_ushort), ("height", ctypes.c_ushort)]

        x11 = ctypes.CDLL("libX11.so.6")
        xext = ctypes.CDLL("libXext.so.6")
        x11.XOpenDisplay.restype = ctypes.c_void_p
        x11.XOpenDisplay.argtypes = [ctypes.c_char_p]
        x11.XFlush.argtypes = [ctypes.c_void_p]
        x11.XCloseDisplay.argtypes = [ctypes.c_void_p]
        xext.XShapeCombineRectangles.argtypes = [ctypes.c_void_p, ctypes.c_ulong, ctypes.c_int, ctypes.c_int, ctypes.c_int,
                                                 ctypes.POINTER(XRectangle), ctypes.c_int, ctypes.c_int, ctypes.c_int]
        dpy = x11.XOpenDisplay(None)
        rect = XRectangle(self.width() - 60, 0, 60, 40)
        xext.XShapeCombineRectangles(dpy, int(self.winId()), 2, 0, 0, ctypes.byref(rect), 1, 0, 0)  # ShapeInput, ShapeSet
        x11.XFlush(dpy)
        x11.XCloseDisplay(dpy)

    def set_flag(self, flag: Qt.WindowType, on: bool) -> None:
        geo = self.geometry()
        self.setWindowFlag(flag, on)
        self.setGeometry(geo)
        self.show()


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--geometry", default="440,480,400,160")
    ap.add_argument("--bypass", action="store_true")
    ap.add_argument("--through", action="store_true")
    a = ap.parse_args()
    app = QApplication(sys.argv[:1])
    log("platform", name=QGuiApplication.platformName(), qt=__import__("PySide6").__version__)
    x, y, w, h = (int(v) for v in a.geometry.split(","))
    win = Caption(a.bypass, a.through)
    win.setGeometry(x, y, w, h)
    win.show()
    log("shown", wid=int(win.winId()), bypass=a.bypass, through=a.through)

    last = [None]

    def poll() -> None:
        pos = QCursor.pos()
        now = (pos.x(), pos.y())
        if now != last[0]:
            last[0] = now
            log("cursor", x=now[0], y=now[1], under=win.underMouse())

    timer = QTimer()
    timer.timeout.connect(poll)
    timer.start(50)

    def command() -> None:
        line = sys.stdin.readline().strip()
        if not line:
            return
        if line == "raise":
            win.raise_()
        elif line == "lock":
            win.set_flag(Qt.WindowType.WindowTransparentForInput, True)
        elif line == "unlock":
            win.set_flag(Qt.WindowType.WindowTransparentForInput, False)
        elif line in ("qlock", "qunlock"):  # the input shape changed live: no re-create, no re-map
            win.windowHandle().setFlag(Qt.WindowType.WindowTransparentForInput, line == "qlock")
        elif line in ("mlock", "munlock"):  # the same window unmapped, changed, mapped again
            win.hide()
            win.windowHandle().setFlag(Qt.WindowType.WindowTransparentForInput, line == "mlock")
            win.show()
        elif line == "spot":
            win.input_spot()
        elif line == "spotmap":  # the same spot, cut while the window is unmapped
            win.hide()
            win.input_spot()
            win.show()
        elif line == "bypass":
            win.set_flag(Qt.WindowType.X11BypassWindowManagerHint, True)
        elif line == "quit":
            app.quit()
        log("did", what=line, flags=int(win.windowFlags().value), wid=int(win.winId()))

    notifier = QSocketNotifier(sys.stdin.fileno(), QSocketNotifier.Type.Read)
    notifier.activated.connect(command)
    app.exec()


if __name__ == "__main__":
    main()
