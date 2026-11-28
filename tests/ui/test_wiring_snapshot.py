"""Main's Qt wiring at run time (859's N5, S5).

`tests/ui/wiring_snapshot.py` builds the interface offscreen as
`test_main_wiring` does, plus a caption window, a transcript and Settings,
and records every QObject by a stable path: class, name, child count, each
signal's receiver count, event filters and each QTimer's interval, single
shot and state. A split that drops or doubles a `.connect`, loses a timer or
an event filter changes it; renaming a local or moving code does not.
Each capture runs in a fresh process (it needs its own QApplication).
Accept an intended change with
`uv run python -m tests.ui.wiring_snapshot --update` (Qt lock).
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest
from tests.ui.wiring_snapshot import GOLDEN

ROOT = Path(__file__).parents[2]
QUIT = "/DesktopApp[0]/app.quit "


def capture(tmp_path: Path, plant: str | None = None) -> dict[str, dict[str, object]]:
    out = tmp_path / f"wiring-{plant or 'as-is'}.json"
    command = [sys.executable, "-m", "tests.ui.wiring_snapshot", "--out", str(out)]
    if plant:
        command += ["--plant", plant]
    subprocess.run(
        command,
        cwd=ROOT,
        env={**os.environ, "QT_QPA_PLATFORM": "offscreen"},
        check=True,
        capture_output=True,
        timeout=120,
    )
    return json.loads(out.read_text(encoding="utf-8"))


def differences(
    before: dict[str, dict[str, object]], after: dict[str, dict[str, object]]
) -> list[str]:
    """One line per object or field that differs, naming the object path."""
    lines = []
    for path in sorted(before.keys() | after.keys()):
        old, new = before.get(path), after.get(path)
        if old is None or new is None:
            lines.append(f"{path}: {'added' if old is None else 'gone'}")
            continue
        for field in sorted(old.keys() | new.keys()):
            if field == "receivers":
                signals = old.get(field, {}), new.get(field, {})
                assert isinstance(signals[0], dict) and isinstance(signals[1], dict)
                for signal in sorted(signals[0].keys() | signals[1].keys()):
                    a, b = signals[0].get(signal, 0), signals[1].get(signal, 0)
                    if a != b:
                        lines.append(f"{path} {signal}: {a} -> {b} receivers")
            elif old.get(field) != new.get(field):
                lines.append(f"{path} {field}: {old.get(field)} -> {new.get(field)}")
    return lines


@pytest.fixture(scope="module")
def golden() -> dict[str, dict[str, object]]:
    if not GOLDEN.exists():
        pytest.skip(f"no wiring record for {sys.platform} yet ({GOLDEN.name})")
    return json.loads(GOLDEN.read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def as_is(tmp_path_factory: pytest.TempPathFactory) -> dict[str, dict[str, object]]:
    """A capture of today's wiring in its own process, on any system."""
    return capture(tmp_path_factory.mktemp("wiring"))


def test_the_wiring_is_today_s(
    tmp_path: Path, golden: dict[str, dict[str, object]]
) -> None:
    changed = differences(golden, capture(tmp_path))
    assert not changed, "\n".join(
        [*changed, "If meant: uv run python -m tests.ui.wiring_snapshot --update"]
    )


@pytest.mark.parametrize(
    ("plant", "change"), [("double", "3 -> 4"), ("drop", "3 -> 0")]
)
def test_a_planted_doubled_or_dropped_connect_fails(
    tmp_path: Path, as_is: dict[str, dict[str, object]], plant: str, change: str
) -> None:
    """Against a fresh capture, so it holds on every system, and so it also
    shows two processes give the same record apart from the plant."""
    changed = differences(as_is, capture(tmp_path, plant))
    quits = [line for line in changed if line.startswith(QUIT)]
    assert quits and all(change in line for line in quits), changed
    assert len(changed) == len(quits), changed
