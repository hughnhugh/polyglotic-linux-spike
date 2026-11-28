"""Who a pack is to Velopack (`pack.sh`): the flavour's pack ID, title and
shortcuts (`core.releases.identity`, polyglotic-hq 1045).

    uv run --no-sync python -m tools.package.pack_identity PACKDIR

Prints the shell assignments pack.sh evaluates: `id`, `title`, and
`shortcuts`, vpk's `--shortcuts` with its value - none for the release,
which leaves Velopack's own (the desktop's and the Start menu's), as the
release has always been packed. The flavour is the build environment's
(`POLYGLOTIC_BUILD_FLAVOUR`, the release when unset), refused when the
app's own stamp in PACKDIR names another: a copy is never packed under an
identity it doesn't read at run time (RULES #7). No Qt.
"""

from __future__ import annotations

import json
import os
import shlex
import sys
from collections.abc import Mapping, Sequence
from pathlib import Path

from polyglotic_desktop.core.releases.identity import (
    STAMP,
    BuildFlavour,
    flavour,
    from_stamp,
)
from tools.package.stamp import FLAVOUR_ENV

STAMPED_AT = (
    f"_internal/polyglotic_desktop/{STAMP}",  # Windows' and Linux's folder
    f"Contents/Frameworks/polyglotic_desktop/{STAMP}",  # a Mac's bundle
)
"""Where the packed app's stamp is, inside PACKDIR (`build.LAYOUT`'s `code`)."""


def stamped(packdir: Path) -> BuildFlavour | None:
    """The identity the app in `packdir` reads at run time, or None if it
    has no stamp there."""
    for name in STAMPED_AT:
        file = packdir / name
        if file.is_file():
            return from_stamp(json.loads(file.read_text(encoding="utf-8")))
    return None


def pack_flavour(packdir: Path, environ: Mapping[str, str]) -> BuildFlavour:
    """The flavour to pack `packdir` as; ValueError if its stamp disagrees."""
    selected = flavour(environ.get(FLAVOUR_ENV) or "release")
    found = stamped(packdir)
    if found is not None and found.stamp != selected.stamp:
        raise ValueError(
            f"{packdir} is a {found.stamp} build: set {FLAVOUR_ENV}={found.stamp}"
            f" to pack it, not {selected.stamp}"
        )
    return selected


def shortcuts(selected: BuildFlavour) -> list[str]:
    """vpk's `--shortcuts` for `selected`: none passed for the release."""
    if selected.shortcuts is None:
        return []
    return ["--shortcuts", selected.shortcuts]


def assignments(selected: BuildFlavour) -> str:
    """pack.sh's `id`, `title` and `shortcuts` (an array), quoted for bash."""
    quoted = " ".join(shlex.quote(a) for a in shortcuts(selected))
    return (
        f"id={shlex.quote(selected.pack_id)}\n"
        f"title={shlex.quote(selected.title)}\n"
        f"shortcuts=({quoted})\n"
    )


def main(argv: Sequence[str] | None = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    if len(args) != 1:
        print("usage: python -m tools.package.pack_identity PACKDIR", file=sys.stderr)
        return 2
    try:
        selected = pack_flavour(Path(args[0]), os.environ)
    except ValueError as e:
        print(f"pack_identity: refused: {e}", file=sys.stderr)
        return 1
    # bytes, so Windows' stdout adds no carriage returns for bash to keep
    sys.stdout.buffer.write(assignments(selected).encode("utf-8"))
    sys.stdout.buffer.flush()
    return 0


if __name__ == "__main__":
    sys.exit(main())
