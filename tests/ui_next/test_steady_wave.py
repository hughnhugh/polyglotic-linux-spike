"""Steady's wave in a caption window (polyglotic-hq 1070, `views.wave`): a
shown word's letters light one after another across the time it took to
say, only on the lines lighting, and never with the OS's reduced motion."""

from collections.abc import Iterator
from functools import partial

import pytest
from PySide6.QtCore import QRect
from PySide6.QtWidgets import QApplication
from tests.budget_judge import sampled, within
from tests.ui_next.test_lookup_card import AREA

from polyglotic_desktop.core.listening.captions import (
    CaptionKind,
    CaptionUpdate,
    Clause,
    Language,
    SpeechTimes,
)
from polyglotic_desktop.core.listening.display import RowKind
from polyglotic_desktop.core.listening.playout import Ahead, PlayoutRules
from polyglotic_desktop.core.listening.timing import CaptionId, CaptionMode
from polyglotic_desktop.perf import budgets
from polyglotic_desktop.ui.recorded_captions import APP, MIC
from polyglotic_desktop.ui_next import caption_window
from polyglotic_desktop.ui_next.caption_window import Canvas, CaptionWindow
from polyglotic_desktop.ui_next.caption_windows import CaptionWindows
from polyglotic_desktop.ui_next.views.wave import WAVE_FADE

EN = Language("en")
FRAME = 1 / 60


class Clock:
    def __init__(self) -> None:
        self.now = 100.0

    def __call__(self) -> float:
        return self.now


def update(
    name: str, text: str, start: float, end: float, *, done: bool = False
) -> CaptionUpdate:
    return CaptionUpdate(
        CaptionId(name), APP, CaptionKind.FINISHED if done else CaptionKind.LIVE,
        (Clause(text, {EN: "..."} if done else {}),), EN, (EN,),
        times=SpeechTimes(start, end, end, end + 0.1),
    )  # fmt: skip


@pytest.fixture
def clock() -> Clock:
    return Clock()


@pytest.fixture(params=[True, False], ids=["cards", "zones"])
def windows(
    request: pytest.FixtureRequest, qapp: QApplication, clock: Clock
) -> Iterator[CaptionWindows]:
    found = CaptionWindows(None, MIC, lambda: [AREA])
    found.set_cards(request.param)
    found.word_clock = clock
    found.set_captioned([("app", APP)])
    found.set_timing(CaptionMode.STEADY)
    found.set_playout(PlayoutRules(delay=2.0, ahead=Ahead.WAITING))
    window = found.windows["app"]
    window.clock = clock
    window.resize(700, 420)
    window.show()
    yield found
    found.close()


@pytest.fixture
def motion(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(caption_window, "reduced_motion", lambda: False)


def at(windows: CaptionWindows, clock: Clock, now: float) -> CaptionWindow:
    """The window drawn at `now`, every word due by then shown at its time."""
    while (due := windows.playout.due()) is not None and due <= now:
        clock.now = due
        windows.release_words()
        if windows.playout.due() == due:
            break
    clock.now = now
    window = windows.windows["app"]
    window.grab()
    return window


def earlier(windows: CaptionWindows, clock: Clock, lines: int, words: str) -> None:
    """`lines` finished captions said and shown before 90 s."""
    for n in range(lines):
        clock.now = 60.0 + 2 * n
        said = update(
            f"old{n}", words.format(n), clock.now - 2, clock.now - 1, done=True
        )
        windows.apply(said)
    at(windows, clock, 90.0)


def lighting(window: CaptionWindow) -> list[tuple[Canvas, int, tuple[float, ...]]]:
    """Each original row lighting now: its canvas, how many of its letters
    are lit all the way and how far each of the front is."""
    out = []
    now = window.clock()
    for canvas in (window.canvas, window.zone):
        for key, wave in canvas.waves.rows.items():
            if key[1] is RowKind.ORIGINAL:
                lit = wave.lit(now, WAVE_FADE.value)
                out.append((canvas, lit.full, lit.front))
    return out


@pytest.mark.usefixtures("motion")
def test_a_shown_words_letters_light_one_after_another(
    windows: CaptionWindows, clock: Clock
) -> None:
    # four words said over the last 2 s: "cat" is due at 98.5 - 0.3 + 2.0
    clock.now = 100.0
    windows.apply(update("one", "cat dog bird fish", 98.0, 100.0))
    window = at(windows, clock, 100.2)
    assert window.lighting.get(window.view.lines[-1].caption_id, 0.0) > 0.0
    halfway = at(windows, clock, 100.45)
    rows = lighting(halfway)
    assert rows and any(front for _, _, front in rows)  # a soft front, part lit
    assert all(full < len("cat ") for _, full, _ in rows)
    done = at(windows, clock, 100.7 + WAVE_FADE.value)
    assert any(full >= len("cat") for _, full, _ in lighting(done))


@pytest.mark.usefixtures("motion")
def test_only_the_lighting_lines_are_drawn_again_for_it(
    windows: CaptionWindows, clock: Clock, monkeypatch: pytest.MonkeyPatch
) -> None:
    earlier(windows, clock, 6, "line {} said before.")
    clock.now = 100.0
    windows.apply(update("one", "cat dog bird fish", 98.0, 100.0))
    at(windows, clock, 100.6)  # the new card or line in place, "cat" lit
    window = at(windows, clock, 100.75)  # "dog" shown at 100.7, lighting
    asked: list[QRect] = []
    for canvas in (window.canvas, window.zone):
        monkeypatch.setattr(canvas, "update", lambda *rect: asked.extend(rect))
    clock.now = 100.85
    window._tick()
    waving = [r for r in asked if isinstance(r, QRect)]
    assert waving and all(r.height() < window.height() / 2 for r in waving)


def test_with_reduced_motion_a_word_lights_whole(
    windows: CaptionWindows, clock: Clock, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(caption_window, "reduced_motion", lambda: True)
    clock.now = 100.0
    windows.apply(update("one", "cat dog bird fish", 98.0, 100.0))
    window = at(windows, clock, 100.3)
    assert lighting(window) == []  # no wave: as established says
    assert all(not canvas.waves.rows for canvas in (window.canvas, window.zone))


@pytest.mark.usefixtures("motion")
def test_a_frame_of_the_wave_is_within_its_budget(
    windows: CaptionWindows, clock: Clock, qapp: QApplication
) -> None:
    earlier(windows, clock, 12, "line {} said before it.")
    clock.now = 100.0
    words = " ".join(f"word{n}" for n in range(14))
    windows.apply(update("one", words, 96.0, 100.0))
    window = at(windows, clock, 100.0)

    def frame(n: int) -> None:
        at(windows, clock, 100.0 + n * FRAME)
        window.canvas.repaint()
        window.zone.repaint()

    within(budgets.FRAME, lambda: sampled(qapp, [partial(frame, n) for n in range(30)]))
