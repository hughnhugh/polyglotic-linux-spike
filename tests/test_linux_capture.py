"""Capturing on Linux (polyglotic-hq 546, 547, 550): what each capture
records - the default output's monitor by name, the output chosen, the mic
but never an output's monitor - and how it follows the sound server's
changes, through a stand-in server. The real one is `linux_desktop`:
PipeWire's pulse server on GitHub's Ubuntu runner (`linux.yml`)."""

import shutil
import struct
import subprocess
import threading
import time
from collections.abc import Callable

import numpy as np
import pytest

from polyglotic_desktop.platform.linux import capture, devices, pulse
from polyglotic_desktop.platform.linux.capture import MicCapture, SystemCapture

SPEAKERS = pulse.Device(
    "alsa_output.speakers", "Speakers", 1, True, monitor="alsa_output.speakers.monitor"
)
HEADPHONES = pulse.Device(
    "bluez_output.phones", "Headphones", 2, False, monitor="bluez_output.phones.monitor"
)
SPEAKERS_MONITOR = pulse.Device(
    "alsa_output.speakers.monitor", "Monitor of Speakers", 3, True, monitor_of=1
)
MIC = pulse.Device("alsa_input.mic", "Built-in Mic", 4, False)
USB_MIC = pulse.Device("alsa_input.usb", "USB Mic", 5, False)


class FakeRecording:
    def __init__(self, source: str) -> None:
        self.source = source
        self.pieces: list[tuple[float, bytes]] = []
        self.failed = False
        self.closed = False

    def take(self) -> list[tuple[float, bytes]]:
        pieces, self.pieces = self.pieces, []
        return pieces

    def close(self) -> None:
        self.closed = True


class FakeServer:
    """The sound server as a capture sees it: its devices and defaults, which
    a test changes (counted as the server's changes)."""

    def __init__(self) -> None:
        self.outputs = [SPEAKERS, HEADPHONES]
        self.inputs = [SPEAKERS_MONITOR, MIC, USB_MIC]
        self.default_output: str | None = SPEAKERS.name
        self.default_input: str | None = MIC.name
        self.changes = 0
        self.alive = True
        self.recordings: list[FakeRecording] = []
        self.refuse: set[str] = set()
        self.closed = 0

    def server_info(self) -> pulse.Defaults:
        if not self.alive:
            raise OSError("gone")
        return pulse.Defaults(
            "PulseAudio (on PipeWire 1.0.5)", self.default_output, self.default_input
        )

    def sinks(self) -> list[pulse.Device]:
        return list(self.outputs)

    def sources(self) -> list[pulse.Device]:
        return list(self.inputs)

    def watch(self) -> None:
        pass

    def record(self, source: str) -> FakeRecording:
        if source in self.refuse:
            raise OSError("The sound server didn't start recording that device")
        recording = FakeRecording(source)
        self.recordings.append(recording)
        return recording

    def run(self, seconds: float) -> None:
        time.sleep(min(seconds, 0.01))

    def close(self) -> None:
        self.closed += 1

    def change(self, **values: object) -> None:
        for key, value in values.items():
            setattr(self, key, value)
        self.changes += 1


def wait_for(condition: Callable[[], object], seconds: float = 3.0) -> None:
    end = time.monotonic() + seconds
    while not condition():
        assert time.monotonic() < end, "timed out"
        time.sleep(0.01)


def started(
    make: Callable[..., capture._Capture], server: FakeServer, device: str | None = None
) -> tuple[capture._Capture, list[tuple[float, bytes]]]:
    heard: list[tuple[float, bytes]] = []
    made = make(device, connect=lambda: server)
    made.start(lambda at, data: heard.append((at, data)))
    return made, heard


def test_everything_the_pc_plays_is_the_default_outputs_monitor_by_name() -> None:
    server = FakeServer()
    system, _ = started(SystemCapture, server)
    try:
        wait_for(lambda: server.recordings)
        assert server.recordings[0].source == "alsa_output.speakers.monitor"
        wait_for(lambda: system.capturing == "Speakers")
    finally:
        system.stop()


def test_a_new_default_output_is_followed() -> None:
    """Headphones plugged in become the default: the next recording is their
    monitor, the speakers' closed."""
    server = FakeServer()
    system, _ = started(SystemCapture, server)
    try:
        wait_for(lambda: server.recordings)
        server.change(default_output=HEADPHONES.name)
        wait_for(lambda: len(server.recordings) == 2)
        assert server.recordings[1].source == "bluez_output.phones.monitor"
        assert server.recordings[0].closed
    finally:
        system.stop()


def test_the_output_chosen_while_its_plugged_in() -> None:
    server = FakeServer()
    system, _ = started(SystemCapture, server, HEADPHONES.name)
    try:
        wait_for(lambda: server.recordings)
        assert server.recordings[0].source == "bluez_output.phones.monitor"
        server.change(outputs=[SPEAKERS])  # unplugged: the default then
        wait_for(lambda: len(server.recordings) == 2)
        assert server.recordings[1].source == "alsa_output.speakers.monitor"
    finally:
        system.stop()


def test_no_output_at_all_says_so() -> None:
    server = FakeServer()
    server.outputs, server.default_output = [], None
    system, _ = started(SystemCapture, server)
    try:
        wait_for(lambda: system.error == capture.NO_OUTPUT)
        assert not server.recordings and system.capturing is None
    finally:
        system.stop()


def test_the_mic_is_the_default_input() -> None:
    server = FakeServer()
    mic, _ = started(MicCapture, server)
    try:
        wait_for(lambda: server.recordings)
        assert server.recordings[0].source == "alsa_input.mic"
        assert mic.capturing == "Built-in Mic"
    finally:
        mic.stop()


def test_the_mic_chosen_while_its_plugged_in() -> None:
    server = FakeServer()
    mic, _ = started(MicCapture, server, USB_MIC.name)
    try:
        wait_for(lambda: server.recordings)
        assert server.recordings[0].source == "alsa_input.usb"
    finally:
        mic.stop()


def test_a_default_input_that_is_an_outputs_monitor_is_no_microphone() -> None:
    """A PC with no mic gets its output's monitor as the default source
    (547): captioning it as the learner's own speech would caption the game.
    Nothing is recorded; the capture says why - and a monitor chosen by
    name isn't taken either."""
    server = FakeServer()
    server.inputs, server.default_input = [SPEAKERS_MONITOR], SPEAKERS_MONITOR.name
    for chosen in (None, SPEAKERS_MONITOR.name):
        mic, _ = started(MicCapture, server, chosen)
        try:
            wait_for(lambda m=mic: m.error == capture.NO_MIC)  # type: ignore[misc]
            assert not server.recordings and mic.capturing is None
        finally:
            mic.stop()
    server.change(inputs=[SPEAKERS_MONITOR, MIC], default_input=MIC.name)
    mic, _ = started(MicCapture, server)
    try:
        wait_for(lambda: server.recordings)
        assert server.recordings[0].source == MIC.name
    finally:
        mic.stop()


def floats(*values: float) -> bytes:
    return struct.pack(f"<{len(values)}f", *values)


def test_audio_is_delivered_as_it_came_stamped_on_the_apps_clock() -> None:
    server = FakeServer()
    system, heard = started(SystemCapture, server)
    try:
        wait_for(lambda: server.recordings)
        now = time.perf_counter()
        piece = floats(*([0.25] * 320))  # 20 ms at 16kHz
        server.recordings[0].pieces += [(now, piece), (now + 0.02, piece)]
        wait_for(lambda: sum(len(d) for _, d in heard) >= 2 * len(piece))
        sound = [(at, data) for at, data in heard if any(np.frombuffer(data, "<f4"))]
        assert sound[0][1] == piece
        assert sound[1][0] == pytest.approx(sound[0][0] + 0.02, abs=1e-6)
        assert sound[0][0] == pytest.approx(now - 0.02, abs=0.01)
    finally:
        system.stop()


def test_silence_fills_in_while_nothing_plays() -> None:
    """Once audio has started, a quiet output still gives continuous audio
    (the port's promise): zeros, on the app's clock."""
    server = FakeServer()
    system, heard = started(SystemCapture, server)
    try:
        wait_for(lambda: server.recordings)
        server.recordings[0].pieces.append((time.perf_counter(), floats(0.5)))
        wait_for(lambda: sum(len(d) for _, d in heard) > 16_000)  # over 0.25 s
        starts = [at for at, _ in heard]
        assert starts == sorted(starts)
    finally:
        system.stop()


def test_a_recording_whose_device_went_is_opened_again() -> None:
    server = FakeServer()
    system, _ = started(SystemCapture, server)
    try:
        wait_for(lambda: server.recordings)
        server.recordings[0].failed = True
        wait_for(lambda: len(server.recordings) == 2)
        assert server.recordings[1].source == "alsa_output.speakers.monitor"
    finally:
        system.stop()


def test_a_device_that_wont_record_is_said_and_tried_again() -> None:
    server = FakeServer()
    server.refuse.add("alsa_output.speakers.monitor")
    system, _ = started(SystemCapture, server)
    try:
        wait_for(lambda: system.error and "didn't start" in system.error)
        server.refuse.clear()
        server.change()
        wait_for(lambda: server.recordings, 4.0)
        wait_for(lambda: system.error is None)
    finally:
        system.stop()


def test_no_sound_server_is_said_and_connected_again(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(capture, "RECONNECT_SEC", 0.05)
    server = FakeServer()
    tries: list[int] = []

    def connect() -> FakeServer:
        tries.append(1)
        if len(tries) < 3:
            raise OSError("No sound server to connect to")
        return server

    system = SystemCapture(connect=connect)
    system.start(lambda *_a: None)
    try:
        wait_for(lambda: server.recordings)
        assert len(tries) == 3
    finally:
        system.stop()


def test_a_server_that_goes_away_is_connected_to_again(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(capture, "RECONNECT_SEC", 0.05)
    first, second = FakeServer(), FakeServer()
    servers = iter([first, second])
    system = SystemCapture(connect=lambda: next(servers))
    system.start(lambda *_a: None)
    try:
        wait_for(lambda: first.recordings)
        first.alive = False
        first.recordings[0].failed = True
        wait_for(lambda: second.recordings)
        assert first.closed == 1
    finally:
        system.stop()


def test_stop_ends_the_thread_and_closes_the_connection() -> None:
    server = FakeServer()
    system, _ = started(SystemCapture, server)
    wait_for(lambda: server.recordings)
    system.stop()
    assert server.recordings[0].closed and server.closed == 1
    assert system.capturing is None


# --- the device lists ---------------------------------------------------------


def test_the_devices_listed_never_count_a_monitor_as_a_mic() -> None:
    found = devices.listed(
        [HEADPHONES, SPEAKERS],
        [SPEAKERS_MONITOR, USB_MIC, MIC],
        pulse.Defaults("x", SPEAKERS.name, SPEAKERS_MONITOR.name),
    )
    assert [d.name for d in found.speakers] == ["Headphones", "Speakers"]
    assert [d.id for d in found.mics] == ["alsa_input.mic", "alsa_input.usb"]
    assert found.default_speaker == SPEAKERS.name
    assert found.default_mic is None  # the monitor: no mic


def test_no_sound_server_lists_nothing() -> None:
    def none() -> FakeServer:
        raise OSError("no server")

    assert devices.sound_devices(none).speakers == ()
    assert devices.outputs_playing(none) is None


def test_outputs_playing_counts_the_running_ones() -> None:
    server = FakeServer()
    assert devices.outputs_playing(lambda: server) == 1
    assert server.closed == 1


# --- the real sound server (GitHub's Ubuntu runner) -----------------------------


def play(seconds: float, hz: float) -> subprocess.Popen[bytes]:
    """A tone on the default output, through the server's own player."""
    player = shutil.which("pw-play") or shutil.which("paplay")
    assert player, "pw-play or paplay"
    rate = 48_000
    t = np.arange(int(seconds * rate)) / rate
    tone = (0.3 * np.sin(2 * np.pi * hz * t)).astype("<f4").tobytes()
    if player.endswith("pw-play"):
        args = [player, "--rate", str(rate), "--channels", "1", "--format", "f32", "-"]
    else:
        args = [
            player,
            "--raw",
            "--rate",
            str(rate),
            "--channels",
            "1",
            "--format",
            "float32le",
        ]
    process = subprocess.Popen(args, stdin=subprocess.PIPE)
    sink = process.stdin
    assert sink is not None

    def feed() -> None:
        sink.write(tone)
        sink.close()

    threading.Thread(target=feed, daemon=True).start()
    return process


@pytest.mark.linux_desktop
def test_the_real_server_names_its_defaults_and_devices() -> None:
    server = pulse.PulseServer("Polyglotic tests")
    try:
        defaults = server.server_info()
        assert "PulseAudio" in defaults.server
        outputs = server.sinks()
        assert defaults.output in {sink.name for sink in outputs}
        assert all(sink.monitor for sink in outputs)
        monitors = [s for s in server.sources() if s.monitor_of is not None]
        assert {m.name for m in monitors} == {sink.monitor for sink in outputs}
    finally:
        server.close()


@pytest.mark.linux_desktop
def test_everything_the_pc_plays_is_heard_through_the_real_server() -> None:
    """A tone played on the default output comes back through the system
    capture as 16kHz float32, loud, about as long as it played."""
    heard: list[tuple[float, bytes]] = []
    system = SystemCapture()
    system.start(lambda at, data: heard.append((at, data)))
    try:
        wait_for(lambda: system.capturing is not None, 10)
        player = play(2.0, 440)
        player.wait(timeout=20)
        time.sleep(0.5)
    finally:
        system.stop()
    samples = np.frombuffer(b"".join(d for _, d in heard), "<f4")
    assert len(samples) > 16_000  # over a second
    assert float(np.sqrt(np.mean(samples**2))) > 0.02
    starts = [at for at, _ in heard]
    assert starts == sorted(starts)
