"""A caption window's preset dropdown: the bar's preset chip ("Video ▾")
opens it (polyglotic-hq 556, desktop decision 0264).

In three groups and a link, top to bottom:
- **Preset** - one choice, a template: Conversation, Video, film & TV,
  Learning, Custom and the learner's own, each with its line of what it's
  for. A click picks it and closes the dropdown;
- **Show** - one choice: Both, Original only or Translation only (the
  user's "captions only" and "translations only", in the app's words);
- **Add** - several on top: Word links or the quiet view (one or the
  other, as the strip's two buttons were: DECISIONS #205), Readings, My
  speech (in every window);
- **Customise presets…** under a rule: Settings > Presets.

What is ticked in Show and Add is saved in the chosen preset at once
(`main`, through `ui.use_presets`) and the dropdown stays open for another.
It is a `SettingsPopover`: it never takes the keyboard or the focus from
the app underneath, and Esc or a click elsewhere closes it.
"""

from typing import TYPE_CHECKING

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QApplication,
    QFrame,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from polyglotic_desktop.ui_next import style
from polyglotic_desktop.ui_next.controls import INSET, TICK, TickButton
from polyglotic_desktop.ui_next.settings_popover import (
    INK,
    LINE,
    SettingsPopover,
)
from polyglotic_desktop.ui_next.views.preset_menu import PresetMenu, Show

if TYPE_CHECKING:
    from polyglotic_desktop.ui_next.caption_window import CaptionWindow

WIDTH = 300
"""At 100 % text size, a little wider than the settings popover: the
presets' lines fit on one line each."""


def _tr(text: str) -> str:
    return QApplication.translate("Presets", text)


def preset_name(key: str) -> str:
    """A built-in preset's own name, in the interface's language."""
    names = {
        "everyday": _tr("Everyday"),
        "conversation": _tr("Conversation"),
        "video": _tr("Video, film & TV"),
        "learning": _tr("Learning"),
        "custom": _tr("Custom"),
    }
    return names.get(key, key)


def preset_note(key: str) -> str:
    """The line under a preset's name: what it's for."""
    notes = {
        "everyday": _tr("Every helper on: the app's own setup"),
        "conversation": _tr("Calls and chats: your speech too"),
        "video": _tr("Subtitles along the bottom, large"),
        "learning": _tr("Each line first, its translation after"),
        "custom": _tr("Your settings from before presets"),
    }
    return notes.get(key, _tr("One of your own"))


def show_name(show: Show) -> str:
    return {
        Show.BOTH: _tr("Both"),
        Show.ORIGINAL: _tr("Original only"),
        Show.TRANSLATION: _tr("Translation only"),
    }[show]


def chip_text(menu: PresetMenu, open_: bool) -> str:
    """The bar's preset chip: the chosen preset's name and its arrow."""
    return f"{menu.name or preset_name('everyday')} {'▴' if open_ else '▾'}"


class PresetPopover(SettingsPopover):
    """The preset dropdown of one caption window (or a joined window's
    column): made from the window's `preset_menu` each time it changes."""

    def __init__(self, window: "CaptionWindow") -> None:
        self._shown: PresetMenu | None = None
        super().__init__(window, window.keys, ("presets",))
        self.setObjectName("caption_window.presets")
        self.width_at_100 = WIDTH
        self.setFixedWidth(style.px(WIDTH))

    def _presets_row(self) -> QWidget:
        self.body = QWidget(self)
        self.column = QVBoxLayout(self.body)
        self.column.setContentsMargins(0, 0, 0, 0)
        self.column.setSpacing(2)
        return self.body

    @property
    def _caption_window(self) -> "CaptionWindow":
        return self.owner  # type: ignore[return-value]

    def refresh(self) -> None:
        menu = self._caption_window.preset_menu
        if menu != self._shown:
            self._shown = menu
            self._make(menu)
        self._fit()

    def _make(self, menu: PresetMenu) -> None:
        """Its rows afresh, from `menu`."""
        while self.column.count():
            item = self.column.takeAt(0)
            assert item is not None
            widget = item.widget()
            if widget is not None:
                widget.deleteLater()
        window = self._caption_window
        self.column.addWidget(self._heading(_tr("Preset")))
        for each in menu.items:
            note = preset_note(each.key)
            row = self._preset(each.name, note, each.key == menu.chosen)
            row.setObjectName(f"presets.preset.{each.key}")
            row.clicked.connect(lambda _=False, key=each.key: self._chose(key))
            self.column.addWidget(row)
        self.column.addSpacing(6)
        self.column.addWidget(self._heading(_tr("Show")))
        segments = QHBoxLayout()
        segments.setContentsMargins(INSET - 1, 0, 0, 0)
        segments.setSpacing(4)
        for show in Show:
            button = QPushButton(show_name(show), self.body)
            button.setObjectName(f"presets.show.{show.value}")
            button.setProperty("segment", True)
            button.setCheckable(True)
            button.setChecked(show is menu.show)
            button.setCursor(Qt.CursorShape.PointingHandCursor)
            button.clicked.connect(
                lambda _=False, chosen=show: window.lines_wanted.emit(chosen.value)
            )
            segments.addWidget(button)
        segments.addStretch(1)
        holder = QWidget(self.body)
        holder.setLayout(segments)
        self.column.addWidget(holder)
        self.column.addSpacing(6)
        self.column.addWidget(self._heading(_tr("Add")))
        links = self._tick(_tr("Word links"), menu.links, "links")
        links.setEnabled(
            menu.show is not Show.TRANSLATION
        )  # they join to what was said
        links.clicked.connect(
            lambda on: window.links_wanted.emit(on, window.readings())
        )
        quiet = self._tick(_tr("Quiet view"), menu.quiet, "quiet")
        quiet.clicked.connect(
            lambda on: window.quiet_wanted.emit(on, window.readings())
        )
        readings = self._tick(_tr("Readings"), menu.readings, "readings")
        readings.setToolTip(_tr("Pinyin, Jyutping or a respelling over the words"))
        readings.clicked.connect(
            lambda on: window.readings_wanted.emit(on, window.readings())
        )
        mine = self._tick(_tr("My speech"), menu.my_speech, "my_speech")
        mine.setToolTip(_tr("What you say, as “You”, in every window"))
        mine.clicked.connect(lambda on: window.my_speech_wanted.emit(on))
        for tick in (links, quiet, readings, mine):
            self.column.addWidget(tick)
        rule = QFrame(self.body)
        rule.setFixedHeight(1)
        rule.setStyleSheet(f"background: {LINE};")
        self.column.addSpacing(4)
        self.column.addWidget(rule)
        self.column.addSpacing(2)
        customise = QPushButton(_tr("Customise presets…"), self.body)
        customise.setObjectName("presets.customise")
        customise.setCursor(Qt.CursorShape.PointingHandCursor)
        customise.setToolTip(_tr("Edit, rename, reset or add presets in Settings"))
        customise.clicked.connect(self._customise)
        self.column.addWidget(customise)
        for child in self.body.findChildren(QWidget):
            child.setFocusPolicy(Qt.FocusPolicy.NoFocus)  # nothing takes the keyboard

    def _heading(self, text: str) -> QLabel:
        heading = QLabel(text, self.body)
        heading.setProperty("note", True)
        return heading

    def _preset(self, name: str, note: str, on: bool) -> TickButton:
        """A preset's row: a tick while chosen, its name, and under it in
        dim its line."""
        button = TickButton(self.body, INK[:2])
        button.setProperty("tick", True)
        button.setCheckable(True)
        button.setChecked(on)
        button.setCursor(Qt.CursorShape.PointingHandCursor)
        button.setAccessibleName(f"{name}. {note}")
        lines = QVBoxLayout(button)
        lines.setContentsMargins(INSET + style.px(TICK), 4, 8, 5)
        lines.setSpacing(0)
        for text, dim in ((name, False), (note, True)):
            line = QLabel(text, button)
            line.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
            line.setProperty("note", dim)  # the popover's dim notes, on its scale
            line.setStyleSheet("padding-left: 0px;")
            lines.addWidget(line)
        button.setMinimumHeight(lines.sizeHint().height())
        return button

    def _tick(self, text: str, on: bool, name: str) -> TickButton:
        button = TickButton(self.body, INK[:2])
        button.setText(text)
        button.setObjectName(f"presets.add.{name}")
        button.setProperty("tick", True)
        button.setCheckable(True)
        button.setChecked(on)
        button.setCursor(Qt.CursorShape.PointingHandCursor)
        return button

    def _chose(self, key: str) -> None:
        """A preset picked: the windows change under it, so it closes."""
        self.close()
        self._caption_window.preset_wanted.emit(key)

    def _customise(self) -> None:
        self.close()
        self._caption_window.customise_wanted.emit()
