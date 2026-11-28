"""Record the learning compatibility corpus from the current Python app.

Run with ``uv run python -m tools.rebuild_fixtures.learning`` (add ``--check``
to fail on a difference instead of writing), or record every rebuild fixture
with ``uv run python -m tools.rebuild_fixtures.record``. All data in this
module is deliberately invented; importantly, the recorder never opens a
user profile. The small, explicit input corpus makes changes to the Python
contracts visible in review while the values are produced by the real store,
dictionary writer, knowledge rules, sync rules, exposure counting and Anki
exporters. The store's ladder (`ladder.py`) is recorded with it.
"""

from __future__ import annotations

import argparse
import json
import shutil
import tempfile
from collections.abc import Iterable, Iterator
from contextlib import contextmanager
from datetime import UTC, date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from polyglotic_desktop.adapters.anki_package import GenankiDeckWriter
from polyglotic_desktop.adapters.sqlite_dictionary import (
    FORMAT,
    RANKS,
    SqliteDictionary,
    write_dictionary,
)
from polyglotic_desktop.adapters.sqlite_learning import SqliteLearningStore
from polyglotic_desktop.core.learning.anki import AnkiNote, anki_csv, deck_notes
from polyglotic_desktop.core.learning.highlights import WordIntroductions
from polyglotic_desktop.core.learning.knowledge import Knowledge
from polyglotic_desktop.core.learning.levels import KnownLine, LanguageChoices
from polyglotic_desktop.core.learning.lookups import LookupContext
from polyglotic_desktop.core.learning.statuses import StatusRecord, StatusSource
from polyglotic_desktop.core.learning.vocabulary import EntryText, Vocabulary
from polyglotic_desktop.core.lexicon.chinese import ChineseDictionary
from polyglotic_desktop.core.lexicon.english import EnglishDictionary, word_at
from polyglotic_desktop.core.shared import (
    EntryFacts,
    EntryId,
    WordInLine,
    WordSaved,
    WordStatus,
    WordStatusChanged,
    WordUnsaved,
)
from polyglotic_desktop.ports.dictionary import EntryRecord
from polyglotic_desktop.ports.learning import (
    StoredCategory,
    StoredExposures,
    StoredLevel,
    StoredSavedWord,
    StoredStatus,
)
from polyglotic_desktop.ui_next.views.lookup import Learner, Lookup
from tools.rebuild_fixtures import ladder
from tools.rebuild_fixtures.plain import plain as _plain
from tools.rebuild_fixtures.store_dump import dump

REPO = Path(__file__).resolve().parents[2]
DEFAULT_OUT = REPO / "fixtures/rebuild/learning"
AT = datetime(2026, 11, 24, 13, 30, tzinfo=UTC)
DAY = date(2026, 11, 24)
LEARNERS_ZONE = timezone(timedelta(hours=11))
"""The learner's own day in the recordings: Melbourne's in summer (AEDT),
fixed so a recording is the same on any machine. At 13:30 UTC it is already
the next day there (ENGINEERING.md: say whose day it is)."""
GIT_ATTRIBUTES = "* -text\n"
"""The corpus's own `.gitattributes`: its bytes are kept exactly as recorded,
never given a checkout's line endings, so a re-record compares bytes."""

# Public/common words and invented example lines only.  IDs intentionally do
# not overlap the production registries: consumers must treat them as opaque.
WORDS: dict[str, tuple[tuple[str, str, str, str], ...]] = {
    "zh": (
        ("fixture:zh:ni", "你", "nǐ", "you"),
        ("fixture:zh:cha", "茶", "chá", "tea"),
    ),
    "en": (
        ("fixture:en:hello", "hello", "hə-LOH", "a greeting"),
        ("fixture:en:tea", "tea", "tee", "a drink"),
    ),
    "ja": (
        ("fixture:ja:konnichiwa", "こんにちは", "konnichiwa", "hello"),
        ("fixture:ja:cha", "茶", "cha", "tea"),
    ),
    "vi": (
        ("fixture:vi:xinchao", "xin chào", "sin chow", "hello"),
        ("fixture:vi:tra", "trà", "cha", "tea"),
    ),
}
LINES: dict[str, str] = {
    "zh": "\U00020000你喝茶吗？茶！",
    "en": "\U0001f600 Hello, tea? Tea!",
    "ja": "\U0001f600 こんにちは 茶",
    "vi": "\U0001f600 Xin chào, trà?",
}
"""An invented line in each language, each after a character outside the
Basic Multilingual Plane: spans are code points, and one shifted by a code
point - or counted in UTF-16 - shows."""


def _json(path: Path, value: Any) -> None:
    path.write_text(
        json.dumps(_plain(value), ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
        newline="\n",
    )


def _records(language: str) -> list[EntryRecord]:
    return [
        EntryRecord(
            entry_id,
            word,
            "",
            reading,
            (meaning,),
            rank,
            (("fixture", 1 if rank == 1 else 2),),
        )
        for rank, (entry_id, word, reading, meaning) in enumerate(WORDS[language], 1)
    ]


def _write_dictionaries(out: Path) -> None:
    folder = out / "dictionaries"
    folder.mkdir()
    for language in WORDS:
        records = _records(language)
        write_dictionary(
            folder / f"{language}.sqlite",
            {
                "format": FORMAT,
                "ranks": RANKS,
                "name": f"S3 fixture {language}",
                "sources": "public fixture corpus",
                "ranked_entries": str(len(records)),
            },
            records,
            {record.headword: [record.entry_id] for record in records},
            {},
        )
    (folder / "CREDITS.md").write_text(
        "# Credits\n\nThe words are common greetings and drink names used as public, synthetic test data.\n"
        "Dictionary files are produced by the desktop app's pinned `write_dictionary` format writer; no upstream dictionary rows are redistributed.\n",
        encoding="utf-8",
        newline="\n",
    )


def _write_profile(out: Path) -> None:
    profile = out / "profile-v11.sqlite"
    store = SqliteLearningStore(profile)
    store.save_level(StoredLevel("fixture", 1.5))
    store.save_category(StoredCategory("interesting", "Interesting", "#2f9e8f", 0))
    for words in WORDS.values():
        first, second = words
        store.save_status(
            StoredStatus(
                first[0], WordStatus.KNOWN.value, StatusSource.LEARNER.value, AT
            )
        )
        store.save_status(
            StoredStatus(
                second[0], WordStatus.LEARNING.value, StatusSource.LEARNER.value, AT
            )
        )
        store.save_word(
            StoredSavedWord(
                second[0],
                second[1],
                "",
                second[2],
                second[3],
                "interesting",
                f"I found {second[1]} in the fixture.",
                "Synthetic translation.",
                AT,
            )
        )
        store.save_exposures(
            [StoredExposures(first[0], 3, 1, 0), StoredExposures(second[0], 2, 0, 1)],
            {DAY: {first[0]: 2, second[0]: 1}},
        )
    snapshot = store.load()
    store.close()
    _json(out / "profile-v11.json", snapshot)
    by_id = {status.entry_id: status for status in snapshot.statuses}
    exposure = {item.entry_id: item for item in snapshot.exposures}
    saved = {item.entry_id: item for item in snapshot.saved_words}
    for language in WORDS:
        _json(
            out / f"words-view-{language}.json",
            [
                {
                    "entry": _plain(record),
                    "status": _plain(by_id[record.entry_id]),
                    "exposures": _plain(exposure[record.entry_id]),
                    "saved": _plain(saved.get(record.entry_id)),
                }
                for record in _records(language)
            ],
        )


class _CardLearner:
    """The lookup model's port, backed only by the recorded production stores."""

    def __init__(self, dictionary: Any, vocabulary: Vocabulary, language: str) -> None:
        self.dictionary = dictionary
        self.vocabulary = vocabulary
        self.language = language
        self.dictionary_problem = None
        self.choices = LanguageChoices()

    ready = True

    def of(self, language: str | None) -> Learner:
        return self

    def word_language(self, word: str, language: str | None) -> str | None:
        return language

    def found_in(
        self, word: str, language: str | None, fallbacks: Any = ()
    ) -> str | None:
        return language

    def has_dictionary(self, language: str | None) -> bool:
        return True

    def learns(self, language: str | None) -> bool:
        return True

    def choices_of(self, language: str | None) -> Any:
        return None

    def is_basic(self, language: str | None) -> bool:
        return False

    def knowledge_of(self, language: str | None) -> Knowledge:
        return self.vocabulary.knowledge

    def form_reading(self, word: str, language: str | None = None) -> str:
        return ""

    def parts(self, word: str, language: str | None = None) -> list[Any]:
        return []

    def lookup(self, word: str, language: str | None = None) -> list[Any]:
        return self.dictionary.lookup(word)

    def facts(self, entry: Any) -> EntryFacts:
        return entry.facts(self.vocabulary.scheme)

    def add_to_load(self, entry_id: EntryId) -> bool:
        return self.vocabulary.add_to_load(entry_id)

    def words_in(
        self, line: str, language: str | None = None, said: Any = ()
    ) -> list[Any]:
        return self.dictionary.words_in(line, self.vocabulary.scheme)

    def word_at(
        self, line: str, index: int, language: str | None = None
    ) -> tuple[int, int] | None:
        return (
            self.dictionary.word_at(line, index)
            if hasattr(self.dictionary, "word_at")
            else word_at(line, index)
        )


SCHEMES = {"zh": "hsk-2025", "en": "en-frequency"}
"""The level scheme of each language with one; a pack language's is the
fixture's own."""


@contextmanager
def _dictionary(out: Path, language: str) -> Iterator[Any]:
    """The language's fixture dictionary as the app opens it: Chinese and
    English by their own classes, a pack language as `open_pack` does."""
    path = out / "dictionaries" / f"{language}.sqlite"
    dictionary: Any
    if language == "zh":
        file = SqliteDictionary(path)
        dictionary = ChineseDictionary(file)
    elif language == "en":
        file = SqliteDictionary(path)
        dictionary = EnglishDictionary(file)
    else:
        from polyglotic_desktop.main import open_pack

        dictionary, file = open_pack(path, language)
    try:
        yield dictionary
    finally:
        file.close()


def _facts_of(dictionary: Any) -> Any:
    def facts(entry_id: EntryId, selected: str) -> EntryFacts | None:
        entry = dictionary.entry(entry_id)
        return entry.facts(selected) if entry else None

    return facts


@contextmanager
def _profile_copy(out: Path, name: str) -> Iterator[Path]:
    """A copy of the recorded profile, removed with its level's copy after."""
    path = out / f".{name}.sqlite"
    shutil.copyfile(out / "profile-v11.sqlite", path)
    try:
        yield path
    finally:
        path.unlink(missing_ok=True)
        (out / f".{name}-level.json").unlink(missing_ok=True)


def _write_card_views(out: Path) -> None:
    """Record the lookup card model, rather than its downstream Anki note."""
    views: dict[str, list[dict[str, Any]]] = {}
    with _profile_copy(out, "cards-view") as card_profile:
        for language, words in WORDS.items():
            with _dictionary(out, language) as dictionary:
                store = SqliteLearningStore(card_profile)
                try:
                    vocabulary = Vocabulary(
                        store,
                        _facts_of(dictionary),
                        SCHEMES.get(language, "fixture"),
                        lambda: AT,
                        day_of=learners_day,
                    )
                    lookup = Lookup(_CardLearner(dictionary, vocabulary, language))
                    views[language] = [
                        _card_view(lookup, language, entry_id, word)
                        for entry_id, word, _reading, _meaning in words
                    ]
                finally:
                    store.close()
    _json(out / "cards-view.json", views)


def _card_view(lookup: Lookup, language: str, entry_id: str, word: str) -> Any:
    context = LookupContext(
        f"Fixture line with {word}.",
        "Synthetic translation.",
        f"counterpart-{language}",
        "en",
    )
    lookup.show(word, context, pinned=True, at=(18, 18 + len(word)), language=language)
    card = lookup.card()
    row = {"entry_id": entry_id, "card": _plain(card), "actions": card.actions}
    if card.parts:
        lookup.part(0)
        row["part"] = _plain(lookup.card())
        lookup.back()
        row["back"] = _plain(lookup.card())
    return row


def _write_cards_and_exports(out: Path) -> None:
    cards: dict[str, list[dict[str, Any]]] = {}
    notes: list[AnkiNote] = []
    for language, words in WORDS.items():
        cards[language] = []
        for entry_id, word, reading, meaning in words:
            note = AnkiNote(
                entry_id,
                word,
                "",
                reading,
                meaning,
                f"Fixture line with {word}.",
                "Synthetic translation.",
                "Interesting",
                AT,
                AT,
            )
            notes.append(note)
            cards[language].append(
                _plain(deck_notes([note], pack_language=language)[0])
            )
    _json(out / "cards.json", cards)
    (out / "anki.csv").write_text(anki_csv(notes), encoding="utf-8", newline="\n")
    deck = deck_notes(notes[:2]) + tuple(
        item
        for language, language_notes in (
            (code, notes[index * 2 : index * 2 + 2]) for index, code in enumerate(WORDS)
        )
        if language not in {"zh"}
        for item in deck_notes(language_notes, pack_language=language)
    )
    GenankiDeckWriter().build(deck)  # exercise the real .apkg writer
    _json(out / "anki-apkg-notes.json", deck)


def _write_learning_answers(out: Path) -> None:
    statuses = {
        "fixture:known": StatusRecord(WordStatus.KNOWN, StatusSource.LEARNER, AT)
    }
    knowledge = Knowledge(
        statuses.get, lambda: KnownLine.words(50), KnownLine.words(10)
    )
    answers = []
    for index in range(200):
        entry_id = "fixture:known" if index == 0 else f"fixture:answer:{index:03d}"
        facts = EntryFacts(EntryId(entry_id), None, index + 1, False)
        answers.append({"entry": _plain(facts), "answer": _plain(knowledge.of(facts))})
    _json(out / "knowledge-200.json", answers)


def _describe(entry_id: EntryId) -> EntryText | None:
    """A word's text from this PC's dictionary: the fixture's word list."""
    for words in WORDS.values():
        for found, word, reading, meaning in words:
            if found == entry_id:
                return EntryText(word, "", reading, meaning)
    return None


_DAY = timedelta(days=1)
FROM_SERVER: tuple[tuple[str, tuple[Any, ...]], ...] = (
    ("nothing", ()),
    (
        "status-newer-than-the-learners",
        (
            WordStatusChanged(
                EntryId("fixture:en:hello"), WordStatus.IGNORED, AT + _DAY
            ),
        ),
    ),
    (
        "status-older-than-the-learners",
        (WordStatusChanged(EntryId("fixture:en:tea"), WordStatus.KNOWN, AT - _DAY),),
    ),
    (
        "status-as-old-as-the-learners",
        (WordStatusChanged(EntryId("fixture:zh:ni"), WordStatus.NEW, AT),),
    ),
    (
        "status-of-a-word-not-set-here",
        (WordStatusChanged(EntryId("fixture:zh:hao"), WordStatus.LEARNING, AT - _DAY),),
    ),
    ("saved-elsewhere", (WordSaved(EntryId("fixture:zh:ni"), AT + _DAY),)),
    (
        "saved-elsewhere-not-in-this-dictionary",
        (WordSaved(EntryId("fixture:zh:missing"), AT),),
    ),
    (
        "unsaved-before-it-was-saved-here",
        (WordUnsaved(EntryId("fixture:zh:cha"), AT - _DAY),),
    ),
    (
        "unsaved-after-it-was-saved-here",
        (WordUnsaved(EntryId("fixture:vi:tra"), AT + _DAY),),
    ),
)
"""Learning data from the server, in turn, applied to the recorded profile:
protocol.md's rule is that the latest `at` wins, and the learner's own
status wins over the same time from the server."""


def _event(event: Any) -> dict[str, Any]:
    return {"kind": type(event).__name__, **_plain(event)}


def _write_from_server(out: Path) -> None:
    """What `apply_from_server` makes of each exchange: how many entries
    changed, and the words' statuses and saved words after it."""
    exchanges = []
    with _profile_copy(out, "from-server") as path:
        store = SqliteLearningStore(path)
        try:
            vocabulary = Vocabulary(
                store,
                lambda entry_id, scheme: None,
                "fixture",
                lambda: AT,
                day_of=learners_day,
            )
            for name, events in FROM_SERVER:
                changed = vocabulary.apply_from_server(events, _describe)
                ids = sorted({event.entry_id for event in events})
                exchanges.append(
                    {
                        "name": name,
                        "events": [_event(event) for event in events],
                        "changed": changed,
                        "after": [
                            {
                                "entry_id": entry_id,
                                "status": _plain(vocabulary.status_of_entry(entry_id)),
                                "saved": _plain(vocabulary.saved_word(entry_id)),
                            }
                            for entry_id in ids
                        ],
                    }
                )
            history = store.status_changes()
        finally:
            store.close()
    _json(out / "from-server.json", {"exchanges": exchanges, "status_history": history})


def learners_day(at: datetime) -> date:
    """The learner's own day at `at` (`LEARNERS_ZONE`)."""
    return at.astimezone(LEARNERS_ZONE).date()


# (seconds from the session's start, what happened, caption ID, source, text,
# the captions it replaces): two sources interleaved, the PC's video and the
# learner's own mic - a join finishes a caption again with new text.
SESSIONS: dict[str, tuple[datetime, tuple[tuple[Any, ...], ...]]] = {
    "before-learning-day": (
        datetime(2026, 11, 24, 8, 15, tzinfo=UTC),
        (
            (0, "finished", "video-1", "video", "你喝茶吗？", ()),
            (2, "finished", "mic-1", "mic", "我喝茶。", ()),
            (3, "finished", "video-2", "video", "你好。", ()),
            (5, "finished", "video-2", "video", "你好，喝茶。", ()),
            (6, "finished", "mic-2", "mic", "你呢？", ()),
            (8, "withdrawn", "video-1", "video", "", ()),
            (9, "finished", "video-3", "video", "茶。", ("video-2",)),
        ),
    ),
    "learning-day-1330-utc": (
        AT,
        (
            (0, "finished", "video-4", "video", "你喝茶。", ()),
            (1, "finished", "mic-3", "mic", "茶。", ()),
            (2, "withdrawn", "mic-3", "mic", "", ()),
            (4, "finished", "video-5", "video", "你。", ()),
            (5, "finished", "video-4", "video", "你喝水。", ()),
        ),
    ),
}
YOURS = frozenset({"mic"})
"""The sources that are the learner's own speech (`by_you`)."""


def _words(dictionary: Any, text: str, scheme: str) -> list[WordInLine]:
    return list(dictionary.words_in(text, scheme))


def _spans(text: str, words: Iterable[Any]) -> list[dict[str, Any]]:
    """Spans of `text` - words in a line, or saved spans - in code points."""
    return [
        {
            "start": w.start,
            "end": w.end,
            "text": text[w.start : w.end],
            "entry_id": w.entry_id if hasattr(w, "entry_id") else w.entry.entry_id,
        }
        for w in words
    ]


def _write_replayed_sessions(out: Path) -> None:
    """Two sessions replayed through the real counting into a new store:
    after each, the exposures, the daily counts and the coverage it keeps."""
    recorded: dict[str, Any] = {}
    now = [AT]
    with tempfile.TemporaryDirectory() as folder, _dictionary(out, "zh") as dictionary:
        store = SqliteLearningStore(Path(folder) / "learning.sqlite")
        try:
            vocabulary = Vocabulary(
                store,
                _facts_of(dictionary),
                SCHEMES["zh"],
                lambda: now[0],
                day_of=learners_day,
            )
            for name, (start, events) in SESSIONS.items():
                replayed = []
                for seconds, what, caption_id, source, text, replaces in events:
                    now[0] = start + timedelta(seconds=seconds)
                    words = _words(dictionary, text, SCHEMES["zh"]) if text else []
                    for replaced in replaces:
                        vocabulary.caption_withdrawn(replaced)
                    if what == "withdrawn":
                        vocabulary.caption_withdrawn(caption_id)
                    else:
                        vocabulary.caption_finished(
                            caption_id, words, source in YOURS, source
                        )
                    replayed.append(
                        {
                            "at": now[0],
                            "what": what,
                            "caption_id": caption_id,
                            "source": source,
                            "replaces": list(replaces),
                            "words": _spans(text, words),
                        }
                    )
                snapshot = store.load()
                recorded[name] = {
                    "events": replayed,
                    "exposures": sorted(snapshot.exposures),
                    "daily_exposures": {
                        day.isoformat(): store.daily_exposures(day)
                        for day in store.exposure_days()
                    },
                    "coverage": snapshot.coverage,
                }
        finally:
            store.close()
    _json(out / "replayed-sessions.json", recorded)


def _write_line_words(out: Path) -> None:
    """Each language's invented line: its words as the dictionary splits
    it, and what the line shows over the recorded profile - its saved words,
    new words and words in the deck - all spans in code points."""
    lines: dict[str, Any] = {}
    with _profile_copy(out, "line-words") as path:
        for language, text in LINES.items():
            with _dictionary(out, language) as dictionary:
                store = SqliteLearningStore(path)
                try:
                    scheme = SCHEMES.get(language, "fixture")
                    vocabulary = Vocabulary(
                        store,
                        _facts_of(dictionary),
                        scheme,
                        lambda: AT,
                        day_of=learners_day,
                    )
                    words = _words(dictionary, text, scheme)
                    (shown,) = vocabulary.highlights(
                        [(text, words)], WordIntroductions.EVERY
                    )
                    lines[language] = {
                        "line": text,
                        "words": _spans(text, words),
                        "saved": _spans(text, shown.saved),
                        "unfamiliar": _spans(text, shown.unfamiliar),
                        "in_deck": _spans(text, shown.in_deck),
                    }
                finally:
                    store.close()
    _json(out / "line-words.json", lines)


def _record_into(out: Path) -> None:
    out.mkdir(parents=True)
    _write_dictionaries(out)
    _write_profile(out)
    _write_card_views(out)
    _write_cards_and_exports(out)
    _write_learning_answers(out)
    _write_from_server(out)
    _write_replayed_sessions(out)
    _write_line_words(out)
    ladder.record(out / "ladder")
    readme = REPO / "tools/rebuild_fixtures/learning_README.md"
    (out / "README.md").write_bytes(readme.read_bytes().replace(b"\r\n", b"\n"))
    (out / ".gitattributes").write_text(GIT_ATTRIBUTES, encoding="utf-8", newline="\n")


def _files(folder: Path) -> dict[str, Path]:
    return {
        path.relative_to(folder).as_posix(): path
        for path in sorted(folder.rglob("*"))
        if path.is_file()
    }


def same(a: Path, b: Path) -> bool:
    """Whether two recorded files are the same: their bytes, or for a
    SQLite file what it holds (`store_dump.dump`) - SQLite stamps its own
    version in the header, so one recorded on Linux differs there from
    Windows' and nowhere else."""
    if a.suffix == ".sqlite":
        return dump(a) == dump(b)
    return a.read_bytes() == b.read_bytes()


def differences(expected: Path, made: Path) -> list[str]:
    """The files that differ between two recordings, missing from either
    included."""
    old, new = _files(expected), _files(made)
    return sorted(
        name
        for name in old.keys() | new.keys()
        if name not in old or name not in new or not same(old[name], new[name])
    )


def record(out: Path = DEFAULT_OUT) -> None:
    """The corpus recorded into `out`, replacing it. A SQLite file that
    holds the same as the one there keeps that one's bytes, so recording on
    another system changes nothing."""
    with tempfile.TemporaryDirectory() as folder:
        made = Path(folder) / "learning"
        _record_into(made)
        if out.exists():
            kept = _files(out)
            for name, path in _files(made).items():
                if name in kept and path.suffix == ".sqlite" and same(kept[name], path):
                    shutil.copyfile(kept[name], path)
            shutil.rmtree(out)
        shutil.copytree(made, out)


def check(out: Path = DEFAULT_OUT) -> list[str]:
    """The corpus's files that a recording now would change."""
    with tempfile.TemporaryDirectory() as folder:
        made = Path(folder) / "learning"
        _record_into(made)
        return differences(out, made)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT)
    parser.add_argument(
        "--check", action="store_true", help="fail instead of rewriting stale files"
    )
    args = parser.parse_args()
    if args.check:
        if stale := check(args.out):
            raise SystemExit("stale learning fixtures: " + ", ".join(stale))
    else:
        record(args.out)


if __name__ == "__main__":
    main()
