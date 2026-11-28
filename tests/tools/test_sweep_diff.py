"""The sweep diff (859's N6, S6 b): the same sweep twice is no difference;
a control that no longer puts its setting back is named."""

import copy
import json
from pathlib import Path
from typing import Any

import pytest

from tools import sweep_diff

SWEEP: dict[str, Any] = {
    "changes": [
        {
            "where": "settings look",
            "what": "caption edge: shadow",
            "stored": {"caption_edge": "shadow"},
            "effect": {},
            "log": ["2026-11-27 18:56:22,001 INFO caption windows shown again"],
            "error_boxes": [],
            "picture": "settings-look-9.png",
        },
        {
            "where": "settings look",
            "what": "caption edge: none",
            "stored": {"caption_edge": "none"},
            "effect": {},
            "log": [],
            "error_boxes": [],
            "picture": "settings-look-10.png",
        },
    ],
    "notes": [],
    "first_stored": {"caption_edge": "none"},
    "seconds": {"settings look": 11.9},
}


def _run(tmp_path: Path, before: object, after: object) -> int:
    (tmp_path / "a.json").write_text(json.dumps(before), encoding="utf-8")
    (tmp_path / "b.json").write_text(json.dumps(after), encoding="utf-8")
    return sweep_diff.main([str(tmp_path / "a.json"), str(tmp_path / "b.json")])


def test_the_same_sweep_with_other_times_logs_and_pictures_is_no_difference(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    again = copy.deepcopy(SWEEP)
    again["seconds"] = {"settings look": 14.2}
    again["changes"][0]["log"] = [
        "2026-11-27 19:20:00,000 INFO caption windows shown again"
    ]
    again["changes"][1]["picture"] = "settings-look-11.png"
    assert _run(tmp_path, SWEEP, again) == 0
    assert capsys.readouterr().out == "no differences\n"


def test_a_planted_put_back_break_names_the_control_and_setting(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    broken = copy.deepcopy(SWEEP)
    broken["changes"][1]["stored"] = {}  # changing back no longer stores "none"
    assert _run(tmp_path, SWEEP, broken) == 1
    out = capsys.readouterr().out
    assert "sections.settings look.stored.caption_edge" in out
    assert '"none" -> "shadow"' in out


def test_one_extra_change_does_not_shift_the_rest(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    more: dict[str, Any] = copy.deepcopy(SWEEP)
    more["changes"].insert(
        0, {"where": "caption popover", "what": "text size: 1", "stored": {}}
    )
    assert _run(tmp_path, SWEEP, more) == 1
    lines = capsys.readouterr().out.splitlines()
    assert lines[-1] == "1 difference(s)"
    assert lines[0].startswith("sections.caption popover: <missing> -> ")


def test_volatile_fields_are_named_with_a_reason() -> None:
    assert set(sweep_diff.VOLATILE) == {"seconds", "log", "picture"}
    assert all(reason for reason in sweep_diff.VOLATILE.values())


def test_a_save_landing_in_the_next_control_is_no_difference(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """The debounced save of one control recorded under its neighbour."""
    late = copy.deepcopy(SWEEP)
    late["changes"][0]["stored"] = {}
    late["changes"][1]["stored"] = {"caption_edge": "none"}
    early = copy.deepcopy(SWEEP)
    early["changes"][0]["stored"] = {"caption_edge": ["none", "shadow"]}
    early["changes"][1]["stored"] = {"caption_edge": ["shadow", "none"]}
    shifted = copy.deepcopy(early)
    shifted["changes"][0]["stored"] = {"caption_edge": ["none", "outline"]}
    shifted["changes"][1]["stored"] = {"caption_edge": ["outline", "none"]}
    assert _run(tmp_path, SWEEP, late) == 0
    assert _run(tmp_path, early, shifted) == 0
    capsys.readouterr()
