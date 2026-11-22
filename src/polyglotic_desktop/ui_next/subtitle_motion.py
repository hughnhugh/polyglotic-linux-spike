"""Visible words and motion between Video's measured subtitle slots."""

from bisect import bisect_right
from collections.abc import Callable
from dataclasses import dataclass, field, replace
from math import copysign, hypot, sqrt

from PySide6.QtCore import QPointF, QRectF, QTextBoundaryFinder
from PySide6.QtGui import QTextOption

from polyglotic_desktop.core.listening.captions import Clause, Language
from polyglotic_desktop.core.listening.display import RowKind
from polyglotic_desktop.core.listening.history import Caption
from polyglotic_desktop.core.listening.playout import MIN_GAP_SEC, Split, word_beats
from polyglotic_desktop.ui_next.caption_layout import (
    CaptionLayout,
    LaidLine,
    LaidRow,
    cursor_x,
    panned_row,
    visible_row,
)
from polyglotic_desktop.ui_next.subtitle_page import PlacedSubtitle, ReadBy, bounds
from polyglotic_desktop.ui_next.views.captions import Line
from polyglotic_desktop.ui_next.views.card_window_defaults import (
    BASELINE_TOLERANCE_PX,
    BEAT_SEC,
    PAN_ROOM,
    SPEED_SHARE,
    WRAP_DROP,
)
from polyglotic_desktop.ui_next.views.cards import (
    DEPTH_SEC,
    EASE_PEAK,
    GLIDE_FASTEST,
    ease,
)
from polyglotic_desktop.ui_next.views.dwell import (
    AFTER_LAST_WORD_SEC,
    MEANT_PACE,
    MEANT_PACE_SPACED,
    SAID_PACE,
    SAID_PACE_SPACED,
    subtitle_need,
)

RowKey = tuple[int, RowKind, str | None, int]


def _row_key(row: LaidRow) -> RowKey:
    return row.row.clause, row.row.kind, row.row.target or row.row.language, row.start


def _speed() -> float:
    return GLIDE_FASTEST.value * min(SPEED_SHARE.value, 1 / sqrt(2))


def _entry_height(line: Line, laid: LaidLine, height: float) -> float:
    """Reserve a matching side for an unfinished original before using the
    free lower margin. A complete bilingual block has its measured height."""
    if (
        not line.live
        and not line.provisional
        and any(row.row.kind is RowKind.TRANSLATION for row in laid.rows)
    ):
        return height
    longest = max(
        (row.layout.boundingRect().height() for row in laid.rows), default=0.0
    )
    return max(height, 2 * longest)


def _graphemes(text: str) -> tuple[int, ...]:
    """Qt's cursor boundaries, converted from UTF-16 to Python offsets."""
    finder = QTextBoundaryFinder(QTextBoundaryFinder.BoundaryType.Grapheme, text)
    offsets = {0: 0}
    units = 0
    for i, char in enumerate(text, 1):
        units += 1 + (ord(char) > 0xFFFF)
        offsets[units] = i
    ends = []
    while (boundary := finder.toNextBoundary()) >= 0:
        ends.append(offsets[boundary])
    return tuple(ends)


@dataclass
class _Move:
    start: QPointF
    goal: QPointF
    at: float
    seconds: float

    def position(self, now: float) -> QPointF:
        if not self.seconds:
            return self.goal
        return self.start + (self.goal - self.start) * ease(
            (now - self.at) / self.seconds
        )

    def stable_y(self, proposed: float, top: float, bottom: float) -> float:
        """Rounding a new page can change its slot by a pixel. Keep the
        existing baseline when all its ink still fits there."""
        rest = self.goal.y()
        if (
            top <= rest <= bottom
            and abs(proposed - rest) <= BASELINE_TOLERANCE_PX.value
        ):
            return rest
        return proposed

    def retarget(self, goal: QPointF, now: float, delay: float = 0.0) -> None:
        if goal == self.goal and not delay:
            return
        self.start = self.position(now)
        self.goal = goal
        self.at = now + delay
        distance = hypot(goal.x() - self.start.x(), goal.y() - self.start.y())
        self.seconds = max(DEPTH_SEC.value, EASE_PEAK * distance / _speed())


@dataclass
class _Pan:
    x: float
    at: float
    velocity: float = 0.0

    def follow(self, goal: float, now: float, speed: float, animate: bool) -> float:
        """Chase a changing word end without restarting the ease on each update."""
        dt = max(0.0, now - self.at)
        self.at = now
        distance = goal - self.x
        if not animate or not distance:
            self.x, self.velocity = goal, 0.0
            return now
        acceleration = speed / DEPTH_SEC.value
        target = copysign(min(speed, sqrt(2 * acceleration * abs(distance))), distance)
        change = max(-acceleration * dt, min(target - self.velocity, acceleration * dt))
        velocity = max(-speed, min(self.velocity + change, speed))
        step = (self.velocity + velocity) * dt / 2
        if step * distance >= distance * distance:
            self.x, self.velocity = goal, 0.0
            return now
        self.x += step
        self.velocity = velocity
        return now + abs(goal - self.x) / speed + DEPTH_SEC.value


@dataclass
class _Words:
    text: str
    ends: tuple[int, ...]
    times: tuple[float, ...]
    unbroken: bool
    # Only the latest clipped layout is kept, never one per frame.
    stamp: tuple[object, ...] = ()
    visible: LaidRow | None = None

    @classmethod
    def schedule(
        cls,
        row: LaidRow,
        split: Split,
        start: float,
        was: "_Words | None",
        clause: Clause | None,
        width: float | None = None,
    ) -> "_Words":
        text = row.row.text
        ends, offsets = word_beats(text, split, clause)
        unbroken = (
            len(ends) == 1
            and (
                row.layout.lineCount() > 1
                or (width is not None and row.layout.maximumWidth() > width)
            )
            and not any(c.isspace() for c in text.strip())
        )
        interval = MIN_GAP_SEC if unbroken else BEAT_SEC.value
        if unbroken:
            ends = _graphemes(text)
        if not ends and text:
            ends = (len(text),)
        kept = 0
        if was is not None:
            for end, old in zip(ends, was.ends, strict=False):
                if end != old or text[:end] != was.text[:end]:
                    break
                kept += 1
            # A correction to a word already read updates that word. Never
            # rewind a visible sentence to its first different character.
            kept = max(kept, min(len(ends), bisect_right(was.times, start)))
        times = list(was.times[:kept]) if was else []
        first = max(start, times[-1] + interval) if times else start
        for i in range(kept, len(ends)):
            if offsets and not unbroken:
                beat = first + offsets[i] - offsets[kept]
                times.append(max(beat, times[-1] + MIN_GAP_SEC) if times else beat)
            else:
                times.append(first + (i - kept) * interval)
        return cls(text, ends, tuple(times), unbroken)

    def _pan(
        self, row: LaidRow, end: int, now: float, width: float
    ) -> tuple[float, bool]:
        """Start a long token inside the free right margin and ease left
        before its growing end reaches the edge. Completed lines stay put."""
        encoded = self.text.encode("utf-16-le")
        units = len(self.text[:end].encode("utf-16-le")) // 2
        line = row.layout.lineForTextPosition(units - 1)
        first = len(encoded[: 2 * line.textStart()].decode("utf-16-le"))
        stop = len(
            encoded[: 2 * (line.textStart() + line.textLength())].decode("utf-16-le")
        )
        a = bisect_right(self.ends, first)
        b = bisect_right(self.ends, stop) - 1
        if a >= b:
            return 0.0, False
        start = self.times[a]
        rightward = cursor_x(line, line.textStart()) <= cursor_x(
            line, line.textStart() + line.textLength()
        )
        direction = 1.0 if rightward else -1.0
        margin = width * PAN_ROOM.value

        def position(index: int) -> float:
            cursor = len(self.text[: self.ends[index]].encode("utf-16-le")) // 2
            x = cursor_x(line, cursor)
            return x if rightward else width - x

        # Keep the opening still until the growing word approaches the
        # margin, then finish the pan before any glyph would cross it.
        edge = a + bisect_right(range(a, b + 1), width - margin, key=position) - 1
        if edge <= a or now >= self.times[edge]:
            return 0.0, False
        available = self.times[edge] - start
        travel = min(margin, available * _speed() / EASE_PEAK)
        if travel <= 0.0:
            return 0.0, False
        seconds = min(available, max(DEPTH_SEC.value, EASE_PEAK * travel / _speed()))
        share = (now - self.times[edge] + seconds) / seconds
        return direction * travel * (1.0 - ease(share)), share >= 0.0

    def draw(
        self, row: LaidRow, now: float, width: float, animate: bool
    ) -> tuple[LaidRow | None, float | None, bool]:
        count = bisect_right(self.times, now)
        next_word = self.times[count] if count < len(self.times) else None
        if not count:
            return None, next_word, False
        end = self.ends[count - 1]
        if count < len(self.ends):
            # Qt includes trailing spaces in the width of the last visual
            # line, then removes them once the next word wraps. Paint ink
            # through the word itself so an unchanged line keeps its width.
            end = len(self.text[:end].rstrip()) or end
        elapsed = now - self.times[count - 1]
        dy = 0.0
        duration = (
            min(BEAT_SEC.value, next_word - self.times[count - 1])
            if next_word is not None
            else BEAT_SEC.value
        )
        if animate and elapsed < duration and count > 1 and row.layout.lineCount() > 1:
            text = self.text
            before = self.ends[count - 2]
            offset = len(text[:before].encode("utf-16-le")) // 2
            final = len(text[:end].rstrip().encode("utf-16-le")) // 2
            wrapped = row.layout.lineForTextPosition(max(0, final - 1))
            if (
                wrapped.isValid()
                and wrapped.textStart() > 0
                and offset <= wrapped.textStart()
            ):
                distance = min(
                    WRAP_DROP.value * wrapped.height(),
                    duration * _speed() / EASE_PEAK,
                )
                dy = -distance * (1.0 - ease(elapsed / duration))
        dx, sliding = (
            self._pan(row, end, now, width)
            if self.unbroken and animate and row.layout.lineCount() > 1
            else (0.0, False)
        )
        stamp = (row.layout, row.top, end, dx, dy)
        if self.stamp != stamp:
            self.visible = visible_row(row, 0, end, QPointF(dx, dy))
            self.stamp = stamp
        return self.visible, next_word, bool(dy) or sliding


@dataclass
class _Block:
    move: _Move
    complete: bool
    visible_at: float | None = None
    shown: bool = False
    entry_y: float | None = None
    rest_y: float | None = None
    rewrap_at: float | None = None
    read_text: tuple[str, str] = ("", "")
    read_until: float = 0.0
    read_seconds: float = 0.0
    written_at: float = 0.0
    pan_until: float = 0.0
    pan_after: dict[tuple[RowKind, Language | None], float] = field(
        default_factory=dict
    )
    original_until: float = 0.0
    translation_until: float = 0.0
    words: dict[RowKey, _Words] = field(default_factory=dict)

    pans: dict[tuple[RowKind, Language | None], _Pan] = field(default_factory=dict)

    def returning_to_wrap(self, laid: LaidLine) -> bool:
        for row in laid.rows:
            pan = self.pans.get((row.row.kind, row.row.target))
            if pan is not None and (
                row.layout.lineCount() > 1
                or (
                    pan.x
                    and row.layout.textOption().wrapMode()
                    != QTextOption.WrapMode.NoWrap
                )
            ):
                return True
        return False

    def pan(
        self, laid: LaidLine, full: LaidLine, width: float, now: float, animate: bool
    ) -> tuple[LaidLine, bool]:
        """Follow each unwrapped row's newest ink, keeping word lookup at the painted origin."""
        tracks: dict[tuple[RowKind, Language | None], QRectF] = {}
        reverse: dict[tuple[RowKind, Language | None], bool] = {}
        for row in laid.rows:
            layout = row.layout
            if (
                layout.lineCount() != 1
                or layout.textOption().wrapMode() != QTextOption.WrapMode.NoWrap
            ):
                continue
            key = row.row.kind, row.row.target
            line = layout.lineAt(0)
            ink = line.naturalTextRect().translated(layout.position())
            tracks[key] = tracks[key].united(ink) if key in tracks else ink
            reverse.setdefault(
                key, cursor_x(line, line.textLength()) < cursor_x(line, 0)
            )
        endings: dict[tuple[RowKind, Language | None], float] = {}
        for row in full.rows:
            side = row.row.kind, row.row.target
            if side in tracks:
                ink = (
                    row.layout.lineAt(0)
                    .naturalTextRect()
                    .translated(row.layout.position())
                )
                endings[side] = max(endings.get(side, 0.0), ink.right())
        self.pan_until = 0.0
        self.pans = {key: pan for key, pan in self.pans.items() if key in tracks}
        moving = False
        for key, ink in tracks.items():
            tail = min(0.0, width - ink.right())
            # A scheduled next word can start moving its predecessor
            # before it reaches the edge, without overshooting the final tail.
            lead = max(0.0, min(width * PAN_ROOM.value, endings[key] - ink.right()))
            goal = (
                max(-ink.left(), tail)
                if reverse[key]
                else min(0.0, width - ink.right() - lead)
            )
            pan = self.pans.get(key)
            if pan is None:
                pan = self.pans[key] = _Pan(tail if reverse[key] else 0.0, now)
            if animate and goal != pan.x and key not in self.pan_after:
                opening = [
                    visible.row.text
                    for row in full.rows
                    if (row.row.kind, row.row.target) == key
                    and (visible := panned_row(row, pan.x, width)) is not None
                ]
                pace, spaced = (
                    (SAID_PACE, SAID_PACE_SPACED)
                    if key[0] is RowKind.ORIGINAL
                    else (MEANT_PACE, MEANT_PACE_SPACED)
                )
                first = self.visible_at if self.visible_at is not None else now
                self.pan_after[key] = first + subtitle_need(
                    " ".join(opening), pace.value, spaced.value
                )
            if animate and now < self.pan_after.get(key, now):
                # Keep the opening in view long enough to read it before
                # following the tail of a live speech update.
                pan.at = now
                self.pan_until = max(self.pan_until, self.pan_after[key])
                continue
            until = pan.follow(goal, now, _speed(), animate)
            if until > now:
                moving = True
                self.pan_until = max(self.pan_until, until)
        rows = []
        for row in laid.rows:
            pan = self.pans.get((row.row.kind, row.row.target))
            visible = panned_row(row, pan.x, width) if pan is not None else row
            if visible is not None:
                rows.append(visible)
        if len(rows) == len(laid.rows) and all(
            a is b for a, b in zip(rows, laid.rows, strict=True)
        ):
            return laid, moving
        return replace(laid, rows=tuple(rows), card_links=None), moving

    def resting_top(
        self,
        y: float,
        height: float,
        above: float,
        gap: float,
        now: float,
        finished: bool,
    ) -> tuple[float, float | None]:
        """During a pause, move a read block far enough to make room for a
        pair like itself. Keep the entire preceding subtitle visible."""
        if self.rest_y is None and finished and self.visible_at is not None:
            ready = max(
                self.original_until,
                max(self.written_at, self.pan_until) + AFTER_LAST_WORD_SEC.value,
                self.move.at + self.move.seconds,
            )
            if now < ready:
                return y, ready
            self.rest_y = max(above, y - height - gap)
        if self.rest_y is not None:
            y = min(y, max(above, self.rest_y))
        return y, None

    def note_reading(self, laid: LaidLine, now: float) -> None:
        said = " ".join(r.row.text for r in laid.rows if r.row.kind is RowKind.ORIGINAL)
        meant = " ".join(
            r.row.text for r in laid.rows if r.row.kind is RowKind.TRANSLATION
        )
        if self.read_text == (said, meant):
            return
        original = (
            subtitle_need(said, SAID_PACE.value, SAID_PACE_SPACED.value)
            if said
            else 0.0
        )
        translation = (
            subtitle_need(meant, MEANT_PACE.value, MEANT_PACE_SPACED.value)
            if meant
            else 0.0
        )
        first = now if self.visible_at is None else self.visible_at
        self.read_until = max(
            self.read_until,
            first + original + translation,
            now + original if said != self.read_text[0] else first,
            now + translation if meant != self.read_text[1] else first,
        )
        if said:
            first_original = now if not self.read_text[0] else first
            self.original_until = max(
                self.original_until, first_original + BEAT_SEC.value + original
            )
        if meant and meant != self.read_text[1]:
            self.translation_until = max(
                self.translation_until, now + BEAT_SEC.value + translation
            )
        self.read_seconds = original + translation
        self.read_text = said, meant


class SubtitleMotion:
    """Animate retained blocks from their last painted location. The new
    block writes into clear space after the preceding block has vacated it."""

    def __init__(self, caption: Callable[[int], Caption | None]) -> None:
        self._caption = caption
        self._blocks: dict[int, _Block] = {}
        self._viewport: tuple[object, ...] = ()
        self._seen: int | None = None
        self._last: list[PlacedSubtitle] = []
        self._outgoing: dict[int, tuple[PlacedSubtitle, float]] = {}
        self._held_at: float | None = None
        self._paused = 0.0
        self.opacity: dict[int, float] = {}
        self.read_until: float | None = None
        self.due: float | None = None
        self.moving = False

    def deadlines(self, key: int | None) -> ReadBy:
        """The lower word schedule and both reading deadlines, on the window clock."""
        block = self._blocks.get(key) if key is not None else None
        if block is None:
            return ReadBy()
        return ReadBy(
            max(block.written_at, block.pan_until) + self._paused,
            block.original_until + self._paused,
            block.read_until + self._paused,
            block.shown,
            block.translation_until + self._paused,
        )

    def show(
        self,
        slots: list[PlacedSubtitle],
        now: float,
        viewport: tuple[CaptionLayout, int, float, float, float],
        split: Split,
        write: bool,
        animate: bool,
        settle: bool,
        gap: float,
        held: bool,
        showing_next: bool = False,
    ) -> list[PlacedSubtitle]:
        self.due = None
        self.moving = False
        _, width, _, top, foot = viewport
        resized = viewport != self._viewport
        same_width = self._viewport[:3] == viewport[:3]
        self._viewport = viewport
        if held and animate and self._last and not resized:
            if self._held_at is None:
                self._held_at = now
            return self._last
        if self._held_at is not None:
            pause = now - self._held_at
            stopped_at = self._held_at - self._paused
            for visible_block in self._blocks.values():
                if (
                    visible_block.shown
                    and max(visible_block.written_at, visible_block.pan_until)
                    <= stopped_at
                ):
                    # Animation stopped under the pointer, but the complete
                    # words stayed visible and could still be read.
                    visible_block.original_until -= pause
                    visible_block.translation_until -= pause
                    visible_block.read_until -= pause
            self._paused += pause
            self._held_at = None
        now -= self._paused
        visible_keys = {line.key for line, _, _ in slots}
        retiring = False
        if animate and not resized:
            for slot in self._last:
                key = slot[0].key
                if key not in visible_keys and key in self._blocks:
                    self._outgoing[key] = slot, now
                    retiring = True
        else:
            self._outgoing.clear()
        self._blocks = {k: b for k, b in self._blocks.items() if k in visible_keys}
        self.opacity = {}
        placed: list[PlacedSubtitle] = []
        for line, laid, rect in slots:
            goal = rect.topLeft()
            block = self._blocks.get(line.key)
            if block is None:
                history = line.key != slots[-1][0].key or (
                    self._seen is not None and line.key <= self._seen
                )
                block = self._blocks[line.key] = _Block(
                    _Move(goal, goal, now, 0.0), history
                )
            # Once a sentence can wrap at its chosen size, a retained word
            # would otherwise jump from the middle of one line to another.
            # Fade the slid line in place before revealing the whole sentence.
            previous_slot = next(
                (slot for slot in self._last if slot[0].key == line.key), None
            )
            translation_only = (
                previous_slot is not None
                and bool(laid.rows)
                and all(row.row.kind is RowKind.TRANSLATION for row in laid.rows)
                and any(
                    row.row.kind is RowKind.ORIGINAL for row in previous_slot[1].rows
                )
            )
            reflow = (
                previous_slot is not None
                and not settle
                and same_width
                and (block.complete or not write)
                and (
                    showing_next
                    or abs(previous_slot[1].height - laid.height)
                    > BASELINE_TOLERANCE_PX.value
                )
                and abs(previous_slot[2].y() - rect.y()) > BASELINE_TOLERANCE_PX.value
            )
            if (
                animate
                and (
                    not resized
                    or reflow
                    or (same_width and block.rewrap_at is not None)
                )
                and (
                    block.rewrap_at is not None
                    or reflow
                    or translation_only
                    or (
                        previous_slot is not None
                        and not settle
                        and line.key == self._seen
                        and line.key != slots[-1][0].key
                        and abs(previous_slot[2].y() - rect.y())
                        > BASELINE_TOLERANCE_PX.value
                    )
                    or (previous_slot is not None and block.returning_to_wrap(laid))
                )
            ):
                if block.rewrap_at is None:
                    block.rewrap_at = now
                elapsed = now - block.rewrap_at
                half_beat = BEAT_SEC.value / 2
                if elapsed < half_beat:
                    if previous_slot is not None and not any(
                        previous_slot[2].intersects(other[2]) for other in placed
                    ):
                        placed.append(previous_slot)
                        self.opacity[line.key] = 1.0 - ease(elapsed / half_beat)
                    self.moving = True
                    continue
                if elapsed < BEAT_SEC.value:
                    reveal_at = block.rewrap_at + BEAT_SEC.value
                    self.due = (
                        reveal_at if self.due is None else min(self.due, reveal_at)
                    )
                    continue
                block.pans.clear()
                block.pan_after.clear()
                block.visible_at = now
                block.move = _Move(goal, goal, now, 0.0)
                block.entry_y = block.rest_y = None
            block.rewrap_at = None
            newest = line.key == slots[-1][0].key
            if resized or not newest or not animate:
                block.entry_y = None
            if block.entry_y is not None:
                goal.setY(max(goal.y(), min(block.entry_y, foot - rect.height())))
            if resized or not settle or not animate:
                block.rest_y = None
            else:
                above = placed[-1][2].bottom() + gap if placed else top
                finished = newest and not line.live and not line.provisional
                y, ready = block.resting_top(
                    goal.y(), rect.height(), above, gap, now, finished
                )
                goal.setY(y)
                if ready is not None:
                    self.due = ready if self.due is None else min(self.due, ready)
            if previous_slot is not None and animate:
                above = placed[-1][2].bottom() if placed else top
                goal.setY(block.move.stable_y(goal.y(), above, foot - rect.height()))
            if not animate:
                block.move = _Move(goal, goal, now, 0.0)
            elif resized:
                # When the window grows, ease from the actual painted
                # position. A shrinking edge can overtake a caption; only
                # bring the ink that would be clipped back inside first.
                ink = bounds(laid)
                old = block.move.position(now)
                safe = QPointF(
                    max(-ink.left(), min(old.x(), width - ink.right())),
                    max(top - ink.top(), min(old.y(), foot - ink.bottom())),
                )
                block.move = _Move(safe, safe, now, 0.0)
            move = block.move
            # Keep the lower words still while the upper subtitle fades,
            # then move them into the space it has left.
            turn = retiring and goal.y() < move.position(now).y()
            move.retarget(goal, now, DEPTH_SEC.value if turn else 0.0)
            box = QRectF(rect)
            box.moveTopLeft(move.position(now))
            self.moving |= now < move.at + move.seconds
            if block.entry_y is not None and box.bottom() > foot:
                # A late clause can outgrow the lower margin. Keep the
                # old words visible through the glide; start the extra
                # line's write-out when its entire line fits.
                prior_slot = next(
                    (slot for slot in self._last if slot[0].key == line.key), None
                )
                if prior_slot is not None and now < move.at + move.seconds:
                    prior_line, prior_layout, prior_box = prior_slot
                    box.setSize(prior_box.size())
                    placed.append((prior_line, prior_layout, box))
                    block.written_at = max(block.written_at, move.at + move.seconds)
                    continue
                box.moveBottom(foot)
            if placed and placed[-1][2].bottom() > box.top():
                prior = placed[-1][2]
                if (
                    newest
                    and animate
                    and not block.complete
                    and block.visible_at is None
                    and _entry_height(line, laid, box.height()) <= foot - prior.bottom()
                ):
                    # Both sides have room beneath the rising text.
                    # Let reading start here and keep this position
                    # through the write-out.
                    block.entry_y = prior.bottom()
                    box.moveTop(block.entry_y)
                    block.move = _Move(box.topLeft(), box.topLeft(), now, 0.0)
                else:
                    previous = self._blocks[placed[-1][0].key].move
                    block.written_at = max(
                        block.written_at, previous.at + previous.seconds
                    )
                    continue
            if block.visible_at is None and any(
                now < at + DEPTH_SEC.value and box.intersects(slot[2])
                for slot, at in self._outgoing.values()
            ):
                self.moving = True
                continue
            if block.visible_at is None:
                # Browsing backwards brings an older subtitle into the top
                # slot. Let the retained one slide down and clear it first.
                occupied = any(
                    other.key in visible_keys
                    and other.key > line.key
                    and box.intersects(previous)
                    for other, _, previous in self._last
                )
                if animate and not resized and occupied:
                    continue
                block.visible_at = now
                block.written_at = now
            if animate:
                opacity = ease((now - block.visible_at) / BEAT_SEC.value)
                self.opacity[line.key] = opacity
                self.moving |= opacity < 1.0
            block.note_reading(laid, now)
            if not write and not animate:
                block.complete = True
            full = laid
            if write and not block.complete:
                laid = self._reveal(
                    block, laid, now, split, rect.width(), animate, line.key
                )
            laid, panning = block.pan(laid, full, rect.width(), now, animate)
            self.moving |= panning
            if not panning and block.pan_until > now:
                self.due = (
                    block.pan_until
                    if self.due is None
                    else min(self.due, block.pan_until)
                )
            block.shown |= bool(laid.rows) and self.opacity.get(line.key, 1.0) > 0.5
            self._seen = line.key if self._seen is None else max(self._seen, line.key)
            placed.append((line, laid, box))
        for key, (slot, at) in list(self._outgoing.items()):
            opacity = 1.0 - ease((now - at) / DEPTH_SEC.value)
            if (
                opacity <= 0.0
                or key in visible_keys
                or any(slot[2].intersects(other[2]) for other in placed)
            ):
                del self._outgoing[key]
            else:
                self.opacity[key] = opacity
                placed.insert(0, slot)
                self.moving = True
        if self.due is not None:
            self.due += self._paused
        self.read_until = max(
            (
                block.read_until + self._paused
                for block in self._blocks.values()
                if block.visible_at is not None
            ),
            default=None,
        )
        self._last = placed
        return placed

    def _reveal(
        self,
        block: _Block,
        laid: LaidLine,
        now: float,
        split: Split,
        width: float,
        animate: bool,
        line_key: int,
    ) -> LaidLine:
        rows = []
        starts: dict[RowKind, float] = {}
        for row in laid.rows:
            side = row.row.kind
            key = _row_key(row)
            words = block.words.get(key)
            if words is None or words.text != row.row.text:
                caption = self._caption(line_key)
                clause = None
                if (
                    side is RowKind.ORIGINAL
                    and not row.start
                    and caption is not None
                    and row.row.clause < len(caption.clauses)
                ):
                    clause = caption.clauses[row.row.clause]
                words = block.words[key] = _Words.schedule(
                    row, split, starts.get(side, now), words, clause, width
                )
            if words.times:
                side_read = words.times[-1] + AFTER_LAST_WORD_SEC.value
                if side is RowKind.ORIGINAL:
                    block.original_until = max(block.original_until, side_read)
                else:
                    block.translation_until = max(block.translation_until, side_read)
                starts[side] = words.times[-1] + BEAT_SEC.value
                block.written_at = max(block.written_at, words.times[-1])
                # Let a viewer who follows the original first finish the
                # translation once the complete pair is available.
                block.read_until = max(
                    block.read_until,
                    words.times[-1]
                    + max(AFTER_LAST_WORD_SEC.value, block.read_seconds),
                )
            visible, due, moving = words.draw(row, now, width, animate)
            if visible is not None:
                rows.append(visible)
            if due is not None:
                self.due = due if self.due is None else min(due, self.due)
            self.moving |= moving
        if len(rows) == len(laid.rows) and all(
            a is b for a, b in zip(rows, laid.rows, strict=True)
        ):
            return laid
        return replace(laid, rows=tuple(rows), card_links=None)
