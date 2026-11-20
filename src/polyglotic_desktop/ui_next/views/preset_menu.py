"""What the caption windows' preset dropdown and Settings > Presets show -
plain Python, no Qt (polyglotic-hq 556, desktop decision 0264).

`main` makes a `PresetMenu` from the settings (`ui.use_presets`, which the
new interface can't import) every time they change, and hands it to every
caption window and to Settings; the learner's clicks go back as signals,
and `main` makes the change. Holds no caption text.
"""

from collections.abc import Callable
from dataclasses import dataclass
from enum import StrEnum

from polyglotic_desktop.ui_next.views.panels import Shared


class Show(StrEnum):
    """What every caption shows: the dropdown's one choice of lines."""

    BOTH = "both"
    ORIGINAL = "original"
    """What was said only: no translation, in any window."""
    TRANSLATION = "translation"
    """The translation only: what was said hidden."""


@dataclass(frozen=True, slots=True)
class PresetItem:
    """A preset as listed: its key ("video", "own1"), its name - the
    learner's, where they renamed it - and whether it's the learner's
    rather than built in (Custom, or one they made: these can be deleted)."""

    key: str
    name: str
    own: bool = False


@dataclass(frozen=True, slots=True)
class PresetMenu:
    """The presets, the chosen one, and what's on in it: its Show, and the
    options added on top - word links or the quiet view, readings, my
    speech in every window. `changes`: what the chosen one changes from
    what it would have, as Settings lists them (the setting's name and its
    value, in words); `can_add`: another preset of the learner's own can be
    made."""

    items: tuple[PresetItem, ...] = ()
    chosen: str = "everyday"
    show: Show = Show.BOTH
    links: bool = False
    quiet: bool = False
    readings: bool = False
    my_speech: bool = False
    changes: tuple[tuple[str, str], ...] = ()
    can_add: bool = True

    @property
    def name(self) -> str:
        """The chosen preset's name ("" before any is known)."""
        return next((i.name for i in self.items if i.key == self.chosen), "")

    @property
    def chosen_own(self) -> bool:
        return any(i.own for i in self.items if i.key == self.chosen)


class PresetsView(Shared[PresetMenu]):
    """The presets as Settings > Presets shows them: `follow`ed from the
    settings, and the learner's steps handed to `main` through the
    callables it sets - pick, rename, reset, add, delete (556)."""

    def __init__(self, menu: PresetMenu | None = None) -> None:
        super().__init__(menu or PresetMenu())
        self.chose: Callable[[str], None] = lambda key: None
        self.rename: Callable[[str, str], None] = lambda key, name: None
        self.reset: Callable[[str], None] = lambda key: None
        self.add: Callable[[str], None] = lambda name: None
        self.delete: Callable[[str], None] = lambda key: None
