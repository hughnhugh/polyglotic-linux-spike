"""Record the old imports and their owners for the fourteen planned R1 splits.

Run `uv run python -m tools.facades` to check, or add `--update` to regenerate
the snapshots after an intentional change to an import or an owner.
"""

from __future__ import annotations

import argparse
import ast
from collections import defaultdict
from collections.abc import Iterable, Iterator
from dataclasses import dataclass
from difflib import unified_diff
from functools import cache
from importlib import import_module
from importlib.util import resolve_name
from pathlib import Path
from types import ModuleType

ROOT = Path(__file__).resolve().parents[1]
SPLITS = {
    "polyglotic_desktop.main": "polyglotic_desktop.main",
    "polyglotic_desktop.ui_next.caption_window": "polyglotic_desktop.ui_next.caption",
    "polyglotic_desktop.ui_next.caption_layout": "polyglotic_desktop.ui_next.layout",
    "polyglotic_desktop.ui_next.caption_windows": "polyglotic_desktop.ui_next.caption_windows",
    "polyglotic_desktop.ui_next.home": "polyglotic_desktop.ui_next.home",
    "polyglotic_desktop.ui_next.transcript_window": "polyglotic_desktop.ui_next.transcript",
    "polyglotic_desktop.ui_next.lookup_card": "polyglotic_desktop.ui_next.lookup",
    "polyglotic_desktop.ui_next.panels": "polyglotic_desktop.ui_next.panels",
    "polyglotic_desktop.ui_next.video": "polyglotic_desktop.ui_next.video",
    "polyglotic_desktop.ui_next.settings_page": "polyglotic_desktop.ui_next.settings",
    "polyglotic_desktop.ui.settings": "polyglotic_desktop.ui.settings",
    "polyglotic_desktop.core.learning.vocabulary": "polyglotic_desktop.core.learning.vocabulary",
    "polyglotic_desktop.adapters.sqlite_learning": "polyglotic_desktop.adapters.sqlite_learning",
    "polyglotic_desktop.connection.session": "polyglotic_desktop.connection.session",
}


@dataclass(frozen=True)
class Export:
    module: str
    name: str

    @property
    def path(self) -> str:
        return f"{self.module}.{self.name}"


class FacadeError(ValueError):
    """An old import or a recorded owner could not be resolved."""


def python_files(folder: Path) -> Iterator[Path]:
    yield from sorted(folder.rglob("*.py"))


def parse(path: Path) -> ast.Module:
    return ast.parse(path.read_bytes(), filename=str(path))


def module_path(root: Path, module: str) -> Path:
    return root.joinpath(*module.split("."))


def package_at(root: Path, path: Path) -> str:
    return ".".join(path.relative_to(root).parts[:-1])


def from_module(node: ast.ImportFrom, package: str) -> str:
    if node.level:
        return resolve_name("." * node.level + (node.module or ""), package)
    return node.module or ""


@cache
def source_bindings(path: Path, package: str) -> tuple[set[str], dict[str, Export]]:
    """Read names used by the implementation and the sources of imported bindings."""
    tree = parse(path)
    reads = {
        node.id
        for node in ast.walk(tree)
        if isinstance(node, ast.Name) and isinstance(node.ctx, ast.Load)
    }
    imports: dict[str, Export] = {}
    for node in tree.body:
        if isinstance(node, ast.ImportFrom):
            origin = from_module(node, package)
            imports.update(
                (item.asname or item.name, Export(origin, item.name))
                for item in node.names
            )
    return reads, imports


def export_owner(module: ModuleType, name: str, obj: object) -> Export:
    """Locate the same object at its defining module, including aliased imports."""
    module_name = module.__name__
    filename = getattr(module, "__file__", None)
    if filename and filename.endswith(".py") and Path(filename).is_file():
        _, imports = source_bindings(Path(filename), module.__package__ or "")
    else:
        imports = {}

    declared = getattr(obj, "__module__", None)
    if isinstance(declared, str) and declared != module_name:
        owner = import_module(declared)
        for candidate in (name, getattr(obj, "__name__", name)):
            if getattr(owner, candidate, object()) is obj:
                return Export(declared, candidate)

    origin = imports.get(name)
    if origin and getattr(import_module(origin.module), origin.name, object()) is obj:
        return origin
    return Export(module_name, name)


def dotted_name(node: ast.expr) -> str:
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        owner = dotted_name(node.value)
        if owner:
            return f"{owner}.{node.attr}"
    return ""


def imported_names(root: Path, modules: Iterable[str]) -> dict[str, set[str]]:
    """Find from-imports, members of imported module aliases and dotted patches."""
    names: dict[str, set[str]] = {module: set() for module in modules}
    for folder in (root / "src", root / "tests", root / "tools"):
        import_root = folder if folder.name == "src" else root
        for path in python_files(folder):
            aliases: dict[str, set[str]] = defaultdict(set)
            nodes = list(ast.walk(parse(path)))
            for node in nodes:
                if isinstance(node, ast.Import):
                    for item in node.names:
                        if item.name in names:
                            aliases[item.asname or item.name].add(item.name)
                elif isinstance(node, ast.ImportFrom):
                    parent = from_module(node, package_at(import_root, path))
                    for item in node.names:
                        if parent in names:
                            names[parent].add(item.name)
                        full_name = f"{parent}.{item.name}"
                        if full_name in names:
                            aliases[item.asname or item.name].add(full_name)
            for node in nodes:
                if isinstance(node, ast.Attribute):
                    for module in aliases.get(dotted_name(node.value), ()):
                        names[module].add(node.attr)
                elif (
                    isinstance(node, ast.Call)
                    and isinstance(node.func, ast.Attribute)
                    and node.func.attr == "setattr"
                    and node.args
                    and isinstance(node.args[0], ast.Constant)
                    and isinstance(node.args[0].value, str)
                ):
                    module, _, name = node.args[0].value.rpartition(".")
                    if module in names:
                        names[module].add(name)
    return names


def snapshot_path(folder: Path, module: str) -> Path:
    return folder / f"{module.rsplit('.', 1)[-1]}.txt"


def snapshot(module: str, names: set[str]) -> str:
    old = import_module(module)
    if "*" in names:
        names = (names - {"*"}) | set(
            getattr(
                old, "__all__", [name for name in vars(old) if not name.startswith("_")]
            )
        )
    lines = []
    for name in sorted(names):
        try:
            obj = getattr(old, name)
        except AttributeError:
            # An attribute read on a local that shares the module's alias
            # (`settings.update(...)` on a Settings object); a from-import of
            # a missing name already fails at import.
            continue
        owner = export_owner(old, name, obj)
        lines.append(f"{name}\t{owner.module}\t{owner.name}\n")
    return "".join(lines)


def check_identity(old: ModuleType, name: str, owner: Export) -> None:
    old_path = f"{old.__name__}.{name}"
    try:
        obj = getattr(old, name)
    except AttributeError as error:
        raise FacadeError(f"Missing facade export {old_path}") from error
    try:
        original = getattr(import_module(owner.module), owner.name)
    except (ImportError, AttributeError) as error:
        raise FacadeError(
            f"Missing recorded owner {owner.path} for {old_path}"
        ) from error
    if obj is not original:
        raise FacadeError(f"{old_path} is not the same object as {owner.path}")


def check_snapshots(root: Path, *, update: bool = False) -> list[str]:
    folder = root / "tests" / "facades"
    changes = []
    for module, names in imported_names(root, SPLITS).items():
        path = snapshot_path(folder, module)
        actual = snapshot(module, names)
        if update:
            path.write_text(actual, encoding="utf-8", newline="\n")
        elif not path.is_file():
            changes.append(f"Missing snapshot {path.name} for {module}")
        else:
            previous = path.read_text(encoding="utf-8")
            if previous != actual:
                changes.append(
                    "\n".join(
                        unified_diff(
                            previous.splitlines(),
                            actual.splitlines(),
                            fromfile=f"recorded {path.name}",
                            tofile=f"current {path.name}",
                            lineterm="",
                        )
                    )
                )
    return changes


def internal_facade_imports(source: Path, facade: str, split: str) -> Iterator[str]:
    """A split's implementations can import each other directly."""
    split_path = module_path(source, split)
    for path in python_files(split_path):
        if facade == split and path == split_path / "__init__.py":
            continue
        package = package_at(source, path)
        for node in ast.walk(parse(path)):
            if isinstance(node, ast.Import):
                bad = any(item.name == facade for item in node.names)
            elif isinstance(node, ast.ImportFrom):
                parent = from_module(node, package)
                bad = any(
                    f"{parent}.{item.name}" == facade
                    or (
                        parent == facade
                        and not (split_path / f"{item.name}.py").is_file()
                        and not (split_path / item.name / "__init__.py").is_file()
                    )
                    for item in node.names
                )
            else:
                continue
            if bad:
                yield f"{path.relative_to(source).as_posix()}:{node.lineno}: imports facade {facade} ({ast.unparse(node)})"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--update", action="store_true", help="rewrite snapshots")
    args = parser.parse_args()
    try:
        changes = check_snapshots(ROOT, update=args.update)
    except FacadeError as error:
        parser.exit(1, f"{error}\n")
    if changes:
        print("\n".join(changes))
        parser.exit(
            1, "Review the changes, then run python -m tools.facades --update.\n"
        )
    action = "Updated" if args.update else "Checked"
    print(f"{action} {len(SPLITS)} facade snapshots.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
