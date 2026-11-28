"""The playout (`core.listening.playout`): a caption's words shown one by
one, each a constant delay after it was said (polyglotic-hq 526)."""

from dataclasses import replace

import pytest

from polyglotic_desktop.core.listening.captions import (
    CaptionKind,
    CaptionUpdate,
    Clause,
    Language,
    SpeechTimes,
    WordLink,
    WordTime,
)
from polyglotic_desktop.core.listening.playout import (
    ESTIMATE_LATE_SEC,
    MIN_GAP_SEC,
    STALE_SEC,
    Ahead,
    Playout,
    PlayoutRules,
    carried,
    word_beats,
)
from polyglotic_desktop.core.listening.sources import SourceId
from polyglotic_desktop.core.listening.timing import CaptionId, WithdrawalReason

APP = SourceId("app")
MIC = SourceId("mic")
EN = Language("en")
ONE = CaptionId("one")
TWO = CaptionId("two")
D = 2.0
RULES = PlayoutRules(delay=D)


def update(
    text: str | tuple[str | Clause, ...],
    start: float,
    end: float,
    kind: CaptionKind = CaptionKind.LIVE,
    caption: CaptionId = ONE,
    source: SourceId = APP,
    established: int = 0,
    replaces: tuple[CaptionId, ...] = (),
) -> CaptionUpdate:
    texts = (text,) if isinstance(text, str) else text
    clauses = tuple(c if isinstance(c, Clause) else Clause(c) for c in texts)
    return CaptionUpdate(
        caption, source, kind, clauses, EN, (EN,), replaces,
        times=SpeechTimes(start, end, end, end + 0.1), established=established,
    )  # fmt: skip


def finished(
    text: str | tuple[str | Clause, ...], start: float, end: float, **more: object
) -> CaptionUpdate:
    return update(text, start, end, CaptionKind.FINISHED, **more)  # type: ignore[arg-type]


def said(shown: CaptionUpdate) -> str:
    return "".join(c.original for c in shown.clauses)


def bare(shown: CaptionUpdate) -> CaptionUpdate:
    """`shown` without how long its new words light (`lighting`): what the
    server sent, for an update the playout gives as it came."""
    return replace(shown, lighting=0.0)


def played(playout: Playout, until: float) -> list[tuple[float, CaptionUpdate]]:
    """Every update the playout gives up to `until`, each with its time."""
    out = []
    while (when := playout.due()) is not None and when <= until:
        out += [(when, shown) for shown in playout.release(when)]
    return out


def test_nothing_is_shown_before_its_moment() -> None:
    playout = Playout(RULES)
    assert playout.heard(update("one two three", 10.0, 11.0), 11.1) == ()
    due = playout.due()
    assert due is not None and due > 11.1


def test_words_come_one_by_one_in_the_speakers_rhythm_a_delay_behind() -> None:
    playout = Playout(RULES)
    playout.heard(finished("cat dog bird fish", 10.0, 12.0), 12.1)
    shown = played(playout, 20.0)
    assert [said(u) for _, u in shown] == [
        "cat",
        "cat dog",
        "cat dog bird",
        "cat dog bird fish",
    ]
    # four words of one syllable over 2 s: half a second apart, the delay after
    # their moments (less what the estimate is known to run late)
    times = [at for at, _ in shown]
    assert times == pytest.approx(
        [10.5 + D - ESTIMATE_LATE_SEC + 0.5 * i for i in range(4)]
    )


def test_what_is_shown_is_established_so_it_is_drawn_as_final() -> None:
    playout = Playout(RULES)
    playout.heard(finished("one two three", 10.0, 11.5), 11.6)
    first, second, _last = (u for _, u in played(playout, 20.0))
    assert (first.kind, first.established) == (CaptionKind.LIVE, len("one"))
    assert (second.kind, second.established) == (CaptionKind.LIVE, len("one two"))


def test_a_finished_captions_last_word_brings_the_servers_own_update() -> None:
    playout = Playout(RULES)
    whole = finished("one two", 10.0, 11.0)
    playout.heard(whole, 11.1)
    assert bare(played(playout, 20.0)[-1][1]) == whole


def test_a_live_updates_newest_word_waits_for_the_next_update() -> None:
    playout = Playout(RULES)
    playout.heard(update("one two three", 10.0, 11.5), 11.6)
    assert [said(u) for _, u in played(playout, 30.0)] == ["one", "one two"]
    assert playout.due() is None  # "three" may yet be reheard
    playout.heard(update("one two three four", 10.0, 12.0), 30.0)
    assert [said(u) for _, u in played(playout, 40.0)] == ["one two three"]


def test_the_newest_word_is_not_held_once_the_server_calls_it_established() -> None:
    playout = Playout(RULES)
    playout.heard(
        update("one two three", 10.0, 11.5, established=len("one two three")), 11.6
    )
    assert said(played(playout, 30.0)[-1][1]) == "one two three"


def test_calm_shows_only_what_the_server_calls_established() -> None:
    playout = Playout(PlayoutRules(delay=D, established_only=True))
    playout.heard(update("one two three", 10.0, 11.5, established=len("one")), 11.6)
    assert [said(u) for _, u in played(playout, 30.0)] == ["one"]
    playout.heard(finished("one two three", 10.0, 11.5), 30.0)
    assert said(played(playout, 40.0)[-1][1]) == "one two three"


def test_the_newest_word_is_shown_too_when_asked() -> None:
    playout = Playout(PlayoutRules(delay=D, hold_back=0))
    playout.heard(update("one two three", 10.0, 11.5), 11.6)
    assert said(played(playout, 30.0)[-1][1]) == "one two three"


def test_a_word_that_comes_after_its_moment_is_shown_at_once_never_in_a_clump() -> None:
    playout = Playout(PlayoutRules(delay=0.5))
    now = playout.heard(finished("one two three", 10.0, 11.0), 15.0)  # all long due
    assert [said(u) for u in now] == []
    shown = played(playout, 20.0)
    assert [said(u) for _, u in shown] == ["one", "one two", "one two three"]
    assert [round(at, 2) for at, _ in shown] == [
        15.0,
        15.25,
        15.5,
    ]


def test_a_late_timer_releases_one_word_then_catches_up() -> None:
    playout = Playout(RULES)
    playout.heard(finished("cat dog bird fish", 10.0, 12.0), 12.1)
    assert [said(u) for u in playout.release(15.0)] == ["cat"]
    assert playout.release(15.0) == ()
    # past the delay after the caption was finished: the rest one after
    # another at once, not at the speaker's pace ever further behind (1070)
    rest = [at for at, _ in played(playout, 20.0)]
    assert rest == pytest.approx([15.0 + MIN_GAP_SEC * n for n in (1, 2, 3)])


def test_a_late_answer_keeps_the_speech_rhythm_while_it_can() -> None:
    playout = Playout(RULES)
    playout.heard(finished("cat dog bird fish", 10.0, 12.0), 12.1)
    assert [said(u) for u in playout.release(12.9)] == ["cat"]
    shown = [at for at, _ in played(playout, 20.0)]
    # the speaker's half seconds, drawn in so the last is out by the delay
    # after the caption was finished
    assert shown == pytest.approx([13.3, 13.7, 12.1 + D])


def test_translation_added_to_an_already_shown_clause_is_delivered_at_once() -> None:
    playout = Playout(RULES)
    playout.heard(update(("one two", " three four"), 10.0, 11.0), 11.1)
    played(playout, 15.0)
    clause = Clause("one two", {EN: "un deux"})
    translated = update((clause, " three four"), 10.0, 11.0)
    assert [u.clauses[0] for u in playout.heard(translated, 16.0)] == [clause]


def test_a_word_keeps_its_moment_when_later_updates_bring_more() -> None:
    playout = Playout(RULES)
    playout.heard(update("cat dog", 10.0, 11.0), 11.1)
    playout.heard(update("cat dog bird fish", 10.0, 12.0), 12.1)
    shown = played(playout, 30.0)
    assert said(shown[0][1]) == "cat" and shown[0][0] == pytest.approx(
        10.5 + D - ESTIMATE_LATE_SEC
    )
    # "three" (the held-back"four" spreads with it) was said after the first
    # update's speech ended, at 11.0
    assert (
        said(shown[2][1]) == "cat dog bird"
        and shown[2][0] > 11.0 + D - ESTIMATE_LATE_SEC
    )


def test_a_shown_word_stays_shown_and_a_rehearing_changes_it_in_place() -> None:
    playout = Playout(RULES)
    playout.heard(update("I scream for", 10.0, 11.0), 11.1)
    played(playout, 14.0)  # "I scream" is on screen
    now = playout.heard(update("ice cream for you", 10.0, 12.0), 14.0)
    assert [said(u) for u in now] == ["ice cream"]  # as many words as were shown
    assert now[0].established == len("ice cream")


def test_carried_keeps_shown_words_wherever_they_moved_to() -> None:
    assert carried(["a", "b", "c"], ["a", "b", "c", "d"], 2) == 2
    assert carried(["a", "b"], ["x", "a", "b", "c"], 2) == 3
    assert carried(["a", "b"], ["x", "y"], 2) == 2
    assert carried(["a", "b"], ["x"], 2) == 1
    assert carried(["a"], ["a"], 0) == 0


def test_a_clauses_translation_and_links_come_with_its_last_word() -> None:
    link = WordLink((0, 3), (0, 2), True, 0.9)
    first = Clause("One two, ", {EN: "Un deux,"}, {EN: (link,)})
    second = Clause("three four.", {EN: "trois quatre."})
    playout = Playout(RULES)
    whole = finished((first, second), 10.0, 12.0)
    playout.heard(whole, 12.1)
    shown = [u for _, u in played(playout, 30.0)]
    assert [tuple(bool(c.translations) for c in u.clauses) for u in shown] == [
        (False,),  # One
        (True,),  # One two, - the clause is whole: a word of the next one follows
        (True, False),  # three
        (True, True),  # the finished caption itself
    ]
    assert shown[1].clauses[0] is first
    assert bare(shown[-1]) == whole


def test_translation_with_a_fully_confirmed_live_clause_arrives_on_its_last_word() -> (
    None
):
    playout = Playout(RULES)
    clause = Clause("one two", {EN: "un deux"})
    playout.heard(update((clause,), 10.0, 11.0, established=len(clause.original)), 11.1)
    first, second = (u for _, u in played(playout, 15.0))
    assert not first.clauses[0].translations
    assert second.clauses == (clause,)


def test_a_live_captions_unconfirmed_last_clause_waits() -> None:
    clause = Clause("one two", {EN: "un deux"})
    playout = Playout(PlayoutRules(delay=D, hold_back=0))
    playout.heard(update((clause,), 10.0, 11.0), 11.1)
    assert [bool(u.clauses[0].translations) for _, u in played(playout, 30.0)] == [
        False,
        False,
    ]


def test_the_servers_word_times_are_used_when_it_sends_them() -> None:
    clause = Clause(
        "one two three",
        words=(
            WordTime((0, 3), 10.0, 10.2),
            WordTime((4, 7), 10.9, 11.0),
            WordTime((8, 13), 11.0, 11.4),
        ),
    )
    playout = Playout(RULES)
    playout.heard(finished((clause,), 10.0, 11.5), 11.6)
    assert [at for at, _ in played(playout, 30.0)] == [10.0 + D, 10.9 + D, 11.0 + D]


def test_a_word_the_server_gave_no_time_takes_the_one_before() -> None:
    clause = Clause(
        "one two three",
        words=(WordTime((0, 3), 10.0, 10.2), WordTime((8, 13), 11.0, 11.4)),
    )
    playout = Playout(RULES)
    playout.heard(finished((clause,), 10.0, 11.5), 11.6)
    assert [at for at, _ in played(playout, 30.0)] == [
        10.0 + D,
        10.0 + D + MIN_GAP_SEC,
        11.0 + D,
    ]


def test_karaoke_gives_the_waiting_words_past_the_established_count() -> None:
    playout = Playout(PlayoutRules(delay=D, ahead=Ahead.WAITING))
    now = playout.heard(update("one two three", 10.0, 11.5), 11.6)
    assert [(said(u), u.established) for u in now] == [
        ("one two", 0)
    ]  # the newest held back
    shown = [u for _, u in played(playout, 30.0)]
    assert [(said(u), u.established) for u in shown] == [
        ("one two", 4),
        ("one two", 7),
    ]


def test_karaoke_pairs_a_finished_translation_with_the_complete_visible_clause() -> (
    None
):
    playout = Playout(PlayoutRules(delay=D, ahead=Ahead.WAITING))
    clause = Clause("one two", {EN: "un deux"})
    (first,) = playout.heard(finished((clause,), 10.0, 11.0), 11.1)
    assert first.established == 0
    assert first.clauses == (clause,)


def test_karaoke_pairs_a_confirmed_live_translation_with_the_waiting_words() -> None:
    playout = Playout(PlayoutRules(delay=D, ahead=Ahead.WAITING))
    clause = Clause("one two", {EN: "un deux"})
    packet = update((clause,), 10.0, 11.0, established=len(clause.original))
    (waiting,) = playout.heard(packet, 11.1)
    assert waiting.established == 0
    assert waiting.clauses == (clause,)


def test_eager_karaoke_gives_the_newest_word_too() -> None:
    playout = Playout(PlayoutRules(delay=D, ahead=Ahead.ALL))
    now = playout.heard(update("one two three", 10.0, 11.5), 11.6)
    assert [(said(u), u.established) for u in now] == [("one two three", 0)]
    assert said(played(playout, 30.0)[-1][1]) == "one two three"
    assert (
        played(playout, 30.0) == [] and playout.due() is None
    )  # lit only when confirmed


def test_a_sources_captions_are_shown_one_after_another() -> None:
    playout = Playout(RULES)
    playout.heard(update("one two three", 10.0, 11.0), 11.1)
    playout.heard(finished("four five", 11.5, 12.0, caption=TWO), 12.1)
    assert [said(u) for _, u in played(playout, 14.0)] == [
        "one",
        "one two",
    ]  # two waits for one
    playout.heard(finished("one two three", 10.0, 11.0), 14.0)
    assert [(u.caption_id, said(u)) for _, u in played(playout, 20.0)] == [
        (ONE,"one two three"), (TWO,"four"), (TWO,"four five"),
    ]  # fmt: skip


def test_words_ahead_of_a_later_caption_wait_for_the_current_one() -> None:
    playout = Playout(PlayoutRules(delay=D, ahead=Ahead.WAITING))
    first = finished("one two three", 10, 12)
    later = finished("four five", 12, 13, caption=TWO)
    playout.heard(first, 12)
    early = playout.heard(later, 12.1)
    assert all(u.caption_id != TWO for u in early)
    shown = [bare(u) for _, u in played(playout, 20)]
    assert shown.index(first) < next(
        i for i, u in enumerate(shown) if u.caption_id == TWO
    )
    assert shown[-1] == later


def test_each_source_has_its_own_pace() -> None:
    playout = Playout(RULES)
    playout.heard(update("one two three", 10.0, 11.0), 11.1)
    playout.heard(finished("four", 10.0, 10.5, caption=TWO, source=MIC), 11.1)
    assert (TWO, "four") in [(u.caption_id, said(u)) for _, u in played(playout, 30.0)]


def test_a_caption_never_finished_stops_holding_the_next_back() -> None:
    playout = Playout(RULES)
    playout.heard(update("one two three", 10.0, 11.0), 11.1)
    playout.heard(finished("four", 11.5, 12.0, caption=TWO), 12.1)
    played(playout, 15.0)
    # The window arms its timer from due(). Silence sends no more packets
    # to release the second caption if the first one never finishes.
    assert playout.due() == pytest.approx(11.1 + STALE_SEC)
    assert [said(u) for _, u in played(playout, 11.1 + STALE_SEC)] == ["four"]
    assert playout.due() is None


def test_a_joined_caption_keeps_what_its_captions_showed() -> None:
    playout = Playout(RULES)
    playout.heard(finished("one two", 10.0, 11.0), 11.1)
    played(playout, 20.0)
    joined = finished("one two three four", 10.0, 13.0, caption=TWO, replaces=(ONE,))
    now = playout.heard(joined, 20.0)
    assert [(said(u), u.replaces) for u in now] == [("one two", (ONE,))]
    later = [u for _, u in played(playout, 30.0)]
    assert said(later[-1]) == "one two three four"
    # named once more at the finish: a caption history retires replaced
    # captions only then; the drafts between name none
    assert [u.replaces for u in later] == [(), (ONE,)]


def test_a_join_under_the_earlier_captions_id_retires_the_live_caption() -> None:
    # the timing finishes a fragment's next stretch as the fragment's own
    # caption (already shown), replacing that stretch's live caption
    playout = Playout(RULES)
    playout.heard(finished("one two", 10.0, 11.0), 11.1)
    played(playout, 14.0)
    playout.heard(update("three four five", 11.5, 13.5, caption=TWO), 13.6)
    shown = played(playout, 16.0)
    assert shown and all(u.caption_id == TWO for _, u in shown)
    joined = finished("one two three four five six", 10.0, 14.0, replaces=(TWO,))
    given = [*playout.heard(joined, 16.0), *(u for _, u in played(playout, 30.0))]
    assert [u.replaces for u in given if u.replaces] == [(TWO,), (TWO,)]
    assert given[0].replaces == (TWO,)  # the first draft: the deck's
    assert given[-1].kind is CaptionKind.FINISHED and given[-1].replaces == (TWO,)
    # and an update for the replaced caption that comes after is too late
    assert playout.heard(update("three four five", 11.5, 14.0, caption=TWO), 31.0) == ()
    assert playout.due() is None


def test_an_update_for_a_withdrawn_caption_is_too_late() -> None:
    playout = Playout(RULES)
    playout.heard(update("one two three", 10.0, 11.0), 11.1)
    played(playout, 20.0)
    gone = CaptionUpdate(
        ONE, APP, CaptionKind.WITHDRAWN, reason=WithdrawalReason.FILLER_WORDS
    )
    assert playout.heard(gone, 20.0) == (gone,)
    assert playout.heard(finished("one two three", 10.0, 11.5), 20.5) == ()
    assert playout.due() is None


def test_a_caption_finished_late_is_shown_by_the_delay_after() -> None:
    # Calm releases only established words while a caption is live: the
    # rest wait for the finish, said long before it came
    playout = Playout(PlayoutRules(delay=D, established_only=True))
    words = "one two three four five six seven eight"
    playout.heard(update(words, 10.0, 14.0), 14.1)
    assert played(playout, 17.0) == []
    playout.heard(finished(words, 10.0, 14.0), 17.0)
    shown = played(playout, 30.0)
    assert len(shown) == 8
    assert shown[-1][0] <= 17.0 + D + 1e-9  # at the speaker's pace: 20.5


def test_the_next_caption_settles_the_one_before() -> None:
    # a live caption's words, behind (its answer came late), are all out by
    # the delay after the next caption is first answered: its words are
    # all heard by then, though its finish has yet to come
    playout = Playout(RULES)
    words = "one two three four five six seven eight"
    playout.heard(update(words, 10.0, 14.0), 18.0)
    first = playout.heard(update("nine ten", 14.0, 15.0, caption=TWO), 18.5)
    shown = [(18.5, u) for u in first] + played(playout, 30.0)
    times = [at for at, u in shown if u.caption_id == ONE]
    assert len(times) == 7  # all but the newest, held for its finish
    assert times[-1] <= 18.5 + D + 1e-9  # at the speaker's pace: 21.5


def test_a_withdrawn_caption_is_taken_back_only_if_it_was_shown() -> None:
    def withdrawn(caption: CaptionId) -> CaptionUpdate:
        return CaptionUpdate(
            caption, APP, CaptionKind.WITHDRAWN, reason=WithdrawalReason.FILLER_WORDS
        )

    playout = Playout(RULES)
    playout.heard(update("one two", 10.0, 11.0), 11.1)
    assert playout.heard(withdrawn(ONE), 11.2) == ()
    assert playout.due() is None
    playout.heard(finished("three four", 12.0, 13.0, caption=TWO), 13.1)
    played(playout, 16.0)
    gone = withdrawn(TWO)
    assert playout.heard(gone, 16.1) == (gone,)


def test_clearing_gives_each_unfinished_caption_as_the_server_sent_it() -> None:
    playout = Playout(RULES)
    latest = update("one two three", 10.0, 11.0)
    playout.heard(latest, 11.1)
    assert playout.clear() == (latest,)
    assert playout.due() is None


def test_speech_this_app_did_not_time_is_paced_from_when_it_came() -> None:
    playout = Playout(RULES)
    bare = CaptionUpdate(
        ONE, APP, CaptionKind.FINISHED, (Clause("one two"),), EN, (EN,)
    )
    playout.heard(bare, 50.0)
    shown = played(playout, 60.0)
    assert [said(u) for _, u in shown] == ["one", "one two"]
    assert shown[0][0] == 50.0 + D - ESTIMATE_LATE_SEC


def test_chinese_is_split_by_the_dictionary_given_and_mixed_text_keeps_every_character() -> (
    None
):
    def pairs(run: str) -> list[tuple[int, int]]:
        return [(i, min(i + 2, len(run))) for i in range(0, len(run), 2)]

    text = "“OK，所以我come from福建。"
    playout = Playout(PlayoutRules(delay=0.0), split=pairs)
    playout.heard(finished(text, 10.0, 12.0), 12.1)
    shown = [said(u) for _, u in played(playout, 30.0)]
    assert shown == [
        "“OK，",
        "“OK，所以",
        "“OK，所以我",
        "“OK，所以我come",
        "“OK，所以我come from",
        text,
    ]


def test_without_a_dictionary_each_chinese_character_is_a_word() -> None:
    playout = Playout(PlayoutRules(delay=0.0))
    playout.heard(finished("你好吗", 10.0, 11.0), 11.1)
    assert [said(u) for _, u in played(playout, 30.0)] == ["你", "你好", "你好吗"]


def test_acquisition_holds_a_clauses_translation_back_after_its_last_word() -> None:
    """Decision 0253: what was said first; the translation and the links
    `translation_after` seconds after the clause is shown whole."""
    link = WordLink((0, 3), (0, 2), True, 0.9)
    first = Clause("One two, ", {EN: "Un deux,"}, {EN: (link,)})
    second = Clause("three four.", {EN: "trois quatre."})
    playout = Playout(PlayoutRules(delay=D, translation_after=1.5))
    whole = finished((first, second), 10.0, 12.0)
    playout.heard(whole, 12.1)
    shown = played(playout, 30.0)
    translated = [
        (round(at, 2), tuple(bool(c.translations) for c in u.clauses))
        for at, u in shown
    ]
    whole_at: dict[str, float] = {}  # when each text first showed
    for at, u in shown:
        whole_at.setdefault(said(u), at)
    first_whole = whole_at["One two,"]
    all_said = whole_at["One two, three four."]
    assert translated[0][1] == (False,)
    # the first clause's translation comes 1.5 s after "two," - not with it
    first_translated = next(at for at, flags in translated if flags[0])
    assert first_translated == pytest.approx(first_whole + 1.5)
    # every word is shown before the last translation, and the caption is
    # finished (not rewritten) while it waits
    last = shown[-1][1]
    assert bare(last) == whole  # the server's own update, in the end
    waiting = [u for at, u in shown if at >= all_said and u is not whole]
    assert waiting and all(u.kind is CaptionKind.FINISHED for u in waiting)
    assert all(said(u) == "One two, three four." for u in waiting)
    assert not waiting[0].clauses[1].translations and not waiting[0].clauses[1].links
    assert shown[-1][0] == pytest.approx(all_said + 1.5)
    assert playout.due() is None


def test_a_held_translation_is_not_lost_when_newer_captions_finish() -> None:
    playout = Playout(PlayoutRules(delay=0.0, hold_back=0, translation_after=5.0))
    seen: dict[str, bool] = {}
    for n in range(6):  # more than the playout keeps finished
        clause = Clause(f"cat dog {n}.", {EN: f"chat chien {n}."})
        whole = CaptionUpdate(
            CaptionId(f"c{n}"), APP, CaptionKind.FINISHED, (clause,), EN, (EN,),
            times=SpeechTimes(n, n + 0.5, n + 0.5, n + 0.6),
        )  # fmt: skip
        for u in playout.heard(whole, n + 0.6):
            seen[u.caption_id] = bool(u.clauses[0].translations)
    for _, u in played(playout, 60.0):
        seen[u.caption_id] = bool(u.clauses[0].translations)
    assert seen == {f"c{n}": True for n in range(6)}


def test_without_it_nothing_is_held() -> None:
    clause = Clause("one two.", {EN: "un deux."})
    playout = Playout(RULES)
    whole = finished((clause,), 10.0, 11.0)
    playout.heard(whole, 11.1)
    assert bare(played(playout, 30.0)[-1][1]) == whole
    assert playout.due() is None


def test_subtitle_word_beats_keep_spoken_pauses_and_attach_punctuation() -> None:
    clause = Clause(
        "A, slow finish.",
        words=(
            WordTime((0, 1), 10.0, 10.1),
            WordTime((3, 7), 10.3, 10.5),
            WordTime((8, 14), 11.8, 12.0),
        ),
    )
    ends, offsets = word_beats(clause.original, lambda run: [(0, len(run))], clause)
    assert ends == (3, 8, 15)
    assert offsets == pytest.approx((0.0, 0.3, 1.8))
    assert word_beats("你好，世界。", lambda run: [(0, len(run))]) == ((3, 6), ())


# -- the wave: how long a shown word lights (1070) --------------------------------------


def timed(words: str, start: float, step: float, said: float) -> Clause:
    """`words` as one clause, each word said for `said` s, one each `step` s."""
    times, at = [], 0
    for n, word in enumerate(words.split()):
        times.append(
            WordTime((at, at + len(word)), start + n * step, start + n * step + said)
        )
        at += len(word) + 1
    return Clause(words, words=tuple(times))


def test_a_shown_word_lights_as_long_as_it_took_to_say() -> None:
    playout = Playout(RULES)
    playout.heard(finished((timed("one two three", 10.0, 0.5, 0.3),), 10.0, 11.5), 11.6)
    lights = [u.lighting for _, u in played(playout, 20.0)]
    assert lights == pytest.approx([0.3, 0.3, 0.3])  # each word's own time


def test_without_word_times_a_word_lights_until_the_next_was_said() -> None:
    playout = Playout(RULES)
    playout.heard(finished("cat dog bird fish", 10.0, 12.0), 12.1)
    lights = [u.lighting for _, u in played(playout, 20.0)]
    assert lights[:3] == pytest.approx([0.5, 0.5, 0.5])  # the speaker's half seconds


def test_a_word_shown_late_lights_by_the_time_the_next_is_due() -> None:
    playout = Playout(RULES)
    playout.heard(finished("cat dog bird fish", 10.0, 12.0), 12.1)
    [shown] = playout.release(13.9)  # "cat", due at 12.2: late
    due = playout.due()
    assert due is not None
    assert shown.lighting == pytest.approx(due - 13.9)
    assert shown.lighting < 0.5


def test_a_word_never_lights_for_longer_than_the_delay() -> None:
    playout = Playout(RULES)
    slow = timed("one two", 10.0, 4.0, 3.5)  # a word drawn out over 3.5 s
    playout.heard(finished((slow,), 10.0, 17.5), 17.6)
    assert all(u.lighting <= D for _, u in played(playout, 30.0))


def test_the_finished_caption_its_last_word_brings_lights_that_word() -> None:
    playout = Playout(RULES)
    whole = finished((timed("one two", 10.0, 0.5, 0.25),), 10.0, 11.0)
    playout.heard(whole, 11.1)
    last = played(playout, 20.0)[-1][1]
    assert last.kind is CaptionKind.FINISHED and last.clauses == whole.clauses
    assert last.lighting == pytest.approx(0.25)
