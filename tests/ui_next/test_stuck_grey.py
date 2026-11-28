"""No line stays grey once its words are settled (polyglotic-hq 1070): the
paced modes' words through the playout, Steady's cards and the caption
history (`paced_replay`), each planted fault in the shape of the founder's
screenshot of 2026-11-29 - continuous speech from a video, captions back to
back, earlier ones finishing while later ones are answered."""

import pytest
from tests.ui_next.paced_replay import FRAME, Heard, play

from polyglotic_desktop.core.listening.captions import (
    CaptionKind,
    CaptionUpdate,
    Clause,
    Language,
    SpeechTimes,
)
from polyglotic_desktop.core.listening.playout import (
    DELAY_SEC,
    Ahead,
    PlayoutRules,
)
from polyglotic_desktop.core.listening.sources import SourceId
from polyglotic_desktop.core.listening.timing import CaptionId

APP = SourceId("app")
EN, ZH = Language("en"), Language("zh")
STEP = 0.3
"""Seconds a word: continuous speech, about 200 words a minute."""
STEADY = PlayoutRules(delay=DELAY_SEC, hold_back=1, ahead=Ahead.WAITING)
CALM = PlayoutRules(
    delay=DELAY_SEC, hold_back=1, ahead=Ahead.WAITING, established_only=True
)
BOUND = DELAY_SEC + FRAME
"""A settled caption's words are all drawn established by the delay after
it, and a frame (the brief's bar)."""

UGLY = "ugly. Like I, I, I do not think I am this odd. What is going on? And like, first of all,"
MEAN = "it is kind of mean to be like, how dare this unusual person think they can come here."


def said(text: str, start: float) -> list[tuple[str, float]]:
    """`text`'s words, each with when it was said."""
    return [(word, start + n * STEP) for n, word in enumerate(text.split())]


def end_of(words: list[tuple[str, float]]) -> float:
    return words[-1][1] + STEP


def clauses(texts: list[str]) -> tuple[tuple[Clause, ...], list[int]]:
    """The words as the server's clauses - a sentence each - and where each
    word ends, in characters of the originals with nothing between them."""
    groups: list[list[str]] = [[]]
    for n, text in enumerate(texts):
        groups[-1].append(text)
        if text[-1] in ".?!" and n < len(texts) - 1:
            groups.append([])
    ends: list[int] = []
    counted = 0
    for group in groups:
        at = 0
        for text in group:
            at += (1 if at else 0) + len(text)
            ends.append(counted + at)
        counted += at
    made = tuple(Clause(" ".join(g), {ZH: "译" * len(g)}) for g in groups)
    return made, ends


def caption(
    name: str,
    words: list[tuple[str, float]],
    *,
    heard_as: dict[int, dict[int, str]] | None = None,
    answer: float = 0.5,
    finish_after: float = 0.8,
    finished_as: tuple[str, list[tuple[str, float]], tuple[str, ...]] | None = None,
) -> list[Heard]:
    """A caption's live updates, one a second of what was said so far, each
    answered `answer` s after it was sent and established as far as it and
    the one before agree (never its last word: server decision 0095); then
    its finished update, `finish_after` s after its last word. `heard_as`:
    words a live update heard differently, by update and word. `finished_as`:
    the finish as a join - the caption it is finished as, all its words and
    the captions it replaces."""
    start, end = words[0][1], end_of(words)
    out: list[Heard] = []
    before: list[str] | None = None
    k = 1
    while start + k < end:
        sent = start + k
        texts = [w for w, at in words if at < sent]
        for n, text in (heard_as or {}).get(k, {}).items():
            texts[n] = text
        agree = 0
        while before and agree < min(len(before), len(texts) - 1):
            if before[agree] != texts[agree]:
                break
            agree += 1
        made, ends = clauses(texts)
        out.append(
            (
                sent + answer,
                CaptionUpdate(
                    CaptionId(name),
                    APP,
                    CaptionKind.LIVE,
                    made,
                    EN,
                    (EN,),
                    times=SpeechTimes(start, sent, sent, sent + answer),
                    established=ends[agree - 1] if agree else 0,
                ),
            )
        )
        before, k = texts, k + 1
    as_name, all_words, replaces = finished_as or (name, words, ())
    made, _ = clauses([w for w, _ in all_words])
    done = end + finish_after
    out.append(
        (
            done,
            CaptionUpdate(
                CaptionId(as_name),
                APP,
                CaptionKind.FINISHED,
                made,
                EN,
                (EN,),
                tuple(CaptionId(r) for r in replaces),
                times=SpeechTimes(all_words[0][1], end, end, done),
            ),
        )
    )
    return out


def back_to_back(**ugly: object) -> list[Heard]:
    """The screenshot's shape: a long caption over three cards, then the
    next one straight after it, each finished as the next is answered."""
    first = said(UGLY, 0.0)
    second = said(MEAN, end_of(first))
    return caption("ugly", first, **ugly) + caption("mean", second)  # type: ignore[arg-type]


@pytest.mark.parametrize("cards", [True, False], ids=["cards", "rows"])
@pytest.mark.parametrize("rules", [STEADY, CALM], ids=["steady", "calm"])
def test_back_to_back_captions_are_all_established_in_time(
    rules: PlayoutRules, cards: bool
) -> None:
    assert play(back_to_back(), rules, cards=cards).stuck_grey <= BOUND


@pytest.mark.parametrize("cards", [True, False], ids=["cards", "rows"])
@pytest.mark.parametrize("rules", [STEADY, CALM], ids=["steady", "calm"])
def test_a_shown_word_heard_again_differently_leaves_nothing_after_it_grey(
    rules: PlayoutRules, cards: bool
) -> None:
    # "Like" is heard "Like," once it has been shown long enough to be
    # settled, and from then on: the established count used to stop where
    # the shown text and the update first differed, so the rest of the
    # caption - on cards, of every card it is on - stayed grey until the
    # caption, or the card, was finished
    misheard = {k: {1: "Like,"} for k in range(2, 12)}
    found = play(back_to_back(heard_as=misheard), rules, cards=cards)
    assert found.stuck_grey <= BOUND, found.worst


@pytest.mark.parametrize("cards", [True, False], ids=["cards", "rows"])
@pytest.mark.parametrize("rules", [STEADY, CALM], ids=["steady", "calm"])
def test_a_joined_fragment_takes_the_place_of_the_live_caption_it_replaced(
    rules: PlayoutRules, cards: bool
) -> None:
    # "Are pretty" is a fragment: the speech after it is finished again as
    # it (the earlier caption's id), replacing that stretch's live caption
    fragment = said("Are pretty", 0.0)
    rest = said(UGLY, end_of(fragment) + 0.7)
    after = said(MEAN, end_of(rest))
    joined = ("are", fragment + rest, ("ugly",))
    events = [
        *caption("are", fragment),
        *caption("ugly", rest, finished_as=joined),
        *caption("mean", after),
    ]
    found = play(events, rules, cards=cards)
    assert found.stuck_grey <= BOUND, found.worst


@pytest.mark.parametrize("cards", [True, False], ids=["cards", "rows"])
@pytest.mark.parametrize("rules", [STEADY, CALM], ids=["steady", "calm"])
def test_words_finished_late_are_all_shown_by_the_delay_after(
    rules: PlayoutRules, cards: bool
) -> None:
    # every finished caption comes 2.5 s after its speech: the words it
    # confirms were said long before, and once came at the speaker's pace
    # from then on, the lag growing caption by caption
    first = said(UGLY, 0.0)
    second = said(MEAN, end_of(first))
    third = said(UGLY, end_of(second))
    events = [
        *caption("one", first, finish_after=2.5),
        *caption("two", second, finish_after=2.5),
        *caption("three", third, finish_after=2.5),
    ]
    found = play(events, rules, cards=cards)
    assert found.stuck_grey <= BOUND, found.worst


@pytest.mark.parametrize("cards", [True, False], ids=["cards", "rows"])
def test_a_live_update_after_its_caption_was_replaced_is_too_late(
    cards: bool,
) -> None:
    fragment = said("Are pretty", 0.0)
    rest = said(UGLY, end_of(fragment) + 0.7)
    joined = ("are", fragment + rest, ("ugly",))
    stretch = caption("ugly", rest, finished_as=joined)
    late_at, late = stretch[-2]  # its last live update, after the join instead
    events = [*caption("are", fragment), *stretch[:-2], stretch[-1]]
    events.append((stretch[-1][0] + 0.1, late))
    assert late_at < stretch[-1][0]
    found = play(events, STEADY, cards=cards)
    assert found.stuck_grey <= BOUND, found.worst
