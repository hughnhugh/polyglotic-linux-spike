"""A learning store as plain text, read by SQL alone (never through the
app's row readers): every table's schema and every row, sorted, with each
value's SQLite type kept, so a row the app can't read is in it too.

`dump` is the store's full sorted contents as JSON-ready data, for the
recorded fixtures and for comparing two files whose bytes differ only where
SQLite stamps its own version (the header's bytes 92-99: a file written on
Linux and on Windows differs there and nowhere else). `script` writes a
store out as SQL that `materialise` turns back into the same file: the
ladder's rungs are kept as such scripts, readable in review.

Made-up data only: these run on the fixtures, never on a learner's file.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Any


def _value(value: object) -> Any:
    """A SQLite value for JSON with its type kept: a blob as its hex."""
    if isinstance(value, bytes):
        return {"blob": value.hex()}
    return value


def _tables(db: sqlite3.Connection) -> list[tuple[str, str]]:
    """Each table and the SQL that makes it, in the order they were made."""
    return [
        (str(name), str(sql))
        for name, sql in db.execute(
            "SELECT name, sql FROM sqlite_master WHERE type = 'table'"
            " AND name NOT LIKE 'sqlite_%' ORDER BY rowid"
        )
    ]


def _columns(db: sqlite3.Connection, table: str) -> list[str]:
    return [str(row[1]) for row in db.execute(f'PRAGMA table_info("{table}")')]


def _rows(db: sqlite3.Connection, table: str, width: int) -> list[tuple[object, ...]]:
    """Every row, in SQLite's order over all its columns (NULLs, then
    numbers, then text, then blobs): the same on any machine."""
    order = ", ".join(str(n) for n in range(1, width + 1))
    return list(db.execute(f'SELECT * FROM "{table}" ORDER BY {order}'))


def dump(path: Path) -> dict[str, Any]:
    """The store at `path`: its version and, by table name, its schema,
    columns and sorted rows."""
    db = sqlite3.connect(path)
    try:
        (version,) = db.execute("PRAGMA user_version").fetchone()
        tables: dict[str, Any] = {}
        for name, sql in sorted(_tables(db)):
            columns = _columns(db, name)
            tables[name] = {
                "sql": sql,
                "columns": columns,
                "rows": [
                    [_value(value) for value in row]
                    for row in _rows(db, name, len(columns))
                ],
            }
        return {"user_version": int(version), "tables": tables}
    finally:
        db.close()


def _literal(value: object) -> str:
    """`value` as an SQL literal - by Python, not SQLite's `quote()`, whose
    way of writing a real number has changed between SQLite versions."""
    if value is None:
        return "NULL"
    if isinstance(value, bool):
        raise TypeError("SQLite has no booleans")
    if isinstance(value, int):
        return str(value)
    if isinstance(value, float):
        return repr(value)
    if isinstance(value, bytes):
        return f"X'{value.hex()}'"
    if isinstance(value, str):
        return "'" + value.replace("'", "''") + "'"
    raise TypeError(f"not a SQLite value: {type(value).__name__}")


def script(path: Path) -> str:
    """The store at `path` as SQL: its version, its tables in the order they
    were made, and each table's rows, sorted, with their columns named."""
    db = sqlite3.connect(path)
    try:
        (version,) = db.execute("PRAGMA user_version").fetchone()
        lines = [f"PRAGMA user_version = {int(version)};"]
        tables = _tables(db)
        lines += [f"{sql};" for _, sql in tables]
        for name, _ in tables:
            columns = _columns(db, name)
            named = ", ".join(f'"{column}"' for column in columns)
            for row in _rows(db, name, len(columns)):
                values = ", ".join(_literal(value) for value in row)
                lines.append(f'INSERT INTO "{name}" ({named}) VALUES ({values});')
        return "\n".join(lines) + "\n"
    finally:
        db.close()


def materialise(sql: str, path: Path) -> Path:
    """`script`'s SQL made into a store at `path` (a new file)."""
    if path.exists():
        raise FileExistsError(path)
    db = sqlite3.connect(path)
    try:
        # one transaction: a commit a statement took about 1 s a rung
        db.executescript(f"BEGIN;\n{sql}COMMIT;\n")
    finally:
        db.close()
    return path
