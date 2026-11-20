"""Presets for use cases (polyglotic-hq 556): the bar's preset chip and its
dropdown open, on Custom as a new learner has it and on Conversation;
Video's subtitles along the bottom of a stand-in screen, as the preset
puts every window there; and Settings > Presets on Video, with what it
changes. The menus are made from real settings (`ui.use_presets`), as
`main` makes them."""

from collections.abc import Callable
from dataclasses import replace

from PySide6.QtCore import QPoint, QPointF, Qt
from PySide6.QtGui import QColor, QLinearGradient, QPainter, QPaintEvent
from PySide6.QtWidgets import QWidget

from polyglotic_desktop.core.listening.display import WordLinks
from polyglotic_desktop.perf import budgets
from polyglotic_desktop.ui import use_presets
from polyglotic_desktop.ui.recorded_captions import APP, MIC
from polyglotic_desktop.ui.settings import AppSettings
from polyglotic_desktop.ui_next.caption_window import CaptionWindow
from polyglotic_desktop.ui_next.caption_windows import CaptionWindows
from polyglotic_desktop.ui_next.preset_popover import preset_name
from polyglotic_desktop.ui_next.presets_card import change_words
from polyglotic_desktop.ui_next.views.caption_window import CaptionLook, TextEdge
from polyglotic_desktop.ui_next.views.placement import Rect
from polyglotic_desktop.ui_next.views.preset_menu import (
    PresetItem,
    PresetMenu,
    PresetsView,
    Show,
)
from tools.ui_lab import pages
from tools.ui_lab.caption_window import AREA, LABELS, _areas, _Together, hovered, window
from tools.ui_lab.lab import Lab, State
from tools.ui_lab.new_parts import finished


def menu_of(value: AppSettings, my_speech: bool = False) -> PresetMenu:
    """The menu `main` would make of `value` (`main.preset_menu`), the
    look's word links and readings from the settings themselves."""
    items = tuple(
        PresetItem(
            key,
            value.preset_names.get(key) or preset_name(key),
            key not in use_presets.ORDER,
        )
        for key in use_presets.keys(value)
    )
    show = (
        Show.ORIGINAL
        if not value.show_translation
        else Show.TRANSLATION
        if not value.show_original
        else Show.BOTH
    )
    return PresetMenu(
        items,
        value.preset,
        show,
        links=value.word_links != WordLinks.OFF.value,
        quiet=value.quiet_view,
        readings=value.preset != use_presets.VIDEO,  # a new learner's: on
        my_speech=my_speech,
        changes=change_words(use_presets.differences(value, value.preset)),
        can_add=use_presets.can_add(value),
    )


def on(key: str) -> AppSettings:
    return use_presets.chosen(AppSettings(), key)


def dropdown(key: str, my_speech: bool = False) -> Callable[[Lab], QWidget]:
    """A window's bar with its preset chip, the dropdown open under it."""

    def run(lab: Lab) -> QWidget:
        value = on(key)
        look = replace(CaptionLook(), word_links=WordLinks(value.word_links))
        shown = window(lab, look=look, show_mic=my_speech)
        menu = menu_of(value, my_speech)  # ticked as the window shows it
        shown.set_presets(replace(menu, readings=bool(shown.look.reading_lines)))
        hovered(lab, shown)

        def toggle() -> None:
            shown.toggle_presets()

        for _ in range(6):  # open, close, open, ...: each a click
            lab.time("presets_dropdown", toggle, budget=budgets.CLICK)
        shown.toggle_presets()
        lab.pump()
        opened = shown.presets
        assert opened is not None
        lab.closing.append(shown.close)
        return _Together([shown, opened])

    return run


class _Screen(QWidget):
    """A stand-in screen: a film's frame, bright sky to dark ground, the
    size of the work area, with the windows where they are on it - scaled
    to half, as the picture of a whole screen is."""

    SCALE = 0.5

    def __init__(self, windows: list[CaptionWindow], area: Rect = AREA) -> None:
        super().__init__()
        self.windows = windows
        self.resize(round(area.width * self.SCALE), round(area.height * self.SCALE))

    def places(self) -> list[tuple[QWidget, QPoint, float]]:
        return [
            (
                each,
                QPoint(round(each.x() * self.SCALE), round(each.y() * self.SCALE)),
                1.0,
            )
            for each in self.windows
        ]

    def paintEvent(self, event: QPaintEvent) -> None:
        painter = QPainter(self)
        sky = QLinearGradient(QPointF(0, 0), QPointF(0, self.height()))
        sky.setColorAt(0.0, QColor("#cfe3f2"))
        sky.setColorAt(0.55, QColor("#e8c48f"))
        sky.setColorAt(0.75, QColor("#5b4a3a"))
        sky.setColorAt(1.0, QColor("#1d1b19"))
        painter.fillRect(self.rect(), sky)
        painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
        for each in self.windows:
            picture = each.grab()
            at = QPoint(round(each.x() * self.SCALE), round(each.y() * self.SCALE))
            painter.drawPixmap(
                at,
                picture.scaled(
                    round(each.width() * self.SCALE),
                    round(each.height() * self.SCALE),
                    Qt.AspectRatioMode.IgnoreAspectRatio,
                    Qt.TransformationMode.SmoothTransformation,
                ),
            )
        painter.end()


QHD = Rect(0, 0, 2560, 1400)
"""A 1440p screen's work area, its taskbar left out."""


def subtitles(area: Rect = AREA) -> Callable[[Lab], QWidget]:
    """Video, film & TV on a screen with work area `area` (1080p's or
    1440p's): the window along its bottom, wide, its text 4.5 % of the
    screen's height, two lines tall, no source or language line, no panel
    and an outline round the letters (556)."""

    def run(lab: Lab) -> QWidget:
        return _subtitles(lab, area)

    return run


def _subtitles(lab: Lab, area: Rect) -> QWidget:
    value = on(use_presets.VIDEO)
    windows = CaptionWindows(None, MIC, lambda: [area])
    windows.set_labels(LABELS, "You")
    windows.set_look(
        replace(
            CaptionLook(),
            opacity=value.opacity,
            show_language=value.show_language,
            show_source=value.show_source,
            edge=TextEdge(value.caption_edge),
            word_links=WordLinks.OFF,
        )
    )
    windows.set_presets(menu_of(value))
    windows.set_captioned([("Video Player.exe", APP)])
    shown = windows.windows["Video Player.exe"]
    shown.always_shown = True
    for update in finished(12):
        windows.apply(update)
    lab.time(
        "subtitles_on",
        lambda: windows.set_subtitles((value.subtitle_size, value.subtitle_width)),
        budget=budgets.CLICK,
    )
    lab.pump()
    lab.closing.append(windows.close)
    return _Screen([shown], area)


def subtitles_back(lab: Lab) -> QWidget:
    """And back: the window where the learner had it, at its own size,
    when another preset is picked."""
    value = on(use_presets.VIDEO)
    windows = CaptionWindows(None, MIC, _areas)
    windows.set_labels(LABELS, "You")
    windows.set_captioned([("Video Player.exe", APP)])
    shown = windows.windows["Video Player.exe"]
    shown.always_shown = True
    for update in finished(12):
        windows.apply(update)
    windows.set_subtitles((value.subtitle_size, value.subtitle_width))
    lab.pump()
    lab.time("subtitles_off", lambda: windows.set_subtitles(None), budget=budgets.CLICK)
    lab.pump()
    lab.closing.append(windows.close)
    return _Screen([shown])


def settings_presets(lab: Lab) -> QWidget:
    """Settings > Presets, Video in use: the presets, and what it changes."""
    value = on(use_presets.VIDEO)
    value = replace(value, word_links="arrows")  # a learner's change in it, say
    value = use_presets.saved_into(value)
    view = PresetsView(menu_of(value))
    return pages.settings("presets", presets=view)(lab)


STATES = [
    State(f"ui_next.{name}", run, gated=True, scene=scene)
    for name, run, scene in (
        ("w1_presets", dropdown(use_presets.EVERYDAY), True),
        ("w1_presets_conversation", dropdown(use_presets.CONVERSATION, True), True),
        ("w1_subtitles", subtitles(), False),
        ("w1_subtitles_1440p", subtitles(QHD), False),
        ("w1_subtitles_back", subtitles_back, False),
        ("w4_settings_presets", settings_presets, False),
    )
]
