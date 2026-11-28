"""Regenerate the main startup snapshot with ``--update --reason '...'``."""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path

from tools import qt_lock

MAIN = "polyglotic_desktop.main"
SNAPSHOT = (
    Path(__file__).resolve().parents[1] / "tests" / "facades" / "imports-main.txt"
)
PROBE_TIMEOUT_SECONDS = 120  # Allow for a cold runner, but bound a stuck import.
# Loaded by the interpreter or the environment at its start, not by main
# (GitHub's Linux image has a sitecustomize; setuptools' .pth adds the hack).
INTERPRETER_START = frozenset({"sitecustomize", "usercustomize", "_distutils_hack"})
PROBE = """
import sys

sys.path[:0] = sys.argv[2:]
__import__(sys.argv[1])
loaded = sorted(name for name, module in sys.modules.items() if module is not None)

import json

print(json.dumps(loaded))
"""


def loaded_modules(module: str = MAIN, import_path: Path | None = None) -> set[str]:
    """Import an entry point in isolation from pytest and the caller's environment."""
    command = [sys.executable, "-I", "-", module]
    if import_path is not None:
        command.append(str(import_path))
    done = subprocess.run(
        command,
        input=PROBE,
        check=False,
        capture_output=True,
        text=True,
        timeout=PROBE_TIMEOUT_SECONDS,
    )
    if done.returncode:
        raise RuntimeError(f"Importing {module} failed\n{done.stderr}")
    return set(json.loads(done.stdout))


def snapshot_modules(loaded: set[str]) -> set[str]:
    """Record every app module and the top-level names of its dependencies."""
    modules = set()
    for name in loaded:
        root = name.partition(".")[0]
        if root == "polyglotic_desktop":
            modules.add(name)
        elif (
            root not in sys.stdlib_module_names
            and root != "__main__"
            and root not in INTERPRETER_START
        ):
            modules.add(root)
    return modules


def read_snapshot() -> set[str]:
    return {
        line
        for line in SNAPSHOT.read_text(encoding="utf-8").splitlines()
        if line and not line.startswith("#")
    }


def import_diff(expected: set[str], actual: set[str]) -> str:
    lines = []
    if added := sorted(actual - expected):
        lines.extend(["Added modules", *(f"  + {name}" for name in added)])
    if removed := sorted(expected - actual):
        lines.extend(["Removed modules", *(f"  - {name}" for name in removed)])
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--update", action="store_true", required=True)
    parser.add_argument("--reason", required=True, help="why the import set changed")
    args = parser.parse_args()
    reason = " ".join(args.reason.split())
    if not reason:
        parser.error("--reason must describe the change")

    with qt_lock.held("Startup import snapshot"):
        modules = snapshot_modules(loaded_modules())
    SNAPSHOT.parent.mkdir(parents=True, exist_ok=True)
    SNAPSHOT.write_text(
        "\n".join(
            [
                '# Regenerate with python -m tools.import_set --update --reason "..."',
                f"# Reason: {reason}",
                *sorted(modules),
                "",
            ]
        ),
        encoding="utf-8",
        newline="\n",
    )
    print(f"Recorded {len(modules)} startup imports in {SNAPSHOT.name}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
