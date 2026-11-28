"""The one help style, checked in every UI lab state (polyglotic-hq 1013).

Help is never Qt's native tooltip (one long strip across the window); it's
one wrapped popup beside what it's about: behind an ⓘ (`InfoIcon`), as the
name of a control that shows no words, or in the box beside an open menu
(`DescribedMenu`, `describe`). A state fails:

- with a native tooltip anywhere Qt could paint one: a widget's, an item's
  in a list, table, tree or combo box (Qt's ToolTipRole), a tab's, or a
  menu that shows its choices' (`toolTipsVisible`);
- with help that only repeats words shown in the window;
- with help hanging on a label, a labelled control or a row: an
  explanation goes behind an ⓘ beside the label;
- with a help popup or a menu's description box wider than
  `HELP_POPUP_CHARACTERS` allows, or cut off.
"""

from PySide6.QtCore import (
    QAbstractItemModel,
    QAbstractListModel,
    QAbstractTableModel,
    QModelIndex,
    Qt,
)
from PySide6.QtWidgets import (
    QAbstractButton,
    QAbstractItemView,
    QComboBox,
    QLabel,
    QMenu,
    QTabBar,
    QToolButton,
    QWidget,
)

from polyglotic_desktop.ui_next.controls import (
    InfoIcon,
    help_text,
    help_width_limit,
    same_words,
    shows_words,
)

MOST_ITEMS = 500
"""How many of a list's or table's items are looked at, its first (100-
5000): enough for every list a state shows, and the check stays quick."""

POPUPS = ("HelpPopup", "MenuDescription", "strip_tip")
"""The object names of the one style's windows: the shared help popup, a
menu's description box and a caption window's strip label."""


def _says(widget: QWidget) -> str:
    """The words a label or a button shows ("" for anything else). A tool
    button showing only its icon keeps its action's words unseen: Qt draws
    them only when there's no icon (a strip's glyph buttons)."""
    if (
        isinstance(widget, QToolButton)
        and not widget.icon().isNull()
        and widget.toolButtonStyle() == Qt.ToolButtonStyle.ToolButtonIconOnly
    ):
        return ""
    if isinstance(widget, (QAbstractButton, QLabel)) and not widget.isHidden():
        return widget.text()
    return ""


def _visible(widget: QWidget, root: QWidget) -> bool:
    return widget is root or widget.isVisibleTo(root)


def native_faults(root: QWidget) -> list[tuple[QWidget, str]]:
    """Every native tooltip in `root` that Qt could paint."""
    found: list[tuple[QWidget, str]] = []
    for widget in (root, *root.findChildren(QWidget)):
        if widget.toolTip():
            found.append((widget, "native tooltip"))
        if isinstance(widget, QMenu) and widget.toolTipsVisible():
            found.append((widget, "menu shows its choices' native tooltips"))
        if isinstance(widget, QTabBar) and any(
            widget.tabToolTip(i) for i in range(widget.count())
        ):
            found.append((widget, "native tooltip on a tab"))
        model: QAbstractItemModel | None = None
        if isinstance(widget, (QAbstractItemView, QComboBox)):
            model = widget.model()
        if model is not None and _item_has_tooltip(model):
            found.append((widget, "native tooltip on an item"))
    return found


def _item_has_tooltip(model: QAbstractItemModel) -> bool:
    """Whether any of `model`'s first `MOST_ITEMS` items, at any depth, has
    Qt's ToolTipRole."""
    # a list's model has one column and no children, a table's no children:
    # Qt keeps those methods private on them
    listed = isinstance(model, QAbstractListModel)
    flat = listed or isinstance(model, QAbstractTableModel)
    seen = 0
    parents = [QModelIndex()]
    while parents and seen < MOST_ITEMS:
        parent = parents.pop()
        columns = 1 if listed else max(1, model.columnCount(parent))
        for row in range(model.rowCount(parent)):
            for column in range(columns):
                index = model.index(row, column, parent)
                seen += 1
                if index.data(Qt.ItemDataRole.ToolTipRole):
                    return True
                if column == 0 and not flat and model.hasChildren(index):
                    parents.append(index)
                if seen >= MOST_ITEMS:
                    return False
    return False


def _near(widget: QWidget, root: QWidget) -> list[str]:
    """The words shown where `widget`'s help is read: its own, and for an ⓘ,
    its row's (its parent's) - not the help's own popup or box."""
    parent = widget.parentWidget()
    place = parent if isinstance(widget, InfoIcon) and parent is not None else widget
    found = [_says(widget)]
    for each in (place, *place.findChildren(QWidget)):
        if each is widget or each.objectName() in POPUPS or not _visible(each, root):
            continue
        found.append(_says(each))
    return [words for words in found if words]


def help_faults(root: QWidget) -> list[tuple[QWidget, str]]:
    """Help in `root` that repeats words shown beside it, or hangs where an
    ⓘ should."""
    found: list[tuple[QWidget, str]] = []
    for widget in (root, *root.findChildren(QWidget)):
        words = help_text(widget)
        if not words or not _visible(widget, root):
            continue
        if any(same_words(words, text) for text in _near(widget, root)):
            found.append((widget, "help repeats visible text"))
        if isinstance(widget, InfoIcon) or widget.property("description"):
            continue  # an ⓘ's, or a choice's in the box beside its menu
        if widget.property("helpText") is None:
            continue
        if isinstance(widget, QLabel) and widget.text():
            found.append((widget, "help on a label: put it behind an ⓘ"))
        elif isinstance(widget, QAbstractButton):
            if shows_words(_says(widget)) and not widget.property("chip"):
                found.append((widget, "help on a labelled control: put it behind an ⓘ"))
        elif any(
            shows_words(_says(child)) and _visible(child, widget)
            for child in widget.findChildren(QWidget)
        ):
            found.append((widget, "help on a whole row: put it behind an ⓘ"))
    return found


def description_is_cut_off(box: QLabel) -> bool:
    """Whether a wrapped help popup has less height than its words need."""
    return box.height() < box.heightForWidth(box.width())


def popup_faults(root: QWidget) -> list[tuple[QWidget, str]]:
    """The one style's windows showing in `root` (or `root` itself, one of
    them) that are wider than the limit or cut off."""
    found: list[tuple[QWidget, str]] = []
    for box in (root, *root.findChildren(QLabel)):
        if not isinstance(box, QLabel) or box.objectName() not in POPUPS:
            continue
        if not box.isVisible() and box is not root:
            continue
        if box.width() > help_width_limit(box) + 1:
            found.append((box, "help popup is wider than the limit"))
        if box.wordWrap() and description_is_cut_off(box):
            found.append((box, "help popup is cut off"))
    return found


def state_tooltip_faults(root: QWidget) -> list[tuple[QWidget, str]]:
    """Every tooltip fault in a real lab state's window `root`."""
    return native_faults(root) + help_faults(root) + popup_faults(root)
