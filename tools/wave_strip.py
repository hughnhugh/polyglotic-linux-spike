"""A filmstrip of Steady's wave (polyglotic-hq 1070) in a real caption window.

    python -m tools.wave_strip OUT.png [--cards|--zones] [--reduced] [--print]

A caption window in Steady, through the playout as the app has it
(`CaptionWindows`), plays a short made-up English line whose words carry
the server's word times, on a patched clock. The window is photographed
with the UI lab's `photograph` every few frames while one word lights, and
the shots are stacked into one picture, oldest on top, each with its time
after the word was shown. `--reduced` plays it with the OS's reduced motion
on (words whole); `--print` also writes the picture to stdout as base64,
for a run on GitHub's machines whose files don't come back.

Offscreen Qt: run it on GitHub's machines (`scripts/remote_test.py --each`),
never beside live. The text is made up (RULES #26, #30).
"""

import argparse
import base64
import os
import sys
from pathlib import Path
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
_WINDOWS_FONTS = Path("C:/Windows/Fonts")
if _WINDOWS_FONTS.is_dir():
    os.environ.setdefault("QT_QPA_FONTDIR", str(_WINDOWS_FONTS))

from PySide6.QtCore import QRect, Qt
from PySide6.QtGui import QColor, QFont, QImage, QPainter

from polyglotic_desktop.core.listening.captions import (
    CaptionKind,
    CaptionUpdate,
    Clause,
    Language,
    SpeechTimes,
    WordTime,
)
from polyglotic_desktop.core.listening.playout import Ahead, PlayoutRules
from polyglotic_desktop.core.listening.sources import SourceId
from polyglotic_desktop.core.listening.timing import CaptionId, CaptionMode
from polyglotic_desktop.ui_next import caption_window
from polyglotic_desktop.ui_next.caption_windows import CaptionWindows
from polyglotic_desktop.ui_next.views.placement import Rect
from tools.scene_replay.drive import app
from tools.ui_lab.lab import photograph

LINE = "the train leaves at seven so we should go"
STEP, SAID = 0.42, 0.38
"""Seconds a word, and of them said: slow and clear, to see each letter."""
DELAY = 1.75
FRAME = 1 / 60
EVERY = 4
"""Frames between shots."""
SHOTS = 10
CROP = 130
"""Px of each shot kept, from its foot: the newest card or the live zone."""
CHUNK = 15000
"""Base64 characters printed a run: GitHub's runner keeps an item's last
20,000 characters of output."""
APP = SourceId("app")
EN = Language("en")


class _Clock:
    def __init__(self) -> None:
        self.now = 0.0

    def __call__(self) -> float:
        return self.now


def _update(kind: CaptionKind, until: float) -> CaptionUpdate:
    words = LINE.split()
    times, text, at = [], "", 0
    for n, word in enumerate(words):
        said = n * STEP
        if said + SAID > until:
            break
        if text:
            text += " "
            at += 1
        times.append(WordTime((at, at + len(word)), said, said + SAID))
        text += word
        at += len(word)
    clause = Clause(
        text, {EN: "..."} if kind is CaptionKind.FINISHED else {}, words=tuple(times)
    )
    end = min(until, len(words) * STEP)
    return CaptionUpdate(
        CaptionId("line"), APP, kind, (clause,), EN, (EN,),
        times=SpeechTimes(0.0, end, end, end + 0.3),
        established=0,
    )  # fmt: skip


def strip(cards: bool, reduced: bool) -> QImage:
    """The filmstrip, drawn now."""
    app()
    clock = _Clock()
    windows = CaptionWindows(None, SourceId("mic"), lambda: [Rect(0, 0, 1920, 1040)])
    try:
        windows.set_cards(cards)
        windows.word_clock = clock
        windows.set_captioned([("app", APP)])
        windows.set_timing(CaptionMode.STEADY)
        windows.set_playout(PlayoutRules(delay=DELAY, ahead=Ahead.WAITING))
        window = windows.windows["app"]
        window.clock = clock
        window.resize(760, 260)
        window.show()
        whole = len(LINE.split()) * STEP
        feeds = [(t + 0.3, _update(CaptionKind.LIVE, t)) for t in (1.0, 2.0, 3.0)]
        feeds.append((whole + 0.5, _update(CaptionKind.FINISHED, whole)))
        shots: list[tuple[float, QImage]] = []
        start = DELAY + 2 * STEP  # the third word ("leaves") is shown
        with patch.object(caption_window, "reduced_motion", return_value=reduced):
            for n in range(round((start + SHOTS * EVERY * FRAME) / FRAME) + 1):
                clock.now = n * FRAME
                while feeds and feeds[0][0] <= clock.now:
                    windows.apply(feeds.pop(0)[1])
                while (due := windows.playout.due()) is not None and due <= clock.now:
                    windows.release_words()
                    if windows.playout.due() == due:
                        break
                window._tick()
                app().processEvents()
                taking = clock.now >= start and len(shots) < SHOTS
                if taking and (not shots or n % EVERY == 0):
                    shot = photograph(window, True)
                    foot = shot.copy(0, shot.height() - CROP, shot.width(), CROP)
                    shots.append((clock.now - start, foot))
        return _stacked(shots)
    finally:
        windows.close()


def _stacked(shots: list[tuple[float, QImage]]) -> QImage:
    margin, rule = 90, 2
    width = margin + max(shot.width() for _, shot in shots)
    height = sum(shot.height() for _, shot in shots) + rule * (len(shots) - 1)
    out = QImage(width, height, QImage.Format.Format_RGB888)
    out.fill(QColor("#20242b"))
    painter = QPainter(out)
    font = QFont()
    font.setPixelSize(14)
    painter.setFont(font)
    painter.setPen(QColor("#e6e9ef"))
    y = 0
    for after, shot in shots:
        painter.drawImage(margin, y, shot)
        painter.drawText(
            QRect(0, y, margin, shot.height()),
            int(Qt.AlignmentFlag.AlignCenter),
            f"+{after:.2f} s",
        )
        y += shot.height() + rule
    painter.end()
    return out


def main() -> int:
    parser = argparse.ArgumentParser(prog="python -m tools.wave_strip")
    parser.add_argument("out")
    parser.add_argument("--cards", action="store_true", help="cards (the default)")
    parser.add_argument("--zones", action="store_true", help="two zones, not cards")
    parser.add_argument("--reduced", action="store_true", help="reduced motion on")
    parser.add_argument("--print", action="store_true", help="base64 to stdout too")
    parser.add_argument(
        "--chunk", type=int, default=0, help="with --print: which part (CHUNK chars)"
    )
    args = parser.parse_args()
    picture = strip(not args.zones, args.reduced)
    picture.save(args.out)
    if args.print:
        small = Path(args.out).with_suffix(".jpg")
        smaller = picture.scaledToWidth(
            picture.width() * 3 // 5, Qt.TransformationMode.SmoothTransformation
        )
        smaller.save(str(small), quality=75)  # the format from ".jpg"
        data = base64.b64encode(small.read_bytes()).decode()
        parts = (len(data) + CHUNK - 1) // CHUNK
        print(f"WAVE-STRIP part {args.chunk} of {parts}, {len(data)} chars")
        part = data[args.chunk * CHUNK : (args.chunk + 1) * CHUNK]
        for at in range(0, len(part), 120):
            print("WS " + part[at : at + 120])
    print(f"wrote {args.out}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
