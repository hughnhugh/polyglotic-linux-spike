"""570's probe, on a desktop session the job made (tools/linux_session.sh),
with a full-screen Wayland window focused beneath (on GNOME and KDE):

1. hotkeys: the app's X11 grab (platform/linux/hotkeys.X11Hotkeys) of
   Ctrl+Alt+Shift+L, P, H; each pressed through the compositor (real input)
   while the full-screen window has the keyboard - heard or not; and a
   combination another client already holds is reported taken.
2. popovers: a caption-like window (override-redirect, no focus, as the
   app's) whose button opens a "popover" of one of three kinds; Esc pressed
   and a click elsewhere, through the compositor - does it close, and did
   the window beneath get them:
   - tool: today's (a Tool window that never takes the focus);
   - popup: a real Qt.Popup (X11 grabs);
   - focus: an ordinary window that takes the focus when opened, closed
     when it loses it.
3. the unlock spot: a locked (input-transparent) window with a small
   window over its corner; the mouse moved over the corner, then away onto
   the Wayland window - does the corner see it come and go (Qt's
   enter/leave), and what does QCursor.pos() say once it's gone.

    python probe570/probe.py OUT.json
"""

from __future__ import annotations

import json
import os
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from PySide6.QtCore import QEvent, QObject, QPoint, QRect, Qt, QTimer  # noqa: E402
from PySide6.QtGui import QCursor, QGuiApplication  # noqa: E402
from PySide6.QtWidgets import QApplication, QLabel, QPushButton, QWidget  # noqa: E402

from tools.linux_input import Input  # noqa: E402

OUT = Path(sys.argv[1])
RESULTS: dict[str, object] = {"screen": os.environ.get("LINUX_SESSION_SCREEN", "xvfb")}
BENEATH_LOG = os.environ.get("POLYGLOTIC_BENEATH_LOG", "")


def note(key: str, value: object) -> None:
    RESULTS[key] = value
    print(key, value, flush=True)
    OUT.write_text(json.dumps(RESULTS, indent=1, default=str))


def spin(seconds: float) -> None:
    end = time.monotonic() + seconds
    while time.monotonic() < end:
        QApplication.processEvents()
        time.sleep(0.01)


def beneath_lines() -> list[str]:
    if not BENEATH_LOG or not Path(BENEATH_LOG).exists():
        return []
    return Path(BENEATH_LOG).read_text().splitlines()


FLAGS = (
    Qt.WindowType.Tool
    | Qt.WindowType.FramelessWindowHint
    | Qt.WindowType.WindowStaysOnTopHint
    | Qt.WindowType.WindowDoesNotAcceptFocus
    | Qt.WindowType.X11BypassWindowManagerHint
)


class Popover(QLabel):
    def __init__(self, kind: str, owner: QWidget) -> None:
        if kind == "tool":
            flags = FLAGS
        elif kind == "popup":
            flags = Qt.WindowType.Popup | Qt.WindowType.FramelessWindowHint
        else:  # focus
            flags = (
                Qt.WindowType.Dialog
                | Qt.WindowType.FramelessWindowHint
                | Qt.WindowType.WindowStaysOnTopHint
            )
        super().__init__(f"a {kind} popover", owner, flags)
        self.kind = kind
        self.events: list[str] = []
        self.setStyleSheet("background: #333; color: white; padding: 20px")
        self.resize(260, 160)
        if kind == "tool":
            self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating)

    def keyPressEvent(self, event) -> None:  # type: ignore[no-untyped-def]
        self.events.append(f"key {event.key()}")
        if event.key() == Qt.Key.Key_Escape:
            self.close()
        else:
            super().keyPressEvent(event)

    def event(self, event: QEvent) -> bool:
        if event.type() == QEvent.Type.WindowDeactivate and self.kind == "focus":
            self.events.append("deactivated")
            self.close()
        if event.type() in (QEvent.Type.FocusIn, QEvent.Type.WindowActivate):
            self.events.append(event.type().name)
        return super().event(event)


def probe_hotkeys(inp: Input) -> None:
    from polyglotic_desktop.platform.linux import hotkeys

    heard: list[str] = []
    other = hotkeys.LibXcb()  # another client holding Ctrl+Alt+Shift+H
    first, mapping = other.keyboard()
    h_code = hotkeys.keycode_for("H", mapping, first)
    assert h_code is not None
    held = all(other.grab(h_code, hotkeys.CTRL_ALT_SHIFT | extra) for extra in hotkeys.IGNORED)
    keys = hotkeys.X11Hotkeys({k: (lambda k=k: heard.append(k)) for k in "LPH"})
    taken = keys.start()
    note("hotkeys_taken", {"held_by_another": held, "taken": taken})
    spin(0.5)
    inp.press("ctrl", "alt", "shift", "l")
    spin(1.0)
    note("hotkey_L_over_the_wayland_window", "L" in heard)
    inp.press("ctrl", "alt", "shift", "p")
    spin(1.0)
    note("hotkey_P_over_the_wayland_window", "P" in heard)
    inp.press("ctrl", "alt", "l")  # the Windows combination: not ours here
    spin(0.5)
    note("heard_in_all", list(heard))
    keys.stop()
    other.close()


def probe_popovers(inp: Input, caption: QWidget, button: QPushButton) -> None:
    for kind in ("tool", "popup", "focus"):
        for how in ("esc", "click"):
            before = len(beneath_lines())
            popover = Popover(kind, caption)
            button.clicked.connect(lambda _=False, p=popover: (p.move(caption.x(), caption.y() + caption.height() + 4), p.show(), p.activateWindow() if p.kind == "focus" else None))
            centre = button.mapToGlobal(button.rect().center())
            inp.click(centre.x(), centre.y())
            spin(1.2)
            opened = popover.isVisible()
            active = QApplication.activeWindow() is popover
            if how == "esc":
                inp.press("esc")
            else:
                inp.click(200, 900)  # on the full-screen window, far from ours
            spin(1.2)
            note(
                f"popover_{kind}_{how}",
                {
                    "opened": opened,
                    "had_the_keyboard": active,
                    "closed": opened and not popover.isVisible(),
                    "events": popover.events,
                    "beneath_got": beneath_lines()[before:],
                },
            )
            button.clicked.disconnect()
            popover.close()
            popover.deleteLater()
            spin(0.5)


def probe_unlock_spot(inp: Input) -> None:
    locked = QLabel("a locked caption window")
    locked.setWindowFlags(FLAGS | Qt.WindowType.WindowTransparentForInput)
    locked.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
    locked.setStyleSheet("background: rgba(0,0,0,150); color: white; font-size: 24px")
    locked.setGeometry(600, 300, 600, 200)
    locked.show()
    catcher = QWidget(locked)
    catcher.setWindowFlags(FLAGS)
    catcher.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
    catcher.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating)
    corner = QRect(600 + 600 - 60, 300 + 200 - 40, 60, 40)
    catcher.setGeometry(corner)
    events: list[str] = []

    class Watch(QObject):
        def eventFilter(self, _o: QObject, e: QEvent) -> bool:
            if e.type() in (QEvent.Type.Enter, QEvent.Type.Leave, QEvent.Type.MouseButtonPress):
                events.append(e.type().name)
            return False

    watch = Watch()
    catcher.installEventFilter(watch)
    catcher.show()
    spin(1.0)
    inp.move(900, 400)  # the middle of the locked window: passes through
    spin(0.6)
    middle = QCursor.pos()
    inp.move(corner.center().x(), corner.center().y())
    spin(0.8)
    on_corner = (catcher.underMouse(), QCursor.pos())
    inp.move(corner.center().x() + 200, corner.center().y() + 300)  # away, onto the Wayland window
    spin(0.8)
    away = (catcher.underMouse(), QCursor.pos())
    before = len(beneath_lines())
    inp.click(950, 380)  # a click on the locked window's middle
    spin(0.8)
    note(
        "unlock_spot",
        {
            "pointer_over_middle": [middle.x(), middle.y()],
            "on_corner_under_mouse": on_corner[0],
            "on_corner_pointer": [on_corner[1].x(), on_corner[1].y()],
            "away_under_mouse": away[0],
            "away_pointer": [away[1].x(), away[1].y()],
            "events": events,
            "click_on_locked_middle_reached_beneath": beneath_lines()[before:],
        },
    )
    catcher.close()
    locked.close()


def main() -> int:
    app = QApplication(sys.argv[:1])
    note("platform", QGuiApplication.platformName())
    inp = Input.make()
    caption = QWidget()
    caption.setWindowFlags(FLAGS)
    caption.setStyleSheet("background: #224; color: white")
    caption.setGeometry(700, 120, 500, 120)
    button = QPushButton("settings", caption)
    button.setGeometry(380, 40, 100, 40)
    caption.show()
    spin(1.5)
    steps = [("hotkeys", lambda: probe_hotkeys(inp)),
             ("popovers", lambda: probe_popovers(inp, caption, button)),
             ("unlock_spot", lambda: probe_unlock_spot(inp))]
    for name, step in steps:
        try:
            step()
        except Exception as error:  # noqa: BLE001
            import traceback

            note(f"{name}_error", traceback.format_exc()[-1500:])
    QTimer.singleShot(0, app.quit)
    app.exec()
    return 0


if __name__ == "__main__":
    sys.exit(main())
