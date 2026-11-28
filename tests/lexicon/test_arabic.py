"""Tests for Arabic plain text normalization and morphological/clitic base guesses."""

from __future__ import annotations

import pytest

from polyglotic_desktop.adapters import spaced_split
from polyglotic_desktop.core.lexicon import arabic


def test_plain_strips_harakat_and_normalizes_alif_wasla_and_quranic_marks() -> None:
    """Captions and classical/Quranic text write alif wasla (ٱ) and annotation
    marks alongside short vowels; lookups expect plain alif without marks."""
    assert arabic.plain("الْكِتَابُ") == "الكتاب"
    assert arabic.plain("ٱلْكِتَابُ") == "الكتاب"
    assert arabic.plain("ٱللَّهِ") == "الله"
    assert arabic.plain("ٱلرَّحْمَٰنِ") == "الرحمن"
    assert arabic.plain("قَالُوا۟") == "قالوا"
    # Hamza and madda stay: they are letters' own parts.
    assert arabic.plain("أَكَلَ") == "أكل"
    assert arabic.plain("إِسْلَام") == "إسلام"
    assert arabic.plain("آمَنَ") == "آمن"


def test_future_proclitic_strips_only_before_imperfect_prefixes() -> None:
    """Future سـ / وسـ / فسـ attaches only to imperfect verbs starting with
    أ / ن / ي / ت, never to nouns or foreign names like سانت or سكس."""
    assert "يكون" in arabic.bases("سيكون")
    assert "تكون" in arabic.bases("ستكون")
    assert "أعود" in arabic.bases("سأعود")
    assert "نبقى" in arabic.bases("وسنبقى")
    assert "تناقش" in arabic.bases("فستناقش")
    assert "تواجه" in arabic.bases("ستواجهها")
    # Non-imperfect stems must not be split as future verbs.
    assert "انت" not in arabic.bases("سانت")
    assert "كس" not in arabic.bases("سكس")


def test_compound_proclitics_follow_single_proclitics() -> None:
    """Conjunction + preposition + article compounds (وبال, فبال, وب, ول...) are
    found, while single-proclitic stems (و+بداية, و+كشف) are tried before
    two-letter non-article compounds (وب+داية, وك+شف)."""
    assert "تالي" in arabic.bases("وبالتالي")
    assert "مقابل" in arabic.bases("وبالمقابل")
    assert "شكل" in arabic.bases("وبشكل")
    assert "كل" in arabic.bases("ولكل")
    assert "مؤسسة" in arabic.bases("وبمؤسساتها")
    # Single proclitic و must precede compound وب / وك so بداية beats داية.
    b_guesses = arabic.bases("وبداية")
    assert b_guesses.index("بداية") < b_guesses.index("داية")
    k_guesses = arabic.bases("وكشف")
    assert k_guesses.index("كشف") < k_guesses.index("شف")


def test_pronoun_suffix_restores_hamza_and_alif_maqsura() -> None:
    """Before pronoun suffixes, final ء shifts to ؤ/ئ (بناؤه -> بناء,
    أصدقائه -> أصدقاء) and final ى shifts to ا (مستواها -> مستوى,
    أعطاه -> أعطى). Verbal -ني is never stripped from ال-prefixed nouns."""
    assert "بناء" in arabic.bases("بناؤه")
    assert "أصدقاء" in arabic.bases("أصدقائه")
    assert "أعضاء" in arabic.bases("أعضائها")
    assert "مستوى" in arabic.bases("مستواها")
    assert "مقتضى" in arabic.bases("بمقتضاه")
    assert "أعطى" in arabic.bases("أعطاه")
    assert "أسبى" not in arabic.bases("الأسباني")


def test_orthographic_hamza_and_final_ya_variants() -> None:
    """Captions and unedited text write hamza on hamzat-al-wasl words
    (الإتصال, إمرأة), swap ي/ى, or drop initial hamza (انواع, اسوأ)."""
    assert "اتصال" in arabic.bases("الإتصال")
    assert "امرأة" in arabic.bases("إمرأة")
    assert "افريقيا" in arabic.bases("أفريقيا")
    assert "يحيي" in arabic.bases("يحيى")
    assert "أنواع" in arabic.bases("انواع")
    assert "أسوأ" in arabic.bases("اسوأ")
    # Short two-letter tokens must not lose hamza, and الـ never takes hamza.
    assert "اف" not in arabic.bases("إف")
    assert "ألكتاب" not in arabic.bases("الكتاب")


def test_regular_feminine_and_sound_feminine_plural_fallbacks() -> None:
    """Regular feminine -ة (len >= 5, excluding -أة/-اة) and sound feminine
    plural -ات (len >= 5, including before pronouns) resolve when omitted
    from Wiktionary inflection tables."""
    assert "قيادة" in arabic.bases("القيادات")
    assert "توقع" in arabic.bases("بالتوقعات")
    assert "استخبار" in arabic.bases("الاستخبارات")
    assert "صادر" in arabic.bases("صادراتهم")
    assert "انتخابي" in arabic.bases("الانتخابية")
    assert "متوقع" in arabic.bases("المتوقعة")
    # Short words and -أة/-اة stems are not over-stripped.
    assert "مائ" not in arabic.bases("مائة")
    assert "مسما" not in arabic.bases("مُسماة")


def test_spaced_split_wires_arabic_bases(monkeypatch: pytest.MonkeyPatch) -> None:
    """SpacedSplit('ar') exposes arabic.bases through CLITICS and arabic_bases."""
    monkeypatch.setattr(spaced_split, "_lemmatizer", lambda: None)
    words = spaced_split.SpacedSplit("ar").words("وسيكون بالتوقعات")
    assert "يكون" in words[0].guesses
    assert "توقع" in words[1].guesses
    assert spaced_split.arabic_bases("سيكون") == arabic.bases("سيكون")
