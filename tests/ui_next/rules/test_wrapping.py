"""The wrapping family's rules, each held on a real window (see
`test_movement.py` for how a rule's test and its planted break are marked)."""

from typing import Any
from unittest.mock import patch

import pytest
from PySide6.QtWidgets import QApplication
from tools.scene_replay import drive, plants, properties, streams
from tools.scene_replay.frames import Frame
from tools.scene_replay.rulebook import breaks, pins

from polyglotic_desktop.ui_next.views.flow import Flow


def replay(stream: str, setup: str, plant: str | None = None) -> list[Frame]:
    with plants.planted(plant):
        return list(drive.play(streams.load(stream), drive.Setup.named(setup)))


SINGLE = [
    "panel+narrow",
    "panel+narrow+paired",
    "panel+readings+narrow",
    "zones+narrow",
    "cards+narrow",
    "joined+narrow",
    "video-instant+narrow",
    "video-scrolling+narrow",
]


@pins("wrapping.every-row-is-a-single-line")
@pytest.mark.parametrize("setup", SINGLE)
def test_every_row_is_a_single_line(qapp: QApplication, setup: str) -> None:
    frames = replay("rules/one-long-line", setup)
    assert any(frame.rows for frame in frames)
    assert properties.single_line(frames) == []


@pins("wrapping.every-row-is-a-single-line")
def test_a_long_caption_carries_on_in_rows_of_its_own(qapp: QApplication) -> None:
    last = replay("rules/one-long-line", "panel+narrow")[-1]
    originals = [row for row in last.rows if row.kind == "original"]
    assert len(originals) > 1, "the caption fits one row: the stream is too short"
    assert len({row.top for row in originals}) == len(originals)


@pins("wrapping.every-row-is-a-single-line")
def test_the_transcript_is_where_a_row_does_wrap(qapp: QApplication) -> None:
    """The rule's one exception, pinned so it is seen when it goes: the
    transcript's rows are wrapped by Qt inside the row."""
    assert properties.single_line(replay("rules/one-long-line", "transcript+narrow"))


@breaks("wrapping.every-row-is-a-single-line")
def test_a_row_left_wrapped_is_seen(qapp: QApplication) -> None:
    broken = properties.single_line(
        replay("rules/one-long-line", "panel+narrow", "wrap")
    )
    assert broken and "lines" in broken[0].what


def _rebroken(
    frames: list[Frame], *, line: int | None = 1, kind: str = "original"
) -> list[tuple[int, tuple[object, ...]]]:
    """Surviving characters whose newest layout puts them on another row
    (`line` None: any caption's)."""
    found = []
    before: dict[tuple[object, ...], int] = {}
    for frame in frames:
        now: dict[tuple[object, ...], int] = {
            (
                row.surface,
                row.key,
                row.kind,
                row.clause,
                char.index,
                char.glyph,
            ): row.visual
            for row in frame.rows
            if row.opacity > 0
            and (line is None or row.key == line)
            and row.kind == kind
            for char in row.chars
        }
        for key in before.keys() & now.keys():
            if before[key] != now[key]:
                found.append((frame.n, key))
        before = now
    return found


@pins("wrapping.live-breaks-follow-the-newest-text")
@pytest.mark.parametrize("setup", ["panel+narrow+paired", "joined+narrow+paired"])
def test_a_live_captions_breaks_follow_its_newest_text(
    qapp: QApplication, setup: str
) -> None:
    # Any caption of the stream: which one rebreaks depends on the platform's
    # fonts. On GitHub's Windows machine caption 1 keeps its breaks in
    # joined+narrow+paired (polyglotic-hq 1033, 2026-11-28), while a later one
    # rebreaks; the rule is about whichever caption is live.
    assert _rebroken(replay("lines/motion", setup), line=None)


@breaks("wrapping.live-breaks-follow-the-newest-text")
def test_frozen_live_breaks_are_seen(qapp: QApplication) -> None:
    """Plant 827's specified-but-unused frozen breaks in the running layout."""
    real = Flow.compose
    kept: dict[int, tuple[tuple[int, int], ...]] = {}

    def frozen(self: Flow, *args: Any, **kwargs: Any) -> Any:
        if kwargs.get("frozen") is None:
            kwargs["frozen"] = kept.get(id(self), ())
        flowed = real(self, *args, **kwargs)
        kept[id(self)] = flowed.frozen
        return flowed

    with patch.object(Flow, "compose", frozen):
        frames = replay("lines/motion", "panel+narrow+paired")
    assert not _rebroken(frames), "827's frozen-break plant did not freeze the fixture"
