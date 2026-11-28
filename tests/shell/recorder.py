"""Subprocess harness that runs `polyglotic_desktop.main.main` offscreen and
records its exact start order, signal connection counts and stop order.

No file under `src/` is touched: every component constructed by `main` is
observed by wrapping its class/factory on `main` (and deferred modules) before
calling `main.main(argv)` in a fresh Python process.  A temporary data folder,
sample dictionaries, made-up credentials and a local stand-in server keep the
run completely isolated from the PC and network (RULES #26, #30).
"""

from __future__ import annotations

import argparse
import base64
import faulthandler
import functools
import importlib.util
import io
import json
import logging
import os
import signal
import sys
import threading
import time
import urllib.error
from collections.abc import Callable, Mapping, Sequence
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Self

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from nacl.signing import SigningKey
from PySide6.QtCore import QMetaMethod, QObject, QTimer
from PySide6.QtNetwork import QLocalSocket
from PySide6.QtWidgets import QApplication, QSystemTrayIcon
from tests.fake_server import FakeServer
from tests.test_sqlite_dictionary import write_sample

from polyglotic_desktop import main as real_main
from polyglotic_desktop.adapters import signed_feed
from polyglotic_desktop.adapters.json_settings import JsonSettingsStore
from polyglotic_desktop.adapters.sqlite_dictionary import write_dictionary
from polyglotic_desktop.adapters.sqlite_outbox import SqliteOutbox
from polyglotic_desktop.adapters.windows_session import (
    WM_ENDSESSION,
    WM_QUERYENDSESSION,
)
from polyglotic_desktop.connection import sign_in, tls
from polyglotic_desktop.connection.reconnect import StopReason
from polyglotic_desktop.connection.session import SessionState, Status
from polyglotic_desktop.core.shared.papers import TESTER_AGREEMENT_VERSION
from polyglotic_desktop.ports.capture import (
    AppCaptureSupport,
    AudioCallback,
    PlayingApp,
    SoundDevices,
    TrialOutcome,
)
from polyglotic_desktop.ports.consent import Agreement, ConsentChoice
from polyglotic_desktop.ports.credentials import DeviceCredentials
from polyglotic_desktop.ports.dictionary import EntryRecord
from polyglotic_desktop.ports.updates import Update
from polyglotic_desktop.ui import one_copy

# Timer intervals in `main._start_and_run` are all unique, so each QTimer can
# be named deterministically without modifying `src/polyglotic_desktop/main.py`.
TIMER_NAMES: dict[int, str] = {
    30_000: "account_refresh",
    60_000: "trace_kept_small",
    24 * 3600 * 1000: "pack_updates",
    5_000: "looking",
    100: "hearing",
    3_600_000: "sharing",
    6 * 3_600_000: "checking",
    600_000: "resending",
}

CONSENT_ID = "00000000-0000-4000-8000-000000000001"
INSTALL_ID = "00000000-0000-4000-8000-000000000002"
FAKE_TOKEN = "pgd_" + "a" * 43
CHECK_KEY = SigningKey(b"\x07" * 32)

# Faults that mutate `main.py` purely in memory inside this subprocess so
# tests can prove the shell net catches regressions without editing `src/`.
FAULTS = ("swapped_close", "doubled_about_to_quit", "doubled_connection")
# Parts that `--hang` makes never return, to prove the quit's 3 s limit
# (polyglotic-hq 1009): the subprocess then ends by the limit's own exit.
HANGS = ("connection.close",)
QUIT_STARTED = "quit_started"
"""A file in the work folder: the time the one quit path began (`time.time()`)."""
HANG_STARTED = "hang_started"
"""A file in the work folder: the time a `--hang` part began to hang."""
# Short times for the freeze scenario, so a test can block the interface
# thread for a second and a half rather than the product's ten.
FREEZE_SHORT = {"after": 0.5, "poll": 0.05, "heartbeat_ms": 50}
APP_LINE = "polyglotic_desktop.shell_net"
"""An app logger of the net's own, for the lines it plants in a run's log."""
OTHER_LINE = "websockets.client"
"""A library's logger: its lines never go into crash details."""
PLANTED = "PLANTED-caption-heron"
"""A caption-like value planted in a run's log: never in crash details."""


def load_main_module(fault: str | None, work_dir: Path) -> Any:
    """Return `polyglotic_desktop.main`, or an isolated mutated copy in
    `work_dir` for a planted fault check."""
    if fault is None:
        return real_main
    source_path = Path(real_main.__file__ or "")
    source = source_path.read_text(encoding="utf-8")
    if fault == "swapped_close":
        old = (
            "        interface.close()  # the windows' choices saved\n"
            "        desktop.close()\n"
            "        store.close()  # after the last save: written before the app ends"
        )
        new = (
            "        store.close()  # PLANTED FAULT: closed before interface\n"
            "        desktop.close()\n"
            "        interface.close()  # the windows' choices saved"
        )
    elif fault == "doubled_about_to_quit":
        old = "    app.aboutToQuit.connect(quit_cleanly)\n"
        new = (
            "    app.aboutToQuit.connect(quit_cleanly)\n"
            "    app.aboutToQuit.connect(quit_cleanly)\n"
        )
    elif fault == "doubled_connection":
        old = "    desktop.settings.changed.connect(settings_changed)\n"
        new = (
            "    desktop.settings.changed.connect(settings_changed)\n"
            "    desktop.settings.changed.connect(settings_changed)\n"
        )
    else:
        raise ValueError(f"unknown fault: {fault!r}")
    if old not in source:
        raise RuntimeError(f"fault target not found in main.py for {fault!r}")
    mutated_path = work_dir / f"_fault_{fault}_main.py"
    mutated_path.parent.mkdir(parents=True, exist_ok=True)
    mutated_path.write_text(source.replace(old, new, 1), encoding="utf-8")
    spec = importlib.util.spec_from_file_location(
        "polyglotic_desktop.main", mutated_path
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules["polyglotic_desktop.main"] = module
    spec.loader.exec_module(module)
    return module


def make_sample_dictionaries(folder: Path) -> Path:
    folder.mkdir(parents=True, exist_ok=True)
    write_sample(folder / "cedict.sqlite")
    run = EntryRecord("ecdict:run", "run", "", "rʌn", ("v. 跑",), 202)
    write_dictionary(
        folder / "ecdict.sqlite",
        {"dictionary": "ecdict"},
        [run],
        {"run": ["ecdict:run"]},
    )
    return folder


def seed_data_folder(
    data: Path,
    *,
    settings: Mapping[str, object] | None = None,
    with_consent: bool = True,
) -> None:
    data.mkdir(parents=True, exist_ok=True)
    if settings is not None:
        (data / "settings.json").write_text(
            json.dumps(dict(settings)), encoding="utf-8"
        )
    if with_consent:
        outbox = SqliteOutbox(data / "outbox.sqlite")
        try:
            now = datetime(2026, 11, 28, 0, 0, tzinfo=UTC)
            outbox.save_consent(
                ConsentChoice(
                    id=CONSENT_ID,
                    at=now,
                    usage=False,
                    crashes=False,
                    exposures=False,
                    agreement=Agreement(TESTER_AGREEMENT_VERSION, now),
                )
            )
        finally:
            outbox.close()


class EventLog:
    """Thread-safe recorder split into `start` (before quitting) and `stop`."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self.phase: str = "start"
        self.start: list[str] = []
        self.stop: list[str] = []
        self.notes: dict[str, Any] = {}

    def enter_stop(self) -> None:
        with self._lock:
            self.phase = "stop"

    def record(self, name: str, *, phase: str | None = None) -> None:
        with self._lock:
            target = phase or self.phase
            if target == "start":
                self.start.append(name)
            else:
                self.stop.append(name)


def _signal_receivers(
    obj: QObject, names: Sequence[str] | None = None
) -> dict[str, int]:
    """Return receiver counts for signals on `obj` via Qt's QMetaObject."""
    meta = obj.metaObject()
    found: dict[str, int] = {}
    wanted = set(names) if names is not None else None
    for index in range(meta.methodCount()):
        method = meta.method(index)
        if method.methodType() != QMetaMethod.MethodType.Signal:
            continue
        sig = bytes(method.methodSignature().data()).decode("ascii", "replace")
        short = sig.split("(", 1)[0]
        if wanted is not None and short not in wanted:
            continue
        if short in ("destroyed", "objectNameChanged"):
            continue
        count = obj.receivers("2" + sig)
        if count > 0 or wanted is not None:
            found[sig] = count
    return found


def _capture_connections(
    app: QApplication,
    app_baseline: Mapping[str, int],
    objects: Mapping[str, QObject | None],
) -> dict[str, int]:
    """Snapshot signal receiver counts for every wired shell object."""
    snapshot: dict[str, int] = {}
    app_now = _signal_receivers(
        app, ("aboutToQuit", "commitDataRequest", "applicationStateChanged")
    )
    for sig, count in sorted(app_now.items()):
        snapshot[f"app.{sig}"] = count - app_baseline.get(sig, 0)
    for label, obj in sorted(objects.items()):
        if obj is None:
            continue
        for sig, count in sorted(_signal_receivers(obj).items()):
            snapshot[f"{label}.{sig}"] = count
    return snapshot


# --- Stand-in OS adapters -----------------------------------------------------


class _FakeCopyLock:
    def __init__(self, log: EventLog, held: bool = False) -> None:
        self._log = log
        self._held = held

    def take(self) -> bool:
        self._log.record("copy_lock.take")
        return not self._held

    def release(self) -> None:
        self._log.record("copy_lock.release", phase="stop")


class _FakeAppList:
    def playing_apps(self) -> list[PlayingApp]:
        return []


class _FakeTrial:
    outcome: TrialOutcome | None = None

    def tell(self, outcome: TrialOutcome) -> None:
        self.outcome = outcome


class _FakeCapture:
    restarts = 0

    def __init__(self, log: EventLog, label: str, level: float = 0.25) -> None:
        self._log = log
        self._label = label
        self._level = level

    def start(self, on_audio: AudioCallback) -> None:
        self._log.record(f"capture.{self._label}.start")
        if self._level > 0:
            import numpy as np

            on_audio(0.0, np.full(1600, self._level, dtype="<f4").tobytes())

    def stop(self) -> None:
        self._log.record(f"capture.{self._label}.stop", phase="stop")

    @property
    def capturing(self) -> str | None:
        return f"Fake {self._label}"

    @property
    def error(self) -> str | None:
        return None


class _FakeCredentials:
    def __init__(self, signed_in: bool) -> None:
        self._creds = DeviceCredentials(INSTALL_ID, FAKE_TOKEN) if signed_in else None
        self._install_id = INSTALL_ID if signed_in else None

    def load(self) -> DeviceCredentials | None:
        return self._creds

    def install_id(self) -> str | None:
        return self._install_id

    def save(self, credentials: DeviceCredentials) -> None:
        self._creds = credentials
        self._install_id = credentials.install_id

    def forget(self) -> None:
        self._creds = None


class _FakeHotkeys:
    available = True

    def __init__(self, log: EventLog) -> None:
        self._log = log

    def start(self) -> list[str]:
        return []

    def stop(self) -> None:
        pass


class _FakeHoldKey:
    def start(self) -> bool:
        return True

    def stop(self) -> None:
        pass


class _FakeSoundOut:
    def play(self, _audio: object, _rate: int) -> None:
        pass

    def stop(self) -> None:
        pass


class _FakeSpeaker:
    def __init__(self, log: EventLog) -> None:
        self._log = log

    def voices(self) -> tuple[object, ...]:
        return ()

    def look_for_voices(self) -> None:
        pass

    def say(self, *_args: object, **_kwargs: object) -> None:
        pass

    def read(self, *_args: object, **_kwargs: object) -> None:
        pass

    def stop(self) -> None:
        pass

    def close(self) -> None:
        self._log.record("speaker.close", phase="stop")


class _FakeOnTop:
    def game_in_front(self) -> bool:
        return False

    def put_on_top(self, _windows: Sequence[int]) -> None:
        pass


class _FakeForegroundWatch:
    def __init__(self, log: EventLog) -> None:
        self._log = log

    def start(self) -> bool:
        self._log.record("in_front.start")
        return True

    def stop(self) -> None:
        self._log.record("in_front.stop", phase="stop")


class _FakeTranslocation:
    def __init__(self, log: EventLog, destination: Path) -> None:
        self._log = log
        self._destination = destination

    def translocated(self) -> bool:
        return True

    def move(self) -> Path:
        self._log.record("translocation.move")
        return self._destination

    def reopen(self, _app: Path) -> None:
        self._log.record("translocation.reopen", phase="stop")


class _FakeUpdater:
    """Stand-in Updater that records `apply_at_exit` and `restart_into`."""

    def __init__(
        self,
        log: EventLog,
        *,
        available: Update | None = None,
        installed: bool = True,
    ) -> None:
        self._log = log
        self._available = available
        self._installed = installed
        self.restarted = threading.Event()

    def installed(self) -> bool:
        return self._installed

    def find(self, _channel: str | None, _allow_downgrade: bool) -> Update | None:
        return self._available

    def download(self, _update: Update) -> None:
        pass

    def apply_at_exit(self, _update: Update, restart: bool = False) -> None:
        self._log.record(f"updater.apply_at_exit(restart={restart})", phase="stop")

    def restart_into(self, _update: Update) -> None:
        self._log.record("updater.restart_into", phase="stop")
        self.restarted.set()


def _make_os_adapters(
    main_mod: Any,
    log: EventLog,
    data: Path,
    *,
    os_name: str = "linux-6",
    lock_held: bool = False,
    signed_in: bool = True,
    with_translocation: bool = False,
    dictation: bool = True,
    list_voices_at_start: bool = False,
) -> Any:
    lock = _FakeCopyLock(log, held=lock_held)
    creds = _FakeCredentials(signed_in)

    def taskbar_id(tid: str) -> str:
        log.record("taskbar_identity")
        return tid

    return main_mod.OsAdapters(
        app_list=_FakeAppList,
        app_capture_support=lambda: AppCaptureSupport.YES,
        app_capture_trial=_FakeTrial,
        app_capture=lambda _pid, _name, _trial: _FakeCapture(log, "app"),
        everything_else_capture=lambda _left, _trial: _FakeCapture(log, "other"),
        windows_build=lambda: "",
        system_capture=lambda _dev: _FakeCapture(log, "system"),
        speaker_capture=lambda _dev: _FakeCapture(log, "speaker"),
        mic_capture=lambda _dev: _FakeCapture(log, "mic"),
        outputs_playing=lambda: None,
        credentials=lambda _entry: creds,
        hotkeys=lambda _mapping: _FakeHotkeys(log),
        sound_out=_FakeSoundOut,
        speaker=lambda _recordings: _FakeSpeaker(log),
        start_at_sign_in=None,
        copy_lock=lambda _name: lock,
        let_to_front=lambda _pid: None,
        keys=lambda _name: False,
        on_top=_FakeOnTop,
        foreground_watch=lambda _cb: _FakeForegroundWatch(log),
        light_taskbar=lambda: False,
        taskbar_identity=taskbar_id,
        store_package=lambda: None,
        os_name=lambda: os_name,
        os_version=lambda: "1.0",
        data_folder=lambda: data,
        show_error=lambda title, _text: log.record(f"show_error({title})"),
        seconds_since_launch=lambda: 0.1,
        read_fonts=lambda: False,
        make_native_window=lambda _addr: False,
        hold_key=lambda _k, _d, _u, _o: _FakeHoldKey(),
        type_text=lambda _text: False,
        keyboard_window=lambda: 0,
        type_text_for=lambda _text, _win: False,
        sound_devices=SoundDevices,
        metered=lambda: False,
        translocation=(
            (lambda: _FakeTranslocation(log, data / "Applications" / "Polyglotic.app"))
            if with_translocation
            else None
        ),
        dictation=dictation,
        list_voices_at_start=list_voices_at_start,
    )


class _HttpAnswer:
    def __init__(self, status: int, body: bytes = b"") -> None:
        self.status = status
        self._body = io.BytesIO(body)

    def read(self, limit: int = -1) -> bytes:
        return self._body.read(limit)

    def __enter__(self) -> Self:
        return self

    def __exit__(self, *_args: object) -> None:
        return None


def _install_check_network_standins(main_mod: Any, log: EventLog) -> None:
    """Replace network calls used by `--check-tls` and `--check-release`."""
    channel = main_mod.this_copys_release().channel
    feed = json.dumps(
        {
            "Assets": [
                {
                    "Type": "Full",
                    "Version": "0.1.13",
                    "FileName": f"Polyglotic-0.1.13-{channel}-full.nupkg",
                    "Size": 100,
                    "SHA256": "ab" * 32,
                }
            ]
        }
    ).encode()
    signature = CHECK_KEY.sign(signed_feed.signed_message(channel, feed)).signature
    public = base64.b64encode(bytes(CHECK_KEY.verify_key)).decode()

    def fake_urlopen(request: Any, timeout: float = 0.0) -> _HttpAnswer:
        _ = timeout
        url = request.full_url
        if url.endswith("/health"):
            log.record("check_tls.health")
            return _HttpAnswer(200, b"ok")
        if url.endswith(f"releases.{channel}.json"):
            log.record("check_release.feed")
            return _HttpAnswer(200, feed)
        if url.endswith(".json.sig"):
            log.record("check_release.signature")
            return _HttpAnswer(200, base64.b64encode(signature))
        if url.endswith(".nupkg"):
            log.record("check_release.package_head")
            return _HttpAnswer(206, b"P")
        if url.endswith("/v1/feedback"):
            log.record("check_release.report")
            raise urllib.error.HTTPError(
                url,
                401,
                "Unauthorized",
                {},  # type: ignore[arg-type]
                io.BytesIO(b'{"error": "token_not_valid"}'),
            )
        raise AssertionError(f"unexpected URL in check stand-in: {url}")

    tls.urlopen = fake_urlopen  # type: ignore[assignment]
    tls.roots = lambda: {"count": 1}
    main_mod._open_url = fake_urlopen
    main_mod.FEED_KEYS = (public,)

    def fake_redeem(*_args: object, **_kwargs: object) -> object:
        log.record("check_tls.sign_in")
        return sign_in.InviteNotValid()

    sign_in.redeem = fake_redeem  # type: ignore[assignment]

    def fake_session_reached(_server: str, _seconds: float) -> str:
        log.record("check_tls.session")
        return "opened"

    main_mod.session_reached = fake_session_reached


def _wrap_deferred_modules(
    log: EventLog,
    state: dict[str, Any],
) -> None:
    """Import and wrap the modules `_start_and_run` imports after first paint.

    Importing them inside this test harness before `main.main` does not touch
    production code; `tests/test_start_imports.py` checks deferred imports
    separately in its own subprocess.
    """
    from polyglotic_desktop.connection import feedback, problem_reports
    from polyglotic_desktop.platform import dictation_mic, speech_pipeline
    from polyglotic_desktop.ui import dictation, respeaking

    orig_sender_close = feedback.FeedbackSender.close

    def sender_close(self: Any) -> None:
        log.record("sender.close", phase="stop")
        orig_sender_close(self)

    feedback.FeedbackSender.close = sender_close  # type: ignore[method-assign]

    orig_problem_close = problem_reports.ProblemReportSender.close

    def problem_close(self: Any) -> None:
        log.record("problem_sender.close", phase="stop")
        orig_problem_close(self)

    problem_reports.ProblemReportSender.close = problem_close  # type: ignore[method-assign]

    orig_pipeline_init = speech_pipeline.SpeechPipeline.__init__
    orig_pipeline_stop = speech_pipeline.SpeechPipeline.stop

    def pipeline_init(self: Any, *args: Any, **kwargs: Any) -> None:
        log.record("pipeline.init")
        orig_pipeline_init(self, *args, **kwargs)

    def pipeline_stop(self: Any) -> None:
        log.record("pipeline.stop", phase="stop")
        orig_pipeline_stop(self)

    speech_pipeline.SpeechPipeline.__init__ = pipeline_init  # type: ignore[method-assign]
    speech_pipeline.SpeechPipeline.stop = pipeline_stop  # type: ignore[method-assign]

    orig_dictating_init = dictation.Dictating.__init__
    orig_dictating_stop = dictation.Dictating.stop

    def dictating_init(self: Any, *args: Any, **kwargs: Any) -> None:
        orig_dictating_init(self, *args, **kwargs)
        label = "typing_theirs" if kwargs.get("from_speakers") else "dictating"
        self._shell_net_label = label
        state[label] = self
        log.record(f"{label}.init")

    def dictating_stop(self: Any) -> None:
        label = getattr(self, "_shell_net_label", "dictating")
        if log.phase == "stop":
            log.record(f"{label}.stop", phase="stop")
        orig_dictating_stop(self)

    dictation.Dictating.__init__ = dictating_init  # type: ignore[method-assign]
    dictation.Dictating.stop = dictating_stop  # type: ignore[method-assign]

    orig_respeaking_init = respeaking.Respeaking.__init__
    orig_respeaking_stop = respeaking.Respeaking.stop

    def respeaking_init(self: Any, *args: Any, **kwargs: Any) -> None:
        orig_respeaking_init(self, *args, **kwargs)
        state["respeaking"] = self
        log.record("respeaking.init")

    def respeaking_stop(self: Any) -> None:
        if log.phase == "stop":
            log.record("respeaking.stop", phase="stop")
        orig_respeaking_stop(self)

    respeaking.Respeaking.__init__ = respeaking_init  # type: ignore[method-assign]
    respeaking.Respeaking.stop = respeaking_stop  # type: ignore[method-assign]

    orig_dmic_init = dictation_mic.DictationMic.__init__
    orig_dmic_stop = dictation_mic.DictationMic.stop
    dmic_count = [0]

    def dmic_init(self: Any, *args: Any, **kwargs: Any) -> None:
        orig_dmic_init(self, *args, **kwargs)
        dmic_count[0] += 1
        if kwargs.get("single_piece"):
            label = "speakers"
        elif kwargs.get("encode") is dictation_mic.encode_respeaking:
            label = "respeak_mic"
        else:
            label = "dictation_mic"
        self._shell_net_label = label
        log.record(f"{label}.init")

    def dmic_stop(self: Any) -> None:
        label = getattr(self, "_shell_net_label", "dictation_mic")
        log.record(f"{label}.stop", phase="stop")
        orig_dmic_stop(self)

    dictation_mic.DictationMic.__init__ = dmic_init  # type: ignore[method-assign]
    dictation_mic.DictationMic.stop = dmic_stop  # type: ignore[method-assign]


def _install_run_health_wrappers(
    main_mod: Any,
    log: EventLog,
    state: dict[str, Any],
    work_dir: Path,
    *,
    short_freeze: bool,
    crash_before_paint: bool = False,
) -> None:
    """The running note's removal in the stop order, the quit path's start
    time, Windows' session-end adapter, the crash offer and every report
    sent (polyglotic-hq 1009)."""
    orig_note_finish = main_mod.RunningNote.finish

    def note_finish(self: Any) -> None:
        log.record("running_note.finish", phase="stop")  # only as a run ends
        orig_note_finish(self)

    main_mod.RunningNote.finish = note_finish

    if crash_before_paint:  # a fault while the window is built (997's)
        orig_new_interface = main_mod.new_interface

        def faulting_build(*args: Any, **kwargs: Any) -> Any:
            plant_lines("early")
            crash_with_fatal_error()
            return orig_new_interface(*args, **kwargs)

        main_mod.new_interface = faulting_build

    orig_shutdown = main_mod.CleanShutdown

    class TimedShutdown(orig_shutdown):  # type: ignore[valid-type, misc]
        def __call__(self) -> None:
            started = work_dir / QUIT_STARTED
            if not started.exists():
                started.write_text(repr(time.time()), encoding="utf-8")
            super().__call__()

    main_mod.CleanShutdown = TimedShutdown

    orig_session_end = main_mod.WindowsSessionEnd

    class SeenSessionEnd(orig_session_end):  # type: ignore[valid-type, misc]
        def __init__(self, *args: Any, **kwargs: Any) -> None:
            super().__init__(*args, **kwargs)
            state["session_end"] = self

    main_mod.WindowsSessionEnd = SeenSessionEnd

    orig_offer = main_mod.offer_previous_crash

    def seen_offer(*args: Any, **kwargs: Any) -> Any:
        offer = orig_offer(*args, **kwargs)
        state["crash_offer"] = offer
        return offer

    main_mod.offer_previous_crash = seen_offer

    orig_submit = main_mod.submit_report_dialog
    submitted: list[dict[str, Any]] = state.setdefault("submitted", [])

    def seen_submit(
        mode: Any, text: Any, ticked: Any, *args: Any, **kwargs: Any
    ) -> Any:
        submitted.append(
            {
                "mode": mode,
                "ticked": sorted(ticked),
                "log_text": kwargs.get("log_text"),
            }
        )
        return orig_submit(mode, text, ticked, *args, **kwargs)

    main_mod.submit_report_dialog = seen_submit

    if short_freeze:
        main_mod.start_freeze_watch = functools.partial(
            main_mod.start_freeze_watch, **FREEZE_SHORT
        )


def _install_main_wrappers(
    main_mod: Any,
    log: EventLog,
    state: dict[str, Any],
    *,
    fake_updater: _FakeUpdater | None,
    on_linux_override: bool | None,
    tray_available: bool,
    on_exec: Callable[[QApplication], None] | None,
    hang: str | None = None,
    work_dir: Path | None = None,
) -> None:
    """Instrument `main_mod` so every lifecycle step is recorded in order."""
    if on_linux_override is not None:
        main_mod.on_linux = lambda: on_linux_override

    QSystemTrayIcon.isSystemTrayAvailable = staticmethod(lambda: tray_available)  # type: ignore[method-assign]

    # Pre-window steps
    def wrap_fn(attr: str, event: str, *, phase: str | None = None) -> None:
        orig = getattr(main_mod, attr)

        @functools.wraps(orig)
        def wrapped(*args: Any, **kwargs: Any) -> Any:
            log.record(event, phase=phase)
            return orig(*args, **kwargs)

        setattr(main_mod, attr, wrapped)

    wrap_fn("leave_packed_environment", "leave_packed_environment")
    wrap_fn("store_copy_here", "store_copy_here")
    wrap_fn("refuse_unknown_arguments", "refuse_unknown_arguments")
    wrap_fn("start_logging", "start_logging")
    wrap_fn("last_crash", "last_crash")
    wrap_fn("use_qt_platform", "use_qt_platform")
    wrap_fn("use_input_methods", "use_input_methods")
    wrap_fn("use_file_dialogs", "use_file_dialogs")
    wrap_fn("start_interface_language", "start_interface_language")
    wrap_fn("windows_deleted", "windows_deleted", phase="stop")

    # Never invoke real Velopack hooks during tests
    main_mod.run_installer_hooks = lambda: log.record("run_installer_hooks")

    # Never spawn a real child process on relaunch
    def fake_relaunch(given_argv: Sequence[str] = ()) -> bool:
        log.record("relaunch_app", phase="stop")
        log.notes["relaunch_flags"] = [a for a in given_argv if a.startswith("--")]
        return True

    main_mod.relaunch_app = fake_relaunch

    # Never hit real network for packs/fonts
    main_mod._open_pack_url = lambda _req, _timeout: (_ for _ in ()).throw(
        OSError("blocked in shell net")
    )

    # CrashTrace
    orig_ct_start = main_mod.CrashTrace.start
    orig_ct_stop = main_mod.CrashTrace.stop

    def ct_start(self: Any) -> bool:
        log.record("crash_trace.start")
        state["crash_trace"] = self
        return bool(orig_ct_start(self))

    def ct_stop(self: Any) -> None:
        log.record("crash_trace.stop", phase="stop")
        orig_ct_stop(self)

    main_mod.CrashTrace.start = ct_start
    main_mod.CrashTrace.stop = ct_stop

    # CrashLog
    orig_cl_install = main_mod.CrashLog.install

    def cl_install(self: Any) -> None:
        log.record("crashes.install")
        orig_cl_install(self)

    main_mod.CrashLog.install = cl_install

    # Updater & BackgroundUpdates
    if fake_updater is not None:

        def make_fake_updater(_feed: str) -> _FakeUpdater:
            log.record("updater")
            return fake_updater

        main_mod.updater = make_fake_updater
    else:
        wrap_fn("updater", "updater")

    orig_bu_check = main_mod.BackgroundUpdates.check
    orig_bu_restart = main_mod.BackgroundUpdates.restart_when_quitting
    orig_bu_update_now = main_mod.BackgroundUpdates.update_now
    orig_bu_at_exit = main_mod.BackgroundUpdates.at_exit

    def bu_check(self: Any) -> None:
        state["updates"] = self
        log.record("updates.check")
        orig_bu_check(self)

    def bu_restart(self: Any) -> None:
        log.record("updates.restart_when_quitting", phase="stop")
        orig_bu_restart(self)

    def bu_update_now(self: Any, found: Any) -> None:
        log.record("updates.update_now", phase="stop")
        orig_bu_update_now(self, found)

    def bu_at_exit(self: Any) -> None:
        log.record("updates.at_exit", phase="stop")
        orig_bu_at_exit(self)

    main_mod.BackgroundUpdates.check = bu_check
    main_mod.BackgroundUpdates.restart_when_quitting = bu_restart
    main_mod.BackgroundUpdates.update_now = bu_update_now
    main_mod.BackgroundUpdates.at_exit = bu_at_exit

    # QApplication
    orig_qapp = main_mod.QApplication

    class RecordingQApplication(orig_qapp):  # type: ignore[valid-type, misc]
        def __init__(self, argv: list[str]) -> None:
            log.record("QApplication.init")
            super().__init__(argv)
            state["app"] = self
            state["app_baseline"] = _signal_receivers(
                self, ("aboutToQuit", "commitDataRequest", "applicationStateChanged")
            )

        def setQuitOnLastWindowClosed(self, on: bool) -> None:
            log.record(f"app.setQuitOnLastWindowClosed({on})")
            super().setQuitOnLastWindowClosed(on)

        def exit(self, retcode: int = 0) -> None:
            log.enter_stop()
            log.record(f"app.exit({retcode})", phase="stop")
            super().exit(retcode)

        def exec(self) -> int:
            log.record("app.exec")
            state["connections"] = _capture_connections(
                self,
                state.get("app_baseline", {}),
                {
                    "desktop": state.get("desktop"),
                    "desktop.settings": (
                        state["desktop"].settings if "desktop" in state else None
                    ),
                    "desktop.quit": (
                        state["desktop"].quit if "desktop" in state else None
                    ),
                    "desktop.feed": (
                        state["desktop"].feed if "desktop" in state else None
                    ),
                    "desktop.pause": (
                        state["desktop"].pause if "desktop" in state else None
                    ),
                    "desktop.usage": (
                        state["desktop"].usage if "desktop" in state else None
                    ),
                    "desktop.lock_windows": (
                        state["desktop"].lock_windows if "desktop" in state else None
                    ),
                    "listener": state.get("listener"),
                    "hub.window": (
                        state["interface"].hub.window if "interface" in state else None
                    ),
                    "hub.home": (
                        state["interface"].hub.home if "interface" in state else None
                    ),
                    "hub.settings": (
                        state["interface"].hub.settings
                        if "interface" in state
                        else None
                    ),
                    "hub.account": (
                        state["interface"].hub.account if "interface" in state else None
                    ),
                    "windows": (
                        state["interface"].windows if "interface" in state else None
                    ),
                    "transcripts": (
                        state["interface"].transcripts if "interface" in state else None
                    ),
                    "packs": state.get("packs"),
                    "per_app": state.get("per_app"),
                    "dictating": state.get("dictating"),
                    "typing_theirs": state.get("typing_theirs"),
                    "respeaking": state.get("respeaking"),
                    **{
                        f"timer.{name}": timer
                        for name, timer in state.get("timers", {}).items()
                    },
                },
            )
            if on_exec is not None:
                QTimer.singleShot(0, lambda: on_exec(self))
            return int(super().exec())

    main_mod.QApplication = RecordingQApplication

    # QTimer
    orig_qtimer = main_mod.QTimer

    class RecordingQTimer(orig_qtimer):  # type: ignore[valid-type, misc]
        def __init__(self, *args: Any, **kwargs: Any) -> None:
            super().__init__(*args, **kwargs)
            interval = kwargs.get("interval")
            name = TIMER_NAMES.get(interval) if isinstance(interval, int) else None
            self._shell_net_name = name
            if name is not None:
                state.setdefault("timers", {})[name] = self

        def start(self, *args: Any, **kwargs: Any) -> None:
            name = getattr(self, "_shell_net_name", None)
            if name is not None:
                log.record(f"timer.{name}.start")
            super().start(*args, **kwargs)

        def stop(self) -> None:
            name = getattr(self, "_shell_net_name", None)
            if name is not None:
                log.record(f"timer.{name}.stop", phase="stop")
            super().stop()

    main_mod.QTimer = RecordingQTimer

    # SecondStarts
    orig_ss_init = one_copy.SecondStarts.__init__
    orig_ss_close = one_copy.SecondStarts.close

    def ss_init(self: Any, *args: Any, **kwargs: Any) -> None:
        log.record("second_starts.init")
        orig_ss_init(self, *args, **kwargs)
        state["second_starts"] = self

    def ss_close(self: Any) -> None:
        log.record("second_starts.close", phase="stop")
        orig_ss_close(self)

    one_copy.SecondStarts.__init__ = ss_init  # type: ignore[method-assign]
    one_copy.SecondStarts.close = ss_close  # type: ignore[method-assign]

    # Watchdog
    orig_wd_start = main_mod.Watchdog.start
    orig_wd_stop = main_mod.Watchdog.stop

    def wd_start(self: Any) -> None:
        log.record("watchdog.start")
        orig_wd_start(self)

    def wd_stop(self: Any) -> None:
        log.record("watchdog.stop", phase="stop")
        orig_wd_stop(self)

    main_mod.Watchdog.start = wd_start
    main_mod.Watchdog.stop = wd_stop

    # JsonSettingsStore
    orig_store_init = JsonSettingsStore.__init__
    orig_store_close = JsonSettingsStore.close

    def store_init(self: Any, *args: Any, **kwargs: Any) -> None:
        log.record("store.init")
        orig_store_init(self, *args, **kwargs)

    def store_close(self: Any) -> None:
        log.record("store.close", phase="stop")
        orig_store_close(self)

    JsonSettingsStore.__init__ = store_init  # type: ignore[method-assign]
    JsonSettingsStore.close = store_close  # type: ignore[method-assign]

    # BackgroundOutbox
    orig_outbox_init = main_mod.BackgroundOutbox.__init__
    orig_outbox_close = main_mod.BackgroundOutbox.close

    def outbox_init(self: Any, *args: Any, **kwargs: Any) -> None:
        log.record("outbox.init")
        orig_outbox_init(self, *args, **kwargs)

    def outbox_close(self: Any) -> None:
        log.record("outbox.close", phase="stop")
        orig_outbox_close(self)

    main_mod.BackgroundOutbox.__init__ = outbox_init
    main_mod.BackgroundOutbox.close = outbox_close

    # BackgroundLearningStore (primary vs beside vs check_install's chinese/english)
    orig_bls_init = main_mod.BackgroundLearningStore.__init__
    orig_bls_close = main_mod.BackgroundLearningStore.close
    bls_count = [0]

    def bls_init(self: Any, *args: Any, **kwargs: Any) -> None:
        orig_bls_init(self, *args, **kwargs)
        bls_count[0] += 1
        label = (
            "learning_store"
            if bls_count[0] == 1
            else f"beside_learning_store_{bls_count[0] - 1}"
        )
        self._shell_net_label = label
        log.record(f"{label}.init")

    def bls_close(self: Any) -> None:
        label = getattr(self, "_shell_net_label", "learning_store")
        log.record(f"{label}.close", phase="stop")
        orig_bls_close(self)

    main_mod.BackgroundLearningStore.__init__ = bls_init
    main_mod.BackgroundLearningStore.close = bls_close

    # DesktopApp
    orig_da_init = main_mod.DesktopApp.__init__
    orig_da_show_tray = main_mod.DesktopApp.show_tray
    orig_da_show_window = main_mod.DesktopApp.show_window
    orig_da_may_quit = main_mod.DesktopApp.may_quit
    orig_da_close = main_mod.DesktopApp.close

    def da_init(self: Any, *args: Any, **kwargs: Any) -> None:
        log.record("desktop.init")
        orig_da_init(self, *args, **kwargs)
        state["desktop"] = self

    def da_show_tray(self: Any) -> None:
        log.record("desktop.show_tray")
        orig_da_show_tray(self)

    def da_show_window(self: Any) -> None:
        log.record("desktop.show_window")
        orig_da_show_window(self)

    def da_may_quit(self: Any) -> bool:
        log.enter_stop()
        log.record("desktop.may_quit", phase="stop")
        return bool(orig_da_may_quit(self))

    def da_close(self: Any) -> None:
        log.record("desktop.close", phase="stop")
        orig_da_close(self)

    main_mod.DesktopApp.__init__ = da_init
    main_mod.DesktopApp.show_tray = da_show_tray
    main_mod.DesktopApp.show_window = da_show_window
    main_mod.DesktopApp.may_quit = da_may_quit
    main_mod.DesktopApp.close = da_close

    # AppsOneByOne
    orig_per_app_init = main_mod.AppsOneByOne.__init__

    def per_app_init(self: Any, *args: Any, **kwargs: Any) -> None:
        orig_per_app_init(self, *args, **kwargs)
        state["per_app"] = self
        log.record("per_app.init")

    main_mod.AppsOneByOne.__init__ = per_app_init

    # new_interface & Interface.close (plus its 5 internal substeps)
    orig_new_interface = main_mod.new_interface

    def wrapped_new_interface(*args: Any, **kwargs: Any) -> Any:
        log.record("new_interface")
        built = orig_new_interface(*args, **kwargs)
        state["interface"] = built
        return built

    main_mod.new_interface = wrapped_new_interface

    orig_iface_close = main_mod.Interface.close

    def iface_close(self: Any) -> None:
        log.enter_stop()
        log.record("interface.close", phase="stop")
        orig_iface_close(self)

    main_mod.Interface.close = iface_close

    orig_panels_save = main_mod.Panels.save_look

    def panels_save(self: Any) -> None:
        if log.phase == "stop":
            log.record("interface.panels.save_look", phase="stop")
        orig_panels_save(self)

    main_mod.Panels.save_look = panels_save

    orig_hub_keep = main_mod.Hub.keep_size
    orig_hub_close = main_mod.Hub.close

    def hub_keep(self: Any) -> None:
        log.record("interface.hub.keep_size", phase="stop")
        orig_hub_keep(self)

    def hub_close(self: Any) -> None:
        log.record("interface.hub.close", phase="stop")
        orig_hub_close(self)

    main_mod.Hub.keep_size = hub_keep
    main_mod.Hub.close = hub_close

    orig_transcripts_close = main_mod.Transcripts.close

    def transcripts_close(self: Any) -> None:
        log.record("interface.transcripts.close", phase="stop")
        orig_transcripts_close(self)

    main_mod.Transcripts.close = transcripts_close

    orig_windows_close = main_mod.CaptionWindows.close

    def windows_close(self: Any) -> None:
        log.record("interface.windows.close", phase="stop")
        orig_windows_close(self)

    main_mod.CaptionWindows.close = windows_close

    # QtListener & caption_connection
    orig_listener_init = main_mod.QtListener.__init__

    def listener_init(self: Any, *args: Any, **kwargs: Any) -> None:
        orig_listener_init(self, *args, **kwargs)
        state["listener"] = self
        log.record("listener.init")

    main_mod.QtListener.__init__ = listener_init

    orig_caption_conn = main_mod.caption_connection

    def wrapped_caption_conn(*args: Any, **kwargs: Any) -> Any:
        log.record("connection.init")
        conn = orig_caption_conn(*args, **kwargs)
        state["connection"] = conn
        orig_conn_close = conn.close

        def conn_close() -> None:
            log.record("connection.close", phase="stop")
            if hang == "connection.close" and work_dir is not None:
                (work_dir / HANG_STARTED).write_text(repr(time.time()), "utf-8")
                threading.Event().wait()  # a part that never returns
            orig_conn_close()

        conn.close = conn_close
        return conn

    main_mod.caption_connection = wrapped_caption_conn

    # PackDelivery & FontDelivery
    orig_packs_init = main_mod.PackDelivery.__init__
    orig_packs_close = main_mod.PackDelivery.close

    def packs_init(self: Any, *args: Any, **kwargs: Any) -> None:
        log.record("packs.init")
        orig_packs_init(self, *args, **kwargs)
        state["packs"] = self

    def packs_close(self: Any) -> None:
        log.record("packs.close", phase="stop")
        orig_packs_close(self)

    main_mod.PackDelivery.__init__ = packs_init
    main_mod.PackDelivery.close = packs_close

    orig_faces_init = main_mod.FontDelivery.__init__

    def faces_init(self: Any, *args: Any, **kwargs: Any) -> None:
        log.record("faces.init")
        orig_faces_init(self, *args, **kwargs)

    main_mod.FontDelivery.__init__ = faces_init

    # UpdateShown (captures `restart_into_update` callback for update-restart tests)
    orig_us_init = main_mod.UpdateShown.__init__

    def us_init(self: Any, *args: Any, **kwargs: Any) -> None:
        orig_us_init(self, *args, **kwargs)
        state["update_shown"] = self

    main_mod.UpdateShown.__init__ = us_init

    # AppHotkeys & DictationKeyHeld
    orig_ah_init = main_mod.AppHotkeys.__init__
    orig_ah_stop = main_mod.AppHotkeys.stop

    def ah_init(self: Any, *args: Any, **kwargs: Any) -> None:
        log.record("hotkeys.init")
        orig_ah_init(self, *args, **kwargs)

    def ah_stop(self: Any) -> None:
        if log.phase == "stop":
            log.record("hotkeys.stop", phase="stop")
        orig_ah_stop(self)

    main_mod.AppHotkeys.__init__ = ah_init
    main_mod.AppHotkeys.stop = ah_stop

    orig_dk_init = main_mod.DictationKeyHeld.__init__
    orig_dk_stop = main_mod.DictationKeyHeld.stop
    dk_count = [0]

    def dk_init(self: Any, *args: Any, **kwargs: Any) -> None:
        orig_dk_init(self, *args, **kwargs)
        dk_count[0] += 1
        label = "dictation_key" if dk_count[0] == 1 else "respeak_key"
        self._shell_net_label = label
        log.record(f"{label}.init")

    def dk_stop(self: Any) -> None:
        label = getattr(self, "_shell_net_label", "dictation_key")
        if log.phase == "stop":
            log.record(f"{label}.stop", phase="stop")
        orig_dk_stop(self)

    main_mod.DictationKeyHeld.__init__ = dk_init
    main_mod.DictationKeyHeld.stop = dk_stop

    # ThreadPoolExecutor for `pack_learners`
    orig_tpe = main_mod.ThreadPoolExecutor

    class RecordingTPE(orig_tpe):  # type: ignore[valid-type, misc]
        def __init__(self, *args: Any, **kwargs: Any) -> None:
            self._shell_net_prefix = kwargs.get("thread_name_prefix", "")
            if self._shell_net_prefix == "pack-learner":
                log.record("pack_learners.init")
            super().__init__(*args, **kwargs)

        def shutdown(self, wait: bool = True, *, cancel_futures: bool = False) -> None:
            if self._shell_net_prefix == "pack-learner":
                log.record("pack_learners.shutdown", phase="stop")
            super().shutdown(wait=wait, cancel_futures=cancel_futures)

    main_mod.ThreadPoolExecutor = RecordingTPE

    # Background threads started directly by `_start_and_run`
    orig_thread_start = threading.Thread.start

    def recording_thread_start(self: threading.Thread) -> None:
        if self.name in ("imports", "milestones"):
            log.record(f"thread.{self.name}.start")
        orig_thread_start(self)

    threading.Thread.start = recording_thread_start  # type: ignore[method-assign]

    # Pin OS locale language list so runs are independent of runner locale.
    main_mod.interface_language.windows_languages = lambda: ["en"]

    # Deferred modules
    _wrap_deferred_modules(log, state)


def run_scenario(
    scenario: str,
    work_dir: Path,
    *,
    fault: str | None = None,
    hang: str | None = None,
) -> dict[str, Any]:
    """Run one named shell lifecycle scenario and return its recorded trace."""
    main_mod = load_main_module(fault, work_dir)
    log = EventLog()
    state: dict[str, Any] = {}
    data = work_dir / "data"
    dicts = make_sample_dictionaries(work_dir / "dictionaries")
    updates_dir = work_dir / "updates"
    updates_dir.mkdir(parents=True, exist_ok=True)
    report_path = work_dir / "check-report.json"

    server: FakeServer | None = None
    server_url = "http://127.0.0.1:9"
    needs_server = scenario in (
        "normal_tray_quit",
        "normal_with_beside",
        "language_relaunch",
        "linux_start_to_quit",
        "quit_close_last_window_with_tray",
        "quit_close_last_window_no_tray_quit",
        "quit_close_last_window_no_tray_keep",
        "quit_close_last_window_neither",
        "quit_second_copy_asks_quit",
        "quit_update_restart_windows",
        "quit_update_restart_linux",
        "quit_update_restart_forced",
        "quit_windows_session_end",
        "quit_ctrl_c",
        *RUN_HEALTH_SCENARIOS,
    )
    if needs_server:
        server = FakeServer()
        server_url = server.url

    try:
        return _dispatch_scenario(
            scenario,
            main_mod,
            log,
            state,
            data=data,
            dicts=dicts,
            updates_dir=updates_dir,
            report_path=report_path,
            server_url=server_url,
            work_dir=work_dir,
            hang=hang,
        )
    finally:
        if server is not None:
            server.stop()


def _dispatch_scenario(
    scenario: str,
    main_mod: Any,
    log: EventLog,
    state: dict[str, Any],
    *,
    data: Path,
    dicts: Path,
    updates_dir: Path,
    report_path: Path,
    server_url: str,
    work_dir: Path,
    hang: str | None = None,
) -> dict[str, Any]:
    base_settings: dict[str, object] = {
        "learning": "zh",
        "whole_system": False,
        "apps": [],
        "first_run_step": "done",
    }
    if scenario == "normal_with_beside":
        base_settings["also_learning"] = ["en"]

    on_linux_override: bool | None = False
    tray_available = True
    dictation = True
    os_name = "linux-6"
    lock_held = False
    with_translocation = False
    fake_updater: _FakeUpdater | None = _FakeUpdater(
        log, available=None, installed=False
    )
    on_exec: Callable[[QApplication], None] | None = None
    argv: list[str] = [
        "--data",
        str(data),
        "--dictionaries",
        str(dicts),
        "--server",
        server_url,
        "--updates",
        str(updates_dir),
    ]

    if scenario == "normal_tray_quit":
        seed_data_folder(data, settings=base_settings)
        on_exec = lambda _app: state["desktop"].quit.trigger()

    elif scenario == "linux_start_to_quit":
        seed_data_folder(data, settings=base_settings)
        on_linux_override = True
        dictation = False
        on_exec = lambda _app: state["desktop"].quit.trigger()

    elif scenario == "normal_with_beside":
        seed_data_folder(data, settings=base_settings)

        def wait_for_beside_then_quit(_app: QApplication) -> None:
            desktop = state["desktop"]
            if desktop.tools is not None and len(desktop.tools.every) >= 2:
                desktop.quit.trigger()
            else:
                QTimer.singleShot(10, lambda: wait_for_beside_then_quit(_app))

        on_exec = wait_for_beside_then_quit

    elif scenario == "language_relaunch":
        seed_data_folder(data, settings=base_settings)
        on_exec = lambda _app: state[
            "interface"
        ].hub.settings.language_restart_wanted.emit()

    elif scenario == "early_exit_moved_to_applications":
        seed_data_folder(data, settings=base_settings)
        with_translocation = True
        orig_moved = main_mod.moved_to_applications

        def moved_auto(place: Any, settings: Any) -> bool:
            return bool(orig_moved(place, settings, offer=lambda p: p.move()))

        main_mod.moved_to_applications = moved_auto

    elif scenario == "early_exit_restart_for_language":
        seed_data_folder(data, settings=base_settings)

        def first_run_restart(
            _store: Any, learner: Any, *_args: Any, **_kwargs: Any
        ) -> Any:
            _tools, learning_store = learner(False)
            log.enter_stop()
            learning_store.close()
            raise main_mod.RestartForLanguage

        main_mod.first_run = first_run_restart

    elif scenario == "early_exit_not_agreed":
        seed_data_folder(data, settings=base_settings)

        def first_run_not_agreed(
            _store: Any, learner: Any, *_args: Any, **_kwargs: Any
        ) -> Any:
            _tools, learning_store = learner(False)
            log.enter_stop()
            learning_store.close()
            raise main_mod.NotAgreed

        main_mod.first_run = first_run_not_agreed

    elif scenario == "check_install":
        seed_data_folder(data, settings=base_settings)
        fake_updater = _FakeUpdater(log, available=None, installed=False)
        argv = [
            "--check-install",
            str(report_path),
            "--dictionaries",
            str(dicts),
            "--data",
            str(data),
        ]

    elif scenario in ("check_capture_non_windows", "check_capture_windows"):
        os_name = "windows-11" if scenario == "check_capture_windows" else "linux-6"
        main_mod.CHECK_CAPTURE_SEC = 0.01
        argv = ["--check-capture", str(report_path)]

    elif scenario == "check_parity_non_macos":
        os_name = "linux-6"
        argv = ["--check-parity", str(report_path)]

    elif scenario == "check_tls":
        _install_check_network_standins(main_mod, log)
        argv = ["--check-tls", str(report_path), "--server", "https://api.example"]

    elif scenario == "check_release":
        _install_check_network_standins(main_mod, log)
        argv = [
            "--check-release",
            str(report_path),
            "--server",
            "https://api.example",
            "--updates",
            "https://updates.example/",
        ]

    elif scenario == "quit_close_last_window_with_tray":
        seed_data_folder(data, settings=base_settings)

        def close_with_tray(app: QApplication) -> None:
            hub = state["interface"].hub
            hidden: list[bool] = []
            hub.window.hidden_to_tray.connect(lambda: hidden.append(True))
            log.enter_stop()
            hub.window.close()
            app.processEvents()
            log.notes["window_visible_after_close"] = hub.window.isVisible()
            log.notes["hidden_to_tray_emitted"] = bool(hidden)
            log.notes["quit_triggered_by_close"] = "app.exit(0)" in log.stop
            # Capture stop steps triggered by close itself, then end the loop
            # without letting teardown masquerade as close-triggered steps.
            log.notes["stop_during_action"] = list(log.stop)
            QApplication.exit(0)

        on_exec = close_with_tray

    elif scenario == "quit_close_last_window_no_tray_quit":
        seed_data_folder(data, settings=base_settings)
        tray_available = False

        def close_no_tray_quit(_app: QApplication) -> None:
            hub = state["interface"].hub
            hub.keep_running = lambda _parent: False
            log.enter_stop()
            hub.window.close()

        on_exec = close_no_tray_quit

    elif scenario == "quit_close_last_window_no_tray_keep":
        seed_data_folder(data, settings=base_settings)
        tray_available = False

        def close_no_tray_keep(app: QApplication) -> None:
            hub = state["interface"].hub
            hub.keep_running = lambda _parent: True
            log.enter_stop()
            hub.window.close()
            app.processEvents()
            log.notes["window_visible_after_close"] = hub.window.isVisible()
            log.notes["stop_during_action"] = list(log.stop)
            QApplication.exit(0)

        on_exec = close_no_tray_keep

    elif scenario == "quit_close_last_window_neither":
        seed_data_folder(data, settings=base_settings)
        tray_available = False

        def close_neither(app: QApplication) -> None:
            hub = state["interface"].hub
            hub.window.keep_in_tray = False
            hub.window.no_tray = False
            log.enter_stop()
            closed = hub.window.close()
            app.processEvents()
            log.notes["close_accepted"] = bool(closed)
            log.notes["quit_on_last_window_closed"] = app.quitOnLastWindowClosed()
            log.notes["stop_during_action"] = list(log.stop)
            QApplication.exit(0)

        on_exec = close_neither

    elif scenario == "quit_second_copy_asks_quit":
        seed_data_folder(data, settings=base_settings)

        def send_quit_over_socket(app: QApplication) -> None:
            name = one_copy.copy_name(data, one_copy.user())
            log.enter_stop()
            # 1) Send "quit\n" directly to SecondStarts socket
            sock = QLocalSocket()
            sock.connectToServer(name)
            connected = sock.waitForConnected(2000)
            greeting = b""
            reply = b""
            if connected:
                deadline = time.monotonic() + 2.0
                while not sock.canReadLine() and time.monotonic() < deadline:
                    app.processEvents()
                    sock.waitForReadyRead(20)
                greeting = bytes(sock.readLine(64).data()).strip()
                sock.write(b"quit\n")
                sock.flush()
                deadline = time.monotonic() + 0.5
                while (
                    sock.state() == QLocalSocket.LocalSocketState.ConnectedState
                    and time.monotonic() < deadline
                ):
                    app.processEvents()
                    sock.waitForReadyRead(20)
                reply = bytes(sock.readAll().data()).strip()
            sock.abort()
            app.processEvents()
            log.notes["socket_connected"] = connected
            log.notes["greeting_prefix"] = greeting.split(b" ")[0].decode(
                "ascii", "replace"
            )
            log.notes["quit_command_reply"] = reply.decode("ascii", "replace")
            log.notes["supported_commands"] = list(one_copy.COMMANDS)
            log.notes["stop_during_action"] = list(log.stop)
            QApplication.exit(0)

        on_exec = send_quit_over_socket

    elif scenario == "quit_second_copy_second_process_show":
        lock_held = True

        def fake_one_copy_start(
            _take: object, _ask: object, show: bool, *_args: object, **_kwargs: object
        ) -> one_copy.Start:
            log.record(f"one_copy.start(show={show})")
            return one_copy.Start.SHOWN

        one_copy.start = fake_one_copy_start  # type: ignore[assignment]

    elif scenario == "quit_second_copy_cli_flag":
        argv = ["--data", str(data), "--quit"]

    elif scenario == "quit_update_restart_windows":
        seed_data_folder(data, settings=base_settings)
        on_linux_override = False
        update = Update("9.9.9")
        fake_updater = _FakeUpdater(log, available=update, installed=True)

        def trigger_restart_win(_app: QApplication) -> None:
            updates = state["updates"]
            updates._worker.submit(lambda: None).result(timeout=5)
            state["desktop"].install_update.trigger()

        on_exec = trigger_restart_win

    elif scenario == "quit_update_restart_linux":
        seed_data_folder(data, settings=base_settings)
        on_linux_override = True
        dictation = False
        update = Update("9.9.9")
        fake_updater = _FakeUpdater(log, available=update, installed=True)

        def trigger_restart_linux(_app: QApplication) -> None:
            updates = state["updates"]
            updates._worker.submit(lambda: None).result(timeout=5)
            state["desktop"].install_update.trigger()

        on_exec = trigger_restart_linux

    elif scenario == "quit_update_restart_forced":
        seed_data_folder(data, settings=base_settings)
        on_linux_override = False
        update = Update("9.9.9")
        fake_updater = _FakeUpdater(log, available=update, installed=True)

        def trigger_forced_update(app: QApplication) -> None:
            updates = state["updates"]
            updates._worker.submit(lambda: None).result(timeout=5)
            log.enter_stop()
            state["listener"].status_changed(
                Status(SessionState.STOPPED, stopped=StopReason.UPDATE_REQUIRED)
            )
            deadline = time.monotonic() + 5.0
            while not fake_updater.restarted.is_set() and time.monotonic() < deadline:
                app.processEvents()
                time.sleep(0.01)
            log.notes["updater_restart_into_called"] = fake_updater.restarted.is_set()
            log.notes["stop_during_action"] = list(log.stop)
            QApplication.exit(0)

        on_exec = trigger_forced_update

    elif scenario == "quit_windows_session_end":
        seed_data_folder(data, settings=base_settings)
        tray_available = True

        def end_session(app: QApplication) -> None:
            """Windows' own order (polyglotic-hq 1009): the query, which
            another app could still cancel; a cancelled end; then the end,
            whose handler must have quit cleanly before it returns. Through
            the adapter `main` gave the native filter (on Windows only)."""
            session_end = state["session_end"]
            note = data / "running.json"
            commit_receivers = app.receivers("2commitDataRequest(QSessionManager&)")
            save_receivers = app.receivers("2saveStateRequest(QSessionManager&)")
            log.enter_stop()
            session_end.message(WM_QUERYENDSESSION)
            log.notes["after_query"] = {"stop": list(log.stop), "note": note.exists()}
            session_end.message(WM_ENDSESSION, ending=False)
            log.notes["after_cancelled_end"] = {
                "stop": list(log.stop),
                "note": note.exists(),
            }
            session_end.message(WM_ENDSESSION, ending=True)
            log.notes["note_after_end"] = note.exists()
            log.notes["commitDataRequest_receivers"] = commit_receivers
            log.notes["saveStateRequest_receivers"] = save_receivers
            QApplication.exit(0)  # as Qt quits after the end's aboutToQuit

        on_exec = end_session

    elif scenario == "quit_ctrl_c":
        seed_data_folder(data, settings=base_settings)

        def press_ctrl_c(_app: QApplication) -> None:
            log.enter_stop()
            signal.raise_signal(signal.SIGINT)  # as Ctrl+C in the console

        on_exec = press_ctrl_c

    elif scenario in RUN_HEALTH_SCENARIOS:
        if not (data / "settings.json").exists():  # the runs before kept theirs
            seed_data_folder(data, settings=base_settings)
        on_exec = _run_health_action(scenario, state, log, data)

    else:
        raise ValueError(f"unknown scenario: {scenario!r}")

    fake_os = _make_os_adapters(
        main_mod,
        log,
        data,
        os_name=os_name,
        lock_held=lock_held,
        signed_in=True,
        with_translocation=with_translocation,
        dictation=dictation,
        list_voices_at_start=False,
    )
    main_mod.os_adapters = lambda system=sys.platform: fake_os

    _install_main_wrappers(
        main_mod,
        log,
        state,
        fake_updater=fake_updater,
        on_linux_override=on_linux_override,
        tray_available=tray_available,
        on_exec=on_exec,
        hang=hang,
        work_dir=work_dir,
    )
    _install_run_health_wrappers(
        main_mod,
        log,
        state,
        work_dir,
        short_freeze=scenario == "freeze_traced",
        crash_before_paint=scenario == "crash_before_paint",
    )

    exit_code: int | str | None = None
    try:
        main_mod.main(argv)
    except SystemExit as ended:
        exit_code = ended.code if isinstance(ended.code, int) else str(ended.code)
        log.record(f"sys.exit({exit_code})", phase="stop")
    finally:
        # Close any background worker left open by an early exit so the
        # subprocess exits cleanly without altering the recorded trace.
        updates_obj = state.get("updates")
        if updates_obj is not None and not updates_obj._worker._shutdown:
            updates_obj._worker.shutdown(wait=False, cancel_futures=True)
        ct = state.get("crash_trace")
        if ct is not None and ct._stream is not None:
            ct._stream.close()
            ct._stream = None

    if report_path.is_file():
        report = json.loads(report_path.read_text(encoding="utf-8"))
        log.notes["check_ok"] = report.get("ok")

    result: dict[str, Any] = {
        "scenario": scenario,
        "exit_code": exit_code,
        "start": log.start,
        "stop": log.notes.get("stop_during_action", log.stop),
        # not in the recorded orders: whether this run's note outlived it
        "running_note_left": (data / "running.json").exists(),
    }
    if "connections" in state:
        result["connections"] = state["connections"]
    if log.notes:
        result["notes"] = {
            k: v for k, v in log.notes.items() if k != "stop_during_action"
        }
    return result


RUN_HEALTH_SCENARIOS: tuple[str, ...] = (
    "freeze_traced",
    "crash_fatal",
    "crash_before_paint",
    "crash_offer_send",
    "crash_offer_dont_send",
)
"""Runs one after another in one data folder (polyglotic-hq 1009): what
they leave is what they test, not an order, so they're outside the
recorded orders (`ALL_SCENARIOS`)."""


def plant_lines(run: str) -> None:
    """Lines a run writes in its log: one of the app's own, naming the run;
    one of a library's and a value carried onto a line of its own, each
    with a planted caption; and the home folder in one of the app's."""
    ours = logging.getLogger(APP_LINE)
    ours.info("shell net: run %s", run)
    ours.info("shell net: a file under %s", Path.home() / "private.txt")
    ours.info("shell net: a value over two lines\n%s", PLANTED)
    logging.getLogger(OTHER_LINE).warning("shell net: %s", PLANTED)


def block_interface_thread(seconds: float) -> None:
    """The interface thread stuck, as a hung part would leave it."""
    time.sleep(seconds)


def crash_with_fatal_error() -> None:
    """A fault no Python `except` catches, as one inside Qt would be."""
    faulthandler._sigsegv()  # type: ignore[attr-defined]


def _run_health_action(
    scenario: str, state: dict[str, Any], log: EventLog, data: Path
) -> Callable[[QApplication], None]:
    """What each of `RUN_HEALTH_SCENARIOS` does once the app is running."""
    trace = data / "logs" / "crash.log"

    def freeze(app: QApplication) -> None:
        plant_lines("A")
        app.processEvents()  # a heartbeat or two first
        block_interface_thread(1.5)  # three times the shortened limit
        text = trace.read_text("utf-8", errors="replace")
        log.notes["trace_has_blocker"] = "in block_interface_thread" in text
        log.notes["trace_names_its_run"] = text.startswith("Polyglotic run ")
        state["desktop"].quit.trigger()

    def crash(_app: QApplication) -> None:
        plant_lines("B")
        crash_with_fatal_error()

    def offered(choice: str) -> Callable[[QApplication], None]:
        def act(app: QApplication) -> None:
            offer = state.get("crash_offer")
            submitted = state.setdefault("submitted", [])
            log.notes["offer_shown"] = offer is not None and offer.isVisible()
            log.notes["sent_before_a_choice"] = list(submitted)
            if offer is not None:
                offer.see.click()
                log.notes["preview_shown"] = offer.preview.isVisible()
                log.notes["preview"] = offer.preview.toPlainText()
                (offer.send if choice == "send" else offer.dismiss).click()
                app.processEvents()
            dialogs = [
                w
                for w in QApplication.topLevelWidgets()
                if w.objectName() == "ProblemReportDialog" and w.isVisible()
            ]
            log.notes["report_dialog_shown"] = bool(dialogs)
            if dialogs:
                dialog: Any = dialogs[0]  # a ProblemReportDialog
                dialog.text.setPlainText("It closed while I was watching.")
                app.processEvents()
                dialog.send.click()
                app.processEvents()
            log.notes["submitted"] = list(submitted)
            state["desktop"].quit.trigger()

        return act

    actions: dict[str, Callable[[QApplication], None]] = {
        "freeze_traced": freeze,
        "crash_fatal": crash,
        "crash_before_paint": crash,  # never reached: it faults before the loop
        "crash_offer_send": offered("send"),
        "crash_offer_dont_send": offered("dont"),
    }
    return actions[scenario]


ALL_SCENARIOS: tuple[str, ...] = (
    "normal_tray_quit",
    "linux_start_to_quit",
    "normal_with_beside",
    "language_relaunch",
    "early_exit_moved_to_applications",
    "early_exit_restart_for_language",
    "early_exit_not_agreed",
    "check_install",
    "check_capture_non_windows",
    "check_capture_windows",
    "check_parity_non_macos",
    "check_tls",
    "check_release",
    "quit_close_last_window_with_tray",
    "quit_close_last_window_no_tray_quit",
    "quit_close_last_window_no_tray_keep",
    "quit_close_last_window_neither",
    "quit_second_copy_asks_quit",
    "quit_second_copy_second_process_show",
    "quit_second_copy_cli_flag",
    "quit_update_restart_windows",
    "quit_update_restart_linux",
    "quit_update_restart_forced",
    "quit_windows_session_end",
    "quit_ctrl_c",
)


def main() -> None:
    parser = argparse.ArgumentParser(description="Record one shell lifecycle scenario.")
    parser.add_argument(
        "scenario", choices=(*ALL_SCENARIOS, *RUN_HEALTH_SCENARIOS, "all")
    )
    parser.add_argument("--work-dir", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--fault", choices=FAULTS, default=None)
    parser.add_argument("--hang", choices=HANGS, default=None)
    parser.add_argument("--print-b64", action="store_true")
    parsed = parser.parse_args()
    if parsed.scenario == "all":
        import subprocess
        import zlib

        recorded: dict[str, Any] = {}
        for name in ALL_SCENARIOS:
            sub_dir = parsed.work_dir / name
            sub_out = sub_dir / "result.json"
            done = subprocess.run(
                [
                    sys.executable,
                    "-m",
                    "tests.shell.recorder",
                    name,
                    "--work-dir",
                    str(sub_dir),
                    "--out",
                    str(sub_out),
                ],
                capture_output=True,
                text=True,
                check=False,
                timeout=120,
            )
            if done.returncode != 0:
                raise SystemExit(
                    f"scenario {name} failed ({done.returncode}):\n"
                    f"STDOUT:\n{done.stdout[-2000:]}\nSTDERR:\n{done.stderr[-2000:]}"
                )
            recorded[name] = json.loads(sub_out.read_text(encoding="utf-8"))
        payload = json.dumps(recorded, indent=2) + "\n"
        parsed.out.parent.mkdir(parents=True, exist_ok=True)
        parsed.out.write_text(payload, encoding="utf-8")
        if parsed.print_b64:
            blob = base64.b64encode(zlib.compress(payload.encode("utf-8"), 9)).decode(
                "ascii"
            )
            print("SHELL_NET_B64_BEGIN")
            for i in range(0, len(blob), 100):
                print(blob[i : i + 100])
            print("SHELL_NET_B64_END")
        return
    result = run_scenario(
        parsed.scenario, parsed.work_dir, fault=parsed.fault, hang=parsed.hang
    )
    parsed.out.parent.mkdir(parents=True, exist_ok=True)
    parsed.out.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
