"""The ink of a replayed frame, read from the app's own picture of it.

The replay's frames say where each row and character is (`drive`); this
says what colour each was drawn in, by looking: the surface is photographed
through the UI lab's `photograph` (`tools/ui_lab/lab.py`: the window's own
`render`, over the lab's stand-in video for a see-through window) and each
character's glyph box is read off the picture. Whatever decides a colour,
in the layout, the marks or inside the paint, what is read is what a
learner would see.

- **paper:** the colour a row is drawn on: the commonest colour in its box.
- **a character's ink:** the pixel of its glyph box that stands out most
  from the paper (the middle of a stroke, where nothing of the paper
  shows through).
- **bars:** what is drawn in the band just under a row's text, where a
  word link's underline goes (`caption_layout._link_bars`), outside every
  glyph: each run of it, and its colour.

A colour is a 0xRRGGBB number. Reading ink costs a photograph of each frame
the window repainted (about 1 ms offscreen); the replay reads it only when
asked (`drive.play(..., ink=True)`), so the matrix's frames and digests are
as they were without it.
"""

from collections.abc import Sequence
from dataclasses import dataclass, replace

import numpy as np
from PySide6.QtGui import QImage

from tools.scene_replay.frames import UNIT, Frame, Row, q
from tools.ui_lab import goldens

STANDS_OUT = 40.0
"""A pixel this far from its row's paper, as a distance in RGB (0-441), is
drawn on it: well above the paper's own noise (0 offscreen) and well below
the faintest ink the display draws (Video's waiting words at half ink on a
dark panel, about 110)."""
STRONG = 0.5
"""A character's ink is the commonest colour among the pixels of its glyph
box that stand out at least this share as far as the strongest: the inside
of its strokes. Not the single strongest pixel: a neighbour's stroke can
reach into a glyph's box (Chinese characters set close), and white stands
further from a dark panel than any link's colour."""
BAND_PX = 10.0
"""How far under a row's text, in px at the text's own size, a word link's
underline is looked for: the widest gap and the thickest bar the look offers
(`views.caption_window.LINK_GAP_PX`, `LINK_PX`) with room to spare, and
less than the room to the next row's ink."""
BAR_LEAST = 3
"""Px: a run narrower than this under a row is a stray edge of something
else (the next item's underline, a glyph's soft edge), not an underline;
the narrowest linked word, one Latin letter at the smallest text, is
wider."""
FONT_PX = 21.0
"""The text size the band is measured at (`caption_layout._link_bars`
scales a bar by the font's px over this)."""


@dataclass(frozen=True)
class Shape:
    """Where one row's ink can be, for reading it off a picture: each
    character's glyph box and the bottom of each of its text lines, in px in
    the photographed widget's coordinates."""

    boxes: tuple[tuple[float, float, float, float], ...]
    """Left, top, right, bottom; one per character of the row, in order."""
    unders: tuple[tuple[float, float, float], ...]
    """Left, right and bottom of each text line: its band starts there."""
    font_px: float
    state: str = ""
    """Its caption's state (`frames.Row.state`), kept with the ink."""
    speaking: bool = False
    """It is a row of the clause still being spoken (`frames.Row.speaking`)."""


def rgb(colour: int) -> tuple[int, int, int]:
    return (colour >> 16) & 255, (colour >> 8) & 255, colour & 255


def hex_of(colour: int) -> str:
    return f"#{colour:06x}"


def distance(a: int, b: int) -> float:
    """How far apart two colours are, in RGB (0-441)."""
    return float(np.linalg.norm(np.subtract(rgb(a), rgb(b), dtype=float)))


def _packed(pixels: np.ndarray) -> np.ndarray:
    as_int = pixels[..., :3].astype(np.int64)
    packed: np.ndarray = (as_int[..., 0] << 16) | (as_int[..., 1] << 8) | as_int[..., 2]
    return packed


def _span(low: float, high: float, size: int) -> tuple[int, int]:
    return max(0, int(np.floor(low))), min(size, int(np.ceil(high)))


def _paper(packed: np.ndarray, row: Row) -> int:
    height, width = packed.shape
    y0, y1 = _span(row.top / UNIT, (row.top + row.height) / UNIT, height)
    x0, x1 = _span(row.left / UNIT - 2, (row.left + row.width) / UNIT + 2, width)
    if y1 <= y0 or x1 <= x0:
        return -1
    values, counts = np.unique(packed[y0:y1, x0:x1], return_counts=True)
    return int(values[int(np.argmax(counts))])


def _stands_out(pixels: np.ndarray, paper: int) -> np.ndarray:
    """Each pixel's distance from `paper`."""
    away = pixels[..., :3].astype(float) - np.array(rgb(paper), dtype=float)
    found: np.ndarray = np.sqrt((away**2).sum(axis=-1))
    return found


def _ink(
    pixels: np.ndarray, packed: np.ndarray, box: Sequence[float], paper: int
) -> int:
    height, width = packed.shape
    y0, y1 = _span(box[1], box[3], height)
    x0, x1 = _span(box[0], box[2], width)
    if y1 <= y0 or x1 <= x0:
        return paper
    away = _stands_out(pixels[y0:y1, x0:x1], paper)
    strong = packed[y0:y1, x0:x1][away >= STRONG * float(away.max())]
    values, counts = np.unique(strong, return_counts=True)
    return int(values[int(np.argmax(counts))])


def _bars(
    pixels: np.ndarray,
    packed: np.ndarray,
    shape: Shape,
    paper: int,
    glyphs: np.ndarray,
) -> tuple[tuple[int, int, int], ...]:
    height, width = packed.shape
    found = []
    band = BAND_PX * max(0.5, shape.font_px / FONT_PX)
    for left, right, bottom in shape.unders:
        y0, y1 = _span(bottom, bottom + band, height)
        x0, x1 = _span(left, right, width)
        if y1 <= y0 or x1 <= x0:
            continue
        away = _stands_out(pixels[y0:y1, x0:x1], paper)
        away[glyphs[y0:y1, x0:x1]] = 0.0
        strongest = away.max(axis=0)
        rows = away.argmax(axis=0)
        columns = [
            (int(packed[y0 + int(rows[x]), x0 + x]), float(strongest[x]))
            if strongest[x] > STANDS_OUT
            else None
            for x in range(strongest.size)
        ]
        found += [
            (q(x0 + start), q(x0 + end), colour)
            for start, end, colour in _runs(columns, paper)
            if end - start >= BAR_LEAST
        ]
    return tuple(found)


def _runs(
    columns: Sequence[tuple[int, float] | None], paper: int
) -> list[tuple[int, int, int]]:
    """Each run of drawn columns, as its first and end column and its
    colour (its strongest column's). Two underlines that touch (two linked
    words side by side) are two runs: a column in a colour that is not on
    the way from the paper to the run's colour, nor the other way round,
    starts a new one."""
    found = []
    start, colour, strength = -1, 0, 0.0
    for x, column in enumerate((*columns, None)):
        if column is not None and start >= 0:
            ink, power = column
            if (
                toward(ink, colour, paper) is None
                and toward(colour, ink, paper) is None
            ):
                found.append((start, x, colour))
                start = -1
            elif power > strength:
                colour, strength = ink, power
                continue
            else:
                continue
        if column is None:
            if start >= 0:
                found.append((start, x, colour))
            start = -1
        else:
            start, (colour, strength) = x, column
    return found


def read(image: QImage, frame: Frame, shapes: Sequence[Shape]) -> Frame:
    """`frame` with each row's paper, its characters' ink and its bars, as
    `image` (the photographed widget) shows them. `shapes`: one per row."""
    pixels = goldens.pixels(image)
    packed = _packed(pixels)
    height, width = packed.shape
    glyphs = np.zeros((height, width), dtype=bool)
    for shape in shapes:
        for left, top, right, bottom in shape.boxes:
            y0, y1 = _span(top, bottom, height)
            x0, x1 = _span(left, right, width)
            glyphs[y0:y1, x0:x1] = True
    rows = []
    for row, shape in zip(frame.rows, shapes, strict=True):
        if row.opacity <= 0 or not row.chars:
            rows.append(row)
            continue
        paper = _paper(packed, row)
        if paper < 0:
            rows.append(row)
            continue
        colours = tuple(_ink(pixels, packed, box, paper) for box in shape.boxes)
        bars = _bars(pixels, packed, shape, paper, glyphs)
        rows.append(
            replace(
                row,
                paper=paper,
                colours=colours,
                bars=bars,
                state=shape.state,
                speaking=shape.speaking,
            )
        )
    return replace(frame, rows=tuple(rows))


# --- judging colours: the measures the ink rules are stated in ---


def _linear(channel: int) -> float:
    c = channel / 255
    return c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4


def luminance(colour: int) -> float:
    """WCAG 2.2's relative luminance."""
    r, g, b = (_linear(c) for c in rgb(colour))
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


def contrast(a: int, b: int) -> float:
    """WCAG 2.2's contrast ratio, 1-21."""
    high, low = sorted((luminance(a), luminance(b)), reverse=True)
    return (high + 0.05) / (low + 0.05)


def _lab(colour: int) -> tuple[float, float, float]:
    r, g, b = (_linear(c) for c in rgb(colour))
    x = (0.4124 * r + 0.3576 * g + 0.1805 * b) / 0.95047
    y = 0.2126 * r + 0.7152 * g + 0.0722 * b
    z = (0.0193 * r + 0.1192 * g + 0.9505 * b) / 1.08883

    def f(t: float) -> float:
        return t ** (1 / 3) if t > (6 / 29) ** 3 else t / (3 * (6 / 29) ** 2) + 4 / 29

    fx, fy, fz = f(x), f(y), f(z)
    return 116 * fy - 16, 500 * (fx - fy), 200 * (fy - fz)


def ciede2000(a: int, b: int) -> float:
    """How far apart two colours look: CIEDE2000 (Sharma, Wu and Dalal,
    2005), the measure the product's own colour choices are stated in."""
    import math

    l1, a1, b1 = _lab(a)
    l2, a2, b2 = _lab(b)
    c1, c2 = math.hypot(a1, b1), math.hypot(a2, b2)
    mean_c = (c1 + c2) / 2
    g = 0.5 * (1 - math.sqrt(mean_c**7 / (mean_c**7 + 25**7)))
    a1p, a2p = (1 + g) * a1, (1 + g) * a2
    c1p, c2p = math.hypot(a1p, b1), math.hypot(a2p, b2)
    h1p = math.degrees(math.atan2(b1, a1p)) % 360
    h2p = math.degrees(math.atan2(b2, a2p)) % 360
    dl, dc = l2 - l1, c2p - c1p
    if c1p * c2p == 0:
        dh = 0.0
    elif abs(h2p - h1p) <= 180:
        dh = h2p - h1p
    else:
        dh = h2p - h1p - 360 if h2p > h1p else h2p - h1p + 360
    big_dh = 2 * math.sqrt(c1p * c2p) * math.sin(math.radians(dh / 2))
    mean_l, mean_cp = (l1 + l2) / 2, (c1p + c2p) / 2
    if c1p * c2p == 0:
        mean_h = h1p + h2p
    elif abs(h1p - h2p) <= 180:
        mean_h = (h1p + h2p) / 2
    else:
        mean_h = (h1p + h2p + 360) / 2 if h1p + h2p < 360 else (h1p + h2p - 360) / 2
    t = (
        1
        - 0.17 * math.cos(math.radians(mean_h - 30))
        + 0.24 * math.cos(math.radians(2 * mean_h))
        + 0.32 * math.cos(math.radians(3 * mean_h + 6))
        - 0.20 * math.cos(math.radians(4 * mean_h - 63))
    )
    sl = 1 + 0.015 * (mean_l - 50) ** 2 / math.sqrt(20 + (mean_l - 50) ** 2)
    sc = 1 + 0.045 * mean_cp
    sh = 1 + 0.015 * mean_cp * t
    rt = (
        -2
        * math.sqrt(mean_cp**7 / (mean_cp**7 + 25**7))
        * math.sin(math.radians(60 * math.exp(-(((mean_h - 275) / 25) ** 2))))
    )
    return math.sqrt(
        (dl / sl) ** 2
        + (dc / sc) ** 2
        + (big_dh / sh) ** 2
        + rt * (dc / sc) * (big_dh / sh)
    )


ON_THE_WAY = 24.0
"""A colour this near (RGB) the straight way from the paper to a row's own
colour is that colour drawn fainter: its own ink, not another's."""


def toward(colour: int, own: int, paper: int) -> float | None:
    """How much of the way from `paper` to `own` `colour` is (1: `own` at
    full ink), or None if it is not on that way (another colour)."""
    p, o, c = (np.array(rgb(x), dtype=float) for x in (paper, own, colour))
    way = o - p
    length = float(way @ way)
    if length == 0:
        return None
    share = float((c - p) @ way) / length
    off = float(np.linalg.norm(c - (p + share * way)))
    return share if off <= ON_THE_WAY else None


def own_share(row: Row, own: int) -> float | None:
    """How full the row's own ink is: the middle share of its characters
    drawn in `own` (`toward`); None if none is."""
    shares = sorted(
        s for s in (toward(c, own, row.paper) for c in row.colours) if s is not None
    )
    return shares[len(shares) // 2] if shares else None
