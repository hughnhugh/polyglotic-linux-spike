"""Render the rulebook's pictures in an isolated checkout's application."""

import argparse
import hashlib
import json
import sys
from pathlib import Path


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("checkout", type=Path)
    parser.add_argument("output", type=Path)
    parser.add_argument("--plant")
    parser.add_argument("--only", action="append", default=[])
    args = parser.parse_args()
    checkout, output = args.checkout, args.output
    sys.path.insert(0, str(checkout / "src"))

    # Imported only after the selected checkout is first on the module path.
    from tools.scene_replay import pictures, rulebook

    rules = rulebook.load(checkout / "tests" / "ui_next" / "rules")
    recipes = {
        picture.file: picture
        for rule in rules
        for picture in ([rule.picture] if rule.picture else [])
    }
    rendered: dict[str, list[list[object]]] = {}
    folder = output.parent / "rendered"
    folder.mkdir()
    for name, picture in sorted(recipes.items()):
        if args.only and not any(pattern in name for pattern in args.only):
            continue
        path = folder / name
        path.parent.mkdir(parents=True, exist_ok=True)
        rendered_picture = pictures.draw(picture)
        if args.plant == "colour":
            # A real pixel change in the rendered evidence, rather than a
            # synthetic digest. Pick an opaque corner so image formats keep it.
            from PySide6.QtGui import QColor

            rendered_picture.setPixelColor(0, 0, QColor("#ff00ff"))
        if not rendered_picture.save(str(path)):
            raise RuntimeError(f"could not save {name}")
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
        rendered[name] = [[frame, digest] for frame in picture.frames]
    output.write_text(json.dumps(rendered) + "\n", "utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
