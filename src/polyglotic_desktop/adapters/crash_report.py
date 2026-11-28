"""Build the exact, content-free text offered after an improper exit.

Everything in it is from the run that ended improperly, found by its run
id (`run_health.RunningNote`): that run's version, its own log records
(`app_log.run_log`) and the frames of its crash trace
(`crash_trace.trace_of`) - never another run's, and never the id itself.
"""

from __future__ import annotations

import re
from pathlib import Path

from polyglotic_desktop.adapters.app_log import hide_home, run_log
from polyglotic_desktop.adapters.crash_trace import trace_of

_FRAME = re.compile(r'^\s*File "([^"]+)", line (\d+) in (.+)$')


def crash_report_text(
    logs: Path,
    *,
    run: str,
    app_version: str,
    os_version: str,
    home: Path | None = None,
) -> str | None:
    """Return run `run`'s version, its log records and its sanitized stack
    frames, no source line and no value; None if it left neither."""
    home = Path.home() if home is None else home
    records = run_log(logs, run, home=home)
    trace = _frames(trace_of(logs, run), home)
    if not records and not trace:
        return None
    parts = [f"Polyglotic: {app_version}", f"OS: {os_version}"]
    if records:
        parts.extend(("", "Log:", records.rstrip()))
    if trace:
        parts.extend(("", "Stack frames:", trace))
    return "\n".join(parts) + "\n"


def _frames(text: str | None, home: Path) -> str:
    if text is None:
        return ""
    frames: list[str] = []
    for line in text.splitlines():
        match = _FRAME.match(line)
        if match:
            filename = hide_home(match.group(1), home)
            frames.append(f"{filename}:{match.group(2)} in {match.group(3)}")
    return "\n".join(frames)
