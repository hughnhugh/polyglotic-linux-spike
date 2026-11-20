"""What a stretch of caption timelines says (perf.trace_summary; polyglotic-hq 543):
segments, hangs and their causes, bursts, drops - and the usage statistics
and problem report made from them."""

import json
from typing import Any

from polyglotic_desktop.perf.trace import Tracer
from polyglotic_desktop.perf.trace_summary import (
    SAMPLES_KEPT,
    SessionTimelines,
    Summary,
    compact,
    expand,
    report_text,
    segments,
    summarise,
    usage_properties,
)

# polyglotic-server's docs/tracking-plan.yaml, caption_timeline_summarised
PLAN = {
    "caption_mode", "live_interval_seconds", "listening_seconds", "platform",
    "updates", "shown", "hangs", "bursts", "drops", "held_mouse", "held_gap",
    "interface_stalls",
    *(
        f"{s}_p{p}_ms"
        for s in ("capture", "detect", "app_queue", "network", "server_queue",
                  "server_work", "interface_queue", "window_hold", "total")
        for p in (50, 95)
    ),
    *(
        f"hangs_{c}"
        for c in ("dropped", "not_asked", "pause", "capture", "detect", "encode",
                  "app_queue", "send", "network", "server_queue", "server_work",
                  "interface_queue", "apply", "window_hold", "paint", "unknown")
    ),
}  # fmt: skip


def update(
    seq: int,
    captured: float,
    shown: float,
    source: str = "video",
    audio: float = 3.0,
    held: str | None = None,
    end: str = "painted",
    windowed: float | None = None,
) -> dict[str, Any]:
    """A live update heard at `captured`, quick all the way to the
    interface thread (0.15 s), then shown at `shown`."""
    t = {
        "captured": captured,
        "heard": captured,
        "delivered": captured + 0.01,
        "detected": captured + 0.02,
        "encoded": captured + 0.03,
        "taken": captured + 0.04,
        "sent": captured + 0.05,
        "received": captured + 0.14,
        "handed": captured + 0.145,
        "applied": captured + 0.15,
    }
    if end == "painted":
        t["windowed"] = windowed if windowed is not None else shown - 0.005
        t["painted"] = shown
    found: dict[str, Any] = {
        "seq": seq, "cap": "c1", "kind": "live", "sec": 0, "src": source,
        "audio": audio, "t": t, "end": end,
        "srv": {"waited": 10, "queued": 1, "server": 60},
    }  # fmt: skip
    if held:
        found["held"] = held
    return found


def test_an_updates_segments_split_the_network_from_the_server() -> None:
    parts = segments(update(1, 10.0, 10.2))
    assert round(parts["network"]) == 30  # a 90 ms round trip, 60 on the server
    assert parts["server_queue"] == 10 and parts["server_work"] == 50
    assert round(parts["total"]) == 200
    assert round(parts["capture"]) == 10 and round(parts["app_queue"]) == 10


def test_a_window_holding_updates_is_a_hang_put_down_to_it() -> None:
    """The user's symptom (2026-11-20): "delay and then process it all at
    once". Live updates every 0.5 s reach the interface at once, but the
    caption window lets them in 3 s later, together."""
    records = [update(n, 10.0 + n * 0.5, 10.0 + n * 0.5 + 0.2) for n in range(4)]
    held_until = 15.2
    records += [
        update(
            n,
            10.0 + n * 0.5,
            held_until + 0.01 * (n - 4),
            held="mouse",
            windowed=held_until,
        )
        for n in range(4, 10)
    ]
    found = summarise(records)
    assert [h.cause for h in found.hangs] == ["window_hold"]
    assert found.hangs[0].seconds > 2.0
    assert len(found.bursts) == 1 and found.bursts[0][1] == 6
    assert found.held["mouse"] == 6


def test_a_new_captions_updates_held_from_its_start_are_a_hang() -> None:
    """346's loop with the mouse over the window (543, 2026-11-20): the last
    caption showed at 21.5 s, the next began at 24.3 s, and its live updates
    from 25.6 s were let in together at 34.4 s. The speech began after the
    last update showed, so the hang runs from its start."""
    held = [
        update(
            n, 25.6 + n * 0.5, 34.4, audio=1.3 + n * 0.5, held="mouse", windowed=34.4
        )
        for n in range(1, 6)
    ]
    found = summarise([update(0, 21.0, 21.5, audio=3.0), *held])
    [hang] = found.hangs
    assert hang.cause == "window_hold"
    assert round(hang.seconds, 1) == round(34.4 - (26.1 - 1.8), 1)  # from 24.3 s


def test_nothing_asked_in_between_is_not_put_down_to_a_segment() -> None:
    """The speech paused (shorter than the hangover): no update was asked
    for 2.5 s, and the next was quick."""
    found = summarise(
        [update(1, 10.0, 10.2, audio=1.0), update(2, 12.6, 12.8, audio=3.6)]
    )
    assert [h.cause for h in found.hangs] == ["not_asked"]


def test_an_update_dropped_in_between_is_the_cause() -> None:
    dropped = update(2, 10.5, 0.0, end="unanswered:overtaken_waiting")
    found = summarise([update(1, 10.0, 10.2), dropped, update(3, 10.6, 13.0)])
    assert [h.cause for h in found.hangs] == ["dropped"]
    assert found.drops["overtaken_waiting"] == 1


def test_a_gap_while_nobody_spoke_is_no_hang() -> None:
    """The next caption's speech started after the last was shown."""
    found = summarise(
        [update(1, 10.0, 10.2, audio=1.0), update(2, 15.0, 15.2, audio=1.0)]
    )
    assert found.hangs == []


def test_each_segments_values_are_sampled_past_the_cap() -> None:
    found = Summary()
    for n in range(SAMPLES_KEPT + 500):
        found.add(update(n, 10.0 + n * 0.5, 10.2 + n * 0.5))
    assert len(found.by_segment["total"]) == SAMPLES_KEPT
    assert found.shown == SAMPLES_KEPT + 500


def test_the_usage_statistics_are_the_tracking_plans_properties() -> None:
    records = [update(n, 10.0 + n * 0.5, 10.2 + n * 0.5) for n in range(4)]
    records.append(update(9, 12.0, 15.5, held="mouse", windowed=15.49))
    props = usage_properties(summarise(records), stalls=3)
    assert set(props) <= PLAN
    assert props["hangs"] == 1 and props["hangs_window_hold"] == 1
    assert props["interface_stalls"] == 3 and props["held_mouse"] == 1
    assert all(isinstance(v, int) for v in props.values())


def test_a_sessions_timelines_are_its_own() -> None:
    now = [99.0]
    tracer = Tracer(clock=lambda: now[0])
    timelines = SessionTimelines(tracer)
    tracer.stalled(80)  # before the session: not its own
    now[0] = 100.0
    timelines.start()
    now[0] = 101.0
    tracer.stalled(120)
    for listener in list(tracer._listeners):  # what the tracer tells it
        listener(update(1, 100.5, 100.7))
    now[0] = 160.0
    timelines.stop()
    for listener in list(tracer._listeners):
        listener(update(2, 150.0, 150.2))
    assert timelines.summary.updates == 1
    assert timelines.stalls() == 1
    assert timelines.seconds() == 60.0


def test_a_compact_row_holds_the_whole_record() -> None:
    record = update(7, 10.0, 10.2, held="gap")
    again = expand(json.loads(json.dumps(compact(record))))
    assert (
        again["seq"] == 7 and again["held"] == "gap" and again["srv"] == record["srv"]
    )
    assert {k: round(v, 3) for k, v in again["t"].items()} == {
        k: round(v, 3) for k, v in record["t"].items()
    }


def test_a_reports_timelines_keep_to_their_size_newest_first() -> None:
    records = [update(n, 10.0 + n * 0.5, 10.2 + n * 0.5) for n in range(200)]
    text = report_text(records, limit=4000)
    assert len(text) <= 4000
    rows = [json.loads(line) for line in text.splitlines() if line.startswith("[")]
    assert rows[-1][0] == 199  # the newest kept
    assert "left out" in text
