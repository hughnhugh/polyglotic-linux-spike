"""CLI for the settings net: inspect coverage, check determinism, and run reopen checks.

Usage:
    uv run python -m tools.settings_corpus check [--ref c51062c4a] [--generated 50]
    uv run python -m tools.settings_corpus coverage
    uv run python -m tools.settings_corpus reopen [--ref c51062c4a] [--generated 50]
"""

import argparse
import json
import tempfile
from collections.abc import Sequence
from pathlib import Path

from tools.settings_corpus.corpus import (
    ALWAYS_NORMALISED_FIELDS,
    corpus_cases,
    field_coverage,
    resolve_stored,
)
from tools.settings_corpus.generator import GENERATOR_LIMITATIONS, generate_cases
from tools.settings_corpus.reopen import (
    LAST_RELEASE_REF,
    extract_release_src,
    verify_round_trip_batch,
)


def _cmd_coverage() -> int:
    real = corpus_cases()
    cov = field_coverage(real)
    print(f"Real-shaped corpus files: {len(real)}")
    print(
        f"AppSettings fields: {cov.total_fields} total | "
        f"{len(cov.present_in_raw)} present in raw | "
        f"{len(cov.non_default_in_raw)} non-default in raw | "
        f"{len(cov.non_default_resolved)} non-default resolved"
    )
    if cov.missing_from_raw:
        print(f"MISSING from raw: {sorted(cov.missing_from_raw)}")
    if cov.default_only_in_raw:
        print(f"Default-only in raw: {sorted(cov.default_only_in_raw)}")
    unexpected_default_resolved = cov.default_only_resolved - ALWAYS_NORMALISED_FIELDS
    if unexpected_default_resolved:
        print(
            f"Unexpected default-only resolved: {sorted(unexpected_default_resolved)}"
        )
    print("Always-normalised fields (exercised in raw, normalised on read):")
    for name in sorted(ALWAYS_NORMALISED_FIELDS):
        print(f"  - {name}")
    print("What generated files cannot represent:")
    for item in GENERATOR_LIMITATIONS:
        print(f"  - {item}")
    return 1 if (cov.missing_from_raw or unexpected_default_resolved) else 0


def _cmd_reopen(ref: str, generated: int, seed: int) -> int:
    cases = [*corpus_cases(), *generate_cases(count=generated, seed=seed)]
    with tempfile.TemporaryDirectory(prefix="settings_net_") as tmp:
        root = Path(tmp)
        old_src = extract_release_src(ref, root / "release_src")
        failures = verify_round_trip_batch(old_src, cases, root / "work")
    if failures:
        print(
            f"FAIL: {len(failures)} of {len(cases)} cases failed reopen against {ref}:"
        )
        for fail in failures:
            print(f"  - {fail.name}: {fail.reason}")
            print(f"    {json.dumps(fail.details, default=str)[:300]}")
        return 1
    print(
        f"PASS: all {len(cases)} cases ({len(corpus_cases())} real-shaped + "
        f"{generated} generated) reopened cleanly in {ref}."
    )
    return 0


def _cmd_check(ref: str, generated: int, seed: int) -> int:
    cases = [*corpus_cases(), *generate_cases(count=generated, seed=seed)]
    first = {name: resolve_stored(raw).to_canonical_json() for name, raw in cases}
    second = {name: resolve_stored(raw).to_canonical_json() for name, raw in cases}
    if first != second:
        mismatches = [k for k in first if first[k] != second[k]]
        print(f"FAIL: corpus did not resolve identically twice: {mismatches}")
        return 1
    print(f"PASS: {len(cases)} corpus files resolved identically twice.")
    cov_rc = _cmd_coverage()
    reopen_rc = _cmd_reopen(ref, generated, seed)
    return 1 if (cov_rc or reopen_rc) else 0


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser(
        "coverage", help="Report 128-field coverage of the real-shaped corpus"
    )

    for name in ("check", "reopen"):
        p = sub.add_parser(name)
        p.add_argument(
            "--ref", default=LAST_RELEASE_REF, help="Git ref of the last release"
        )
        p.add_argument(
            "--generated", type=int, default=50, help="Number of generated files"
        )
        p.add_argument(
            "--seed", type=int, default=987, help="RNG seed for generated files"
        )

    args = parser.parse_args(argv)
    if args.command == "coverage":
        return _cmd_coverage()
    if args.command == "reopen":
        return _cmd_reopen(args.ref, args.generated, args.seed)
    return _cmd_check(args.ref, args.generated, args.seed)


if __name__ == "__main__":
    raise SystemExit(main())
