"""The fourteen split modules keep every old import (859's S1).

`tests/facades/<module>.txt` lists each name that `src`, `tests` and `tools`
import from a module R1 splits, with the module that owns it. After a move
the old path must still give **the same object** as its owner: a wrapper
(`def X(*a): return new.X(*a)`) imports fine and breaks identity, patches
and `isinstance`. And no module inside a split package may import its own
facade, or the facade becomes a cycle the split can't remove.
`python -m tools.facades --update` accepts a change.
"""

from __future__ import annotations

import sys
from collections.abc import Iterator
from importlib import import_module
from pathlib import Path

import pytest
from tools.facades import SPLITS, Export, FacadeError, check_identity

from tools import facades

ROOT = Path(__file__).parents[1]
FOLDER = ROOT / "tests" / "facades"


def recorded(module: str) -> list[tuple[str, Export]]:
    path = facades.snapshot_path(FOLDER, module)
    rows = []
    for line in path.read_text(encoding="utf-8").splitlines():
        name, owner, owner_name = line.split("\t")
        rows.append((name, Export(owner, owner_name)))
    return rows


def test_the_recorded_imports_are_today_s() -> None:
    changes = facades.check_snapshots(ROOT)
    assert not changes, (
        "\n".join(changes) + "\nIf meant: python -m tools.facades --update"
    )


@pytest.mark.parametrize("module", sorted(SPLITS))
def test_each_old_import_is_its_owner_s_own_object(module: str) -> None:
    old = import_module(module)
    problems = []
    for name, owner in recorded(module):
        try:
            check_identity(old, name, owner)
        except FacadeError as error:
            problems.append(str(error))
    assert problems == []


def test_no_split_package_imports_its_own_facade() -> None:
    source = ROOT / "src"
    problems = [
        problem
        for facade, split in SPLITS.items()
        for problem in facades.internal_facade_imports(source, facade, split)
    ]
    assert problems == []


@pytest.fixture
def moved(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[Path]:
    """A fake split: `fakesplit` is the facade, `fakesplit.parts` the owner."""
    package = tmp_path / "fakesplit"
    package.mkdir()
    (package / "parts.py").write_text(
        "def helper(x):\n    return x + 1\n", encoding="utf-8"
    )
    (package / "__init__.py").write_text(
        "from .parts import helper\n", encoding="utf-8"
    )
    monkeypatch.syspath_prepend(str(tmp_path))
    yield package
    for name in [name for name in sys.modules if name.split(".")[0] == "fakesplit"]:
        del sys.modules[name]


def test_a_re_export_keeps_identity(moved: Path) -> None:
    check_identity(
        import_module("fakesplit"), "helper", Export("fakesplit.parts", "helper")
    )


def test_a_planted_wrapper_fails_identity(moved: Path) -> None:
    (moved / "__init__.py").write_text(
        "from . import parts\n\n\ndef helper(*a):\n    return parts.helper(*a)\n",
        encoding="utf-8",
    )
    with pytest.raises(FacadeError, match="fakesplit.helper is not the same object"):
        check_identity(
            import_module("fakesplit"), "helper", Export("fakesplit.parts", "helper")
        )


def test_a_planted_internal_facade_import_fails(moved: Path) -> None:
    (moved / "drawing.py").write_text(
        "from fakesplit import helper\n", encoding="utf-8"
    )
    (moved / "timing.py").write_text("import fakesplit\n", encoding="utf-8")
    problems = list(
        facades.internal_facade_imports(moved.parent, "fakesplit", "fakesplit")
    )
    assert sorted(problems) == [
        "fakesplit/drawing.py:1: imports facade fakesplit (from fakesplit import helper)",
        "fakesplit/timing.py:1: imports facade fakesplit (import fakesplit)",
    ]
