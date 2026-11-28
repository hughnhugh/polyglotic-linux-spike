"""The release's version from its git tag, stamped into the app (decision 0015).

    uv run python -m tools.package.stamp v0.1.0 --channel win-x64-alpha --out build/package/release.json

Writes `{"version": "0.1.0", "channel": "win-x64-alpha", "built":
"2026-11-14T05:12:00Z"}` - `built`, when it was built in UTC, is the app's
floor for a certificate's dates (decision 0104). A preview's or a
rehearsal's also names its `flavour` and, if its build gave them, its
private `feed` folder and `global_hotkeys` (`core.releases.identity`,
polyglotic-hq 1045). Refuses a tag that isn't `v` plus protocol.md's
`MAJOR.MINOR.PATCH`, a channel protocol.md doesn't know and an identity the
app wouldn't take - checked by the same readers the app uses
(`connection.app.read_release`, `identity.from_stamp`), so the build can't
write a stamp the app would refuse.
"""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Mapping, Sequence
from datetime import UTC, datetime
from pathlib import Path
from typing import TypedDict

from polyglotic_desktop.connection.app import Release, read_release
from polyglotic_desktop.core.releases import identity

FLAVOUR_ENV = "POLYGLOTIC_BUILD_FLAVOUR"
"""The build's environment names its flavour (`core.releases.identity`):
release when unset. A build asked for another is refused, so a preview is
never built where a release is, nor the other way (polyglotic-hq 1045)."""
FEED_ENV = "POLYGLOTIC_BUILD_FEED"
"""A preview's or rehearsal's private feed folder, stamped into it: a build
input, never a literal, and never a release's."""
HOTKEYS_ENV = "POLYGLOTIC_BUILD_GLOBAL_HOTKEYS"
"""`1`: a preview's or rehearsal's Everywhere hotkeys act everywhere, for
trying one with a real key press (polyglotic-hq 990); never a release's."""


class Identity(TypedDict, total=False):
    """A stamp's identity fields (`identity.from_stamp`'s)."""

    flavour: str
    feed: str
    global_hotkeys: bool


def build_inputs(requested: str, environ: Mapping[str, str]) -> Identity:
    """The stamp's identity fields (`stamp.stamp`'s keywords) for a build of
    flavour `requested`, from the build's environment (`environ`).
    ValueError for an unknown flavour, an environment that names another,
    a release given a feed or hotkeys, or a feed `identity` wouldn't take."""
    identity.flavour(requested)  # unknown flavours refused
    named = environ.get(FLAVOUR_ENV) or "release"
    if named != requested:
        raise ValueError(
            f"a {requested} build in a {named!r} environment: set {FLAVOUR_ENV}"
            " to the flavour asked for"
        )
    feed = environ.get(FEED_ENV) or None
    hotkeys = environ.get(HOTKEYS_ENV) or None
    if requested == "release" and (feed or hotkeys):
        raise ValueError(f"a release takes no {FEED_ENV} or {HOTKEYS_ENV}")
    if hotkeys not in (None, "1"):
        raise ValueError(f"{HOTKEYS_ENV} is 1 or unset, not {hotkeys!r}")
    inputs = Identity(flavour=requested)
    if feed is not None:
        inputs["feed"] = feed
    if hotkeys is not None:
        inputs["global_hotkeys"] = True
    identity.from_stamp(inputs)  # the feed: a folder's absolute path
    return inputs


def version_from_tag(tag: str) -> str:
    """`v0.1.0` (or `refs/tags/v0.1.0`) -> `0.1.0`; ValueError otherwise."""
    name = tag.removeprefix("refs/tags/")
    if not name.startswith("v"):
        raise ValueError(f"a release tag starts with v: {name!r}")
    return name[1:]


def built_now() -> str:
    """This moment in UTC, as the stamp keeps it."""
    return datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def stamp(
    version: str,
    channel: str,
    built: str | None = None,
    flavour: str = "release",
    feed: str | None = None,
    global_hotkeys: bool | None = None,
) -> str:
    """`release.json`'s text, checked as the app will read it. `built`: the
    build's time (`built_now()`); a build promoted to another channel keeps
    its own, or none if it had none (promote.py). `flavour`, `feed` and
    `global_hotkeys`: `identity.from_stamp`'s, none of them a release's."""
    fields: dict[str, object] = {"version": version, "channel": channel}
    if flavour != "release":
        fields["flavour"] = flavour
    if feed is not None:
        fields["feed"] = feed
    if global_hotkeys is not None:
        fields["global_hotkeys"] = global_hotkeys
    if built is not None:
        fields["built"] = built
    text = json.dumps(fields) + "\n"
    read_release(text)  # ValueError if the app would refuse it
    identity.from_stamp(fields)  # and if it wouldn't take the identity
    return text


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m tools.package.stamp")
    parser.add_argument("tag", help="the release's git tag, e.g. v0.1.0")
    parser.add_argument("--channel", default="win-x64-alpha")
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        text = stamp(version_from_tag(args.tag), args.channel, built_now())
    except ValueError as e:
        print(f"Not a release tag: {e}", file=sys.stderr)
        return 1
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(text, encoding="utf-8")
    release: Release = read_release(text)
    print(f"Stamped {release.version} on {release.channel} -> {args.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
