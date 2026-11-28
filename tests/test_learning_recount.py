"""Two caption sources interleaved - the PC's audio and the learner's own
mic - through the real counting into a real learning file: whatever order
captions finish, finish again (a join), replace others and are withdrawn
in, the stored counts equal a plain recount of the captions left standing
(933's learning-1; the learning review's R2: words counted twice or not
at all).

Within one hour at 13:30 UTC, when the learner's day (Melbourne's,
fixed) is already the next: `first_heard` and the daily rows follow the
UTC day, `last_heard` the learner's. Coverage isn't recounted here."""

import random
import sqlite3
from collections import Counter
from datetime import UTC, date, datetime, timedelta
from pathlib import Path

import pytest
from tools.rebuild_fixtures.learning import learners_day

from polyglotic_desktop.adapters.sqlite_learning import SqliteLearningStore
from polyglotic_desktop.core.learning.exposures import RECENT_CAPTIONS
from polyglotic_desktop.core.learning.vocabulary import Vocabulary
from polyglotic_desktop.core.shared import EntryFacts, EntryId, WordInLine

START = datetime(2026, 11, 24, 13, 30, tzinfo=UTC)
UTC_DAY, LEARNERS_DAY = date(2026, 11, 24), date(2026, 11, 25)
ENTRIES = [
    EntryFacts(EntryId(f"fixture:recount:{n}"), None, n + 1, is_name=n == 5)
    for n in range(6)
]
"""Six made-up entries; the last a name, which is never counted."""
BY_YOU = {"video": False, "mic": True}
STEPS = 60
SEEDS = range(20)


def _line(rng: random.Random) -> list[WordInLine]:
    """A line's words: some entries, one perhaps twice (counted once)."""
    chosen = rng.choices(ENTRIES, k=rng.randint(0, 4))
    return [WordInLine(i * 3, i * 3 + 2, facts) for i, facts in enumerate(chosen)]


def _replay(vocabulary: Vocabulary, rng: random.Random, now: list[datetime]) -> dict:
    """Random interleaved events, as `ui/captions.py`'s `_count` turns a
    caption update into them; returns the captions left standing."""
    standing: dict[str, tuple[bool, frozenset[EntryId]]] = {}
    made: dict[str, list[str]] = {source: [] for source in BY_YOU}
    for _ in range(STEPS):
        now[0] += timedelta(seconds=rng.randint(1, 30))
        source = rng.choice(sorted(BY_YOU))
        earlier = made[source]
        what = rng.choice(["new", "new", "join", "replaces", "withdraw"])
        if what in {"join", "withdraw"} and not earlier:
            what = "new"
        if what == "withdraw":
            caption_id = rng.choice(earlier)
            vocabulary.caption_withdrawn(caption_id)
            standing.pop(caption_id, None)
            continue
        if what == "join":
            caption_id = rng.choice(earlier)
        else:
            caption_id = f"{source}-{len(earlier) + 1}"
            earlier.append(caption_id)
        if what == "replaces":
            for replaced in rng.sample(earlier[:-1], k=min(2, len(earlier) - 1)):
                vocabulary.caption_withdrawn(replaced)
                standing.pop(replaced, None)
        words = _line(rng)
        vocabulary.caption_finished(caption_id, words, BY_YOU[source], source)
        entries = frozenset(w.entry.entry_id for w in words if not w.entry.is_name)
        standing[caption_id] = (BY_YOU[source], entries)
    assert sum(len(ids) for ids in made.values()) < RECENT_CAPTIONS
    return standing


def _recount(standing: dict) -> dict[str, tuple]:
    """The counts, plainly: each entry, per caption left standing."""
    heard: Counter[str] = Counter()
    yours: Counter[str] = Counter()
    for by_you, entries in standing.values():
        (yours if by_you else heard).update(entries)
    return {
        entry: (
            heard[entry],
            yours[entry],
            0,  # no word is in the deck
            UTC_DAY if heard[entry] else None,
            1 if heard[entry] else 0,
            LEARNERS_DAY if heard[entry] else None,
        )
        for entry in heard.keys() | yours.keys()
        if heard[entry] or yours[entry]
    }


@pytest.mark.parametrize("seed", SEEDS)
def test_the_stored_counts_equal_a_plain_recount(seed: int, tmp_path: Path) -> None:
    path = tmp_path / "learning.sqlite"
    facts = {f.entry_id: f for f in ENTRIES}
    now = [START]
    store = SqliteLearningStore(path)
    vocabulary = Vocabulary(
        store,
        lambda entry_id, scheme: facts.get(entry_id),
        "fixture",
        lambda: now[0],
        day_of=learners_day,
    )
    standing = _replay(vocabulary, random.Random(seed), now)
    store.close()
    assert now[0].date() == UTC_DAY and learners_day(now[0]) == LEARNERS_DAY
    expected = _recount(standing)

    store = SqliteLearningStore(path)  # what the file holds, read again
    stored = {
        e.entry_id: (
            e.heard,
            e.heard_by_you,
            e.heard_in_deck,
            e.first_heard,
            e.days_heard,
            e.last_heard,
        )
        for e in store.load().exposures
        if e.heard or e.heard_by_you
    }
    daily = dict(store.daily_exposures(UTC_DAY))
    store.close()
    assert stored == expected
    assert daily == {e: counts[0] for e, counts in expected.items() if counts[0]}
    db = sqlite3.connect(path)
    days = {day for (day,) in db.execute("SELECT DISTINCT day FROM daily_exposures")}
    db.close()
    assert days <= {UTC_DAY.isoformat()}
