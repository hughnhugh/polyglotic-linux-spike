"""Small, content-free evidence that the previous app run did not finish.

The running note is deliberately separate from the log: it contains only
process metadata and is removed only after orderly shutdown has completed.
Its run id is the same random id the run's first log line and its crash
trace's first line carry (`app_log.RUN_LOG`, `crash_trace.header`), so the
next start offers that run's evidence and no other run's; the id itself
never leaves the PC (polyglotic-hq 1009).
The freeze watch asks the interface for a heartbeat and, when it misses one,
writes Python frame locations (never locals) using :mod:`faulthandler`.
"""

from __future__ import annotations

import json
import os
import secrets
import sys
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import TextIO

RUN_NOTE_NAME = "running.json"
FREEZE_AFTER_SECONDS = 10.0
"""Unanswered UI heartbeat before a trace (seconds, 5-30; 10 avoids busy starts)."""
FREEZE_POLL_SECONDS = 1.0
"""Freeze-watch polling interval (seconds, 0.25-1; one wake per second)."""
QUIT_DEADLINE_SECONDS = 3.0
"""Maximum orderly shutdown time (seconds, fixed by the product brief)."""
RUN_ID_BYTES = 8
"""A run id's random bytes (16 hex digits): new each run, kept on this PC."""


def new_run_id() -> str:
    """A random id for this run: in its note, first log line and trace."""
    return secrets.token_hex(RUN_ID_BYTES)


@dataclass(frozen=True, slots=True)
class PreviousRun:
    version: str
    started_at: str
    process_id: int
    run_id: str


class RunningNote:
    """Atomically create and remove the process' content-free running note."""

    def __init__(
        self,
        data: Path,
        version: str,
        process_id: int | None = None,
        process_is_polyglotic: Callable[[int], bool] | None = None,
        run_id: str | None = None,
    ) -> None:
        self.path = data / RUN_NOTE_NAME
        self.version = version
        self.process_id = os.getpid() if process_id is None else process_id
        self.run_id = new_run_id() if run_id is None else run_id
        self._process_is_polyglotic = process_is_polyglotic or _is_polyglotic_process

    def previous(self) -> PreviousRun | None:
        try:
            value = json.loads(self.path.read_text("utf-8"))
            previous = PreviousRun(
                str(value["version"]),
                str(value["started_at"]),
                int(value["process_id"]),
                str(value["run_id"]),
            )
        except (OSError, ValueError, KeyError, TypeError):
            # A damaged note must not produce an offer on every later start.
            self._remove()
            return None
        if self._process_is_polyglotic(previous.process_id):
            # The owner is still alive: this is another copy, not a crash.  Its
            # note belongs to it and must remain until that copy shuts down.
            return None
        # Claim the evidence before returning it, so one improper run is
        # offered exactly once even if this start itself fails shortly after.
        self._remove()
        return previous

    def start(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.path.with_suffix(".tmp")
        temporary.write_text(
            json.dumps(
                {
                    "version": self.version,
                    "started_at": datetime.now(UTC).isoformat(timespec="seconds"),
                    "process_id": self.process_id,
                    "run_id": self.run_id,
                },
                separators=(",", ":"),
            ),
            "utf-8",
        )
        temporary.replace(self.path)

    def finish(self) -> None:
        """This run's note gone, as it ends properly: never another run's,
        which a copy relaunched (a new interface language) or a second copy
        may have written since; and a damaged one is left for the next
        start (`previous`) to put away."""
        try:
            note = json.loads(self.path.read_text("utf-8"))
        except (OSError, ValueError):
            return
        if isinstance(note, dict) and note.get("run_id") == self.run_id:
            self._remove()

    def _remove(self) -> None:
        self.path.unlink(missing_ok=True)


def hard_exit(code: int) -> None:
    """End this process now, with `code`.

    On Windows by `TerminateProcess`, which skips the libraries' unloading:
    `os._exit` runs it, and with the interface thread hung in a part Qt's
    crashed there (an access violation, exit 0xC0000005, not `code`), on
    GitHub's Windows machine (polyglotic-hq 1009). The log's lines are
    already written (each record is flushed), and the trace is unbuffered.
    Elsewhere `os._exit`."""
    if sys.platform == "win32":
        import ctypes
        from ctypes import wintypes

        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        terminate = kernel32.TerminateProcess
        terminate.argtypes = (wintypes.HANDLE, wintypes.UINT)
        terminate.restype = wintypes.BOOL
        current = wintypes.HANDLE(-1)  # GetCurrentProcess()'s own handle
        terminate(current, code)
    os._exit(code)  # elsewhere; and on Windows if that was refused


class CleanShutdown:
    """Run the one ordered shutdown path, once, with a hard deadline."""

    def __init__(
        self,
        steps: list[tuple[str, Callable[[], None]]],
        *,
        deadline: float = QUIT_DEADLINE_SECONDS,
        timed_out: Callable[[str], None],
        force_exit: Callable[[int], None] = hard_exit,
        before_force_exit: Callable[[], None] | None = None,
    ) -> None:
        self._steps = steps
        self._deadline = deadline
        self._timed_out = timed_out
        self._force_exit = force_exit
        self._before_force_exit = before_force_exit or (lambda: None)
        self._lock = threading.Lock()
        self._started = False
        self._part = "starting"

    def __call__(self) -> None:
        with self._lock:
            if self._started:
                return
            self._started = True

        def force() -> None:
            self._timed_out(self._part)
            # Evidence of a running process must never survive an intentional
            # deadline exit.  This hook is deliberately independent of the
            # possibly hung ordered cleanup thread.
            self._before_force_exit()
            self._force_exit(1)

        deadline = threading.Timer(self._deadline, force)
        deadline.name = "quit-deadline"
        deadline.daemon = True
        deadline.start()
        try:
            for part, step in self._steps:
                self._part = part
                step()
        finally:
            deadline.cancel()


def _is_polyglotic_process(
    process_id: int,
    *,
    windows: bool = sys.platform == "win32",
    windows_image: Callable[[int], str] | None = None,
) -> bool:
    """Whether *process_id* is alive and its command identifies this app.

    PIDs are reused, so merely probing the PID would misclassify an unrelated
    process as a second copy.  Linux exposes the command without another
    dependency; packaged Windows copies have ``Polyglotic`` in their image
    name.  A source run is also recognised by its ``polyglotic_desktop``
    module/path.

    Windows never goes near ``os.kill``: there it sends Ctrl+C to, or
    terminates, whatever process now has that id (polyglotic-hq RULES #50).
    It asks for the image of a process still running instead.
    """
    if process_id <= 0:
        return False
    if windows:
        image = (windows_image or _windows_process_image)(process_id)
        return "polyglotic" in image.casefold()
    try:
        os.kill(process_id, 0)  # POSIX: signal 0 only asks whether it's alive
    except (OSError, ValueError):
        return False
    try:
        command = (
            Path(f"/proc/{process_id}/cmdline")
            .read_bytes()
            .replace(b"\0", b" ")
            .decode("utf-8", errors="replace")
        )
    except OSError:
        return False
    return "polyglotic" in command.casefold()


def _windows_process_image(process_id: int) -> str:
    """A running Windows process's image path, or "" if it has ended or
    can't be asked."""
    if sys.platform != "win32":
        return ""
    import ctypes
    from ctypes import wintypes

    query_limited_information = 0x1000
    still_active = 259
    kernel32 = ctypes.windll.kernel32
    process = kernel32.OpenProcess(query_limited_information, False, process_id)
    if not process:
        return ""
    try:
        code = wintypes.DWORD()
        if not kernel32.GetExitCodeProcess(process, ctypes.byref(code)):
            return ""
        if code.value != still_active:  # ended; a handle still held keeps it
            return ""
        size = wintypes.DWORD(32768)
        buffer = ctypes.create_unicode_buffer(size.value)
        if kernel32.QueryFullProcessImageNameW(process, 0, buffer, ctypes.byref(size)):
            return buffer.value
        return ""
    finally:
        kernel32.CloseHandle(process)


class FreezeWatch:
    """Write all Python stacks when the interface stops acknowledging beats.

    `stream` gives the trace's file as it is now: the crash trace can start
    its file again (`CrashTrace.keep_small`), which closes the one before."""

    def __init__(
        self,
        stream: Callable[[], TextIO | None],
        *,
        after: float = FREEZE_AFTER_SECONDS,
        poll: float = FREEZE_POLL_SECONDS,
    ) -> None:
        self._stream = stream
        self._after = after
        self._poll = poll
        self._last_beat = time.monotonic()
        self._stopped = threading.Event()
        self._thread: threading.Thread | None = None
        self._written = False

    def start(self) -> None:
        if self._thread is not None:
            return
        import faulthandler

        def watch() -> None:
            while not self._stopped.wait(self._poll):
                if (
                    not self._written
                    and time.monotonic() - self._last_beat >= self._after
                ):
                    stream = self._stream()
                    if stream is None:
                        continue
                    try:
                        faulthandler.dump_traceback(stream, all_threads=True)
                        stream.flush()
                    except (OSError, ValueError):
                        continue  # closed as it was started again: next poll
                    self._written = True

        self._thread = threading.Thread(target=watch, name="freeze-watch", daemon=True)
        self._thread.start()

    def beat(self) -> None:
        self._last_beat = time.monotonic()
        self._written = False

    def stop(self) -> None:
        self._stopped.set()
        if self._thread is not None:
            self._thread.join(timeout=self._poll * 2)
            self._thread = None
