"""Windows' shutdown, restart and sign-out, into the app's one quit path.

Windows asks every app first (`WM_QUERYENDSESSION`): the answer is yes at
once, and nothing closes yet, because another app can still cancel. Only
when the session really ends (`WM_ENDSESSION` with `wParam` TRUE) does the
app quit cleanly, before the handler returns, since Windows may end the
process any time after it; the quit's own 3 s limit (`run_health`) keeps it
inside the few seconds Windows waits. A cancelled end (`wParam` FALSE)
leaves the app running as it was. Microsoft's guidance is the same: answer
the query at once and clean up on WM_ENDSESSION.

Qt answers the query itself and emits `aboutToQuit` on the end, so the
filter only adds the clean quit and lets every message through. Unproven on
a real Windows shutdown until Claude's rehearsal (polyglotic-hq 1009).
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from PySide6.QtCore import QAbstractNativeEventFilter

WM_QUERYENDSESSION = 0x0011
WM_ENDSESSION = 0x0016


class WindowsSessionEnd:
    """Small, fakeable adapter for native Windows shutdown notifications."""

    def __init__(self, quit_cleanly: Callable[[], None]) -> None:
        self._quit_cleanly = quit_cleanly

    def message(self, message: int, ending: bool = True) -> None:
        """One session message: `ending` is WM_ENDSESSION's `wParam`."""
        if message == WM_ENDSESSION and ending:
            self._quit_cleanly()


class NativeSessionFilter(QAbstractNativeEventFilter):
    """Qt native filter; kept thin so message policy remains fake-testable."""

    def __init__(self, session_end: WindowsSessionEnd) -> None:
        super().__init__()
        self._session_end = session_end
        from ctypes import wintypes

        self._msg = wintypes.MSG

    def nativeEventFilter(self, _event_type: Any, message: int) -> tuple[bool, int]:
        native = self._msg.from_address(int(message))
        if native.message == WM_ENDSESSION:
            self._session_end.message(native.message, ending=bool(native.wParam))
        return False, 0  # Qt's own handling goes on: its answer, aboutToQuit
