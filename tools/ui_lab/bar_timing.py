"""A caption window's bar: languages, preset, timing (polyglotic-hq 593).

- the bar hovered, Learning chosen: "Detect → English ▾ · Learning ▾ ·
  Steady ▾", and the passive mic light;
- the timing chip's dropdown open, under Learning (Steady, Calm, and the
  translation after or with the line) and under Video (Instant, Subtitle
  blocks);
- the gear menu, seven rows;
- a responsive bar at short labels, icons, and overflow into the gear
  menu (polyglotic-hq 635).

The menus are made from real settings (`ui.use_presets`), as `main` makes
them.
"""

from collections.abc import Callable
from dataclasses import replace

from PySide6.QtWidgets import QWidget

from polyglotic_desktop.core.listening.captions import CaptionKind
from polyglotic_desktop.core.listening.playout import ReadingPath
from polyglotic_desktop.core.listening.respeaking import DEFAULT_RESPEAK_KEY
from polyglotic_desktop.core.listening.sources import WHOLE_SYSTEM
from polyglotic_desktop.core.listening.timing import CaptionMode, WithdrawalReason
from polyglotic_desktop.perf import budgets
from polyglotic_desktop.ui import use_presets
from polyglotic_desktop.ui_next.caption_window import CaptionWindow, StripLabels
from polyglotic_desktop.ui_next.caption_windows import CaptionWindows
from polyglotic_desktop.ui_next.dictation_sign import DictationSign
from polyglotic_desktop.ui_next.settings_popover import BAR_ROWS
from polyglotic_desktop.ui_next.views import placement
from tools.ui_lab.caption_window import LABELS, _Together, hovered, window
from tools.ui_lab.lab import Lab, State
from tools.ui_lab.new_parts import CAPTIONS, finished
from tools.ui_lab.use_presets import menu_of, on

WIDE = 900
"""The window's width for the bar's states: every chip shows."""


def bar(
    lab: Lab,
    key: str,
    timing: CaptionMode,
    path: ReadingPath = ReadingPath.BOTH,
    captions: int = CAPTIONS,
) -> CaptionWindow:
    """A window `WIDE` px wide, its bar hovered, under preset `key` with
    `timing` and re-speaking on. `captions`: 0 where a paced timing would
    draw its settled lines dimmed (the lab's contrast check is about them,
    not the bar)."""
    shown = window(lab, captions=captions)
    shown.resize(WIDE, shown.height())
    shown.set_presets(menu_of(on(key)))
    shown.set_timing(timing)
    shown.set_path(path)
    shown.set_respeaking(True, DEFAULT_RESPEAK_KEY, hold_only=True)
    hovered(lab, shown)
    lab.closing.append(shown.close)
    return shown


def bar_state(lab: Lab) -> QWidget:
    """All the labels and controls, at the same settings as the narrow states."""
    shown = responsive_bar(lab)
    shown.set_mic_level(0.65)
    assert shown.strip_labels is StripLabels.FULL
    return shown


def timing_open(
    key: str,
    timing: CaptionMode,
    path: ReadingPath = ReadingPath.BOTH,
    captions: int = CAPTIONS,
) -> Callable[[Lab], QWidget]:
    """The timing chip's dropdown open under it."""

    def run(lab: Lab) -> QWidget:
        shown = bar(lab, key, timing, path, captions)

        def toggle() -> None:
            shown.toggle_timings()

        for _ in range(6):  # open, close, open, ...: each a click
            lab.time("timing_dropdown", toggle, budget=budgets.CLICK)
        shown.toggle_timings()
        lab.pump()
        opened = shown.timings
        assert opened is not None
        return _Together([shown, opened])

    return run


def menu(lab: Lab) -> QWidget:
    """The gear menu with independent Caption size and Translation size (655)."""
    shown = bar(lab, use_presets.EVERYDAY, CaptionMode.WHOLE)
    shown.windows = 2  # Join windows shows
    shown.toggle_settings()
    lab.pump()
    popover = shown.popover
    assert popover is not None
    return _Together([shown, popover])


def sizes_apart(lab: Lab) -> QWidget:
    """Mandarin -> English with Caption size 150 % and Translation size 120 %,
    and the gear menu showing both independent sliders and Match (655)."""
    shown = bar(lab, use_presets.LEARNING, CaptionMode.WHOLE)
    shown.set_spoken_language("zh")
    shown.set_language("en")
    shown.set_text_size(1.5)
    shown.set_translation_size(1.2)
    shown.toggle_settings()
    lab.pump()
    popover = shown.popover
    assert popover is not None
    return _Together([shown, popover])


def narrow_bar(lab: Lab) -> QWidget:
    """At the minimum, all three dropdowns fit as icons."""
    shown = responsive_bar(lab)
    shown.resize(shown._minimum().width, shown.height())
    lab.pump()
    assert shown.strip_labels is StripLabels.ICONS and shown.mic_button.isVisible()
    assert all(not chip.isHidden() for chip in shown._chips)
    return shown


def responsive_bar(lab: Lab) -> CaptionWindow:
    shown = bar(lab, use_presets.EVERYDAY, CaptionMode.INSTANT)
    shown.set_show_mic(True)
    shown.set_reporting(True)
    return shown


def short_labels(lab: Lab) -> QWidget:
    """The app and preset elide and the language uses its code."""
    shown = responsive_bar(lab)
    for width in range(shown._minimum().width, WIDE):
        shown.resize(width, shown.height())
        if shown.strip_labels is StripLabels.SHORT:
            break
    assert shown.strip_labels is StripLabels.SHORT
    return shown


def overflow(lab: Lab) -> QWidget:
    """Below the icons' minimum, the gear lists every displaced dropdown."""
    shown = responsive_bar(lab)
    # A constrained width below the usual drag minimum. Keep room for the
    # fixed controls and dot, and overflow the first pixel of the last chip.
    width = (
        shown.tag.icon_width()
        + shown._strip_buttons_width()
        + shown.preset_chip.iconSize().width()
        + 2 * placement.CORNER_ZONE
    )
    shown.resize(width, shown.height())
    shown.toggle_settings()
    lab.pump()
    popover = shown.popover
    assert popover is not None
    assert all(popover.rows[name].isVisible() for name in BAR_ROWS)
    return _Together([shown, popover])


def narrow_menu(lab: Lab) -> QWidget:
    """The narrowest bar still shows the mic switch, and the gear menu has no hold button."""
    shown = bar(lab, use_presets.EVERYDAY, CaptionMode.WHOLE)
    shown.resize(shown._minimum().width, shown.height())
    lab.pump()
    assert shown.mic_button.isVisible()
    shown.toggle_settings()
    lab.pump()
    popover = shown.popover
    assert popover is not None
    return _Together([shown, popover])


def recognition_miss(lab: Lab) -> QWidget:
    windows = CaptionWindows(None)
    windows.set_captioned([("system", WHOLE_SYSTEM)])
    shown = windows.windows["system"]
    windows.set_labels(LABELS, "You")
    windows.set_respeaking(True, DEFAULT_RESPEAK_KEY, hold_only=True)
    shown.always_shown = True
    shown.resize(WIDE, shown.height())
    shown.show()
    windows.offer_respeaking(
        replace(
            finished(1, WHOLE_SYSTEM)[0],
            kind=CaptionKind.WITHDRAWN,
            clauses=(),
            reason=WithdrawalReason.EMPTY,
        )
    )
    assert windows.stored.respeaking_hinted
    lab.closing.append(windows.close)
    lab.pump()
    return shown


def respeaking_held(lab: Lab) -> QWidget:
    shown = responsive_bar(lab)
    shown.set_show_mic(False)
    assert shown.strip_labels is StripLabels.FULL
    # Keep the fixture within the offscreen display, so the sign can sit
    # above the window as it would on the learner’s monitor.
    area = shown.screen().availableGeometry()
    shown.resize(min(shown.width(), area.width()), shown.height())
    shown.move(area.center() - shown.rect().center())
    level = 0.65  # synthetic microphone sample
    sign = DictationSign()
    sign.show_respeaking("listening", level, shown.label.name, shown)
    lab.closing.append(sign.close)
    lab.pump()
    return _Together([shown, sign])


STATES = [
    State(f"ui_next.{name}", run, gated=True, scene=scene)
    for name, run, scene in (
        ("w1_bar_timing", bar_state, True),
        ("w1_respeaking_held", respeaking_held, True),
        ("w1_respeaking_miss", recognition_miss, True),
        (
            "w1_timing_learning",
            timing_open(
                use_presets.LEARNING,
                CaptionMode.STEADY,
                ReadingPath.ACQUISITION,
                captions=0,
            ),
            True,
        ),
        ("w1_timing_video", timing_open(use_presets.VIDEO, CaptionMode.INSTANT), True),
        ("w1_menu", menu, True),
        ("w1_sizes_apart", sizes_apart, True),
        ("w1_bar_short_labels", short_labels, True),
        ("w1_narrow_bar", narrow_bar, True),
        ("w1_bar_overflow", overflow, True),
        ("w1_narrow_menu", narrow_menu, True),
    )
]
