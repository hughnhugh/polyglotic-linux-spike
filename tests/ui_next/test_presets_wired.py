"""Presets wired in `main` (polyglotic-hq 556): the menu the windows and
Settings show, made from the settings; a preset picked from the bar saves
the look's change waiting into the one before, and the windows follow -
my speech, Video's subtitles, the original only."""

import time
from collections.abc import Iterator
from dataclasses import replace

import pytest
from PySide6.QtWidgets import QApplication
from tests.ui.fakes import MemorySettingsStore

from polyglotic_desktop.main import (
    Panels,
    caption_look,
    follow_presets,
    lines_changes,
    preset_menu,
)
from polyglotic_desktop.ui import use_presets
from polyglotic_desktop.ui.recorded_captions import APP, MIC
from polyglotic_desktop.ui.settings import AppSettings, Settings
from polyglotic_desktop.ui_next.caption_windows import (
    SUBTITLES_SAID_SEC,
    CaptionWindows,
)
from polyglotic_desktop.ui_next.views.placement import Rect
from polyglotic_desktop.ui_next.views.preset_menu import Show


def areas() -> list[Rect]:
    return [Rect(0, 0, 1920, 1040)]


@pytest.fixture
def wired(qapp: QApplication) -> Iterator[tuple[Settings, CaptionWindows, Panels]]:
    settings = Settings(MemorySettingsStore({}))
    windows = CaptionWindows(None, MIC, areas)
    windows.set_captioned([("Discord.exe", APP)])
    panels = Panels(settings, windows)
    settings.changed.connect(lambda: follow_presets(windows, settings.value))
    yield settings, windows, panels
    windows.close()


def test_the_menu_names_every_preset_and_what_shows() -> None:
    value = use_presets.added(AppSettings(), "Anime nights")
    value = replace(value, show_translation=False)
    menu = preset_menu(value, caption_look(value), my_speech=True)
    assert [i.key for i in menu.items] == [
        "everyday",
        "conversation",
        "video",
        "learning",
        "own1",
    ]
    assert menu.name == "Anime nights" and menu.chosen_own
    assert menu.show is Show.ORIGINAL and menu.my_speech and menu.links


def test_show_is_two_settings() -> None:
    assert lines_changes(Show.TRANSLATION) == {
        "show_original": False,
        "show_translation": True,
    }
    assert lines_changes(Show.ORIGINAL) == {
        "show_original": True,
        "show_translation": False,
    }


def test_conversation_from_the_bar_turns_my_speech_on_everywhere(
    wired: tuple[Settings, CaptionWindows, Panels],
) -> None:
    settings, windows, panels = wired
    assert not windows.show_mic_anywhere
    panels.choose_preset("conversation")
    assert settings.value.preset == "conversation" and settings.value.my_speech
    assert windows.show_mic_anywhere
    assert windows.preset_menu.chosen == "conversation"  # the chip follows


def said(windows: CaptionWindows) -> str | None:
    window = windows.windows["Discord.exe"]
    return window.notices.showing(time.monotonic())[1]


def test_video_from_the_bar_makes_subtitles_and_back_saying_so_briefly(
    wired: tuple[Settings, CaptionWindows, Panels],
) -> None:
    settings, windows, panels = wired
    panels.choose_preset("video")
    assert windows.subtitles == (settings.value.subtitle_size, 0.8)
    assert said(windows) == "Subtitles: along the bottom of the screen"
    later = time.monotonic() + SUBTITLES_SAID_SEC + 0.1  # gone, not left on a film
    assert windows.windows["Discord.exe"].notices.showing(later)[1] is None
    panels.choose_preset("everyday")
    assert windows.subtitles is None
    assert said(windows) == "Back where you put it"


def test_a_start_on_video_moves_the_windows_saying_nothing(
    qapp: QApplication,
) -> None:
    settings = Settings(MemorySettingsStore({}))
    settings.change(use_presets.chosen(settings.value, "video"))
    windows = CaptionWindows(None, MIC, areas)
    try:
        windows.set_captioned([("Discord.exe", APP)])
        follow_presets(windows, settings.value)  # as the app starts
        assert windows.subtitles is not None
        assert said(windows) is None
    finally:
        windows.close()


def test_a_look_change_waiting_goes_into_the_preset_before(
    wired: tuple[Settings, CaptionWindows, Panels],
) -> None:
    settings, _windows, panels = wired
    panels.look.set_show_source(False)  # waits to settle
    panels.choose_preset("video")
    assert settings.value.preset_values["everyday"]["show_source"] is False


def test_original_only_from_the_bar_is_every_windows(
    wired: tuple[Settings, CaptionWindows, Panels],
) -> None:
    settings, windows, panels = wired
    panels.set_lines("original")
    assert not settings.value.show_translation
    assert windows.original_only and windows.targets()[APP] == ()
    assert settings.value.preset_values["everyday"]["show_translation"] is False
