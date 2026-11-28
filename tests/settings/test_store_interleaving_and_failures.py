"""Interleaved puts and removes, failed reads and failed replaces on `JsonSettingsStore`.

Tests multi-owner document merging (`Settings` beside `caption_windows`,
`transcripts`, `save_folder`, `words_open` and unknown future keys), transient
read failures, atomic `os.replace` failures (cross-platform via monkeypatch),
corrupt file set-aside, and reopening the recovered file in 0.1.12 (`c51062c4a`).
"""

import json
import os
from pathlib import Path
from typing import Any

import pytest
from tools.settings_corpus.reopen import (
    LAST_RELEASE_REF,
    ReleaseSourceUnavailable,
    extract_release_src,
    reopen_batch,
)

from polyglotic_desktop.adapters import json_settings
from polyglotic_desktop.adapters.json_settings import JsonSettingsStore
from polyglotic_desktop.ui import use_presets
from polyglotic_desktop.ui.settings import Settings


def _side_owner_put(store: JsonSettingsStore, key: str, value: object) -> None:
    """Simulate a side-store writer (`caption_windows`, `transcripts`, etc.) putting `key`."""
    current = store.load()
    store.save({**current, key: value})


def _side_owner_remove(store: JsonSettingsStore, key: str) -> None:
    """Simulate a side-store owner removing `key` from the shared settings document."""
    current = store.load()
    current.pop(key, None)
    store.save(current)


def _extract_or_skip(dest: Path) -> Path:
    try:
        return extract_release_src(LAST_RELEASE_REF, dest)
    except ReleaseSourceUnavailable as exc:
        if os.environ.get("GITHUB_REPOSITORY", "").endswith("/polyglotic-desktop"):
            pytest.fail(str(exc))
        pytest.skip(str(exc))


def test_interleaved_puts_and_removes_across_owners_and_reopen_in_last_release(
    tmp_path: Path,
) -> None:
    """Interleaved puts and removes across `Settings` and side-store owners never
    clobber each other or resurrect removed keys, and the resulting file reopens
    cleanly in 0.1.12."""
    path = tmp_path / "settings.json"
    store = JsonSettingsStore(path)
    try:
        # Initial seed with an unknown future key already on disk.
        store.save({"future_owner_v2": {"revision": 1, "flags": ["a", "b"]}})
        store.flush()

        settings = Settings(store)
        settings.update(
            theme="glaze",
            opacity=0.84,
            apps=("Sample Player", "Demo Browser"),
            whole_system=False,
            hotkeys={"lock": "ctrl+alt+l", "pause": "f9"},
        )
        _side_owner_put(
            store,
            "caption_windows",
            {
                "windows": {
                    "Sample Player": {"translate_into": "en", "text_size": 1.2},
                    "Demo Browser": {"translate_into": "ja", "text_size": 1.1},
                }
            },
        )
        _side_owner_put(
            store,
            "transcripts",
            {
                "Sample Player": {"text_size": 1.3, "rail_open": True},
                "Demo Browser": {"text_size": 1.0, "rail_open": False},
            },
        )
        _side_owner_put(store, "save_folder", "/tmp/polyglotic-interleaved")
        _side_owner_put(store, "words_open", {"zh": True, "ja": False})
        _side_owner_put(store, "ephemeral_side_key", {"temp": True})

        # Interleaved puts and removes across owners.
        settings.change(use_presets.added(settings.value, "Temp Preset"))
        assert settings.value.preset == "own1"
        _side_owner_remove(store, "ephemeral_side_key")

        # Remove one window and one transcript entry.
        raw_windows = store.load()["caption_windows"]
        assert isinstance(raw_windows, dict)
        windows_now = dict(raw_windows)
        inner_windows = dict(windows_now["windows"])
        del inner_windows["Demo Browser"]
        _side_owner_put(
            store, "caption_windows", {**windows_now, "windows": inner_windows}
        )

        raw_transcripts = store.load()["transcripts"]
        assert isinstance(raw_transcripts, dict)
        transcripts_now = dict(raw_transcripts)
        del transcripts_now["Demo Browser"]
        _side_owner_put(store, "transcripts", transcripts_now)

        # Remove a hotkey and delete the temporary preset via Settings.
        settings.update(hotkeys={"lock": "ctrl+alt+l"})
        settings.change(use_presets.removed(settings.value, "own1"))
        _side_owner_put(store, "words_open", {"zh": True})
    finally:
        store.close()

    reloaded = JsonSettingsStore(path).load()
    assert "ephemeral_side_key" not in reloaded
    assert reloaded["theme"] == "glaze"
    # Deleting `own1` switches back to `everyday` (restoring everyday's default opacity).
    assert reloaded["opacity"] == 0.88
    assert reloaded["apps"] == ["Sample Player", "Demo Browser"]
    assert reloaded["hotkeys"] == {"lock": "ctrl+alt+l"}
    assert reloaded["preset"] == "everyday"
    assert reloaded["own_presets"] == []
    assert reloaded["save_folder"] == "/tmp/polyglotic-interleaved"
    assert reloaded["words_open"] == {"zh": True}
    assert reloaded["future_owner_v2"] == {"revision": 1, "flags": ["a", "b"]}
    reloaded_windows = reloaded["caption_windows"]
    assert isinstance(reloaded_windows, dict)
    assert list(reloaded_windows["windows"]) == ["Sample Player"]
    reloaded_transcripts = reloaded["transcripts"]
    assert isinstance(reloaded_transcripts, dict)
    assert list(reloaded_transcripts) == ["Sample Player"]

    # Reopen and save the interleaved document in 0.1.12's own process.
    old_src = _extract_or_skip(tmp_path / "v0_1_12")
    outcome = reopen_batch(
        old_src, [("interleaved", reloaded)], tmp_path / "work", stem="interleaved"
    )[0]
    assert not outcome.rejected
    assert outcome.reopened["hotkeys"] == {"lock": "ctrl+alt+l"}
    assert outcome.reopened["theme"] == "glaze"
    assert outcome.saved["save_folder"] == "/tmp/polyglotic-interleaved"
    assert outcome.saved["words_open"] == {"zh": True}
    assert outcome.saved["future_owner_v2"] == {"revision": 1, "flags": ["a", "b"]}
    assert "ephemeral_side_key" not in outcome.saved


def test_failed_read_mid_session_preserves_last_known_state(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Corrupt, non-mapping, missing, or permission-denied reads after a good
    load/save return the last known state so interleaved puts/removes never wipe
    other owners' keys."""
    path = tmp_path / "settings.json"
    store = JsonSettingsStore(path)
    try:
        settings = Settings(store)
        settings.update(theme="signal", opacity=0.76)
        _side_owner_put(store, "save_folder", "/tmp/polyglotic-keep")
        _side_owner_put(store, "future_keep", {"ok": 1})
        store.flush()

        # 1. Corrupt JSON on disk.
        path.write_text("{truncated", encoding="utf-8")
        assert store.load()["theme"] == "signal"
        assert store.load()["save_folder"] == "/tmp/polyglotic-keep"

        # 2. Non-mapping JSON on disk.
        path.write_text("[1, 2, 3]", encoding="utf-8")
        assert store.load()["future_keep"] == {"ok": 1}

        # 3. File temporarily removed from disk.
        path.unlink()
        assert store.load()["theme"] == "signal"

        # 4. OS read failure via PermissionError while another owner puts and removes.
        real_open = Path.open

        def fail_read(self: Path, *args: Any, **kwargs: Any) -> Any:
            mode = args[0] if args else kwargs.get("mode", "r")
            if self == path and "w" not in str(mode):
                raise PermissionError("locked for reading")
            return real_open(self, *args, **kwargs)

        path.write_text('{"theme": "margin"}', encoding="utf-8")
        monkeypatch.setattr(Path, "open", fail_read)
        settings.update(window_theme="light")
        _side_owner_put(store, "words_open", {"zh": True})
        monkeypatch.undo()
    finally:
        store.close()

    reloaded = JsonSettingsStore(path).load()
    assert reloaded["theme"] == "signal"
    assert reloaded["window_theme"] == "light"
    assert reloaded["opacity"] == 0.76
    assert reloaded["save_folder"] == "/tmp/polyglotic-keep"
    assert reloaded["words_open"] == {"zh": True}
    assert reloaded["future_keep"] == {"ok": 1}


def test_failed_replace_keeps_latest_values_and_recovers_on_next_save(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """When atomic `os.replace` fails, the previous on-disk file stays intact,
    no `.tmp` file is left behind, in-memory puts/removes keep accumulating, and
    the next successful save writes the full accumulated state."""
    path = tmp_path / "settings.json"
    store = JsonSettingsStore(path)
    real_replace = json_settings.os.replace
    fail_replace = False

    def guarded_replace(src: Any, dst: Any) -> None:
        if fail_replace and Path(dst) == path:
            raise PermissionError("simulated antivirus lock on replace")
        real_replace(src, dst)

    monkeypatch.setattr(json_settings.os, "replace", guarded_replace)
    try:
        settings = Settings(store)
        settings.update(theme="margin", opacity=0.88)
        _side_owner_put(store, "save_folder", "/tmp/polyglotic-before")
        _side_owner_put(store, "drop_me", True)
        store.flush()
        baseline_on_disk = json.loads(path.read_text(encoding="utf-8"))

        # Trigger atomic replace failure across interleaved puts and removes.
        fail_replace = True
        settings.update(theme="glaze", opacity=0.62, hotkeys={"lock": "ctrl+alt+l"})
        _side_owner_put(store, "save_folder", "/tmp/polyglotic-during-fail")
        _side_owner_remove(store, "drop_me")
        _side_owner_put(store, "future_during_fail", [1, 2, 3])
        store.flush()

        # On-disk file is untouched, no .tmp left behind, memory holds newest state.
        assert json.loads(path.read_text(encoding="utf-8")) == baseline_on_disk
        assert not path.with_name("settings.json.tmp").exists()
        in_memory = store.load()
        assert in_memory["theme"] == "glaze"
        assert in_memory["opacity"] == 0.62
        assert in_memory["save_folder"] == "/tmp/polyglotic-during-fail"
        assert "drop_me" not in in_memory
        assert in_memory["future_during_fail"] == [1, 2, 3]

        # Recovery: next save succeeds and flushes the entire accumulated state.
        fail_replace = False
        settings.update(window_theme="light")
    finally:
        store.close()

    recovered = JsonSettingsStore(path).load()
    assert recovered["theme"] == "glaze"
    assert recovered["window_theme"] == "light"
    assert recovered["opacity"] == 0.62
    assert recovered["hotkeys"] == {"lock": "ctrl+alt+l"}
    assert recovered["save_folder"] == "/tmp/polyglotic-during-fail"
    assert "drop_me" not in recovered
    assert recovered["future_during_fail"] == [1, 2, 3]

    # Verify the recovered file also reopens cleanly in 0.1.12.
    old_src = _extract_or_skip(tmp_path / "v0_1_12")
    outcome = reopen_batch(
        old_src, [("recovered", recovered)], tmp_path / "work", stem="recovered"
    )[0]
    assert not outcome.rejected
    assert outcome.reopened["theme"] == "glaze"
    assert outcome.reopened["hotkeys"] == {"lock": "ctrl+alt+l"}
    assert outcome.saved["future_during_fail"] == [1, 2, 3]


@pytest.mark.parametrize("broken_content", ["{not json", "[1, 2, 3]"])
def test_cold_start_corrupt_file_is_set_aside_and_recovers(
    tmp_path: Path, broken_content: str
) -> None:
    """A corrupt or non-mapping file at cold start is set aside beside the settings
    without losing its bytes, and subsequent saves write a clean file."""
    path = tmp_path / "settings.json"
    path.write_text(broken_content, encoding="utf-8")

    store = JsonSettingsStore(path)
    try:
        settings = Settings(store)
        assert store.set_aside is not None
        assert store.set_aside.read_text(encoding="utf-8") == broken_content
        assert not path.exists()
        settings.update(theme="signal")
    finally:
        store.close()

    assert json.loads(path.read_text(encoding="utf-8"))["theme"] == "signal"
    assert store.set_aside.read_text(encoding="utf-8") == broken_content
