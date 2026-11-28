"""Keep the import set stable while the composition root is split."""

from functools import cache
from pathlib import Path

from tools.import_set import (
    import_diff,
    loaded_modules,
    read_snapshot,
    snapshot_modules,
)

NOT_BEFORE_THE_WINDOW = (
    "numpy",
    "onnxruntime",
    "pydantic",
    "websockets",
    "nacl",
    "genanki",
    "urllib.request",
    "polyglotic_desktop.connection.protocol",
    "polyglotic_desktop.platform.speech_pipeline",
    # The install and network checks are split out of main in R1 (859, M4).
    "polyglotic_desktop.main.install_checks",
    "polyglotic_desktop.main.network_checks",
    # Mandarin in Traditional (375): read when a caption first needs it;
    # Thai's split: when a Thai pack opens (400)
    "polyglotic_desktop.adapters.traditional_table",
    "polyglotic_desktop.core.lexicon.traditional",
    "polyglotic_desktop.core.lexicon.thai",
)
"""Imported after the window's first paint (or never, from source)."""


@cache
def _imports_at_start() -> set[str]:
    return loaded_modules()


def test_importing_main_has_the_snapshot_import_set() -> None:
    changes = import_diff(read_snapshot(), snapshot_modules(_imports_at_start()))
    assert not changes, (
        f"Startup import set changed\n{changes}\n"
        "For an intentional change, run "
        'python -m tools.import_set --update --reason "..."'
    )


def test_importing_main_leaves_the_connection_and_speech_libraries_for_later() -> None:
    too_early = sorted(set(NOT_BEFORE_THE_WINDOW) & _imports_at_start())
    assert not too_early, f"Imported with main: {', '.join(too_early)}"


def test_import_set_reports_an_eager_numpy_import(tmp_path: Path) -> None:
    (tmp_path / "planted_start.py").write_text(
        "import polyglotic_desktop.main\nimport numpy\n", encoding="utf-8"
    )
    actual = snapshot_modules(loaded_modules("planted_start", import_path=tmp_path))
    changes = import_diff(read_snapshot(), actual)
    assert "Added modules\n" in changes
    assert "  + numpy" in changes.splitlines(), changes
    assert not any(line.startswith("  + numpy.") for line in changes.splitlines())


def test_the_interpreter_s_own_start_hooks_are_not_main_s_imports() -> None:
    """GitHub's Linux image loads a `sitecustomize` before any code runs."""
    recorded = snapshot_modules({"sitecustomize", "numpy.core", "json", "PySide6"})
    assert recorded == {"numpy", "PySide6"}
