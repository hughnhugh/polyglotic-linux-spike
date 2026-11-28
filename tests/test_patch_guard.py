"""The patch guard (859's S3): today's patch sites pass, a facade patch fails."""

from __future__ import annotations

import ast
import sys
from collections.abc import Iterator
from importlib import import_module
from pathlib import Path

import pytest
from tests.facades import patch_guard
from tools.facades import SPLITS

TESTS = Path(__file__).parent

SITES = {
    # Today's sites (2026-11-27): main's and caption_window's are 859's 25 and 3, grown.
    "polyglotic_desktop.adapters.sqlite_learning.VERSION",
    "polyglotic_desktop.adapters.sqlite_learning._MIGRATIONS",
    "polyglotic_desktop.adapters.sqlite_learning.datetime",
    "polyglotic_desktop.connection.session.time",
    "polyglotic_desktop.main.DesktopApp",
    "polyglotic_desktop.main.FEED_KEYS",
    "polyglotic_desktop.main.JAPANESE_DICTIONARY",
    "polyglotic_desktop.main.QApplication",
    "polyglotic_desktop.main._open_url",
    "polyglotic_desktop.main._start_and_run",
    "polyglotic_desktop.main.installed",
    "polyglotic_desktop.main.learner_tools",
    "polyglotic_desktop.main.new_interface",
    "polyglotic_desktop.main.os_adapters",
    "polyglotic_desktop.main.release_notes",
    "polyglotic_desktop.main.run_installer_hooks",
    "polyglotic_desktop.main.sample_file",
    "polyglotic_desktop.main.session_reached",
    "polyglotic_desktop.main.start_interface_language",
    "polyglotic_desktop.main.tls_found",
    "polyglotic_desktop.ui.settings.default_caption_mode",
    "polyglotic_desktop.ui_next.caption_layout.readable_through",
    "polyglotic_desktop.ui_next.caption_layout.romaji",
    "polyglotic_desktop.ui_next.caption_window.QGuiApplication",
    "polyglotic_desktop.ui_next.caption_window._tr",
    "polyglotic_desktop.ui_next.caption_window.copies_exactly",
    "polyglotic_desktop.ui_next.caption_window.drum",
    "polyglotic_desktop.ui_next.caption_window.on_a_mac",
    "polyglotic_desktop.ui_next.caption_window.panel_picture",
    "polyglotic_desktop.ui_next.caption_window.reduced_motion",
    "polyglotic_desktop.ui_next.caption_window.shows",
    "polyglotic_desktop.ui_next.caption_window.time",
    "polyglotic_desktop.ui_next.caption_windows.stored_windows",
    "polyglotic_desktop.ui_next.caption_windows.time",
    "polyglotic_desktop.ui_next.home.QDate",
    "polyglotic_desktop.ui_next.home.QDateTime",
    "polyglotic_desktop.ui_next.home.on_linux",
    "polyglotic_desktop.ui_next.panels.RESPELLED_WORD_LIMIT",
    "polyglotic_desktop.ui_next.settings_page.ASK_FROM_LINES",
    "polyglotic_desktop.ui_next.settings_page.TRANSCRIPT_HOURS",
    "polyglotic_desktop.ui_next.settings_page.TRANSCRIPT_LINES",
}


def patch_sites(tests: Path = TESTS) -> Iterator[tuple[str, str, str]]:
    """(test file, module, name) for each `monkeypatch.setattr` on a split
    module, by alias (`setattr(main, "X", ...)`) or by string."""
    for path in sorted(tests.rglob("*.py")):
        tree = ast.parse(path.read_bytes(), filename=str(path))
        aliases: dict[str, str] = {}
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for item in node.names:
                    if item.name in SPLITS:
                        aliases[item.asname or item.name] = item.name
            elif isinstance(node, ast.ImportFrom) and node.module and not node.level:
                for item in node.names:
                    if f"{node.module}.{item.name}" in SPLITS:
                        aliases[item.asname or item.name] = f"{node.module}.{item.name}"
        for node in ast.walk(tree):
            if not (
                isinstance(node, ast.Call)
                and isinstance(node.func, ast.Attribute)
                and node.func.attr == "setattr"
                and node.args
            ):
                continue
            first = node.args[0]
            where = path.relative_to(tests).as_posix()
            if (
                isinstance(first, ast.Name)
                and first.id in aliases
                and len(node.args) > 1
                and isinstance(node.args[1], ast.Constant)
                and isinstance(node.args[1].value, str)
            ):
                yield where, aliases[first.id], node.args[1].value
            elif isinstance(first, ast.Constant) and isinstance(first.value, str):
                module, _, name = first.value.rpartition(".")
                if module in SPLITS:
                    yield where, module, name


def test_today_s_patch_sites_are_listed_and_pass() -> None:
    found = sorted(set(patch_sites()))
    problems = [
        f"{where}: {reason}"
        for where, module, name in found
        if (reason := patch_guard.problem(import_module(module), name, SPLITS))
    ]
    assert problems == []
    assert {f"{module}.{name}" for _where, module, name in found} == SITES


def test_the_guard_is_on_in_this_suite() -> None:
    assert hasattr(pytest.MonkeyPatch.setattr, "__wrapped__")


@pytest.fixture
def moved(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    """A fake move: `fakeguard.helper` went to `fakeguard.parts`; the facade
    only re-exports it, and the code that reads it moved too."""
    package = tmp_path / "fakeguard"
    package.mkdir()
    (package / "parts.py").write_text(
        "def helper():\n    return 1\n\n\ndef caller():\n    return helper()\n",
        encoding="utf-8",
    )
    (package / "__init__.py").write_text(
        "from .parts import caller, helper\n\nLIMIT = 3\n\n\ndef own():\n    return LIMIT\n",
        encoding="utf-8",
    )
    monkeypatch.syspath_prepend(str(tmp_path))
    yield
    for name in [name for name in sys.modules if name.split(".")[0] == "fakeguard"]:
        del sys.modules[name]


def test_a_planted_facade_patch_fails_naming_the_owner(moved: None) -> None:
    guarded = pytest.MonkeyPatch()
    guarded_setattr = patch_guard.guard({"fakeguard"})
    facade = import_module("fakeguard")
    try:
        with pytest.raises(
            patch_guard.FacadePatch, match="patch fakeguard.parts.helper instead"
        ):
            guarded_setattr(guarded, facade, "helper", lambda: 2)
        with pytest.raises(
            patch_guard.FacadePatch, match="patch fakeguard.parts.helper instead"
        ):
            guarded_setattr(guarded, "fakeguard.helper", lambda: 2)
        # The facade's own code reads LIMIT: patching it there still works.
        guarded_setattr(guarded, facade, "LIMIT", 4)
        assert facade.own() == 4
        # Patching the owner is the fix.
        guarded_setattr(guarded, import_module("fakeguard.parts"), "helper", lambda: 2)
        assert facade.caller() == 2
    finally:
        guarded.undo()
