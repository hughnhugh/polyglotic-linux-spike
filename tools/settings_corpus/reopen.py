"""Run the last release's own settings code from git in its own process.

Extracts `src/polyglotic_desktop` at `LAST_RELEASE_REF` (`c51062c4a`, 0.1.12)
via `git archive` and executes that release's `AppSettings` and `use_presets`
readers/writers in an isolated child Python process. This proves that:
1. the last release rejects no existing key written by the candidate build;
2. every choice the last release can hold comes back unchanged; and
3. saving an unrelated change in the last release leaves every candidate choice
   and foreign/future key intact when the candidate reopens the file.
"""

import io
import json
import os
import subprocess
import sys
import tarfile
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any

from polyglotic_desktop.ui.settings import with_changed
from tools.settings_corpus.corpus import resolve_stored

REPO_ROOT = Path(__file__).resolve().parents[2]
LAST_RELEASE_REF = "c51062c4a"
"""Release 0.1.12 (#1205), the last shipped release on main."""


class ReleaseSourceUnavailable(RuntimeError):
    """Raised when `LAST_RELEASE_REF` cannot be extracted from git."""


@dataclass(frozen=True, slots=True)
class ReopenOutcome:
    """Result of reopening and saving one settings document in the last release."""

    name: str
    rejected: dict[str, Any]
    reopened: dict[str, Any]
    saved: dict[str, Any]
    unknown_keys: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class RoundTripFailure:
    """One failure found when checking candidate -> last release -> candidate."""

    name: str
    reason: str
    details: dict[str, Any]


def extract_release_src(
    ref: str = LAST_RELEASE_REF,
    dest: Path | None = None,
    *,
    repo_root: Path = REPO_ROOT,
) -> Path:
    """Extract `src/polyglotic_desktop` at git commit `ref` into `dest`."""
    if dest is None:
        raise ValueError("dest directory is required")
    target_src = dest / "src"
    if (target_src / "polyglotic_desktop" / "__init__.py").is_file():
        return target_src
    dest.mkdir(parents=True, exist_ok=True)
    try:
        subprocess.run(
            ["git", "rev-parse", "--verify", "--quiet", f"{ref}^{{commit}}"],
            cwd=repo_root,
            capture_output=True,
            check=True,
        )
        archived = subprocess.run(
            ["git", "archive", "--format=tar", ref, "src/polyglotic_desktop"],
            cwd=repo_root,
            capture_output=True,
            check=True,
        )
    except (OSError, subprocess.CalledProcessError) as exc:
        raise ReleaseSourceUnavailable(
            f"cannot load {ref} from git (git missing or shallow/snapshot checkout): {exc}"
        ) from exc
    with tarfile.open(fileobj=io.BytesIO(archived.stdout)) as archive:
        archive.extractall(dest, filter="data")
    return target_src


_BATCH_REOPEN_SCRIPT = """
import json
import sys
from dataclasses import fields, replace
from pathlib import Path

old_src = Path(sys.argv[1]).resolve()
in_path = Path(sys.argv[2])
out_path = Path(sys.argv[3])

sys.path.insert(0, str(old_src))
import polyglotic_desktop
from polyglotic_desktop.ui import use_presets
from polyglotic_desktop.ui.settings import _INVALID, _valid, AppSettings, with_changed

loaded_from = Path(polyglotic_desktop.__file__).resolve()
assert loaded_from.is_relative_to(old_src), (
    f"imported polyglotic_desktop from {loaded_from}, expected under {old_src}"
)

cases = json.loads(in_path.read_text(encoding="utf-8"))
defaults = AppSettings()
app_fields = fields(AppSettings)
known = {f.name for f in app_fields}

results = []
for entry in cases:
    name = entry["name"]
    stored = entry["stored"]
    rejected = {
        f.name: stored[f.name]
        for f in app_fields
        if f.name in stored
        and _valid(f.name, stored[f.name], getattr(defaults, f.name)) is _INVALID
    }
    read = AppSettings.from_stored(stored)
    value = use_presets.from_flat(
        use_presets.follow_reading_defaults(read, stored),
        before_presets="preset" not in stored,
        built_ins=read.built_ins if "built_ins" in stored else 1,
    )
    reopened = value.to_stored()
    unknown = {k: v for k, v in stored.items() if k not in known}
    edited = with_changed(
        value,
        replace(value, transcript_ask_at_quit=not value.transcript_ask_at_quit),
    )
    saved = {**unknown, **edited.to_stored()}
    results.append(
        {
            "name": name,
            "rejected": rejected,
            "reopened": reopened,
            "saved": saved,
            "unknown_keys": sorted(unknown),
        }
    )

out_path.write_text(json.dumps(results, ensure_ascii=False), encoding="utf-8")
"""


def reopen_batch(
    old_src: Path,
    cases: Sequence[tuple[str, Mapping[str, object]]],
    work_dir: Path,
    *,
    stem: str = "reopen_batch",
) -> list[ReopenOutcome]:
    """Run the extracted release's reader/writer in a fresh child process over `cases`."""
    work_dir.mkdir(parents=True, exist_ok=True)
    in_path = work_dir / f"{stem}_in.json"
    out_path = work_dir / f"{stem}_out.json"
    payload = [{"name": name, "stored": dict(stored)} for name, stored in cases]
    in_path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")

    # Strip any ambient PYTHONPATH so only `old_src` is importable as polyglotic_desktop.
    env = {k: v for k, v in os.environ.items() if k != "PYTHONPATH"}
    env["PYTHONPATH"] = str(old_src.resolve())

    done = subprocess.run(
        [
            sys.executable,
            "-I",
            "-c",
            _BATCH_REOPEN_SCRIPT,
            str(old_src.resolve()),
            str(in_path),
            str(out_path),
        ],
        cwd=work_dir,
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )
    if done.returncode != 0:
        raise RuntimeError(
            f"last-release reopen subprocess failed (exit {done.returncode}):\n"
            f"STDOUT:\n{done.stdout}\nSTDERR:\n{done.stderr}"
        )
    raw_results = json.loads(out_path.read_text(encoding="utf-8"))
    return [
        ReopenOutcome(
            name=item["name"],
            rejected=item["rejected"],
            reopened=item["reopened"],
            saved=item["saved"],
            unknown_keys=tuple(item["unknown_keys"]),
        )
        for item in raw_results
    ]


def verify_round_trip_batch(
    old_src: Path,
    cases: Sequence[tuple[str, Mapping[str, object]]],
    work_dir: Path,
    *,
    stem: str = "round_trip",
) -> list[RoundTripFailure]:
    """Check candidate -> last release reopen & save -> candidate reopen for `cases`."""
    prepared: list[tuple[str, Any, dict[str, Any]]] = []
    batch_input: list[tuple[str, dict[str, Any]]] = []
    for name, raw in cases:
        snap = resolve_stored(raw)
        written: dict[str, Any] = {**snap.foreign_keys, **snap.stored}
        prepared.append((name, snap, written))
        batch_input.append((name, written))

    outcomes = reopen_batch(old_src, batch_input, work_dir, stem=stem)
    failures: list[RoundTripFailure] = []

    for (name, snap, written), outcome in zip(prepared, outcomes, strict=True):
        if outcome.rejected:
            failures.append(
                RoundTripFailure(
                    name=name,
                    reason="last release rejected existing keys written by candidate",
                    details={"rejected": outcome.rejected},
                )
            )
            continue

        changed_in_old = {
            key: {"written": written.get(key), "reopened": old_val}
            for key, old_val in outcome.reopened.items()
            if written.get(key) != old_val
        }
        if changed_in_old:
            failures.append(
                RoundTripFailure(
                    name=name,
                    reason="last release did not read back candidate's legacy keys unchanged",
                    details={"diffs": changed_in_old},
                )
            )
            continue

        after = resolve_stored(outcome.saved)
        expected_value = with_changed(
            snap.value,
            replace(
                snap.value,
                transcript_ask_at_quit=not snap.value.transcript_ask_at_quit,
            ),
        )
        if after.value != expected_value:
            field_diffs = {
                key: {
                    "expected": getattr(expected_value, key),
                    "actual": getattr(after.value, key),
                }
                for key in expected_value.__dataclass_fields__
                if getattr(expected_value, key) != getattr(after.value, key)
            }
            failures.append(
                RoundTripFailure(
                    name=name,
                    reason="candidate lost choices after last release saved an unrelated edit",
                    details={"field_diffs": field_diffs},
                )
            )
            continue

        lost_foreign = {
            k: {"expected": v, "actual": outcome.saved.get(k)}
            for k, v in snap.foreign_keys.items()
            if outcome.saved.get(k) != v
        }
        if lost_foreign:
            failures.append(
                RoundTripFailure(
                    name=name,
                    reason="last release dropped or altered foreign/side-store keys on save",
                    details={"lost_foreign": lost_foreign},
                )
            )

    return failures
