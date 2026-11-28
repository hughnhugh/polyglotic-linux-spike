"""The move proof (859's S0): a pure move passes, every planted edit fails."""

from __future__ import annotations

import ast
import subprocess
import sys
from pathlib import Path

import pytest
from tools.move_check import compare

from tools import move_check

BIG = '''\
"""The big module."""

from __future__ import annotations

from PySide6.QtCore import QCoreApplication

LIMIT = 40


def _tr(text: str) -> str:
    return QCoreApplication.translate("CaptionWindow", text)


def helper(value: int = 2) -> int:
    total = value + LIMIT
    return total + 1


class Window:
    """A window."""

    rows = 3

    def show(self) -> str:
        return _tr("Show")

    def hide(self) -> str:
        count = 7
        return _tr("Hide") * count
'''

# The pure move: helper, LIMIT and Window.hide go to a new module, with the
# same _tr wrapper, imports and a re-export left behind.
BIG_AFTER = '''\
"""The big module."""

from __future__ import annotations

from PySide6.QtCore import QCoreApplication

from .small import HideMixin, helper

__all__ = ["Window", "helper"]
helper_alias = helper


def _tr(text: str) -> str:
    return QCoreApplication.translate("CaptionWindow", text)


class Window(HideMixin):
    """A window."""

    rows = 3

    def show(self) -> str:
        return _tr("Show")
'''

SMALL = '''\
"""Moved out of big."""

from __future__ import annotations

from typing import TYPE_CHECKING

from PySide6.QtCore import QCoreApplication

if TYPE_CHECKING:
    from .big import Window

LIMIT = 40


def _tr(text: str) -> str:
    return QCoreApplication.translate("CaptionWindow", text)


def helper(value: int = 2) -> int:
    total = value + LIMIT
    return total + 1


class HideMixin:
    def hide(self) -> str:
        count = 7
        return _tr("Hide") * count
'''


def _check(small: str, big_after: str = BIG_AFTER) -> move_check.Result:
    return compare({"big.py": BIG}, {"big.py": big_after, "small.py": small})


def _reasons(result: move_check.Result) -> list[str]:
    return [f"{reason}: {unit.label}" for reason, unit in result.not_a_move]


def test_a_pure_move_passes() -> None:
    result = _check(SMALL)
    assert result.ok, _reasons(result)
    moved = {old.label for old, _new in result.moved}
    assert moved == {"helper", "Window.hide", "LIMIT = 40"}
    # The two class headers are listed for the reviewer, not failed.
    assert {unit.label for unit in result.structure} == {
        "class Window",
        "class HideMixin",
    }


PLANTED_FAULTS = [
    (
        "a changed constant inside a moved body",
        "count = 7",
        "count = 8",
        ["removed or changed: Window.hide", "added: HideMixin.hide"],
    ),
    (
        "a renamed local",
        "total = value + LIMIT\n    return total + 1",
        "result = value + LIMIT\n    return result + 1",
        ["removed or changed: helper", "added: helper"],
    ),
    (
        "a dropped method",
        (
            "class HideMixin:\n    def hide(self) -> str:\n"
            '        count = 7\n        return _tr("Hide") * count\n'
        ),
        "class HideMixin:\n    pass\n",
        ["removed or changed: Window.hide", "added: HideMixin.pass"],
    ),
    (
        "a _tr with a different context",
        'QCoreApplication.translate("CaptionWindow", text)',
        'QCoreApplication.translate("HideMixin", text)',
        ["wrapper differs from every base copy: _tr"],
    ),
    (
        "a changed module constant",
        "LIMIT = 40",
        "LIMIT = 41",
        ["removed or changed: LIMIT = 40", "added: LIMIT = 41"],
    ),
    (
        "a decorator added",
        "def helper(",
        "@staticmethod\ndef helper(",
        ["removed or changed: helper", "added: helper"],
    ),
]


@pytest.mark.parametrize(
    ("name", "old", "new", "expected"),
    PLANTED_FAULTS,
    ids=[case[0] for case in PLANTED_FAULTS],
)
def test_each_planted_fault_fails(
    name: str, old: str, new: str, expected: list[str]
) -> None:
    assert old in SMALL, name
    result = _check(SMALL.replace(old, new))
    assert not result.ok
    assert sorted(_reasons(result)) == sorted(expected)


def test_a_definition_copied_instead_of_moved_fails() -> None:
    kept = (
        BIG_AFTER
        + "\n\ndef helper(value: int = 2) -> int:\n    total = value + LIMIT\n    return total + 1\n"
    )
    result = _check(
        SMALL, big_after=kept.replace("from .small import HideMixin, helper\n", "")
    )
    assert "added: helper" in _reasons(result)


def test_new_code_beside_a_move_fails() -> None:
    result = _check(SMALL + "\n\ndef extra() -> None:\n    pass\n")
    assert _reasons(result) == ["added: extra"]


def test_a_method_dropped_from_a_class_moved_whole_fails() -> None:
    base = {
        "a.py": "class Panel:\n    def one(self):\n        return 1\n\n    def two(self):\n        return 2\n"
    }
    head = {"a.py": "", "b.py": "class Panel:\n    def one(self):\n        return 1\n"}
    result = compare(base, head)
    assert _reasons(result) == ["removed or changed: Panel.two"]


def test_unchanged_files_and_untouched_units_are_quiet() -> None:
    result = compare({"a.py": BIG}, {"a.py": BIG})
    assert result.ok
    assert not result.moved and not result.allowed and not result.structure


def test_the_tool_imports_only_the_standard_library() -> None:
    tree = ast.parse(Path(move_check.__file__).read_text(encoding="utf-8"))
    imported = {
        alias.name.split(".")[0]
        for node in ast.walk(tree)
        if isinstance(node, ast.Import)
        for alias in node.names
    } | {
        node.module.split(".")[0]
        for node in ast.walk(tree)
        if isinstance(node, ast.ImportFrom) and node.module and not node.level
    }
    assert imported <= set(sys.stdlib_module_names)


def _git(repo: Path, *args: str) -> None:
    subprocess.run(["git", "-C", str(repo), *args], check=True, capture_output=True)


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    _git(tmp_path, "init", "-q")
    _git(tmp_path, "config", "user.email", "test@example.invalid")
    _git(tmp_path, "config", "user.name", "Test")
    _git(tmp_path, "config", "commit.gpgsign", "false")
    (tmp_path / "big.py").write_text(BIG, encoding="utf-8")
    (tmp_path / "notes.md").write_text("plan\n", encoding="utf-8")
    _git(tmp_path, "add", ".")
    _git(tmp_path, "commit", "-qm", "base")
    return tmp_path


def _commit_move(repo: Path, small: str) -> None:
    (repo / "big.py").write_text(BIG_AFTER, encoding="utf-8")
    (repo / "small.py").write_text(small, encoding="utf-8")
    _git(repo, "add", ".")
    _git(repo, "commit", "-qm", "move")


def test_the_command_passes_a_pure_move_between_commits(
    repo: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    _commit_move(repo, SMALL)
    assert move_check.main(["HEAD~1", "HEAD", "--repo", str(repo)]) == 0
    out = capsys.readouterr().out
    assert out.startswith(
        "move check passed: 2 Python file(s), 3 unit(s) moved unchanged"
    )


def test_the_command_fails_a_planted_edit_and_names_it(
    repo: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    _commit_move(repo, SMALL.replace("count = 7", "count = 8"))
    assert move_check.main(["HEAD~1", "HEAD", "--repo", str(repo)]) == 1
    out = capsys.readouterr().out
    assert "removed or changed: big.py:" in out and "Window.hide" in out
    assert "added: small.py:" in out


def test_the_command_reads_the_working_tree_without_a_head(repo: Path) -> None:
    (repo / "big.py").write_text(BIG_AFTER, encoding="utf-8")
    (repo / "small.py").write_text(SMALL, encoding="utf-8")
    _git(repo, "add", "small.py")  # git diff BASE sees tracked files only
    assert move_check.main(["HEAD", "--repo", str(repo)]) == 0


def test_a_change_with_no_python_file_says_so(
    repo: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    (repo / "notes.md").write_text("plan, revised\n", encoding="utf-8")
    _git(repo, "commit", "-qam", "docs")
    assert move_check.main(["HEAD~1", "HEAD", "--repo", str(repo)]) == 0
    assert capsys.readouterr().out.strip() == "move check: no Python file changed"


def test_a_bad_revision_is_an_error_not_a_pass(repo: Path) -> None:
    assert move_check.main(["no-such-rev", "HEAD", "--repo", str(repo)]) == 2
