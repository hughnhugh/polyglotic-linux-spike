"""Refresh the reviewed snapshot with this command under the Qt lock:

uv run pytest -p tests.ui.test_settings_start_quit \
    tests/ui/test_settings_start_quit.py -k match_the_snapshot --update
"""

import difflib
import json
import os
from collections.abc import Mapping
from pathlib import Path

import pytest
from PySide6.QtCore import QEvent, QTimer
from PySide6.QtWidgets import QApplication
from tests.ui.fakes import FakeAppList, MemorySettingsStore
from tests.ui.test_settings_across_versions import BEFORE_THE_SWITCH

from polyglotic_desktop.main import new_interface
from polyglotic_desktop.ui.app import DesktopApp
from polyglotic_desktop.ui_next.views import migration
from polyglotic_desktop.ui_next.views.caption_window import WindowChoices

SNAPSHOT = Path(__file__).parents[1] / "facades" / "settings-start-quit.json"
VOLATILE_VALUES = {
    # Hub sizes its first window to the screen's available geometry and DPI.
    # Keep the key and write phase visible, even when dimensions vary.
    "main_window_size": "<screen-dependent size>",
}


class RecordingStore(MemorySettingsStore):
    """Keep each save's changed and removed keys, in the order written."""

    def __init__(self, values: Mapping[str, object]) -> None:
        super().__init__(values)
        self.writes: list[dict[str, object]] = []

    def save(self, values: Mapping[str, object]) -> None:
        changed = {
            key: VOLATILE_VALUES.get(key, value)
            for key, value in values.items()
            if key not in self.values or value != self.values[key]
        }
        removed = sorted(self.values.keys() - values.keys())
        if changed or removed:
            # Freeze nested values at save time and use their JSON representation.
            self.writes.append(
                json.loads(json.dumps({"set": changed, "removed": removed}))
            )
        super().save(values)


def start_and_quit(
    qapp: QApplication, initial: Mapping[str, object]
) -> dict[str, list[dict[str, object]]]:
    store = RecordingStore(initial)
    desktop = DesktopApp(store, None, FakeAppList())
    interface = new_interface(desktop, store, None, per_app=True)
    desktop.quit_check = interface.transcripts.may_quit

    def close_interface() -> None:
        interface.close()
        desktop.close()

    qapp.aboutToQuit.connect(close_interface)
    guard = QTimer(desktop, singleShot=True, interval=5000)
    guard.timeout.connect(lambda: qapp.exit(9))
    try:
        desktop.show_window()
        qapp.processEvents()
        started = store.writes.copy()
        store.writes.clear()
        QTimer.singleShot(0, desktop.quit.trigger)
        guard.start()
        assert qapp.exec() == 0
        return {"start": started, "quit": store.writes.copy()}
    finally:
        guard.stop()
        qapp.aboutToQuit.disconnect(close_interface)
        interface.hub.window.deleteLater()
        desktop.deleteLater()
        qapp.sendPostedEvents(None, QEvent.Type.DeferredDelete)


def assert_matches_snapshot(actual: object) -> None:
    expected = "\n".join(SNAPSHOT.read_text(encoding="utf-8").splitlines()) + "\n"
    current = json.dumps(actual, indent=2, sort_keys=True) + "\n"
    if current != expected:
        changes = difflib.unified_diff(
            expected.splitlines(),
            current.splitlines(),
            fromfile="reviewed",
            tofile="actual",
        )
        pytest.fail("\n".join(changes), pytrace=False)


def settings_at_start_and_quit(qapp: QApplication) -> dict[str, object]:
    return {
        "empty": start_and_quit(qapp, {}),
        "before_the_switch": start_and_quit(qapp, BEFORE_THE_SWITCH),
    }


def test_settings_writes_match_the_snapshot(qapp: QApplication) -> None:
    actual = settings_at_start_and_quit(qapp)
    if os.environ.get("POLYGLOTIC_UPDATE_SNAPSHOT") == "1":
        SNAPSHOT.write_text(
            json.dumps(actual, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
            newline="\n",
        )
    assert_matches_snapshot(actual)


def test_a_changed_migration_default_breaks_the_start_snapshot(
    qapp: QApplication, monkeypatch: pytest.MonkeyPatch
) -> None:
    # The default in migration.todays_values feeds the startup save of the
    # oldest store's caption windows. No settings are changed by the test.
    monkeypatch.setattr(
        migration, "WindowChoices", lambda: WindowChoices(show_pace=False)
    )

    with pytest.raises(pytest.fail.Exception, match='"show_pace": false'):
        assert_matches_snapshot(settings_at_start_and_quit(qapp))
