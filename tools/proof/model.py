"""Values written to proof.json and proof.md."""

from dataclasses import asdict, dataclass
from typing import Any


@dataclass(frozen=True)
class Difference:
    what: str
    fixture: str
    frame: int
    rule: str
    detail: str

    def plain(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class Evidence:
    what: str
    fixtures: int
    fingerprints: dict[str, tuple[tuple[int, str], ...]]
