"""Each caption timing, and every caption-window control whose name doesn't
say enough, explains itself on hover, in plain words (the user's rehearsal
feedback F22, polyglotic-hq 249, 2026-11-08: "there should be tooltips for
each of timings")."""

from PySide6.QtWidgets import QApplication, QPushButton
from tests.ui_next.test_caption_window import window_of
from tests.ui_next.test_transcript_window import DISCORD, made_up

from polyglotic_desktop.core.listening.timing import (
    OFFERED_MODES,
    CaptionMode,
    default_caption_mode,
)
from polyglotic_desktop.ui_next import help_page
from polyglotic_desktop.ui_next.caption_window import timing_name, timing_tip
from polyglotic_desktop.ui_next.panels import TimingPanel
from polyglotic_desktop.ui_next.transcript_window import TranscriptWindow
from polyglotic_desktop.ui_next.views.panels import Timing, TimingView
from polyglotic_desktop.ui_next.views.transcript import TranscriptChoices


def test_each_timing_says_what_it_does() -> None:
    tips = {mode: timing_tip(mode) for mode in OFFERED_MODES}
    assert len(set(tips.values())) == 4
    for mode, tip in tips.items():
        assert tip and tip != timing_name(mode)
    assert len({timing_name(mode) for mode in OFFERED_MODES}) == 4
    assert "half a second" in tips[CaptionMode.WHOLE]  # what 145 measured
    assert "one by one" in tips[CaptionMode.STEADY]
    # Quick preview, retired, reads as Steady wherever a name is still asked
    assert timing_name(CaptionMode.PREVIEW) == timing_name(CaptionMode.STEADY)


def test_the_windows_controls_say_what_they_do(qapp: QApplication) -> None:
    window = window_of(qapp)
    try:
        for mode in OFFERED_MODES:
            assert window.controls[mode.value].toolTip() == timing_tip(mode)
        assert CaptionMode.PREVIEW.value not in window.controls
        for name in ("settings", "all_settings", "transcript"):
            control = window.controls[name]
            assert control.toolTip() and control.toolTip() != control.text(), name
        assert window.pill.toolTip()
        window.hovered = True
        window._show_band(True)
        window.toggle_settings()
        popover = window.popover
        assert popover is not None
        assert popover.language.toolTip()
        steady = popover.findChild(
            QPushButton, "settings_popover.caption_window.steady"
        )
        assert steady is not None and steady.toolTip() == timing_tip(CaptionMode.WHOLE)
    finally:
        window.close()


def test_the_timing_panel_s_choices_say_what_they_do(qapp: QApplication) -> None:
    panel = TimingPanel(TimingView(Timing(CaptionMode.STEADY, 1.5)))
    assert [b.toolTip() for b in panel.mode.buttons] == [
        timing_tip(mode) for mode in OFFERED_MODES
    ]


def test_a_transcript_s_timing_menu_says_what_each_does(qapp: QApplication) -> None:
    window = TranscriptWindow("Discord.exe", made_up(), DISCORD, TranscriptChoices())
    try:
        for mode, action in window.timing_actions.items():
            assert action.toolTip() == timing_tip(mode)
        menu = window.buttons["timing"].menu()
        assert menu is not None and menu.toolTipsVisible()
    finally:
        window.close()


def test_the_default_timing_is_named_first_wherever_it_s_chosen(
    qapp: QApplication,
) -> None:
    """Steady is the default (desktop decision 0246, polyglotic-hq 526):
    Help's "When do captions appear?" names it first, the others after
    it, by the names the app gives them, and the Timing panel offers them
    in the same order."""
    default = default_caption_mode()
    assert default is CaptionMode.STEADY
    spectrum = list(OFFERED_MODES)
    panel = TimingPanel(TimingView(Timing(default, 1.5)))
    assert [b.text() for b in panel.mode.buttons] == [timing_name(m) for m in spectrum]
    [said] = [
        text
        for title, text in help_page.questions()
        if title == "When do captions appear?"
    ]
    assert said.startswith(f"{timing_name(default)}, the default:")
    places = [said.index(timing_name(mode)) for mode in spectrum]
    assert places == sorted(places)
    assert "Settings > Timing" in said  # Home's panel went in 261, a section in 304
