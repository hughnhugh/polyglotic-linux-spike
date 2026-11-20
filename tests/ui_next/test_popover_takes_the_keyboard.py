"""On Linux a caption window's settings popover takes the keyboard while
it's open (polyglotic-hq 570): the app, an X11 program, hears no key or
click meant for a Wayland app, so Esc and a click elsewhere reach the
popover only as its own Esc and its losing the keyboard. 570's runs on
GitHub's runners (GNOME 46 and 51, KDE 6.8) found a window that takes the
keyboard closed on both, where a real Qt.Popup and today's popover didn't."""

from collections.abc import Iterator

import pytest
from PySide6.QtCore import QEvent, Qt
from PySide6.QtGui import QKeyEvent
from PySide6.QtWidgets import QApplication
from tests.ui_next.test_caption_window import window  # noqa: F401 - the fixture

from polyglotic_desktop.ui_next import settings_popover
from polyglotic_desktop.ui_next.caption_window import CaptionWindow
from polyglotic_desktop.ui_next.settings_popover import SettingsPopover


@pytest.fixture
def opened(
    window: CaptionWindow,  # noqa: F811 - the fixture
    monkeypatch: pytest.MonkeyPatch,
) -> Iterator[tuple[CaptionWindow, SettingsPopover]]:
    monkeypatch.setattr(settings_popover, "POPOVERS_TAKE_THE_KEYBOARD", True)
    window.hovered = True
    window._show_band(True)
    window.toggle_settings()
    popover = window.popover
    assert popover is not None and popover.isVisible()
    yield window, popover


def told(popover: SettingsPopover, kind: QEvent.Type) -> None:
    QApplication.sendEvent(popover, QEvent(kind))


def test_its_window_can_take_the_keyboard(
    opened: tuple[CaptionWindow, SettingsPopover],
) -> None:
    caption, popover = opened
    assert popover.takes_the_keyboard
    flags = popover.windowFlags()
    assert not flags & Qt.WindowType.WindowDoesNotAcceptFocus
    assert not flags & Qt.WindowType.X11BypassWindowManagerHint  # managed: focusable
    assert not popover.testAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating)
    assert caption.windowFlags() & Qt.WindowType.WindowDoesNotAcceptFocus  # not it


def test_losing_the_keyboard_closes_it(
    opened: tuple[CaptionWindow, SettingsPopover],
) -> None:
    """A click anywhere else: another window takes the keyboard back."""
    caption, popover = opened
    told(popover, QEvent.Type.WindowDeactivate)  # before it had it: stays
    assert popover.isVisible()
    told(popover, QEvent.Type.WindowActivate)
    told(popover, QEvent.Type.WindowDeactivate)
    assert not popover.isVisible()
    caption.toggle_settings()  # again: the same, each time
    assert popover.isVisible()
    told(popover, QEvent.Type.WindowDeactivate)
    assert popover.isVisible()
    told(popover, QEvent.Type.WindowActivate)
    told(popover, QEvent.Type.WindowDeactivate)
    assert not popover.isVisible()


def test_esc_closes_it(opened: tuple[CaptionWindow, SettingsPopover]) -> None:
    _, popover = opened
    told(popover, QEvent.Type.WindowActivate)
    QApplication.sendEvent(
        popover,
        QKeyEvent(
            QEvent.Type.KeyPress, Qt.Key.Key_Escape, Qt.KeyboardModifier.NoModifier
        ),
    )
    assert not popover.isVisible()


def test_on_windows_and_a_mac_it_never_takes_the_keyboard(
    window: CaptionWindow,  # noqa: F811 - the fixture
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(settings_popover, "POPOVERS_TAKE_THE_KEYBOARD", False)
    window.hovered = True
    window._show_band(True)
    window.toggle_settings()
    popover = window.popover
    assert popover is not None and not popover.takes_the_keyboard
    assert popover.windowFlags() & Qt.WindowType.WindowDoesNotAcceptFocus
    told(popover, QEvent.Type.WindowActivate)
    told(popover, QEvent.Type.WindowDeactivate)
    assert popover.isVisible()  # Windows' key state closes it (`keys`)
