"""Update identity at the Velopack adapter boundary."""

from typing import Any, ClassVar

import pytest

from polyglotic_desktop.adapters import velopack_updates
from polyglotic_desktop.adapters.velopack_updates import VelopackUpdater


class Asset:
    def __init__(self) -> None:
        self.Version = "2.0.0"
        self.NotesMarkdown = ""
        self.Size = 1


class Info:
    TargetFullRelease = Asset()
    IsDowngrade = False
    DeltasToTarget: ClassVar[list[object]] = []
    BaseRelease = None


class Manager:
    made: ClassVar[list["Manager"]] = []

    def __init__(self, source: str, options: Any) -> None:
        self.channel = options.ExplicitChannel
        self.downloaded = False
        self.made.append(self)

    def check_for_updates(self) -> Info:
        return Info()

    def download_updates(self, info: Info) -> None:
        self.downloaded = True


@pytest.mark.xfail(
    strict=True,
    reason="platform lane, before any second channel publishes",
)
def test_same_version_on_a_second_channel_does_not_take_over_first_handles(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Known owner: platform lane; Update equality currently omits channel."""
    Manager.made = []
    monkeypatch.setattr(velopack_updates.velopack, "UpdateManager", Manager)
    updater = VelopackUpdater("https://updates.example.org")
    first = updater.find("win-x64-alpha", False)
    updater.find("win-x64-beta", False)

    assert first is not None
    updater.download(first)

    alpha, beta = Manager.made
    assert alpha.downloaded is True
    assert beta.downloaded is False
