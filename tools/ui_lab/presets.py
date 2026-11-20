"""The ten colour presets as caption windows, each a state with its golden
(polyglotic-hq 248's section 6, Q7 A; 248's B6, built by 261): a window
of finished captions in the preset's colours and panel, photographed over
the stand-in video - the checks judge its text's contrast as seen - and
the change to it from Classic (Classic's: from Broadcast) timed (a click:
50 ms) - and each with its top bar showing (`_bar`), so the contrast check
reads the bar's words on every preset (polyglotic-hq 272: white icons were
1.05:1 on Paper's cream; the icons themselves are checked in
tests/ui_next/test_bar_readable_on_every_panel.py).

And the three recommended looks (polyglotic-hq 532): each as a caption
window - pinyin over the Chinese, word links on as a new learner has
them, the lookup card's sample dictionary giving the readings - and their
tiles, in the window theme's dark and light."""

from collections.abc import Callable
from dataclasses import asdict, replace

from PySide6.QtWidgets import QVBoxLayout, QWidget

from polyglotic_desktop.core.listening.display import WordLinks
from polyglotic_desktop.perf import budgets
from polyglotic_desktop.ui import theme as todays_theme
from polyglotic_desktop.ui_next import style
from polyglotic_desktop.ui_next.colour_controls import RecommendedTiles
from polyglotic_desktop.ui_next.views.caption_window import CaptionLook
from polyglotic_desktop.ui_next.views.presets import (
    LOOKS,
    PRESETS,
    ColourPreset,
    with_look,
)
from polyglotic_desktop.ui_next.views.presets import look_of as recommended_of
from tools.ui_lab.caption_window import hovered, window
from tools.ui_lab.lab import Lab, State
from tools.ui_lab.lookup import _drawn


def look_of(preset: ColourPreset) -> CaptionLook:
    return replace(
        CaptionLook(),
        original=preset.original,
        translation=preset.translation,
        background=preset.background,
        opacity=preset.opacity,
    )


def preset_window(preset: ColourPreset) -> Callable[[Lab], QWidget]:
    def run(lab: Lab) -> QWidget:
        shown = window(lab, captions=6)
        before = PRESETS[1] if preset is PRESETS[0] else PRESETS[0]
        looks = [look_of(before), look_of(preset)]
        lab.time(
            "preset",
            lambda: shown.set_look(looks[shown.look == looks[0]]),
            repeat=6,
            budget=budgets.CLICK,
        )
        shown.set_look(looks[1])
        lab.pump()
        return shown

    return run


def preset_bar(preset: ColourPreset) -> Callable[[Lab], QWidget]:
    def run(lab: Lab) -> QWidget:
        shown = window(lab, captions=6)
        shown.set_look(look_of(preset))
        hovered(lab, shown)
        return shown

    return run


def recommended(key: str) -> Callable[[Lab], QWidget]:
    """A recommended look (532), as a new learner who picked it sees it:
    word links on (polyglotic-hq 478), pinyin over the Chinese."""

    def run(lab: Lab) -> QWidget:
        start = CaptionLook(word_links=WordLinks.ARROWS, reading_lines=("zh",))
        look = with_look(start, key)
        assert recommended_of(look) is not None
        return _drawn(lab, look)

    return run


def tiles(mode: str) -> Callable[[Lab], QWidget]:
    """The recommended looks' tiles in Settings' column, in the default
    window theme's `mode` (dark or light), Quiet chosen."""

    def run(lab: Lab) -> QWidget:
        palette = todays_theme.palette(mode, todays_theme.DEFAULT_THEME)
        family = todays_theme.THEMES[todays_theme.DEFAULT_THEME].heading_family
        theme = style.Theme(asdict(palette), family, dark=mode == "dark")
        style.use(theme)
        shown = QWidget()
        shown.setObjectName("Content")
        shown.setStyleSheet(style.stylesheet(theme))
        column = QVBoxLayout(shown)
        column.setContentsMargins(16, 16, 16, 16)
        made = RecommendedTiles(shown)
        made.show_look(LOOKS[0])
        column.addWidget(made)
        shown.resize(style.px(600), style.px(140))
        shown.show()
        lab.pump()
        return shown

    return run


STATES = (
    [
        State(
            f"ui_next.preset_{preset.key}",
            preset_window(preset),
            gated=True,
            scene=True,
        )
        for preset in PRESETS
    ]
    + [
        State(
            f"ui_next.preset_{preset.key}_bar",
            preset_bar(preset),
            gated=True,
            scene=True,
        )
        for preset in PRESETS
    ]
    + [
        State(f"ui_next.look_{look.key}", recommended(look.key), gated=True, scene=True)
        for look in LOOKS
    ]
    + [
        State(f"ui_next.looks_tiles_{mode}", tiles(mode), gated=True)
        for mode in ("dark", "light")
    ]
)
