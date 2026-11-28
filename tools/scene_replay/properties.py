"""The rules as properties of a replay's frames.

Each function reads the frames of one run and returns what breaks the rule:
an empty list means the rule held at every frame. They are plain Python over
`frames.Frame`, so the same property judges a later scene, or the Rust one,
from recorded frames with no window open.

One property per rule, named by the rule's id in `rules.toml`
(`PROPERTIES`).
"""

import itertools
from collections import Counter
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from typing import Any

from tools.scene_replay import inks
from tools.scene_replay.frames import FRAME, UNIT, Frame, Row, px

SLACK = 1
"""A move this small, in 1/64 px, is rounding, not a move."""

GLIDE_FASTEST = 300.0
"""Px a second: the approved glide's top speed (`views.cards.GLIDE_FASTEST`,
552 and 583; the tests check the product's own value is still this)."""
JUMP_PX = 6.0
JUMP_SPEED = 360.0
"""A jump: more than 6 px in one frame at more than 360 px a second (346's
thresholds, kept by 827's line replay)."""
OVERLAP_PX = 1.0
"""Two rows' ink overlaps when it shares more than this, both ways, in px."""


@dataclass(frozen=True)
class Broken:
    """One place a rule did not hold."""

    frame: int
    what: str

    def __str__(self) -> str:
        return f"frame {self.frame} ({self.frame * FRAME:.3f} s): {self.what}"


def _same_room(before: Frame, after: Frame) -> bool:
    """The window's size and the top of its text did not change: 969's
    condition for "no movement is asked for"."""
    return before.surfaces == after.surfaces


def never_fall(frames: Sequence[Frame]) -> list[Broken]:
    """No character that stays on screen is lower than it was a frame ago,
    while the window's size and the top of its text are unchanged."""
    broken = []
    for before, after in itertools.pairwise(frames):
        if before.rows is after.rows or not _same_room(before, after):
            continue
        old, new = before.chars(), after.chars()
        fell = [
            (new[key].top - old[key].top, key)
            for key in old.keys() & new.keys()
            if new[key].top > old[key].top + SLACK
        ]
        if fell:
            most, key = max(fell, key=lambda item: item[0])
            broken.append(
                Broken(
                    after.n,
                    f"{len(fell)} character(s) fell, one by {px(most):.2f} px"
                    f" (line {key[1]}, {key[2]}, on {key[0]})",
                )
            )
    return broken


def single_line(frames: Sequence[Frame]) -> list[Broken]:
    """Every row is one line of text: none holds a wrapped second line."""
    broken = []
    seen: set[tuple[str, int, str, int, int, int]] = set()
    for frame in frames:
        for row in frame.rows:
            if row.lines > 1 and row.id not in seen:
                seen.add(row.id)
                broken.append(
                    Broken(
                        frame.n,
                        f"a row holds {row.lines} lines"
                        f" (line {row.key}, {row.kind}, on {row.surface})",
                    )
                )
    return broken


def no_sideways_slide(frames: Sequence[Frame]) -> list[Broken]:
    """No character travels sideways: its left edge never changes in two
    frames running. (One step, when its caption's text is laid out again,
    is not a slide.)"""
    broken = []
    moved_before: set[Any] = set()
    for before, after in itertools.pairwise(frames):
        if before.rows is after.rows:
            moved_before = set()
            continue
        old, new = before.chars(), after.chars()
        moved = {
            key
            for key in old.keys() & new.keys()
            if abs(new[key].left - old[key].left) > SLACK
        }
        twice = moved & moved_before
        if twice:
            key = min(twice, key=str)
            broken.append(
                Broken(
                    after.n,
                    f"{len(twice)} character(s) moved sideways two frames running,"
                    f" one by {px(new[key].left - old[key].left):+.2f} px"
                    f" (line {key[1]}, {key[2]}, on {key[0]})",
                )
            )
        moved_before = moved
    return broken


def approved_glide(frames: Sequence[Frame]) -> list[Broken]:
    """A row that moves up or down never moves faster than the glide's top
    speed, and never jumps - except in the frame where a window put a
    burst of captions in place at once. A character that a new line break
    moves to another row is not this rule's (it is wrapping's)."""
    broken = []
    for before, after in itertools.pairwise(frames):
        if (
            before.rows is after.rows
            or before.bursts != after.bursts
            or not _same_room(before, after)
        ):
            continue
        old, new = before.placed_chars(), after.placed_chars()
        most = max(
            (abs(new[key].top - old[key].top) for key in old.keys() & new.keys()),
            default=0,
        )
        speed = px(most) / FRAME
        if px(most) > JUMP_PX and speed > JUMP_SPEED:
            broken.append(Broken(after.n, f"a jump of {px(most):.1f} px in one frame"))
        elif speed > GLIDE_FASTEST + SLACK / UNIT / FRAME:
            broken.append(
                Broken(after.n, f"text moving at {speed:.0f} px/s, over the glide's")
            )
    return broken


def _overlap(a: Row, b: Row) -> bool:
    across = min(a.ink[2], b.ink[2]) - max(a.ink[0], b.ink[0])
    down = min(a.ink[3], b.ink[3]) - max(a.ink[1], b.ink[1])
    return across > OVERLAP_PX * UNIT and down > OVERLAP_PX * UNIT


def waits_then_fades(frames: Sequence[Frame]) -> list[Broken]:
    """A row that is fading in never lies over other text and never moves
    while it fades; and no row ever appears on top of another's ink."""
    broken = []
    reported: set[object] = set()
    before_rows: dict[object, Row] = {}
    last: object = None
    for frame in frames:
        if frame.rows is last:
            continue
        last = frame.rows
        inked = [
            row for row in frame.rows if row.opacity > 0 and row.ink[2] > row.ink[0]
        ]
        for i, row in enumerate(inked):
            was = before_rows.get(row.id)
            fading = row.opacity < UNIT
            if (
                fading
                and was is not None
                and was.opacity > 0
                and (abs(was.top - row.top) > SLACK or abs(was.left - row.left) > SLACK)
                and ("moved", row.id) not in reported
            ):
                reported.add(("moved", row.id))
                broken.append(
                    Broken(
                        frame.n,
                        f"a row moved while fading in (line {row.key}, {row.kind},"
                        f" on {row.surface})",
                    )
                )
            for other in inked[i + 1 :]:
                pair = (row.id, other.id)
                if (
                    other.surface == row.surface
                    and pair not in reported
                    and _overlap(row, other)
                ):
                    reported.add(pair)
                    broken.append(
                        Broken(
                            frame.n,
                            f"two rows' ink overlaps on {row.surface}: line"
                            f" {row.key} {row.kind} and line {other.key} {other.kind}",
                        )
                    )
        before_rows = {row.id: row for row in frame.rows}
    return broken


# --- ink: read off the app's own picture of each frame (`inks`) ---

ORIGINAL_INK = 0xFFFFFF
TRANSLATION_INK = 0xFFD76E
"""The replay's look's own colours (a bare `CaptionLook`: Classic's), what
was said white and its translation gold; the tests check the product's are
still these."""
OWN = {"original": ORIGINAL_INK, "translation": TRANSLATION_INK}
FULL = 0.98
"""A row's own ink at least this much of the way from its paper to its
colour is full ink: within the picture's rounding and the glyphs' edges."""
LIVE_FULLEST = 0.92
"""Text still being spoken is fainter: none of it more than this much of
the way to its full colour. Today's is 0.85 (`caption_layout.Ink`)."""
STEP_LEAST = 0.008
"""An older caption steps back by at least this much of the way: two of
the picture's 256 levels on the default panel. Today's first step is about
0.013 (polyglotic-hq 996's measures)."""
NEW_FOR = 3.25
"""Seconds a caption may stay at full ink after it first showed: the Lab's
`new_for` (3 s, `views.lab.CaptionLab`) and a margin for the frame."""
OWN_LEAST = 0.3
"""A character this far or more along the way from the paper to a colour
is in that colour; nearer the paper, every colour's way looks alike."""
EDGE = round(3.0 * UNIT)
"""An underline's ends are soft by a pixel or two: a character whose ink
starts within 3 px of its end belongs to the next word, and one starting up
to 3 px before its start (its own side bearing) to this one."""
SAME_INK = 24.0
"""Two inks this near in RGB, as photographed, are one colour."""
APART_FROM_TEXT = 22.0
"""A word link's colour is at least this far (CIEDE2000) from its rows'
own colours (`word_classes.APART_FROM_TEXT`, 554; the tests check the
product's is still this)."""


CLEAR_ROWS = 3
"""A row this many of its own heights under the top of its surface is clear
of the fade a caption takes as it leaves over the top (`views.arrivals.
TOP_FADE_PAIRS`: one line pair), and its ink is its own."""


def _full(row: Row) -> bool:
    return (
        row.paper >= 0
        and row.opacity >= UNIT
        and row.scale == UNIT
        and row.kind in OWN
        and bool(row.chars)
    )


def _judged(frame: Frame) -> list[Row]:
    """The rows of `frame` whose ink is theirs alone to judge: at full
    opacity and size, inside their surface with the band under them, clear
    of the fade at its top, and over no other row's ink (that is the
    movement family's)."""
    surfaces = {s.name: s for s in frame.surfaces}
    band = round(inks.BAND_PX * UNIT)
    rows = [row for row in frame.rows if _full(row)]
    over: set[int] = set()
    for a, b in itertools.combinations(rows, 2):
        if a.surface == b.surface and _overlap(a, b):
            over.update((id(a), id(b)))
    found = []
    for row in rows:
        surface = surfaces.get(row.surface)
        if surface is None or id(row) in over:
            continue
        if row.top < surface.top + CLEAR_ROWS * row.height:
            continue
        if row.ink[3] + band > surface.foot:
            continue
        if row.ink[0] < 0 or row.ink[2] > surface.width:
            continue  # panned past an edge (Video Scrolling); joined: column 0
        found.append(row)
    return found


def _still(frames: Sequence[Frame]) -> list[Frame]:
    """The frames at rest, once each time the picture settles: the same as
    the frame before, so nothing is moving or fading in them."""
    found: list[Frame] = []
    before: object = None
    for frame in frames:
        if frame.rows == before and (not found or found[-1].rows != frame.rows):
            found.append(frame)
        before = frame.rows
    return found


def own_colours(frames: Sequence[Frame]) -> list[Broken]:
    """Every row is drawn in its own kind's colour: more of its characters
    on the way from the paper to its kind's colour than to the other's."""
    broken = []
    reported: set[object] = set()
    for frame in _still(frames):
        for row in _judged(frame):
            if row.id in reported:
                continue
            other = "translation" if row.kind == "original" else "original"
            mine = theirs = 0
            for colour in row.colours:
                share = inks.toward(colour, OWN[row.kind], row.paper)
                mine += share is not None and share > OWN_LEAST
                share = inks.toward(colour, OWN[other], row.paper)
                theirs += share is not None and share > OWN_LEAST
            if theirs > mine:
                reported.add(row.id)
                drawn = Counter(row.colours).most_common(1)[0][0]
                broken.append(
                    Broken(
                        frame.n,
                        f"a {row.kind} row is not in its own colour: mostly"
                        f" {inks.hex_of(drawn)} (line {row.key}, on {row.surface})",
                    )
                )
    return broken


def _faintest(row: Row) -> float | None:
    shares = [
        s
        for s in (inks.toward(c, OWN[row.kind], row.paper) for c in row.colours)
        if s is not None and s > 0.2
    ]
    return min(shares) if shares else None


def fainter_while_spoken(frames: Sequence[Frame]) -> list[Broken]:
    """Text still being spoken (a live caption) is drawn fainter than full
    ink: some of each of its rows at most `LIVE_FULLEST` of the way."""
    broken = []
    reported: set[object] = set()
    for frame in _still(frames):
        for row in _judged(frame):
            if row.state != "live" or row.key in reported:
                continue
            share = _faintest(row)
            if share is not None and share > LIVE_FULLEST:
                reported.add(row.key)
                broken.append(
                    Broken(
                        frame.n,
                        f"a caption still being spoken is in full ink ({share:.2f}"
                        f" of the way; line {row.key}, {row.kind}, on {row.surface})",
                    )
                )
    return broken


def _middle(values: list[float]) -> float:
    return sorted(values)[len(values) // 2]


def older_step_back(frames: Sequence[Frame]) -> list[Broken]:
    """The newest caption, once finished, is in full ink; a finished one
    before it is never brighter than a caption after it; and the finished
    caption nearest the newest is a step fainter than full ink once it has
    been up `NEW_FOR` seconds. The newest is the newest that is not Quick
    preview's line, finished or still being spoken."""
    broken = []
    reported: set[str] = set()
    first: dict[tuple[str, int], int] = {}

    def report(n: int, what: str, kind: str) -> None:
        if kind not in reported:
            reported.add(kind)
            broken.append(Broken(n, what))

    for frame in frames:
        for row in frame.rows:
            first.setdefault((row.surface, row.key), frame.n)
    for frame in _still(frames):
        by_key: dict[tuple[str, int], list[float]] = {}
        newest_of: dict[str, int] = {}
        for row in frame.rows:
            if row.state in ("live", "finished"):  # Quick preview's is newer still
                newest_of[row.surface] = max(newest_of.get(row.surface, -1), row.key)
        for row in _judged(frame):
            if row.state == "finished" and row.kind == "original":
                share = inks.own_share(row, ORIGINAL_INK)
                if share is not None:
                    by_key.setdefault((row.surface, row.key), []).append(share)
        for surface in sorted({s for s, _ in by_key}):
            keys = sorted(k for s, k in by_key if s == surface)
            shares = {k: _middle(by_key[surface, k]) for k in keys}
            newest = newest_of[surface]
            if newest in shares and shares[newest] < FULL:
                report(
                    frame.n,
                    "the newest finished caption is not in full ink"
                    f" ({shares[newest]:.2f}; line {newest}, on {surface})",
                    "newest",
                )
            for older, newer in itertools.pairwise(keys):
                if shares[older] > shares[newer] + STEP_LEAST / 2:
                    report(
                        frame.n,
                        f"an older caption is brighter than a newer one (line"
                        f" {older} {shares[older]:.3f}, line {newer}"
                        f" {shares[newer]:.3f}, on {surface})",
                        "brighter",
                    )
            earlier = [k for k in keys if k < newest]
            if earlier:
                before = earlier[-1]
                up = (frame.n - first[surface, before]) * FRAME
                if up >= NEW_FOR and shares[before] > 1.0 - STEP_LEAST:
                    report(
                        frame.n,
                        "a caption before the newest has not stepped back"
                        f" ({shares[before]:.3f}; line {before}, on {surface})",
                        "step",
                    )
    return broken


def one_link_colour(frames: Sequence[Frame]) -> list[Broken]:
    """A word link is one colour at both ends: every underline under what
    was said has one of the same colour under its translation, and the
    other way round; and the word over an underline is drawn in its
    colour."""
    broken = []
    reported: set[object] = set()
    for frame in _still(frames):
        clauses: dict[tuple[str, int, int], dict[str, list[int]]] = {}
        judged = _judged(frame)
        whole = Counter((r.surface, r.key, r.clause) for r in frame.rows)
        seen = Counter((r.surface, r.key, r.clause) for r in judged)
        for row in judged:
            ends = clauses.setdefault((row.surface, row.key, row.clause), {})
            ends.setdefault(row.kind, []).extend(colour for _, _, colour in row.bars)
            for left, right, colour in row.bars:
                over = [
                    c
                    for char, c in zip(row.chars, row.colours, strict=True)
                    if left - EDGE <= char.left < right - EDGE
                ]
                near = sum(inks.distance(c, colour) <= SAME_INK for c in over)
                if over and near * 2 < len(over) and ("word", row.id) not in reported:
                    reported.add(("word", row.id))
                    broken.append(
                        Broken(
                            frame.n,
                            "a linked word is not in its underline's colour"
                            f" {inks.hex_of(colour)} (line {row.key}, {row.kind},"
                            f" on {row.surface})",
                        )
                    )
        for where, ends in clauses.items():
            said, meant = ends.get("original"), ends.get("translation")
            if said is None or meant is None or where in reported:
                continue
            if seen[where] != whole[where]:
                continue  # part of the clause is not judged: its ends may be there
            alone = [
                c
                for mine, theirs in ((said, meant), (meant, said))
                for c in mine
                if not any(inks.distance(c, t) <= SAME_INK for t in theirs)
            ]
            if alone:
                reported.add(where)
                broken.append(
                    Broken(
                        frame.n,
                        f"a link's underline {inks.hex_of(alone[0])} has no"
                        f" counterpart of its colour (line {where[1]}, on {where[0]})",
                    )
                )
    return broken


def links_clear_of_the_text(frames: Sequence[Frame]) -> list[Broken]:
    """No word link's underline is in a colour that reads like its rows'
    own: each is at least `APART_FROM_TEXT` from both."""
    broken = []
    seen: set[int] = set()
    for frame in _still(frames):
        for row in _judged(frame):
            for _, _, colour in row.bars:
                if colour in seen:
                    continue
                seen.add(colour)
                near = min(inks.ciede2000(colour, own) for own in OWN.values())
                if near < APART_FROM_TEXT:
                    broken.append(
                        Broken(
                            frame.n,
                            f"a link in {inks.hex_of(colour)} reads like the rows'"
                            f" own colours ({near:.1f} apart; line {row.key})",
                        )
                    )
    return broken


def no_links_while_spoken(frames: Sequence[Frame]) -> list[Broken]:
    """The clause still being spoken has no word links: no underline under
    the last clause of a live caption."""
    broken = []
    reported: set[int] = set()
    for frame in _still(frames):
        for row in _judged(frame):
            if row.speaking and row.bars and row.key not in reported:
                reported.add(row.key)
                broken.append(
                    Broken(
                        frame.n,
                        "a caption still being spoken has a word link"
                        f" (line {row.key}, {row.kind}, on {row.surface})",
                    )
                )
    return broken


INK_PROPERTIES: dict[str, Callable[[Sequence[Frame]], list[Broken]]] = {
    "ink.own-colours": own_colours,
    "ink.fainter-while-spoken": fainter_while_spoken,
    "ink.older-captions-step-back": older_step_back,
    "ink.a-link-is-one-colour": one_link_colour,
    "ink.links-clear-of-the-text": links_clear_of_the_text,
    "ink.no-links-while-spoken": no_links_while_spoken,
}
"""The ink family's properties, by rule id. They judge frames whose ink was
read (`drive.play(..., ink=True)`); a frame without it gives them nothing
to judge."""


PROPERTIES: dict[str, Callable[[Sequence[Frame]], list[Broken]]] = {
    "movement.words-never-fall": never_fall,
    "wrapping.every-row-is-a-single-line": single_line,
    "movement.no-sideways-slide": no_sideways_slide,
    "movement.the-approved-glide": approved_glide,
    "movement.a-new-row-waits-then-fades-in": waits_then_fades,
}
"""Each rule's property, by its id in `tests/ui_next/rules/rules.toml`."""
