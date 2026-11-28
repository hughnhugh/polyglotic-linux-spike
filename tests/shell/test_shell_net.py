"""The shell net (933 unit shell-2, polyglotic-hq 1008): records and pins the
exact order in which `polyglotic_desktop.main` starts parts, wires Qt signal
connections, and stops parts across:

- a normal start-to-quit run (identical on three runs);
- Linux start-to-quit (runs in Linux CI);
- a normal run with a second (`beside`) learning store;
- language-change relaunch (`packs.close`, `windows_deleted`, `copy_lock.release`,
  `relaunch_app`);
- the three early exits (`moved_to_applications`, `RestartForLanguage`,
  `NotAgreed`);
- each `--check-*` path (`--check-install`, `--check-capture`, `--check-parity`,
  `--check-tls`, `--check-release`);
- every quit path (tray Quit, closing the last window, a second copy asking the
  first to quit, an update's ordinary and forced restart, Windows' session
  end and Ctrl+C);
- planted faults (a swapped close, a doubled `aboutToQuit` connection, and a
  doubled settings connection) that must each fail the net;
- the one quit path for each quit source (polyglotic-hq 1009): its order, the
  running note removed, and the 3 s limit with a part that never returns;
- the freeze watch as `main` installs it, and an improper exit end to end:
  the next start's offer, what it would send, and Report a problem sending
  it only after the learner's yes.

Each scenario executes `polyglotic_desktop.main.main` in a clean offscreen
subprocess against a temporary data folder, sample dictionaries and a local
stand-in server, leaving no global Qt state behind in pytest.
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

# Keep `tests/conftest.py`'s `NEEDS_QT` detector aware that this file runs Qt
# (in offscreen subprocesses) so environments without libGL/libEGL skip it.
import PySide6.QtWidgets  # noqa: F401
import pytest
from tests.shell.recorder import (
    ALL_SCENARIOS,
    HANG_STARTED,
    OTHER_LINE,
    PLANTED,
    QUIT_STARTED,
)

from polyglotic_desktop.adapters.run_health import QUIT_DEADLINE_SECONDS

RECORDED_PATH = Path(__file__).with_name("recorded_order.json")


def load_recorded() -> dict[str, dict[str, Any]]:
    return dict(json.loads(RECORDED_PATH.read_text(encoding="utf-8")))


def record_in_subprocess(
    scenario: str,
    work_dir: Path,
    *,
    fault: str | None = None,
) -> dict[str, Any]:
    """Run `tests.shell.recorder` in a fresh offscreen Python subprocess."""
    out = work_dir / f"{scenario}.json"
    cmd = [
        sys.executable,
        "-m",
        "tests.shell.recorder",
        scenario,
        "--work-dir",
        str(work_dir / "run"),
        "--out",
        str(out),
    ]
    if fault is not None:
        cmd.extend(["--fault", fault])
    env = dict(os.environ, QT_QPA_PLATFORM="offscreen")
    done = subprocess.run(
        cmd,
        env=env,
        capture_output=True,
        text=True,
        timeout=120,
        check=False,
    )
    assert done.returncode == 0, (
        f"recorder failed for {scenario!r} (fault={fault!r}, exit={done.returncode}):\n"
        f"STDOUT:\n{done.stdout[-2000:]}\nSTDERR:\n{done.stderr[-2000:]}"
    )
    return dict(json.loads(out.read_text(encoding="utf-8")))


def assert_matches_net(
    recorded: dict[str, Any],
    expected: dict[str, Any],
) -> None:
    """Assert a recorded trace matches the committed shell-net baseline."""
    name = expected["scenario"]
    assert recorded["exit_code"] == expected["exit_code"], (
        f"{name}: exit_code mismatch: got {recorded['exit_code']!r}, "
        f"expected {expected['exit_code']!r}"
    )
    assert recorded["start"] == expected["start"], (
        f"{name}: start order mismatch:\n"
        f"  got:      {recorded['start']}\n"
        f"  expected: {expected['start']}"
    )
    assert recorded["stop"] == expected["stop"], (
        f"{name}: stop order mismatch:\n"
        f"  got:      {recorded['stop']}\n"
        f"  expected: {expected['stop']}"
    )
    if "connections" in expected:
        got_conn = recorded.get("connections", {})
        exp_conn = expected["connections"]
        if got_conn != exp_conn:
            diffs = [
                f"  {key}: got {got_conn.get(key)!r}, expected {exp_conn.get(key)!r}"
                for key in sorted(set(got_conn) | set(exp_conn))
                if got_conn.get(key) != exp_conn.get(key)
            ]
            raise AssertionError(f"{name}: connections mismatch:\n" + "\n".join(diffs))
    if "notes" in expected:
        assert recorded.get("notes") == expected["notes"], (
            f"{name}: notes mismatch:\n"
            f"  got:      {recorded.get('notes')}\n"
            f"  expected: {expected['notes']}"
        )
    if "running_note_left" in expected:
        assert recorded.get("running_note_left") == expected["running_note_left"], (
            f"{name}: running note left: got {recorded.get('running_note_left')!r}"
        )


def test_recorded_baseline_covers_all_scenarios() -> None:
    recorded = load_recorded()
    assert tuple(recorded) == ALL_SCENARIOS


def test_normal_run_is_identical_across_three_runs(tmp_path: Path) -> None:
    """Criterion 0.11: the normal start-to-quit order is identical on three
    independent runs and matches the committed shell-net baseline."""
    expected = load_recorded()["normal_tray_quit"]
    runs = [
        record_in_subprocess("normal_tray_quit", tmp_path / f"run-{index}")
        for index in range(3)
    ]
    assert runs[0] == runs[1] == runs[2]
    assert_matches_net(runs[0], expected)

    stop = runs[0]["stop"]
    assert stop.index("second_starts.close") < stop.index("timer.resending.stop")
    assert stop.index("pipeline.stop") < stop.index("connection.close")
    assert stop.index("interface.close") < stop.index("store.close")
    assert stop.index("connection.close") < stop.index("outbox.close")
    assert stop.index("outbox.close") < stop.index("learning_store.close")
    assert stop.index("learning_store.close") < stop.index("packs.close")
    assert stop.index("packs.close") < stop.index("windows_deleted")
    # Today, DesktopApp._quit() calls desktop.close() before app.exit(0), and
    # stop() calls desktop.close() a second time on aboutToQuit.
    assert stop.count("desktop.close") == 2


def test_linux_start_to_quit(tmp_path: Path) -> None:
    """Acceptance #3: a full start-to-quit run executes and passes in Linux CI."""
    expected = load_recorded()["linux_start_to_quit"]
    recorded = record_in_subprocess("linux_start_to_quit", tmp_path)
    assert_matches_net(recorded, expected)
    assert recorded["exit_code"] == 0
    assert "packs.close" in recorded["stop"]
    assert "windows_deleted" in recorded["stop"]


def test_normal_run_with_beside_closes_beside_after_primary_and_before_packs(
    tmp_path: Path,
) -> None:
    expected = load_recorded()["normal_with_beside"]
    recorded = record_in_subprocess("normal_with_beside", tmp_path)
    assert_matches_net(recorded, expected)
    stop = recorded["stop"]
    assert (
        stop.index("learning_store.close")
        < stop.index("beside_learning_store_1.close")
        < stop.index("packs.close")
    )


def test_language_relaunch_releases_lock_and_relaunches_after_windows_deleted(
    tmp_path: Path,
) -> None:
    expected = load_recorded()["language_relaunch"]
    recorded = record_in_subprocess("language_relaunch", tmp_path)
    assert_matches_net(recorded, expected)
    stop = recorded["stop"]
    assert (
        stop.index("packs.close")
        < stop.index("windows_deleted")
        < stop.index("copy_lock.release")
        < stop.index("relaunch_app")
    )
    # restart_for_language() checks may_quit(), then desktop.quit.trigger()
    # invokes DesktopApp._quit() which checks may_quit() a second time.
    assert stop.count("desktop.may_quit") == 2


@pytest.mark.parametrize(
    "scenario",
    [
        "early_exit_moved_to_applications",
        "early_exit_restart_for_language",
        "early_exit_not_agreed",
    ],
)
def test_early_exits_match_recorded_order(scenario: str, tmp_path: Path) -> None:
    expected = load_recorded()[scenario]
    recorded = record_in_subprocess(scenario, tmp_path)
    assert_matches_net(recorded, expected)


@pytest.mark.parametrize(
    "scenario",
    [
        "check_install",
        "check_capture_non_windows",
        "check_capture_windows",
        "check_parity_non_macos",
        "check_tls",
        "check_release",
    ],
)
def test_check_paths_match_recorded_order(scenario: str, tmp_path: Path) -> None:
    expected = load_recorded()[scenario]
    recorded = record_in_subprocess(scenario, tmp_path)
    assert_matches_net(recorded, expected)


@pytest.mark.parametrize(
    "scenario",
    [
        "quit_close_last_window_with_tray",
        "quit_close_last_window_no_tray_keep",
        "quit_close_last_window_neither",
        "quit_second_copy_asks_quit",
        "quit_second_copy_second_process_show",
        "quit_second_copy_cli_flag",
        "quit_update_restart_linux",
        "quit_update_restart_forced",
    ],
)
def test_quit_paths_match_recorded_order(scenario: str, tmp_path: Path) -> None:
    expected = load_recorded()[scenario]
    recorded = record_in_subprocess(scenario, tmp_path)
    assert_matches_net(recorded, expected)


# polyglotic-hq 1009: each way the app is asked to quit, as `main` wires it
QUIT_SOURCES = {
    "tray Quit": "normal_tray_quit",
    "closing the last window": "quit_close_last_window_no_tray_quit",
    "Windows session end": "quit_windows_session_end",
    "an update's restart": "quit_update_restart_windows",
    "Ctrl+C": "quit_ctrl_c",
}
ONE_PATH = (
    "connection.close",
    "interface.close",
    "store.close",
    "outbox.close",
    "learning_store.close",
    "packs.close",
    "running_note.finish",
    "windows_deleted",
)
"""The one quit path's parts the net sees, in their order."""
LIMIT_SLACK_SECONDS = 1.5
"""Past the 3 s limit, the time a forced exit may take to end the process
and the test to see it end (seconds): a loaded runner's slowest."""


def run_recorder(
    scenario: str, work_dir: Path, *, hang: str | None = None
) -> tuple[subprocess.CompletedProcess[str], float]:
    """The recorder as `record_in_subprocess` runs it, for a run that may
    end without writing its trace; and the time it ended."""
    cmd = [
        sys.executable,
        "-m",
        "tests.shell.recorder",
        scenario,
        "--work-dir",
        str(work_dir / "run"),
        "--out",
        str(work_dir / f"{scenario}.json"),
    ]
    if hang is not None:
        cmd.extend(["--hang", hang])
    env = dict(os.environ, QT_QPA_PLATFORM="offscreen")
    done = subprocess.run(
        cmd, env=env, capture_output=True, text=True, timeout=120, check=False
    )
    return done, time.time()


@pytest.mark.parametrize("source", QUIT_SOURCES)
def test_each_quit_source_takes_the_one_path_and_removes_the_note(
    source: str, tmp_path: Path
) -> None:
    scenario = QUIT_SOURCES[source]
    recorded = record_in_subprocess(scenario, tmp_path)
    assert_matches_net(recorded, load_recorded()[scenario])  # the order, pinned
    stop = recorded["stop"]
    places = [stop.index(part) for part in ONE_PATH]
    assert places == sorted(places), f"{source}: {stop}"
    assert stop.count("running_note.finish") == 1
    assert recorded["exit_code"] == 0
    assert not recorded["running_note_left"]


@pytest.mark.parametrize("source", QUIT_SOURCES)
def test_each_quit_source_ends_within_the_limit_when_a_part_hangs(
    source: str, tmp_path: Path
) -> None:
    """The server session's close never returns: the limit ends the app
    within 3 s of the quit's start, says which part hung, and the running
    note is gone first."""
    done, ended = run_recorder(QUIT_SOURCES[source], tmp_path, hang="connection.close")
    run = tmp_path / "run"
    assert done.returncode == 1, done.stderr[-2000:]
    assert (run / HANG_STARTED).exists()
    began = float((run / QUIT_STARTED).read_text("utf-8"))
    assert ended - began < QUIT_DEADLINE_SECONDS + LIMIT_SLACK_SECONDS
    assert not (run / "data" / "running.json").exists()
    said = (run / "data" / "logs" / "polyglotic.log").read_text("utf-8")
    assert "the 3 second limit ended the app while closing application parts" in said


def test_session_end_quits_on_the_end_not_the_query(tmp_path: Path) -> None:
    """Another app can cancel a shutdown after the query: nothing closes
    until Windows says the session ends, and then all of it, at once."""
    notes = record_in_subprocess("quit_windows_session_end", tmp_path)["notes"]
    assert notes["after_query"] == {"stop": [], "note": True}
    assert notes["after_cancelled_end"] == {"stop": [], "note": True}
    assert notes["note_after_end"] is False
    assert notes["commitDataRequest_receivers"] == 0  # Qt answers the query yes


def test_a_frozen_interface_leaves_its_trace_through_mains_wiring(
    tmp_path: Path,
) -> None:
    """The heartbeat and watch as `main` installs them (times shortened):
    the blocked interface thread's frames land in this run's crash.log,
    and a clean quit after it leaves no running note."""
    recorded = record_in_subprocess("freeze_traced", tmp_path)
    assert recorded["notes"]["trace_has_blocker"]
    assert recorded["notes"]["trace_names_its_run"]
    assert not recorded["running_note_left"]


def details_of(work: Path) -> dict[str, Any]:
    """A run that freezes and quits cleanly (A), then one that crashes (B),
    then the start after (C) that sends B's details: C's notes."""
    a = record_in_subprocess("freeze_traced", work)
    assert a["notes"]["trace_has_blocker"] and not a["running_note_left"]
    done, _ = run_recorder("crash_fatal", work)
    assert done.returncode != 0, "the fault ended the run"
    assert (work / "run" / "data" / "running.json").exists()
    return dict(record_in_subprocess("crash_offer_send", work)["notes"])


def test_an_improper_exit_is_offered_and_sends_that_runs_details_alone(
    tmp_path: Path,
) -> None:
    """End to end (polyglotic-hq 1009): a crash, then the next start offers
    to send; See what's sent shows the exact text; Send opens Report a
    problem, which sends that text as its log - B's version, B's own
    records and B's frames, never A's, a library's line, a planted caption,
    the home folder or a run id; nothing before the learner's yes; and the
    start after that offers nothing."""
    notes = details_of(tmp_path)
    assert notes["offer_shown"] and notes["preview_shown"]
    assert notes["sent_before_a_choice"] == []
    preview = notes["preview"]
    assert "in crash_with_fatal_error" in preview  # B's trace
    assert "shell net: run B" in preview  # B's own records
    assert "block_interface_thread" not in preview  # A's trace
    assert "shell net: run A" not in preview  # A's records
    assert PLANTED not in preview
    assert OTHER_LINE not in preview
    assert str(Path.home()).casefold() not in preview.casefold()
    assert "%USERPROFILE%" in preview
    assert "Polyglotic run " not in preview
    assert not re.search(r"\brun [0-9a-f]{16}\b", preview)
    assert notes["report_dialog_shown"]
    assert len(notes["submitted"]) == 1
    sent = notes["submitted"][0]
    assert sent["mode"] == "problem" and "log" in sent["ticked"]
    assert sent["log_text"] == preview
    after = record_in_subprocess("crash_offer_dont_send", tmp_path)["notes"]
    assert not after["offer_shown"]  # once per improper exit
    assert after["submitted"] == []


def test_a_crash_while_the_window_is_built_is_offered_at_the_next_start(
    tmp_path: Path,
) -> None:
    """997's start crash (1 in 250 starts, in `Flow.add_layout`) comes
    before the first paint: the running note is written before the window
    is built, so a fault there is offered at the next start, its frames
    and its own records with it."""
    done, _ = run_recorder("crash_before_paint", tmp_path)
    assert done.returncode != 0, "the fault ended the run"
    assert (tmp_path / "run" / "data" / "running.json").exists()
    notes = record_in_subprocess("crash_offer_dont_send", tmp_path)["notes"]
    assert notes["offer_shown"]
    assert "in crash_with_fatal_error" in notes["preview"]
    assert "shell net: run early" in notes["preview"]


def test_dont_send_sends_nothing(tmp_path: Path) -> None:
    done, _ = run_recorder("crash_fatal", tmp_path)
    assert done.returncode != 0
    notes = record_in_subprocess("crash_offer_dont_send", tmp_path)["notes"]
    assert notes["offer_shown"]
    assert not notes["report_dialog_shown"]
    assert notes["submitted"] == []


def test_planted_swapped_close_fails(tmp_path: Path) -> None:
    """Acceptance #4: swapping two close calls in `stop()` must fail the net."""
    expected = load_recorded()["normal_tray_quit"]
    mutated = record_in_subprocess("normal_tray_quit", tmp_path, fault="swapped_close")
    with pytest.raises(AssertionError, match="stop order mismatch"):
        assert_matches_net(mutated, expected)


def test_planted_doubled_about_to_quit_fails(tmp_path: Path) -> None:
    """A duplicate clean-shutdown receiver is caught even though the
    idempotent shutdown correctly prevents a duplicated stop order."""
    expected = load_recorded()["normal_tray_quit"]
    mutated = record_in_subprocess(
        "normal_tray_quit", tmp_path, fault="doubled_about_to_quit"
    )
    assert (
        mutated["connections"]["app.aboutToQuit()"]
        == expected["connections"]["app.aboutToQuit()"] + 1
    )
    assert mutated["stop"] == expected["stop"]
    with pytest.raises(AssertionError, match="connections mismatch"):
        assert_matches_net(mutated, expected)


def test_planted_doubled_connection_fails(tmp_path: Path) -> None:
    """Acceptance #4: doubling a wiring `.connect(...)` in `_start_and_run`
    must fail the net even when the stop list itself is unchanged."""
    expected = load_recorded()["normal_tray_quit"]
    mutated = record_in_subprocess(
        "normal_tray_quit", tmp_path, fault="doubled_connection"
    )
    assert mutated["stop"] == expected["stop"]
    with pytest.raises(AssertionError, match=r"desktop\.settings\.changed\(\)"):
        assert_matches_net(mutated, expected)
