"""The split classes keep their method order (859's S7).

Splitting a class into mixins changes its `__mro__`: a mixin listed in the
wrong place shadows a method, and a mixin with its own `__init__`, its own
`super().__init__` or its own `.connect(` wiring splits one start-up into
several. This holds today's `__mro__` of the eight classes R1 cuts and, by
AST, keeps mixin modules free of those three.
"""

from __future__ import annotations

import ast
from importlib import import_module
from pathlib import Path

import pytest

SRC = Path(__file__).parents[1] / "src"

MRO = {
    "polyglotic_desktop.ui_next.caption_window.Canvas": [
        "Canvas",
        "CaptionSurface",
        "QWidget",
        "QObject",
        "QPaintDevice",
        "Object",
        "object",
    ],
    "polyglotic_desktop.ui_next.caption_window.CaptionWindow": [
        "CaptionWindow",
        "CaptionTopLevel",
        "QWidget",
        "QObject",
        "QPaintDevice",
        "Object",
        "object",
    ],
    "polyglotic_desktop.ui_next.caption_windows.CaptionWindows": [
        "CaptionWindows",
        "QObject",
        "Object",
        "object",
    ],
    "polyglotic_desktop.ui_next.caption_layout.CaptionLayout": [
        "CaptionLayout",
        "object",
    ],
    "polyglotic_desktop.ui_next.lookup_card.LookupCard": [
        "LookupCard",
        "QWidget",
        "QObject",
        "QPaintDevice",
        "Object",
        "object",
    ],
    "polyglotic_desktop.ui_next.settings_page.SettingsPage": [
        "SettingsPage",
        "Page",
        "QScrollArea",
        "QAbstractScrollArea",
        "QFrame",
        "QWidget",
        "QObject",
        "QPaintDevice",
        "Object",
        "object",
    ],
    "polyglotic_desktop.core.learning.vocabulary.Vocabulary": ["Vocabulary", "object"],
    "polyglotic_desktop.connection.session.ListeningSession": [
        "ListeningSession",
        "object",
    ],
}
"""Today's `__mro__` names. A split that adds mixins adds them here, in order."""


def _class(path: str) -> type:
    module, _, name = path.rpartition(".")
    found = getattr(import_module(module), name)
    assert isinstance(found, type)
    return found


@pytest.mark.parametrize("path", sorted(MRO))
def test_each_split_class_keeps_its_method_order(path: str) -> None:
    assert [each.__name__ for each in _class(path).__mro__] == MRO[path]


def mixin_problems(source: str, filename: str) -> list[str]:
    """What a mixin module does that only the class it joins may do."""
    problems: list[str] = []
    for node in ast.walk(ast.parse(source, filename=filename)):
        if (
            isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef)
            and node.name == "__init__"
        ):
            problems.append(f"{filename}:{node.lineno}: defines __init__")
        elif isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
            if node.func.attr == "connect":
                problems.append(f"{filename}:{node.lineno}: calls .connect(")
            elif (
                node.func.attr == "__init__"
                and isinstance(node.func.value, ast.Call)
                and isinstance(node.func.value.func, ast.Name)
                and node.func.value.func.id == "super"
            ):
                problems.append(f"{filename}:{node.lineno}: calls super().__init__")
    return problems


def mixin_modules(src: Path = SRC) -> list[Path]:
    """Modules that hold mixins: any module defining a class named `*Mixin`,
    or any module in a mixins package (`.../mixins/`)."""
    found = []
    for path in sorted(src.rglob("*.py")):
        if "mixins" in path.parts:
            found.append(path)
            continue
        tree = ast.parse(path.read_bytes(), filename=str(path))
        if any(
            isinstance(node, ast.ClassDef) and node.name.endswith("Mixin")
            for node in tree.body
        ):
            found.append(path)
    return found


def test_no_mixin_starts_or_wires_itself() -> None:
    problems = [
        problem
        for path in mixin_modules()
        for problem in mixin_problems(
            path.read_text(encoding="utf-8"), path.relative_to(SRC).as_posix()
        )
    ]
    assert problems == []


def test_a_planted_mixin_init_fails(tmp_path: Path) -> None:
    package = tmp_path / "polyglotic_desktop" / "ui_next" / "caption" / "mixins"
    package.mkdir(parents=True)
    (package / "drawing.py").write_text(
        "class DrawingMixin:\n"
        "    def __init__(self):\n"
        "        super().__init__()\n"
        "        self.changed.connect(self.update)\n",
        encoding="utf-8",
    )
    paths = mixin_modules(tmp_path)
    assert [path.name for path in paths] == ["drawing.py"]
    problems = mixin_problems(paths[0].read_text(encoding="utf-8"), "drawing.py")
    assert sorted(problems) == [
        "drawing.py:2: defines __init__",
        "drawing.py:3: calls super().__init__",
        "drawing.py:4: calls .connect(",
    ]
