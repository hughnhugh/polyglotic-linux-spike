"""The learning corpus for the Rust rebuild (HQ 825, 879, 933's learning-1):
re-recorded from today's app it is what's checked in, two recordings at one
commit are the same bytes, and it holds only the recorder's made-up text."""

import json
import re
from pathlib import Path

import pytest
from tools.rebuild_fixtures import ladder, learning
from tools.rebuild_fixtures.learning import DEFAULT_OUT, differences, record

RECORDERS = (Path(learning.__file__), Path(ladder.__file__))


@pytest.fixture(scope="module")
def recorded(tmp_path_factory: pytest.TempPathFactory) -> Path:
    """One recording now (about 5 s), for the tests below."""
    made = tmp_path_factory.mktemp("recorded") / "learning"
    record(made)
    return made


def test_learning_fixtures_rerecord_exactly(recorded: Path) -> None:
    assert differences(DEFAULT_OUT, recorded) == []


def test_two_recordings_at_one_commit_are_the_same_bytes(
    recorded: Path, tmp_path: Path
) -> None:
    first, second = recorded, tmp_path / "second"
    record(second)
    files = sorted(p.relative_to(first) for p in first.rglob("*") if p.is_file())
    assert files == sorted(
        p.relative_to(second) for p in second.rglob("*") if p.is_file()
    )
    for name in files:
        assert (first / name).read_bytes() == (second / name).read_bytes(), name


def _strings(value: object) -> list[str]:
    if isinstance(value, str):
        return [value]
    if isinstance(value, dict):
        return [s for k, v in value.items() for s in (*_strings(k), *_strings(v))]
    if isinstance(value, list):
        return [s for item in value for s in _strings(item)]
    return []


def test_the_fixtures_hold_only_the_recorders_made_up_text() -> None:
    """No learner's text can be in it (RULES #26, #30): every entry is the
    recorder's own (`fixture:`), and every character outside ASCII is one
    the recorder's own sources or the app's interface wrote."""
    allowed = set("".join(path.read_text(encoding="utf-8") for path in RECORDERS))
    allowed |= set("…·–—’“”")  # the card's own punctuation
    allowed |= set("".join(learning.LINES.values()))  # written as escapes
    texts = [
        text
        for path in DEFAULT_OUT.rglob("*")
        if path.suffix in {".json", ".sql", ".csv"}
        for text in (
            _strings(json.loads(path.read_text(encoding="utf-8")))
            if path.suffix == ".json"
            else [path.read_text(encoding="utf-8")]
        )
    ]
    assert texts
    foreign = {c for text in texts for c in text if ord(c) > 127} - allowed
    assert foreign == set()
    ids = {
        found
        for text in texts
        for found in re.findall(r"\b(?:cedict|ecdict|jmdict|pack):[\w:.-]+", text)
    }
    assert ids == set()  # only the recorder's own `fixture:` entries
