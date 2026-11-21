"""591's probe: speech-dispatcher on GitHub's Ubuntu runner, talked to over
its socket (SSIP) as the app would - which socket, autospawn, the output
modules, the voices' listing, the events, and the sound it plays measured
at the default output's monitor. Standard library only; prints a report."""

import json
import math
import os
import shutil
import socket
import subprocess
import sys
import time
from array import array
from pathlib import Path

OUT = Path(sys.argv[1])
OUT.mkdir(parents=True, exist_ok=True)
report: dict = {}


def socket_path() -> str:
    address = os.environ.get("SPEECHD_ADDRESS", "")
    if address.startswith("unix_socket:"):
        return address.split(":", 1)[1]
    runtime = os.environ.get("XDG_RUNTIME_DIR", "/tmp")
    return f"{runtime}/speech-dispatcher/speechd.sock"


class Ssip:
    def __init__(self, path: str) -> None:
        self.s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        self.s.settimeout(10)
        self.s.connect(path)
        self.buf = b""
        self.events: list[tuple[float, list[str]]] = []

    def line(self) -> str:
        while b"\r\n" not in self.buf:
            chunk = self.s.recv(65536)
            if not chunk:
                raise OSError("closed")
            self.buf += chunk
        line, self.buf = self.buf.split(b"\r\n", 1)
        return line.decode("utf-8", "replace")

    def reply(self) -> list[str]:
        lines = []
        while True:
            line = self.line()
            lines.append(line)
            if len(line) >= 4 and line[3] == " ":
                if line.startswith("7"):  # an event: kept, not the reply
                    self.events.append((time.perf_counter(), lines))
                    lines = []
                    continue
                return lines

    def cmd(self, text: str) -> list[str]:
        self.s.sendall(text.encode() + b"\r\n")
        return self.reply()

    def speak(self, text: str) -> list[str]:
        first = self.cmd("SPEAK")
        if not first[-1].startswith("230"):
            return first
        body = "\r\n".join(".." + l if l.startswith(".") else l for l in text.split("\n"))
        self.s.sendall(body.encode() + b"\r\n.\r\n")
        return self.reply()

    def wait_events(self, seconds: float) -> None:
        end = time.perf_counter() + seconds
        self.s.settimeout(0.05)
        try:
            while time.perf_counter() < end:
                try:
                    lines = []
                    while True:
                        line = self.line()
                        lines.append(line)
                        if len(line) >= 4 and line[3] == " ":
                            break
                    self.events.append((time.perf_counter(), lines))
                except (TimeoutError, socket.timeout):
                    continue
        finally:
            self.s.settimeout(10)


def record(seconds: float, name: str) -> subprocess.Popen:
    return subprocess.Popen(
        ["parecord", "--device=session_speakers.monitor", "--raw", "--format=s16le",
         "--rate=16000", "--channels=1", str(OUT / name)],
    )


def levels(name: str, t0: float) -> dict:
    data = (OUT / name).read_bytes()
    samples = array("h")
    samples.frombytes(data[: len(data) // 2 * 2])
    step = 800  # 50 ms
    rows = []
    for i in range(0, len(samples), step):
        part = samples[i : i + step]
        if not part:
            break
        rms = math.sqrt(sum(x * x for x in part) / len(part)) or 1e-9
        rows.append(round(20 * math.log10(rms / 32768), 1))
    loud = [i for i, db in enumerate(rows) if db > -50]
    return {
        "seconds": round(len(samples) / 16000, 2),
        "peak_dbfs": max(rows) if rows else None,
        "loud_from_s": loud[0] * 0.05 if loud else None,
        "loud_to_s": (loud[-1] + 1) * 0.05 if loud else None,
        "loud_windows": len(loud),
        "per_50ms": rows,
    }


report["programs"] = {p: shutil.which(p) for p in ("speech-dispatcher", "spd-say", "espeak-ng", "parecord")}
units = subprocess.run("ls /usr/lib/systemd/user /etc/systemd/user 2>/dev/null | grep -i speech",
                       shell=True, capture_output=True, text=True)
report["systemd_user_units"] = units.stdout.split()
report["modules_dir"] = sorted(os.listdir("/usr/lib/speech-dispatcher-modules")) if os.path.isdir("/usr/lib/speech-dispatcher-modules") else None
path = socket_path()
report["socket"] = path
report["socket_before"] = os.path.exists(path)
spawned = None
if not os.path.exists(path):
    t = time.perf_counter()
    done = subprocess.run(
        ["speech-dispatcher", "--spawn", "--communication-method", "unix_socket",
         "--socket-path", path],
        capture_output=True, text=True, timeout=30,
    )
    for _ in range(100):
        if os.path.exists(path):
            break
        time.sleep(0.05)
    spawned = {"code": done.returncode, "out": (done.stdout + done.stderr)[-2000:],
               "seconds": round(time.perf_counter() - t, 2), "socket_after": os.path.exists(path)}
report["spawn"] = spawned

c = Ssip(path)
report["client_name"] = c.cmd("SET self CLIENT_NAME user:polyglotic:probe")
modules = c.cmd("LIST OUTPUT_MODULES")
report["modules"] = modules
report["current_module"] = c.cmd("GET OUTPUT_MODULE")
voices: dict = {}
for line in modules[:-1]:
    module = line[4:]
    set_ = c.cmd(f"SET self OUTPUT_MODULE {module}")
    listed = c.cmd("LIST SYNTHESIS_VOICES")
    rows = [l[4:].split("\t") for l in listed[:-1]]
    langs = sorted({r[1] for r in rows if len(r) > 1})
    voices[module] = {
        "set": set_,
        "end": listed[-1],
        "count": len(rows),
        "with_plus": sum(1 for r in rows if "+" in r[0]),
        "first": rows[:15],
        "languages": langs,
        "for": {
            want: [r for r in rows if len(r) > 1 and r[1].lower().startswith(want)][:6]
            for want in ("en", "zh", "cmn", "yue", "ja", "ko", "fr", "es", "de", "vi", "th", "ru")
        },
    }
report["voices"] = voices
(OUT / "voices-full.txt").write_text(
    "\n".join(f"{m}: {r}" for m, v in voices.items() for r in v["first"]), encoding="utf-8"
)
report["filtered_list"] = c.cmd("LIST SYNTHESIS_VOICES en")
report["notification"] = c.cmd("SET self NOTIFICATION all on")
report["module_back"] = c.cmd("SET self OUTPUT_MODULE espeak-ng")
report["language"] = c.cmd("SET self LANGUAGE en")
report["rate"] = c.cmd("SET self RATE 0")
report["history"] = c.cmd("SET self PRIORITY text")

# 1. a word, heard to its end
rec = record(6, "word.raw")
time.sleep(1.0)
t0 = time.perf_counter()
report["speak"] = c.speak("Hello, this is a test of the system voice.")
said_at = time.perf_counter()
c.wait_events(4.0)
rec.terminate(); rec.wait()
report["word_events"] = [(round(t - t0, 3), lines) for t, lines in c.events]
report["word_levels"] = levels("word.raw", t0)
report["word_said_after_record_s"] = 1.0
c.events.clear()

# 2. a long text, cancelled after 0.6 s
rec = record(6, "cancel.raw")
time.sleep(1.0)
t0 = time.perf_counter()
c.speak("This is a much longer sentence that should be stopped before it ends, "
        "because the learner pressed stop on the card while it was still speaking.")
c.wait_events(0.6)
report["cancel"] = c.cmd("CANCEL self")
c.wait_events(2.5)
rec.terminate(); rec.wait()
report["cancel_events"] = [(round(t - t0, 3), lines) for t, lines in c.events]
report["cancel_levels"] = levels("cancel.raw", t0)
c.events.clear()

# 3. a Chinese word and a voice by name
report["zh_language"] = c.cmd("SET self LANGUAGE zh")
rec = record(4, "zh.raw")
time.sleep(0.5)
t0 = time.perf_counter()
c.speak("你好")
c.wait_events(3.0)
rec.terminate(); rec.wait()
report["zh_events"] = [(round(t - t0, 3), lines) for t, lines in c.events]
report["zh_levels"] = {k: v for k, v in levels("zh.raw", t0).items() if k != "per_50ms"}
c.events.clear()
fr = voices.get("espeak-ng", {}).get("for", {}).get("fr", [])
if fr:
    report["voice_by_name"] = c.cmd(f"SET self SYNTHESIS_VOICE {fr[0][0]}")
    t0 = time.perf_counter()
    c.speak("Bonjour")
    c.wait_events(2.0)
    report["fr_events"] = [(round(t - t0, 3), lines) for t, lines in c.events]
c.events.clear()
report["quit"] = c.cmd("QUIT")

# 4. pulse's view of what played: the streams' properties
report["streams_note"] = subprocess.run(
    "pactl list clients | grep -E 'application.name|application.process.binary' | sort | uniq -c",
    shell=True, capture_output=True, text=True).stdout
(OUT / "report.json").write_text(json.dumps(report, indent=1, ensure_ascii=False), encoding="utf-8")
short = {k: v for k, v in report.items() if k not in ("voices",)}
for key in ("word_levels", "cancel_levels"):
    short[key] = {k: v for k, v in report[key].items() if k != "per_50ms"}
print(json.dumps(short, indent=1, ensure_ascii=False)[:12000])
print(json.dumps({m: {k: v[k] for k in ("count", "with_plus", "first", "for")} for m, v in voices.items()},
                 ensure_ascii=False)[:8000])
