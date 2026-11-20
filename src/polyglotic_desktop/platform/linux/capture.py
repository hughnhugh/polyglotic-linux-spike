"""Capturing audio on Linux (polyglotic-hq 546, 547, 550): everything the PC
plays and the mic, through the sound server's own library (`pulse.py`) -
the `AudioCapture` port.

- **Everything the PC plays:** a record stream on the default output's
  *monitor*, found by name from the server's own answer (not the
  `@DEFAULT_MONITOR@` alias: a pipewire-pulse bug once recorded the mic
  through it) - or, with an output chosen while it's plugged in, that
  output's monitor.
- **The mic:** a record stream on the input chosen while it's plugged in,
  else the default input. A default input that is an output's monitor
  (`monitor_of`) is no microphone at all: a PC without one gets its
  output's monitor as the default source (547) - captioning that as the
  learner's own speech would caption the game. Nothing is captured then,
  and the capture says why.
- **Following changes:** each capture subscribes to the server's changes
  (`PulseServer.watch`) and checks what it should record whenever one
  comes - and every DEVICE_POLL_SEC anyway - so a new default output,
  headphones plugged in or the server restarted move the capture on
  within a moment. A stream is never moved by the server itself
  (`PA_STREAM_DONT_MOVE`): it ends with its device, and is opened again
  on what's wanted now.
- **One app, everything else:** not yet (slice 2): `app_capture_support`
  says no, so the app offers everything the PC plays only.

The server delivers 16kHz mono float32 itself, so nothing is converted
here: each piece is stamped on the app's clock (`Stamper`) and kept
continuous (`Timeline`). Linux asks no permission for either.

Each capture runs on a thread of its own, with a connection of its own
made on that thread (libpulse's loop is driven there: `pulse.PulseServer`).
"""

from __future__ import annotations

import threading
import time
from collections.abc import Callable, Hashable
from typing import Protocol

from polyglotic_desktop.core.listening.timing import VAD_SAMPLE_RATE
from polyglotic_desktop.platform.linux import pulse
from polyglotic_desktop.platform.timeline import BYTES_PER_SAMPLE, Timeline
from polyglotic_desktop.ports.capture import (
    AppCaptureSupport,
    AppCaptureTrial,
    AudioCallback,
    TrialOutcome,
)

DEVICE_POLL_SEC = 1.0
WAKE_SEC = 0.05
"""How long one pass of the connection's loop may wait for audio."""
RESYNC_SEC = 0.2
"""How far a piece's arrival may stray from the time its samples count to
before the stamps start again from its arrival (a stall, a lost piece)."""
RECONNECT_SEC = 2.0
NO_MIC = "No microphone is plugged in."
NO_OUTPUT = "No speakers or headphones are plugged in."


class Recording(Protocol):
    @property
    def failed(self) -> bool: ...

    def take(self) -> list[tuple[float, bytes]]: ...

    def close(self) -> None: ...


class Server(Protocol):
    """What a capture asks the sound server (`pulse.PulseServer`)."""

    changes: int

    @property
    def alive(self) -> bool: ...

    def server_info(self) -> pulse.Defaults: ...

    def sinks(self) -> list[pulse.Device]: ...

    def sources(self) -> list[pulse.Device]: ...

    def watch(self) -> None: ...

    def record(self, source: str) -> Recording: ...

    def run(self, seconds: float) -> None: ...

    def close(self) -> None: ...


def connect() -> Server:
    return pulse.PulseServer()


class Stamper:
    """When each piece's first sample was captured, on the app's clock: the
    first from its arrival less its length, the rest counted on in samples
    - so stamps don't jitter with the threads - until a piece's arrival
    strays more than RESYNC_SEC from its count (then from its arrival)."""

    def __init__(self) -> None:
        self._next: float | None = None

    def __call__(self, arrival: float, seconds: float) -> float:
        guess = arrival - seconds
        if self._next is None or abs(guess - self._next) > RESYNC_SEC:
            start = guess
        else:
            start = self._next
        self._next = start + seconds
        return start


def output_monitor(server: Server, chosen: str | None) -> tuple[str, str] | None:
    """The monitor to record for everything an output plays, with the
    output's description: the output `chosen` (by name) while it's there,
    else the default output; None if there's no output at all."""
    outputs = server.sinks()
    by_name = {sink.name: sink for sink in outputs}
    sink = by_name.get(chosen or "") or by_name.get(server.server_info().output or "")
    if sink is None or not sink.monitor:
        return None
    return sink.monitor, sink.description


def microphone(server: Server, chosen: str | None) -> tuple[str, str] | None:
    """The input to record as the mic, with its description: `chosen` (by
    name) while it's there, else the default input - unless that is an
    output's monitor, which means there is no microphone (547)."""
    inputs = {source.name: source for source in server.sources()}
    found = inputs.get(chosen or "")
    if found is None or found.monitor_of is not None:
        found = inputs.get(server.server_info().input or "")
    if found is None or found.monitor_of is not None:
        return None
    return found.name, found.description


class _Capture:
    """The thread that runs one capture: connects to the sound server,
    records what `_wanted` names, delivers it continuous, and records
    something else when what's wanted changes."""

    MISSING = ""
    """What `error` says while there's nothing to record."""

    def __init__(
        self,
        device_id: str | None = None,
        connect: Callable[[], Server] = connect,
    ) -> None:
        self.device_id = device_id
        """The device the learner chose (the server's name for it), or None
        for the default."""
        self._connect = connect
        self._thread: threading.Thread | None = None
        self._stop = threading.Event()
        self._capturing: str | None = None
        self._error: str | None = None

    @property
    def capturing(self) -> str | None:
        return self._capturing

    @property
    def error(self) -> str | None:
        return self._error

    def start(self, on_audio: AudioCallback) -> None:
        if self._thread is not None:
            return
        self._stop.clear()
        self._thread = threading.Thread(
            target=self._run, args=(on_audio,), name=type(self).__name__, daemon=True
        )
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=3)
            self._thread = None

    def _wanted(self, server: Server) -> tuple[str, str] | None:
        """The source to record now and its name for the learner."""
        raise NotImplementedError

    def _run(self, on_audio: AudioCallback) -> None:
        timeline = Timeline()
        try:
            while not self._stop.is_set():
                try:
                    server = self._connect()
                except OSError as e:
                    self._capturing, self._error = None, str(e)
                    self._stop.wait(RECONNECT_SEC)
                    continue
                try:
                    self._connected(server, timeline, on_audio)
                except OSError as e:  # the server went: connect again
                    self._capturing, self._error = None, str(e)
                    self._stop.wait(RECONNECT_SEC)
                finally:
                    server.close()
        except Exception as e:  # noqa: BLE001 - the thread must not die quietly
            # Report it by its type, never its text: it could hold anything.
            self._error = f"Capture stopped: {type(e).__name__}"
        finally:
            self._capturing = None

    def _connected(
        self, server: Server, timeline: Timeline, on_audio: AudioCallback
    ) -> None:
        server.watch()
        while not self._stop.is_set():
            seen = server.changes
            wanted = self._wanted(server)
            if wanted is None:
                self._capturing, self._error = None, self.MISSING
                self._idle(server, timeline, on_audio, seen)
                continue
            source, name = wanted
            try:
                recording = server.record(source)
            except OSError as e:  # it went as it was opened: look again
                if not server.alive:
                    raise
                self._capturing, self._error = None, str(e)
                self._idle(server, timeline, on_audio, seen)
                continue
            try:
                self._capturing, self._error = name, None
                self._pump(server, recording, wanted, timeline, on_audio)
            finally:
                recording.close()

    def _idle(
        self, server: Server, timeline: Timeline, on_audio: AudioCallback, seen: int
    ) -> None:
        """Nothing to record: silence, until the server changes or a poll."""
        until = time.perf_counter() + DEVICE_POLL_SEC
        while not self._stop.is_set() and time.perf_counter() < until:
            server.run(WAKE_SEC)
            for piece in timeline.idle(time.perf_counter()):
                on_audio(*piece)
            if server.changes != seen:
                return
        if not server.alive:
            raise OSError("The sound server went away")

    def _pump(
        self,
        server: Server,
        recording: Recording,
        wanted: Hashable,
        timeline: Timeline,
        on_audio: AudioCallback,
    ) -> None:
        stamper = Stamper()
        seen = server.changes
        next_check = time.perf_counter() + DEVICE_POLL_SEC
        while not self._stop.is_set():
            server.run(WAKE_SEC)
            delivered = False
            for arrival, data in recording.take():
                usable = data[: len(data) - len(data) % BYTES_PER_SAMPLE]
                seconds = len(usable) / BYTES_PER_SAMPLE / VAD_SAMPLE_RATE
                for piece in timeline.packet(stamper(arrival, seconds), usable):
                    on_audio(*piece)
                    delivered = True
            now = time.perf_counter()
            if not delivered:
                for piece in timeline.idle(now):
                    on_audio(*piece)
            if recording.failed:  # its device went: what's wanted now?
                if not server.alive:
                    raise OSError("The sound server went away")
                return
            if server.changes != seen or now >= next_check:
                seen, next_check = server.changes, now + DEVICE_POLL_SEC
                if self._wanted(server) != wanted:
                    return


class SystemCapture(_Capture):
    """Everything the PC plays: the default output's monitor as the default
    changes - or the output the learner chose, while it's plugged in."""

    MISSING = NO_OUTPUT

    def _wanted(self, server: Server) -> tuple[str, str] | None:
        return output_monitor(server, self.device_id)


class MicCapture(_Capture):
    """A microphone: the one chosen while it's plugged in, else the default
    input - never an output's monitor (no microphone, then)."""

    MISSING = NO_MIC

    def _wanted(self, server: Server) -> tuple[str, str] | None:
        return microphone(server, self.device_id)


# -- one app at a time: not yet (slice 2) ---------------------------------------


def app_capture_support() -> AppCaptureSupport:
    """One app alone: not yet on Linux (polyglotic-hq 546's slice 2) - so
    everything the PC plays is the only choice, as on an older Windows 10."""
    return AppCaptureSupport.NO


def no_windows_build() -> str:
    """`OsAdapters.windows_build`: none on Linux."""
    return ""


class Trial:
    """The `AppCaptureTrial` port: never needed (no app is captured alone
    yet), kept so `main` can ask the same."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._outcome: TrialOutcome | None = None

    @property
    def outcome(self) -> TrialOutcome | None:
        return self._outcome

    def tell(self, outcome: TrialOutcome) -> None:
        with self._lock:
            if self._outcome is None:
                self._outcome = outcome


class NotYet:
    """One app's capture, or everything else's: not on Linux yet. Never
    asked for while `app_capture_support` says no; if it is, it captures
    nothing and says why."""

    def __init__(self, *_args: object, **_kwargs: object) -> None:
        pass

    def start(self, _on_audio: AudioCallback) -> None:
        pass

    def stop(self) -> None:
        pass

    @property
    def capturing(self) -> str | None:
        return None

    @property
    def error(self) -> str | None:
        return "Capturing one app alone isn't on Linux yet."


def app_capture(
    _process_id: int, _name: str, _trial: AppCaptureTrial | None = None
) -> NotYet:
    return NotYet()


def everything_else_capture(
    _process_id: int, _trial: AppCaptureTrial | None = None
) -> NotYet:
    return NotYet()
