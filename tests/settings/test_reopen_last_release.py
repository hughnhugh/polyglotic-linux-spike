"""Rollback reopen tests: the last release's own settings code from git (`c51062c4a`).

Runs 0.1.12's own `AppSettings` and `use_presets` modules in an isolated child
process against every file this build writes:
1. 977's hotkeys and hold keys (the first case — fails on the 0.1.13 train
   without #1259, passes with #1259 and on 0.1.12);
2. every real-shaped release-format corpus file;
3. generated synthetic settings documents; and
4. planted rollback faults (proving the check catches them).
"""

import os
from pathlib import Path

import pytest
from tools.settings_corpus.corpus import corpus_cases
from tools.settings_corpus.generator import generate_cases
from tools.settings_corpus.reopen import (
    LAST_RELEASE_REF,
    ReleaseSourceUnavailable,
    extract_release_src,
    reopen_batch,
    verify_round_trip_batch,
)


@pytest.fixture(scope="module")
def last_release_src(tmp_path_factory: pytest.TempPathFactory) -> Path:
    dest = tmp_path_factory.mktemp("release_0_1_12")
    try:
        return extract_release_src(LAST_RELEASE_REF, dest)
    except ReleaseSourceUnavailable as exc:
        if os.environ.get("GITHUB_REPOSITORY", "").endswith("/polyglotic-desktop"):
            pytest.fail(str(exc))
        pytest.skip(str(exc))


def test_977_hotkey_case_reopens_in_last_release(
    last_release_src: Path, tmp_path: Path
) -> None:
    """977's hotkeys & hold keys: every choice 0.1.12 can hold comes back unchanged,
    and every candidate choice survives a 0.1.12 reopen-and-save cycle."""
    by_name = dict(corpus_cases())
    mixed_977 = by_name["13_v0_1_13_hotkeys_and_scopes"]
    legacy_hold_977 = {
        **mixed_977,
        "dictation_key": "f10",
        "respeak_key": "f7",
        "last_respeak_key": "f7",
    }
    cases = [
        ("977_mixed_hotkeys_and_v2_hold_keys", mixed_977),
        ("977_mixed_hotkeys_and_legacy_hold_keys", legacy_hold_977),
    ]
    failures = verify_round_trip_batch(
        last_release_src, cases, tmp_path, stem="reopen_977"
    )
    assert not failures, f"977 hotkey rollback failed: {failures}"


def test_every_release_corpus_file_reopens_in_last_release(
    last_release_src: Path, tmp_path: Path
) -> None:
    """Every real-shaped release format written by this build reopens cleanly in 0.1.12."""
    failures = verify_round_trip_batch(
        last_release_src, corpus_cases(), tmp_path, stem="reopen_corpus"
    )
    assert not failures, f"corpus rollback failures: {failures}"


def test_generated_corpus_reopens_in_last_release(
    last_release_src: Path, tmp_path: Path
) -> None:
    """Generated synthetic files written by this build reopen cleanly in 0.1.12."""
    generated = generate_cases(count=50, seed=987, include_invalid=True)
    failures = verify_round_trip_batch(
        last_release_src, generated, tmp_path, stem="reopen_generated"
    )
    assert not failures, f"generated rollback failures: {failures}"


def test_reopen_check_catches_planted_977_hotkey_and_legacy_key_faults(
    last_release_src: Path, tmp_path: Path
) -> None:
    """Planted faults: writing 0.1.13-only bindings directly into 0.1.12's keys
    (the #1236 fault fixed by #1259) or writing out-of-range values into legacy
    keys must be caught by 0.1.12's own reader."""
    planted_977 = {
        "hotkeys": {"lock": "ctrl+alt+l", "hide": "space"},
        "hotkey_scopes": {"hide": "app"},
        "dictation_key": "semicolon",
        "respeak_key": "media_play",
        "last_respeak_key": "ctrl+alt+comma",
        "preset": "everyday",
        "built_ins": 7,
        "changed": ["hotkeys", "dictation_key", "respeak_key", "last_respeak_key"],
    }
    planted_bad_legacy = {
        "opacity": 1.5,
        "theme": "future_theme_name",
        "preset": "everyday",
        "built_ins": 7,
        "changed": ["opacity", "theme"],
    }
    outcomes = reopen_batch(
        last_release_src,
        [("planted_977", planted_977), ("planted_bad_legacy", planted_bad_legacy)],
        tmp_path,
        stem="planted_faults",
    )

    hotkey_outcome, legacy_outcome = outcomes
    assert set(hotkey_outcome.rejected) == {
        "hotkeys",
        "dictation_key",
        "respeak_key",
        "last_respeak_key",
    }
    # Confirm 0.1.12 actually voided the entire hotkeys map (losing `lock` too).
    assert hotkey_outcome.reopened["hotkeys"] == {}
    assert hotkey_outcome.saved["hotkeys"] == {}

    assert set(legacy_outcome.rejected) == {"opacity", "theme"}
