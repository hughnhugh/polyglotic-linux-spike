"""Prove that a change between two commits only moves Python code.

``python -m tools.move_check BASE [HEAD] [--paths PATH ...]`` parses every
Python file the change touches, at both commits, and splits each file into
units: module-level statements, and for each class its header and its
members.  A unit that leaves its place must arrive somewhere else unchanged
(``ast.dump`` with no line numbers), once.  Anything else is listed as
"not a move" and the check fails.

Allowed without a match, because a move needs them:

* imports (also inside ``if TYPE_CHECKING:``), ``__all__`` and module
  docstrings;
* re-export lines (``name = other`` or ``name = module.attr``);
* a per-module ``_tr``/``_trn`` wrapper, only when it is identical to one the
  base already has, so a copy with a different translation context fails;
* class headers (name, bases, keywords, decorators), listed as "structure"
  for the reviewer; the base-class order is held by the MRO test.

The tool imports only the standard library, so the server can carry the same
file with a hash check.
"""

from __future__ import annotations

import argparse
import ast
import subprocess
import sys
from collections import Counter
from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field
from pathlib import Path

#: Wrapper names a moved module may copy unchanged from its source module.
TRANSLATION_WRAPPERS = frozenset({"_tr", "_trn"})


class MoveCheckError(ValueError):
    """The check could not run (a file failed to parse, git failed)."""


@dataclass(frozen=True)
class Unit:
    """One movable piece of a file."""

    path: str
    where: str  # "Class.member", "Class" (header) or "<module>"
    kind: str  # "def", "class", "header", "statement", "allowed", "wrapper"
    label: str
    dump: str
    line: int


@dataclass
class Result:
    """What a change did, unit by unit."""

    moved: list[tuple[Unit, Unit]] = field(default_factory=list)
    allowed: list[Unit] = field(default_factory=list)
    structure: list[Unit] = field(default_factory=list)
    not_a_move: list[tuple[str, Unit]] = field(default_factory=list)
    files: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.not_a_move


def _dump(node: ast.AST) -> str:
    return ast.dump(node, include_attributes=False)


def _is_docstring(node: ast.stmt) -> bool:
    return (
        isinstance(node, ast.Expr)
        and isinstance(node.value, ast.Constant)
        and isinstance(node.value.value, str)
    )


def _is_type_checking_imports(node: ast.stmt) -> bool:
    if not isinstance(node, ast.If) or node.orelse:
        return False
    test = node.test
    name = (
        test.id
        if isinstance(test, ast.Name)
        else test.attr
        if isinstance(test, ast.Attribute)
        else None
    )
    return name == "TYPE_CHECKING" and all(
        isinstance(stmt, (ast.Import, ast.ImportFrom)) for stmt in node.body
    )


def _is_reexport(node: ast.stmt) -> bool:
    if isinstance(node, ast.Assign):
        targets, value = node.targets, node.value
    elif isinstance(node, ast.AnnAssign) and node.value is not None:
        targets, value = [node.target], node.value
    else:
        return False
    if not all(isinstance(target, ast.Name) for target in targets):
        return False
    if any(isinstance(t, ast.Name) and t.id == "__all__" for t in targets):
        return True
    while isinstance(value, ast.Attribute):
        value = value.value
    return isinstance(value, ast.Name)


def _label(node: ast.stmt) -> str:
    if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
        return node.name
    text = ast.unparse(node).splitlines()[0] if node else ""
    return text if len(text) <= 70 else text[:67] + "..."


def _header(node: ast.ClassDef) -> str:
    shell = ast.ClassDef(
        name=node.name,
        bases=node.bases,
        keywords=node.keywords,
        body=[ast.Pass()],
        decorator_list=node.decorator_list,
        type_params=getattr(node, "type_params", []),
    )
    return _dump(shell)


def units(source: str, *, path: str) -> list[Unit]:
    """Split *source* into the units a move is checked by."""

    try:
        tree = ast.parse(source, filename=path)
    except SyntaxError as error:
        raise MoveCheckError(f"cannot parse {path}: {error}") from error
    found: list[Unit] = []
    for index, node in enumerate(tree.body):
        if isinstance(node, ast.ClassDef):
            found.append(
                Unit(
                    path,
                    node.name,
                    "header",
                    f"class {node.name}",
                    _header(node),
                    node.lineno,
                )
            )
            for member in node.body:
                where = f"{node.name}.{_label(member)}"
                kind = (
                    "def"
                    if isinstance(
                        member, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)
                    )
                    else "statement"
                )
                found.append(
                    Unit(path, where, kind, where, _dump(member), member.lineno)
                )
            continue
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            kind = "wrapper" if node.name in TRANSLATION_WRAPPERS else "def"
            found.append(
                Unit(path, node.name, kind, node.name, _dump(node), node.lineno)
            )
            continue
        allowed = (
            isinstance(node, (ast.Import, ast.ImportFrom))
            or _is_type_checking_imports(node)
            or (index == 0 and _is_docstring(node))
            or _is_reexport(node)
        )
        found.append(
            Unit(
                path,
                "<module>",
                "allowed" if allowed else "statement",
                _label(node),
                _dump(node),
                node.lineno,
            )
        )
    return found


def _key(unit: Unit) -> tuple[str, str, str]:
    return (unit.path, unit.where, unit.dump)


def _subtract(left: list[Unit], right: list[Unit]) -> list[Unit]:
    """Units of *left* with no identical unit at the same place in *right*."""

    remaining = Counter(_key(unit) for unit in right)
    out: list[Unit] = []
    for unit in left:
        key = _key(unit)
        if remaining[key]:
            remaining[key] -= 1
        else:
            out.append(unit)
    return out


def compare(base_files: dict[str, str], head_files: dict[str, str]) -> Result:
    """Compare files at two commits.  A missing file is an empty string."""

    result = Result(files=sorted(set(base_files) | set(head_files)))
    before: list[Unit] = []
    after: list[Unit] = []
    for path in result.files:
        before.extend(units(base_files.get(path, ""), path=path))
        after.extend(units(head_files.get(path, ""), path=path))
    removed = _subtract(before, after)
    added = _subtract(after, before)
    base_wrappers = {unit.dump for unit in before if unit.kind == "wrapper"}

    arrivals: dict[str, list[Unit]] = {}
    for unit in added:
        if unit.kind not in ("allowed", "header"):
            arrivals.setdefault(unit.dump, []).append(unit)
    for unit in removed:
        if unit.kind in ("allowed", "header"):
            (result.allowed if unit.kind == "allowed" else result.structure).append(
                unit
            )
            continue
        candidates = arrivals.get(unit.dump)
        if candidates:
            result.moved.append((unit, candidates.pop(0)))
        else:
            result.not_a_move.append(("removed or changed", unit))
    for unit in added:
        if unit.kind == "allowed":
            result.allowed.append(unit)
        elif unit.kind == "header":
            result.structure.append(unit)
    for left in arrivals.values():
        for unit in left:
            if unit.kind == "wrapper" and unit.dump in base_wrappers:
                result.allowed.append(unit)
            elif unit.kind == "wrapper":
                result.not_a_move.append(("wrapper differs from every base copy", unit))
            else:
                result.not_a_move.append(("added", unit))
    return result


def _git(repo: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", "-C", str(repo), *args],
        check=False,
        capture_output=True,
        text=True,
        encoding="utf-8",
    )


def _changed_paths(
    repo: Path, base: str, head: str | None, paths: Sequence[str]
) -> list[str]:
    revs = [base] if head is None else [base, head]
    result = _git(
        repo, "diff", "--name-only", "--no-renames", *revs, "--", *(paths or ["."])
    )
    if result.returncode:
        raise MoveCheckError(f"git diff failed: {result.stderr.strip()}")
    return sorted(line for line in result.stdout.splitlines() if line.endswith(".py"))


def _read(repo: Path, rev: str | None, path: str) -> str:
    if rev is None:
        file = repo / path
        return file.read_text(encoding="utf-8") if file.exists() else ""
    result = _git(repo, "cat-file", "-e", f"{rev}:{path}")
    if result.returncode:
        return ""
    shown = _git(repo, "show", f"{rev}:{path}")
    if shown.returncode:
        raise MoveCheckError(f"cannot read {path} at {rev}: {shown.stderr.strip()}")
    return shown.stdout


def check(
    *, repo: Path, base: str, head: str | None, paths: Sequence[str] = ()
) -> Result:
    """Check the change from *base* to *head* (the working tree when None)."""

    changed = _changed_paths(repo, base, head, paths)
    base_files = {path: _read(repo, base, path) for path in changed}
    head_files = {path: _read(repo, head, path) for path in changed}
    return compare(base_files, head_files)


def _where(unit: Unit) -> str:
    return f"{unit.path}:{unit.line} {unit.label}"


def report(result: Result) -> Iterable[str]:
    """Lines describing *result*, failures first."""

    if not result.files:
        yield "move check: no Python file changed"
        return
    verdict = "passed" if result.ok else "failed"
    yield (
        f"move check {verdict}: {len(result.files)} Python file(s), "
        f"{len(result.moved)} unit(s) moved unchanged, "
        f"{len(result.not_a_move)} not a move"
    )
    if result.not_a_move:
        yield "not a move:"
        for reason, unit in result.not_a_move:
            yield f"  {reason}: {_where(unit)}"
    if result.structure:
        yield "structure (class headers, read these):"
        for unit in result.structure:
            yield f"  {_where(unit)}"
    if result.moved:
        yield "moved:"
        for old, new in result.moved:
            yield f"  {old.label}: {old.path}:{old.line} -> {new.path}:{new.line}"
    if result.allowed:
        yield f"allowed (imports, __all__, re-exports, docstrings, wrappers): {len(result.allowed)}"


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Prove that a change between two commits only moves Python code."
    )
    parser.add_argument("base", help="Git revision before the move")
    parser.add_argument(
        "head",
        nargs="?",
        default=None,
        help="Git revision after it (default: the working tree)",
    )
    parser.add_argument("--paths", nargs="+", default=[], help="limit to these paths")
    parser.add_argument("--repo", type=Path, default=Path.cwd(), help="the repository")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        result = check(repo=args.repo, base=args.base, head=args.head, paths=args.paths)
    except MoveCheckError as error:
        print(f"move check could not run: {error}", file=sys.stderr)
        return 2
    for line in report(result):
        print(line)
    return 0 if result.ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
