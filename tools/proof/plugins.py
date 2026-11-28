"""Replay and picture evidence collectors."""

import json
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

from tools.proof.model import Difference, Evidence


class Plugin(Protocol):
    name: str

    def collect(
        self, checkout: Path, scratch: Path, plant: str | None = None
    ) -> Evidence: ...

    def compare(self, base: Evidence, head: Evidence) -> list[Difference]: ...

    def noise_control(self, recorded: Evidence) -> tuple["Plugin", Evidence]: ...


def _first(
    left: tuple[tuple[int, str], ...], right: tuple[tuple[int, str], ...]
) -> int:
    for (a_frame, a), (b_frame, b) in zip(left, right, strict=False):
        if (a_frame, a) != (b_frame, b):
            return min(a_frame, b_frame)
    if len(left) != len(right):
        longer = left if len(left) > len(right) else right
        return longer[min(len(left), len(right))][0]
    return 0


def compare_evidence(base: Evidence, head: Evidence, rule: str) -> list[Difference]:
    found = []
    for fixture in sorted(base.fingerprints.keys() | head.fingerprints.keys()):
        before = base.fingerprints.get(fixture, ())
        after = head.fingerprints.get(fixture, ())
        if before != after:
            found.append(
                Difference(
                    base.what,
                    fixture,
                    _first(before, after),
                    rule,
                    "missing fixture"
                    if not before or not after
                    else "fingerprint changed",
                )
            )
    return found


@dataclass(frozen=True)
class ReplayPlugin:
    name = "replay"
    only: tuple[str, ...] = ()

    def collect(
        self, checkout: Path, scratch: Path, plant: str | None = None
    ) -> Evidence:
        out = scratch / "replay.json"
        command = [
            sys.executable,
            "-m",
            "tools.scene_replay",
            "record",
            "--src",
            str(checkout / "src"),
            "--out",
            str(out),
            "--jobs",
            "2",
        ]
        for pattern in self.only:
            command += ["--only", pattern]
        if plant:
            command += ["--plant", plant]
        subprocess.run(command, check=True)
        data = json.loads(out.read_text("utf-8"))
        fingerprints = {
            run["run"]: tuple((int(frame), digest) for frame, digest in run["changed"])
            for run in data["runs"]
        }
        return Evidence(self.name, len(fingerprints), fingerprints)

    def compare(self, base: Evidence, head: Evidence) -> list[Difference]:
        return compare_evidence(base, head, "replay.frame")

    def noise_control(self, recorded: Evidence) -> tuple[Plugin, Evidence]:
        fixture = next(iter(sorted(recorded.fingerprints)))
        sample = Evidence(self.name, 1, {fixture: recorded.fingerprints[fixture]})
        return ReplayPlugin((fixture,)), sample


@dataclass(frozen=True)
class PicturesPlugin:
    """Render and compare the rulebook pictures through the UI lab photograph."""

    name = "pictures"
    only: tuple[str, ...] = ()

    def collect(
        self, checkout: Path, scratch: Path, plant: str | None = None
    ) -> Evidence:
        out = scratch / "pictures.json"
        subprocess.run(
            [
                sys.executable,
                "-m",
                "tools.proof.picture_worker",
                str(checkout),
                str(out),
                *(plant and ["--plant", plant] or []),
                *(item for pattern in self.only for item in ("--only", pattern)),
            ],
            check=True,
        )
        plain = json.loads(out.read_text("utf-8"))
        fingerprints: dict[str, tuple[tuple[int, str], ...]] = {
            name: tuple((int(frame), str(digest)) for frame, digest in frames)
            for name, frames in plain.items()
        }
        return Evidence(self.name, len(fingerprints), fingerprints)

    def compare(self, base: Evidence, head: Evidence) -> list[Difference]:
        return compare_evidence(base, head, "pictures.pixels")

    def noise_control(self, recorded: Evidence) -> tuple[Plugin, Evidence]:
        fixture = next(iter(sorted(recorded.fingerprints)))
        sample = Evidence(self.name, 1, {fixture: recorded.fingerprints[fixture]})
        return PicturesPlugin((fixture,)), sample


PLUGINS: dict[str, Plugin] = {
    "replay": ReplayPlugin(),
    "pictures": PicturesPlugin(),
}
