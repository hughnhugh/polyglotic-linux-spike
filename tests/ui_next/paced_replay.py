"""The paced modes' replay (polyglotic-hq 1070): timed caption updates
through the playout - and Steady's cards - into a caption history, as a
caption window's view holds them, at 60 frames a second of made-up time.

The line replay (`line_replay`) gives a window the server's updates as
they come, so it never sees the playout or the cards: the stuck grey of
1070 lived between them and the history. This one has no Qt - the
playout, the deck and the history are plain Python - so it runs anywhere,
fast.

`Metrics.stuck_grey` is the longest any word was drawn unestablished
(Steady's grey ink) once it should not have been: after the playout gave
it as established; after its caption settled - its finished caption came
(a join's, for the captions it took in) or the next caption of its source
was first answered; or after a later word of its caption was drawn
established. The playout shows a settled caption's words by its delay
after, so this stays within the delay and a frame.
"""

import math
from collections.abc import Callable, Iterable, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from polyglotic_desktop.core.listening.captions import CaptionKind, CaptionUpdate
from polyglotic_desktop.core.listening.established import per_clause
from polyglotic_desktop.core.listening.history import Caption, CaptionHistory
from polyglotic_desktop.core.listening.playout import (
    Playout,
    PlayoutRules,
    each_character,
)
from polyglotic_desktop.core.listening.timing import CaptionId
from polyglotic_desktop.ui_next.views.cards import FIT, Card, Deck
from polyglotic_desktop.ui_next.views.wave import Waves

FRAME = 1 / 60
TAIL = 6.0
"""Seconds played after the last update: its words, at their moments
plus the delay, and the history's settling all done."""
CARD_PX = 600.0
"""The cards' width; every character 10 px wide."""
DAY = datetime(2026, 11, 29, tzinfo=UTC)

Heard = tuple[float, CaptionUpdate]
"""An update and when it came, in seconds on the updates' speech clock."""


@dataclass
class Metrics:
    stuck_grey: float = 0.0
    worst: tuple[float, CaptionId] | None = None
    """When the longest stuck grey was seen, and whose words they were."""
    frames: int = 0


def wide(text: str, translation: bool) -> float:
    return 10.0 * len(text)


class _Settling:
    """When each caption's words should all be established, from the whole
    stream: its finished update (or a join naming it), or the first answer
    to the next caption said after it, not one it later takes in."""

    def __init__(self, events: Sequence[Heard]) -> None:
        first: dict[CaptionId, float] = {}
        start: dict[CaptionId, float] = {}
        self.finishes: dict[CaptionId, list[float]] = {}
        taken: dict[CaptionId, CaptionId] = {}
        for at, update in events:
            caption = update.caption_id
            first.setdefault(caption, at)
            if update.times is not None:
                start[caption] = min(
                    start.get(caption, math.inf), update.times.speech_start
                )
            if update.kind is CaptionKind.FINISHED:
                for each in {caption, *update.replaces}:
                    self.finishes.setdefault(each, []).append(at)
                for other in update.replaces:
                    if other != caption:
                        taken[other] = caption
        self.next: dict[CaptionId, float] = {
            caption: min(
                (
                    first[other]
                    for other in first
                    if start.get(other, first[other]) > start.get(caption, at)
                    and taken.get(other) != caption
                ),
                default=math.inf,
            )
            for caption, at in first.items()
        }

    def due(self, caption: CaptionId, now: float) -> float:
        finished = [at for at in self.finishes.get(caption, []) if at <= now]
        return min(self.next.get(caption, math.inf), max(finished, default=math.inf))


def play(
    events: Iterable[Heard],
    rules: PlayoutRules,
    *,
    cards: bool = True,
    observe: Callable[[float, CaptionHistory, Deck | None], None] | None = None,
) -> Metrics:
    """`events` played through `rules` into a history, and how long words
    stayed grey that should not have (`Metrics`)."""
    stream = sorted(events, key=lambda heard: heard[0])
    settling = _Settling(stream)
    playout = Playout(rules)
    deck = Deck(CARD_PX / FIT, wide, each_character, likely=1.0) if cards else None
    now = 0.0
    history = CaptionHistory(clock=lambda: DAY + timedelta(seconds=now))
    hole_since: dict[CaptionId, float] = {}
    promised: dict[CaptionId, list[tuple[float, int]]] = {}
    result = Metrics()
    waiting = list(stream)
    end = (stream[-1][0] if stream else 0.0) + TAIL
    frame = 0
    while now <= end:
        now = frame * FRAME
        given: list[CaptionUpdate] = []
        while waiting and waiting[0][0] <= now + 1e-9:
            at, update = waiting.pop(0)
            if deck is not None:
                deck.hear(update, at)
            given += playout.heard(update, at)
        while (due := playout.due()) is not None and due <= now + 1e-9:
            given += playout.release(due)  # as the window's timer: at its time
            if playout.due() == due:
                break
        for update in given:
            _promise(promised, update, now)
            for shown in deck.show(update, now) if deck is not None else (update,):
                history.apply(shown)
        _look(history, deck, settling, hole_since, promised, now, result)
        if observe is not None:
            observe(now, history, deck)
        frame += 1
    result.frames = frame
    return result


def _look(
    history: CaptionHistory,
    deck: Deck | None,
    settling: _Settling,
    hole_since: dict[CaptionId, float],
    promised: dict[CaptionId, list[tuple[float, int]]],
    now: float,
    result: Metrics,
) -> None:
    cards = {deck.card_id(card): card for card in deck.cards} if deck else {}
    # each caption's words as drawn, line after line: (grey, lit) characters
    drawn: dict[CaptionId, list[tuple[int, int]]] = {}
    lit_words: dict[CaptionId, int] = {}
    for line in history.captions:
        owners = _owners(line, cards.get(line.caption_id))
        finals = (
            per_clause(line.clauses, line.established)
            if line.live
            else tuple(len(c.original) for c in line.clauses)
        )
        for clause, final, owner in zip(line.clauses, finals, owners, strict=False):
            drawn.setdefault(owner, []).append((len(clause.original) - final, final))
            lit_words[owner] = lit_words.get(owner, 0) + len(
                clause.original[:final].split()
            )
    for owner, parts in drawn.items():
        grey = [n for n, (unlit, _) in enumerate(parts) if unlit]
        if not grey:
            hole_since.pop(owner, None)
            continue
        if any(lit for _, lit in parts[grey[0] + 1 :]):
            hole_since.setdefault(owner, now)  # grey before a word drawn established
        else:
            hole_since.pop(owner, None)
        given = next(
            (at for at, count in promised.get(owner, ()) if count > lit_words[owner]),
            math.inf,
        )  # the first words the playout gave as established, not drawn so
        since = min(settling.due(owner, now), hole_since.get(owner, math.inf), given)
        if now - since > result.stuck_grey:
            result.stuck_grey, result.worst = now - since, (now, owner)


def _promise(
    promised: dict[CaptionId, list[tuple[float, int]]],
    update: CaptionUpdate,
    now: float,
) -> None:
    """When the playout first gave each count of `update`'s caption's words
    as established: what is drawn final from then on."""
    if update.kind is CaptionKind.WITHDRAWN:
        return
    said = " ".join(clause.original for clause in update.clauses)
    if update.kind is CaptionKind.LIVE:
        said = "".join(clause.original for clause in update.clauses)
        said = said[: update.established]
    count = len(said.split())
    times = promised.setdefault(update.caption_id, [])
    if not times or count > times[-1][1]:
        times.append((now, count))


def _owners(line: Caption, card: Card | None) -> list[CaptionId]:
    """Whose words each clause of `line` is: a card's clause a caption on
    it, in order; any other line, its own caption's."""
    if card is None:
        return [line.caption_id] * len(line.clauses)
    return list(dict.fromkeys(owner for owner, _ in card.words))


# -- Steady's wave (1070 part 3) -------------------------------------------------------


@dataclass(frozen=True)
class Letter:
    """A spoken letter: its caption, where it is in the caption's text (the
    clauses' originals end to end), when it was said, when its word began
    to be said and when its word was shown."""

    caption: CaptionId
    at: int
    said: float
    word_said: float
    shown: float


def letters_lit(
    events: Iterable[Heard], rules: PlayoutRules, *, lighting: bool = True
) -> list[tuple[Letter, float]]:
    """Each letter the stream's finished captions time (their word times),
    with when the wave began to light it: the playout's updates, as a
    window draws them (`views.wave`), a caption's text one row. Without
    `lighting`, words light whole, as before the wave."""
    stream = sorted(events, key=lambda heard: heard[0])
    playout = Playout(rules)
    waves = Waves()
    shown_at: dict[tuple[CaptionId, int], float] = {}
    finished: dict[CaptionId, CaptionUpdate] = {}

    def draw(updates: Iterable[CaptionUpdate], now: float) -> None:
        for update in updates:
            if update.kind is CaptionKind.WITHDRAWN:
                continue
            text = "".join(clause.original for clause in update.clauses)
            live = update.kind is CaptionKind.LIVE
            count = update.established if live else len(text)
            key = (hash(update.caption_id), CaptionKind.LIVE, 0)
            before = len(waves.rows[key].starts) if key in waves.rows else 0
            over = update.lighting if lighting else 0.0
            waves.to(key, count, now, over, text)
            for n in range(before, count):
                shown_at.setdefault((update.caption_id, n), now)

    for at, update in stream:
        while (due := playout.due()) is not None and due <= at:
            draw(playout.release(due), due)
            if playout.due() == due:
                break
        if update.kind is CaptionKind.FINISHED:
            finished[update.caption_id] = update
        draw(playout.heard(update, at), at)
    while (due := playout.due()) is not None:
        draw(playout.release(due), due)
        if playout.due() == due:
            break
    out: list[tuple[Letter, float]] = []
    for caption, update in finished.items():
        starts = waves.rows[(hash(caption), CaptionKind.LIVE, 0)].starts
        offset = 0
        for clause in update.clauses:
            for time in clause.words:
                first, end = time.original
                letters = [n for n in range(first, end) if clause.original[n].isalnum()]
                for j, n in enumerate(letters):
                    said = time.start + (time.end - time.start) * j / len(letters)
                    at = offset + n
                    shown = shown_at[caption, offset + letters[0]]
                    letter = Letter(caption, at, said, time.start, shown)
                    out.append((letter, starts[at]))
            offset += len(clause.original)
    return out
