"""Capture the live, offscreen interface. Refresh with
`uv run python -m tests.ui.wiring_snapshot --update` under the Qt lock.
"""

import argparse
import hashlib
import json
import os
import sys
from collections import Counter, defaultdict
from pathlib import Path
from urllib.parse import quote

import pytest
import shiboken6
from PySide6.QtCore import (
    SIGNAL,
    QCoreApplication,
    QEvent,
    QLocale,
    QMetaMethod,
    QObject,
    QTimer,
)
from PySide6.QtWidgets import QApplication
from tests.ui.fakes import FakeAppList, MemorySettingsStore

from polyglotic_desktop import main
from polyglotic_desktop.core.listening.sources import SourceId
from polyglotic_desktop.ui.app import DesktopApp
from polyglotic_desktop.ui_next import languages

# One record per system: Qt builds a different tree on each (Linux has no
# minimise button and its own event dispatcher, Settings shows another help
# topic), so each system is held to its own.
GOLDEN = Path(__file__).resolve().parents[1] / "facades" / f"wiring-{sys.platform}.json"


def track_filters(patch: pytest.MonkeyPatch) -> dict[QObject, list[QObject]]:
    """Qt exposes installation and removal to Python, but no filter getter."""
    filters: dict[QObject, list[QObject]] = defaultdict(list)
    install = QObject.installEventFilter
    remove = QObject.removeEventFilter

    def installed(target: QObject, watcher: QObject) -> None:
        install(target, watcher)
        chain = filters[target]
        if watcher in chain:
            chain.remove(watcher)
        chain.insert(0, watcher)  # reinstalling moves the filter to the front

    def removed(target: QObject, watcher: QObject) -> None:
        remove(target, watcher)
        if watcher in filters[target]:
            filters[target].remove(watcher)

    patch.setattr(QObject, "installEventFilter", installed)
    patch.setattr(QObject, "removeEventFilter", removed)
    return filters


def component(obj: QObject) -> str:
    return quote(obj.objectName() or obj.metaObject().className(), safe=".")


def receivers_of(obj: QObject) -> dict[str, int]:
    """Each signal's receiver count, by its signature."""
    meta = obj.metaObject()
    signals = {}
    for i in range(meta.methodCount()):
        method = meta.method(i)
        if method.methodType() == QMetaMethod.MethodType.Signal:
            sig = bytes(method.methodSignature().data()).decode()
            signals[sig] = obj.receivers(SIGNAL(sig))
    return signals


def signature(obj: QObject) -> str:
    """Everything recorded about an object and its children, so that two
    roots sort the same way every run (ties are identical in every field)."""
    timer = f"{obj.interval()}:{obj.isSingleShot()}" if isinstance(obj, QTimer) else ""
    wired = sorted(f"{k}={v}" for k, v in receivers_of(obj).items() if v)
    kids = ",".join(signature(child) for child in obj.children())
    return f"{component(obj)}|{timer}|{';'.join(wired)}|[{kids}]"


def paths_for(roots: list[QObject]) -> dict[QObject, str]:
    """A stable path per object. Children keep Qt's order (creation order);
    the roots come from shiboken's wrapper table, whose order isn't stable
    from run to run, so they are sorted by what they are."""
    paths: dict[QObject, str] = {}
    roots = sorted(roots, key=signature)

    def visit(siblings: list[QObject], parent: str) -> None:
        counts = Counter(map(component, siblings))
        indices: Counter[str] = Counter()
        for obj in siblings:
            name = component(obj)
            segment = name
            if not obj.objectName() or counts[name] > 1:
                segment += f"[{indices[name]}]"
            indices[name] += 1
            path = f"{parent}/{segment}"
            paths[obj] = path
            visit(obj.children(), path)

    visit(roots, "")
    return paths


PLANTS = ("double", "drop")
"""Planted faults for the net's own tests: a doubled and a dropped
`.connect` on the app's Quit action, made after the real wiring."""


def capture(plant: str | None = None) -> dict:
    os.environ["QT_QPA_PLATFORM"] = "offscreen"
    app = QApplication(["wiring"])
    app.setStyle("Fusion")
    QLocale.setDefault(QLocale("en_US"))
    with pytest.MonkeyPatch.context() as patch:
        filters = track_filters(patch)
        patch.setattr(languages, "own_languages", lambda: ["en"])
        store = MemorySettingsStore({"apps": ["Web Browser"], "whole_system": False})
        desktop = DesktopApp(store, None, FakeAppList())
        interface = main.new_interface(desktop, store, None, per_app=True)
        try:
            main.QtListener(desktop, None)
            main.wire_caption_windows(interface.windows, desktop, lambda: None)
            main.wire_transcripts(interface.transcripts, desktop)
            interface.windows.set_captioned([("Web Browser", SourceId("app"))])
            interface.transcripts.follow()
            interface.transcripts.show("Web Browser")
            interface.hub.window.go_to("settings")
            if plant == "double":
                desktop.quit.triggered.connect(desktop.quit.trigger)
            elif plant == "drop":
                desktop.quit.triggered.disconnect()
            QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
            roots = [
                o
                for o in shiboken6.getAllValidWrappers()
                if isinstance(o, QObject) and o.parent() is None
            ]
            paths = paths_for(roots)
            snapshot = {}
            for obj, path in paths.items():
                meta = obj.metaObject()
                row = {
                    "class": meta.className(),
                    "name": obj.objectName(),
                    "children": len(obj.children()),
                    "receivers": {k: v for k, v in receivers_of(obj).items() if v},
                    # By what the filter is, not its path: identical filter
                    # objects at the root have no stable order between them.
                    "filters": [
                        component(f)
                        for f in filters.get(obj, [])
                        if shiboken6.isValid(f)
                    ],
                }
                if isinstance(obj, QTimer):
                    row["timer"] = {
                        "interval_ms": obj.interval(),
                        "singleShot": obj.isSingleShot(),
                        "active": obj.isActive(),
                    }
                snapshot[path] = row
            return snapshot
        finally:
            interface.close()
            desktop.close()
            shiboken6.delete(interface.hub.window)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--update", action="store_true")
    parser.add_argument("--out", type=Path)
    parser.add_argument("--plant", choices=PLANTS)
    args = parser.parse_args()
    data = (json.dumps(capture(args.plant), sort_keys=True, indent=2) + "\n").encode()
    print(hashlib.sha256(data).hexdigest(), len(data))
    if args.update:
        GOLDEN.parent.mkdir(exist_ok=True)
        GOLDEN.write_bytes(data)
    elif args.out:
        args.out.write_bytes(data)
