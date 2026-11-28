"""The one help style open (polyglotic-hq 1013): an ⓘ's explanation, a
dropdown choice's description in the box beside it, and each mirrored, as
right-to-left text lays them out. The app has no right-to-left interface
language yet, so a mirrored layout stands in for one (as 1009's dialog
did): the popup goes before what it explains, on the left.

Run at 200 % text and in Chinese with `--text-size 200 --language zh_CN`.
"""

from collections.abc import Callable

from PySide6.QtCore import QPoint, QRect, Qt
from PySide6.QtWidgets import QAbstractButton, QApplication, QLabel, QWidget

from polyglotic_desktop.ui_next.controls import InfoIcon, hide_help
from tools.ui_lab import caption_window
from tools.ui_lab.lab import Lab, State
from tools.ui_lab.panels import look_rail


def _shown_popup() -> QLabel:
    return next(
        w
        for w in QApplication.topLevelWidgets()
        if isinstance(w, QLabel) and w.objectName() == "HelpPopup" and w.isVisible()
    )


def info(mirrored: bool) -> Callable[[Lab], QWidget]:
    """The look rail's first ⓘ, its explanation shown as keyboard focus or a
    resting pointer shows it: wrapped, beside the ⓘ, never over it."""

    def run(lab: Lab) -> QWidget:
        rail = look_rail(lab)
        area = rail.screen().availableGeometry()  # room on both sides of it
        rail.move(area.center().x() - rail.width() // 2, area.top() + 20)
        if mirrored:
            rail.setLayoutDirection(Qt.LayoutDirection.RightToLeft)
            lab.pump()
        icon = next(i for i in rail.findChildren(InfoIcon) if i.isVisible())
        icon.hover.show()
        lab.pump()
        popup = _shown_popup()
        lab.closing.append(hide_help)
        spot = QRect(icon.mapToGlobal(QPoint(0, 0)), icon.size())
        assert not popup.geometry().intersects(spot), "beside the ⓘ, never over it"
        return popup

    return run


def described(
    popover_name: str, row_name: str, mirrored: bool
) -> Callable[[Lab], QWidget]:
    """A caption window's dropdown open (`popover_name`: its toggle) with
    `row_name`'s description in the box beside it, level with the row."""

    def run(lab: Lab) -> QWidget:
        shown = caption_window.window(lab, captions=3)
        caption_window.hovered(lab, shown)
        getattr(shown, f"toggle_{popover_name}")()
        popover = getattr(shown, popover_name)
        assert popover is not None
        if mirrored:
            popover.setLayoutDirection(Qt.LayoutDirection.RightToLeft)
        lab.pump()
        rows = {b.objectName(): b for b in popover.findChildren(QAbstractButton)}
        row = rows[row_name]
        row.property("described").show()
        lab.pump()
        box = popover.findChild(QLabel, "MenuDescription")
        assert box is not None and box.isVisible(), "the box beside the dropdown"
        frame = popover.frameGeometry()
        geometry = box.geometry()
        assert not geometry.intersects(frame), "beside the dropdown, never over it"
        lab.closing.append(shown.close)
        return box

    return run


WHOLE_ROW = "timings.timing.steady"
"""Whole captions' row in the timing dropdown: its stored value is "steady"."""

STATES = [
    State("ui_next.help_info", info(False), gated=True),
    State("ui_next.help_info_mirrored", info(True), gated=True),
    State(
        "ui_next.help_timing_described",
        described("timings", WHOLE_ROW, False),
        gated=True,
    ),
    State(
        "ui_next.help_timing_described_mirrored",
        described("timings", WHOLE_ROW, True),
        gated=True,
    ),
    State(
        "ui_next.help_readings_described",
        described("presets", "presets.add.readings", False),
        gated=True,
    ),
]
