"""The one help style (polyglotic-hq 1013): an ⓘ beside a label, a word-less
control's name and a choice's description in a box beside its open menu -
themed, wrapped, beside what it explains, on hover and keyboard focus, and
never Qt's native tooltip."""

import time

from PySide6.QtCore import QEvent, QPoint, QRect, QSize, Qt
from PySide6.QtGui import QFocusEvent, QFont, QHelpEvent
from PySide6.QtTest import QTest
from PySide6.QtWidgets import (
    QApplication,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QSlider,
    QToolButton,
    QWidget,
)

from polyglotic_desktop.ui_next import style
from polyglotic_desktop.ui_next.controls import (
    HELP_DELAY_MS,
    HELP_POPUP_CHARACTERS,
    HELP_ROLE,
    DescribedMenu,
    InfoIcon,
    Row,
    SwitchRow,
    describe,
    help_text,
    help_width_limit,
    hide_help,
    item_help,
    place_beside,
    set_help_tip,
    with_info,
)

LONG = (
    "Each sentence appears once, finished, about half a second after it "
    "ends. Nothing changes while you read."
)


def _popup() -> QLabel | None:
    return next(
        (
            w
            for w in QApplication.topLevelWidgets()
            if isinstance(w, QLabel) and w.objectName() == "HelpPopup" and w.isVisible()
        ),
        None,
    )


def _keyboard_focus(widget: QWidget) -> None:
    event = QFocusEvent(QEvent.Type.FocusIn, Qt.FocusReason.TabFocusReason)
    QApplication.sendEvent(widget, event)


def test_help_is_never_a_native_tooltip(qapp: QApplication) -> None:
    """Qt paints a native tooltip as one long strip across the window: no
    control, action or item gets one, and Qt's own copy onto a tool button
    (its action's words) is cleared as it comes."""
    button = QToolButton()
    set_help_tip(button, "Save caption")
    assert not button.toolTip() and help_text(button) == "Save caption"
    menu = DescribedMenu()
    action = menu.add_described_action("Whole captions", LONG)
    assert not menu.toolTipsVisible()
    assert help_text(action) == LONG
    strip = QToolButton()
    strip.setDefaultAction(action)  # Qt copies the action's words onto it
    set_help_tip(strip, "")
    action.setText("Whole")  # ...and again when the action changes
    assert not strip.toolTip()
    item = QListWidgetItem("Discord")
    set_help_tip(item, "Captioning starts when Discord plays sound")
    assert not item.toolTip() and help_text(item).startswith("Captioning")
    assert item.data(HELP_ROLE) == help_text(item)
    event = QHelpEvent(QEvent.Type.ToolTip, QPoint(), QPoint())
    assert QApplication.sendEvent(button, event)  # Qt's event, swallowed


def test_an_info_icon_shows_on_keyboard_focus_hover_and_click(
    qapp: QApplication,
) -> None:
    holder = QWidget()
    icon = InfoIcon("What the panel behind captions is for", "Background", holder)
    holder.show()
    assert icon.focusPolicy() & Qt.FocusPolicy.TabFocus  # a Tab stop
    assert icon.accessibleName() == "About Background"
    assert icon.accessibleDescription() == help_text(icon)
    _keyboard_focus(icon)
    shown = _popup()
    assert shown is not None and shown.text() == help_text(icon)
    hide_help()
    QApplication.sendEvent(icon, QEvent(QEvent.Type.Enter))
    assert _popup() is None  # not at once: only on resting
    QTest.qWait(HELP_DELAY_MS + 100)
    # offscreen, the pointer's never over it: resting shows it via Qt's
    # own tooltip event instead, as on a desktop
    QApplication.sendEvent(icon, QHelpEvent(QEvent.Type.ToolTip, QPoint(), QPoint()))
    assert _popup() is not None
    QApplication.sendEvent(icon, QEvent(QEvent.Type.Leave))
    assert _popup() is None
    icon.click()
    assert _popup() is not None
    hide_help()
    holder.close()


def test_the_popup_is_wrapped_themed_and_beside_never_over(qapp: QApplication) -> None:
    holder = QWidget()
    holder.setGeometry(300, 300, 200, 40)
    icon = InfoIcon(LONG, "Whole captions", holder)
    holder.show()
    icon.hover.show()
    popup = _popup()
    assert popup is not None and popup.wordWrap()
    assert popup.width() <= help_width_limit(popup)
    words = popup.fontMetrics().averageCharWidth() * HELP_POPUP_CHARACTERS
    assert popup.width() <= words + 2 * popup.margin() + 2  # about 40 a line
    assert popup.height() >= popup.heightForWidth(popup.width())  # never cut off
    assert style.current()["SURFACE_2"] in popup.styleSheet()
    spot = QRect(icon.mapToGlobal(QPoint(0, 0)), icon.size())
    assert not popup.geometry().intersects(spot)  # beside, never over
    assert popup.geometry().left() > spot.right()  # after it, left to right
    hide_help()
    holder.close()


def test_a_short_name_is_as_narrow_as_it_needs(qapp: QApplication) -> None:
    button = QToolButton()
    button.move(400, 400)
    set_help_tip(button, "Save caption")
    button.show()
    QApplication.sendEvent(button, QHelpEvent(QEvent.Type.ToolTip, QPoint(), QPoint()))
    popup = _popup()
    assert popup is not None
    assert popup.width() < help_width_limit(popup) // 2
    hide_help()
    button.close()


def test_placement_stays_on_screen_at_both_edges_both_ways_at_200_percent(
    qapp: QApplication,
) -> None:
    """Beside what it explains, after it in the reading direction - before
    it, right to left - and kept on the screen at its edges."""
    screen = QRect(0, 0, 1280, 720)
    size = QSize(2 * 300, 120)  # 200 % text: twice as wide
    for rtl in (False, True):
        for area in (QRect(1240, 300, 30, 20), QRect(10, 300, 30, 20)):
            at = QRect(place_beside(area, size, screen, rtl), size)
            assert screen.contains(at), (rtl, area, at)
            assert not at.intersects(area), (rtl, area, at)
    middle = QRect(620, 300, 30, 20)  # room on both sides
    assert (
        QRect(place_beside(middle, size, screen, False), size).left() > middle.right()
    )
    assert QRect(place_beside(middle, size, screen, True), size).right() < middle.left()
    wide = QRect(0, 300, 1280, 20)  # a row as wide as the screen: under it
    under = QRect(place_beside(wide, size, screen, False), size)
    assert under.top() > wide.bottom() and screen.contains(under)


def test_chinese_and_arabic_wrap_right_to_left_at_200_percent(
    qapp: QApplication,
) -> None:
    """The app has no right-to-left interface language yet: a mirrored
    layout stands in for Arabic (as 1009's did)."""
    app_font = QApplication.font()
    doubled = QFont(app_font)  # 200 % text
    if app_font.pointSizeF() > 0:
        doubled.setPointSizeF(app_font.pointSizeF() * 2)
    else:
        doubled.setPixelSize(app_font.pixelSize() * 2)
    QApplication.setFont(doubled)
    try:
        holder = QWidget()
        holder.setLayoutDirection(Qt.LayoutDirection.RightToLeft)
        edge = QApplication.primaryScreen().availableGeometry().right()
        holder.setGeometry(edge - 60, 300, 50, 40)  # room on its left only
        icon = InfoIcon(
            "中文说明会自动换行，不会被截断。 شرح عربي يلتف داخل الصندوق ولا يُقطع.",
            "",
            holder,
        )
        holder.show()
        icon.hover.show()
        popup = _popup()
        assert popup is not None and popup.wordWrap()
        assert popup.layoutDirection() == Qt.LayoutDirection.RightToLeft
        spot = QRect(icon.mapToGlobal(QPoint(0, 0)), icon.size())
        assert popup.geometry().right() < spot.left()  # before it, on its left
        assert popup.height() >= popup.heightForWidth(popup.width())
        screen = popup.screen().availableGeometry()
        assert screen.contains(popup.geometry())
        hide_help()
        holder.close()
    finally:
        QApplication.setFont(app_font)


def test_a_row_s_explanation_is_behind_an_info_icon_beside_its_title(
    qapp: QApplication,
) -> None:
    """Never on the whole row, and none when it's the line shown under it."""
    slider = QSlider()
    row = Row("Live updates every", "", slider, tip="The first waits a second.")
    assert row.info is not None and help_text(row.info) == "The first waits a second."
    assert not help_text(row) and not help_text(slider)
    assert slider.accessibleDescription() == "The first waits a second."
    said = Row(
        "Fade", "Captions disappear after.", QSlider(), tip="Captions disappear after."
    )
    assert said.info is None
    switch = SwitchRow(
        "Pinyin above Chinese", "", "look.pinyin", "Readings over the words"
    )
    assert switch.info is not None and not help_text(switch)
    label = with_info(QPushButton("Delete"), "Removes its saved words too", "Delete")
    (icon,) = label.findChildren(InfoIcon)
    assert help_text(icon) == "Removes its saved words too"


def test_a_menu_describes_its_highlighted_choice_beside_it(qapp: QApplication) -> None:
    menu = DescribedMenu()
    first = menu.add_described_action("Steady", "Words appear one by one.")
    second = menu.add_described_action("Whole captions", LONG)
    plain = menu.addAction("Plain choice")
    menu.popup(QPoint(200, 200))
    qapp.processEvents()
    menu.setActiveAction(first)
    QTest.keyClick(menu, Qt.Key.Key_Down)  # the keyboard, as hover does
    qapp.processEvents()
    assert menu.activeAction() is second
    box = menu.description
    assert box.isVisible() and box.text() == LONG and box.wordWrap()
    assert box.height() >= box.heightForWidth(box.width())  # never cut off
    assert not box.geometry().intersects(menu.frameGeometry())  # beside it
    menu._show_description(plain)
    assert not box.isVisible()  # a choice with nothing to say: no box
    menu.close()


def test_a_dropdown_row_is_described_beside_the_dropdown(qapp: QApplication) -> None:
    dropdown = QWidget()
    dropdown.setGeometry(300, 200, 280, 200)
    row = QPushButton("Readings", dropdown)
    describe(row, "Pinyin, Jyutping or a respelling over the words")
    dropdown.show()
    QApplication.sendEvent(row, QEvent(QEvent.Type.Enter))
    box = dropdown.findChild(QWidget, "MenuDescription")
    assert box is not None and box.isVisible()
    assert not box.geometry().intersects(dropdown.frameGeometry())
    QApplication.sendEvent(row, QEvent(QEvent.Type.Leave))
    assert not box.isVisible()
    dropdown.close()


def test_an_item_shows_its_help_beside_it_and_never_qt_s(qapp: QApplication) -> None:
    view = QListWidget()
    view.setGeometry(300, 300, 240, 120)
    item = QListWidgetItem("Discord - starts when it plays")
    set_help_tip(item, "Captioning starts when Discord plays sound")
    view.addItem(item)
    item_help(view)
    view.show()
    qapp.processEvents()
    cell = view.visualItemRect(item)
    event = QHelpEvent(
        QEvent.Type.ToolTip, cell.center(), view.viewport().mapToGlobal(cell.center())
    )
    assert QApplication.sendEvent(view.viewport(), event)  # swallowed: no native strip
    popup = _popup()
    assert popup is not None and popup.text() == help_text(item)
    hide_help()
    view.close()


def test_opening_a_menu_and_its_description_is_within_the_click_budget(
    qapp: QApplication,
) -> None:
    menu = DescribedMenu()
    action = menu.add_described_action("Whole captions", LONG)
    started = time.perf_counter()
    menu.popup(QPoint(20, 20), action)
    qapp.processEvents()
    menu.setActiveAction(action)
    QTest.keyClick(menu, Qt.Key.Key_Home)
    qapp.processEvents()
    assert menu.description.isVisible()
    assert (time.perf_counter() - started) * 1000 < 30  # budgets.CLICK
    menu.close()
    icon = InfoIcon(LONG, "Whole captions")
    icon.show()
    started = time.perf_counter()
    icon.click()
    assert _popup() is not None
    assert (time.perf_counter() - started) * 1000 < 30
    hide_help()
    icon.close()


def test_a_view_going_with_its_item_help_raises_nothing(qapp: QApplication) -> None:
    """Its viewport's last events come after the view itself has gone: the
    Words table raised from each test's teardown until the filter checked."""
    holder = QWidget()
    view = QListWidget(holder)
    view.addItem("Discord")
    item_help(view)
    holder.show()
    qapp.processEvents()
    holder.deleteLater()
    qapp.processEvents()  # no RuntimeError from the filter
