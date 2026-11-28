"""Run health (polyglotic-hq 1009): the running note, its run id tying the
offer to the run that failed, the quit's limit, the freeze watch, the
crash details' privacy filter and Windows' session end.

What `main` wires - each quit source, the freeze watch, the offer end to
end - is driven through `main` itself in `tests/shell/test_shell_net.py`."""

import faulthandler
import io
import json
import subprocess
import sys
import threading
import time
from collections.abc import Iterator
from pathlib import Path
from typing import TextIO

import pytest

from polyglotic_desktop.adapters import run_health
from polyglotic_desktop.adapters.app_log import RUN_LOG, read_log, run_log
from polyglotic_desktop.adapters.crash_report import crash_report_text
from polyglotic_desktop.adapters.crash_trace import (
    CRASH_TRACE_NAME,
    CrashTrace,
    header,
    trace_of,
)
from polyglotic_desktop.adapters.run_health import (
    CleanShutdown,
    FreezeWatch,
    RunningNote,
    new_run_id,
)
from polyglotic_desktop.adapters.windows_session import (
    WM_ENDSESSION,
    WM_QUERYENDSESSION,
    WindowsSessionEnd,
)

HOME = Path("C:/Users/PrivatePerson")
FAILED = "0123456789abcdef"
BEFORE = "fedcba9876543210"
AFTER = "00112233aabbccdd"


@pytest.fixture(autouse=True)
def pytests_own_trace_kept() -> Iterator[None]:
    """pytest's faulthandler on again after a test's own `CrashTrace.stop`."""
    was = faulthandler.is_enabled()
    yield
    if was and not faulthandler.is_enabled() and sys.__stderr__ is not None:
        faulthandler.enable(sys.__stderr__, all_threads=True)


def record(logger: str, message: str) -> str:
    """A log line as `main.start_logging` writes it."""
    return f"2026-11-28 21:00:00,000 INFO {logger}: {message}\n"


def three_runs_log(folder: Path) -> None:
    """The run before, the run that failed and the run after, in the log:
    the failed run's own records among a library's line, a value carried
    onto a line of its own and the home folder."""
    (folder / "polyglotic.log").write_text(
        record(RUN_LOG, f"run {BEFORE}")
        + record("polyglotic_desktop.main", "the run before")
        + record(RUN_LOG, f"run {FAILED}")
        + record("polyglotic_desktop.main", "Polyglotic 0.1.14 (alpha)")
        + record("polyglotic_desktop.main", "opened C:/Users/PrivatePerson/app/x.py")
        + record("polyglotic_desktop.main", "a value over two lines")
        + "caption: PLANTED SECRET\n"
        + record("websockets.client", "setting token=SECRET VALUE")
        + record(RUN_LOG, f"run {AFTER}")
        + record("polyglotic_desktop.main", "the run after"),
        "utf-8",
    )


def test_the_note_is_content_free_and_offered_once(tmp_path: Path) -> None:
    note = RunningNote(
        tmp_path, "0.1.14", process_id=123, process_is_polyglotic=lambda _pid: False
    )
    note.start()
    assert json.loads(note.path.read_text("utf-8")).keys() == {
        "version",
        "started_at",
        "process_id",
        "run_id",
    }
    previous = note.previous()
    assert previous is not None and previous.run_id == note.run_id
    assert note.previous() is None
    assert not note.path.exists()


def test_a_note_without_its_run_is_put_away_unoffered(tmp_path: Path) -> None:
    """A note that can't say which run it was offers nothing: the offer
    would have no way to find that run's evidence alone."""
    note = RunningNote(tmp_path, "0.1.14", process_is_polyglotic=lambda _pid: False)
    note.path.write_text(
        json.dumps({"version": "0.1.14", "started_at": "x", "process_id": 1}), "utf-8"
    )
    assert note.previous() is None
    assert not note.path.exists()


def test_a_run_ending_removes_its_own_note_and_never_another_runs(
    tmp_path: Path,
) -> None:
    """A copy relaunched into a new interface language writes its note while
    the old one is still ending: the old one's finish must leave it."""
    ending = RunningNote(tmp_path, "0.1.14", run_id=FAILED)
    ending.start()
    relaunched = RunningNote(tmp_path, "0.1.14", run_id=AFTER)
    relaunched.start()
    ending.finish()
    assert json.loads(ending.path.read_text("utf-8"))["run_id"] == AFTER
    relaunched.finish()
    assert not relaunched.path.exists()


def test_run_ids_are_random_and_new_each_run() -> None:
    ids = {new_run_id() for _ in range(50)}
    assert len(ids) == 50
    assert all(len(i) == 16 and int(i, 16) >= 0 for i in ids)


def test_a_live_polyglotic_owner_is_a_second_copy_and_keeps_its_note(
    tmp_path: Path,
) -> None:
    note = RunningNote(
        tmp_path, "0.1.14", process_id=321, process_is_polyglotic=lambda pid: pid == 321
    )
    note.start()
    assert note.previous() is None
    assert note.path.exists()


def test_windows_asks_the_process_and_never_os_kill(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """On Windows `os.kill(pid, 0)` sends Ctrl+C to, or ends, whatever
    process has that id now (polyglotic-hq RULES #50): the check must only
    ask for a running process's image."""

    def never(*_args: object) -> None:
        raise AssertionError("os.kill on Windows")

    monkeypatch.setattr(run_health.os, "kill", never)
    asked: list[int] = []

    def image(pid: int) -> str:
        asked.append(pid)
        return "C:\\Program Files\\Polyglotic\\Polyglotic.exe" if pid == 7 else ""

    check = run_health._is_polyglotic_process
    assert check(7, windows=True, windows_image=image)
    assert not check(8, windows=True, windows_image=image)  # ended or another's
    assert asked == [7, 8]


def test_a_really_killed_run_is_offered_once(tmp_path: Path) -> None:
    child = subprocess.Popen(
        [
            sys.executable,
            "-c",
            (
                "import json,os,pathlib,time;"
                f"p=pathlib.Path({str(tmp_path / 'running.json')!r});"
                "p.write_text(json.dumps({'version':'0.1.14','started_at':'now',"
                f"'process_id':os.getpid(),'run_id':{FAILED!r}}}));time.sleep(60)"
            ),
        ]
    )
    try:
        deadline = time.monotonic() + 10
        while not (tmp_path / "running.json").exists() and time.monotonic() < deadline:
            time.sleep(0.01)
        child.kill()
        child.wait(timeout=10)
        note = RunningNote(tmp_path, "0.1.14")
        previous = note.previous()
        assert previous is not None and previous.run_id == FAILED
        assert note.previous() is None
    finally:
        if child.poll() is None:
            child.kill()


def test_the_details_are_the_failed_runs_alone_and_content_free(
    tmp_path: Path,
) -> None:
    three_runs_log(tmp_path)
    (tmp_path / CRASH_TRACE_NAME).write_text(
        header(AFTER)
        + '  File "C:/Users/PrivatePerson/app/main.py", line 9 in after\n',
        "utf-8",
    )
    (tmp_path / f"{CRASH_TRACE_NAME}.1").write_text(
        header(FAILED)
        + "Fatal Python error: Segmentation fault\n"
        + '  File "C:/Users/PrivatePerson/app/main.py", line 12 in run\n'
        + '    caption = "PLANTED SECRET"\n',
        "utf-8",
    )
    (tmp_path / f"{CRASH_TRACE_NAME}.2").write_text(
        header(BEFORE) + '  File "C:/Users/PrivatePerson/app/main.py", line 3 in old\n',
        "utf-8",
    )
    bundle = crash_report_text(
        tmp_path, run=FAILED, app_version="0.1.14", os_version="Windows 11", home=HOME
    )
    assert bundle is not None
    assert bundle.startswith("Polyglotic: 0.1.14\nOS: Windows 11\n")
    assert "%USERPROFILE%/app/main.py:12 in run" in bundle
    assert "Polyglotic 0.1.14 (alpha)" in bundle
    assert "opened %USERPROFILE%/app/x.py" in bundle
    for not_sent in (
        "in after",  # the next run's trace
        "in old",  # the one before's
        "the run before",
        "the run after",
        "PLANTED SECRET",  # a value over a line break, and the trace's
        "SECRET VALUE",  # a library's line
        "PrivatePerson",
        FAILED,  # the run ids stay on this PC
        BEFORE,
        AFTER,
    ):
        assert not_sent not in bundle, not_sent


def test_a_run_that_left_nothing_is_not_offered(tmp_path: Path) -> None:
    (tmp_path / "polyglotic.log").write_text(
        record(RUN_LOG, f"run {FAILED}")
        + record("websockets.client", "a library's line only"),
        "utf-8",
    )
    (tmp_path / CRASH_TRACE_NAME).write_text(header(FAILED), "utf-8")
    assert (
        crash_report_text(tmp_path, run=FAILED, app_version="1", os_version="x") is None
    )
    assert run_log(tmp_path, BEFORE) is None  # a run the log never had


def test_a_runs_first_line_reaches_back_into_rotated_files(tmp_path: Path) -> None:
    (tmp_path / "polyglotic.log.1").write_text(
        record(RUN_LOG, f"run {FAILED}") + record("polyglotic_desktop.a", "early"),
        "utf-8",
    )
    (tmp_path / "polyglotic.log").write_text(
        record("polyglotic_desktop.a", "late"), "utf-8"
    )
    found = run_log(tmp_path, FAILED, home=HOME) or ""
    assert "early" in found and "late" in found


def test_a_report_never_carries_a_run_id(tmp_path: Path) -> None:
    three_runs_log(tmp_path)
    attached = read_log(tmp_path, home=HOME) or ""
    assert "the run before" in attached
    for run in (FAILED, BEFORE, AFTER):
        assert run not in attached


def test_a_trace_file_names_its_run_and_one_left_empty_is_used_again(
    tmp_path: Path,
) -> None:
    trace = CrashTrace(tmp_path, run=FAILED)
    assert trace.start()
    trace.stop()
    assert (tmp_path / CRASH_TRACE_NAME).read_text("utf-8") == header(FAILED)
    assert trace_of(tmp_path, FAILED) == ""
    again = CrashTrace(tmp_path, run=AFTER)
    assert again.start()  # the run before left no trace: its file is used again
    again.stop()
    assert not (tmp_path / f"{CRASH_TRACE_NAME}.1").exists()
    assert trace_of(tmp_path, FAILED) is None


def test_a_runs_trace_is_kept_when_the_next_run_starts(tmp_path: Path) -> None:
    (tmp_path / CRASH_TRACE_NAME).write_text(
        header(FAILED) + '  File "app/main.py", line 17 in heartbeat\n', "utf-8"
    )
    trace = CrashTrace(tmp_path, run=AFTER)
    assert trace.start()
    trace.stop()
    assert "line 17 in heartbeat" in (trace_of(tmp_path, FAILED) or "")
    assert trace_of(tmp_path, AFTER) == ""


def test_the_freeze_watch_writes_every_threads_frames(tmp_path: Path) -> None:
    with (tmp_path / "crash.log").open("w", encoding="utf-8") as stream:
        watch = FreezeWatch(lambda: stream, after=0.05, poll=0.01)
        watch.start()
        deadline = time.monotonic() + 5
        while stream.tell() == 0 and time.monotonic() < deadline:
            time.sleep(0.01)
        watch.stop()
    assert "test_the_freeze_watch_writes_every_threads_frames" in (
        tmp_path / "crash.log"
    ).read_text("utf-8")


def test_the_freeze_watch_follows_a_trace_file_started_again(tmp_path: Path) -> None:
    """`CrashTrace.keep_small` closes its file and opens a new one: the
    watch writes to the new one rather than failing on the closed one."""
    closed = io.StringIO()
    closed.close()
    files: list[TextIO] = [closed]
    with (tmp_path / "crash.log").open("w", encoding="utf-8") as current:
        watch = FreezeWatch(lambda: files[-1], after=0.05, poll=0.01)
        watch.start()
        time.sleep(0.15)  # it tried the closed one
        files.append(current)
        deadline = time.monotonic() + 5
        while current.tell() == 0 and time.monotonic() < deadline:
            time.sleep(0.01)
        watch.stop()
    assert "test_the_freeze_watch_follows" in (tmp_path / "crash.log").read_text(
        "utf-8"
    )


def _ignore(_value: object) -> None:
    """A step's own return value: a shutdown step returns nothing."""


def test_clean_shutdown_has_one_ordered_idempotent_path() -> None:
    called: list[str] = []
    shutdown = CleanShutdown(
        [
            ("listener", lambda: called.append("listener")),
            ("note", lambda: called.append("note")),
        ],
        timed_out=lambda part: called.append(f"timeout:{part}"),
    )
    shutdown()
    shutdown()
    assert called == ["listener", "note"]


def test_the_limit_names_the_hung_part_and_removes_the_note_first(
    tmp_path: Path,
) -> None:
    note = RunningNote(tmp_path, "0.1.14", process_id=123)
    note.start()
    release = threading.Event()
    order: list[str] = []
    exited = threading.Event()

    def forced(code: int) -> None:
        order.append(f"exit {code}, note {'kept' if note.path.exists() else 'gone'}")
        exited.set()

    shutdown = CleanShutdown(
        [
            ("server session", lambda: _ignore(release.wait())),
            ("running note", note.finish),
        ],
        deadline=0.05,
        timed_out=lambda part: order.append(f"limit: {part}"),
        before_force_exit=note.finish,
        force_exit=forced,
    )
    worker = threading.Thread(target=shutdown)
    worker.start()
    assert exited.wait(5)
    assert order == ["limit: server session", "exit 1, note gone"]
    release.set()
    worker.join(timeout=5)


def test_windows_session_end_quits_on_the_end_and_never_on_the_query() -> None:
    """Another app can cancel after the query (Microsoft: answer it at
    once, clean up on WM_ENDSESSION): only a real end quits."""
    called: list[str] = []
    adapter = WindowsSessionEnd(lambda: called.append("quit"))
    adapter.message(WM_QUERYENDSESSION)
    assert called == []
    adapter.message(WM_ENDSESSION, ending=False)  # cancelled: runs on
    assert called == []
    adapter.message(WM_ENDSESSION, ending=True)
    assert called == ["quit"]
