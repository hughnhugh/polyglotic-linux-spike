"""Speaking pace uses voiced time, never pauses or processing time."""

from time import perf_counter

from polyglotic_desktop.core.listening.pace import PaceMeter


def test_pause_does_not_lower_now_but_two_seconds_silence_shows_zero() -> None:
    pace = PaceMeter()
    assert pace.now(10.0) == 0
    assert pace.add(10, 2.0, 10.0) == 300
    assert pace.now(11.9) == 300
    assert pace.now(12.1) == 0
    assert pace.mean == 300


def test_last_five_seconds_of_speech_and_peak_ignore_wall_clock_gaps() -> None:
    pace = PaceMeter()
    assert pace.add(10, 2.0, 1.0) == 300
    assert pace.add(6, 3.0, 100.0) == 192
    assert pace.add(10, 2.0, 101.0) == 192
    assert pace.peak == 300
    assert pace.mean == round(26 * 60 / 7)


def test_voiced_seconds_are_banded_without_content() -> None:
    pace = PaceMeter()
    pace.add(2, 2.0, 0.0)
    pace.add(8, 2.0, 1.0)
    assert pace.seconds == {
        "1_60": 2,
        "61_120": 0,
        "121_180": 2,
        "181_240": 0,
        "241_plus": 0,
    }


def test_a_speaking_second_counts_only_when_its_bucket_has_words() -> None:
    pace = PaceMeter()
    pace.add(0, 1.0, 0.0)
    pace.add(1, 1.0, 1.0)
    assert sum(pace.seconds.values()) == 1


def test_add_stays_within_the_point_zero_five_ms_budget() -> None:
    pace = PaceMeter()
    started = perf_counter()
    for n in range(10_000):
        pace.add(3, 0.4, float(n))
    elapsed_ms = (perf_counter() - started) * 1_000 / 10_000
    assert elapsed_ms < 0.05
