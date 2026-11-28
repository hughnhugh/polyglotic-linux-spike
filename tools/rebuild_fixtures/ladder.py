"""The learning store's ladder: a store at each schema version, 1 to the
app's, and what today's app makes of each (933's learning-1, from the
learning review's R1: nothing protects against a migration that succeeds
and is wrong).

Each rung is made by running the app's first N migrations (`_MIGRATIONS`)
on an empty file and seeding every table that version has, with a row or
two in most tables that the app can't read (a value not of its column's
type, a time or a status it can't parse: polyglotic-hq 207), and kept as
SQL (`ladder/vNN.sql`). Then the rung is opened by today's store - every
migration it lacks runs - and what it reads and what the file then holds
are recorded (`ladder/vNN.json`): `reads` through the app's own readers,
`file` by SQL alone (`store_dump.dump`), and the level's copy beside it.
`started-again.json` is a store started again beside the copy of the
level (decision 0048): the level is taken from the copy.

A rung's SQL changes only when an old migration does; what its upgrade
gives changes when a migration, a reader or the level's copy does. Either
shows in review, and `record --check` fails until it's re-recorded.

All the data is made up: common words and invented lines (RULES #26, #30).
"""

from __future__ import annotations

import json
import shutil
import sqlite3
import tempfile
from pathlib import Path
from typing import Any

from polyglotic_desktop.adapters import sqlite_learning
from polyglotic_desktop.adapters.sqlite_learning import (
    VERSION,
    SqliteLearningStore,
    level_file,
)
from tools.rebuild_fixtures.plain import plain as _plain
from tools.rebuild_fixtures.store_dump import dump, materialise, script

FORGOTTEN = "fixture:zh:ni"
"""The entry in every table that has entries, for `forget_entry`'s test."""
KEPT_WHEN_FORGOTTEN = frozenset({"daily_exposures", "status_history"})
"""The tables `forget_entry` leaves an entry in, by design: the daily
counts (for sharing, decision 0041) and the status history (appended,
never changed: polyglotic-hq 474)."""

_AT = "2026-10-01T09:00:00+00:00"
_LATER = "2026-10-20T18:45:30.250000+00:00"

# Every table's rows, with every column up to today's version: a rung takes
# the columns its version has. The text is common words and invented lines.
SEEDS: dict[str, tuple[dict[str, object], ...]] = {
    "level": ({"id": 1, "scheme": "hsk-2025", "midpoint": 2.5},),
    "statuses": (
        {"entry_id": FORGOTTEN, "status": "known", "source": "learner", "at": _AT},
        {
            "entry_id": "fixture:zh:cha",
            "status": "learning",
            "source": "learner",
            "at": _LATER,
        },
        # a pinned lookup turned it back to new: version 8 keeps it as a lookup
        {
            "entry_id": "fixture:zh:shui",
            "status": "new",
            "source": "estimated",
            "at": "2026-10-03T07:15:00+00:00",
        },
        {
            "entry_id": "fixture:en:hello",
            "status": "ignored",
            "source": "imported",
            "at": "2026-10-04T12:00:00+00:00",
        },
    ),
    "categories": (
        {"id": "interesting", "name": "Interesting", "color": "#2f9e8f", "position": 0},
        {"id": "food", "name": "Food and drink", "color": "#c0563b", "position": 1},
    ),
    "saved_words": (
        {
            "entry_id": FORGOTTEN,
            "headword": "你",
            "traditional": "你",
            "reading": "nǐ",
            "meaning": "you",
            "category_id": "interesting",
            "source_sentence": "Fixture line: 你好吗？",
            "source_translation": "Fixture line: how are you?",
            "saved_at": _AT,
        },
        {
            "entry_id": "fixture:zh:cha",
            "headword": "茶",
            "traditional": "茶",
            "reading": "chá",
            "meaning": "tea",
            "category_id": "food",
            "source_sentence": "Fixture line: 我喝茶。",
            "source_translation": "Fixture line: I drink tea.",
            "saved_at": _LATER,
        },
    ),
    "exposures": (
        # heard on three kept days (one taken back to 0 doesn't count)
        {
            "entry_id": FORGOTTEN,
            "heard": 9,
            "heard_by_you": 1,
            "heard_in_deck": 0,
            "first_heard": "2026-10-01",
            "days_heard": 3,
            "last_heard": "2026-10-20",
        },
        # heard before any day was kept: version 11 counts it at least 1 day
        {
            "entry_id": "fixture:zh:cha",
            "heard": 4,
            "heard_by_you": 0,
            "heard_in_deck": 2,
            "first_heard": None,
            "days_heard": 1,
            "last_heard": None,
        },
        # only the learner's own speech: no day
        {
            "entry_id": "fixture:en:hello",
            "heard": 0,
            "heard_by_you": 2,
            "heard_in_deck": 0,
            "first_heard": None,
            "days_heard": 0,
            "last_heard": None,
        },
    ),
    "daily_exposures": (
        {"day": "2026-10-01", "entry_id": FORGOTTEN, "count": 4},
        {"day": "2026-10-09", "entry_id": FORGOTTEN, "count": 2},
        {"day": "2026-10-20", "entry_id": FORGOTTEN, "count": 3},
        {"day": "2026-10-21", "entry_id": FORGOTTEN, "count": 0},
    ),
    "deck_words": (
        {
            "entry_id": FORGOTTEN,
            "headword": "你",
            "traditional": "你",
            "reading": "nǐ",
            "meaning": "you",
            "sentence": "Fixture line: 你好。",
            "translation": "Fixture line: hello.",
            "learned_at": _AT,
        },
        {
            "entry_id": "fixture:zh:cha",
            "headword": "茶",
            "traditional": "茶",
            "reading": "chá",
            "meaning": "tea",
            "sentence": "Fixture line: 一杯茶。",
            "translation": "Fixture line: a cup of tea.",
            "learned_at": _LATER,
        },
    ),
    "anki_exports": (
        {"entry_id": FORGOTTEN, "exported_at": "2026-10-05T10:00:00+00:00"},
        {"entry_id": "fixture:zh:cha", "exported_at": "2026-10-06T10:00:00+00:00"},
    ),
    "daily_coverage": (
        {"day": "2026-10-01", "known": 5, "deck": 2, "new": 3},
        {"day": "2026-10-20", "known": 1, "deck": 0, "new": 4},
    ),
    "daily_listening": (
        {"day": "2026-10-01", "category": "video", "seconds": 300.0},
        {"day": "2026-10-01", "category": "call", "seconds": 42.25},
    ),
    "handed_over_days": ({"day": "2026-10-01"}, {"day": "2026-10-09"}),
    "load_words": (
        {
            "entry_id": FORGOTTEN,
            "standing": "in",
            "stage": 2,
            "meetings": 5,
            "by_hand": 0,
            "place": 1,
            "entered_at": _AT,
            "last_met": _LATER,
            "graduated_at": None,
        },
        {
            "entry_id": "fixture:zh:cha",
            "standing": "graduated",
            "stage": 4,
            "meetings": 12,
            "by_hand": 1,
            "place": None,
            "entered_at": _AT,
            "last_met": None,
            "graduated_at": _LATER,
        },
    ),
    "anki_csv_exports": (
        {"entry_id": FORGOTTEN, "exported_at": "2026-10-07T10:00:00+00:00"},
    ),
    "lookups": (
        {
            "entry_id": FORGOTTEN,
            "pinned": 3,
            "hovered": 5,
            "last_at": _LATER,
            "pinned_since_known": 1,
        },
        {
            "entry_id": "fixture:zh:cha",
            "pinned": 1,
            "hovered": 0,
            "last_at": _AT,
            "pinned_since_known": 0,
        },
    ),
    "saved_sentences": (
        {
            "id": "fixture-sentence-1",
            "original": "我喝茶。",
            "translation": "I drink tea.",
            "parts": '[["我喝茶。","I drink tea.","1",[[2,3,8,11,true]]]]',
            "translation_language": "en",
            "category_id": "food",
            "saved_at": _LATER,
        },
    ),
    "curriculum_words": (
        {
            "entry_id": FORGOTTEN,
            "standing": "in",
            "came": "heard",
            "entered_at": _AT,
            "days_met": 2,
            "last_day": "2026-10-20",
            "sittings": 1,
            "retired_at": None,
        },
        {
            "entry_id": "fixture:zh:cha",
            "standing": "retired",
            "came": "order",
            "entered_at": _AT,
            "days_met": 6,
            "last_day": None,
            "sittings": 3,
            "retired_at": _LATER,
        },
    ),
    "status_history": (
        {
            "id": 1,
            "entry_id": FORGOTTEN,
            "before": "new",
            "after": "known",
            "source": "learner",
            "at": _AT,
        },
        {
            "id": 2,
            "entry_id": "fixture:zh:cha",
            "before": "new",
            "after": "learning",
            "source": "server",
            "at": _LATER,
        },
    ),
    "line_history": (
        {
            "id": 1,
            "scheme": "hsk-2025",
            "midpoint": 2.5,
            "source": "learner",
            "at": _AT,
        },
        {"id": 2, "scheme": None, "midpoint": None, "source": "learner", "at": _LATER},
    ),
    "set_words": (
        {
            "name": "quiet",
            "entry_id": FORGOTTEN,
            "sources": "saved,deck",
            "added_at": _AT,
        },
        {
            "name": "quiet",
            "entry_id": "fixture:zh:cha",
            "sources": "",
            "added_at": _LATER,
        },
    ),
}

# Rows the app can't read - kept in the file, left out of what it reads.
UNREADABLE: dict[str, tuple[dict[str, object], ...]] = {
    "statuses": (
        {
            "entry_id": "fixture:bad:status",
            "status": "maybe",
            "source": "learner",
            "at": _AT,
        },
    ),
    "categories": (
        {"id": "garbled", "name": "Garbled", "color": "#000000", "position": "first"},
    ),
    "saved_words": (
        {
            "entry_id": "fixture:bad:saved",
            "headword": "水",
            "traditional": "水",
            "reading": "shuǐ",
            "meaning": "water",
            "category_id": "food",
            "source_sentence": "Fixture line: 水。",
            "source_translation": "Fixture line: water.",
            "saved_at": "last Tuesday",
        },
    ),
    "exposures": (
        {
            "entry_id": "fixture:bad:exposures",
            "heard": "lots",
            "heard_by_you": 0,
            "heard_in_deck": 0,
            "first_heard": None,
            "days_heard": 0,
            "last_heard": None,
        },
    ),
    "daily_exposures": (
        {"day": "2026-10-02", "entry_id": "fixture:bad:daily", "count": "two"},
    ),
    "deck_words": (
        {
            "entry_id": "fixture:bad:deck",
            "headword": "水",
            "traditional": "水",
            "reading": "shuǐ",
            "meaning": "water",
            "sentence": "Fixture line: 水。",
            "translation": "Fixture line: water.",
            "learned_at": b"\x00\xff",
        },
    ),
    "anki_exports": ({"entry_id": "fixture:bad:anki", "exported_at": "never"},),
    "anki_csv_exports": ({"entry_id": "fixture:bad:csv", "exported_at": "some day"},),
    "daily_coverage": ({"day": "2026-10-21", "known": "many", "deck": 0, "new": 0},),
    "daily_listening": (
        {"day": "2026-10-02", "category": "game", "seconds": "a long time"},
    ),
    "load_words": (
        {
            "entry_id": "fixture:bad:load",
            "standing": "in",
            "stage": 2.5,
            "meetings": 1,
            "by_hand": 0,
            "place": None,
            "entered_at": _AT,
            "last_met": None,
            "graduated_at": None,
        },
    ),
    "lookups": (
        {
            "entry_id": "fixture:bad:lookups",
            "pinned": "often",
            "hovered": 0,
            "last_at": _AT,
            "pinned_since_known": 0,
        },
    ),
    "saved_sentences": (
        {
            "id": "fixture-sentence-garbled",
            "original": "水。",
            "translation": "Water.",
            "parts": "{not json",
            "translation_language": "en",
            "category_id": "food",
            "saved_at": _AT,
        },
    ),
    "curriculum_words": (
        {
            "entry_id": "fixture:bad:curriculum",
            "standing": "in",
            "came": "heard",
            "entered_at": "whenever",
            "days_met": 1,
            "last_day": None,
            "sittings": 0,
            "retired_at": None,
        },
    ),
    "status_history": (
        {
            "id": 3,
            "entry_id": "fixture:bad:history",
            "before": "new",
            "after": "known",
            "source": "learner",
            "at": "soon",
        },
    ),
    "line_history": (
        {
            "id": 3,
            "scheme": "hsk-2025",
            "midpoint": "middle",
            "source": "learner",
            "at": _AT,
        },
    ),
    "set_words": (
        {
            "name": "quiet",
            "entry_id": "fixture:bad:set",
            "sources": "saved",
            "added_at": "tomorrow",
        },
    ),
}


def tables_of(version: int) -> list[str]:
    """The tables a store of `version` has, in the order they were made."""
    return [
        table
        for migration in sqlite_learning._TABLES[:version]
        for table in sorted(migration)
    ]


def build(version: int, path: Path) -> Path:
    """A store of `version` at `path`: the app's first `version` migrations
    on an empty file, then every table seeded with the columns it has then,
    the rows the app can't read among them."""
    db = sqlite3.connect(path)
    try:
        with db:
            for migration in sqlite_learning._MIGRATIONS[:version]:
                for statement in migration:
                    db.execute(statement)
            db.execute(f"PRAGMA user_version = {version}")
            for table in tables_of(version):
                columns = [row[1] for row in db.execute(f"PRAGMA table_info({table})")]
                rows = SEEDS.get(table, ()) + UNREADABLE.get(table, ())
                if not rows:
                    raise ValueError(f"no seed for {table}")
                for row in rows:
                    names = [c for c in columns if c in row]
                    db.execute(
                        f"INSERT INTO {table} ({', '.join(names)})"
                        f" VALUES ({', '.join('?' for _ in names)})",
                        [row[c] for c in names],
                    )
    finally:
        db.close()
    return path


def rung(version: int) -> str:
    """Rung `version` as SQL (`store_dump.script`)."""
    with tempfile.TemporaryDirectory() as folder:
        return script(build(version, Path(folder) / "learning.sqlite"))


def reads(store: SqliteLearningStore) -> dict[str, Any]:
    """Everything the app reads from a store, through its own readers."""
    days = store.exposure_days()
    return {
        "load": _plain(store.load()),
        "saved_sentences": _plain(store.saved_sentences()),
        "status_changes": _plain(store.status_changes()),
        "line_changes": _plain(store.line_changes()),
        "exposure_days": _plain(days),
        "days_to_hand_over": _plain(store.days_to_hand_over()),
        "daily_exposures": {
            day.isoformat(): _plain(store.daily_exposures(day)) for day in days
        },
    }


def _level_copy(path: Path) -> Any:
    copy = level_file(path)
    return json.loads(copy.read_text(encoding="utf-8")) if copy.exists() else None


def opened(path: Path) -> dict[str, Any]:
    """The store at `path` opened by today's app - migrated, if it's older -
    and closed: what it read, what the file then holds and the level's copy."""
    store = SqliteLearningStore(path)
    try:
        found = reads(store)
    finally:
        store.close()
    return {"reads": found, "file": dump(path), "level_copy": _level_copy(path)}


def upgraded(sql: str, folder: Path) -> dict[str, Any]:
    """A rung's SQL made into a store in `folder` and opened by today's app."""
    path = materialise(sql, folder / "learning.sqlite")
    db = sqlite3.connect(path)
    (version,) = db.execute("PRAGMA user_version").fetchone()
    db.close()
    return {"from_version": version, "to_version": VERSION, **opened(path)}


def started_again(sql: str, folder: Path) -> dict[str, Any]:
    """The newest rung opened once - so its level's copy is written beside it
    - then gone (set aside, say), and a store started again at its place."""
    path = materialise(sql, folder / "learning.sqlite")
    SqliteLearningStore(path).close()
    path.rename(path.with_name("learning.sqlite.set-aside"))
    return opened(path)


def _text(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n"


def files() -> dict[str, str]:
    """Every file of the ladder, by name, as recorded from the code now."""
    made: dict[str, str] = {}
    for version in range(1, VERSION + 1):
        sql = rung(version)
        made[f"v{version:02d}.sql"] = sql
        with tempfile.TemporaryDirectory() as folder:
            made[f"v{version:02d}.json"] = _text(upgraded(sql, Path(folder)))
    with tempfile.TemporaryDirectory() as folder:
        made["started-again.json"] = _text(
            started_again(made[f"v{VERSION:02d}.sql"], Path(folder))
        )
    return made


def record(out: Path) -> None:
    """The ladder written to `out` (replaced)."""
    if out.exists():
        shutil.rmtree(out)
    out.mkdir(parents=True)
    for name, text in files().items():
        (out / name).write_text(text, encoding="utf-8", newline="\n")
