"""The interface's translation lookups as a snapshot (859's N4, S4).

Each row is what Qt looks a translation up by: context, English source,
disambiguation comment and whether it is a plural. File and line are left
out on purpose (a `.ts` location carries a file and no line, and a move
changes both), so a pure move keeps the snapshot and a lost string or a
changed context does not. `python -m tools.i18n snapshot` accepts a change.
"""

import json
from collections import Counter
from pathlib import Path

from tools.i18n.extract import Message

Row = tuple[str, str, str, bool]


def rows(messages: list[Message]) -> list[Row]:
    """The lookup identities, independent of source order and place."""
    return sorted(
        (message.context, message.source, message.comment, message.numerus)
        for message in messages
    )


def text(messages: list[Message]) -> str:
    """The snapshot file's text for *messages*."""
    return json.dumps(rows(messages), ensure_ascii=False, indent=2) + "\n"


def changes(recorded: str, messages: list[Message]) -> list[str]:
    """What differs from the recorded snapshot, one line per lookup."""
    before: Counter[tuple[object, ...]] = Counter(
        tuple(row) for row in json.loads(recorded)
    )
    after: Counter[tuple[object, ...]] = Counter(rows(messages))
    lost = sorted((before - after).elements(), key=repr)
    new = sorted((after - before).elements(), key=repr)
    return [f"lost: {row!r}" for row in lost] + [f"new: {row!r}" for row in new]


def write(path: Path, messages: list[Message]) -> None:
    """Replace ``path`` with the current translation lookups."""
    path.write_text(text(messages), encoding="utf-8", newline="\n")
