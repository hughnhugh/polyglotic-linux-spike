"""`tools/ci_lock.py`: CI's timing steps run alone on the PC the Windows
runners share (polyglotic-hq 312) - a step held alone waits for shared
ones and keeps new ones waiting; shared steps run side by side; the
step's exit code is kept; the lock never fails a step."""

import ctypes
import os
import subprocess
import sys
import time
from pathlib import Path

import pytest

from tools import ci_lock

WINDOWS = pytest.mark.skipif(sys.platform != "win32", reason="Windows' LockFileEx")


def step(how: str, lock: Path, code: str = "", *options: str) -> subprocess.Popen[str]:
    """`python -m tools.ci_lock HOW [OPTIONS] -- python -c CODE`, as a CI
    step runs it."""
    return subprocess.Popen(
        [sys.executable, "-m", "tools.ci_lock", how, *options, "--"]
        + [sys.executable, "-c", code],
        env=dict(os.environ, POLYGLOTIC_CI_LOCK=str(lock)),
        cwd=Path(__file__).resolve().parents[2],
        stdout=subprocess.PIPE,
        text=True,
    )


def holding(lock: Path) -> subprocess.Popen[bytes]:
    """A step holding the lock alone for a minute, its output not kept (its
    own command would keep the pipe open after it's killed)."""
    return subprocess.Popen(
        [sys.executable, "-m", "tools.ci_lock", "alone", "--"]
        + [sys.executable, "-c", "import time; time.sleep(60)"],
        env=dict(os.environ, POLYGLOTIC_CI_LOCK=str(lock)),
        cwd=Path(__file__).resolve().parents[2],
        stdout=subprocess.DEVNULL,
    )


@WINDOWS
def test_a_step_held_alone_waits_for_a_shared_one(tmp_path: Path) -> None:
    lock = tmp_path / "steps.lock"
    with ci_lock.held(alone=False, path=lock):
        timing = step("alone", lock)
        time.sleep(1.5)
        assert timing.poll() is None  # waiting
    out, _ = timing.communicate(timeout=30)
    assert timing.returncode == 0
    assert "ci_lock: alone, after" in out


@WINDOWS
def test_a_shared_step_that_comes_while_one_waits_alone_waits_behind_it(
    tmp_path: Path,
) -> None:
    """polyglotic-hq 344: the start with real windows waited 10 minutes and
    gave up (2026-11-14 11:56-12:06 UTC): shared steps that started while it
    waited took the lock beside the ones running, so it never came free. A
    shared step that comes later now waits for the alone one."""
    lock = tmp_path / "steps.lock"
    stamp = "import time; print('at', time.time())"
    with ci_lock.held(alone=False, path=lock):  # the other runner's pytest
        timing = step("alone", lock, stamp)
        time.sleep(1.5)  # waiting for the pytest
        assert timing.poll() is None
        later = step("shared", lock, stamp)  # the next heavy step starts
        time.sleep(1.5)
        assert later.poll() is None  # behind the timing step, not beside the pytest
    timed, _ = timing.communicate(timeout=30)
    after, _ = later.communicate(timeout=30)
    assert timing.returncode == 0 and later.returncode == 0
    assert "ci_lock: alone, after" in timed and "ci_lock: shared, after" in after

    def at(out: str) -> float:
        return float(
            next(line for line in out.splitlines() if line.startswith("at "))[3:]
        )

    assert at(timed) <= at(after)


@WINDOWS
def test_shared_steps_run_side_by_side(tmp_path: Path) -> None:
    lock = tmp_path / "steps.lock"
    with ci_lock.held(alone=False, path=lock):
        other = step("shared", lock)
        out, _ = other.communicate(timeout=30)
    assert other.returncode == 0 and "ci_lock: shared, after 0 s" in out


@WINDOWS
def test_a_shared_step_waits_while_one_is_held_alone(tmp_path: Path) -> None:
    lock = tmp_path / "steps.lock"
    with ci_lock.held(alone=True, path=lock):
        heavy = step("shared", lock)
        time.sleep(1.5)
        assert heavy.poll() is None
    heavy.communicate(timeout=30)
    assert heavy.returncode == 0


def test_the_steps_own_exit_code_is_kept(tmp_path: Path) -> None:
    done = step("alone", tmp_path / "steps.lock", "raise SystemExit(3)")
    done.communicate(timeout=30)
    assert done.returncode == 3


def test_a_lock_that_cant_be_had_runs_the_step_unlocked(tmp_path: Path) -> None:
    folder = tmp_path / "a-folder"  # a folder can't be opened as the lock
    folder.mkdir()
    done = step("alone", folder)
    out, _ = done.communicate(timeout=30)
    assert done.returncode == 0 and "ci_lock: unlocked" in out


@WINDOWS
def test_a_step_held_alone_gives_up_with_a_clear_line_not_a_hung_job(
    tmp_path: Path,
) -> None:
    lock = tmp_path / "steps.lock"
    with ci_lock.held(alone=False, path=lock):
        timing = step("alone", lock, "print('ran')", "--most-minutes", "0.02")
        out, _ = timing.communicate(timeout=30)
    assert timing.returncode == 1 and "ran" not in out
    assert "ci_lock: gave up after 0.02 min: other CI steps held" in out


@WINDOWS
def test_a_jobs_own_wait_replaces_the_default_and_the_flag_wins(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """polyglotic-hq 999: the UI lab's walks gave up after the default 10
    minutes while a Checks (Windows) run held the PC shared; the lab's job
    names a longer wait once, for every step it locks."""
    lock = tmp_path / "steps.lock"
    monkeypatch.setenv(ci_lock.MINUTES_VARIABLE, "0.02")
    with ci_lock.held(alone=False, path=lock):
        timing = step("alone", lock, "print('ran')")
        out, _ = timing.communicate(timeout=30)
        assert "ci_lock: gave up after 0.02 min" in out
        flagged = step("alone", lock, "print('ran')", "--most-minutes", "0.03")
        out, _ = flagged.communicate(timeout=30)
        assert "ci_lock: gave up after 0.03 min" in out


@WINDOWS
def test_a_shared_step_that_waited_too_long_runs_unlocked(tmp_path: Path) -> None:
    lock = tmp_path / "steps.lock"
    with ci_lock.held(alone=True, path=lock):
        heavy = step("shared", lock, "print('ran')", "--most-minutes", "0.02")
        out, _ = heavy.communicate(timeout=30)
    assert heavy.returncode == 0 and "ran" in out and "gave up" in out


@WINDOWS
def test_a_lock_is_let_go_when_its_process_is_killed(tmp_path: Path) -> None:
    """A cancelled job's lock: Windows releases it with the process."""
    lock = tmp_path / "steps.lock"
    holder = holding(lock)
    time.sleep(1.5)  # it holds the lock now
    holder.kill()  # as a cancelled job's step is; its command may live on
    holder.wait(timeout=30)
    with ci_lock.held(alone=True, path=lock, most_minutes=0.1) as said:
        assert said.startswith("alone")


def test_off_ci_the_lock_is_taken_only_if_it_is_here(tmp_path: Path) -> None:
    lock = tmp_path / "polyglotic-ci" / "steps.lock"
    done = step("shared", lock, "", "--if-present")
    out, _ = done.communicate(timeout=30)
    assert done.returncode == 0
    assert (
        "ci_lock: unlocked: " + ("no " if sys.platform == "win32" else "not Windows")
        in out
    )
    assert not lock.parent.exists()  # never made off CI


def _alive(pid: int) -> bool:
    """Whether process `pid` is still running (Windows)."""
    import ctypes

    # getattr: WinDLL exists on Windows only (mypy --platform linux/darwin)
    kernel32 = getattr(ctypes, "WinDLL")("kernel32", use_last_error=True)  # noqa: B009
    handle = kernel32.OpenProcess(0x1000, False, pid)  # QUERY_LIMITED_INFORMATION
    if not handle:
        return False
    try:
        code = ctypes.c_ulong()
        kernel32.GetExitCodeProcess(handle, ctypes.byref(code))
        return code.value == 259  # STILL_ACTIVE
    finally:
        kernel32.CloseHandle(handle)


def _end(pid: int) -> None:
    """Our own test process `pid` ended, if it's still there (by its PID)."""
    import ctypes

    # getattr: WinDLL exists on Windows only (mypy --platform linux/darwin)
    kernel32 = getattr(ctypes, "WinDLL")("kernel32", use_last_error=True)  # noqa: B009
    handle = kernel32.OpenProcess(0x0001, False, pid)  # PROCESS_TERMINATE
    if handle:
        kernel32.TerminateProcess(handle, 1)
        kernel32.CloseHandle(handle)


@WINDOWS
@pytest.mark.parametrize("ends", ["killed", "on its own"])
def test_what_a_step_started_ends_with_it(tmp_path: Path, ends: str) -> None:
    """polyglotic-hq 344: a cancelled job left the language walk's Pythons
    running, holding the runner's work folder, and every job after it on
    that runner failed at checkout (2026-11-15). As CI runs it - `python`
    through the venv's launcher, a command that starts a child of its own -
    the child ends with the step: killed, as a cancel does, or left behind
    by a command that ended."""
    pid_file = tmp_path / "child.pid"
    child = f"import os, time; open({str(pid_file)!r}, 'w').write(str(os.getpid())); time.sleep(60)"
    command = (
        "import subprocess, sys, time; "
        f"subprocess.Popen([sys.executable, '-c', {child!r}]); "
        + ("time.sleep(60)" if ends == "killed" else "time.sleep(3)")
    )
    started = step("shared", tmp_path / "steps.lock", command)
    try:
        deadline = time.monotonic() + 20
        while not pid_file.exists() or not pid_file.read_text():
            assert time.monotonic() < deadline, "the child never started"
            time.sleep(0.1)
        pid = int(pid_file.read_text())
        assert _alive(pid)
        if ends == "killed":
            started.kill()  # the step's own process, as a cancel ends it
        started.communicate(timeout=30)
        deadline = time.monotonic() + 10
        while _alive(pid) and time.monotonic() < deadline:
            time.sleep(0.1)
        assert not _alive(pid), "the step's child outlived it"
    finally:
        if pid_file.exists() and pid_file.read_text():
            _end(int(pid_file.read_text()))
        if started.poll() is None:
            started.kill()


# -- memory gate and priority (polyglotic-hq 1023) ------------------------------------


def test_min_free_gb_tunable_has_metadata_and_range_check() -> None:
    """RULES #40 / polyglotic-hq 1023: `ui_lab.min_free_gb` is declared once
    with default 5 GB, unit GB, bounds 2-12 and reason, and rejects values
    outside its range."""
    assert ci_lock.MIN_FREE_GB.name == "ui_lab.min_free_gb"
    assert ci_lock.MIN_FREE_GB.default == 5.0
    assert ci_lock.MIN_FREE_GB.unit == "GB"
    assert ci_lock.MIN_FREE_GB.bounds == (2.0, 12.0)
    assert ci_lock.MIN_FREE_GB.source
    assert ci_lock.MEMORY_POLL_SECONDS.default == 15.0
    assert ci_lock.MEMORY_POLL_SECONDS.unit == "s"
    assert ci_lock.MEMORY_WAIT_MINUTES.default == 30.0
    assert ci_lock.MEMORY_WAIT_MINUTES.unit == "min"

    for valid in (2, 2.0, 5, 5.0, 12, 12.0):
        assert ci_lock.checked_min_free_gb(valid) == float(valid)

    for out_of_range in (1.99, 0, -1.0, 12.01, 16, float("nan"), float("inf")):
        with pytest.raises(ValueError, match=r"outside 2\.\.12 GB"):
            ci_lock.checked_min_free_gb(out_of_range)

    for wrong_type in (True, False, "5", None):
        with pytest.raises(TypeError, match="expected a number"):
            ci_lock.checked_min_free_gb(wrong_type)

    with pytest.raises(ValueError, match=r"outside 2\.\.12 GB"):
        ci_lock.wait_for_memory(
            1.5,
            memory=lambda: pytest.fail("should reject before reading memory"),
            sleep=lambda _: pytest.fail("should reject before sleeping"),
        )


def test_worker_min_free_gb_tunable_has_metadata_and_range_check() -> None:
    """The per-worker floor is a separate named tunable: language workers
    need enough headroom to start without requiring the pass gate's 5 GB."""
    tunable = ci_lock.WORKER_MIN_FREE_GB
    assert tunable.name == "ui_lab.worker_min_free_gb"
    assert tunable.default == 2.5
    assert tunable.unit == "GB"
    assert tunable.bounds == (1.0, 8.0)
    assert tunable.source

    for valid in (1, 2.5, 8):
        assert ci_lock.checked_worker_min_free_gb(valid) == float(valid)
    for invalid in (0.99, 8.01, float("nan"), float("inf")):
        with pytest.raises(ValueError, match=r"outside 1\.\.8 GB"):
            ci_lock.checked_worker_min_free_gb(invalid)


@pytest.mark.parametrize("free", [5.0, 5.01, 8.5])
def test_memory_gate_continues_at_or_above_floor_with_no_wait(free: float) -> None:
    """Performance budget (1023): zero wait when 5 GB or more is free,
    including exactly at the floor."""
    logs: list[str] = []
    result = ci_lock.wait_for_memory(
        memory=lambda: free,
        sleep=lambda _: pytest.fail("must not sleep at or above the floor"),
        clock=lambda: 100.0,
        say=logs.append,
    )
    assert result.ok is True
    assert result.waits == 0
    assert result.waited_seconds == 0.0
    assert result.free_gb == free
    assert logs == []


def test_memory_gate_waits_under_floor_logs_each_wait_and_continues_at_floor() -> None:
    """Under the floor, the gate polls every 15 s, logs each wait, and
    continues as soon as a reading reaches the floor."""
    readings = [3.1, 4.2, 4.99, 5.0]
    now = [0.0]
    sleeps: list[float] = []
    logs: list[str] = []

    def fake_sleep(seconds: float) -> None:
        sleeps.append(seconds)
        now[0] += seconds

    result = ci_lock.wait_for_memory(
        memory=lambda: readings.pop(0),
        sleep=fake_sleep,
        clock=lambda: now[0],
        say=logs.append,
    )
    assert result.ok is True
    assert result.waits == 3
    assert sleeps == [15.0, 15.0, 15.0]
    assert result.waited_seconds == 45.0
    assert result.free_gb == 5.0
    assert len(logs) == 3
    assert "3.10 GB free < 5 GB; wait 1," in logs[0]
    assert "4.20 GB free < 5 GB; wait 2," in logs[1]
    assert "4.99 GB free < 5 GB; wait 3," in logs[2]


def test_memory_gate_fails_after_30_minutes_with_plain_message() -> None:
    """After 30 minutes under the floor, the gate fails with the plain
    message naming the floor and does not sleep past the limit."""
    now = [0.0]
    sleeps: list[float] = []
    logs: list[str] = []

    def fake_sleep(seconds: float) -> None:
        sleeps.append(seconds)
        now[0] += seconds

    result = ci_lock.wait_for_memory(
        memory=lambda: 3.4,
        sleep=fake_sleep,
        clock=lambda: now[0],
        say=logs.append,
    )
    assert result.ok is False
    assert result.waits == 120
    assert result.waited_seconds == 1800.0
    assert sleeps == [15.0] * 120
    assert len(logs) == 120
    assert "this PC stayed under 5 GB free; the UI lab waits for live" in result.message

    # Custom floor formats cleanly in the failure message too
    now[0] = 0.0
    custom = ci_lock.wait_for_memory(
        6.5,
        poll_seconds=15.0,
        most_minutes=0.5,
        memory=lambda: 4.0,
        sleep=fake_sleep,
        clock=lambda: now[0],
        say=lambda _: None,
    )
    assert custom.ok is False
    assert (
        "this PC stayed under 6.5 GB free; the UI lab waits for live" in custom.message
    )


def test_memory_gate_skips_when_memory_cannot_be_read() -> None:
    result = ci_lock.wait_for_memory(
        memory=lambda: None,
        sleep=lambda _: pytest.fail("must not sleep when memory is unreadable"),
        clock=lambda: 0.0,
    )
    assert result.ok is True
    assert result.waits == 0
    assert result.free_gb is None


def test_main_enforces_memory_gate_from_env_and_validates_range(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """`main` reads the job's floor from `MIN_FREE_GB_VARIABLE`, validates
    `--min-free-gb` and the env var against 2-12 GB, and blocks the command
    without running it when the wait times out."""
    monkeypatch.setenv("POLYGLOTIC_CI_LOCK", str(tmp_path / "steps.lock"))
    ran: list[list[str]] = []

    def fake_run(
        command: list[str], **_kwargs: object
    ) -> subprocess.CompletedProcess[str]:
        ran.append(command)
        return subprocess.CompletedProcess(command, 0)

    monkeypatch.setattr(ci_lock.subprocess, "run", fake_run)
    monkeypatch.setattr(ci_lock, "ending_with_this_process", lambda: "end with it")

    # Invalid range via flag and via env var
    for bad in ("1", "15", "not-a-number"):
        monkeypatch.delenv(ci_lock.MIN_FREE_GB_VARIABLE, raising=False)
        with pytest.raises(SystemExit) as raised:
            ci_lock.main(["alone", "--min-free-gb", bad, "--", "echo", "hi"])
        assert raised.value.code == 2
        assert "ui_lab.min_free_gb" in capsys.readouterr().err

    monkeypatch.setenv(ci_lock.MIN_FREE_GB_VARIABLE, "1")
    with pytest.raises(SystemExit) as raised:
        ci_lock.main(["alone", "--", "echo", "hi"])
    assert raised.value.code == 2
    assert "ui_lab.min_free_gb" in capsys.readouterr().err

    # Under the floor through the timeout: fails without running command
    now = [0.0]

    def fake_sleep(seconds: float) -> None:
        now[0] += seconds

    monkeypatch.setenv(ci_lock.MIN_FREE_GB_VARIABLE, "5")
    monkeypatch.setattr(ci_lock, "free_gb", lambda: 3.0)
    monkeypatch.setattr(ci_lock.time, "monotonic", lambda: now[0])
    monkeypatch.setattr(ci_lock.time, "sleep", fake_sleep)
    code = ci_lock.main(
        [
            "alone",
            "--memory-poll-seconds",
            "15",
            "--memory-wait-minutes",
            "0.5",
            "--",
            "echo",
            "hi",
        ]
    )
    out = capsys.readouterr().out
    assert code == 1
    assert ran == []
    assert "this PC stayed under 5 GB free; the UI lab waits for live" in out
    assert "ci_lock: waiting for memory (3.00 GB free < 5 GB; wait 1," in out

    # At the floor: runs the command with zero waits
    monkeypatch.setattr(ci_lock, "free_gb", lambda: 5.0)
    code = ci_lock.main(["alone", "--", "echo", "hi"])
    out = capsys.readouterr().out
    assert code == 0
    assert ran == [["echo", "hi"]]
    assert "ci_lock: memory ok: 5.00 GB free (floor 5 GB)" in out

    # Explicit --min-free-gb wins over the env var
    monkeypatch.setattr(ci_lock, "free_gb", lambda: 4.0)
    code = ci_lock.main(["alone", "--min-free-gb", "4", "--", "echo", "flag"])
    out = capsys.readouterr().out
    assert code == 0
    assert ran[-1] == ["echo", "flag"]
    assert "ci_lock: memory ok: 4.00 GB free (floor 4 GB)" in out


@WINDOWS
def test_below_normal_priority_applies_to_command_and_its_children(
    tmp_path: Path,
) -> None:
    """polyglotic-hq 1023: `--below-normal` starts the command at Windows'
    BELOW_NORMAL_PRIORITY_CLASS (0x4000), which its child processes inherit
    (the UI lab's parallel language workers)."""
    lock = tmp_path / "steps.lock"
    grandchild = (
        "import ctypes; "
        "k = ctypes.WinDLL('kernel32'); "
        "k.GetCurrentProcess.restype = ctypes.c_void_p; "
        "k.GetPriorityClass.argtypes = [ctypes.c_void_p]; "
        "k.GetPriorityClass.restype = ctypes.c_uint32; "
        "print(hex(k.GetPriorityClass(k.GetCurrentProcess())))"
    )
    probe = (
        "import ctypes, subprocess, sys; "
        "k = ctypes.WinDLL('kernel32'); "
        "k.GetCurrentProcess.restype = ctypes.c_void_p; "
        "k.GetPriorityClass.argtypes = [ctypes.c_void_p]; "
        "k.GetPriorityClass.restype = ctypes.c_uint32; "
        "p = hex(k.GetPriorityClass(k.GetCurrentProcess())); "
        f"g = subprocess.check_output([sys.executable, '-c', {grandchild!r}], text=True).strip(); "
        "print('prio', p, g)"
    )

    lowered = step("shared", lock, probe, "--below-normal")
    out, _ = lowered.communicate(timeout=30)
    assert lowered.returncode == 0
    assert "ci_lock: priority below-normal" in out
    assert "prio 0x4000 0x4000" in out

    # Without the flag the command keeps this test's own priority class. A
    # runner may already start pytest below normal (gpubox's runner does, as
    # GitHub's did on 2026-11-29), so compare with ours, not with "normal".
    k = ctypes.WinDLL("kernel32")  # type: ignore[attr-defined,unused-ignore]
    k.GetCurrentProcess.restype = ctypes.c_void_p
    k.GetPriorityClass.argtypes = [ctypes.c_void_p]
    k.GetPriorityClass.restype = ctypes.c_uint32
    own = hex(k.GetPriorityClass(k.GetCurrentProcess()))
    normal = step("shared", lock, probe)
    out_normal, _ = normal.communicate(timeout=30)
    assert normal.returncode == 0
    assert "ci_lock: priority below-normal" not in out_normal
    assert f"prio {own} {own}" in out_normal
