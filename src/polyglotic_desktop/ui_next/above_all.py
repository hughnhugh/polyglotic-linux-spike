"""The windows that float over everything - the caption windows, their
popovers, the lookup and sentence cards, the dictation sign - as each OS
needs them (polyglotic-hq 546, 547, 550).

- `ABOVE_ALL`: on Linux, Qt's `X11BypassWindowManagerHint` beside the
  always-on-top flag - an *override-redirect* window, which the window
  manager doesn't manage and stacks above every window it does. 547's
  runs on GNOME 46 and 51 and KDE 6.8 found nothing else that stayed above
  a focused full-screen window (KWin hid the always-on-top flag alone
  under it every time); their order among themselves is then kept by
  `platform/linux/on_top.py`. Nothing on Windows and macOS, whose own
  `on_top` keeps them above.
- `set_click_through`: a window's clicks passing through it, or not,
  changed only while it isn't mapped - hidden, the flag changed, shown
  again - never as a live change to a mapped window's input shape, which
  GNOME's window manager ignores (547: the click then went to nobody over
  a Wayland window). Qt's own flag change hides the window first on
  every OS today; doing it here first keeps that true whatever Qt does.
"""

import sys

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QWidget

ABOVE_ALL = (
    Qt.WindowType.X11BypassWindowManagerHint
    if sys.platform.startswith("linux")
    else Qt.WindowType.Widget  # no flag
)
THROUGH = Qt.WindowType.WindowTransparentForInput


def set_click_through(widget: QWidget, through: bool, show: bool = True) -> None:
    """Clicks pass through `widget`'s window (`through`), or reach it:
    changed while it's hidden, and shown again if it showed - unless the
    caller shows it itself once it's ready (`show` False)."""
    if bool(widget.windowFlags() & THROUGH) == through:
        return
    showing = widget.isVisible()
    if showing:
        widget.hide()
    widget.setWindowFlag(THROUGH, through)
    if showing and show:
        widget.show()
