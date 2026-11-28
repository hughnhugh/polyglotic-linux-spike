"""Compare two settings sweeps (859's N6, S6 b).

    python -m tools.sweep_diff BASE/sweep.json HEAD/sweep.json [--ignore PATH]

`tools.macos_settings_sweep OUT` writes `OUT/sweep.json`: every control it
changed and put back, with what each did to the stored settings. Run it at
the base and at the head of a refactor, the same way, and this lists by JSON
path each change whose stored settings, effect, error boxes or notes differ.
Changes are compared per section (`PER_SECTION` says why), so one
extra change does not shift every later one. A setting a control no longer
puts back shows in its section's `stored`. Exit 0 when the
sweeps agree, 1 when they differ, 2 when an input can't be read.
"""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Mapping
from pathlib import Path

MISSING = object()

VOLATILE = {
    "seconds": "how long each part took: differs every run",
    "log": "log lines carry timestamps",
    "picture": "a file name; the pictures themselves are the UI lab's to judge",
}
"""Fields of a sweep, or of each of its changes, no refactor is judged by."""


PER_SECTION = ("stored", "effect")
"""What each change did, compared per section (`where`), not per control.
A settings save is debounced: run to run it can land in the next control's
record, and a slider's intermediate values differ (two runs at one commit
on 2026-11-27 moved 26 deltas between neighbours, e.g. `show_mic` from
"combo Microphone" to "toggle Show my speech", and caught different
opacities on the way). So each section is compared by its net effect per
setting: the value before its first change and after its last. A setting a
control no longer puts back shows there."""


def _flat(value: object, path: str, into: dict[str, list[object]]) -> None:
    if isinstance(value, Mapping) and value:
        for key, child in value.items():
            _flat(child, f"{path}.{key}" if path else str(key), into)
    elif path:
        into.setdefault(path, []).append(value)


def _net(values: list[object]) -> object:
    """[before, after] pairs to the first before and the last after; else the last."""
    if all(isinstance(v, list) and len(v) == 2 for v in values):
        first, last = values[0], values[-1]
        assert isinstance(first, list) and isinstance(last, list)
        return [first[0], last[1]]
    return values[-1]


def comparable(sweep: Mapping[str, object]) -> dict[str, object]:
    """The sweep by section, without `VOLATILE`: each section's controls in
    order, its error boxes, and per setting the deltas its controls made."""
    out: dict[str, object] = {
        key: value
        for key, value in sweep.items()
        if key not in VOLATILE and key != "changes"
    }
    sections: dict[str, dict[str, object]] = {}
    raw = sweep.get("changes", [])
    for change in raw if isinstance(raw, list) else []:
        if not isinstance(change, Mapping):
            continue
        section = sections.setdefault(
            str(change.get("where", "?")),
            {"controls": [], "error_boxes": [], **{k: {} for k in PER_SECTION}},
        )
        section["controls"].append(change.get("what", "?"))  # type: ignore[attr-defined]
        section["error_boxes"].extend(change.get("error_boxes") or [])  # type: ignore[attr-defined]
        for kind in PER_SECTION:
            _flat(change.get(kind, {}), "", section[kind])  # type: ignore[arg-type]
    for section in sections.values():
        for kind in PER_SECTION:
            deltas = section[kind]
            assert isinstance(deltas, dict)
            section[kind] = {key: _net(values) for key, values in deltas.items()}
    out["sections"] = sections
    return out


def differences(
    before: object, after: object, ignored: frozenset[str] = frozenset()
) -> list[tuple[str, object, object]]:
    """Changed leaves as `(JSON path, before, after)`."""
    found: list[tuple[str, object, object]] = []

    def walk(left: object, right: object, path: str) -> None:
        if path in ignored:
            return
        if isinstance(left, dict) and isinstance(right, dict):
            for key in sorted(left.keys() | right.keys(), key=str):
                child = f"{path}.{key}" if path else str(key)
                walk(left.get(key, MISSING), right.get(key, MISSING), child)
        elif isinstance(left, list) and isinstance(right, list):
            for index in range(max(len(left), len(right))):
                walk(
                    left[index] if index < len(left) else MISSING,
                    right[index] if index < len(right) else MISSING,
                    f"{path}[{index}]",
                )
        elif left != right or isinstance(left, bool) != isinstance(right, bool):
            found.append((path or "$", left, right))

    walk(before, after, "")
    return found


def read_sweep(path: Path) -> dict[str, object]:
    sweep = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(sweep, dict) or not isinstance(sweep.get("changes"), list):
        raise TypeError(f"{path} is not a sweep.json (no list of changes)")
    return sweep


def _shown(value: object) -> str:
    return "<missing>" if value is MISSING else json.dumps(value, ensure_ascii=False)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("before", type=Path)
    parser.add_argument("after", type=Path)
    parser.add_argument(
        "--ignore",
        action="append",
        default=[],
        metavar="JSON_PATH",
        help="also ignore this exact JSON path (repeatable)",
    )
    args = parser.parse_args(argv)
    try:
        before, after = read_sweep(args.before), read_sweep(args.after)
    except (OSError, ValueError, TypeError) as problem:
        print(f"sweep_diff: {problem}", file=sys.stderr)
        return 2
    changed = differences(comparable(before), comparable(after), frozenset(args.ignore))
    for path, left, right in changed:
        print(f"{path}: {_shown(left)} -> {_shown(right)}")
    if changed:
        print(f"{len(changed)} difference(s)")
        return 1
    print("no differences")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
