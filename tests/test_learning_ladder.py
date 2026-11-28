"""The learning store's ladder (933's learning-1; `tools/rebuild_fixtures/
ladder.py`): a recorded store at every schema version, each upgraded by
today's app to what was recorded - its rows, the ones it can't read among
them, and its level - and nothing lost on the way.

Each rung's SQL is checked in, so an edited old migration shows as a
changed rung, and a new version fails here until its rung is recorded
(`uv run python -m tools.rebuild_fixtures.record`)."""

import shutil
import sqlite3
from pathlib import Path

import pytest
from tools.rebuild_fixtures import ladder
from tools.rebuild_fixtures.learning import DEFAULT_OUT
from tools.rebuild_fixtures.store_dump import dump, materialise

from polyglotic_desktop.adapters.sqlite_learning import (
    VERSION,
    SqliteLearningStore,
    level_file,
)

LADDER = DEFAULT_OUT / "ladder"
VERSIONS = range(1, VERSION + 1)


def _rung(version: int) -> str:
    return (LADDER / f"v{version:02d}.sql").read_text(encoding="utf-8")


def _recorded(name: str) -> str:
    return (LADDER / name).read_text(encoding="utf-8")


def _opened_once(version: int, folder: Path) -> Path:
    path = materialise(_rung(version), folder / "learning.sqlite")
    SqliteLearningStore(path).close()
    return path


def test_there_is_a_rung_for_every_version() -> None:
    assert sorted(p.name for p in LADDER.iterdir()) == sorted(
        [f"v{v:02d}.{kind}" for v in VERSIONS for kind in ("sql", "json")]
        + ["started-again.json"]
    )


@pytest.mark.parametrize("version", VERSIONS)
def test_each_rung_is_what_its_migrations_make(version: int) -> None:
    """The first N migrations, seeded: an old migration edited shows here."""
    assert ladder.rung(version) == _rung(version)


@pytest.mark.parametrize("version", VERSIONS)
def test_each_rung_seeds_every_table_with_rows_it_cant_read(
    version: int, tmp_path: Path
) -> None:
    path = materialise(_rung(version), tmp_path / "learning.sqlite")
    tables = dump(path)["tables"]
    assert sorted(tables) == sorted(ladder.tables_of(version))
    assert all(tables[name]["rows"] for name in tables)
    # every table but the level's one row and the days handed over (whose
    # text the app never parses) has a row the app can't read
    assert set(tables) - set(ladder.UNREADABLE) <= {"level", "handed_over_days"}


@pytest.mark.parametrize("version", VERSIONS)
def test_each_rung_upgrades_to_what_was_recorded(version: int, tmp_path: Path) -> None:
    """Every migration it lacks, and today's readers: the rows read, every
    row the file then holds (by SQL alone) and the level's copy."""
    found = ladder.upgraded(_rung(version), tmp_path)
    assert found["file"]["user_version"] == VERSION
    assert ladder._text(found) == _recorded(f"v{version:02d}.json")


def _as_dumped(value: object) -> object:
    return {"blob": value.hex()} if isinstance(value, bytes) else value


@pytest.mark.parametrize("version", VERSIONS)
def test_the_rows_it_cant_read_stay_in_the_file(version: int, tmp_path: Path) -> None:
    """Each garbled row is still there after the upgrade, as it was (but
    for the days a word was heard on, which version 11 fills in)."""
    rung = dump(materialise(_rung(version), tmp_path / "rung.sqlite"))["tables"]
    upgraded = dump(_opened_once(version, tmp_path))["tables"]
    for table, garbled in ladder.UNREADABLE.items():
        if table not in rung:
            continue
        columns = upgraded[table]["columns"]
        rows = [dict(zip(columns, row, strict=True)) for row in upgraded[table]["rows"]]
        for seed in garbled:
            wanted = {
                column: _as_dumped(value)
                for column, value in seed.items()
                if column in rung[table]["columns"]
                and column not in {"days_heard", "last_heard"}
            }
            assert any(all(row[c] == v for c, v in wanted.items()) for row in rows), (
                table,
                seed,
            )


@pytest.mark.parametrize("version", VERSIONS)
def test_a_second_start_changes_nothing(version: int, tmp_path: Path) -> None:
    path = _opened_once(version, tmp_path)
    before, copy = dump(path), level_file(path).read_bytes()
    SqliteLearningStore(path).close()
    assert dump(path) == before
    assert level_file(path).read_bytes() == copy


def _with_entry_ids(path: Path) -> dict[str, int]:
    db = sqlite3.connect(path)
    try:
        return {
            table: db.execute(
                f"SELECT COUNT(*) FROM {table} WHERE entry_id = ?", (ladder.FORGOTTEN,)
            ).fetchone()[0]
            for (table,) in db.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table'"
            )
            if "entry_id"
            in {row[1] for row in db.execute(f"PRAGMA table_info({table})")}
        }
    finally:
        db.close()


@pytest.mark.parametrize("version", VERSIONS)
def test_a_forgotten_entry_is_left_only_where_it_is_kept(
    version: int, tmp_path: Path
) -> None:
    """`forget_entry` (an entry merged into another) takes the entry out of
    every table that has entries - a table added later too - but the daily
    counts and the status history."""
    path = _opened_once(version, tmp_path)
    before = _with_entry_ids(path)
    # in every table with entries that the rung's version had, to start with
    assert all(before[t] for t in ladder.tables_of(version) if t in before), before
    store = SqliteLearningStore(path)
    store.forget_entry(ladder.FORGOTTEN)
    store.close()
    after = _with_entry_ids(path)
    kept = {t: n for t, n in before.items() if n and t in ladder.KEPT_WHEN_FORGOTTEN}
    assert {t: n for t, n in after.items() if n} == kept


def test_a_store_started_again_takes_the_level_from_its_copy(tmp_path: Path) -> None:
    found = ladder.started_again(_rung(VERSION), tmp_path)
    assert found["reads"]["load"]["level"] == {"scheme": "hsk-2025", "midpoint": 2.5}
    assert ladder._text(found) == _recorded("started-again.json")


def test_the_recorded_profile_is_unchanged_by_opening_it(tmp_path: Path) -> None:
    """The round trip: open the v11 profile, do nothing, close."""
    path = tmp_path / "profile-v11.sqlite"
    shutil.copyfile(DEFAULT_OUT / "profile-v11.sqlite", path)
    shutil.copyfile(DEFAULT_OUT / "profile-v11-level.json", level_file(path))
    before, copy = dump(path), level_file(path).read_bytes()
    SqliteLearningStore(path).close()
    assert dump(path) == before
    assert level_file(path).read_bytes() == copy
