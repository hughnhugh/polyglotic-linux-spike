"""Steady's and Calm's wave (polyglotic-hq 1070): established text lit
letter by letter at the speaker's pace, behind a soft front.

The founder, 2026-11-29: "Can you also make the word letters themselves
establish smoothly too? like a clean mexican wave in line with the pace of
the speech (basically smoothed out)".

The playout shows a word at the moment it was said plus its delay, and
says how long it took to say (`CaptionUpdate.lighting`). A row's newly
established letters begin to light one after another across that time -
each character of Chinese, Japanese or Korean a letter of its own - and
each eases from the waiting ink to the full ink over `WAVE_FADE`: the
letters part way are the front, a few letters wide. A row's letters never
begin out of order: a word shown before the last one finished lighting
takes the rest of it along, spread over its own time. With the OS's reduced
motion on, the window gives no time, and words light whole, as before.

`Wave` is one row's letters; `Waves` a window's rows, by line and row.
Plain Python, no Qt, no clock of its own. Holds no caption text.
"""

from collections.abc import Hashable
from dataclasses import dataclass, field

from polyglotic_desktop.core.shared.tunables import tunable

WAVE_FADE = tunable(
    "wave.fade",
    0.16,
    "seconds",
    (0.05, 0.4),
    source="1070 the wave (brief: about 120-200 ms)",
)
"""How long one letter takes from the waiting ink to the full ink: at the
speaker's pace (about 15 letters a second) the front is two or three
letters wide - a soft edge, not a smear - and a word is never left half
lit for long."""


def ease(share: float) -> float:
    """Eased in and out (smoothstep): 0 at 0, 1 at 1."""
    x = min(1.0, max(0.0, share))
    return x * x * (3.0 - 2.0 * x)


@dataclass(frozen=True, slots=True)
class Lit:
    """A row's letters as lit at one moment: the first `full` all the way,
    each in `front` after them part way (from the most lit), the rest not
    begun."""

    full: int
    front: tuple[float, ...] = ()

    def within(self, start: int, length: int) -> "Lit":
        """The same, for the `length` letters from `start` (a row laid out
        over more than one line: one of its lines)."""
        full = min(length, max(0, self.full - start))
        if full < length and start > self.full:
            skip = start - self.full
            return Lit(full, self.front[skip : skip + length])
        return Lit(full, self.front[: length - full] if full < length else ())


@dataclass(slots=True)
class Wave:
    """One row's letters: when each began to light, in order."""

    starts: list[float] = field(default_factory=list)

    def to(self, established: int, now: float, over: float, text: str = "") -> None:
        """The row, whose text is `text`, has `established` letters
        established as of `now`: the new ones begin to light across `over`
        seconds (0: all at once), with any still waiting to begin - its
        letters and digits one after another, as they were said, each space
        or mark with the letter before it. Fewer than before (a
        correction): the letters after them go."""
        if established <= len(self.starts):
            del self.starts[established:]
            return
        waiting = next(
            (n for n, start in enumerate(self.starts) if start > now), len(self.starts)
        )
        new = text[waiting:established]
        if len(new) < established - waiting:  # no text: each character a letter
            new = "a" * (established - waiting)
        letters = sum(1 for char in new if char.isalnum()) or 1
        step = over / letters if over > 0.0 else 0.0
        at, begun, starts = now, 0, []
        for char in new:
            if char.isalnum():
                at = now + step * begun
                begun += 1
            starts.append(at)
        self.starts[waiting:] = starts

    def lit(self, now: float, fade: float) -> Lit:
        full = 0
        front: list[float] = []
        for start in self.starts:
            amount = 1.0 if fade <= 0.0 else ease((now - start) / fade)
            if amount >= 1.0 and not front:
                full += 1
            elif amount <= 0.0:
                break
            else:
                front.append(amount)
        return Lit(full, tuple(front))

    def moving(self, now: float, fade: float) -> bool:
        """Whether a letter is still lighting."""
        return bool(self.starts) and now < self.starts[-1] + fade


RowKey = tuple[int, Hashable, int]
"""A row by its line's key, its kind and its clause."""


@dataclass(slots=True)
class Waves:
    """A window's rows that light letter by letter, by `RowKey`."""

    rows: dict[RowKey, Wave] = field(default_factory=dict)
    seen: set[RowKey] = field(default_factory=set)

    def to(
        self, key: RowKey, established: int, now: float, over: float, text: str = ""
    ) -> Wave:
        """Row `key`, of text `text`, has `established` letters established
        as of `now` (`Wave.to`): a row first seen lights them from its
        first letter."""
        self.seen.add(key)
        wave = self.rows.setdefault(key, Wave())
        wave.to(established, now, over, text)
        return wave

    def has(self, line: int) -> bool:
        """Whether line `line` has rows here: it was drawn live."""
        return any(key[0] == line for key in self.rows)

    def moving(self, now: float, fade: float) -> set[int]:
        """The lines a letter is still lighting on."""
        return {key[0] for key, wave in self.rows.items() if wave.moving(now, fade)}

    def forget(self, line: int) -> None:
        """Line `line`'s rows light no more: it is drawn as it stands."""
        for key in [key for key in self.rows if key[0] == line]:
            del self.rows[key]

    def drawn(self) -> None:
        """A paint is done: rows it did not draw are forgotten."""
        for key in self.rows.keys() - self.seen:
            del self.rows[key]
        self.seen.clear()
