"""Settings > Hotkeys: every key the app answers, in one place (polyglotic-hq 567, decision 0273).

The user, 2026-11-20: "Hotkey to jump to line (consider other power user
shortcuts/features) ... customiseable ... global hotkeys customisation
section". Three cards:

- **Hotkeys** (`HotkeysCard`) - pressed anywhere, over a game, a call or a
  video: each one's name, its key in a box that listens for a new one when
  clicked (`dictation_key.KeyBox`, as dictation's), Clear, and Reset all
  under them. A key pressed that can't be one says why on the hotkey's own
  line (`refusal_words`: it types, Windows keeps it, it's another
  hotkey's or dictation's...); one another program has, or one two hotkeys
  share (a file edited by hand), says so there too. A change goes out as
  `hotkey_wanted` (the hotkey's name and its key as kept, "" for none);
  `main` keeps it and takes the keys again.
- **Held while you speak** - dictation's key, named, with the way to
  change it (Settings > Dictation, where it's set: `dictation_wanted`).
- **In a window** - the keys a transcript and the lookup card answer while
  they have the keyboard: Windows' own (Ctrl+F, Ctrl+C, End, Esc), named
  here so every key is in one place, not changed (decision 0273).

No key is ever logged.
"""

from collections.abc import Collection, Mapping

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QKeySequence
from PySide6.QtWidgets import (
    QApplication,
    QGridLayout,
    QPushButton,
    QWidget,
)

from polyglotic_desktop.core.listening.dictation_keys import (
    DEFAULT_KEY,
    DictationKey,
    Refusal,
)
from polyglotic_desktop.core.listening.hotkeys import (
    DICTATE,
    ORDER,
    Hotkey,
    clashes,
    holder,
)
from polyglotic_desktop.core.listening.hotkeys import (
    defaults as hotkey_defaults,
)
from polyglotic_desktop.core.listening.hotkeys import (
    refusal as hotkey_refusal,
)
from polyglotic_desktop.ui_next import os_words
from polyglotic_desktop.ui_next.controls import Card, label, right_row
from polyglotic_desktop.ui_next.dictation_key import KeyBox, key_words
from polyglotic_desktop.ui_next.dictation_key import refusal_words as key_refusal_words


def _tr(text: str) -> str:
    return QApplication.translate("Hotkeys", text)


def _tr_settings(text: str) -> str:
    """Settings' own words for the hotkeys it named before (its App card)."""
    return QApplication.translate("Settings", text)


def hotkey_names() -> dict[str, str]:
    """What each hotkey does, by its name, as Settings lists it; dictation's
    key as "Dictate"."""
    return {
        Hotkey.LOCK.value: _tr_settings("Lock all caption windows"),
        Hotkey.PAUSE.value: _tr_settings("Pause captions"),
        Hotkey.HIDE.value: _tr_settings("Hide all caption windows"),
        #: jump every caption window and transcript to its newest line
        Hotkey.LIVE.value: _tr("Back to live"),
        Hotkey.COPY.value: _tr("Copy the newest caption"),
        Hotkey.PRESET.value: _tr("Next preset"),
        Hotkey.BIGGER.value: _tr("Caption text bigger"),
        Hotkey.SMALLER.value: _tr("Caption text smaller"),
        DICTATE: _tr("Dictate"),
    }


def refusal_words(refusal: Refusal | None) -> str:
    """Why a key can't be a hotkey's, plainly: dictation's words where they
    fit (`dictation_key.refusal_words`), a hotkey's own where they don't."""
    if refusal is Refusal.HELD_ALONE:
        return os_words.pc_or_mac(
            _tr("Hold Ctrl, Alt, Shift or Win with a key, or choose an F key."),
            _tr("Hold ⌘, ⌥, ⇧ or ⌃ with a key, or choose an F key."),
        )
    if refusal is Refusal.ESCAPE:
        return _tr("Esc closes things in every program: choose another key.")
    if refusal is Refusal.ALT and not os_words.on_a_mac():
        return _tr("Letting go of Alt opens a program's menu: hold Ctrl with it too.")
    return key_refusal_words(refusal)


def shortcut_words(sequence: QKeySequence.StandardKey | str) -> str:
    """A window's key as this OS writes it, in the app's language
    ("Ctrl+F", "Strg+F", "⌘F")."""
    found = QKeySequence(sequence)
    return found.toString(QKeySequence.SequenceFormat.NativeText)


class HotkeyLine(QWidget):
    """One hotkey: what it does, its key (click to change), Clear, and a
    note under them when there's something to say."""

    def __init__(self, name: str, title: str) -> None:
        super().__init__()
        self.setObjectName(f"hotkeys.{name}")
        grid = QGridLayout(self)
        grid.setContentsMargins(0, 0, 0, 0)
        grid.setHorizontalSpacing(8)
        grid.setVerticalSpacing(2)
        self.title = label(title, "RowTitle", wrap=True)
        grid.addWidget(self.title, 0, 0)
        self.box = KeyBox("", f"hotkeys.{name}.key", title)
        self.box.setMinimumWidth(140)
        grid.addWidget(self.box, 0, 1)
        self.clear = QPushButton(_tr("Clear"))
        self.clear.setObjectName(f"hotkeys.{name}.clear")
        self.clear.setCursor(Qt.CursorShape.PointingHandCursor)
        self.clear.setToolTip(_tr("No key: the hotkey does nothing"))
        self.clear.setAccessibleName(_tr("Clear {name}'s key").format(name=title))
        grid.addWidget(self.clear, 0, 2)
        self.note = label("", "Faint", wrap=True)
        self.note.setObjectName(f"hotkeys.{name}.note")
        grid.addWidget(self.note, 1, 0, 1, 3)
        self.note.hide()  # after its parent: never a window of its own
        grid.setColumnStretch(0, 1)

    def show_note(self, text: str) -> None:
        self.note.setText(text)
        self.note.setHidden(not text)


class HotkeysCard(Card):
    """The hotkeys, each one's key changed, cleared or all reset."""

    hotkey_wanted = Signal(str, str)
    """A hotkey's name and the key the learner gave it, as kept ("" for
    none) - one nothing here refuses."""
    reset_wanted = Signal()
    """Reset all: every hotkey's key its default."""
    listening = Signal(bool)
    """A key box listens: the app's own keys must let keys through."""

    def __init__(self) -> None:
        super().__init__(
            _tr_settings("Hotkeys"),
            os_words.pc_or_mac(
                _tr(
                    "They work from any program, even a game in front. Click a key,"
                    " then press the one you want."
                ),
                _tr(
                    "They work from any app, even a game in front. Click a key, then"
                    " press the one you want."
                ),
            ),
        )
        self.setObjectName("settings.hotkeys_card")
        self.names = hotkey_names()
        self.lines: dict[str, HotkeyLine] = {}
        for hotkey in ORDER:
            line = HotkeyLine(hotkey.value, self.names[hotkey.value])
            line.box.pressed_key.connect(
                lambda pressed, n=hotkey.value: self._pressed(n, pressed)
            )
            line.box.listening_changed.connect(self.listening)
            line.clear.clicked.connect(
                lambda _checked=False, n=hotkey.value: self._clear(n)
            )
            self.lines[hotkey.value] = line
            self.add(line)
        self.reset = QPushButton(_tr("Reset all"))
        self.reset.setObjectName("hotkeys.reset")
        self.reset.setCursor(Qt.CursorShape.PointingHandCursor)
        self.reset.setToolTip(_tr("Every hotkey back to its own key"))
        self.reset.clicked.connect(self._reset)
        self.add(right_row(self.reset))
        self._keys: dict[str, DictationKey | None] = {}
        """Each hotkey's key now, and dictation's (`DICTATE`), by name."""
        self._taken: frozenset[str] = frozenset()
        self._said: dict[str, str] = {}
        """A refusal said on a hotkey's line until its key next changes."""
        self.show_keys({}, ())

    @property
    def keys(self) -> Mapping[str, DictationKey | None]:
        """Each hotkey's key now, and dictation's (`DICTATE`), by name."""
        return self._keys

    def show_keys(
        self,
        keys: Mapping[str, str],
        taken: Collection[str],
        dictation: str | None = None,
    ) -> None:
        """Each hotkey's key now, as kept ("" none) - a hotkey not in
        `keys` has its default; `taken`: those another program has;
        `dictation`: dictation's key while it's on."""
        defaults = hotkey_defaults(os_words.platform())
        found: dict[str, DictationKey | None] = {
            DICTATE: DictationKey.parse(dictation) if dictation else None
        }
        for hotkey in ORDER:
            text = keys.get(hotkey.value)
            found[hotkey.value] = (
                defaults[hotkey]
                if text is None
                else DictationKey.parse(text)
                if text
                else None
            )
        changed = {n for n in self.lines if found.get(n) != self._keys.get(n)}
        self._said = {n: t for n, t in self._said.items() if n not in changed}
        self._keys, self._taken = found, frozenset(taken)
        shared = clashes(found)
        for name, line in self.lines.items():
            key = found[name]
            line.box.show_key(str(key) if key else "")
            line.clear.setEnabled(key is not None)
            if name in self._said:
                note = self._said[name]
            elif name in shared:
                note = _tr("{other} has this key too, and only it works.").format(
                    other=self.names[shared[name]]
                )
            elif name in self._taken:
                note = _tr("Another program has this key: choose another.")
            else:
                note = ""
            line.show_note(note)
        self.reset.setEnabled(any(found[h.value] != defaults[h] for h in ORDER))

    def _pressed(self, name: str, pressed: str) -> None:
        """A key pressed in a hotkey's box: refused with why, or asked for
        (`hotkey_wanted`) - unless it's the key already."""
        key = DictationKey.parse(pressed) if pressed else None
        if key is None:
            self._say(name, refusal_words(None))
            return
        who = holder(key, self._keys, but=name)
        if who is not None:
            self._say(
                name,
                _tr("{other} has that key: clear it there, or choose another.").format(
                    other=self.names[who]
                ),
            )
            return
        refused = hotkey_refusal(key)
        if refused is not None:
            self._say(name, refusal_words(refused))
            return
        self._say(name, "")
        if key != self._keys.get(name):
            self.hotkey_wanted.emit(name, pressed)

    def _clear(self, name: str) -> None:
        self._say(name, "")
        self.hotkey_wanted.emit(name, "")

    def _reset(self) -> None:
        self._said.clear()
        self.reset_wanted.emit()

    def _say(self, name: str, text: str) -> None:
        if text:
            self._said[name] = text
        else:
            self._said.pop(name, None)
        self.lines[name].show_note(text)


class HoldKeysCard(Card):
    """The keys held while the learner speaks: dictation's, named, and the
    way to Settings > Dictation where it's changed."""

    dictation_wanted = Signal()

    def __init__(self) -> None:
        super().__init__(_tr("Held while you speak"))
        self.setObjectName("settings.hold_keys")
        self.dictation = label("", "Dim", wrap=True)
        self.dictation.setObjectName("hotkeys.dictate")
        self.add(self.dictation)
        change = QPushButton(_tr("Change in Dictation"))
        change.setObjectName("hotkeys.dictate.change")
        change.setCursor(Qt.CursorShape.PointingHandCursor)
        change.clicked.connect(self.dictation_wanted)
        self.add(right_row(change))
        self.show_dictation(True, str(DEFAULT_KEY))  # as a new learner's, until told

    def show_dictation(self, on: bool, key: str) -> None:
        self.dictation.setText(
            _tr("Dictate: hold {key} and speak.").format(key=key_words(key))
            if on
            else _tr("Dictate: off. Turn it on in Dictation.")
        )


def window_keys() -> list[tuple[str, str]]:
    """The keys a window answers while it has the keyboard, as they're
    listed: what each does, and its key as this OS writes it."""
    find = shortcut_words(QKeySequence.StandardKey.Find)
    copy = shortcut_words(QKeySequence.StandardKey.Copy)
    return [
        (_tr("Search a transcript"), find),
        (_tr("Back to live in a transcript"), shortcut_words("End")),
        (_tr("Copy what's selected"), copy),
        (_tr("Close the search or the lookup"), shortcut_words("Esc")),
    ]


class WindowKeysCard(Card):
    """The keys windows answer while they have the keyboard - named, not
    changed (decision 0273)."""

    def __init__(self) -> None:
        super().__init__(
            _tr("In a window"),
            _tr("While a transcript or the lookup has the keyboard."),
        )
        self.setObjectName("settings.window_keys")
        grid = QGridLayout()
        grid.setHorizontalSpacing(12)
        grid.setVerticalSpacing(6)
        for row, (what, key) in enumerate(window_keys()):
            grid.addWidget(label(what, wrap=True), row, 0)
            grid.addWidget(label(key, "Dim"), row, 1)
        grid.setColumnStretch(0, 1)
        self.add(grid)
