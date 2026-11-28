"""The patch guard (859's S3): a patch on a facade that its code no longer reads fails.

`monkeypatch.setattr(main, "X", fake)` works today because `main`'s own code
looks `X` up in `main`'s globals. Once the code that reads `X` moves to
another module, the patch still "succeeds" but changes nothing, and the test
goes on passing without testing anything. So on the fourteen split modules
(`tools.facades.SPLITS`), a patch fails when the module's own source never
reads the name and the value belongs to another module (defined there, or
imported from there); the failure names the owner to patch instead.
"""

from __future__ import annotations

import ast
from collections.abc import Callable, Collection
from functools import cache
from importlib import import_module
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest
from tools.facades import SPLITS, export_owner


class FacadePatch(AssertionError):
    """A patch on a facade that the facade's own code doesn't read."""


@cache
def _reads(filename: str) -> frozenset[str]:
    """Names the module's own code reads (not its import lines)."""
    tree = ast.parse(Path(filename).read_bytes(), filename=filename)
    return frozenset(
        node.id
        for node in ast.walk(tree)
        if isinstance(node, ast.Name) and isinstance(node.ctx, ast.Load)
    )


def problem(module: ModuleType, name: str, guarded: Collection[str]) -> str | None:
    """Why patching `module.name` would be a facade patch, or None."""
    if module.__name__ not in guarded or not hasattr(module, name):
        return None
    filename = getattr(module, "__file__", None)
    if not filename or not filename.endswith(".py"):
        return None
    if name in _reads(filename):
        return None
    owner = export_owner(module, name, getattr(module, name))
    if owner.module == module.__name__:
        return None
    return (
        f"{module.__name__}.{name} is a re-export its own code doesn't read:"
        f" patch {owner.path} instead"
    )


def guard(guarded: Collection[str]) -> Callable[..., Any]:
    """A replacement for `MonkeyPatch.setattr` that checks `guarded` modules."""
    original = pytest.MonkeyPatch.setattr

    def setattr(
        self: pytest.MonkeyPatch, target: object, *args: Any, **kwargs: Any
    ) -> Any:
        if isinstance(target, str):
            if "." in target:
                module_name, _, name = target.rpartition(".")
                try:
                    module: object = import_module(module_name)
                except ImportError:
                    module = None
                if isinstance(module, ModuleType) and (
                    reason := problem(module, name, guarded)
                ):
                    raise FacadePatch(reason)
        elif (
            isinstance(target, ModuleType)
            and args
            and isinstance(args[0], str)
            and (reason := problem(target, args[0], guarded))
        ):
            raise FacadePatch(reason)
        return original(self, target, *args, **kwargs)

    setattr.__wrapped__ = original  # type: ignore[attr-defined]
    return setattr


@pytest.hookimpl(tryfirst=True)
def pytest_configure(config: pytest.Config) -> None:
    if not hasattr(pytest.MonkeyPatch.setattr, "__wrapped__"):
        pytest.MonkeyPatch.setattr = guard(SPLITS)  # type: ignore[method-assign]
