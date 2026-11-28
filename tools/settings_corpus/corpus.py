"""Real-shaped settings corpus loader, resolver and 128-field coverage report."""

import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, fields
from pathlib import Path
from typing import Any

from polyglotic_desktop.ui import use_presets
from polyglotic_desktop.ui.settings import AppSettings
from polyglotic_desktop.ui_next.save_folder import STORED_KEY as SAVE_FOLDER_KEY
from polyglotic_desktop.ui_next.views.caption_window import (
    STORED_KEY as WINDOWS_KEY,
)
from polyglotic_desktop.ui_next.views.caption_window import StoredWindows, WindowChoices
from polyglotic_desktop.ui_next.views.transcript import (
    STORED_KEY as TRANSCRIPTS_KEY,
)
from polyglotic_desktop.ui_next.views.transcript import StoredTranscripts

CORPUS_DIR = Path(__file__).resolve().parent / "files"
"""Directory holding one made-up real-shaped JSON file per release format."""

WORDS_OPEN_KEY = "words_open"
"""Words page section fold state key (`ui_next.words_page.OPEN_KEY`)."""

SIDE_STORE_KEYS = frozenset(
    {WINDOWS_KEY, TRANSCRIPTS_KEY, SAVE_FOLDER_KEY, WORDS_OPEN_KEY}
)
"""Top-level keys owned by side stores outside `AppSettings`."""

ALWAYS_NORMALISED_FIELDS = frozenset(
    {
        "translate_live",
        "language_links_chosen",
        "built_ins",
        "caption_lab_version",
    }
)
"""Fields whose resolved value is intentionally normalised on every read:
`translate_live` is retired (always True), `language_links_chosen` is a
one-time migration marker (always True), `built_ins` advances to `BUILT_INS`,
and `caption_lab_version` advances to at least `CAPTION_LAB_VERSION`."""


@dataclass(frozen=True, slots=True)
class ResolvedSnapshot:
    """Canonical result of resolving one stored settings document."""

    value: AppSettings
    stored: dict[str, Any]
    foreign_keys: dict[str, Any]
    caption_windows: dict[str, Any]
    transcripts: dict[str, Any]
    save_folder: str | None
    words_open: dict[str, bool]

    def to_canonical_json(self) -> str:
        """Deterministic JSON representation for equality-across-runs checks."""
        payload = {
            "stored": self.stored,
            "foreign_keys": self.foreign_keys,
            "caption_windows": self.caption_windows,
            "transcripts": self.transcripts,
            "save_folder": self.save_folder,
            "words_open": self.words_open,
        }
        return json.dumps(payload, sort_keys=True, ensure_ascii=False)


@dataclass(frozen=True, slots=True)
class FieldCoverage:
    """Coverage summary of `AppSettings` fields across a corpus."""

    total_fields: int
    present_in_raw: frozenset[str]
    non_default_in_raw: frozenset[str]
    non_default_resolved: frozenset[str]
    missing_from_raw: frozenset[str]
    default_only_in_raw: frozenset[str]
    default_only_resolved: frozenset[str]


def _json_normalise(value: object) -> Any:
    """Round-trip through JSON so tuples become lists and keys are plain."""
    return json.loads(json.dumps(value, ensure_ascii=False))


def load_corpus_file(path: Path) -> dict[str, object]:
    """Read one JSON settings fixture as a mapping."""
    loaded = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(loaded, dict):
        raise TypeError(f"{path.name} must hold a JSON object")
    return loaded


def corpus_cases(directory: Path = CORPUS_DIR) -> list[tuple[str, dict[str, object]]]:
    """All committed real-shaped corpus files, sorted deterministically by name."""
    paths = sorted(directory.glob("*.json"))
    return [(path.stem, load_corpus_file(path)) for path in paths]


def resolve_stored(raw: Mapping[str, object]) -> ResolvedSnapshot:
    """Run the full settings read pipeline (AppSettings + presets + side stores)."""
    read = AppSettings.from_stored(raw)
    value = use_presets.from_flat(
        use_presets.follow_reading_defaults(read, raw),
        before_presets="preset" not in raw,
        built_ins=read.built_ins if "built_ins" in raw else 1,
    )
    own_stored = _json_normalise(value.to_stored())
    known_and_owned = {f.name for f in fields(AppSettings)} | set(own_stored)
    foreign = _json_normalise(
        {k: v for k, v in raw.items() if k not in known_and_owned}
    )

    raw_windows = raw.get(WINDOWS_KEY)
    windows = (
        StoredWindows.from_stored(raw_windows, WindowChoices())
        if isinstance(raw_windows, Mapping)
        else StoredWindows()
    )
    transcripts = StoredTranscripts.from_stored(raw)
    raw_folder = raw.get(SAVE_FOLDER_KEY)
    save_folder = raw_folder if isinstance(raw_folder, str) and raw_folder else None
    raw_open = raw.get(WORDS_OPEN_KEY)
    words_open = (
        {
            k: v
            for k, v in raw_open.items()
            if isinstance(k, str) and isinstance(v, bool)
        }
        if isinstance(raw_open, dict)
        else {}
    )

    return ResolvedSnapshot(
        value=value,
        stored=own_stored,
        foreign_keys=foreign,
        caption_windows=_json_normalise(windows.to_stored()),
        transcripts=_json_normalise(transcripts.to_stored()),
        save_folder=save_folder,
        words_open=words_open,
    )


def field_coverage(
    cases: Sequence[tuple[str, Mapping[str, object]]],
) -> FieldCoverage:
    """Measure how many of `AppSettings`'s fields are exercised by `cases`."""
    defaults = AppSettings()
    all_fields = frozenset(f.name for f in fields(AppSettings))
    present_raw: set[str] = set()
    non_default_raw: set[str] = set()
    non_default_resolved: set[str] = set()

    for _, raw in cases:
        for f in fields(AppSettings):
            if f.name in raw:
                present_raw.add(f.name)
                default_val = _json_normalise(getattr(defaults, f.name))
                if _json_normalise(raw[f.name]) != default_val:
                    non_default_raw.add(f.name)
        resolved = resolve_stored(raw).value
        for f in fields(AppSettings):
            if getattr(resolved, f.name) != getattr(defaults, f.name):
                non_default_resolved.add(f.name)

    return FieldCoverage(
        total_fields=len(all_fields),
        present_in_raw=frozenset(present_raw),
        non_default_in_raw=frozenset(non_default_raw),
        non_default_resolved=frozenset(non_default_resolved),
        missing_from_raw=all_fields - present_raw,
        default_only_in_raw=all_fields - non_default_raw,
        default_only_resolved=all_fields - non_default_resolved,
    )
