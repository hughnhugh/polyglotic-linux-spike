"""A menu which can explain its highlighted actions beside the menu.

The two interface packages are peers and may not import one another.  This
small Qt helper contains the interaction they share; each interface supplies
the function which draws and places its description in that interface's help
style.
"""

from collections.abc import Callable

from PySide6.QtCore import QEvent, QObject, QPoint, QRect, Qt, QTimer
from PySide6.QtGui import QAction, QFontMetrics
from PySide6.QtWidgets import QApplication, QLabel, QMenu, QWidget
from shiboken6 import isValid

ShowDescription = Callable[[QWidget, QRect, str, QLabel], None]

DESCRIPTION_CHARACTERS = 40
"""The box's widest line, in average characters (ui_next's
`HELP_POPUP_CHARACTERS`, which `ui` may not import): a short paragraph."""
DESCRIPTION_MARGIN_PX = 8
"""Inside the box, around its text (4-12)."""
DESCRIPTION_RADIUS_PX = 6
"""The box's rounded corners (0-8), as the help style's."""
DESCRIPTION_GAP_PX = 8
"""Between the menu and the box (4-16), so they read as two things."""
SCREEN_EDGE_PX = 4
"""The least room kept between the box and the screen's edge (0-8)."""


def show_description(
    window: QWidget,
    row: QRect,
    text: str,
    box: QLabel,
    colours: tuple[str, str, str] | None = None,
) -> None:
    """Draw a wrapped description beside ``row``: in ``colours``
    (background, text, border) when the menu draws its own (a dark tray
    menu's style sheet), else in the menu's palette."""
    palette = window.palette()
    background, ink, border = colours or (
        palette.window().color().name(),
        palette.windowText().color().name(),
        palette.mid().color().name(),
    )
    box.setWindowFlags(
        Qt.WindowType.ToolTip
        | Qt.WindowType.FramelessWindowHint
        | Qt.WindowType.WindowStaysOnTopHint
        | Qt.WindowType.WindowDoesNotAcceptFocus
        | Qt.WindowType.WindowTransparentForInput
    )
    box.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating)
    box.setTextFormat(Qt.TextFormat.PlainText)
    box.setFont(QApplication.font())
    box.setMargin(DESCRIPTION_MARGIN_PX)
    box.setStyleSheet(
        f"QLabel {{ background: {background}; color: {ink};"
        f" border: 1px solid {border}; border-radius: {DESCRIPTION_RADIUS_PX}px; }}"
    )
    box.setText(text)
    screen = window.screen() or QApplication.primaryScreen()
    available = screen.availableGeometry()
    metrics = QFontMetrics(box.font())
    width = min(
        metrics.horizontalAdvance(text) + 2 * box.margin() + 4,
        metrics.averageCharWidth() * DESCRIPTION_CHARACTERS + 2 * box.margin() + 2,
        available.width() - 2 * SCREEN_EDGE_PX,
    )
    box.setFixedSize(width, box.heightForWidth(width))
    frame = window.frameGeometry()
    # right() and bottom() are the last pixel's, hence the + 1
    after = frame.right() + 1 + DESCRIPTION_GAP_PX
    before = frame.left() - DESCRIPTION_GAP_PX - width
    x = after if after + width <= available.right() else before
    if x < available.left():
        x = max(
            available.left() + SCREEN_EDGE_PX,
            min(frame.left(), available.right() - width),
        )
        y = frame.bottom() + 1 + DESCRIPTION_GAP_PX
    else:
        y = row.top()
    y = max(available.top() + SCREEN_EDGE_PX, min(y, available.bottom() - box.height()))
    box.move(QPoint(x, y))
    box.show()
    box.raise_()


class DescribedMenu(QMenu):
    """Show an action's description beside its highlighted menu row."""

    def __init__(
        self,
        show_description: ShowDescription,
        parent: QWidget | None = None,
        description: QLabel | None = None,
    ) -> None:
        super().__init__(parent)
        self._show_beside = show_description
        self.description = description or QLabel()
        self.description.setObjectName("MenuDescription")
        self.description.setWordWrap(True)
        self.hovered.connect(self._show_description)
        self.aboutToHide.connect(self.description.hide)
        self.destroyed.connect(self.description.deleteLater)
        self.installEventFilter(self)

    def add_described_action(self, name: str, description: str) -> QAction:
        """Add a choice with a short name and a full description."""
        action = self.addAction(name)
        self.describe(action, description)
        return action

    def describe(self, action: QAction, description: str) -> None:
        """Set ``action``'s description; an empty description shows no box."""
        action.setProperty("description", description)
        if self.activeAction() is action and self.isVisible():
            self._show_description(action)

    def _show_description(self, action: QAction) -> None:
        text = action.property("description")
        if not isinstance(text, str) or not text or not action.isVisible():
            self.description.hide()
            return
        item = self.actionGeometry(action)
        row = QRect(self.mapToGlobal(item.topLeft()), item.size())
        self._show_beside(self, row, text, self.description)

    def eventFilter(self, watched: QObject, event: QEvent) -> bool:
        """Explain keyboard selection exactly as mouse hover does."""
        if watched is self and event.type() in (
            QEvent.Type.KeyPress,
            QEvent.Type.FocusIn,
        ):
            QTimer.singleShot(0, self._show_active_description)
        return super().eventFilter(watched, event)

    def _show_active_description(self) -> None:
        if not isValid(self) or not self.isVisible():
            return
        action = self.activeAction()
        if action is not None:
            self._show_description(action)
