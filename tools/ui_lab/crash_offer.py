"""The offer after an improper exit (polyglotic-hq 1009): its question
and three choices; with See what's sent pressed, the exact text a report
would carry; and the same mirrored, right to left, as an Arabic interface
would lay it out (none is offered yet: the strings stay English's).

Its sample text has the shape `crash_report.crash_report_text` gives:
versions, the failed run's own records and its frames, the home folder
hidden. Made up: no run of anyone's.
"""

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QWidget

from polyglotic_desktop.ui_next import style
from polyglotic_desktop.ui_next.crash_offer import CrashOffer
from tools.ui_lab.lab import Lab, State

SAMPLE = (
    "Polyglotic: 0.1.14\n"
    "OS: Windows 11 (10.0.26100)\n"
    "\n"
    "Log:\n"
    "2026-11-28 21:40:02,114 INFO polyglotic_desktop.main: Polyglotic 0.1.14"
    " (alpha), taskbar ID Polyglotic\n"
    "2026-11-28 21:40:03,580 INFO polyglotic_desktop.main: learning data open: ja\n"
    "2026-11-28 21:41:17,032 INFO polyglotic_desktop.connection.session:"
    " listening: 1 source\n"
    "\n"
    "Stack frames:\n"
    "%USERPROFILE%\\AppData\\Local\\Polyglotic\\current\\_internal\\"
    "polyglotic_desktop\\ui_next\\flow.py:212 in add_layout\n"
    "%USERPROFILE%\\AppData\\Local\\Polyglotic\\current\\_internal\\"
    "polyglotic_desktop\\ui_next\\home.py:1480 in _rows\n"
    "%USERPROFILE%\\AppData\\Local\\Polyglotic\\current\\_internal\\"
    "polyglotic_desktop\\main.py:10021 in _start_and_run\n"
)


def offer(lab: Lab, details: bool = False, right_to_left: bool = False) -> QWidget:
    shown = CrashOffer(SAMPLE)
    # what `MainWindow.childEvent` gives a dialog over the window
    shown.setStyleSheet(style.stylesheet(style.current()))
    if right_to_left:
        shown.setLayoutDirection(Qt.LayoutDirection.RightToLeft)
    shown.show()
    if details:
        shown.show_details()
    lab.pump()
    assert shown.preview.isVisible() == details, "the details shown or hidden"
    return shown


STATES = [
    State("ui_next.crash_offer", offer, gated=True),
    State(
        "ui_next.crash_offer_details", lambda lab: offer(lab, details=True), gated=True
    ),
    State(
        "ui_next.crash_offer_right_to_left",
        lambda lab: offer(lab, details=True, right_to_left=True),
        gated=True,
    ),
]
