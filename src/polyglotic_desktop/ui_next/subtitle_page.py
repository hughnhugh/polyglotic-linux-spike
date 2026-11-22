"""Video subtitles that grow in place. A page has as many complete caption
slots as the window can hold at the chosen size, up to Video's card limit.
A block keeps its writing size as speech grows. Overflow pages at whole
visual lines, and completed blocks keep their place in reading order.
"""

from bisect import bisect_left, bisect_right
from collections.abc import Callable, Iterable, Sequence
from dataclasses import dataclass, replace
from itertools import accumulate, groupby, pairwise
from math import floor, isclose

from PySide6.QtCore import QPointF, QRectF

from polyglotic_desktop.core.listening.display import RowKind
from polyglotic_desktop.ui_next.caption_layout import (
    CaptionLayout,
    LaidLine,
    row_room,
    visible_row,
)
from polyglotic_desktop.ui_next.views.captions import Line
from polyglotic_desktop.ui_next.views.card_window_defaults import (
    BEAT_SEC,
    CARD_STEP_SEC,
    SUBTITLE_CARD_ROWS,
)
from polyglotic_desktop.ui_next.views.dwell import (
    AFTER_LAST_WORD_SEC,
    HOLD_VIDEO_SEC,
    MEANT_PACE,
    MEANT_PACE_SPACED,
    SAID_PACE,
    SAID_PACE_SPACED,
    subtitle_need,
)

PlacedSubtitle = tuple[Line, LaidLine, QRectF]


@dataclass(frozen=True, slots=True)
class ReadBy:
    written: float = 0.0
    original: float = 0.0
    pair: float = 0.0
    shown: bool = False
    translation: float = 0.0


@dataclass(frozen=True)
class _Part:
    layout: LaidLine
    seconds: float
    includes_turn: bool = False
    original_lead: float = 0.0
    translation_lead: float = 0.0

    def words(self) -> tuple[tuple[int, RowKind, str | None, int, str], ...]:
        return tuple(
            (
                r.row.clause,
                r.row.kind,
                r.row.target or r.row.language,
                r.start,
                r.row.text,
            )
            for r in self.layout.rows
        )


def _glyphs(
    words: Iterable[tuple[int, RowKind, str | None, int, str]],
) -> set[tuple[int, RowKind, str | None, int, str]]:
    """Characters at their caption source offsets, independent of wrapping."""
    return {
        (clause, kind, language, start + offset, char)
        for clause, kind, language, start, text in words
        for offset, char in enumerate(text)
    }


def _resume_parts(
    old: tuple[_Part, ...], index: int, finished: bool, new: tuple[_Part, ...]
) -> tuple[int, bool]:
    """Find the first new page carrying unread words after a reflow.
    A row shared with the next page can be finished on that page."""
    if not old or not new:
        return 0, False
    current = set(old[index].words())
    read = _glyphs(
        word
        for part in old[: index + 1]
        for word in part.words()
        if finished or word not in current
    )
    at = 0
    for before, after in pairwise(new):
        leaving = set(before.words()).difference(after.words())
        if not _glyphs(leaving).issubset(read):
            break
        at += 1
    # Reuse the remaining time only if every word on this page was
    # already read or was on the screen when the window changed.
    available = read | _glyphs(current)
    return at, _glyphs(new[at].words()).issubset(available)


def _parts(laid: LaidLine, room: float) -> list[_Part]:
    """Split at complete visual lines. A fragment contains the glyphs it
    actually paints and retains their source offsets for word lookup."""
    bands: list[tuple[float, float, int, int, int]] = []
    if laid.label is not None:
        bands.append((0.0, laid.label.boundingRect().bottom(), -1, 0, 0))
    for row in laid.rows:
        encoded = row.row.text.encode("utf-16-le")
        for i in range(row.layout.lineCount()):
            qt_line = row.layout.lineAt(i)
            y = row.top + row.layout.position().y() + qt_line.y()
            start = qt_line.textStart()
            end = start + qt_line.textLength()
            text = encoded[2 * start : 2 * end].decode("utf-16-le")
            first = len(encoded[: 2 * start].decode("utf-16-le"))
            bands.append(
                (
                    y - row.band,
                    y + qt_line.height(),
                    row.index,
                    first,
                    first + len(text),
                )
            )
    ordered = sorted(bands)
    clauses = {row.index: row.row.clause for row in laid.rows}
    pair_end = {}
    for _clause, same_clause in groupby(ordered, key=lambda band: clauses.get(band[2])):
        section = list(same_clause)
        opening = section[0]
        pair_foot = max(band[1] for band in section)
        if pair_foot - opening[0] <= room:
            pair_end[opening] = pair_foot
    groups: list[list[tuple[float, float, int, int, int]]] = []
    bottom = 0.0
    for band in ordered:
        top, foot, *_ = band
        # Move a whole clause to the next page when it fits there. Only a
        # clause taller than the page needs to split from its translation.
        if not groups or (
            (top >= bottom or isclose(top, bottom))
            and pair_end.get(band, foot) - groups[-1][0][0] > room
        ):
            groups.append([])
            bottom = foot
        groups[-1].append(band)
        bottom = max(bottom, foot)
    parts = []
    earlier_rows: set[int] = set()
    for group in groups:
        top = group[0][0]
        height = max(foot for _, foot, *_ in group) - top
        if height > room:
            return []  # a control covers even one row: wait until it clears
        spans: dict[int, tuple[int, int]] = {}
        for _, _, key, first, end in group:
            spans[key] = (spans.get(key, (first, end))[0], end)
        rows = []
        for row in laid.rows:
            if row.index in spans:
                first, end = spans[row.index]
                visible = visible_row(row, first, end, QPointF())
                # Qt keeps the separator in a wrapped line's source span.
                # Shaping it as a standalone page can extend that trailing
                # space past the right edge. Keep every word at its offset.
                if laid.width and visible.row.text[-1:].isspace():
                    last = visible.layout.lineAt(visible.layout.lineCount() - 1)
                    if (
                        last.naturalTextRect().right() + visible.layout.position().x()
                        > laid.width
                    ):
                        trimmed = len(visible.row.text.rstrip())
                        if trimmed:
                            visible = visible_row(
                                row, first, first + trimmed, QPointF()
                            )
                rows.append(replace(visible, top=visible.top - top))
        original = " ".join(
            row.row.text for row in rows if row.row.kind is RowKind.ORIGINAL
        )
        translation = " ".join(
            row.row.text for row in rows if row.row.kind is RowKind.TRANSLATION
        )
        seconds = (
            subtitle_need(original, SAID_PACE.value, SAID_PACE_SPACED.value)
            if original
            else 0.0
        )
        if translation:
            seconds += subtitle_need(
                translation,
                MEANT_PACE.value,
                MEANT_PACE_SPACED.value,
                continuing=any(
                    row.index in earlier_rows and row.row.kind is RowKind.TRANSLATION
                    for row in rows
                ),
            )
        earlier_rows = set(spans)
        part = replace(
            laid,
            rows=tuple(rows),
            height=height,
            label=laid.label if -1 in spans else None,
            breaks=(),
            card_links=None,
        )
        parts.append(_Part(part, seconds))
    return parts


def _reading_parts(
    laid: LaidLine, room: float, delays: tuple[float, float] = (0.0, 0.0)
) -> list[_Part]:
    """Page the two languages independently when a pair fits. Each side
    stays readable while the other advances to its next whole line."""
    if laid.poured:
        return _parts(laid, room)
    heading = laid.rows[0].top if laid.label is not None and laid.rows else 0.0
    sides = []
    for kind in (RowKind.ORIGINAL, RowKind.TRANSLATION):
        rows = []
        height = band = 0.0
        for row in laid.rows:
            if row.row.kind is not kind or not row.layout.lineCount():
                continue
            box = row.layout.boundingRect().translated(row.layout.position())
            rows.append(replace(row, top=height - box.top() + row.band))
            height += box.height() + row.band
            band = max(
                band,
                max(
                    row.layout.lineAt(i).height() + row.band
                    for i in range(row.layout.lineCount())
                ),
            )
        if not rows or band <= 0:
            return _parts(laid, room)
        sides.append((replace(laid, rows=tuple(rows), height=height, label=None), band))

    heights = [band for _, band in sides]
    if heading + sum(heights) > room:
        return _parts(laid, room)
    # Give any spare visual lines to the side with the most text left.
    for i in sorted(
        range(len(sides)), key=lambda i: sides[i][0].height / heights[i], reverse=True
    ):
        heights[i] += min(
            room - heading - sum(heights), max(0.0, sides[i][0].height - heights[i])
        )

    pages = [
        _parts(side, height) for (side, _), height in zip(sides, heights, strict=True)
    ]
    if not all(pages):
        return _parts(laid, room)
    # A changing side needs a beat to turn. The other language remains
    # on screen and its reading clock keeps running through that beat.
    starts = [
        [0.0, *accumulate(part.seconds + BEAT_SEC.value for part in parts)]
        for parts in pages
    ]
    for times, delay in zip(starts, delays, strict=True):
        for i in range(1, len(times)):
            times[i] += delay
    end = max(times[-1] for times in starts)
    turns = sorted({end, *(t for times in starts for t in times[:-1])})
    result = []
    for at, until in pairwise(turns):
        original, translation = (
            parts[bisect_right(times[:-1], at) - 1].layout
            for parts, times in zip(pages, starts, strict=True)
        )
        page_rows = (
            *(replace(row, top=row.top + heading) for row in original.rows),
            *(
                replace(row, top=row.top + heading + heights[0])
                for row in translation.rows
            ),
        )
        result.append(
            _Part(
                replace(
                    laid,
                    rows=page_rows,
                    height=heading + heights[0] + translation.height,
                    breaks=(),
                    card_links=None,
                ),
                until - at,
                includes_turn=True,
                original_lead=end - starts[0][-1],
                translation_lead=end - starts[1][-1],
            )
        )
    return result


@dataclass
class _Reading:
    """A subtitle needing the whole window or several pages. Hold it and
    show the subtitles that came meanwhile in order."""

    key: int
    anchor: int | None
    stamp: tuple[object, ...] = ()
    parts: tuple[_Part, ...] = ()
    index: int = 0
    until: float = 0.0
    turn_until: float = 0.0
    retained_rows: frozenset[tuple[int, int, str]] = frozenset()
    inset: float = 0.0
    above: tuple[PlacedSubtitle, ...] = ()
    above_until: float = 0.0
    above_read_until: float = 0.0
    delays: tuple[float, float] = (0.0, 0.0)
    next_page: PlacedSubtitle | None = None
    next_frame: tuple[object, ...] = ()
    viewport: tuple[object, ...] = ()


def bounds(laid: LaidLine) -> QRectF:
    """The painted text can extend past the composer's last baseline."""
    box = QRectF(0.0, 0.0, 0.0, laid.height)
    for row in laid.rows:
        layout = row.layout
        offset = layout.position()
        for i in range(layout.lineCount()):
            ink = (
                layout.lineAt(i)
                .naturalTextRect()
                .translated(offset.x(), row.top + offset.y())
            )
            box = box.united(ink)
    if laid.label is not None:
        box = box.united(laid.label.boundingRect())
    return box


def _keep_rows(laid: LaidLine, previous: LaidLine | None) -> LaidLine | None:
    """A translation already on screen keeps its top when its original
    changes. Release the anchor if a newly wrapped row crosses it.
    Poured rows share baselines with other clauses and must move together."""
    if previous is None or laid.poured or previous.poured:
        return laid
    if {r.row.clause for r in laid.rows} != {r.row.clause for r in previous.rows}:
        # A revision split or joined clauses. The old translation position
        # belonged to a different phrase and can leave a whole pair's gap.
        return laid
    anchors = {
        (r.row.clause, r.row.kind, r.row.target or r.row.language): r.top
        for r in previous.rows
    }
    rows = []
    shift = 0.0
    for row in laid.rows:
        at = row.top + shift
        kept = anchors.get(
            (row.row.clause, row.row.kind, row.row.target or row.row.language)
        )
        if kept is not None:
            if at > kept:
                return None
            shift = kept - row.top
        rows.append(replace(row, top=row.top + shift))
    return replace(laid, rows=tuple(rows), height=laid.height + shift, breaks=())


def _first_pair_height(incoming: LaidLine) -> float:
    """Room for one whole visual line of each incoming language."""
    bands: dict[tuple[RowKind, str | None], float] = {}
    for row in incoming.rows:
        if not row.layout.lineCount():
            continue
        key = row.row.kind, row.row.target
        bands[key] = max(bands.get(key, 0.0), row.layout.lineAt(0).height() + row.band)
    label = (
        incoming.rows[0].top if incoming.label is not None and incoming.rows else 0.0
    )
    return label + sum(bands.values()) if bands else float("inf")


def _keep_above(
    layout: LaidLine,
    incoming: LaidLine,
    room: float,
    gap: float,
) -> tuple[LaidLine, float] | None:
    """Keep a complete previous pair, or its last translation, above
    the first readable page of the incoming subtitle."""
    available = room - _first_pair_height(incoming)
    ink = bounds(layout)
    full_height = max(layout.height, ink.bottom())
    if ink.top() >= 0 and full_height <= available:
        return layout, full_height + min(gap, available - full_height)
    rows = [row for row in layout.rows if row.row.kind is RowKind.TRANSLATION]
    if not rows:
        return None
    head = min(
        row.top + row.layout.position().y() + row.layout.boundingRect().top() - row.band
        for row in rows
    )
    foot = max(
        row.top + row.layout.position().y() + row.layout.boundingRect().bottom()
        for row in rows
    )
    height = foot - head
    spare = available - height
    if spare < 0:
        return None
    translation = replace(
        layout,
        rows=tuple(replace(row, top=row.top - head) for row in rows),
        height=height,
        label=None,
        breaks=(),
        card_links=None,
    )
    return translation, height + min(gap, spare)


def measured(
    engine: CaptionLayout,
    line: Line,
    width: int,
    size: float,
    room: float,
    previous: LaidLine | None = None,
    *,
    writing: bool = False,
) -> tuple[LaidLine, QRectF]:
    """Live words can pan. A complete pair wraps, then pages if it is too tall."""
    wrapped = engine.laid(line, width, size)
    layout = wrapped
    if writing:
        track = engine.laid(line, width, size, single_rows=True)
        if line.live or line.provisional or bounds(track).width() <= width:
            layout = track
    kept = _keep_rows(layout, previous)
    if kept is not None and kept.height <= room:
        layout = kept
    return layout, bounds(layout)


def _slots(
    heights: list[float], room: float, gap: float, nominal: int
) -> list[tuple[float, float]]:
    """Place a contiguous suffix of pairs, sharing free vertical space.
    Only the oldest may leave. An empty upper slot at startup lets the next
    pair enter below the first one's rising text."""
    used = heights[-1]
    first = len(heights) - 1
    while first and used + gap + heights[first - 1] <= room:
        first -= 1
        used += gap + heights[first]
    kept = heights[first:]
    # While there is still no history to fill the upper slots, allocate
    # their share as before, provided the visible ink fits in what remains.
    empty = max(0, nominal - len(kept)) if first == 0 else 0
    nominal_slot = (room + gap) / nominal - gap
    head = min(max(0.0, room - used), empty * (nominal_slot + gap))
    spare = max(0.0, room - used - head) / len(kept)
    slots = []
    for height in kept:
        slots.append((head, height + spare))
        head += height + spare + gap
    return slots


class SubtitlePage:
    """The newest subtitles in reading order. A translation wraps below its
    original without scrolling the page or pushing the next subtitle."""

    def __init__(self) -> None:
        self.first: int | None = None
        self._waiting: tuple[int, float] | None = None
        self._room: tuple[int, float] | None = None
        self._resized_at = float("-inf")
        self._finished: int | None = None
        self._last_shown: int | None = None
        self.reading: _Reading | None = None
        self.due: float | None = None
        self._frame: tuple[object, ...] = ()
        self._stamp: tuple[object, ...] = ()
        self._placed: list[tuple[Line, LaidLine, QRectF]] = []
        self._last_part: PlacedSubtitle | None = None
        self.waiting_slot: PlacedSubtitle | None = None
        self.waiting_since = 0.0
        self._waiting_key: int | None = None

    def next_pair(self, lines: Sequence[Line], anchor: int | None) -> Sequence[Line]:
        """The two adjacent captions competing for room at the reading position."""
        if len(lines) <= 2:
            return lines
        key = anchor
        if key is None:
            key = self.reading.key if self.reading is not None else self._last_shown
        if key is None:
            return lines[-2:]
        at = min(bisect_left(lines, key, key=lambda line: line.key), len(lines) - 2)
        return lines[at : at + 2]

    def _through_block(
        self,
        lines: Sequence[Line],
        now: float,
        count: int,
        deadlines: Callable[[int | None], ReadBy],
        fits_together: Callable[[Line, Line], bool],
    ) -> Sequence[Line]:
        """Deal queued blocks in order. Give a reader finishing the upper
        translation Video's normal grace before the next promotion."""
        if self._last_shown is None:
            return lines
        pending = bisect_right(lines, self._last_shown, key=lambda line: line.key)
        if pending == len(lines):
            self._waiting = None
            return lines
        if self._finished == self._last_shown:
            self._waiting = None
            return lines[: pending + 1]
        key = lines[pending].key
        if self._waiting is None or self._waiting[0] != key:
            self._waiting = key, now
        arrived = self._waiting[1]
        catch_up_by = arrived + HOLD_VIDEO_SEC.value
        lower = deadlines(self._last_shown)
        if pending and lines[pending - 1].key == self._last_shown and not lower.shown:
            # A placed slot can still be waiting for the outgoing pair to
            # fade. Do not advance past a caption nobody has actually seen.
            self.due = now + CARD_STEP_SEC.value
            return lines[:pending]
        read = 0.0
        if pending >= count:
            evicted = deadlines(lines[pending - count].key)
            # A reader can finish the original before following it up.
            # A backlog or a recent resize can leave just one slot: use
            # Video's bounded catch-up hold until two slots are stable.
            catching_up = (
                count == 1
                or pending + 1 < len(lines)
                or arrived <= self._resized_at + HOLD_VIDEO_SEC.value
            )
            original = (
                lower.original if count > 1 else max(lower.original, lower.translation)
            )
            if (
                count > 1
                and pending + 1 < len(lines)
                and fits_together(lines[pending - 1], lines[pending])
            ):
                # The lower pair will remain fully visible in the upper slot.
                # Finish the pair that actually leaves before bringing in more.
                original = max(evicted.original, evicted.translation)
            # Once the current original is ready to move, give the upper
            # pair the regular grace to finish. Its reading time already
            # elapsed while the lower block was writing still counts.
            ready = max(arrived, lower.written, original)
            turn_by = catch_up_by if catching_up else ready + HOLD_VIDEO_SEC.value
            read = max(original, min(evicted.pair, turn_by))
        release = max(lower.written, read)
        if pending and now < release:
            self.due = release
            return lines[:pending]
        self._waiting = None
        if pending + 1 < len(lines):
            self.due = now + max(CARD_STEP_SEC.value, HOLD_VIDEO_SEC.value)
        return lines[: pending + 1]

    def resume(self) -> None:
        """Return from browsing at the next waiting caption in the live queue."""
        self._finished = self._last_shown
        self.reading = None
        self._stamp = ()

    def browse_part(self, step: int) -> int | None:
        """Move within an oversized subtitle before stepping to another."""
        reading = self.reading
        if reading is None:
            return None
        to = max(0, min(len(reading.parts) - 1, reading.index - step))
        if to == reading.index:
            return None
        reading.index = to
        reading.anchor = reading.key
        return reading.key

    def _read(
        self,
        lines: Sequence[Line],
        engine: CaptionLayout,
        width: int,
        size: float,
        top: float,
        room: float,
        now: float,
        held: bool,
    ) -> list[PlacedSubtitle] | None:
        reading = self.reading
        assert reading is not None
        at = bisect_left(lines, reading.key, key=lambda ln: ln.key)
        if at >= len(lines) or lines[at].key != reading.key:
            self.reading = None
            return None  # withdrawn or removed from history
        line = lines[at]
        if reading.viewport and reading.viewport != (engine, width, size, top, room):
            reading.above = ()
            if reading.viewport[1:] != (width, size, top, room):
                reading.inset = 0.0
            reading.viewport = (engine, width, size, top, room)
        top += reading.inset
        room -= reading.inset
        stamp = (line, engine, width, size, room)
        if stamp != reading.stamp:
            # Even one unwrapped pair is taller than the viewport.
            # Page complete visual lines so neither language is lost.
            laid = engine.laid(line, width, size)
            if laid.poured:
                laid = engine.laid(line, width, size, separate_rows=True)
            parts = tuple(_reading_parts(laid, room, reading.delays))
            if parts and not parts[0].includes_turn and any(reading.delays):
                first = replace(
                    parts[0], seconds=parts[0].seconds + max(reading.delays)
                )
                parts = (first, *parts[1:])
            reading.delays = (0.0, 0.0)
            reading.index, keep_deadline = _resume_parts(
                reading.parts, reading.index, now >= reading.until, parts
            )
            reading.parts = parts
            reading.stamp = stamp
            if parts and not keep_deadline:
                initial_part = parts[reading.index]
                start = now + BEAT_SEC.value  # acquire the newly placed caption
                reading.until = start + initial_part.seconds
        if not reading.parts:
            return []
        if reading.index == len(reading.parts) - 1:
            reading.until = max(reading.until, reading.above_read_until)
        if not held and now >= reading.until:
            if reading.index + 1 < len(reading.parts):
                previous = reading.parts[reading.index].layout
                reading.retained_rows = frozenset(
                    (row.index, row.start, row.row.text) for row in previous.rows
                )
                reading.index += 1
                reading.turn_until = now + BEAT_SEC.value
                next_part = reading.parts[reading.index]
                start = now if next_part.includes_turn else reading.turn_until
                reading.until = start + next_part.seconds
            elif reading.anchor is None and at + 1 < len(lines):
                self._finished = reading.key
                self.first = lines[at + 1].key
                self.reading = None
                self._stamp = ()
                return None
        self.due = reading.until if not held and now < reading.until else None
        if reading.anchor is None:
            self._last_shown = line.key
        part = reading.parts[reading.index].layout
        if now < reading.turn_until:
            # A page break separates different words at the same position.
            # A side still being read keeps all its ink through the break.
            part = replace(
                part,
                rows=tuple(
                    row
                    for row in part.rows
                    if (row.index, row.start, row.row.text) in reading.retained_rows
                ),
            )
            self.due = reading.turn_until
        y = top + floor((room - part.height) / 2) if len(reading.parts) == 1 else top
        shown = line, part, QRectF(0, y, width, part.height)
        self._last_part = shown
        # A speaker can withdraw a caption while the lower block pages.
        above = [
            slot
            for slot in reading.above
            if any(line.key == slot[0].key for line in lines)
        ]
        if above and now < reading.above_until:
            self.due = (
                reading.above_until
                if self.due is None
                else min(self.due, reading.above_until)
            )
            return [*above, shown]
        return [shown]

    def _next_below(
        self,
        lines: Sequence[Line],
        reading: _Reading,
        engine: CaptionLayout,
        width: int,
        size: float,
        top: float,
        room: float,
        gap: float,
        now: float,
        visible: Sequence[PlacedSubtitle],
    ) -> bool:
        """Start the waiting caption when the current final page can finish above it."""
        if (
            not reading.parts
            or reading.index != len(reading.parts) - 1
            or now >= reading.until
            or now < reading.turn_until
            or (reading.above and now < reading.above_until)
        ):
            return False
        next_index = bisect_right(lines, reading.key, key=lambda item: item.key)
        if next_index == len(lines):
            return False
        page = reading.parts[-1]
        painted = next((slot for slot in visible if slot[0].key == reading.key), None)
        if painted is None or _Part(painted[1], 0.0).words() != page.words():
            return False
        incoming = lines[next_index]
        layout = engine.laid(incoming, width, size)
        original_end = reading.until - page.original_lead
        translation_end = reading.until - page.translation_lead
        history = _keep_above(painted[1], layout, room, gap)
        if history is None or (history[0] is not painted[1] and now < original_end):
            first_read = original_end
            if now < first_read < reading.until:
                self.due = first_read if self.due is None else min(self.due, first_read)
            return False
        tail, inset = history
        upper_end = reading.until + BEAT_SEC.value
        translation = " ".join(
            row.row.text for row in tail.rows if row.row.kind is RowKind.TRANSLATION
        )
        self._finished = reading.key
        self.first = reading.key
        self.reading = _Reading(
            incoming.key,
            None,
            inset=inset,
            above=(
                (
                    painted[0],
                    tail,
                    QRectF(painted[2].x(), top, painted[2].width(), tail.height),
                ),
            ),
            above_read_until=upper_end,
            # The upper translation can be read throughout the handoff.
            # Its remaining deadline and its fresh reading interval overlap.
            above_until=max(
                upper_end,
                now
                + BEAT_SEC.value
                + subtitle_need(translation, MEANT_PACE.value, MEANT_PACE_SPACED.value),
            ),
            delays=(max(0.0, original_end - now), max(0.0, translation_end - now)),
            viewport=(engine, width, size, top, room),
        )
        self._stamp = ()
        return True

    def _waiting_below(
        self,
        lines: Sequence[Line],
        reading: _Reading,
        shown: PlacedSubtitle,
        engine: CaptionLayout,
        width: int,
        size: float,
        top: float,
        room: float,
        gap: float,
        now: float,
    ) -> PlacedSubtitle:
        """Give the waiting caption a first page without taking any time
        from the original or translation already being read."""
        if (
            not reading.parts
            or reading.index + 2 < len(reading.parts)
            or not reading.inset
            or now < reading.above_until
            or (now < reading.turn_until and reading.next_page is None)
        ):
            return shown
        index = bisect_right(lines, reading.key, key=lambda item: item.key)
        if index == len(lines):
            return shown
        incoming = lines[index]
        upper = max(part.layout.height for part in reading.parts[reading.index :])
        frame = (incoming, engine, width, size, top, room, gap, upper)
        if frame != reading.next_frame:
            reading.next_frame = frame
            reading.next_page = None
            laid = engine.laid(incoming, width, size, separate_rows=True)
            spare = room - upper - _first_pair_height(laid)
            if spare >= 0:
                lower = room - upper - min(gap, spare)
                parts = _reading_parts(laid, lower)
                if parts:
                    opening = parts[0].layout
                    reading.next_page = (
                        incoming,
                        opening,
                        QRectF(0, top + room - lower, width, opening.height),
                    )
        if reading.next_page is None:
            return shown
        if self._waiting_key != incoming.key:
            self.waiting_since = now
            self._waiting_key = incoming.key
            # Reacquire the current words if its page moves into the upper slot.
            reading.until += BEAT_SEC.value
        self.waiting_slot = reading.next_page
        line, layout, box = shown
        kept = QRectF(box)
        kept.moveTop(min(box.y(), self.waiting_slot[2].y() - upper))
        current = line, layout, kept
        self._last_part = current
        return current

    def place(
        self,
        lines: Sequence[Line],
        engine: CaptionLayout,
        width: int,
        size: float,
        top: float,
        foot: float,
        limit: int,
        gap: float,
        anchor: int | None,
        now: float,
        held: bool,
        deadlines: Callable[[int | None], ReadBy],
        write: bool = False,
        visible: Sequence[PlacedSubtitle] = (),
    ) -> list[PlacedSubtitle]:
        self.due = None
        if self.waiting_slot is not None:
            visible = [
                slot for slot in visible if slot[0].key != self.waiting_slot[0].key
            ]
        if (
            not held
            or anchor is not None
            or self.reading is None
            or self.reading.viewport != (engine, width, size, top, foot - top)
        ):
            self.waiting_slot = None
        if not lines or foot <= top:
            if not lines:
                self.reading = None
                self._finished = None
                self._last_shown = -1
            elif self.reading is None:
                self.reading = _Reading(
                    anchor if anchor is not None else lines[-1].key, anchor
                )
            self.first = None
            self._placed = []
            self._last_part = None
            self._stamp = ()
            return []
        room = foot - top
        if self._room is not None and self._room != (width, room):
            self._resized_at = now
        self._room = width, room
        if self.reading is not None and self.reading.anchor != anchor:
            self.reading = None
        while self.reading is not None:
            if anchor is None:
                self.reading.until = max(
                    self.reading.until,
                    deadlines(self.reading.key).written + AFTER_LAST_WORD_SEC.value,
                )
            part = self._read(lines, engine, width, size, top, room, now, held)
            if part is not None:
                reading = self.reading
                if anchor is None and not held and reading is not None:
                    if self._next_below(
                        lines,
                        reading,
                        engine,
                        width,
                        size,
                        top,
                        room,
                        gap,
                        now,
                        visible,
                    ):
                        continue
                    if len(part) == 1:
                        current = self._waiting_below(
                            lines,
                            reading,
                            part[0],
                            engine,
                            width,
                            size,
                            top,
                            room,
                            gap,
                            now,
                        )
                        return [current]
                return part
        nominal = SUBTITLE_CARD_ROWS.value * row_room(engine, RowKind.ORIGINAL, size)
        count = max(1, min(limit, floor((room + gap) / (nominal + gap))))
        if count == 1 and limit > 1:
            pair = row_room(engine, RowKind.ORIGINAL, size) + row_room(
                engine, RowKind.TRANSLATION, size
            )
            two = 2 * pair
            if len(lines) >= 2:
                blocks = [
                    engine.laid(line, width, size, single_rows=True)
                    for line in self.next_pair(lines, anchor)
                ]
                two = sum(max(block.height, bounds(block).height()) for block in blocks)
            if two + gap <= room:
                count = 2
        if anchor is None:

            def fits_together(previous: Line, incoming: Line) -> bool:
                if (
                    previous.live
                    or previous.provisional
                    or incoming.live
                    or incoming.provisional
                ):
                    return False
                height = gap
                for item in (previous, incoming):
                    layout, ink = measured(engine, item, width, size, room)
                    height += max(layout.height, ink.bottom()) - min(0.0, ink.top())
                if height <= room:
                    return True
                if self._frame[:6] != (engine, width, size, top, foot, count):
                    return False
                previous_layout = engine.laid(previous, width, size)
                painted = next(
                    (slot[1] for slot in visible if slot[0].key == previous.key), None
                )
                if painted is None or [r.row for r in painted.rows] != [
                    r.row for r in previous_layout.rows
                ]:
                    return False
                kept = _keep_above(
                    painted, engine.laid(incoming, width, size), room, gap
                )
                return kept is not None and kept[0] is painted

            lines = self._through_block(lines, now, count, deadlines, fits_together)
        # Keep the preceding subtitle readable for as long as it fits.
        start = max(0, len(lines) - count)
        if self._finished is not None:
            # A long caption borrowed the whole page. Once read, its last
            # part must not reclaim the slots intended for its successors.
            after = bisect_right(lines, self._finished, key=lambda line: line.key)
            start = max(start, min(after, len(lines) - 1))
        self.first = lines[start].key
        if anchor is not None:
            start = min(
                bisect_left(lines, anchor, key=lambda line: line.key), len(lines) - 1
            )
        page = lines[start : start + count]
        if anchor is None:
            self._last_shown = page[-1].key
        frame = (engine, width, size, top, foot, count, gap, nominal)
        older = None
        if anchor is None and start > 0 and len(page) == 1:
            preceding = lines[start - 1]
            # A catch-up page can end on a short block. Show that whole
            # block in the empty upper slot when the live subtitle returns.
            if count > 1 or preceding.key != self._finished:
                older = preceding
        read = deadlines(page[-1].key)
        writing_newest = (
            write and anchor is None and (not read.written or now < read.written)
        )
        if writing_newest and now < read.written:
            self.due = read.written if self.due is None else min(self.due, read.written)
        stamp = (*frame, writing_newest, id(older), *(id(line) for line in page))
        if stamp == self._stamp:
            if anchor is None:
                self.first = self._placed[0][0].key
            return self._placed
        same_frame = frame == self._frame
        previous = (
            {line.key: (laid, rect) for line, laid, rect in self._placed}
            if same_frame
            else {}
        )
        if frame != self._frame:
            self._last_part = None
        self._frame = frame

        pair = row_room(engine, RowKind.ORIGINAL, size) + row_room(
            engine, RowKind.TRANSLATION, size
        )
        minimum = []
        measured_page = []
        for item in page:
            writing = (
                item.live or item.provisional or (item is page[-1] and writing_newest)
            )
            prior = previous.get(item.key)
            layout, ink = measured(
                engine,
                item,
                width,
                size,
                room,
                prior[0] if prior else None,
                writing=writing,
            )
            height = max(layout.height, ink.bottom()) - min(0.0, ink.top())
            minimum.append(height)
            measured_page.append((item, layout, ink, height))
        if anchor is None and len(lines) > 1 and same_frame:
            latest, layout, _, height = measured_page[-1]
            previous_slot = next(
                (slot for slot in visible if slot[0].key == lines[-2].key), None
            )
            entering = all(slot[0].key != latest.key for slot in visible)
            if (
                previous_slot is not None
                and entering
                and previous_slot[2].height() + gap + height > room
            ):
                history = _keep_above(previous_slot[1], layout, room, gap)
                if history is not None:
                    tail, inset = history
                    above = previous_slot[0], tail, QRectF(0, top, width, tail.height)
                    translation = " ".join(
                        row.row.text
                        for row in tail.rows
                        if row.row.kind is RowKind.TRANSLATION
                    )
                    keep_until = 0.0
                    if tail is previous_slot[1]:
                        read_by = deadlines(previous_slot[0].key)
                        keep_until = max(read_by.original, read_by.translation)
                    self.reading = _Reading(
                        latest.key,
                        anchor,
                        inset=inset,
                        above=(above,),
                        above_read_until=keep_until,
                        above_until=max(
                            keep_until,
                            now
                            + subtitle_need(
                                translation, MEANT_PACE.value, MEANT_PACE_SPACED.value
                            ),
                        ),
                        viewport=(engine, width, size, top, room),
                    )
                    self._stamp = ()
                    return (
                        self._read(lines, engine, width, size, top, room, now, held)
                        or []
                    )
        slots = _slots(minimum, room, gap, count)
        visible_page = measured_page[-len(slots) :]
        placed: list[PlacedSubtitle] = []
        for i, ((line, laid, ink, height), (offset, slot)) in enumerate(
            zip(visible_page, slots, strict=True)
        ):
            slot_top = top + offset
            before = previous.get(line.key)
            was = before[1] if before is not None else None
            # An original needs room for its translation from the first
            # frame. A long block already complete can use the whole slot.
            full = engine.laid(line, width, size)
            inset = max(0.0, (slot - max(pair, full.height)) / 2)
            same_slot = was is not None and slot_top <= was.y() < slot_top + slot
            if same_slot and was is not None:
                inset = was.y() - slot_top
            inset = max(0.0, min(inset, slot - height))
            if height > room:
                self.reading = _Reading(line.key, anchor)
                self._stamp = ()
                return (
                    self._read(lines, engine, width, size, top, room, now, held) or []
                )
            if i < len(visible_page) - 1 and not same_slot:
                # An earlier subtitle fits at its settled size now. Centre
                # that ink in its slot so it stays close to the next line.
                inset = (
                    slot - max(laid.height, ink.bottom()) + min(0.0, ink.top())
                ) / 2
            left = (
                0.0
                if line.live or line.provisional
                else (width - ink.width()) / 2 - ink.left()
            )
            if was is not None:
                left = was.x()  # a correction keeps the original's reading position
            x = (
                0.0
                if ink.width() > width
                else max(-ink.left(), min(left, width - ink.right()))
            )
            y = slot_top + inset - min(0.0, ink.top())
            placed.append(
                (line, laid, QRectF(x, y, width - x, max(laid.height, ink.bottom())))
            )
        if older is not None:
            # Blocks arrive complete. Let the preceding subtitle remain in
            # the room above a short one, with the current text at its size
            # and position. A previous block must fit in full to stay.
            spare = placed[0][2].top() - gap - top
            if spare > 0:
                old_rect: QRectF | None
                last = self._last_part
                prior = previous.get(older.key)
                if last is not None and last[0] is older and last[2].width() == width:
                    # A paged block has already been read. Promote the last
                    # page as it stood instead of replacing it with every
                    # earlier clause in a suddenly smaller font.
                    laid, old_rect = last[1], last[2]
                    ink = QRectF(0.0, 0.0, old_rect.width(), laid.height)
                elif prior is not None:
                    laid, old_rect = prior
                    ink = bounds(laid)
                else:
                    laid, ink = measured(engine, older, width, size, spare)
                    old_rect = None
                height = max(laid.height, ink.bottom()) - min(0.0, ink.top())
                if height <= spare:
                    x = (
                        old_rect.x()
                        if old_rect is not None
                        else max(0.0, (width - ink.width()) / 2 - ink.left())
                    )
                    y = top + (spare - height) / 2 - min(0.0, ink.top())
                    placed.insert(0, (older, laid, QRectF(x, y, width - x, height)))
                    self.first = older.key
        self.first = placed[0][0].key
        self._stamp, self._placed = stamp, placed
        return placed
