"""Made-up two-source feed-to-surface trace used by project 1025's tests."""

from __future__ import annotations

import json
import os
from collections.abc import Iterable
from typing import Any, cast

from PySide6.QtWidgets import QApplication
from tests.ui.fakes import FakeAppList, MemorySettingsStore, chinese_tools

from polyglotic_desktop.core.listening.captions import CaptionKind, CaptionUpdate
from polyglotic_desktop.core.listening.sources import MIC, SourceId
from polyglotic_desktop.main import QtListener, wire_caption_windows, wire_transcripts
from polyglotic_desktop.ui.app import DesktopApp
from polyglotic_desktop.ui.recorded_captions import clause, finished, live
from polyglotic_desktop.ui_next.caption_windows import CaptionWindows
from polyglotic_desktop.ui_next.transcripts import Transcripts
from polyglotic_desktop.ui_next.views.placement import Rect

SPEAKER = SourceId("made-up-speaker")
PLAYER = SourceId("made-up-player")
SOURCES = (("Conversation", SPEAKER), ("Video Player", PLAYER))


def overlapping_updates() -> dict[SourceId, tuple[CaptionUpdate, ...]]:
    """Two fictional sources whose live speech overlaps before either finishes."""
    return {
        SPEAKER: (
            live("speaker-1", clause("我的电脑", "my computer"), source=SPEAKER),
            finished(
                "speaker-1",
                clause("我的电脑又卡了。", "My computer froze again."),
                source=SPEAKER,
            ),
        ),
        PLAYER: (
            live("player-1", clause("打游戏", "play games"), source=PLAYER),
            finished("player-1", clause("打游戏。", "Play games."), source=PLAYER),
        ),
    }


def schedule(first: SourceId = SPEAKER) -> list[CaptionUpdate]:
    other = PLAYER if first == SPEAKER else SPEAKER
    updates = overlapping_updates()
    return [updates[first][0], updates[other][0], updates[first][1], updates[other][1]]


def _lines(lines: Iterable[Any]) -> list[dict[str, Any]]:
    return [
        {
            "id": str(line.caption_id),
            "kind": "live" if line.live else "finished",
            "rows": [
                {
                    "kind": row.kind.value,
                    "language": row.language,
                    "text": row.text,
                }
                for row in line.rows
            ],
        }
        for line in lines
    ]


def trace(updates: list[CaptionUpdate], mutation: str = "") -> list[dict[str, Any]]:
    """Run session-listener updates through the real feed and UI wiring."""
    app = QApplication.instance() or QApplication([])
    tools = chinese_tools()
    store = MemorySettingsStore(
        {"apps": [name for name, _ in SOURCES], "targets": ["en"]}
    )
    desktop = DesktopApp(store, tools, FakeAppList())
    listener = QtListener(desktop, None)
    windows = CaptionWindows(store, MIC, lambda: [Rect(0, 0, 1920, 1040)])
    transcripts = Transcripts(windows, store, areas=lambda: [Rect(0, 0, 1920, 1040)])
    events: list[dict[str, Any]] = []

    wire_caption_windows(windows, desktop, lambda: None)
    wire_transcripts(transcripts, desktop)
    windows.set_captioned(list(SOURCES))
    windows.windows["Video Player"].set_video(True)

    vocabulary = tools.vocabulary
    counted = vocabulary.caption_finished

    def learning(
        caption_id: Any, words: list[Any], by_you: bool, source: Any, forms: list[str]
    ) -> None:
        events.append(
            {
                "event": "learning.delivery",
                "source": str(source),
                "caption": str(caption_id),
                # caption_finished is Learning's line-delivery boundary. Record
                # the delivered identity rather than synthesising a count.
                "lines_heard": [str(caption_id)],
                "words_met": [
                    [word.start, word.end, form]
                    for word, form in zip(words, forms, strict=True)
                ],
            }
        )
        counted(caption_id, words, by_you, source, forms)

    cast(Any, vocabulary).caption_finished = learning

    if mutation == "repeated-learning":
        delivered = vocabulary.caption_finished

        def repeat_learning(*args: Any, **kwargs: Any) -> None:
            delivered(*args, **kwargs)
            if str(args[3]) == str(SPEAKER):
                delivered(*args, **kwargs)

        cast(Any, vocabulary).caption_finished = repeat_learning

    if mutation == "shifted-span":
        from polyglotic_desktop.ui import captions

        words_said = captions._words_said

        def shifted_words(*args: Any, **kwargs: Any) -> tuple[list[Any], list[str]]:
            words, forms = words_said(*args, **kwargs)
            shifted = [replace(word, start=word.start + 1) for word in words]
            return shifted, forms

        from dataclasses import replace

        captions._words_said = shifted_words

    if mutation == "dropped-finish":
        delivered_to_feed = desktop.feed.receive

        def drop_finish(update: CaptionUpdate) -> None:
            if not (
                update.source_id == SPEAKER and update.kind is CaptionKind.FINISHED
            ):
                delivered_to_feed(update)

        cast(Any, desktop.feed).receive = drop_finish

    def arrived(update: CaptionUpdate) -> None:
        events.append(
            {
                "event": "listener.update",
                "source": str(update.source_id),
                "caption": str(update.caption_id),
                "kind": update.kind.value,
                "original": "".join(part.original for part in update.clauses),
            }
        )

    def surfaces(update: CaptionUpdate) -> None:
        own = next(name for name, source in SOURCES if source == update.source_id)
        joined = windows.joined_window
        events.append(
            {
                "event": "surfaces.hold",
                "source": str(update.source_id),
                "caption_window": _lines(windows.windows[own].view.lines),
                "transcript": _lines(transcripts.transcripts[own].lines),
                "joined_window": {
                    column.key: _lines(column.view.lines) for column in joined.columns
                }
                if joined is not None
                else {},
                "video": _lines(windows.windows["Video Player"].view.lines),
            }
        )

    desktop.feed.applied.connect(surfaces)
    try:
        for update in updates:
            arrived(update)
            listener.caption_updated(update)
            app.processEvents()
        return events
    finally:
        if mutation == "shifted-span":
            captions._words_said = words_said
        transcripts.close()
        windows.close()
        desktop.close()


def main() -> None:
    print(
        json.dumps(
            trace(schedule(), os.environ.get("TRACE_MUTATION", "")), sort_keys=True
        )
    )


if __name__ == "__main__":
    main()
