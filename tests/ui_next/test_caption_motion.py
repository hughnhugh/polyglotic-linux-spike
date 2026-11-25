"""The grouped caption opens a row before its glyphs and readings enter."""

from itertools import pairwise

import pytest
from PySide6.QtCore import QPointF, QRectF
from PySide6.QtGui import QFontMetricsF
from PySide6.QtWidgets import QApplication
from tests.ui_next.line_replay import FIXTURES, load, measure

from polyglotic_desktop.core.listening.display import RowKind
from polyglotic_desktop.ui_next.caption_layout import LaidRow
from polyglotic_desktop.ui_next.caption_window import CaptionWindow


def _ink(row: LaidRow, origin: QPointF) -> list[QRectF]:
    """Painted glyphs, including ruby. Line metric boxes can overlap at rest."""
    glyphs = []
    for run in row.layout.lineAt(0).glyphRuns():
        raw_font = run.rawFont()
        for index, position in zip(run.glyphIndexes(), run.positions(), strict=True):
            box = raw_font.boundingRect(index)
            if not box.isEmpty():
                glyphs.append(box.translated(origin + position))
    for marks, font in ((row.above, row.above_font), (row.below, row.below_font)):
        if font is None:
            continue
        for mark in marks:
            metrics = QFontMetricsF(mark.font or font)
            glyphs.append(
                metrics.tightBoundingRect(mark.text).translated(
                    origin + QPointF(mark.x, mark.y)
                )
            )
    return glyphs


@pytest.mark.parametrize("kind", RowKind)
@pytest.mark.parametrize("finished", [False, True], ids=["live", "finished"])
@pytest.mark.parametrize("reduced", [False, True], ids=["glide", "step"])
def test_grouped_wrap_opens_room_before_entering(
    qapp: QApplication, kind: RowKind, finished: bool, reduced: bool
) -> None:
    stream = load(FIXTURES / "e.json")
    initial, growth = stream["events"]
    initial["clauses"][0].update(said="过桥", words=["过桥"], reading=["guò", "qiáo"])
    growth["t"] = 2
    growth["live"] = not finished
    said = "过桥" * (9 if kind is RowKind.ORIGINAL else 1)
    growth["clauses"][0].update(
        said=said,
        words=[said],
        reading=["guò", "qiáo"] * (len(said) // 2),
        translation="Cross the bridge"
        + (" and walk down the street." if kind is RowKind.TRANSLATION else ""),
    )
    before = {}
    frames = []
    opacity = []
    readings = []

    def observe(window: CaptionWindow, now: float) -> None:
        if not window.canvas.placed:
            return
        rows = {}
        ink = {}
        for _, laid, rect in window.canvas.placed:
            for row in laid.rows:
                part = row.layout.lineAt(0)
                box = part.naturalTextRect().translated(rect.x(), rect.y() + row.top)
                box.adjust(0, -row.band, 0, row.below_band)
                key = row.row.kind, row.visual_line
                rows[key] = box
                ink[key] = _ink(row, QPointF(rect.x(), rect.y() + row.top))
                if now >= growth["t"] and row.row.kind is kind and row.visual_line == 1:
                    opacity.append(row.arrival_opacity)
                    if kind is RowKind.ORIGINAL:
                        assert row.above and row.band
                        readings.append(
                            (
                                rect.x() + row.above[0].x,
                                row.above[0].y + rect.y() + row.top,
                            )
                        )
        if now < growth["t"]:
            before.update(rows)
        else:
            frames.append(rows)
            added = kind, 1
            for other in ink.keys() - {added}:
                assert not any(
                    a.intersects(b) for a in ink[added] for b in ink[other]
                ), (now, added, other)

    measure(stream, qapp, observe=observe, reduced=reduced)
    rest = frames[-1]
    added = (kind, 1)
    assert rest.keys() - before.keys() == {added}
    pitch = rest[added].top() - rest[kind, 0].top()
    assert pitch > 0
    for key, old in before.items():
        rise = pitch if rest[key].top() < rest[added].top() else 0.0
        assert old.top() - rest[key].top() == pytest.approx(rise, abs=1)
    xs = []
    for rows in frames:
        incoming = rows[added]
        assert incoming.top() == pytest.approx(rest[added].top(), abs=0.02)
        xs.append(incoming.left())
    if readings:
        at_rest, y = readings[-1]
        assert all(
            mark_x - at_rest == pytest.approx(x - xs[-1], abs=0.02)
            and mark_y == pytest.approx(y, abs=0.02)
            for x, (mark_x, mark_y) in zip(xs, readings, strict=True)
        )
    if reduced:
        assert all(o == 1.0 for o in opacity)
        assert all(rows == rest for rows in frames)
    else:
        assert opacity[0] == 0 and opacity[-1] == 1
        assert any(0 < o < 1 for o in opacity)
        assert all(a <= b for a, b in pairwise(opacity))
        assert xs[0] >= stream["window"]["width"] - 20
        assert all(a >= b for a, b in pairwise(xs))
        assert any(xs[0] > x > xs[-1] for x in xs)
        assert frames[0][kind, 0].top() == pytest.approx(before[kind, 0].top())
        for rows in frames:
            if rows[added].left() < xs[0]:
                assert rows[kind, 0].top() == pytest.approx(
                    rest[kind, 0].top(), abs=0.02
                )


def test_new_clause_completes_its_entry_through_a_live_revision(
    qapp: QApplication,
) -> None:
    stream = load(FIXTURES / "b.json")
    _, growth = stream["events"]
    growth["t"] = 2
    revision = {
        **growth,
        "t": 2.5,
        "clauses": [
            growth["clauses"][0],
            {**growth["clauses"][1], "translation": "let's go now."},
        ],
    }
    stream["events"].append(revision)
    frames = []

    def observe(window: CaptionWindow, now: float) -> None:
        if now < growth["t"]:
            return
        _, laid, rect = window.canvas.placed[-1]
        rows = {
            (row.row.clause, row.row.kind): row.layout.lineAt(0)
            .naturalTextRect()
            .translated(rect.x(), rect.y() + row.top)
            for row in laid.rows
        }
        frames.append(rows)

    measure(stream, qapp, observe=observe)
    for kind in RowKind:
        key = 1, kind
        boxes = [rows[key] for rows in frames]
        assert all(box.top() == pytest.approx(boxes[-1].top()) for box in boxes)
        assert boxes[0].left() > boxes[-1].left()
        assert any(boxes[0].left() > box.left() > boxes[-1].left() for box in boxes)
        assert all(a.left() >= b.left() for a, b in pairwise(boxes))
        for rows in frames:
            assert all(
                not rows[key].intersects(box)
                for other, box in rows.items()
                if other != key
            )
