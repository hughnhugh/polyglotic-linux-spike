"""The glyph positions of a writing subtitle, between recorder frames."""

from dataclasses import replace
from itertools import pairwise
from unittest.mock import Mock

import pytest
from PySide6.QtCore import QPointF, QRectF
from PySide6.QtGui import QFont, QTextLayout, QTextOption
from PySide6.QtWidgets import QApplication

from polyglotic_desktop.core.listening.display import CaptionRow, RowKind
from polyglotic_desktop.ui_next.caption_layout import (
    LaidLine,
    LaidRow,
    char_under,
    panned_row,
    visible_row,
)
from polyglotic_desktop.ui_next.subtitle_motion import _Move, _Pan, _Words
from polyglotic_desktop.ui_next.subtitle_page import (
    SubtitlePage,
    _keep_above,
    _Part,
    _parts,
    _Reading,
    _reading_parts,
    _resume_parts,
    _slots,
)
from polyglotic_desktop.ui_next.views.card_window_defaults import BEAT_SEC
from polyglotic_desktop.ui_next.views.cards import GLIDE_FASTEST


def wrapped(text: str, width: int) -> LaidRow:
    font = QFont("Segoe UI")
    font.setPixelSize(18)
    layout = QTextLayout(text, font)
    option = QTextOption()
    option.setWrapMode(QTextOption.WrapMode.WrapAtWordBoundaryOrAnywhere)
    layout.setTextOption(option)
    layout.beginLayout()
    height = 0.0
    while (line := layout.createLine()).isValid():
        line.setLineWidth(width)
        line.setPosition(QPointF(0.0, height))
        height += line.height()
    layout.endLayout()
    return LaidRow(CaptionRow(text, RowKind.ORIGINAL, None, 0, True), layout, 0, 0)


def test_only_the_word_opening_a_new_line_slides_down(qapp: QApplication) -> None:
    width = 101
    row = wrapped("one two three four five six seven eight", width)
    assert row.layout.lineCount() >= 2
    words = _Words.schedule(row, lambda run: [(0, len(run))], 0.0, None, None)
    start = row.layout.lineAt(1).textStart()
    at = next(t for t, end in zip(words.times, words.ends, strict=True) if end > start)
    final_y = row.layout.lineAt(1).y()
    positions = []
    for frame in range(11):
        visible, _, _ = words.draw(row, at + BEAT_SEC.value * frame / 10, width, True)
        assert visible is not None
        assert visible.layout.lineAt(0).position() == row.layout.lineAt(0).position()
        positions.append(visible.layout.lineAt(1).y())
    assert positions[0] < positions[1] < positions[-1] == final_y
    speeds = [(b - a) * 10 / BEAT_SEC.value for a, b in pairwise(positions)]
    assert max(speeds) <= GLIDE_FASTEST.value
    assert speeds[0] < max(speeds) and speeds[-1] < max(speeds)


def test_long_word_pans_left_without_clipping_or_splitting_a_grapheme(
    qapp: QApplication,
) -> None:
    width = 140
    row = wrapped("extraordinarily" * 4, width)
    words = _Words.schedule(row, lambda run: [(0, len(run))], 0.0, None, None)
    assert words.unbroken
    first_line = row.layout.lineAt(0)
    positions = []
    for frame in range(100):
        at = frame / 100
        shown, _, _ = words.draw(row, at, width, True)
        assert shown is not None
        line = shown.layout.lineAt(0)
        assert line.naturalTextRect().right() <= width + 0.5
        positions.append(line.x())
        if len(shown.row.text) >= first_line.textLength():
            break
    assert positions[0] > positions[-1] == 0
    assert 0 < max((a - b) * 100 for a, b in pairwise(positions)) <= GLIDE_FASTEST.value
    emoji = wrapped("👩‍🚀" * 24, width)
    words = _Words.schedule(emoji, lambda run: [(0, len(run))], 0.0, None, None)
    assert words.ends == tuple(range(len("👩‍🚀"), len(emoji.row.text) + 1, len("👩‍🚀")))


def test_later_page_lookup_and_selection_use_original_character_offsets(
    qapp: QApplication,
) -> None:
    row = wrapped("first page then a 🐈 finds its way home", 115)
    text = row.row.text
    line = row.layout.lineForTextPosition(
        len(text[: text.index("🐈")].encode("utf-16-le")) // 2
    )
    first = len(text.encode("utf-16-le")[: 2 * line.textStart()].decode("utf-16-le"))
    end = len(
        text.encode("utf-16-le")[: 2 * (line.textStart() + line.textLength())].decode(
            "utf-16-le"
        )
    )
    cut = visible_row(row, first, end, QPointF())
    assert cut.start == first > 0
    cat = text.index("🐈")
    boxes = cut.rectangles(cat, cat + 1)
    assert len(boxes) == 1
    hit = char_under([(cut, QPointF())], boxes[0].center())
    assert hit is not None and hit[-1] == cat
    assert not cut.rectangles(0, first)


def test_page_turn_keeps_a_clause_with_its_translation_when_the_pair_fits(
    qapp: QApplication,
) -> None:
    rows = []
    for i, text in enumerate(("First.", "Premier.", "Next.", "Ensuite.")):
        row = wrapped(text, 180)
        height = row.layout.lineAt(0).height()
        kind = RowKind.TRANSLATION if i % 2 else RowKind.ORIGINAL
        rows.append(
            replace(
                row,
                row=replace(row.row, kind=kind, clause=i // 2),
                index=i,
                top=i * height,
            )
        )
    pages = _parts(LaidLine(tuple(rows), 4 * height), 3 * height)
    assert [[row.row.text for row in part.layout.rows] for part in pages] == [
        ["First.", "Premier."],
        ["Next.", "Ensuite."],
    ]


def test_overflowing_translation_turns_pages_under_a_readable_original(
    qapp: QApplication,
) -> None:
    original = wrapped("Read this.", 140)
    target = wrapped("une traduction qui prend plusieurs lignes pour finir", 140)
    band = original.layout.lineAt(0).height()
    target = replace(
        target, row=replace(target.row, kind=RowKind.TRANSLATION), index=1, top=band
    )
    laid = LaidLine((original, target), band + target.layout.boundingRect().height())
    pages = _reading_parts(laid, 2 * band)
    assert len(pages) > 1
    shown: list[str] = []
    for page in pages:
        said, meant = page.layout.rows
        assert said.row.text == original.row.text
        assert said.top == 0 and meant.top == band
        assert meant.layout.font() == target.layout.font()
        assert page.seconds > 0
        if not shown or shown[-1] != meant.row.text:
            shown.append(meant.row.text)
    assert "".join(shown) == target.row.text


def test_page_separator_cannot_push_ink_past_the_right_edge(qapp: QApplication) -> None:
    word = wrapped("first", 200)
    width = int(word.layout.lineAt(0).naturalTextWidth()) + 1
    row = wrapped("first rest", width)
    height = row.layout.lineAt(0).height()
    pages = _parts(
        LaidLine((row,), row.layout.boundingRect().height(), width=width), height
    )
    first, second = (page.layout.rows[0] for page in pages)
    assert first.layout.lineAt(0).naturalTextRect().right() <= width
    assert first.row.text.rstrip() == "first"
    assert second.start == len("first ") and second.row.text == "rest"


def test_one_pixel_reflow_keeps_a_readable_baseline_only_if_it_fits() -> None:
    position = QPointF(0, 37)
    move = _Move(position, position, 0.0, 0.0)
    assert move.stable_y(36, 20, 50) == 37
    assert move.stable_y(36, 20, 36) == 36
    assert move.stable_y(32, 20, 50) == 32


def test_retained_original_keeps_reading_while_the_translation_turns(
    qapp: QApplication,
) -> None:
    original = wrapped("This original takes time to read.", 300)
    target = wrapped("plusieurs mots pour la seconde ligne de la traduction", 85)
    band = original.layout.lineAt(0).height()
    target = replace(
        target, row=replace(target.row, kind=RowKind.TRANSLATION), index=1, top=band
    )
    pair = LaidLine((original, target), band + target.layout.boundingRect().height())
    pages = _reading_parts(pair, 2 * band)
    original_pages = _parts(LaidLine((original,), band), band)
    translation_pages = _parts(
        LaidLine((replace(target, top=0),), target.layout.boundingRect().height()), band
    )
    assert len(translation_pages) > 1
    # Each side gets its own reading interval and page breaks concurrently.
    expected = max(
        sum(part.seconds + BEAT_SEC.value for part in side)
        for side in (original_pages, translation_pages)
    )
    assert sum(part.seconds for part in pages) == pytest.approx(expected)


def test_reflow_continues_after_the_words_already_read(qapp: QApplication) -> None:
    said = wrapped("Read this.", 240)
    target = wrapped("one two three", 240)
    target = replace(target, row=replace(target.row, kind=RowKind.TRANSLATION))

    def part(start: int, end: int) -> _Part:
        translation = visible_row(target, start, end, QPointF())
        return _Part(LaidLine((said, translation), 60), 2.0)

    narrow = (part(0, 4), part(4, 8), part(8, 13))
    wide = (part(0, 8), part(8, 13))
    # The unchanged original can keep its place while the two earlier
    # translation fragments become one line. An unread word still blocks it.
    assert _resume_parts(narrow, 2, False, wide) == (1, True)
    assert _resume_parts(narrow, 1, False, wide) == (0, True)
    assert _resume_parts(narrow, 0, False, wide) == (0, False)


def test_waiting_caption_begins_only_when_the_previous_translation_can_stay(
    qapp: QApplication,
) -> None:
    said = wrapped("Original", 240)
    height = said.layout.lineAt(0).height()
    english = replace(wrapped("Translation", 240), index=1, top=height)
    english = replace(english, row=replace(english.row, kind=RowKind.TRANSLATION))
    pair = LaidLine((said, english), 2 * height)
    page = _Part(pair, 5, includes_turn=True, original_lead=2)
    reading = _Reading(1, None, parts=(page,), until=10)
    current, waiting = Mock(key=1), Mock(key=2)
    engine = Mock()
    engine.laid.return_value = pair
    painted = [(current, pair, QRectF(0, 0, 240, 2 * height))]
    view = SubtitlePage()

    def start(now: float) -> bool:
        return view._next_below(
            [current, waiting], reading, engine, 240, 1, 0, 3 * height, 0, now, painted
        )

    # A single successor may arrive after this page has already started.
    assert not start(7) and view.due == 8
    assert start(8) and view.reading is not None
    assert view.reading.key == 2 and view.reading.above_read_until >= 10
    assert [row.row.kind for row in view.reading.above[0][1].rows] == [
        RowKind.TRANSLATION
    ]
    assert view.reading.delays == (0.0, 2.0)


def test_waiting_pair_uses_clear_space_without_completing_the_current_page(
    qapp: QApplication,
) -> None:
    said = wrapped("Original", 240)
    height = said.layout.lineAt(0).height()
    english = replace(wrapped("Translation", 240), index=1, top=height)
    english = replace(english, row=replace(english.row, kind=RowKind.TRANSLATION))
    pair = LaidLine((said, english), 2 * height)
    current, waiting = Mock(key=1), Mock(key=2)
    engine = Mock()
    engine.laid.return_value = pair
    reading = _Reading(1, None, parts=(_Part(pair, 5),), until=10, inset=2 * height)
    box = QRectF(0, 2 * height, 240, 2 * height)
    view = SubtitlePage()
    view.reading = reading
    before = current, pair, box

    def show(room: float):
        return view._waiting_below(
            [current, waiting], reading, before, engine, 240, 1, 0, room, 0, 8
        )

    assert show(3 * height) == before and view.waiting_slot is None
    reading.parts = (_Part(pair, 5),) * 3
    assert show(4 * height) == before and view.waiting_slot is None
    reading.index = 1
    upper = show(4 * height)
    assert upper[1] is pair and upper[2].y() == 0
    assert view.waiting_slot is not None and view.waiting_slot[0] is waiting
    assert upper[2].bottom() <= view.waiting_slot[2].top()
    assert view.reading is reading and reading.until >= 10
    until = reading.until
    show(4 * height)
    assert reading.until == until


def test_previous_translation_stays_only_if_the_incoming_pair_fits(
    qapp: QApplication,
) -> None:
    said = wrapped("Read the original.", 240)
    height = said.layout.lineAt(0).height()
    meant = replace(wrapped("Read this next.", 240), index=1, top=height)
    meant = replace(meant, row=replace(meant.row, kind=RowKind.TRANSLATION), start=6)
    pair = LaidLine((said, meant), 2 * height)
    assert _keep_above(pair, pair, 4 * height, gap=height) == (pair, 2 * height)
    kept = _keep_above(pair, pair, 3 * height, gap=height)
    assert kept is not None
    previous, inset = kept
    assert previous.height == inset == height
    assert previous.rows == (replace(meant, top=0),)
    assert _keep_above(pair, pair, 3 * height - 1, gap=height) is None


def test_panned_graphemes_keep_their_full_size_and_source_coordinates(
    qapp: QApplication,
) -> None:
    row = wrapped("one two three four five six seven eight", 900)
    line = row.layout.lineAt(0)
    width = 101
    for offset in (0, -5, -22, -79, width - line.naturalTextWidth()):
        visible = panned_row(row, offset, width)
        assert visible is not None
        assert visible.layout.font() == row.layout.font()
        text = visible.row.text
        assert row.row.text[visible.start : visible.start + len(text)] == text
        ink = visible.layout.lineAt(0).naturalTextRect()
        assert ink.left() >= -0.5
        assert ink.right() <= width + 0.5
        assert char_under([(visible, QPointF())], ink.center()) is not None
    assert visible is not None
    assert visible.row.text.endswith("eight")
    assert visible.start > 0


def test_successive_new_words_keep_the_pan_moving_within_its_speed_limit() -> None:
    pan = _Pan(0, 0)
    speed, dt = 200.0, 0.02
    positions = []
    for frame in range(150):
        goal = -min(180, (1 + frame // 9) * 36)
        pan.follow(goal, frame * dt, speed, True)
        positions.append(pan.x)
    steps = [a - b for a, b in pairwise(positions)]
    assert positions[-1] == -180
    assert min(steps) >= 0
    assert max(steps) <= speed * dt + 1e-6
    assert 0 < steps[0] < max(steps)
    assert 0 < min(step for step in steps[-100:] if step) < max(steps)
    assert steps[-1] == 0


def test_unequal_marked_pairs_use_the_whole_height_in_consecutive_order() -> None:
    assert _slots([90, 170], 280, 10, 2) == [(0, 95), (105, 175)]
    # The short first pair cannot substitute for the middle one that left.
    assert _slots([50, 190, 140], 300, 10, 3) == [(0, 300)]
    assert _slots([90], 300, 10, 2) == [(155, 145)]
