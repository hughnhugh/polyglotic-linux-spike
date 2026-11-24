"""Constant-space measurement of pace over time actually spent speaking."""

from dataclasses import dataclass, field

WINDOW_SECONDS = 5
SILENT_AFTER_SECONDS = 2.0
PACE_BANDS = ("1_60", "61_120", "121_180", "181_240", "241_plus")


@dataclass(frozen=True, slots=True)
class PaceReading:
    """A pace value plus the counts needed to combine visible own speech."""

    now: int
    mean: int
    recent_words: float
    recent_seconds: float
    total_words: int
    total_seconds: float

    def combined(self, other: "PaceReading") -> "PaceReading":
        recent_words = self.recent_words + other.recent_words
        recent_seconds = self.recent_seconds + other.recent_seconds
        total_words = self.total_words + other.total_words
        total_seconds = self.total_seconds + other.total_seconds
        return PaceReading(
            round(recent_words * 60 / recent_seconds) if recent_seconds else 0,
            round(total_words * 60 / total_seconds) if total_seconds else 0,
            recent_words,
            recent_seconds,
            total_words,
            total_seconds,
        )


def _band(wpm: int) -> str | None:
    if wpm <= 0:
        return None
    if wpm <= 60:
        return PACE_BANDS[0]
    if wpm <= 120:
        return PACE_BANDS[1]
    if wpm <= 180:
        return PACE_BANDS[2]
    if wpm <= 240:
        return PACE_BANDS[3]
    return PACE_BANDS[4]


@dataclass(slots=True)
class PaceMeter:
    """Current and window-average WPM, excluding every non-speech gap."""

    _index: int = 0
    _words: list[float] = field(default_factory=lambda: [0.0] * WINDOW_SECONDS)
    _durations: list[float] = field(default_factory=lambda: [0.0] * WINDOW_SECONDS)
    _total_words: int = 0
    _total_duration: float = 0.0
    _peak: int = 0
    _last_spoken_at: float | None = None
    _bands: dict[str, float] = field(
        default_factory=lambda: dict.fromkeys(PACE_BANDS, 0.0)
    )

    def add(self, count: int, voiced_seconds: float, at: float) -> int:
        """Add one finished caption; words and voiced duration count once."""
        count = max(0, count)
        duration = max(0.0, voiced_seconds)
        if not count or not duration:
            return self.now(at)
        self._last_spoken_at = at
        self._total_words += count
        self._total_duration += duration
        # Only the tail can remain in the rolling window. This also bounds the
        # loop to five buckets for an unusually long caption.
        remaining = min(duration, float(WINDOW_SECONDS))
        words_left = count * remaining / duration
        rolling_words = words_left
        while remaining > 0:
            if self._durations[self._index] >= 1.0 - 1e-9:
                self._index = (self._index + 1) % WINDOW_SECONDS
                self._durations[self._index] = 0.0
                self._words[self._index] = 0.0
            room = 1.0 - self._durations[self._index]
            used = min(room, remaining)
            share = (
                words_left
                if used == remaining
                else rolling_words * used / min(duration, float(WINDOW_SECONDS))
            )
            self._durations[self._index] += used
            self._words[self._index] += share
            remaining -= used
            words_left -= share
        current = self.now(at)
        self._peak = max(self._peak, current)
        band = _band(current)
        if band is not None:
            self._bands[band] += duration
        return current

    def now(self, at: float) -> int:
        """Current WPM, becoming zero after two wall-clock seconds quiet."""
        if (
            self._last_spoken_at is None
            or at - self._last_spoken_at > SILENT_AFTER_SECONDS
        ):
            return 0
        duration = sum(self._durations)
        return round(sum(self._words) * 60 / duration) if duration else 0

    def reading(self, at: float) -> PaceReading:
        """Current and lifetime pace, retaining only content-free counts."""
        active = self.now(at) != 0
        recent_words = sum(self._words) if active else 0.0
        recent_seconds = sum(self._durations) if active else 0.0
        return PaceReading(
            self.now(at),
            self.mean,
            recent_words,
            recent_seconds,
            self._total_words,
            self._total_duration,
        )

    @property
    def peak(self) -> int:
        return self._peak

    @property
    def mean(self) -> int:
        return (
            round(self._total_words * 60 / self._total_duration)
            if self._total_duration
            else 0
        )

    @property
    def seconds(self) -> dict[str, int]:
        return {key: round(value) for key, value in self._bands.items()}
