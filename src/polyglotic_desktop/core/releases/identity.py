"""Who this copy is to Windows, macOS, Velopack and the server: its build
flavour (933 platform-5, polyglotic-hq 1045).

One build, stamped: the release, a preview and a rehearsal are the same
code, and the build's stamp (`release.json`'s `flavour`) says which one a
packed copy is. A preview or a rehearsal never reads anything that is the
release's own - its feed, feed keys, data folder, credential, Run value,
pack ID or bundle ID (polyglotic-hq RULES #7) - so a copy of each can sit
beside the installed app without touching it.

Plain literals, no Qt: `tools/release_check.py` reads the addresses from
this file at any commit, and the pack tools import it without Qt.
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from dataclasses import dataclass, replace
from functools import cache
from importlib.resources import files
from pathlib import Path

PROTOCOL = 1
"""The protocol version this app speaks (polyglotic-server docs/protocol.md);
`connection.protocol` re-exports it."""

SERVER = "https://api.polyglotic.io"
UPDATES = "https://updates.polyglotic.io/"
PACKS = UPDATES
FEED_KEYS: tuple[str, ...] = ("T9JEreM5nPkehQOMIfPbjUz1+UoZ73pUJ7rslb72xBs=",)
"""The release's addresses and feed keys (main.py says what each is)."""

STAMP = "release.json"


@dataclass(frozen=True, slots=True)
class BuildFlavour:
    """One flavour's identity."""

    stamp: str
    """The name `release.json` carries (a release's stamp names none)."""
    pack_id: str
    """Velopack's pack ID; its `.Desktop` is the taskbar's ID."""
    title: str
    credential: str
    """The device token's entry (Windows' Credential Manager, the Mac's keychain)."""
    data_folder: str
    """The learner's data folder's name (`%APPDATA%`, `~/Library/...`)."""
    run_value: str
    """The Windows Run key's value that starts the app with Windows."""
    shortcuts: str | None
    """vpk's `--shortcuts`: None passes none, so Velopack makes its own (the
    desktop's and the Start menu's, as the release has always had); "" for
    no shortcuts at all."""
    server: str
    packs: str
    """Where the dictionary packs come from."""
    packs_keys: tuple[str, ...]
    """The keys the packs' list must be signed with."""
    bundle_id: str
    """The Mac app's identifier."""
    updates: str
    """The release's update feed; any other flavour's private feed folder,
    from its build's stamp ("" when the build named none)."""
    feed_keys: tuple[str, ...]
    """The keys the update feed must be signed with: none for a local folder."""
    global_hotkeys: bool
    """Whether the Everywhere hotkeys act everywhere; else only in the app,
    leaving them to the installed copy."""

    def update_feed(self, program_folder: Path) -> str:
        """Where this copy looks for updates: the release's feed; any other
        flavour's private folder while it exists, else `program_folder`,
        which never holds a feed - a deleted feed folder stops the updates,
        never the app."""
        if self.stamp == "release":
            return self.updates
        if self.updates and Path(self.updates).is_dir():
            return self.updates
        return str(program_folder)


FLAVOURS = {
    "release": BuildFlavour(
        stamp="release",
        pack_id="Polyglotic",
        title="Polyglotic",
        credential="Polyglotic/device",
        data_folder="Polyglotic",
        run_value="Polyglotic",
        shortcuts=None,
        server=SERVER,
        packs=PACKS,
        packs_keys=FEED_KEYS,
        bundle_id="io.polyglotic.desktop",
        updates=UPDATES,
        feed_keys=FEED_KEYS,
        global_hotkeys=True,
    ),
    # Beside the installed app on the founder's PC (polyglotic-hq 990):
    # real captions and the real dictionary packs, its own everything else.
    "preview": BuildFlavour(
        stamp="preview",
        pack_id="PolygloticPreview",
        title="Polyglotic Preview",
        credential="Polyglotic/preview",
        data_folder="Polyglotic-Preview",
        run_value="Polyglotic-Preview",
        shortcuts="StartMenuRoot",
        server=SERVER,
        packs=PACKS,
        packs_keys=FEED_KEYS,
        bundle_id="io.polyglotic.desktop.preview",
        updates="",
        feed_keys=(),
        global_hotkeys=False,
    ),
    # The proof on the private desktop (RULES #7): nothing listens on its
    # server's or packs' port, so it sends nothing anywhere.
    "rehearsal": BuildFlavour(
        stamp="rehearsal",
        pack_id="PolygloticRehearsal990",
        title="Polyglotic Rehearsal 990",
        credential="Polyglotic/rehearsal-990",
        data_folder="Polyglotic-Rehearsal-990",
        run_value="Polyglotic-Rehearsal-990",
        shortcuts="",
        server="http://127.0.0.1:8990",
        packs="https://127.0.0.1:8990/",
        packs_keys=FEED_KEYS,
        bundle_id="io.polyglotic.desktop.rehearsal",
        updates="",
        feed_keys=(),
        global_hotkeys=False,
    ),
}


def flavour(name: str) -> BuildFlavour:
    try:
        return FLAVOURS[name]
    except KeyError:
        raise ValueError(
            f"unknown build flavour {name!r}; choose {', '.join(FLAVOURS)}"
        ) from None


def from_stamp(fields: Mapping[str, object]) -> BuildFlavour:
    """The identity a stamp's fields give: its flavour, and for any but the
    release, the build's private feed folder (`feed`) and hotkeys
    (`global_hotkeys`). ValueError for an unknown flavour, a release that
    names either (its feed is the literal above, never the build's), or a
    feed that isn't a folder's absolute path."""
    selected = flavour(str(fields.get("flavour", "release")))
    feed, hotkeys = fields.get("feed"), fields.get("global_hotkeys")
    if selected.stamp == "release":
        if feed is not None or hotkeys is not None:
            raise ValueError("release.json: a release takes no feed or hotkeys")
        return selected
    if feed is not None:
        if not isinstance(feed, str) or "://" in feed or not Path(feed).is_absolute():
            raise ValueError("release.json: the feed isn't a folder on this computer")
        selected = replace(selected, updates=feed)
    if hotkeys is not None:
        if not isinstance(hotkeys, bool):
            raise ValueError("release.json: global_hotkeys isn't true or false")
        selected = replace(selected, global_hotkeys=hotkeys)
    return selected


@cache
def current() -> BuildFlavour:
    """This copy's identity, from its stamp; a copy run from source has
    none and is the release. A stamp that can't be read is refused, never
    taken as the release's (RULES #7): the build checks it first."""
    stamp = files("polyglotic_desktop") / STAMP
    if not stamp.is_file():
        return flavour("release")
    try:
        fields = json.loads(stamp.read_text(encoding="utf-8"))
    except (ValueError, OSError) as error:
        raise ValueError("release.json: the build's flavour can't be read") from error
    if isinstance(fields, dict):
        return from_stamp(fields)
    raise ValueError("release.json: the build's flavour can't be read")
