"""The UI lab's tooltip check (polyglotic-hq 1013): each fault it fails a
state for, planted in a made-up window - and the one style passing it."""

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QApplication,
    QComboBox,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QMenu,
    QPushButton,
    QSlider,
    QTabBar,
    QTableWidget,
    QTableWidgetItem,
    QToolButton,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)
from tests.ui.fakes import make_app
from tools.ui_lab.tooltips import (
    description_is_cut_off,
    native_faults,
    state_tooltip_faults,
)

from polyglotic_desktop.ui_next.controls import (
    DescribedMenu,
    InfoIcon,
    Row,
    describe,
    help_width_limit,
    set_help_tip,
    show_help,
)


@pytest.fixture(scope="module")
def app() -> QApplication:
    found = QApplication.instance() or QApplication([])
    assert isinstance(found, QApplication)
    return found


def _faults(root: QWidget) -> list[str]:
    return [fault for _widget, fault in state_tooltip_faults(root)]


def _state() -> tuple[QWidget, QVBoxLayout]:
    state = QWidget()
    return state, QVBoxLayout(state)


def test_a_native_tooltip_on_a_widget_fails(app: QApplication) -> None:
    state, column = _state()
    button = QPushButton("Mode")
    button.setToolTip("Qt's own long strip")
    column.addWidget(button)
    assert "native tooltip" in _faults(state)


@pytest.mark.parametrize("kind", ["list", "table", "tree", "combo"])
def test_a_native_tooltip_on_an_item_fails(app: QApplication, kind: str) -> None:
    """The walker saw only widgets: a list item's native tooltip - Settings'
    app list's - passed (1033's final read)."""
    state, column = _state()
    view: QWidget
    if kind == "list":
        view = QListWidget()
        item = QListWidgetItem("Discord - starts when it plays")
        item.setToolTip("Captioning starts when Discord plays sound")
        view.addItem(item)
    elif kind == "table":
        view = QTableWidget(1, 2)
        cell = QTableWidgetItem("word")
        cell.setToolTip("Open dictionary")
        view.setItem(0, 1, cell)
    elif kind == "tree":
        view = QTreeWidget()
        parent = QTreeWidgetItem(["Saved"])
        child = QTreeWidgetItem(["猫"])
        child.setToolTip(0, "cat")
        parent.addChild(child)
        view.addTopLevelItem(parent)
    else:
        view = QComboBox()
        view.addItem("Detect")
        view.setItemData(0, "Finds the language each time", Qt.ItemDataRole.ToolTipRole)
    column.addWidget(view)
    assert "native tooltip on an item" in _faults(state)


def test_a_menu_showing_its_choices_tooltips_and_a_tab_s_fail(
    app: QApplication,
) -> None:
    menu = QMenu()
    action = menu.addAction("Say it")
    action.setToolTip("How to add a voice")
    menu.setToolTipsVisible(True)
    assert "menu shows its choices' native tooltips" in _faults(menu)
    tabs = QTabBar()
    tabs.addTab("Look")
    tabs.setTabToolTip(0, "How captions look")
    assert "native tooltip on a tab" in _faults(tabs)


def test_help_repeating_what_is_shown_fails(app: QApplication) -> None:
    state, column = _state()
    column.addWidget(QLabel("Pinyin above Chinese"))
    column.addWidget(InfoIcon("Pinyin above Chinese"))
    assert "help repeats visible text" in _faults(state)


def test_help_on_a_label_a_labelled_control_or_a_row_fails(app: QApplication) -> None:
    state, column = _state()
    title = QLabel("Machine draft")
    set_help_tip(title, "No native speaker has checked it yet")
    button = QPushButton("Reset all")
    set_help_tip(button, "Every hotkey back to its own key")
    row = QWidget()
    QVBoxLayout(row).addWidget(QLabel("Discord playing"))
    set_help_tip(row, "Caption Discord")
    for each in (title, button, row):
        column.addWidget(each)
    faults = _faults(state)
    assert "help on a label: put it behind an ⓘ" in faults
    assert "help on a labelled control: put it behind an ⓘ" in faults
    assert "help on a whole row: put it behind an ⓘ" in faults


def test_the_one_style_passes(app: QApplication) -> None:
    """An ⓘ, a word-less control's name, a code's, a chip's, a choice's
    description and a row's ⓘ: nothing to fail."""
    state, column = _state()
    glyph = QToolButton()
    set_help_tip(glyph, "Save caption")
    code = QToolButton()
    code.setText("A+")
    set_help_tip(code, "Bigger text (Ctrl+wheel)")
    chip = QToolButton()
    chip.setText("EN ▾")
    chip.setProperty("chip", True)
    set_help_tip(chip, "Translate into")
    slider = QSlider()
    set_help_tip(slider, "Semibold")
    choice = QPushButton("Whole captions")
    describe(choice, "Each sentence appears once, finished.")
    row = Row("Live updates every", "", QSlider(), tip="The first waits a second.")
    for each in (glyph, code, chip, slider, choice, row):
        column.addWidget(each)
    assert row.info is not None
    assert _faults(state) == []
    assert native_faults(state) == []  # and set_help_tip never makes one


def test_the_tray_menu_uses_descriptions_not_native_tooltips(
    app: QApplication,
) -> None:
    desktop = make_app()
    menu = desktop.tray_menu
    assert desktop.lock_windows.property("description")
    assert desktop.show_delay.property("description")
    assert desktop.quit.property("description")
    assert native_faults(menu) == []
    desktop.close()


def test_a_help_popup_wider_than_the_limit_or_cut_off_fails(app: QApplication) -> None:
    anchor = QPushButton("A+")
    wide = show_help(anchor, "A short name")
    wide.setFixedWidth(help_width_limit(wide) + 40)
    assert "help popup is wider than the limit" in _faults(wide)
    wide.hide()
    menu = DescribedMenu()
    clipped = menu.description
    clipped.setText("A description that needs more than one line to be read")
    clipped.setFixedSize(80, 5)
    assert description_is_cut_off(clipped)
    assert "help popup is cut off" in _faults(clipped)


def test_an_icon_only_button_s_hidden_words_are_not_shown_words(
    app: QApplication,
) -> None:
    """A caption window's strip buttons show a glyph; their action's words
    are never drawn, so a name in the one style repeats nothing."""
    state, column = _state()
    glyph = QToolButton()
    glyph.setText("Settings")  # its action's words, as setDefaultAction gives it
    glyph.setIcon(
        app.style().standardIcon(app.style().StandardPixmap.SP_TitleBarMenuButton)
    )
    set_help_tip(glyph, "Settings")
    column.addWidget(glyph)
    assert _faults(state) == []
    words = QToolButton()
    words.setText("Settings")  # no icon: Qt draws the words
    set_help_tip(words, "Settings")
    column.addWidget(words)
    assert "help repeats visible text" in _faults(state)
