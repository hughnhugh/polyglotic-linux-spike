"""The deterministic listener-to-surfaces-and-Learning trace (display-1b)."""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest
from tests.ui_next.feed_surface_trace import PLAYER, SPEAKER, schedule, trace

ROOT = Path(__file__).parents[2]
EXPECTED = ROOT / "tests" / "ui_next" / "feed_surface_trace.json"


def _worker(mutation: str = "") -> list[dict[str, Any]]:
    environment = {
        **os.environ,
        "QT_QPA_PLATFORM": "offscreen",
        "TRACE_MUTATION": mutation,
    }
    result = subprocess.run(
        [sys.executable, "-m", "tests.ui_next.feed_surface_trace"],
        cwd=ROOT,
        env=environment,
        check=True,
        capture_output=True,
        text=True,
        timeout=30,
    )
    return json.loads(result.stdout)


def _first_difference(
    expected: list[dict[str, Any]], actual: list[dict[str, Any]]
) -> None:
    for position in range(max(len(expected), len(actual))):
        wanted = expected[position] if position < len(expected) else "<end of trace>"
        found = actual[position] if position < len(actual) else "<end of trace>"
        if wanted != found:
            names = [
                event.get("event")
                for event in (wanted, found)
                if isinstance(event, dict)
            ]
            name = "learning.delivery" if "learning.delivery" in names else names[0]
            pytest.fail(
                f"first wrong event {position}: {name}; expected {wanted!r}, got {found!r}"
            )


def test_the_same_trace_comes_out_twice_in_separate_processes() -> None:
    assert _worker() == _worker()


def test_the_trace_is_the_checked_in_feed_to_surface_oracle() -> None:
    expected = json.loads(EXPECTED.read_text(encoding="utf-8"))
    _first_difference(expected, _worker())


@pytest.mark.parametrize(
    ("mutation", "named_event"),
    [
        ("dropped-finish", "learning.delivery"),
        ("shifted-span", "learning.delivery"),
        ("repeated-learning", "learning.delivery"),
    ],
)
def test_a_planted_fault_fails_at_and_names_the_first_wrong_event(
    mutation: str, named_event: str
) -> None:
    expected, changed = _worker(), _worker(mutation)
    with pytest.raises(
        pytest.fail.Exception, match=rf"first wrong event \d+: {named_event}"
    ):
        _first_difference(expected, changed)


def _for_source(events: list[dict[str, Any]], source: object) -> list[dict[str, Any]]:
    name = str(source)
    return [event for event in events if event.get("source") == name]


@pytest.mark.xfail(
    strict=True,
    reason=(
        "joined-window and Video snapshots include the other source's current line, "
        "so their intermediate trace depends on which overlapping update arrived first"
    ),
)
def test_neither_sources_trace_depends_on_which_overlapping_update_arrives_first(
    qapp: object,
) -> None:
    speaker_first = trace(schedule(SPEAKER))
    player_first = trace(schedule(PLAYER))
    assert _for_source(speaker_first, SPEAKER) == _for_source(player_first, SPEAKER)
    assert _for_source(speaker_first, PLAYER) == _for_source(player_first, PLAYER)
