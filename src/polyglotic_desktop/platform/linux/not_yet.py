"""What the first Linux build doesn't have yet (polyglotic-hq 546's slices
3-8, 550, 561): each piece says so through its port, the way the app already
handles an OS that refuses it, so the interface hides it or explains it.

- `NoHotkeys` - Ctrl+Alt+L, P and H answer "not working here" (slice 3);
- `NoHoldKey`, `type_nothing`, `no_window` - dictation's key and typing
  (slice 8);
- `no_keys` - Esc, Backspace and clicks elsewhere aren't read (slice 3);
- `NoSound` - Home's sample isn't played aloud (slice 5).

The rest of Windows' pieces have no Linux counterpart at all, as on a Mac:
the store's package, the taskbar's ID, fonts read and windows made ahead
(`main` reads False as "not done ahead" and goes on as before).
"""

from collections.abc import Callable, Mapping
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from polyglotic_desktop.platform.speech_detection import Audio


class NoHotkeys:
    """`Hotkeys`: none taken - every key answers "not working here", so the
    interface says how else to lock, pause or hide (slice 3)."""

    def __init__(self, keys: Mapping[str, Callable[[], None]]) -> None:
        self._keys = list(keys)

    def start(self) -> list[str]:
        return list(self._keys)

    def stop(self) -> None:
        pass


class NoHoldKey:
    """`HoldKey`: dictation's key isn't taken (slice 8)."""

    def __init__(self, *_args: object) -> None:
        pass

    def start(self) -> bool:
        return False

    def stop(self) -> None:
        pass


def type_nothing(_text: str) -> bool:
    """`TypeText`: nothing typed (slice 8)."""
    return False


def no_window() -> int:
    """`KeyboardWindow`: none known."""
    return 0


def no_keys(_name: str) -> bool:
    """`KeyState`: nothing read held (slice 3)."""
    return False


class NoSound:
    """`SoundOut`: Home's sample isn't played aloud on Linux yet."""

    def play(self, _audio: "Audio", _rate: int) -> bool:
        return False

    def stop(self) -> None:
        pass


class NoForegroundWatch:
    """`ForegroundWatch`: not watched (the caption windows are above every
    window anyway: `on_top.py`)."""

    def __init__(self, _changed: Callable[[], None]) -> None:
        pass

    def start(self) -> bool:
        return False

    def stop(self) -> None:
        pass


def none_found() -> None:
    """`StorePackage`: no app store's package."""
    return


def same_name(name: str) -> str:
    """`TaskbarIdentity`: the panel knows the app by its desktop file and
    window class, not an ID the app gives itself - the name given is
    logged as it is."""
    return name


def not_done() -> bool:
    """`read_fonts`: not read ahead (Qt reads them when first asked)."""
    return False


def not_made(_widget: int) -> bool:
    """`make_native_window`: not made ahead."""
    return False
