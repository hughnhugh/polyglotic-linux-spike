"""The translation snapshot (859's N4, S4): a move keeps it; a lost string,
a changed context, comment or plural each change it."""

from tools.i18n import snapshot
from tools.i18n.extract import Message, read_text

HOME = """\
from PySide6.QtCore import QCoreApplication


def _tr(text: str) -> str:
    return QCoreApplication.translate("Home", text)


LISTEN = _tr("Start listening")
"""


def _messages(*modules: tuple[str, str]) -> list[Message]:
    return [m for file, source in modules for m in read_text(source, file).messages]


def test_a_move_to_another_module_keeps_the_snapshot() -> None:
    before = snapshot.text(_messages(("src/home.py", HOME)))
    moved = _messages(("src/home.py", ""), ("src/home_parts/listen.py", HOME))
    assert snapshot.text(moved) == before
    assert snapshot.changes(before, moved) == []


def test_a_moved_module_that_imports_its_tr_loses_the_string() -> None:
    """Planted fault: the moved code imports `_tr` instead of defining it,
    so the extractor (and Qt's lupdate) no longer sees the call."""
    before = snapshot.text(_messages(("src/home.py", HOME)))
    imported = "from src.home import _tr\n\nLISTEN = _tr('Start listening')\n"
    after = _messages(("src/home_parts/listen.py", imported))
    assert snapshot.changes(before, after) == [
        "lost: ('Home', 'Start listening', '', False)"
    ]


def test_a_moved_tr_with_another_context_changes_the_snapshot() -> None:
    """Planted fault: the copied wrapper names the new module's context."""
    before = snapshot.text(_messages(("src/home.py", HOME)))
    other = HOME.replace('translate("Home"', 'translate("HomeListen"')
    after = _messages(("src/home_parts/listen.py", other))
    assert snapshot.changes(before, after) == [
        "lost: ('Home', 'Start listening', '', False)",
        "new: ('HomeListen', 'Start listening', '', False)",
    ]


def test_each_lookup_field_counts_and_place_does_not() -> None:
    original = Message("Home", "%n caption(s)", "finished", True)
    expected = snapshot.text([original])
    for fault in (
        Message("MainWindow", original.source, original.comment, original.numerus),
        Message(original.context, "%n line(s)", original.comment, original.numerus),
        Message(original.context, original.source, "live", original.numerus),
        Message(original.context, original.source, original.comment, False),
    ):
        assert snapshot.text([fault]) != expected, fault
    first = Message("Home", "Listen", file="src/old.py", line=10)
    moved = Message("Home", "Listen", file="src/new.py", line=200)
    other = Message("Words", "Save")
    assert snapshot.text([first, other]) == snapshot.text([other, moved])
