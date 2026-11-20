"""547's window scenarios, run inside a headless GNOME (mutter) or KDE (KWin) session.

    python harness.py gnome|kde OUT_DIR

For each scenario: a caption stand-in (caption.py, always X11 through
XWayland) and a full-screen stand-in (fullscreen.py, X11 or native
Wayland) are started; the full-screen window is clicked (focused, as a
player clicking into a game); then the compositor's own picture of the
screen says whether the caption is on top (its solid half green) and
translucent (its half-green half blended); the pointer is moved over the
caption and clicked through the compositor's own input, and the two
windows' logs say who saw the pointer and who got the click.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import threading
import time
from pathlib import Path

if os.environ.get("GITHUB_ACTIONS") != "true" or not sys.platform.startswith("linux"):
    sys.exit("547's probes run only on GitHub's Linux runners")

HERE = Path(__file__).resolve().parent
W, H = 1280, 720
CAPTION = (440, 480, 400, 160)  # x, y, w, h
SOLID = (810, 500)  # the caption's solid half, away from its text
HALF = (470, 500)  # the caption's 50 % half
OUTSIDE = (100, 100)  # the full-screen window only
OVER = [(600, 520), (700, 540)]  # pointer stops over the caption
CLICK = (810, 600)


class Proc:
    def __init__(self, name: str, args: list[str], env: dict[str, str], out: Path) -> None:
        self.name = name
        self.events: list[dict] = []
        self.err = open(out / f"{name}.stderr.txt", "w")
        self.p = subprocess.Popen([sys.executable, *args], stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                  stderr=self.err, env=env, text=True, bufsize=1)
        threading.Thread(target=self._read, daemon=True).start()

    def _read(self) -> None:
        assert self.p.stdout
        for line in self.p.stdout:
            try:
                self.events.append(json.loads(line))
            except ValueError:
                self.events.append({"ev": "raw", "line": line.rstrip()})

    def send(self, cmd: str) -> None:
        if self.p.poll() is None and self.p.stdin:
            self.p.stdin.write(cmd + "\n")
            self.p.stdin.flush()

    def wait_for(self, ev: str, timeout: float = 15) -> dict | None:
        end = time.monotonic() + timeout
        while time.monotonic() < end:
            for e in self.events:
                if e.get("ev") == ev:
                    return e
            if self.p.poll() is not None:
                return None
            time.sleep(0.05)
        return None

    def since(self, mark: int, ev: str) -> list[dict]:
        return [e for e in self.events[mark:] if e.get("ev") == ev]

    def stop(self) -> None:
        self.send("quit")
        try:
            self.p.wait(timeout=4)
        except subprocess.TimeoutExpired:
            self.p.kill()
            self.p.wait(timeout=4)
        self.err.close()


def pixels(path: Path) -> dict:
    from PySide6.QtGui import QImage

    img = QImage(str(path))
    sx, sy = img.width() / W, img.height() / H

    def px(p: tuple[int, int]) -> list[int]:
        c = img.pixelColor(int(p[0] * sx), int(p[1] * sy))
        return [c.red(), c.green(), c.blue()]

    solid, half, outside = px(SOLID), px(HALF), px(OUTSIDE)
    on_top = solid[1] > 200 and solid[0] < 80 and solid[2] < 80
    translucent = on_top and 80 < half[1] < 200 and max(half[0], half[2]) > 80
    return {"size": [img.width(), img.height()], "solid": solid, "half": half, "outside": outside,
            "caption_on_top": on_top, "translucent": translucent}


def main() -> None:
    de, out = sys.argv[1], Path(sys.argv[2])
    out.mkdir(parents=True, exist_ok=True)
    if de == "gnome":
        from mutter_session import Mutter

        session = Mutter()
        session.start_pointer()
        stacking = None
    else:
        from kwin_session import KWin

        session = KWin(Path(os.environ["KWIN_LOG"]), out)
        stacking = session.stacking
    base = dict(os.environ, QT_WAYLAND_DISABLE_WINDOWDECORATION="1")
    plat = {"x11": dict(base, QT_QPA_PLATFORM="xcb"), "wayland": dict(base, QT_QPA_PLATFORM="wayland")}
    geo = ",".join(str(v) for v in CAPTION)
    # name, the full-screen window's platform, caption options, a command sent to it mid-way, who starts first
    scenarios = [
        ("x11fs-above-locked", "x11", [], None, "caption"),
        ("x11fs-bypass-locked", "x11", ["--bypass"], None, "caption"),
        ("wlfs-above-locked", "wayland", [], None, "caption"),
        ("wlfs-bypass-locked", "wayland", ["--bypass"], None, "caption"),
        ("x11fs-above-then-bypass", "x11", [], "bypass", "caption"),
        ("wlfs-above-then-bypass", "wayland", [], "bypass", "caption"),
        ("x11fs-first-above-locked", "x11", [], None, "fullscreen"),
        ("wlfs-first-above-locked", "wayland", [], None, "fullscreen"),
        ("x11fs-above-unlocked-then-lock", "x11", ["--unlocked"], "lock", "caption"),
        ("wlfs-above-unlocked-then-lock", "wayland", ["--unlocked"], "lock", "caption"),
        ("wlfs-bypass-unlocked-then-lock", "wayland", ["--bypass", "--unlocked"], "lock", "caption"),
    ]
    results = []
    for name, fs_platform, opts, mid, first in scenarios:
        print(f"--- {name}", flush=True)
        cap_args = [str(HERE / "caption.py"), "--geometry", geo]
        cap_args += [o for o in opts if o != "--unlocked"]
        if "--unlocked" not in opts:
            cap_args.append("--through")
        r: dict = {"scenario": name, "fullscreen": fs_platform, "caption": opts or ["--above"], "mid": mid, "first": first}
        procs: list[Proc] = []
        try:
            def start_cap() -> Proc:
                c = Proc(f"{name}.caption", cap_args, plat["x11"], out)
                procs.append(c)
                r["caption_shown"] = c.wait_for("shown")
                return c

            def start_fs() -> Proc:
                f = Proc(f"{name}.fullscreen", [str(HERE / "fullscreen.py")], plat[fs_platform], out)
                procs.append(f)
                r["fullscreen_shown"] = f.wait_for("shown")
                return f

            if first == "caption":
                cap = start_cap(); time.sleep(1.0); fs = start_fs()
            else:
                fs = start_fs(); time.sleep(1.0); cap = start_cap()
            time.sleep(1.5)
            session.click(*OUTSIDE)  # focus the full-screen window, as a player clicking into the game
            time.sleep(0.8)
            r["fullscreen_active"] = [e.get("value") for e in fs.events if e.get("ev") == "active"]
            shot = out / f"{name}-1.png"
            session.picture(shot)
            r["picture_1"] = pixels(shot)
            if stacking:
                r["stack_1"] = stacking(f"{name}-1")
            if mid in ("bypass",):
                cap.send(mid)
                time.sleep(1.2)
                shot = out / f"{name}-2-after-{mid}.png"
                session.picture(shot)
                r["picture_2_after_" + mid] = pixels(shot)
                if stacking:
                    r["stack_2"] = stacking(f"{name}-2")
            cap.send("raise")
            time.sleep(0.8)
            shot = out / f"{name}-3-after-raise.png"
            session.picture(shot)
            r["picture_3_after_raise"] = pixels(shot)

            def pointer_round(tag: str) -> None:
                mc, mf = len(cap.events), len(fs.events)
                for x, y in OVER:
                    session.move(x, y)
                    time.sleep(0.4)
                session.click(*CLICK)
                time.sleep(0.6)
                cursor = cap.since(mc, "cursor")
                r[f"pointer_{tag}"] = {
                    "caption_cursor_readings": [[e["x"], e["y"]] for e in cursor],
                    "caption_saw_pointer_at_stops": all(any(e["x"] == x and e["y"] == y for e in cursor) for x, y in OVER),
                    "caption_enter": len(cap.since(mc, "enter")),
                    "caption_moves": len(cap.since(mc, "move")),
                    "caption_presses": [[e["x"], e["y"]] for e in cap.since(mc, "press")],
                    "fullscreen_presses": [[e["x"], e["y"]] for e in fs.since(mf, "press")],
                    "fullscreen_moves": len(fs.since(mf, "move")),
                }

            pointer_round("1")
            if mid == "lock":
                cap.send("lock")
                time.sleep(1.2)
                shot = out / f"{name}-4-after-lock.png"
                session.picture(shot)
                r["picture_4_after_lock"] = pixels(shot)
                pointer_round("2_after_lock")
            if stacking:
                r["stack_end"] = stacking(f"{name}-end")
        except Exception as exc:  # noqa: BLE001 - a scenario's failure is a result too
            r["error"] = repr(exc)
        finally:
            for p in procs:
                p.stop()
            r["caption_log_tail"] = procs[0].events[-6:] if procs else []
            time.sleep(0.5)
        print(json.dumps(r), flush=True)
        results.append(r)
    (out / "results.json").write_text(json.dumps(results, indent=1))
    summary = ["| scenario | on top (1st) | after bypass | after raise | translucent | caption saw pointer | click went to |", "|---|---|---|---|---|---|---|"]
    for r in results:
        if "error" in r and "picture_1" not in r:
            summary.append(f"| {r['scenario']} | error: {r['error'][:80]} | | | | | |")
            continue
        p1 = r.get("picture_1", {})
        pb = r.get("picture_2_after_bypass", {})
        pr = r.get("picture_3_after_raise", {})
        pt = r.get("pointer_1", {})
        to = "caption" if pt.get("caption_presses") else ("full-screen" if pt.get("fullscreen_presses") else "nobody")
        rounds = f"{pt.get('caption_saw_pointer_at_stops')}"
        if "pointer_2_after_lock" in r:
            p2 = r["pointer_2_after_lock"]
            to2 = "caption" if p2.get("caption_presses") else ("full-screen" if p2.get("fullscreen_presses") else "nobody")
            to += f"; locked: {to2}"
            rounds += f"; locked: {p2.get('caption_saw_pointer_at_stops')}"
        summary.append(f"| {r['scenario']} | {p1.get('caption_on_top')} | {pb.get('caption_on_top', '-')} | "
                       f"{pr.get('caption_on_top')} | {p1.get('translucent')} | {rounds} | {to} |")
    text = f"### {de}\n\n" + "\n".join(summary) + "\n"
    (out / "summary.md").write_text(text)
    print(text)
    if os.environ.get("GITHUB_STEP_SUMMARY"):
        with open(os.environ["GITHUB_STEP_SUMMARY"], "a") as f:
            f.write(text + "\n")


if __name__ == "__main__":
    main()
