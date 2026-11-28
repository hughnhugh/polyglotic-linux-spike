"""Steady's and Calm's wave (`views.wave`, polyglotic-hq 1070): established
letters light one after another at the speaker's pace, behind a soft front
- the founder's "clean mexican wave in line with the pace of the speech"."""

import pytest
from tests.ui_next.paced_replay import FRAME, Heard, letters_lit

from polyglotic_desktop.core.listening.captions import (
    CaptionKind,
    CaptionUpdate,
    Clause,
    Language,
    SpeechTimes,
    WordTime,
)
from polyglotic_desktop.core.listening.playout import DELAY_SEC, Ahead, PlayoutRules
from polyglotic_desktop.core.listening.sources import SourceId
from polyglotic_desktop.core.listening.timing import CaptionId
from polyglotic_desktop.ui_next.views.wave import WAVE_FADE, Lit, Wave, Waves, ease

APP = SourceId("app")
EN, ZH = Language("en"), Language("zh")
STEADY = PlayoutRules(delay=DELAY_SEC, hold_back=1, ahead=Ahead.WAITING)
CALM = PlayoutRules(
    delay=DELAY_SEC, hold_back=1, ahead=Ahead.WAITING, established_only=True
)


# -- one row's letters ------------------------------------------------------------------


def test_a_words_letters_begin_one_after_another_across_its_time() -> None:
    wave = Wave()
    wave.to(len("cat "), 10.0, 0.3, "cat ")
    # the speaker's three letters across 0.3 s; the space with the "t"
    assert wave.starts == pytest.approx([10.0, 10.1, 10.2, 10.2])


def test_marks_and_spaces_light_with_the_letter_before_them() -> None:
    wave = Wave()
    wave.to(len("ok, "), 5.0, 0.2, "ok, ")
    assert wave.starts == pytest.approx([5.0, 5.1, 5.1, 5.1])


def test_each_chinese_character_is_a_letter() -> None:
    wave = Wave()
    wave.to(len("我们，"), 1.0, 0.4, "我们，")
    assert wave.starts == pytest.approx([1.0, 1.2, 1.2])


def test_the_front_is_soft_a_few_letters_wide() -> None:
    wave = Wave()
    text = "hello world "
    wave.to(len(text), 0.0, 0.6, text)  # 10 letters, one each 60 ms
    fade = 0.16
    lit = wave.lit(0.3, fade)
    assert 0 < lit.full < 5 < lit.full + len(lit.front) < len(text)
    assert list(lit.front) == sorted(lit.front, reverse=True)
    assert all(0.0 < part < 1.0 for part in lit.front)
    assert 2 <= len(lit.front) <= 4  # a soft edge, not a smear
    assert wave.lit(0.6 + fade, fade) == Lit(len(text))


def test_without_time_a_word_lights_whole_as_before() -> None:
    # reduced motion: the window gives no time and no fade
    wave = Wave()
    wave.to(len("cat "), 10.0, 0.0, "cat ")
    assert wave.lit(10.0, 0.0) == Lit(len("cat "))


def test_a_word_shown_before_the_last_finished_takes_the_rest_along() -> None:
    wave = Wave()
    wave.to(len("one "), 0.0, 0.6, "one two ")
    wave.to(len("one two "), 0.2, 0.3, "one two ")
    # "e" (0.4) had yet to begin: it begins with "two", all across 0.3 s
    assert wave.starts[:2] == pytest.approx([0.0, 0.2])
    assert wave.starts == sorted(wave.starts)
    assert wave.starts[-1] <= 0.2 + 0.3


def test_a_correction_takes_the_letters_after_it_away() -> None:
    wave = Wave()
    wave.to(len("one two "), 0.0, 0.5, "one two ")
    wave.to(len("one "), 1.0, 0.5, "one tea ")
    assert len(wave.starts) == len("one ")


def test_a_rows_later_line_has_its_own_share() -> None:
    lit = Lit(5, (0.8, 0.4))
    assert lit.within(0, 4) == Lit(4)
    assert lit.within(4, 4) == Lit(1, (0.8, 0.4))
    assert lit.within(6, 4) == Lit(0, (0.4,))
    assert lit.within(8, 4) == Lit(0)


def test_the_window_forgets_rows_it_no_longer_draws() -> None:
    waves = Waves()
    waves.to((1, "original", 0), 4, 0.0, 0.3, "cat ")
    assert waves.has(1) and waves.moving(0.1, 0.16) == {1}
    waves.drawn()
    assert waves.has(1)
    waves.drawn()  # not drawn this time
    assert not waves.has(1)
    assert waves.moving(10.0, 0.16) == set()


def test_the_fade_is_a_named_short_ease() -> None:
    assert 0.12 <= WAVE_FADE.value <= 0.2  # the brief: about 120-200 ms
    assert ease(0.0) == 0.0 and ease(1.0) == 1.0 and ease(0.5) == 0.5


# -- against the speech -------------------------------------------------------------------


STEP = 0.3  # seconds a word
SAID = 0.24  # of which said; the rest a gap before the next


def timed(text: str, start: float, step: float = STEP) -> list[tuple[str, float]]:
    return [(word, start + n * step) for n, word in enumerate(text.split(" "))]


def spoken(words: list[tuple[str, float]], joined: str) -> tuple[Clause, ...]:
    """The words as one clause, joined by `joined`, with their word times."""
    text, times, at = "", [], 0
    for n, (word, said) in enumerate(words):
        if n:
            text += joined
            at += len(joined)
        times.append(WordTime((at, at + len(word)), said, said + SAID))
        text += word
        at += len(word)
    return (Clause(text, {EN: "..."}, words=tuple(times)),)


def caption(
    name: str, words: list[tuple[str, float]], joined: str = " "
) -> list[Heard]:
    """Live updates once a second, each answered half a second after it was
    sent and established all but its newest word as the one before had it;
    then the finished caption 0.8 s after the last word."""
    start = words[0][1]
    end = words[-1][1] + STEP
    out: list[Heard] = []
    k = 1
    before = 0
    while start + k < end:
        sent = start + k
        heard = [(w, at) for w, at in words if at + SAID <= sent]
        clauses = spoken(heard, joined) if heard else ()
        agree = min(before, len(heard) - 1)
        established = sum(len(w) + len(joined) for w, _ in heard[:agree])
        if heard:
            out.append(
                (
                    sent + 0.5,
                    CaptionUpdate(
                        CaptionId(name),
                        APP,
                        CaptionKind.LIVE,
                        clauses,
                        EN,
                        (EN,),
                        times=SpeechTimes(start, sent, sent, sent + 0.5),
                        established=max(0, established - len(joined) * bool(agree)),
                    ),
                )
            )
        before, k = len(heard), k + 1
    out.append(
        (
            end + 0.8,
            CaptionUpdate(
                CaptionId(name),
                APP,
                CaptionKind.FINISHED,
                spoken(words, joined),
                EN,
                (EN,),
                times=SpeechTimes(start, end, end, end + 0.8),
            ),
        )
    )
    return out


ENGLISH = "the train leaves at seven so we should go now before it rains again"
CHINESE = "我们现在就走吧因为火车七点开走了"


def stream(chinese: bool) -> list[Heard]:
    if chinese:
        first = timed(" ".join(CHINESE[:8]), 0.0, 0.25)
        second = timed(" ".join(CHINESE[8:]), 2.0, 0.25)
        return caption("one", first, "") + caption("two", second, "")
    words = timed(ENGLISH, 0.0)
    return caption("one", words[:7]) + caption("two", timed(" ".join(
        w for w, _ in words[7:]), words[6][1] + STEP))  # fmt: skip


@pytest.mark.parametrize("chinese", [False, True], ids=["english", "chinese"])
@pytest.mark.parametrize("rules", [STEADY, CALM], ids=["steady", "calm"])
def test_each_letter_lights_with_the_speech_a_delay_behind(
    rules: PlayoutRules, chinese: bool
) -> None:
    found = letters_lit(stream(chinese), rules)
    assert found
    for letter, began in found:
        word_late = max(0.0, letter.shown - (letter.word_said + rules.delay))
        # never before its moment and the delay; after it by no more than
        # its word was shown late (the playout's), and a frame
        assert began >= letter.said + rules.delay - FRAME, letter
        late = began - (letter.said + rules.delay)
        assert late <= max(word_late, 0.0) + FRAME, (letter, late)


def test_a_word_lit_whole_is_ahead_of_its_letters() -> None:
    # the planted break of the wave's rule: lit whole, a word's later
    # letters light before they were said, plus the delay
    found = letters_lit(stream(False), STEADY, lighting=False)
    early = [
        letter.said + STEADY.delay - began
        for letter, began in found
        if began < letter.said + STEADY.delay - FRAME
    ]
    assert len(early) > len(found) // 3
    assert max(early) > 3 * FRAME


def test_a_line_done_lighting_is_forgotten_whole() -> None:
    waves = Waves()
    waves.to((1, "original", 0), 4, 0.0, 0.3, "cat ")
    waves.to((1, "translation", 0), 2, 0.0, 0.3, "猫。")
    waves.to((2, "original", 0), 4, 0.0, 0.3, "dog ")
    waves.forget(1)
    assert not waves.has(1) and waves.has(2)
