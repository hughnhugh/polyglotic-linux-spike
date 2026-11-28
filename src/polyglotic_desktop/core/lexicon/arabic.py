"""Arabic as captions write it: without the vowel marks (polyglotic-hq 380),
and candidate base forms for clitics and regular inflections (polyglotic-hq 989).

Wiktionary's inflection tables mark every vowel ("الْكِتَابُ"); speech
models and most text write none ("الكتاب"). A form is looked up, and kept
in a pack, as `plain` writes it: the short vowels, tanween, shadda and
sukun, the dagger alif, tatweel and Quranic annotation marks taken off, and
alif wasla (ٱ) written as plain alif (ا). Hamza and madda stay: they are
letters' own parts (أ, إ, آ), kept whole by NFC first.

`bases` produces fallback dictionary guesses (tried only when the pack has
neither the word nor its lemma) by stripping MSA proclitics (definite
compounds, single proclitics, conjunction+preposition compounds, and future
سـ/وسـ/فسـ before imperfect prefixes), enclitic pronouns (with stem-final
ت->ة, اؤ/ائ->اء, ا->ى restoration), common unedited orthographic variants
(bare alif, final ي<->ى, initial dropped hamza), and regular nominal
endings (-ات, -ة) omitted from Wiktionary tables.
"""

from __future__ import annotations

import unicodedata

# Minimum stem lengths (unit: Arabic letters) guarding fallback guesses against
# over-stripping short roots and loanwords (measured on UD_Arabic-PADT r2.17
# and wordfreq 3.1.1; polyglotic-hq 989).
MIN_CLITIC_STEM = 2
"""Letters remaining after a proclitic or enclitic pronoun (range 2-3; 2 keeps
common biliteral words such as دم، يد، أب، كل)."""
MIN_FUTURE_STEM = 3
"""Letters remaining after future سـ/وسـ/فسـ (range 3-4; MSA imperfect verbs
have at least prefix + 2 radicals, e.g. يجد، يقف، يكن)."""
MIN_HAMZA_STRIP_LEN = 3
"""Stem length before stripping hamza on alif (range 3-4; avoids turning 2-letter
initialisms like إف into وفى)."""
MIN_HAMZA_PRON_STEM = 4
"""Stem length for اؤ/ائ -> اء before a pronoun (range 4-5; covers بناء، أعضاء،
زملاء، أصدقاء)."""
MIN_ALIF_MAQSURA_STEM = 3
"""Stem length for final ا -> ى before a pronoun (range 3-4; covers رأى، أعطى،
مستوى، مقتضى)."""
MIN_REGULAR_SUFFIX_STEM = 5
"""Word length before stripping -ات or -ة (range 4-6; 5 avoids 4-letter false
positives like مائة -> مأى and غادة -> غدا while covering قيادات، انتخابية)."""
MIN_INITIAL_ALIF_STEM = 4
"""Bare-alif stem length before trying initial أ/إ (range 4-5; covers انواع ->
أنواع and اسوأ -> أسوأ without noisy 3-letter matches)."""

_MARKS: dict[int, str | None] = {
    **dict.fromkeys(
        [
            *range(0x064B, 0x0653),
            *range(0x0656, 0x0660),
            0x0670,
            0x0640,
            *range(0x06D6, 0x06DD),
            *range(0x06DF, 0x06E5),
            0x06E7,
            0x06E8,
            *range(0x06EA, 0x06EE),
        ]
    ),
    0x0671: "ا",
}
"""Fathatan to sukun, marks after hamza below, dagger alif, tatweel, Quranic
combining annotation marks, and alif wasla (ٱ -> ا)."""

# Proclitics dispatched by first letter. Definite compounds come first, then
# single proclitics (و، ف، ب، ل، ك), then two-letter conjunction+preposition
# compounds so و+بداية is always tried before وب+داية and و+كشف before وك+شف.
_PROCLITICS_BY_FIRST: dict[str, tuple[str, ...]] = {
    "و": ("وبال", "وكال", "وال", "ولل", "و", "وب", "ول", "وك"),
    "ف": ("فبال", "فكال", "فال", "فلل", "ف", "فب", "فل", "فك"),
    "ب": ("بال", "ب"),
    "ك": ("كال", "ك"),
    "ل": ("لل", "ل"),
    "ا": ("ال",),
}
_FUTURE_BY_FIRST: dict[str, tuple[str, ...]] = {
    "و": ("وس",),
    "ف": ("فس",),
    "س": ("س",),
}
_IMPERFECT_PREFIXES = frozenset("أنيت")
"""MSA imperfect verb prefixes that future سـ/وسـ/فسـ can attach to."""

_ENCLITICS_BY_LAST: dict[str, tuple[str, ...]] = {
    "ا": ("هما", "كما", "ها", "نا"),
    "م": ("هم", "كم"),
    "ن": ("هن", "كن"),
    "ي": ("ني", "ي"),
    "ه": ("ه",),
    "ك": ("ك",),
}
"""Pronoun suffixes dispatched by final letter, longest first."""

_HAMZA_ON_ALIF = str.maketrans("أإآ", "ااا")


def plain(text: str) -> str:
    """`text` without Arabic's vowel marks and with alif wasla as plain alif:
    "الْكِتَابُ" -> "الكتاب", "ٱللَّهِ" -> "الله"."""
    if not unicodedata.is_normalized("NFC", text):
        text = unicodedata.normalize("NFC", text)
    return text.translate(_MARKS)


_DEFINITE_PROCLITICS = frozenset(
    {
        "وبال",
        "فبال",
        "وكال",
        "فكال",
        "وال",
        "فال",
        "بال",
        "كال",
        "ولل",
        "فلل",
        "لل",
        "ال",
    }
)
"""Proclitics that include the definite article الـ (mutually exclusive with
verbal 1sg object suffix -ني)."""


def _spelling_alts(stem: str, has_hamza: bool) -> list[str]:
    """Bare-alif (initial hamza first, then all alif-hamzas) and final ي<->ى variants."""
    out: list[str] = []
    n = len(stem)
    if has_hamza and n >= MIN_HAMZA_STRIP_LEN:
        if stem[0] in ("أ", "إ", "آ"):
            out.append("ا" + stem[1:])
        bare = stem.translate(_HAMZA_ON_ALIF)
        if bare != stem:
            out.append(bare)
            if bare[-1] in ("ي", "ى"):
                out.append(bare[:-1] + ("ى" if bare[-1] == "ي" else "ي"))
    if n >= MIN_CLITIC_STEM and stem[-1] in ("ي", "ى"):
        out.append(stem[:-1] + ("ى" if stem[-1] == "ي" else "ي"))
    return out


def bases(word: str) -> tuple[str, ...]:
    """What an Arabic word may be without its clitics or regular endings,
    likeliest first: without vowel marks, without proclitics (including future
    سـ/وسـ/فسـ before imperfect prefixes), without an attached pronoun (with
    ت->ة, اؤ/ائ->اء, ا->ى stem restoration), then orthographic bare-alif/ي<->ى
    variants, regular -ات/-ة nominal forms, and dropped initial hamza."""
    text = plain(word)
    if not text:
        return ()
    out: list[str] = [text] if text != word else []
    stems: list[tuple[str, bool]] = [(text, text.startswith("ال"))]
    first = text[0]
    plen = len(text)
    if first in _PROCLITICS_BY_FIRST:
        for prefix in _PROCLITICS_BY_FIRST[first]:
            if plen - len(prefix) >= MIN_CLITIC_STEM and text.startswith(prefix):
                rest = text[len(prefix) :]
                stems.append(
                    (rest, prefix in _DEFINITE_PROCLITICS or rest.startswith("ال"))
                )
    if first in _FUTURE_BY_FIRST:
        for prefix in _FUTURE_BY_FIRST[first]:
            if plen - len(prefix) >= MIN_FUTURE_STEM and text.startswith(prefix):
                rest = text[len(prefix) :]
                if rest[0] in _IMPERFECT_PREFIXES:
                    stems.append((rest, False))
    if len(stems) > 1:
        out.extend(s for s, _ in stems[1:])

    has_hamza = ("أ" in text) or ("إ" in text) or ("آ" in text)

    pron_bases: list[str] = []
    for stem, definite in stems:
        endings = _ENCLITICS_BY_LAST.get(stem[-1])
        if not endings:
            continue
        slen = len(stem)
        for ending in endings:
            if ending == "ني" and definite:
                continue  # verbal 1sg object pronoun never attaches to definite ال-
            elen = len(ending)
            if slen - elen >= MIN_CLITIC_STEM and stem.endswith(ending):
                base = stem[:-elen]
                out.append(base)
                pron_bases.append(base)
                last = base[-1]
                if last == "ت":
                    out.append(base[:-1] + "ة")
                elif (
                    (last == "ؤ" or last == "ئ")
                    and len(base) >= MIN_HAMZA_PRON_STEM
                    and base[-2] == "ا"
                ):
                    restored = base[:-1] + "ء"
                    out.append(restored)
                    if has_hamza:
                        bare_h = restored.translate(_HAMZA_ON_ALIF)
                        if bare_h != restored:
                            out.append(bare_h)
                elif last == "ا" and len(base) >= MIN_ALIF_MAQSURA_STEM:
                    out.append(base[:-1] + "ى")

    if has_hamza or text[-1] in ("ي", "ى"):
        for stem, _ in stems:
            out.extend(_spelling_alts(stem, has_hamza))

    for stem, _ in stems:
        if len(stem) >= MIN_REGULAR_SUFFIX_STEM:
            if stem.endswith("ات"):
                for cand in (stem[:-2] + "ة", stem[:-2]):
                    out.append(cand)
                    if has_hamza or cand[-1] in ("ي", "ى"):
                        out.extend(_spelling_alts(cand, has_hamza))
            elif stem[-1] == "ة" and stem[-2] not in ("أ", "ا"):
                cand = stem[:-1]
                out.append(cand)
                if has_hamza or cand[-1] in ("ي", "ى"):
                    out.extend(_spelling_alts(cand, has_hamza))
    for base in pron_bases:
        if len(base) >= MIN_REGULAR_SUFFIX_STEM and base.endswith("ات"):
            for cand in (base[:-2] + "ة", base[:-2]):
                out.append(cand)
                if has_hamza or cand[-1] in ("ي", "ى"):
                    out.extend(_spelling_alts(cand, has_hamza))

    for stem, _ in stems:
        if (
            stem[0] == "ا"
            and len(stem) >= MIN_INITIAL_ALIF_STEM
            and not stem.startswith("ال")
        ):
            out.append("أ" + stem[1:])
            out.append("إ" + stem[1:])

    if not out:
        return ()
    if len(out) == 1:
        return () if out[0] == word else (out[0],)
    return tuple(dict.fromkeys(w for w in out if w != word))
