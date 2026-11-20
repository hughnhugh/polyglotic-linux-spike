r"""A button of the packed app pressed as a screen reader presses it
(polyglotic-hq 574): through the desktop's accessibility bus (AT-SPI), from
another process - the app's own widgets, found by their names, with nothing
of the tour inside the app. Qt serves AT-SPI when the app is started with
`QT_LINUX_ACCESSIBILITY_ALWAYS_ON=1`.

    /usr/bin/python3 tools/linux_atspi_press.py NAME [NAME...]

Each NAME is pressed in turn: the first button (or menu item, or page tab)
of the app named Polyglotic whose accessible name is NAME. Says what it
pressed, one JSON line each; exits 1 if a name wasn't found. A press that
opens something modal (a file dialog) gets no answer until it closes: that
counts as pressed.

The system's Python with the distribution's pyatspi (`python3-pyatspi`), not
the app's environment: GitHub's runners only (`tools/linux_packed_tour.py`).
"""

import importlib
import json
import os
import sys
import time
from typing import Any

PRESSABLE = {"push button", "toggle button", "menu item", "page tab", "list item"}
VERBS = ("press", "click", "activate", "toggle")


def apps(atspi: Any) -> list[Any]:
    desktop = atspi.Registry.getDesktop(0)
    return [
        a for a in desktop if a is not None and "polyglotic" in (a.name or "").lower()
    ]


def find(node: Any, name: str, depth: int = 0) -> Any:
    if node is None or depth > 60:
        return None
    try:
        if (node.name or "") == name and node.getRoleName() in PRESSABLE:
            return node
        for child in node:
            found = find(child, name, depth + 1)
            if found is not None:
                return found
    except Exception:  # noqa: BLE001 - a node gone while it was read
        return None
    return None


def press(atspi: Any, name: str, seconds: float = 30.0) -> dict[str, Any]:
    end = time.monotonic() + seconds
    while time.monotonic() < end:
        for app in apps(atspi):
            node = find(app, name)
            if node is None:
                continue
            action = node.queryAction()
            names = [action.getName(i) for i in range(action.nActions)]
            which = next((i for i, n in enumerate(names) if n.lower() in VERBS), 0)
            answered = True
            try:
                action.doAction(which)
            except Exception:  # noqa: BLE001 - modal: no answer until it closes
                answered = False
            return {
                "pressed": name,
                "role": node.getRoleName(),
                "action": names[which] if names else None,
                "answered": answered,
            }
        time.sleep(1)
    return {"pressed": None, "wanted": name, "apps": [a.name for a in apps(atspi)]}


def main() -> int:
    if os.environ.get("GITHUB_ACTIONS") != "true":
        sys.exit("574: this runs only on GitHub's Linux runners")
    atspi = importlib.import_module("pyatspi")
    failed = False
    for name in sys.argv[1:]:
        said = press(atspi, name)
        print(json.dumps(said, ensure_ascii=False), flush=True)
        failed = failed or said.get("pressed") is None
        time.sleep(2)
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
