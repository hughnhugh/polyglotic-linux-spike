"""Deterministic generator of synthetic settings documents for the settings net.

Uses the standard library (`random.Random(seed)`) so the corpus generator works
everywhere without extra dependencies, reproduces identical files across runs,
and mixes valid choices, boundary values, legacy migration keys, side stores,
invalid types, and unknown future keys. All generated values are synthetic
(RULES #26, #30).
"""

import random
from typing import Any

from polyglotic_desktop.core.learning.curriculum import MAX_SIZE as CURRICULUM_MAX
from polyglotic_desktop.core.learning.curriculum import MIN_SIZE as CURRICULUM_MIN
from polyglotic_desktop.core.listening.display import (
    READING_LANGUAGES,
    JapaneseReading,
    LinkDetail,
    LinkGap,
    LinkLine,
    LongLines,
    ReadingColour,
    ReadingSize,
    ReadingSystem,
    WordLinks,
)
from polyglotic_desktop.core.listening.hidden import PAUSE_CHOICES
from polyglotic_desktop.core.listening.hotkeys import Hotkey
from polyglotic_desktop.core.listening.playout import (
    TRANSLATION_AFTER_RANGE,
    Ahead,
    ReadingPath,
)
from polyglotic_desktop.core.listening.preset_reading import VIDEO_LINE_CHOICES
from polyglotic_desktop.core.listening.settling import SETTLE_RANGE
from polyglotic_desktop.core.listening.timing import MAX_WAIT_RANGE, CaptionMode
from polyglotic_desktop.core.listening.type_theirs import TypeWhat
from polyglotic_desktop.ui.settings import (
    APP_TEXT_SIZES,
    ARRIVALS,
    BUILT_INS,
    FIRST_RUN_STEPS,
    FOLLOW_DEFAULT,
    LIVE_INTERVALS,
    MANDARIN_SCRIPTS,
    MARKS_IN,
    OLD_TEXT_SIZES,
    POSITIONS,
    SUBTITLE_SIZES,
    SUBTITLE_WIDTHS,
    TEXT_SCALES,
    TRANSCRIPT_LENGTHS,
    WIDTH_SHARES,
)
from polyglotic_desktop.ui.theme import THEMES, WINDOW_THEMES
from polyglotic_desktop.ui.use_presets import ORDER as BUILTIN_PRESETS

GENERATOR_LIMITATIONS: tuple[str, ...] = (
    "In-memory edit history and Undo state (`use_presets.Before`, `restored`) never touch disk.",
    "Pre-0.1.8 ambiguity between 'never touched' and 'changed then changed back to the old default' when `changed` is absent.",
    "Runtime/OS-dependent resolution: system locale for `interface_language=None` and `mandarin_script=None`, live `tunables.toml` / `refused_choices()` overrides, attached audio device IDs, and platform hotkey defaults (Windows vs macOS vs Linux).",
    "Filesystem and concurrency failures: transient unreadable files, `os.replace` permission errors, corrupt JSON set-aside, and interleaved multi-owner puts/removes.",
    "Cross-release rollback intent: a generator drawing from the current build's valid domains cannot by itself prove what the last release rejects; that requires running the last release's own code from git plus authored regression cases such as 977's hotkeys.",
    "Live Settings UI bindings: whether a widget writes the right key or restores its prior value on reset.",
)
"""Behaviours a static generated settings JSON file cannot represent on its own."""

_FAKE_APPS = ("Sample Player", "Demo Browser", "Study Call", "Quiz Viewer", "Audio Lab")
_FAKE_COLORS = (
    "#ffffff",
    "#ffd76e",
    "#0a0c10",
    "#ff6e9c",
    "#4dd0e1",
    "#9ad0ff",
    "#1b2a41",
)
_LEARNED_CODES = ("zh", "en", "ja", "ko", "fr", "de", "es", "ru", "yue")
_INTERFACE_CODES = ("en", "zh_CN", "zh_TW", "ja", "ko", "fr", "de", "es", "pt_BR")
_DICTATION_LANGS = ("en", "zh", "ja", "ko", "fr", "de", "es", "ru")
_LEGACY_HOLD_KEYS = (
    "right_ctrl",
    "f7",
    "f8",
    "f9",
    "f10",
    "insert",
    "ctrl+alt+d",
    "ctrl+win",
)
_LEGACY_HOTKEY_VALUES = (
    "ctrl+alt+l",
    "ctrl+alt+p",
    "ctrl+alt+h",
    "ctrl+alt+c",
    "f9",
    "f10",
    "",
)
# Hashable invalid JSON scalars: 12 enum/theme `_CHECKS` lambdas in 0.1.12 use
# `v in {set}` without `isinstance(v, str)`, raising TypeError on lists/dicts.
_INVALID_SAMPLES: tuple[object, ...] = (
    "not-valid",
    -999,
    999999,
    True,
    False,
    3.14159,
    "",
    None,
)


def _rand_float(rng: random.Random, low: float, high: float) -> float:
    return round(rng.uniform(low, high), 3)


def _rand_valid_field(rng: random.Random, name: str) -> Any:
    """Produce a valid synthetic value for `AppSettings` field `name`."""
    if name == "learning":
        return rng.choice([None, "zh", "en"])
    if name in ("also_learning", "not_now_learning", "better_voice_quiet"):
        return rng.sample(_LEARNED_CODES, rng.randint(0, 3))
    if name == "interface_language":
        return rng.choice([None, *_INTERFACE_CODES])
    if name == "first_run_step":
        return rng.choice([None, *FIRST_RUN_STEPS])
    if name == "targets":
        return rng.sample(["en", "zh", "ja", "ko", "fr", "mn", "kk"], rng.randint(1, 3))
    if name == "second_languages":
        return {
            k: rng.choice(["en", "fr", "ja"])
            for k in rng.sample(["ja", "zh", "ko", "kk"], rng.randint(0, 2))
        }
    if name == "no_second_language":
        return rng.sample(["ja", "zh", "fr"], rng.randint(0, 2))
    if name == "spoken_language":
        return rng.choice([None, "zh", "ja", "en", "ko"])
    if name == "mandarin_script":
        return rng.choice([None, *MANDARIN_SCRIPTS])
    if name == "translate_live":
        return rng.choice([True, False])
    if name == "spelling_hints":
        return rng.sample(["Aoi", "Ren", "Mina", "Kaito"], rng.randint(0, 3))
    if name in (
        "lyrics",
        "show_original",
        "show_language",
        "show_hidden_on_speech",
        "reading_past",
        "respelling_past",
        "quiet_view",
        "colour_links_by_word_class",
        "said_in_link_colours",
        "translation_in_link_colours",
        "steady_newest_word",
        "steady_two_zones",
        "steady_cards",
        "common_words_only",
        "marks_off",
        "language_links_chosen",
        "locked",
        "unlock_spot",
        "unlock_told",
        "transcript_ask_at_quit",
        "say_it_translation_first",
        "tray_note_shown",
        "start_with_windows_asked",
        "applications_offered",
        "level_line_dismissed",
        "whole_system",
        "everything_else",
        "caption_mic",
        "show_source",
        "show_delay",
        "dictation",
        "dictation_australian",
        "type_theirs",
        "legacy_respeaking",
        "show_translation",
        "subtitles",
    ):
        return rng.choice([True, False])
    if name == "preset_languages":
        return {
            app: {
                "spoken_language": rng.choice(["", "zh", "ja"]),
                "translate_into": rng.choice(["", "en", "fr"]),
            }
            for app in rng.sample(_FAKE_APPS, rng.randint(0, 2))
        }
    if name == "preset_second_languages":
        return {
            k: rng.choice(["", "en", "fr"])
            for k in rng.sample(["ja", "zh"], rng.randint(0, 2))
        }
    if name == "word_links":
        return rng.choice([w.value for w in WordLinks])
    if name == "link_detail":
        return rng.choice([d.value for d in LinkDetail])
    if name == "link_line":
        return rng.choice([w.value for w in LinkLine])
    if name == "link_gap":
        return rng.choice([g.value for g in LinkGap])
    if name == "text_scale":
        return _rand_float(rng, *TEXT_SCALES)
    if name == "opacity":
        return _rand_float(rng, 0.0, 1.0)
    if name == "recommended_look_before":
        return rng.choice(
            [
                {},
                {
                    "opacity": _rand_float(rng, 0.2, 0.9),
                    "caption_edge": rng.choice(["none", "shadow", "outline"]),
                },
            ]
        )
    if name == "fade_after":
        return rng.choice([None, _rand_float(rng, 1.0, 600.0)])
    if name == "caption_arrival":
        return rng.choice(ARRIVALS)
    if name == "pause_hidden_after":
        return rng.choice([None, *PAUSE_CHOICES])
    if name == "reading_lines":
        return rng.sample(READING_LANGUAGES, rng.randint(0, 3))
    if name == "reading_size":
        return rng.choice([s.value for s in ReadingSize])
    if name == "reading_system":
        return rng.choice([s.value for s in ReadingSystem])
    if name == "japanese_reading":
        return rng.choice([s.value for s in JapaneseReading])
    if name == "reading_colour":
        return rng.choice([c.value for c in ReadingColour])
    if name in (
        "reading_custom_color",
        "original_color",
        "translation_color",
        "background_color",
    ):
        return rng.choice(_FAKE_COLORS)
    if name == "quiet_words":
        return rng.sample(["curriculum", "edge", "load", "saved"], rng.randint(0, 4))
    if name == "marks_in":
        return rng.choice(MARKS_IN)
    if name == "curriculum_size":
        return rng.randint(CURRICULUM_MIN, CURRICULUM_MAX)
    if name in ("caption_contrast", "caption_vibrance"):
        return rng.randint(-100, 100)
    if name == "caption_weight":
        return rng.choice([300, 400, 500, 600, 700])
    if name == "caption_edge":
        return rng.choice(["none", "shadow", "outline"])
    if name == "caption_lab":
        return rng.choice(
            [
                {},
                {
                    "older": round(rng.uniform(0.5, 1.0), 2),
                    "load": rng.choice([True, False]),
                },
            ]
        )
    if name == "caption_lab_version":
        return rng.choice([1, 2])
    if name == "caption_mode_chosen":
        return rng.choice(
            [None, *(m.value for m in CaptionMode), "delayed_translation"]
        )
    if name == "long_lines":
        return rng.choice([*(m.value for m in LongLines), "carry", "ellipsis"])
    if name == "caption_path":
        return rng.choice([p.value for p in ReadingPath])
    if name == "translation_after":
        return _rand_float(rng, *TRANSLATION_AFTER_RANGE)
    if name == "steady_words_ahead":
        return rng.choice([a.value for a in Ahead])
    if name == "live_update_interval":
        return _rand_float(rng, *LIVE_INTERVALS)
    if name == "max_wait_for_text":
        return _rand_float(rng, *MAX_WAIT_RANGE)
    if name == "text_settles_after":
        return _rand_float(rng, *SETTLE_RANGE)
    if name == "language_choices":
        return {
            code: {
                "links": rng.choice(["every", "past_known", "off"]),
                "window": rng.choice([500, 1000, "unlimited"]),
            }
            for code in rng.sample(["zh", "ja", "en"], rng.randint(0, 2))
        }
    if name == "learning_load":
        return {
            code: {
                "size": rng.randint(5, 30),
                "step": rng.randint(1, 10),
                "counting": rng.choice(["captions", "minutes"]),
            }
            for code in rng.sample(["zh", "en"], rng.randint(0, 2))
        }
    if name == "known_reset":
        return rng.choice([{}, {"zh": {"scale": "words", "known": 1000}}, {"en": {}}])
    if name == "overlay_geometry":
        return {
            k: [100, 120, 640, 220] for k in rng.sample(["en", "ja"], rng.randint(0, 2))
        }
    if name == "caption_font":
        return rng.choice([None, "Georgia", "Demo Sans"])
    if name == "caption_faces":
        return {
            k: rng.choice(["", "Demo Kai", "Demo Mincho"])
            for k in rng.sample(["zh", "ja", "ko"], rng.randint(0, 2))
        }
    if name == "overlay_position":
        return rng.choice(POSITIONS)
    if name == "overlay_width":
        return rng.choice([None, _rand_float(rng, *WIDTH_SHARES)])
    if name == "theme":
        return rng.choice(tuple(THEMES))
    if name == "window_theme":
        return rng.choice(WINDOW_THEMES)
    if name == "interface_text_size":
        return rng.choice(APP_TEXT_SIZES)
    if name == "transcript_length":
        return rng.choice(TRANSCRIPT_LENGTHS)
    if name == "video_timing_explained":
        return rng.choice([{}, {"words": "live"}, {"steady": "live"}])
    if name == "main_window_size":
        return rng.choice([None, [rng.randint(800, 1920), rng.randint(600, 1080)]])
    if name == "whats_new_seen":
        return rng.choice([None, "0.1.9", "0.1.10", "0.1.12"])
    if name == "cohort":
        return rng.choice([None, "alpha", "beta"])
    if name == "maintenance":
        return rng.choice(
            [
                {},
                {
                    "starts_at": "2026-12-02T01:00:00+00:00",
                    "ends_at": "2026-12-02T02:00:00+00:00",
                    "pc_ahead": 0.0,
                },
            ]
        )
    if name == "apps":
        return rng.sample(_FAKE_APPS, rng.randint(0, 3))
    if name == "call_notices_shown":
        return rng.sample(["Study Call", "Voice Room"], rng.randint(0, 2))
    if name == "speaker_device":
        return rng.choice([None, "sample-speaker-1", "sample-speaker-2"])
    if name == "mic_device":
        return rng.choice([None, "sample-mic-1", "sample-mic-2"])
    if name == "app_capture_fell_back":
        return rng.choice([{}, {"windows": "19045", "app": "0.1.12", "why": "silent"}])
    if name == "source_names":
        return {
            app: f"Label {i}"
            for i, app in enumerate(rng.sample(_FAKE_APPS, rng.randint(0, 2)))
        }
    if name == "source_colors":
        return {
            app: rng.choice(_FAKE_COLORS)
            for app in rng.sample(_FAKE_APPS, rng.randint(0, 2))
        }
    if name == "dictation_key":
        return rng.choice(_LEGACY_HOLD_KEYS)
    if name == "dictation_language":
        return rng.choice([None, *_DICTATION_LANGS])
    if name == "hotkeys":
        chosen = rng.sample([h.value for h in Hotkey], rng.randint(0, 4))
        result: dict[str, str] = {}
        for h in chosen:
            if h == Hotkey.LIVE.value and rng.random() < 0.4:
                result[h] = "space"
            else:
                result[h] = rng.choice(_LEGACY_HOTKEY_VALUES)
        return result
    if name == "hotkey_scopes":
        chosen = rng.sample([h.value for h in Hotkey], rng.randint(0, 3))
        return {h: rng.choice(["app", "everywhere"]) for h in chosen}
    if name == "type_what":
        return rng.choice([TypeWhat.ORIGINAL.value, TypeWhat.TRANSLATION.value])
    if name == "respeak_key":
        return rng.choice(["", *_LEGACY_HOLD_KEYS])
    if name == "last_respeak_key":
        return rng.choice(_LEGACY_HOLD_KEYS)
    if name == "subtitle_size":
        return _rand_float(rng, *SUBTITLE_SIZES)
    if name == "subtitle_width":
        return _rand_float(rng, *SUBTITLE_WIDTHS)
    if name == "video_lines_shown":
        return rng.choice(VIDEO_LINE_CHOICES)
    if name == "my_speech":
        return rng.choice([None, True, False])
    if name == "preset":
        return rng.choice([*BUILTIN_PRESETS, "own1"])
    if name == "own_presets":
        return rng.choice([[], ["own1"], ["own1", "own2"]])
    if name == "preset_values":
        return rng.choice(
            [
                {},
                {
                    "video": {
                        "opacity": _rand_float(rng, 0.0, 1.0),
                        "word_links": rng.choice(["off", "arrows"]),
                    },
                    "own1": {"subtitle_width": _rand_float(rng, *SUBTITLE_WIDTHS)},
                },
            ]
        )
    if name == "preset_names":
        return rng.choice([{}, {"own1": "Custom Study", "video": "Movies"}])
    if name == "preset_parents":
        return rng.choice([{}, {"own1": rng.choice(BUILTIN_PRESETS)}])
    if name == "built_ins":
        return rng.randint(1, BUILT_INS)
    if name == "changed":
        return rng.sample(
            list(FOLLOW_DEFAULT), rng.randint(0, len(FOLLOW_DEFAULT) // 2)
        )
    # Forward-compatible fallback for fields added in newer releases.
    from polyglotic_desktop.ui.settings import AppSettings

    default = getattr(AppSettings(), name)
    if isinstance(default, bool):
        return rng.choice([True, False])
    if isinstance(default, tuple):
        return list(default)
    return default


def generate_one(
    rng: random.Random, index: int, *, include_invalid: bool = True
) -> dict[str, object]:
    """Generate one synthetic settings document with optional legacy, invalid, and future keys."""
    from dataclasses import fields

    from polyglotic_desktop.ui.settings import AppSettings

    all_names = [f.name for f in fields(AppSettings)]
    picked = rng.sample(all_names, rng.randint(10, 45))
    doc: dict[str, object] = {}

    for name in picked:
        if include_invalid and rng.random() < 0.08:
            doc[name] = rng.choice(_INVALID_SAMPLES)
        else:
            doc[name] = _rand_valid_field(rng, name)

    # Every release that writes `preset` (0.1.10+) also writes `changed` (0.1.8+);
    # keep that era invariant so generated files match real on-disk shapes.
    if "preset" in doc and "changed" not in doc:
        doc["changed"] = _rand_valid_field(rng, "changed")

    # Exercise legacy/retired keys in roughly a third of generated files.
    if rng.random() < 0.35:
        if "apps" not in doc and rng.random() < 0.5:
            doc["app_name"] = rng.choice(_FAKE_APPS)
        if "interface_text_size" not in doc and rng.random() < 0.5:
            doc["app_text_size"] = rng.choice([*OLD_TEXT_SIZES, "normal"])
        if "caption_mode_chosen" not in doc and rng.random() < 0.5:
            doc["caption_timing"] = rng.choice(["preview", "live", "steady", "words"])
        if rng.random() < 0.4:
            doc["link_words_coloured"] = rng.choice([True, False])
        if "type_theirs" not in doc and rng.random() < 0.4:
            doc["respeaking"] = rng.choice([True, False])
        if rng.random() < 0.5:
            doc["video_layout"] = 2

    # Exercise side-store keys in half of generated files.
    if rng.random() < 0.5:
        doc["caption_windows"] = {
            "windows": {
                rng.choice(_FAKE_APPS): {
                    "translate_into": rng.choice(["en", "ja", ""]),
                    "text_size": round(rng.uniform(0.8, 1.8), 2),
                    "translation_text_size": round(rng.uniform(0.8, 1.8), 2),
                    "opacity": round(rng.uniform(0.2, 1.0), 2),
                    "show_pace": rng.choice([True, False]),
                    "show_caption_info": rng.choice([True, False]),
                }
            },
            "joined": {
                "on": rng.choice([True, False]),
                "chosen": rng.choice([True, False]),
            },
        }
    if rng.random() < 0.4:
        doc["transcripts"] = {
            rng.choice(_FAKE_APPS): {
                "text_size": round(rng.uniform(0.8, 1.8), 2),
                "rail_open": rng.choice([True, False]),
                "size": [rng.randint(600, 1200), rng.randint(400, 900)],
            }
        }
    if rng.random() < 0.3:
        doc["save_folder"] = f"/tmp/polyglotic-gen-{index}"
    if rng.random() < 0.3:
        doc["words_open"] = {
            "zh": rng.choice([True, False]),
            "en": rng.choice([True, False]),
        }

    # Always attach a synthetic unknown future key to assert round-trip survival.
    doc[f"future_setting_{index % 7}"] = {"version": index % 5, "flag": bool(index % 2)}
    return doc


def generate_cases(
    count: int = 50,
    seed: int = 987,
    *,
    include_invalid: bool = True,
) -> list[tuple[str, dict[str, object]]]:
    """Generate `count` deterministic synthetic settings cases from `seed`."""
    rng = random.Random(seed)
    return [
        (f"gen_{i:03d}", generate_one(rng, i, include_invalid=include_invalid))
        for i in range(count)
    ]
