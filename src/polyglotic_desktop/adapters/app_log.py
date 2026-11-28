"""The app's log, as a report attaches it: the newest part, the user's folder hidden.

The log (`logs/polyglotic.log` in the data folder, rotated as
`polyglotic.log.1`, `.2`...) records what the app did - never captions,
audio or settings. A report may attach its newest `LIMIT` characters,
reading back into the previous file when the current one is short. Before
the user sees it, their home folder (`C:\\Users\\<name>`) is replaced by
`%USERPROFILE%`: a traceback names files by their full path, and the
path holds the user's name. What `read_log` returns is exactly what's
shown and sent.

Each run starts its part of the log with one line from `RUN_LOG`, `run
<id>` (polyglotic-hq 1009): how the next start finds the lines of a run
that ended improperly (`run_log`), and no other run's. The id is random,
new each run and kept on this PC: neither `read_log` nor `run_log` returns
those lines.
"""

import re
from pathlib import Path

LIMIT = 256 * 1024  # characters: half the protocol's 512 KiB, so a request stays small
LOG_NAME = "polyglotic.log"
LOG_FILES_READ = 10
"""Rotated files read back (count): more than the app keeps (`main.LOG_FILES`)."""
RUN_LOG = "polyglotic_desktop.run"
"""The logger of each run's first line, `run <id>`."""

# A record as `main.start_logging` writes it: time, level, logger, message.
_RECORD = re.compile(r"^\d{4}-\d\d-\d\d \d\d:\d\d:\d\d,\d{3} [A-Z]+ ([\w.]+): (.*)$")
_RUN_ID = re.compile(r"^run ([0-9a-f]{16})$")


def run_started(line: str) -> str | None:
    """The run id that `line` starts, if it's a run's first line."""
    record = _RECORD.match(line)
    if record is None or record.group(1) != RUN_LOG:
        return None
    started = _RUN_ID.match(record.group(2))
    return started.group(1) if started else None


def read_log(folder: Path, home: Path | None = None, limit: int = LIMIT) -> str | None:
    """The newest `limit` characters of the log in `folder`, starting at a
    whole line, with `home` hidden; None if there's no log (run from
    source, the app logs to its console)."""
    parts: list[str] = []
    size = 0
    for index in range(LOG_FILES_READ):
        try:
            text = _log_file(folder, index).read_text("utf-8", errors="replace")
        except OSError:
            break
        parts.insert(0, text)
        size += len(text)
        if size >= limit:
            break
    if not parts:
        return None
    joined = "".join(
        line
        for line in "".join(parts).splitlines(keepends=True)
        if run_started(line.rstrip("\r\n")) is None
    )
    return hide_home(_newest(joined, limit), home if home is not None else Path.home())


def run_log(
    folder: Path, run: str, home: Path | None = None, limit: int = LIMIT
) -> str | None:
    """The app's own records from run `run` alone - from its first line to
    the next run's - its newest `limit` characters, `home` hidden; None
    if the log holds no line of that run.

    Only whole records of the app's own loggers (`polyglotic_desktop...`)
    are kept: no library's line and no line that isn't a record (a value
    some message carried over a line break). The run lines themselves are
    left out: their ids stay on this PC."""
    parts: list[str] = []
    for index in range(LOG_FILES_READ):
        try:
            text = _log_file(folder, index).read_text("utf-8", errors="replace")
        except OSError:
            break
        parts.insert(0, text)
        if run in text:  # its first line is in this file: no older file needed
            break
    kept: list[str] = []
    within = False
    for line in "".join(parts).splitlines():
        started = run_started(line)
        if started is not None:
            if within:
                break  # the next run's part
            within = started == run
            continue
        if within and _ours(line):
            kept.append(line + "\n")
    if not kept:
        return None
    return hide_home(
        _newest("".join(kept), limit), home if home is not None else Path.home()
    )


def _log_file(folder: Path, index: int) -> Path:
    return folder / (LOG_NAME if index == 0 else f"{LOG_NAME}.{index}")


def _ours(line: str) -> bool:
    record = _RECORD.match(line)
    if record is None:
        return False
    name = record.group(1)
    return name in ("polyglotic_desktop", "__main__") or name.startswith(
        "polyglotic_desktop."
    )


def _newest(text: str, limit: int) -> str:
    if len(text) <= limit:
        return text
    text = text[-limit:]
    newline = text.find("\n")
    return text[newline + 1 :] if newline >= 0 else text


def hide_home(text: str, home: Path) -> str:
    """`text` with the user's home folder written as `%USERPROFILE%`, in
    either slash, any case (Windows paths ignore case), and escaped with
    each backslash doubled, as Velopack's own lines write a path at every
    update check ("Reading releases from file: ...", polyglotic-hq 336)."""
    escaped = str(home).replace("\\", "\\\\")
    for form in (escaped, str(home), home.as_posix()):  # the escaped one first
        if len(form) <= 3:  # a drive or nothing: no name to hide
            continue
        lowered, needle = text.lower(), form.lower()
        found = lowered.find(needle)
        while found >= 0:
            text = text[:found] + "%USERPROFILE%" + text[found + len(form) :]
            lowered = text.lower()
            found = lowered.find(needle, found + len("%USERPROFILE%"))
    return text
