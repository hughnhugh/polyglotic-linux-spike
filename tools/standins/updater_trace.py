"""Deterministic updater trace and its deliberately broken variants.

Run with ``python -m tools.standins.updater_trace``.  The two ``--fault``
choices are mutations used to prove that the trace detects an apply twice and
a download which core did not request.
"""

from __future__ import annotations

import argparse
import json
from dataclasses import dataclass, field

from polyglotic_desktop.core.releases.updates import CHANNELS, RestartOffer, Updates
from polyglotic_desktop.ports.updates import Update

VERSION = "9.8.7"


@dataclass
class TracingUpdater:
    """The Updater port with an observable, inert implementation."""

    update: Update
    events: list[str] = field(default_factory=list)

    def installed(self) -> bool:
        return True

    def find(self, channel: str | None, allow_downgrade: bool) -> Update:
        self.events.append(f"find:{channel or 'installed'}:{allow_downgrade}")
        return self.update

    def download(self, update: Update) -> None:
        self.events.append(f"download:{update.version}")

    def apply_at_exit(self, update: Update, restart: bool = False) -> None:
        self.events.append(f"apply:{update.version}:restart={restart}")

    def restart_into(self, update: Update) -> None:
        self.events.append(f"restart:{update.version}")


def pair_trace(installed: str, offered: str) -> list[str]:
    switching = installed.rsplit("-", 1)[0] == offered.rsplit("-", 1)[0]
    update = Update(VERSION, downgrade=switching and installed != offered)
    updater = TracingUpdater(update)
    updates = Updates(updater, installed)
    updates.follow(offered)
    assert updates.check() == update
    return updater.events


def lifecycle_trace() -> dict[str, list[str]]:
    update = Update(VERSION)

    ordinary_port = TracingUpdater(update)
    ordinary = Updates(ordinary_port, CHANNELS[0])
    ordinary.check()
    ordinary.at_exit()

    forced_port = TracingUpdater(update)
    forced = Updates(forced_port, CHANNELS[0])
    forced.update_now()

    linux_port = TracingUpdater(update)
    linux = Updates(linux_port, "linux-x64-alpha", apply_on_quit=True)
    linux.check()
    linux.at_exit()

    offer = RestartOffer()
    offer.found(update)
    late_subscriber = [f"asking:{offer.asking.version if offer.asking else None}"]
    return {
        "late_subscriber": late_subscriber,
        "ordinary": ordinary_port.events,
        "forced": forced_port.events,
        "linux_exit": linux_port.events,
    }


def trace(fault: str | None = None) -> dict[str, object]:
    pairs = {
        f"{installed}->{offered}": pair_trace(installed, offered)
        for installed in CHANNELS
        for offered in CHANNELS
    }
    lifecycle = lifecycle_trace()
    if fault == "double-apply":
        lifecycle["linux_exit"].append(f"apply:{VERSION}:restart=False")
    elif fault == "unasked-download":
        lifecycle["ordinary"].append(f"download:{VERSION}")
    result: dict[str, object] = {"pairs": pairs, **lifecycle}
    return result


def validate(found: dict[str, object]) -> None:
    pairs = found["pairs"]
    assert isinstance(pairs, dict) and len(pairs) == 81
    for events in pairs.values():
        assert isinstance(events, list)
        assert sum(event.startswith("download:") for event in events) == 1
    ordinary = found["ordinary"]
    forced = found["forced"]
    linux = found["linux_exit"]
    assert isinstance(ordinary, list) and ordinary.count(f"download:{VERSION}") == 1
    assert not any(event.startswith("apply:") for event in ordinary)
    assert isinstance(forced, list) and forced[-1] == f"restart:{VERSION}"
    assert (
        isinstance(linux, list) and linux.count(f"apply:{VERSION}:restart=False") == 1
    )
    assert found["late_subscriber"] == [f"asking:{VERSION}"]


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--fault", choices=("double-apply", "unasked-download"))
    args = parser.parse_args()
    found = trace(args.fault)
    validate(found)
    print(json.dumps(found, sort_keys=True, separators=(",", ":")))


if __name__ == "__main__":
    main()
