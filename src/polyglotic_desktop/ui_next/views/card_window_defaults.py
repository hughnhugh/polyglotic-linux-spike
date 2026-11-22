"""Settings for the card stack drawn by CaptionWindow (plain Python)."""

from polyglotic_desktop.core.shared.tunables import Applies, tunable

CARD_READ_SEC = tunable(
    "caption_window.card_read",
    1.9,
    "seconds",
    (1.0, 4.0),
    source="552 card stack; 556 subtitles; 583 depth",
)
"""How long the newest card stands before the next may push it: a line
isn't pushed while it is new (the user, 2026-11-20: "lines getting pushed
too much whilst I'm reading it")."""

CARD_STEP_SEC = tunable(
    "caption_window.card_step",
    0.5,
    "seconds",
    (0.2, 1.5),
    source="552 card stack; 556 subtitles; 583 depth",
)
"""A burst of cards (text held back, then let go) comes in one card at a
time, this far apart - so long as no more than `CARDS_KEPT_MOST` wait."""

CARD_WAIT_SEC = tunable(
    "caption_window.card_wait",
    0.6,
    "seconds",
    (0.0, 1.5),
    source="552 card stack; 556 subtitles; 583 depth",
)
"""The most a new card is kept back for that: its words are never later
than this."""

TRANSLATION_WAIT_SEC = tunable(
    "caption_window.translation_wait",
    2.5,
    "seconds",
    (1.0, 6.0),
    source="552 card stack; 556 subtitles; 583 depth",
)
"""A translation never waits longer than this to land, moving or not."""

CARD_CLEAR_PX = tunable(
    "caption_window.card_clear",
    0.0,
    "pixels",
    (0.0, 12.0),
    source="552 card stack; 556 subtitles; 583 depth",
)
"""A new card shows at full ink once the card before is this near to clear
of it."""

CARD_BAR_PX = tunable(
    "caption_window.card_bar",
    6,
    "pixels",
    (2.0, 16.0),
    source="552 card stack; 556 subtitles; 583 depth",
    applies=Applies.NEW_WINDOWS,
)
"""The cards' scroll bar's width: in the window's padding, beside the text."""

VIEW_GRACE_SEC = tunable(
    "caption_window.view_grace",
    0.5,
    "seconds",
    (0.2, 2.0),
    source="552 card stack; 556 subtitles; 583 depth",
)
"""The mouse came off the words: the view it held goes live this long
after - one glide - unless it comes back (polyglotic-hq 583, the user,
2026-11-21: "The mouse shouldn't hold up delivery, could hold up pushing
text by introducing back to live / new messages alert right?"). Captions
are never held for the mouse: until 583 they waited while it moved over
the words, 2 s at most (554)."""

SUBTITLE_CARD_ROWS = tunable(
    "caption_window.subtitle_card_rows",
    2.7,
    "rows",
    (2.0, 4.0),
    source="552 card stack; 556 subtitles; 583 depth",
)
"""One of Steady's cards in Video - what was said and its translation, the
gap after it and Chinese's taller line - in rows of text (556: two took
5.4 rows; one pair 3.0, measured)."""

BEAT_SEC = tunable(
    "subtitle.word_beat",
    0.18,
    "seconds",
    (0.06, 0.5),
    source="652 Video subtitle blocks",
)
"""Interval between words on each side. Both languages start together."""
WRAP_DROP = tunable(
    "subtitle.wrap_drop",
    0.25,
    "fraction",
    (0.0, 0.5),
    source="652 Video subtitle blocks",
)
"""Fraction of a line height travelled by the word opening a new line."""
PAN_ROOM = tunable(
    "subtitle.pan_room",
    0.16,
    "fraction",
    (0.0, 0.4),
    source="652 Video subtitle blocks",
)
"""Share of a wrapped, indivisible word's line available for horizontal travel."""

BASELINE_TOLERANCE_PX = tunable(
    "subtitle.baseline_tolerance",
    1.0,
    "pixels",
    (0.0, 2.0),
    source="672 Video subtitle page rounding",
)
"""Keep a readable baseline when rounding changes its slot by this much and the ink still fits."""


SPEED_SHARE = tunable(
    "subtitle.glide_share",
    0.75,
    "fraction",
    (0.5, 1.0),
    source="652 Video subtitle blocks",
)
"""Reserve frame scheduling headroom below the shared maximum paint speed."""

OWN_SUBTITLE_SIZE = tunable(
    "subtitle.own_size", 0.85, "fraction", (0.5, 1.0), source="668 Video own speech"
)
"""Size of the two own-speech rows as a share of the window's caption size."""


OWN_SUBTITLE_ROOM = tunable(
    "subtitle.own_room", 0.25, "fraction", (0.1, 0.4), source="668 Video own speech"
)
"""Maximum share of the usable Video window for both own-speech rows in a shallow window."""
