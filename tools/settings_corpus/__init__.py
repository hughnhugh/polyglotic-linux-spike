"""The settings net (933 unit shell-1): corpus, generator and last-release reopen check.

Provides a deterministic corpus of real-shaped settings files (one per
historical release format, plus edge cases and 977's 0.1.13 hotkey case),
a seeded generator for synthetic valid/invalid/future-key documents, and an
isolated subprocess runner that checks rollback safety against the last
release's own settings code from git (`c51062c4a`).

Every fixture uses made-up values only (RULES #26, #30).
"""

from tools.settings_corpus.corpus import (
    CORPUS_DIR,
    FieldCoverage,
    ResolvedSnapshot,
    corpus_cases,
    field_coverage,
    load_corpus_file,
    resolve_stored,
)
from tools.settings_corpus.generator import (
    GENERATOR_LIMITATIONS,
    generate_cases,
)
from tools.settings_corpus.reopen import (
    LAST_RELEASE_REF,
    ReopenOutcome,
    RoundTripFailure,
    extract_release_src,
    reopen_batch,
    verify_round_trip_batch,
)

__all__ = [
    "CORPUS_DIR",
    "GENERATOR_LIMITATIONS",
    "LAST_RELEASE_REF",
    "FieldCoverage",
    "ReopenOutcome",
    "ResolvedSnapshot",
    "RoundTripFailure",
    "corpus_cases",
    "extract_release_src",
    "field_coverage",
    "generate_cases",
    "load_corpus_file",
    "reopen_batch",
    "resolve_stored",
    "verify_round_trip_batch",
]
