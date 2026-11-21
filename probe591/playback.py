"""591's probe: the app's playback stream (pulse.Playback) on pipewire-pulse,
each write the server asked for and the drain timed, beside what the
default output's monitor heard (parecord) - the default buffer, and one
the size of the clip."""

import ctypes
import json
import math
import struct
import subprocess
import sys
import time
from array import array
from pathlib import Path

from polyglotic_desktop.platform.linux import pulse

OUT = Path(sys.argv[1])
OUT.mkdir(parents=True, exist_ok=True)


class _Attr(ctypes.Structure):
    _fields_ = [(n, ctypes.c_uint32) for n in ("maxlength", "tlength", "prebuf", "minreq", "fragsize")]


def tone(seconds: float, rate: int) -> bytes:
    n = round(seconds * rate)
    return struct.pack(f"<{n}h", *(round(0.5 * 32767 * math.sin(2 * math.pi * 440 * i / rate)) for i in range(n)))


def levels(name: str) -> dict:
    data = (OUT / name).read_bytes()
    s = array("h")
    s.frombytes(data[: len(data) // 2 * 2])
    rows = []
    for i in range(0, len(s), 320):
        part = s[i : i + 320]
        rms = math.sqrt(sum(x * x for x in part) / max(1, len(part))) or 1e-9
        rows.append(round(20 * math.log10(rms / 32768), 1))
    loud = [i for i, db in enumerate(rows) if db > -45]
    return {"loud_from": loud[0] * 0.02 if loud else None, "loud_to": (loud[-1] + 1) * 0.02 if loud else None,
            "loud_pieces": len(loud), "rows": "".join("#" if db > -45 else "." for db in rows)}


def trial(name: str, pcm: bytes, rate: int, poll: float, big: bool) -> dict:
    lib = pulse.library()
    lib.pa_stream_get_buffer_attr.restype = ctypes.POINTER(_Attr)
    lib.pa_stream_get_buffer_attr.argtypes = [ctypes.c_void_p]
    events = []
    t0 = time.perf_counter()
    original = pulse.Playback._writable

    def writable(self, stream, size, data):
        events.append(("write", round(time.perf_counter() - t0, 3), size, self._at))
        original(self, stream, size, data)

    def drained(self, stream, success, data):
        events.append(("drained", round(time.perf_counter() - t0, 3), success))
        self.done = True

    pulse.Playback._writable = writable
    pulse.Playback._drained = drained
    rec = subprocess.Popen(["parecord", "--device=session_speakers.monitor", "--raw", "--format=s16le",
                            "--rate=16000", "--channels=1", str(OUT / f"{name}.raw")])
    time.sleep(0.5)
    t0 = time.perf_counter()
    server = pulse.PulseServer("probe")
    playback = server.play(pcm, rate, 1)
    a = lib.pa_stream_get_buffer_attr(playback._stream).contents
    attr = {n: getattr(a, n) for n, _ in _Attr._fields_}
    events.append(("ready", round(time.perf_counter() - t0, 3)))
    while not playback.done and time.perf_counter() - t0 < 6:
        server.run(0)
        time.sleep(poll)
    events.append(("loop_end", round(time.perf_counter() - t0, 3), playback.done))
    playback.close()
    server.close()
    time.sleep(0.5)
    rec.terminate(); rec.wait()
    pulse.Playback._writable = original
    return {"name": name, "bytes": len(pcm), "rate": rate, "attr": attr, "events": events[:40],
            "writes": sum(1 for e in events if e[0] == "write"), "heard": levels(f"{name}.raw")}


results = [
    trial("tone-24k-poll20ms", tone(0.8, 24000), 24000, 0.02, False),
    trial("tone-16k-2s-poll50ms", tone(2.0, 16000), 16000, 0.05, False),
]
(OUT / "playback.json").write_text(json.dumps(results, indent=1), encoding="utf-8")
for r in results:
    print(json.dumps({k: v for k, v in r.items() if k != "heard"}))
    print("  heard:", json.dumps(r["heard"]))
