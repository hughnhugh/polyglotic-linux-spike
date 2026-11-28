"""Planted faults: each breaks one thing in the running display, on purpose.

A rule's test is only worth its name if it fails when the rule is broken,
and the replay's diff only if it sees a 1 px nudge. These break the product
while it runs, by replacing one of its functions for the length of a replay;
no file under `src/` is changed. Each is what a careless edit to that
function would do.

    with plants.planted("fall"):
        frames = list(drive.play(stream, setup))
"""

from collections.abc import Callable, Iterator, Sequence
from contextlib import contextmanager
from dataclasses import replace
from typing import Any
from unittest.mock import patch

from PySide6.QtCore import QPointF

from polyglotic_desktop.core.listening.display import LIVE_TRAIL, RowKind
from polyglotic_desktop.ui_next import caption_layout, caption_marks, caption_window
from polyglotic_desktop.ui_next.caption_layout import LINK_MARK, CaptionLayout, Ink
from polyglotic_desktop.ui_next.caption_marks import CaptionMarks
from polyglotic_desktop.ui_next.caption_window import Canvas, CaptionWindow
from polyglotic_desktop.ui_next.views import captions
from polyglotic_desktop.ui_next.views.captions import Line

NUDGE_PX = 1.0
"""The nudge: every row this far lower, in px. The smallest move the diff
must see (PLAN.md, display-0's acceptance)."""
FALL_PX = 3.0
"""The fall: every row this far lower for one frame, in px."""
SLIDE_PX = 40.0
"""The sideways slide: a new row starts this far right of its place, in px."""
SLIDE_FRAMES = 12
"""And reaches it over this many paints."""
AFTER_PAINTS = 3
"""A nudge or a fall starts at this paint of a canvas that has rows: after
the first captions are up, so there is something to compare it with."""


def _lowered(page: list[Any], by: float) -> list[Any]:
    return [(line, laid, y + by) for line, laid, y in page]


def _positions(change: Callable[[Canvas, list[Any], int], list[Any]]) -> Any:
    """`Canvas._list_positions` with its page passed through `change`,
    which is given how many pages with rows this canvas has made."""
    real = Canvas._list_positions
    paints: dict[int, int] = {}

    def planted(self: Canvas) -> tuple[list[Any], float]:
        page, offset = real(self)
        if page:
            paints[id(self)] = paints.get(id(self), 0) + 1
            page = change(self, page, paints[id(self)])
        return page, offset

    return patch.object(Canvas, "_list_positions", planted)


def _nudge() -> Any:
    def change(_canvas: Canvas, page: list[Any], paint: int) -> list[Any]:
        return _lowered(page, NUDGE_PX) if paint >= AFTER_PAINTS else page

    return _positions(change)


def _fall() -> Any:
    def change(canvas: Canvas, page: list[Any], paint: int) -> list[Any]:
        if paint != AFTER_PAINTS:
            return page
        canvas.update()  # the next frame puts it back: a fall of one frame
        return _lowered(page, FALL_PX)

    return _positions(change)


def _slide() -> Any:
    first_seen: dict[tuple[int, int, int, int], int] = {}

    def change(canvas: Canvas, page: list[Any], paint: int) -> list[Any]:
        result = []
        moving = False
        for line, laid, y in page:
            rows = []
            nth: dict[int, int] = {}
            for row in laid.rows:
                visual = nth[row.index] = nth.get(row.index, -1) + 1
                if row.opacity <= 0:  # held back: not on screen yet
                    rows.append(row)
                    continue
                seen = (id(canvas), line.key, row.index, visual)
                since = first_seen.setdefault(seen, paint)
                left = 1 - (paint - since) / SLIDE_FRAMES
                if paint > 1 and since > 1 and left > 0:
                    moving = True
                    layout = caption_layout.moving_layout(row.layout)
                    for n in range(layout.lineCount()):
                        part = layout.lineAt(n)
                        at = part.position()
                        part.setPosition(QPointF(at.x() + SLIDE_PX * left, at.y()))
                    row = replace(row, layout=layout)
                rows.append(row)
            if any(a is not b for a, b in zip(rows, laid.rows, strict=True)):
                laid = replace(laid, rows=tuple(rows), link_paint=None)
            result.append((line, laid, y))
        if moving:
            canvas.update()
        return result

    return _positions(change)


def _step() -> Any:
    """Arrivals as they were before the glide (830): when a caption in view
    gains a row, the stack is put at its new place in one frame."""
    real = CaptionWindow._note_arrivals

    def planted(self: CaptionWindow, *, revealed_line: bool = False) -> None:
        in_view = {line.key for line in self.canvas.lines_in_view()}
        if not revealed_line and self._known == in_view:
            self.canvas.at_rest = self.canvas.rest_rows()
            return
        real(self, revealed_line=revealed_line)

    return patch.object(CaptionWindow, "_note_arrivals", planted)


def _wrap() -> Any:
    """The composer's rows left as one item each, however many lines."""
    return patch.object(
        caption_layout,
        "_single_line_rows",
        lambda row, _continuations, _mark_overflow: (row,),
    )


def _no_wait() -> Any:
    """A new wrapped row drawn at once, at full ink, before its place is
    clear."""
    return patch.object(Canvas, "_reveal_wraps", lambda _self, page, _rest: page)


def _inked(change: Callable[[Ink], Ink]) -> Any:
    """Every caption drawn with its ink passed through `change` first."""
    real = CaptionLayout.paint

    def planted(
        self: CaptionLayout,
        painter: Any,
        line: Any,
        laid: Any,
        at: Any,
        ink: Ink,
        *args: Any,
        **kwargs: Any,
    ) -> None:
        real(self, painter, line, laid, at, change(ink), *args, **kwargs)

    return patch.object(CaptionLayout, "paint", planted)


def _swap_inks() -> Any:
    """What was said drawn in the translation's colour, and the other way
    round."""
    return _inked(
        lambda ink: replace(ink, original=ink.translation, translation=ink.original)
    )


def _full_while_spoken() -> Any:
    """Text still being spoken drawn in full ink, as a finished caption is."""
    return _inked(lambda ink: replace(ink, live_alpha=1.0, provisional_alpha=1.0))


def _no_step_back() -> Any:
    """Older captions keep all of the newest's contrast: no step back."""
    return patch.object(caption_window, "older_alphas", lambda *_, **__: (1.0, 1.0))


def _shifted_links() -> Any:
    """The translation's word links each take the next link's colour."""
    real = CaptionMarks.__call__

    def planted(self: CaptionMarks, line: Line, row: int) -> Sequence[Any]:
        marks = real(self, line, row)
        if line.rows[row].kind is not RowKind.TRANSLATION:
            return marks
        moved = []
        for start, end, format_ in marks:
            link = format_.property(LINK_MARK)
            if link is not None:
                colour = caption_marks.link_colour(self.panel, int(link) + 1)
                format_ = self._format("link", colour, int(link))
            moved.append((start, end, format_))
        return moved

    return patch.object(CaptionMarks, "__call__", planted)


def _links_near_the_text() -> Any:
    """Every link colour kept, those like the rows' own text too (before
    554)."""
    return patch.object(
        caption_marks, "link_colours", lambda _panel: caption_marks.LINK_COLORS
    )


def _links_while_spoken() -> Any:
    """A caption still being spoken linked as if it were finished."""
    real = captions.caption_rows

    def planted(caption: Any, *args: Any, **kwargs: Any) -> list[Any]:
        rows = real(caption, *args, **kwargs)
        if not caption.live:
            return rows
        settled = real(replace(caption, live=False), *args, **kwargs)
        if [r.text.removesuffix(LIVE_TRAIL) for r in rows] != [r.text for r in settled]:
            return rows
        return [replace(r, links=s.links) for r, s in zip(rows, settled, strict=True)]

    return patch.object(captions, "caption_rows", planted)


PLANTS: dict[str, tuple[Callable[[], Any], str]] = {
    "nudge": (_nudge, f"every row {NUDGE_PX:g} px lower from a canvas's third paint"),
    "fall": (_fall, f"every row {FALL_PX:g} px lower for one frame"),
    "slide": (_slide, f"a new row slides in from {SLIDE_PX:g} px to the right"),
    "step": (_step, "a caption that gains a row moves the stack in one frame"),
    "wrap": (_wrap, "a composed row keeps all its lines in one item"),
    "no-wait": (_no_wait, "a new wrapped row appears at once, over other text"),
    "swap-inks": (_swap_inks, "what was said in gold, its translation in white"),
    "full-while-spoken": (_full_while_spoken, "a live caption in full ink"),
    "no-step-back": (_no_step_back, "older captions as bright as the newest"),
    "shifted-links": (_shifted_links, "the translation's links one colour on"),
    "links-near-the-text": (_links_near_the_text, "link colours like the text kept"),
    "links-while-spoken": (_links_while_spoken, "a live caption's words linked"),
}


@contextmanager
def planted(name: str | None) -> Iterator[None]:
    """The display with the fault called `name` in it (None: as it is)."""
    if name is None:
        yield
        return
    make, _ = PLANTS[name]
    with make():
        yield
