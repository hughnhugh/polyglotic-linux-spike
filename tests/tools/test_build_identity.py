"""One build, stamped (polyglotic-hq 1045): each flavour's identity, and a
preview or rehearsal never reads a value that is the release's (RULES #7)."""

import json
import subprocess
import sys
from collections.abc import Iterator
from dataclasses import fields
from pathlib import Path

import pytest

from polyglotic_desktop.core.releases import identity

RELEASE = identity.flavour("release")
REAL_KEY = identity.FEED_KEYS[0]  # the release feed's public key (DECISIONS #97)

EXPECTED = {
    # pack ID, title, credential, data folder, Run value, shortcuts, server, packs
    # - as HQ's scripts/preview_roll.py names them (PREVIEW, REHEARSAL)
    "release": (
        "Polyglotic", "Polyglotic", "Polyglotic/device", "Polyglotic", "Polyglotic",
        None, "https://api.polyglotic.io", "https://updates.polyglotic.io/",
    ),
    "preview": (
        "PolygloticPreview", "Polyglotic Preview", "Polyglotic/preview",
        "Polyglotic-Preview", "Polyglotic-Preview", "StartMenuRoot",
        "https://api.polyglotic.io", "https://updates.polyglotic.io/",
    ),
    "rehearsal": (
        "PolygloticRehearsal990", "Polyglotic Rehearsal 990", "Polyglotic/rehearsal-990",
        "Polyglotic-Rehearsal-990", "Polyglotic-Rehearsal-990", "",
        "http://127.0.0.1:8990", "https://127.0.0.1:8990/",
    ),
}  # fmt: skip

SHARED_WITH_THE_RELEASE = {
    "preview": {"server", "packs", "packs_keys"},  # real captions, real packs
    "rehearsal": {"packs_keys"},  # checked with the real key, from nowhere
}
"""What a flavour may share with the release, and nothing else: never its
feed, feed keys, data folder, credential, Run value, IDs or title."""


@pytest.mark.parametrize(("name", "expected"), EXPECTED.items())
def test_each_flavour_has_its_own_identity(
    name: str, expected: tuple[object, ...]
) -> None:
    selected = identity.flavour(name)
    assert (
        selected.pack_id,
        selected.title,
        selected.credential,
        selected.data_folder,
        selected.run_value,
        selected.shortcuts,
        selected.server,
        selected.packs,
    ) == expected
    assert selected.packs_keys == (REAL_KEY,)


def test_the_release_keeps_its_feed_keys_hotkeys_and_velopacks_own_shortcuts() -> None:
    assert RELEASE.updates == "https://updates.polyglotic.io/"
    assert RELEASE.feed_keys == (REAL_KEY,)
    assert RELEASE.global_hotkeys is True
    assert (
        RELEASE.shortcuts is None
    )  # vpk's default: the desktop's and the Start menu's
    assert RELEASE.bundle_id == "io.polyglotic.desktop"


@pytest.mark.parametrize("name", ["preview", "rehearsal"])
def test_no_real_value_leaks_into_a_flavour(name: str, tmp_path: Path) -> None:
    """Every field differs from the release's but those it may share, as
    built and as stamped with a private feed and hotkeys; and its updates
    come from that folder or its own program folder, unsigned."""
    feed = tmp_path / "feed"
    feed.mkdir()
    built = identity.flavour(name)
    stamped = identity.from_stamp({"flavour": name, "feed": str(feed)})
    for selected in (built, stamped):
        for field in fields(identity.BuildFlavour):
            if field.name in SHARED_WITH_THE_RELEASE[name]:
                continue
            mine, real = getattr(selected, field.name), getattr(RELEASE, field.name)
            assert mine != real, f"{name}'s {field.name} is the release's: {real!r}"
        assert selected.feed_keys == ()
    program = tmp_path / "program"
    assert built.update_feed(program) == str(program)
    assert stamped.update_feed(program) == str(feed)
    assert identity.UPDATES not in (
        built.update_feed(program),
        stamped.update_feed(program),
    )


def test_a_deleted_feed_folder_stops_updates_never_the_app(tmp_path: Path) -> None:
    gone = identity.from_stamp({"flavour": "preview", "feed": str(tmp_path / "gone")})
    assert gone.update_feed(tmp_path) == str(tmp_path)


def test_the_release_reads_its_own_feed_whatever_the_program_folder(
    tmp_path: Path,
) -> None:
    assert RELEASE.update_feed(tmp_path) == "https://updates.polyglotic.io/"


@pytest.mark.parametrize(
    "stamp",
    [
        {"feed": "C:/previews/feed"},
        {"flavour": "release", "global_hotkeys": False},
        {"flavour": "preview", "feed": "https://updates.polyglotic.io/"},
        {"flavour": "preview", "feed": "previews/feed"},
        {"flavour": "rehearsal", "global_hotkeys": "yes"},
        {"flavour": "nightly"},
    ],
)
def test_a_stamp_the_app_must_not_take_is_refused(stamp: dict[str, object]) -> None:
    with pytest.raises(ValueError):
        identity.from_stamp(stamp)


def test_a_stamp_can_keep_a_previews_everywhere_hotkeys() -> None:
    keeps = identity.from_stamp({"flavour": "preview", "global_hotkeys": True})
    assert keeps.global_hotkeys and keeps.pack_id == "PolygloticPreview"


def test_an_unknown_flavour_is_refused() -> None:
    with pytest.raises(ValueError, match="unknown build flavour"):
        identity.flavour("nightly")


@pytest.fixture
def package(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Iterator[Path]:
    folder = tmp_path / "polyglotic_desktop"
    folder.mkdir()
    monkeypatch.setattr(identity, "files", lambda _: folder)
    identity.current.cache_clear()
    yield folder
    identity.current.cache_clear()


def test_current_reads_the_build_stamp(package: Path) -> None:
    assert identity.current() == RELEASE  # from source: no stamp
    identity.current.cache_clear()
    (package / "release.json").write_text(json.dumps({"flavour": "preview"}))
    assert identity.current() == identity.flavour("preview")


def test_a_stamp_that_cant_be_read_is_refused_never_taken_as_the_release(
    package: Path,
) -> None:
    (package / "release.json").write_text('{"flavour": "prev')
    with pytest.raises(ValueError, match="can't be read"):
        identity.current()


APP_SAYS = """
import json, sys
from pathlib import Path
from polyglotic_desktop.core.releases import identity
identity.files = lambda _name: Path(sys.argv[1])  # this copy's stamp
from polyglotic_desktop import main
from polyglotic_desktop.platform.macos import system as macos_system
from polyglotic_desktop.platform.windows import system as windows_system
said = {
    "server": main.SERVER,
    "updates": main.UPDATES,
    "feed_keys": list(main.FEED_KEYS),
    "packs": list(main.pack_storage(main.PACKS, (), True)),
    "elsewhere": main.CREDENTIALS_ELSEWHERE,
    "windows_data": windows_system.data_folder().name,
    "mac_data": macos_system.APP_FOLDER,
    "mac_feed": main.verified_feed_folder(
        "/A.app/Contents/MacOS/A", Path("/h"), system="darwin"
    ).parent.name,
    "linux_feed": main.verified_feed_folder(system="linux", environ={"XDG_CACHE_HOME": "/c"}).parent.name,
}
if sys.platform == "win32":
    from polyglotic_desktop.adapters import windows_credentials
    from polyglotic_desktop.platform.windows import startup
    said |= {"credential": windows_credentials.TARGET, "run_value": startup.VALUE}
print(json.dumps(said))
"""
"""What the app's own modules read in a copy stamped with a flavour."""


def app_says(stamp: dict[str, object], tmp_path: Path) -> dict[str, object]:
    package = tmp_path / "polyglotic_desktop"
    package.mkdir()
    (package / "release.json").write_text(json.dumps(stamp), encoding="utf-8")
    done = subprocess.run(
        [sys.executable, "-c", APP_SAYS, str(package)],
        capture_output=True,
        text=True,
        timeout=120,
        check=False,
    )
    assert done.returncode == 0, done.stderr[-3000:]
    return json.loads(done.stdout.splitlines()[-1])


@pytest.mark.parametrize("name", ["preview", "rehearsal"])
def test_the_app_reads_no_real_value_in_a_flavoured_copy(
    name: str, tmp_path: Path
) -> None:
    feed = tmp_path / "feed"
    feed.mkdir()
    said = app_says({"version": "0.1.14", "channel": "win-x64-alpha", "flavour": name,
                     "feed": str(feed)}, tmp_path)  # fmt: skip
    own = identity.flavour(name)
    assert said["updates"] == str(feed) and said["feed_keys"] == []
    assert said["packs"] == [own.packs, [REAL_KEY]]
    assert said["server"] == own.server
    assert said["elsewhere"] == own.credential + "@{server}"
    data = {
        said["windows_data"],
        said["mac_data"],
        said["mac_feed"],
        said["linux_feed"],
    }
    assert data == {own.data_folder}
    if sys.platform == "win32":
        assert (said["credential"], said["run_value"]) == (
            own.credential,
            own.run_value,
        )
    if name == "rehearsal":
        assert "polyglotic.io" not in json.dumps(said)
