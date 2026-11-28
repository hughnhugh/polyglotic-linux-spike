import json
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any, cast

import pytest
from tools.proof.model import Evidence
from tools.proof.plugins import PicturesPlugin, ReplayPlugin, compare_evidence

from tools.proof import harness


class FakePlugin:
    name = "replay"

    def __init__(
        self, results: list[Evidence], name: str = "replay", rule: str = "replay.frame"
    ) -> None:
        self.results = iter(results)
        self.name = name
        self.rule = rule

    def collect(
        self, checkout: Path, scratch: Path, plant: str | None = None
    ) -> Evidence:
        del plant
        del checkout, scratch
        return next(self.results)

    def compare(self, base: Evidence, head: Evidence):
        return compare_evidence(base, head, self.rule)

    def noise_control(self, recorded: Evidence):
        return self, recorded


@contextmanager
def fake_worktree(root: Path, revision: str, target: Path) -> Iterator[Path]:
    del root, revision
    target.mkdir()
    yield target


def evidence(digest: str, frame: int = 12) -> Evidence:
    return Evidence("replay", 1, {"lines/a@panel": ((frame, digest),)})


def test_self_diff_reuses_recording_and_writes_identical_reports(
    tmp_path: Path, monkeypatch
) -> None:
    monkeypatch.setattr(harness, "worktree", fake_worktree)
    monkeypatch.setattr(harness, "_same_commit", lambda *_args: True)
    plugin = FakePlugin([evidence("same")] * 2)

    code, result = harness.run(tmp_path, "base", "head", [plugin], tmp_path / "out")

    assert code == 0
    assert result["status"] == "identical"
    assert result["control_runs"] == 2
    assert result["self_diff_runs"] == 1
    assert (
        json.loads((tmp_path / "out" / "proof.json").read_text("utf-8"))["status"]
        == "identical"
    )
    assert "repeated-base control was quiet" in (
        tmp_path / "out" / "proof.md"
    ).read_text("utf-8")


def test_noisy_control_wins_over_head_differences(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(harness, "worktree", fake_worktree)
    monkeypatch.setattr(harness, "_same_commit", lambda *_args: False)
    plugin = FakePlugin(
        [
            evidence("base"),
            evidence("head", 14),
            evidence("noise", 13),
        ]
    )

    code, result = harness.run(tmp_path, "base", "head", [plugin], tmp_path / "out")

    assert code == 1
    assert result["status"] == "noisy"
    assert result["differences"] == [
        {
            "what": "replay",
            "fixture": "lines/a@panel",
            "frame": 12,
            "rule": "replay.frame",
            "detail": "fingerprint changed",
        }
    ]


@pytest.mark.parametrize(
    ("fault", "plugin", "expected_fixture", "rule"),
    [
        (
            "nudge",
            ReplayPlugin(("lines/motion@panel+narrow",)),
            "lines/motion@panel+narrow",
            "replay.frame",
        ),
        (
            "fall",
            ReplayPlugin(("lines/motion@panel+narrow",)),
            "lines/motion@panel+narrow",
            "replay.frame",
        ),
        (
            "colour",
            PicturesPlugin(("movement.words-never-fall.png",)),
            "movement.words-never-fall.png",
            "pictures.pixels",
        ),
    ],
)
def test_real_rendered_fault_report_names_fixture_frame_and_rule(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    fault: str,
    plugin: ReplayPlugin | PicturesPlugin,
    expected_fixture: str,
    rule: str,
) -> None:
    root = Path(__file__).resolve().parents[3]

    @contextmanager
    def current_tree(_root: Path, _revision: str, _target: Path) -> Iterator[Path]:
        yield root

    monkeypatch.setattr(harness, "worktree", current_tree)
    monkeypatch.setattr(harness, "_same_commit", lambda *_args: True)

    code, result = harness.run(
        root,
        "base",
        "head",
        [plugin],
        tmp_path / "out",
        plants={plugin.name: fault},
    )

    assert code == 1
    assert result["status"] == "different"
    difference = cast(list[dict[str, Any]], result["differences"])[0]
    assert difference["fixture"] == expected_fixture
    assert isinstance(difference["frame"], int)
    assert difference["frame"] > 0
    assert difference["rule"] == rule
    report = (tmp_path / "out" / "proof.md").read_text("utf-8")
    assert expected_fixture in report
    assert f"| {difference['frame']} |" in report
    assert rule in report


def test_markdown_escapes_fixture_pipes_and_names_windows_target() -> None:
    result: dict[str, object] = {
        "status": "different",
        "runtime_seconds": 1.25,
        "differences": [
            {
                "what": "replay",
                "fixture": "line|variant",
                "frame": 4,
                "rule": "replay.frame",
                "detail": "fingerprint changed",
            }
        ],
    }

    report = harness._markdown(result)

    assert "`line\\|variant`" in report
    assert "under 10 minutes on GitHub's Windows machine" in report
