"""Settings net corpus tests: 128-field coverage, determinism and migrations.

All fixtures live under `tools/settings_corpus/files/` and use made-up values
only (RULES #26, #30).
"""

import json
import subprocess
import sys
from pathlib import Path

from tools.settings_corpus.corpus import (
    ALWAYS_NORMALISED_FIELDS,
    CORPUS_DIR,
    corpus_cases,
    field_coverage,
    resolve_stored,
)
from tools.settings_corpus.generator import GENERATOR_LIMITATIONS, generate_cases

from polyglotic_desktop.core.listening.display import JapaneseReading, LongLines
from polyglotic_desktop.core.listening.timing import CaptionMode
from polyglotic_desktop.ui.settings import BUILT_INS, CAPTION_LAB_VERSION, AppSettings

REPO_ROOT = Path(__file__).resolve().parents[2]


def test_corpus_has_real_shaped_files_and_covers_all_128_fields() -> None:
    cases = corpus_cases()
    assert len(cases) >= 12, "expected one real-shaped file per release format"

    # Guard RULES #26/#30: no real user profile path or APPDATA reference.
    for path in sorted(CORPUS_DIR.glob("*.json")):
        text = path.read_text(encoding="utf-8")
        assert "Users\\" not in text and "AppData" not in text, path.name

    cov = field_coverage(cases)
    assert cov.total_fields >= 128
    assert not cov.missing_from_raw, (
        f"missing from raw corpus: {sorted(cov.missing_from_raw)}"
    )
    assert not cov.default_only_in_raw, (
        f"only at default in raw corpus: {sorted(cov.default_only_in_raw)}"
    )
    unexpected = cov.default_only_resolved - ALWAYS_NORMALISED_FIELDS
    assert not unexpected, (
        f"unexpected default-only resolved fields: {sorted(unexpected)}"
    )


def test_corpus_and_generated_files_resolve_identically_twice() -> None:
    cases = [*corpus_cases(), *generate_cases(count=100, seed=987)]
    first = {name: resolve_stored(raw) for name, raw in cases}
    second = {name: resolve_stored(raw) for name, raw in cases}

    for name, snap in first.items():
        assert snap.to_canonical_json() == second[name].to_canonical_json(), name
        # Second-pass idempotence: resolving what this build wrote gives the same state.
        written = {**snap.foreign_keys, **snap.stored}
        again = resolve_stored(written)
        assert again.value == snap.value, name
        assert again.stored == snap.stored, name


def test_corpus_resolves_identically_across_two_fresh_processes() -> None:
    script = (
        "import json; "
        "from tools.settings_corpus import corpus_cases, generate_cases, resolve_stored; "
        "cases = [*corpus_cases(), *generate_cases(count=30, seed=987)]; "
        "print(json.dumps({n: resolve_stored(r).to_canonical_json() for n, r in cases}, sort_keys=True))"
    )
    run_one = subprocess.run(
        [sys.executable, "-c", script],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=True,
    )
    run_two = subprocess.run(
        [sys.executable, "-c", script],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=True,
    )
    assert run_one.stdout == run_two.stdout
    parsed = json.loads(run_one.stdout)
    assert len(parsed) == len(corpus_cases()) + 30


def test_release_format_migrations_are_pinned() -> None:
    by_name = dict(corpus_cases())

    # 01: pre-switch app_name -> apps, overlay_geometry -> custom, interval None -> steady
    s01 = resolve_stored(by_name["01_pre_switch_app_name"])
    assert s01.value.apps == ("Sample Player",)
    assert s01.value.overlay_position == "custom"
    assert s01.value.caption_mode_chosen == CaptionMode.WHOLE.value
    assert s01.value.translate_live is True
    assert "translate_live" not in s01.stored
    assert s01.value.whole_system is False

    # 02: 0.1.0-0.1.3 caption_timing preview -> words, old defaults follow, NOT_OFFERED dropped
    s02 = resolve_stored(by_name["02_v0_1_0_pre_switch"])
    assert s02.value.caption_mode_chosen == CaptionMode.STEADY.value
    assert s02.value.live_update_interval == AppSettings().live_update_interval
    assert s02.value.opacity == AppSettings().opacity
    assert s02.value.targets == ("ja", "en")
    assert s02.value.second_languages == {"ja": "fr"}

    # 03: 0.1.4 app_text_size larger -> normal, caption_lab v1 -> v2, side stores read
    s03 = resolve_stored(by_name["03_v0_1_4_dictation_lab"])
    assert s03.value.interface_text_size == "normal"
    assert s03.value.caption_lab_version == CAPTION_LAB_VERSION
    older = s03.value.caption_lab["older"]
    assert isinstance(older, float) and 0.5 <= older <= 1.0
    assert s03.save_folder == "/tmp/polyglotic-exports"
    assert s03.words_open == {"en": False, "zh": True}
    win = s03.caption_windows["windows"]["Sample Player"]
    assert win["translation_text_size"] == round(1.2 * 0.85, 2)

    # 04: 0.1.5 ADDED_LINKS cleared where no links_from, preserved where links_from set
    s04 = resolve_stored(by_name["04_v0_1_5_learning_transcripts"])
    assert s04.value.interface_text_size == "larger"
    assert s04.value.language_links_chosen is True
    assert s04.value.language_choices["zh"] == {"window": 2000}
    assert s04.value.language_choices["ja"]["links"] == "past_known"
    assert s04.value.text_settles_after == AppSettings().text_settles_after

    # 05: 0.1.6 live_update_interval 2.5 -> live, app_text_size smaller -> smaller
    s05 = resolve_stored(by_name["05_v0_1_6_known_reset"])
    assert s05.value.interface_text_size == "smaller"
    assert s05.value.caption_mode_chosen == CaptionMode.INSTANT.value
    assert s05.value.known_reset == {"en": {}, "zh": {"known": 2000, "scale": "words"}}

    # 06: 0.1.7 link_words_coloured -> both switches off; untouched reading_lines follows default
    s06 = resolve_stored(by_name["06_v0_1_7_readings_link_words"])
    assert s06.value.said_in_link_colours is False
    assert s06.value.translation_in_link_colours is False
    assert "reading_lines" not in s06.value.changed

    # 07: 0.1.8 changed record, respeaking -> type_theirs, reading_lines without ja -> ja off
    s07 = resolve_stored(by_name["07_v0_1_8_changed_record"])
    assert s07.value.type_theirs is False
    assert s07.value.japanese_reading == JapaneseReading.OFF.value
    assert s07.value.max_wait_for_text == 4.5
    assert s07.value.text_settles_after == 1.5
    assert s07.value.respeak_key == "f8"

    # 08: 0.1.9 pre-presets with custom choices -> custom preset; ja in reading_lines -> kana
    s08 = resolve_stored(by_name["08_v0_1_9_quiet_faces"])
    assert s08.value.preset == "custom"
    assert s08.value.own_presets == ("custom",)
    assert s08.value.japanese_reading == JapaneseReading.KANA.value
    assert s08.value.interface_text_size == "normal"

    # 09: 0.1.10 delayed_translation -> live, built_ins 2 -> 7 with lyrics copied, links kept
    s09 = resolve_stored(by_name["09_v0_1_10_presets_hotkeys"])
    assert s09.value.caption_mode_chosen == CaptionMode.INSTANT.value
    assert s09.value.built_ins == BUILT_INS
    assert s09.value.language_choices["zh"]["links"] == "past_known"
    assert s09.value.preset_values["video"]["lyrics"] is True

    # 10: 0.1.11 video live without video_layout -> scrolling, preset caption_lab cleaned, respeak "" kept
    s10 = resolve_stored(by_name["10_v0_1_11_lab_v2"])
    assert s10.value.caption_mode_chosen == CaptionMode.SCROLLING.value
    assert "caption_lab" not in s10.value.preset_values.get("video", {})
    assert (
        s10.value.preset_values["video"]["caption_mode_chosen"]
        == CaptionMode.INSTANT.value
    )
    assert s10.value.respeak_key == ""

    # 11: 0.1.12 current format keeps all fields and foreign keys
    s11 = resolve_stored(by_name["11_v0_1_12_release"])
    assert s11.value.built_ins == BUILT_INS
    assert s11.value.japanese_reading == JapaneseReading.BOTH.value
    assert s11.value.long_lines == LongLines.DISPLAY_NEW_LINES.value
    assert s11.value.call_notices_shown == ("Study Call",)
    assert s11.foreign_keys["future_flag_0_2"] == {
        "enabled": True,
        "note": "synthetic future payload",
    }

    # 12: edge branches (legacy long_lines, f8 conflict, invalid preset/parents, all NOT_OFFERED)
    s12 = resolve_stored(by_name["12_v0_1_12_edge_branches"])
    assert s12.value.long_lines == LongLines.DISPLAY_NEW_LINES.value
    assert s12.value.preset_values["own1"]["long_lines"] == LongLines.GROUPED.value
    assert s12.value.respeak_key == ""
    assert s12.value.preset == "everyday"
    assert s12.value.preset_parents == {}
    assert s12.value.targets == ("en",)
    assert s12.value.whole_system is False
    assert s12.value.recommended_look_before == {"opacity": 0.65}


def test_generated_corpus_covers_all_fields_and_preserves_unknown_keys() -> None:
    generated = generate_cases(count=100, seed=987, include_invalid=True)
    cov = field_coverage(generated)
    assert not cov.missing_from_raw, (
        f"generator missed fields: {sorted(cov.missing_from_raw)}"
    )
    assert len(GENERATOR_LIMITATIONS) >= 5

    for name, raw in generated:
        snap = resolve_stored(raw)
        future_keys = {k: v for k, v in raw.items() if k.startswith("future_setting_")}
        assert future_keys, name
        for key, value in future_keys.items():
            assert snap.foreign_keys[key] == value, name
