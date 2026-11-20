#!/usr/bin/env python3
"""547 capture probe: libpulse through ctypes on the runner's own PipeWire.

Questions (Polyglotic's project 547, item 2):
- the server's name and version (PipeWire's, against Ubuntu 24.04's 1.0.5);
- the apps playing (sink inputs) and their names, for a libpulse client
  (paplay) and a native PipeWire client (pw-play);
- one app's sink-input monitor with PA_STREAM_DONT_MOVE: each tone's level
  and the isolation between apps;
- what happens to that monitor when its app stops, with and without
  DONT_MOVE;
- the default sink's monitor (by its monitor_source_name), and a mic source
  by name and as the default source;
- chunk sizes and the first-sample latency.

Tones (48 kHz mono, -12 dBFS): app A 440 Hz, app B 1000 Hz, the mic 700 Hz.
Writes results.json and probe.log to the folder given.
"""

from __future__ import annotations

import array
import json
import math
import os
import statistics
import struct
import subprocess
import sys
import time
import wave

if not (sys.platform.startswith("linux") and os.environ.get("GITHUB_ACTIONS") == "true"):
    sys.exit("547: this probe runs only on GitHub's Ubuntu runners")

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import pulse as P  # noqa: E402

OUT = sys.argv[1] if len(sys.argv) > 1 else "out"
os.makedirs(OUT, exist_ok=True)
LOG = open(os.path.join(OUT, "probe.log"), "w", encoding="utf-8")
RATE = 16000
FREQS = {"A 440": 440.0, "B 1000": 1000.0, "mic 700": 700.0, "floor 2500": 2500.0}
results: dict = {"checks": {}}
failures: list[str] = []


def log(*a) -> None:
    line = " ".join(str(x) for x in a)
    print(line, flush=True)
    LOG.write(line + "\n")
    LOG.flush()


def check(name: str, ok: bool, detail: str) -> None:
    results["checks"][name] = {"ok": ok, "detail": detail}
    log(f"[{'PASS' if ok else 'FAIL'}] {name}: {detail}")
    if not ok:
        failures.append(name)


# --- tones -------------------------------------------------------------------

def tone_samples(freq: float, seconds: float, rate: int = 48000, amp: float = 0.25) -> bytes:
    n = int(seconds * rate)
    a = array.array("h", (int(amp * 32767 * math.sin(2 * math.pi * freq * i / rate)) for i in range(n)))
    return a.tobytes()


def write_wav(path: str, freq: float, seconds: float) -> None:
    with wave.open(path, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(48000)
        w.writeframes(tone_samples(freq, seconds))


_hann: dict[int, list[float]] = {}


def level_db(samples, freq: float, rate: int = RATE) -> float | None:
    """A tone's amplitude in dBFS (Goertzel with a Hann window)."""
    n = len(samples)
    if n < 512:
        return None
    win = _hann.get(n)
    if win is None:
        win = [0.5 - 0.5 * math.cos(2 * math.pi * i / (n - 1)) for i in range(n)]
        _hann[n] = win
    coeff = 2 * math.cos(2 * math.pi * freq / rate)
    s1 = s2 = 0.0
    for x, h in zip(samples, win):
        s0 = x * h + coeff * s1 - s2
        s2 = s1
        s1 = s0
    power = s1 * s1 + s2 * s2 - coeff * s1 * s2
    amp = 2 * math.sqrt(max(power, 0.0)) / (n * 0.5)
    return round(20 * math.log10(amp / 32768), 1) if amp > 0 else -200.0


def rms_db(samples) -> float:
    if not samples:
        return -200.0
    r = math.sqrt(sum(x * x for x in samples) / len(samples))
    return round(20 * math.log10(r / 32768), 1) if r > 0 else -200.0


def levels(data: bytes | bytearray) -> dict:
    a = array.array("h")
    a.frombytes(bytes(data[: len(data) // 2 * 2]))
    # skip the first 0.25 s (the stream settling), use up to 3 s
    seg = a[RATE // 4: RATE // 4 + 3 * RATE]
    out = {k: level_db(seg, f) for k, f in FREQS.items()}
    out["rms"] = rms_db(seg)
    out["seconds"] = round(len(a) / RATE, 2)
    out["peak_hz"] = peak_hz(seg[: RATE // 4])
    return out


def peak_hz(seg) -> float | None:
    """The strongest frequency, 50-4000 Hz in 10 Hz steps."""
    best = (-300.0, None)
    for f in range(50, 4001, 10):
        v = level_db(seg, float(f))
        if v is not None and v > best[0]:
            best = (v, f)
    return best[1]


def windows(data: bytes | bytearray, mark: int, step: float = 0.5) -> list[dict]:
    """Levels per half second, times relative to the mark (the kill)."""
    a = array.array("h")
    a.frombytes(bytes(data[: len(data) // 2 * 2]))
    n = int(step * RATE)
    m = mark // 2
    out = []
    for start in range(0, len(a) - n + 1, n):
        seg = a[start: start + n]
        out.append({
            "t": round((start - m) / RATE, 2),
            **{k: level_db(seg, f) for k, f in FREQS.items() if k != "floor 2500"},
            "rms": rms_db(seg),
        })
    return out


def chunk_stats(rec: P.Recorder) -> dict:
    if not rec.chunks:
        return {"chunks": 0}
    sizes = [n for _, n in rec.chunks]
    times = [t for t, _ in rec.chunks]
    gaps = [round((b - a) * 1000, 1) for a, b in zip(times, times[1:])]
    return {
        "chunks": len(sizes),
        "first_chunk_ms_after_connect": round((times[0] - rec.t_connect) * 1000, 1),
        "bytes_median": statistics.median(sizes),
        "bytes_min": min(sizes),
        "bytes_max": max(sizes),
        "gap_ms_median": statistics.median(gaps) if gaps else None,
        "gap_ms_p90": sorted(gaps)[int(len(gaps) * 0.9)] if gaps else None,
    }


# --- the run -------------------------------------------------------------------

def main() -> int:
    tmp = os.path.join(OUT, "tones")
    os.makedirs(tmp, exist_ok=True)
    a_wav, b_wav = os.path.join(tmp, "a440.wav"), os.path.join(tmp, "b1000.wav")
    write_wav(a_wav, 440.0, 40)
    write_wav(b_wav, 1000.0, 40)
    mic_raw = tone_samples(700.0, 1.0)  # 700 whole cycles: loops without a click

    log("libpulse", P.s(P.get_library_version()))
    pa = P.Pulse("547 capture probe")
    info = pa.server_info()
    results["server"] = info
    log("server:", json.dumps(info))
    check("server is pipewire-pulse", "PipeWire" in (info.get("server_name") or ""),
          f"server_name={info.get('server_name')!r} server_version={info.get('server_version')!r}")
    results["sinks_before"] = pa.sinks()
    results["sources_before"] = pa.sources()
    log("sinks before:", json.dumps(results["sinks_before"]))
    log("sources before:", json.dumps(results["sources_before"]))

    # Test nodes, made through libpulse itself: an output and a mic.
    out_mod = pa.load_module("module-null-sink",
                             "sink_name=spike_out rate=48000 channels=2 "
                             "sink_properties=device.description=SpikeOut")
    log("null sink module:", out_mod)
    out2_mod = pa.load_module("module-null-sink",
                              "sink_name=spike_out2 rate=48000 channels=2 "
                              "sink_properties=device.description=SpikeHeadset")
    log("second output (a headset) module:", out2_mod)
    fifo = os.path.join(tmp, "mic.fifo")
    os.mkfifo(fifo)
    pipe_mod = pa.load_module("module-pipe-source",
                              f"source_name=spike_pipe file={fifo} format=s16le rate=48000 channels=1 "
                              "source_properties=device.description=SpikePipe")
    log("pipe source module:", pipe_mod)
    procs: list[subprocess.Popen] = []
    writer = (
        "import sys\nd=open(sys.argv[2],'rb').read()\nf=open(sys.argv[1],'wb',buffering=0)\n"
        "while True:\n f.write(d)\n"
    )
    raw = os.path.join(tmp, "mic700.raw")
    with open(raw, "wb") as fh:
        fh.write(mic_raw)
    if pipe_mod != P.PA_INVALID_INDEX:
        procs.append(subprocess.Popen([sys.executable, "-I", "-c", writer, fifo, raw]))
    # The stand-in mic: a real Audio/Source (a remap of a hidden sink's
    # monitor), fed a 700 Hz tone by paplay on that sink.
    feed_mod = pa.load_module("module-null-sink",
                              "sink_name=spike_micfeed rate=48000 channels=1 channel_map=mono "
                              "sink_properties=device.description=SpikeMicFeed")
    mic_mod = pa.load_module("module-remap-source",
                             "master=spike_micfeed.monitor source_name=spike_mic channels=1 channel_map=mono "
                             "source_properties=device.description=SpikeMic")
    log("mic feed sink module:", feed_mod, "| remap source module:", mic_mod)
    mic_wav = os.path.join(tmp, "mic700.wav")
    write_wav(mic_wav, 700.0, 60)
    feeder = subprocess.Popen(["paplay", "--device=spike_micfeed", "--client-name=Mic feed", mic_wav])
    procs.append(feeder)
    log("mic feeder: paplay pid", feeder.pid)
    mic_name = "spike_mic" if mic_mod != P.PA_INVALID_INDEX else "spike_pipe"
    results["mic_route"] = mic_name
    time.sleep(0.5)
    log("set default sink:", pa.set_default_sink("spike_out"))
    log("set default source:", pa.set_default_source(mic_name))
    pa.run_for(1.0)
    info2 = pa.server_info()
    results["server_after_defaults"] = info2
    log("defaults now:", info2.get("default_sink_name"), info2.get("default_source_name"))
    check("default sink is ours", info2.get("default_sink_name") == "spike_out", str(info2.get("default_sink_name")))
    check("default source is ours", info2.get("default_source_name") == mic_name, str(info2.get("default_source_name")))

    pa.subscribe()

    # The two apps.
    def start_a() -> subprocess.Popen:
        return subprocess.Popen(["paplay", "--client-name=Tone A", "--stream-name=A 440 Hz", a_wav])

    pa_a = start_a()
    pw_b = subprocess.Popen(["pw-play", b_wav])
    procs += [pw_b]
    log("players: A paplay pid", pa_a.pid, "| B pw-play pid", pw_b.pid)

    def joined() -> list[dict]:
        """Sink inputs with their client's properties beside them."""
        clients = {c["index"]: c["props"] for c in pa.clients()}
        out = pa.sink_inputs()
        for si in out:
            si["client_props"] = clients.get(si["client"], {})
        return out

    def pid_of(si: dict) -> str | None:
        return si["props"].get("application.process.id") or si["client_props"].get("application.process.id")

    def find(pid: int, timeout: float = 6.0) -> dict | None:
        end = time.monotonic() + timeout
        while time.monotonic() < end:
            for si in joined():
                if pid_of(si) == str(pid):
                    return si
            pa.run_for(0.2)
        return None

    si_a, si_b = find(pa_a.pid), find(pw_b.pid)
    all_si = joined()
    results["sink_inputs"] = all_si
    results["clients"] = pa.clients()
    log("sink inputs:")
    for si in all_si:
        p = si["props"]
        log(f"  #{si['index']} sink={si['sink']} client={si['client']} driver={si['driver']} name={si['name']!r}")
        for k in ("application.name", "application.process.binary", "application.process.id",
                  "media.name", "node.name", "application.id", "client.api", "media.role"):
            log(f"      {k} = {p.get(k)!r}   (client: {si['client_props'].get(k)!r})")
    log("clients:", json.dumps([{k: c[k] for k in ("index", "name", "driver")} for c in results["clients"]]))
    def who(si):
        if si is None:
            return "not found"
        p, c = si["props"], si["client_props"]
        return (f"sink input: name={p.get('application.name')!r} binary={p.get('application.process.binary')!r} "
                f"pid={p.get('application.process.id')!r}; client: name={c.get('application.name')!r} "
                f"binary={c.get('application.process.binary')!r} pid={c.get('application.process.id')!r}")

    check("app A (libpulse) found by pid", si_a is not None, who(si_a))
    check("app B (native PipeWire) found by pid", si_b is not None, who(si_b))
    if si_a is None:
        # match by name as a fallback, to carry on
        si_a = next((x for x in all_si if x["props"].get("application.name") == "Tone A"), None)
    if si_b is None and si_a is not None:
        si_b = next((x for x in all_si if x["index"] != si_a["index"] and x["sink"] != P.PA_INVALID_INDEX), None)
    if si_a is None or si_b is None:
        log("no sink inputs to monitor: stop")
        return 1

    sink = pa.sink_by_name("spike_out")
    mon_name = sink["monitor_source_name"] if sink else None
    log("default sink's monitor:", mon_name)

    # 1. All at once: A's monitor, B's monitor, the default sink's monitor,
    #    the mic by name and the default source.
    recs = {
        "A monitor (DONT_MOVE)": P.Recorder(pa, "rec A", mon_name, monitor_of=si_a["index"], dont_move=True),
        "B monitor (DONT_MOVE)": P.Recorder(pa, "rec B", mon_name, monitor_of=si_b["index"], dont_move=True),
        "default sink monitor": P.Recorder(pa, "rec mon", mon_name, dont_move=True),
        "mic by name": P.Recorder(pa, "rec mic", mic_name, dont_move=True),
        "default source": P.Recorder(pa, "rec default src", None),
        "pipe source by name": P.Recorder(pa, "rec pipe", "spike_pipe", dont_move=True),
        "@DEFAULT_MONITOR@": P.Recorder(pa, "rec @DEFAULT_MONITOR@", "@DEFAULT_MONITOR@"),
    }
    pa.run_for(4.0)
    results["recordings"] = {}
    for label, r in recs.items():
        lv = levels(r.data)
        cs = chunk_stats(r)
        results["recordings"][label] = {"levels": lv, "chunks": cs, "events": r.events, "device": r.device()}
        log(f"{label}: device={r.device()} levels={json.dumps(lv)}")
        log(f"    chunks={json.dumps(cs)}")
        log(f"    events={r.events}")
    for r in recs.values():
        r.close()

    def lv(label: str, k: str) -> float:
        v = results["recordings"][label]["levels"].get(k)
        return v if v is not None else -200.0

    a_iso = lv("A monitor (DONT_MOVE)", "A 440") - lv("A monitor (DONT_MOVE)", "B 1000")
    b_iso = lv("B monitor (DONT_MOVE)", "B 1000") - lv("B monitor (DONT_MOVE)", "A 440")
    results["isolation_db"] = {"A": round(a_iso, 1), "B": round(b_iso, 1)}
    check("A's monitor has A's tone", lv("A monitor (DONT_MOVE)", "A 440") > -30,
          f"440 Hz at {lv('A monitor (DONT_MOVE)', 'A 440')} dBFS, 1000 Hz at {lv('A monitor (DONT_MOVE)', 'B 1000')}; isolation {a_iso:.1f} dB")
    check("B's monitor has B's tone", lv("B monitor (DONT_MOVE)", "B 1000") > -30,
          f"1000 Hz at {lv('B monitor (DONT_MOVE)', 'B 1000')} dBFS, 440 Hz at {lv('B monitor (DONT_MOVE)', 'A 440')}; isolation {b_iso:.1f} dB")
    check("one-app isolation at least 60 dB", min(a_iso, b_iso) >= 60, f"A {a_iso:.1f} dB, B {b_iso:.1f} dB")
    check("default sink monitor has both tones",
          lv("default sink monitor", "A 440") > -30 and lv("default sink monitor", "B 1000") > -30,
          f"440 at {lv('default sink monitor', 'A 440')}, 1000 at {lv('default sink monitor', 'B 1000')}, 700 at {lv('default sink monitor', 'mic 700')}")
    check("@DEFAULT_MONITOR@ is the output, not the mic",
          lv("@DEFAULT_MONITOR@", "A 440") > -30 and lv("@DEFAULT_MONITOR@", "mic 700") < -60,
          f"device={results['recordings']['@DEFAULT_MONITOR@']['device']} 440 at {lv('@DEFAULT_MONITOR@', 'A 440')}, "
          f"700 at {lv('@DEFAULT_MONITOR@', 'mic 700')}")
    log("pipe source (information only):", json.dumps(results["recordings"]["pipe source by name"]["levels"]))
    for label in ("mic by name", "default source"):
        check(f"{label}: the mic's tone only",
              lv(label, "mic 700") > -30 and lv(label, "A 440") < -60 and lv(label, "B 1000") < -60,
              f"700 at {lv(label, 'mic 700')}, 440 at {lv(label, 'A 440')}, 1000 at {lv(label, 'B 1000')}")

    # 2. A's monitor when A stops: with DONT_MOVE, then without.
    results["when_the_app_stops"] = {}
    for dont_move in (True, False):
        key = "DONT_MOVE" if dont_move else "no DONT_MOVE"
        if pa_a.poll() is not None:
            pa_a = start_a()
            si_a = find(pa_a.pid)
            if si_a is None:
                check(f"restart A for {key}", False, "no sink input")
                continue
        rec = P.Recorder(pa, f"rec A {key}", mon_name, monitor_of=si_a["index"], dont_move=dont_move)
        pa.run_for(2.0)
        mark = len(rec.data)
        t_kill = pa.now()
        rec.events.append((round(t_kill, 3), f"--- kill A (pid {pa_a.pid}, sink input #{si_a['index']})"))
        pa_a.terminate()
        pa_a.wait(5)
        pa.run_for(3.0)
        after = len(rec.data) - mark
        last = rec.chunks[-1][0] if rec.chunks else None
        res = {
            "state_after": rec.state(),
            "device_after": rec.device(),
            "bytes_after_kill": after,
            "seconds_of_audio_after_kill": round(after / 2 / RATE, 2),
            "last_chunk_s_after_kill": round(last - t_kill, 2) if last else None,
            "events": rec.events,
            "windows": windows(rec.data, mark),
        }
        results["when_the_app_stops"][key] = res
        log(f"A's monitor, {key}: state after={res['state_after']} device after={res['device_after']} "
            f"audio after kill={res['seconds_of_audio_after_kill']} s, last chunk {res['last_chunk_s_after_kill']} s after")
        for e in rec.events:
            log("    ", e)
        for w in res["windows"]:
            log("    ", json.dumps(w))
        rec.close()
    # 3. The app's stream moved to another output (a headset plugged in),
    #    while its monitor (DONT_MOVE) records; then the default output
    #    changed: is it announced?
    if pa_a.poll() is not None:
        pa_a = start_a()
        si_a = find(pa_a.pid)
    if si_a is not None:
        rec = P.Recorder(pa, "rec A follow", mon_name, monitor_of=si_a["index"], dont_move=True)
        pa.run_for(2.0)
        mark = len(rec.data)
        rec.events.append((round(pa.now(), 3), f"--- move sink input #{si_a['index']} to spike_out2"))
        moved = pa.move_sink_input(si_a["index"], "spike_out2")
        pa.run_for(3.0)
        after = [w for w in windows(rec.data, mark) if w["t"] >= 0.5]
        ok = bool(after) and all(w["A 440"] > -30 for w in after)
        res = {"move_ok": moved, "state_after": rec.state(), "device_after": rec.device(),
               "seconds_after_move": round((len(rec.data) - mark) / 2 / RATE, 2),
               "events": rec.events, "windows": windows(rec.data, mark)}
        results["app_moved_to_another_output"] = res
        check("A's monitor follows A to another output", ok and rec.state() == "READY",
              f"move ok={moved}, state after={res['state_after']}, device after={res['device_after']}, "
              f"audio after={res['seconds_after_move']} s, 440 Hz after: {[w['A 440'] for w in after]}")
        for e in rec.events:
            log("    ", e)
        rec.close()
        n0 = len(pa.events)
        log("set default sink to spike_out2:", pa.set_default_sink("spike_out2"))
        pa.run_for(1.0)
        server_events = [e for e in pa.events[n0:] if e[1].startswith("server")]
        info3 = pa.server_info()
        check("a default-output change is announced", bool(server_events) and info3.get("default_sink_name") == "spike_out2",
              f"server events {server_events}; default sink now {info3.get('default_sink_name')}")

    results["subscription_events"] = pa.events
    log("subscription events:", pa.events)

    # 3. The list after A has gone: only B left?
    results["sink_inputs_end"] = [
        {"index": x["index"], "application.name": x["props"].get("application.name"),
         "binary": x["props"].get("application.process.binary")} for x in pa.sink_inputs()]
    log("sink inputs at the end:", json.dumps(results["sink_inputs_end"]))

    for p in procs + [pa_a]:
        if p.poll() is None:
            p.terminate()
    results["failures"] = failures
    with open(os.path.join(OUT, "results.json"), "w", encoding="utf-8") as fh:
        json.dump(results, fh, indent=1)
    log("failures:", failures)
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
