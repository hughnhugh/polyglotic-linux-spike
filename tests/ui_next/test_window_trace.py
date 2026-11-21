"""A caption window marks the caption timelines (perf.trace; polyglotic-hq 543):
when it puts an update into its view, when it paints, and why it kept one
waiting - the mouse over it, or the Lab's gap between new captions. The
user's "delay and then process it all at once" is visible there: the
updates reach the window in time, and the window lets them in together."""

from collections.abc import Iterator
from dataclasses import replace

import pytest
from PySide6.QtWidgets import QApplication
from tests.ui_next.made_up import finished_updates
from tests.ui_next.test_arrival_gap import paced
from tests.ui_next.test_caption_window import window_of

from polyglotic_desktop.core.listening.captions import CaptionUpdate, SpeechTimes
from polyglotic_desktop.perf import trace
from polyglotic_desktop.perf.trace import Tracer, speech_key
from polyglotic_desktop.ui_next.views.captions import CaptionLines


@pytest.fixture
def tracer() -> Iterator[Tracer]:
    made = Tracer()
    before = trace.use(made)
    yield made
    trace.use(before)


def numbered(tracer: Tracer, updates: list[CaptionUpdate]) -> list[CaptionUpdate]:
    """`updates`, each sent and answered as numbered frames."""
    out = []
    for n, update in enumerate(updates):
        seq = tracer.sending(
            speech_key(update.caption_id, update.kind.value, None, float(n)),
            "video",
            1.0,
            taken=tracer.clock(),
        )
        tracer.mark(seq, "applied")
        out.append(replace(update, times=SpeechTimes(0.0, float(n), 0.0, 0.0, seq=seq)))
    return out


def test_updates_the_mouse_held_are_windowed_when_it_lets_them_in(
    qapp: QApplication, tracer: Tracer
) -> None:
    window = window_of(qapp, captions=2)
    try:
        window._hold()  # the mouse moves over the window
        updates = numbered(tracer, finished_updates(2, start=2))
        for update in updates:
            assert window.receive(update) is False
        tracer.painted()  # a paint while they wait shows none of them
        assert all(r["end"] != "painted" for r in tracer.recent())
        window.let_in()
        window.repaint()
        tracer.flush()
        done = {r["seq"]: r for r in tracer.recent()}
        for update in updates:
            assert update.times is not None
            record = done[update.times.seq]
            assert record["held"] == "mouse"
            assert "windowed" in record["t"] and record["end"] == "painted"
    finally:
        window.close()


def test_updates_the_gap_held_say_so(qapp: QApplication, tracer: Tracer) -> None:
    window, _ = paced(qapp, 0.5)
    try:
        first, second = numbered(tracer, finished_updates(2, start=2))
        assert window.receive(first) is True
        assert window.receive(second) is False  # waits for the gap
        tracer.flush()
        held = {r["seq"]: r.get("held") for r in tracer.recent()}
        assert first.times is not None and second.times is not None
        assert held[first.times.seq] is None
        assert held[second.times.seq] == "gap"
    finally:
        window.close()


def test_only_a_window_marks_an_update_on_screen(tracer: Tracer) -> None:
    """A transcript collects each update into lines of its own, unseen (its
    `CaptionLines`): that isn't the screen. The first real run (543, 346's
    loop) had every update held by the mouse marked shown at once, by the
    transcript."""
    (update,) = numbered(tracer, finished_updates(1, start=2))
    lines = CaptionLines((update.source_id,), None, keep=10)
    assert lines.apply(update)
    tracer.flush()
    [done] = tracer.recent()
    assert "windowed" not in done["t"]
