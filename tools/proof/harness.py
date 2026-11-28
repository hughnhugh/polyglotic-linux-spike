"""Worktree lifecycle, sampled noise control and reports."""

import json
import subprocess
import time
from collections.abc import Iterator, Sequence
from contextlib import ExitStack, contextmanager
from pathlib import Path
from tempfile import TemporaryDirectory

from tools.proof.model import Difference, Evidence
from tools.proof.plugins import PLUGINS, Plugin

# One deterministic fixture catches ambient renderer/replay noise without making
# the control repeat all 1,400+ fixtures. Range: exactly one fixture per proof
# kind; reason: it keeps the control independent while fitting the CI budget.
NOISE_CONTROL_FIXTURES_PER_PLUGIN = 1


def _same_commit(root: Path, base: str, head: str) -> bool:
    if base == head:
        return True
    resolved = []
    for revision in (base, head):
        resolved.append(
            subprocess.run(
                ["git", "rev-parse", revision],
                cwd=root,
                check=True,
                capture_output=True,
                text=True,
            ).stdout.strip()
        )
    return resolved[0] == resolved[1]


@contextmanager
def worktree(root: Path, revision: str, target: Path) -> Iterator[Path]:
    subprocess.run(
        ["git", "worktree", "add", "--detach", str(target), revision],
        cwd=root,
        check=True,
        stdout=subprocess.DEVNULL,
    )
    try:
        yield target
    finally:
        subprocess.run(
            ["git", "worktree", "remove", "--force", str(target)],
            cwd=root,
            check=True,
            stdout=subprocess.DEVNULL,
        )


def _plain(evidence: Evidence) -> dict[str, object]:
    return {
        "what": evidence.what,
        "fixtures": evidence.fixtures,
        "fingerprints": {
            key: list(value) for key, value in evidence.fingerprints.items()
        },
    }


def _markdown(result: dict[str, object]) -> str:
    lines = ["# Proof", "", f"Status: **{result['status']}**.", ""]
    differences = result["differences"]
    assert isinstance(differences, list)
    if differences:
        lines += [
            "| What | Fixture | Frame | Rule | Detail |",
            "|---|---|---:|---|---|",
        ]
        lines += [
            f"| {d['what']} | `{str(d['fixture']).replace('|', r'\|')}` | {d['frame']} | `{d['rule']}` | {d['detail']} |"
            for d in differences
        ]
    else:
        lines.append(
            "All selected evidence is identical; the repeated-base control was quiet."
        )
    lines += [
        "",
        (
            f"Runtime: {result['runtime_seconds']:.2f} seconds on Linux; "
            "target: under 10 minutes on GitHub's Windows machine."
        ),
    ]
    return "\n".join(lines) + "\n"


def run(
    root: Path,
    base: str,
    head: str,
    selected: Sequence[Plugin],
    output: Path,
    plants: dict[str, str] | None = None,
) -> tuple[int, dict[str, object]]:
    started = time.perf_counter()
    same_commit = _same_commit(root, base, head)
    with TemporaryDirectory(prefix="proof-") as temporary, ExitStack() as stack:
        temp = Path(temporary)
        checkouts = {
            "base": stack.enter_context(worktree(root, base, temp / "base")),
            "head": stack.enter_context(worktree(root, head, temp / "head")),
        }
        collected: dict[str, dict[str, Evidence]] = {}
        noisy: list[Difference] = []
        differences: list[Difference] = []
        for plugin in selected:
            scratches = [
                temp / f"{plugin.name}-base",
                temp / f"{plugin.name}-head",
                temp / f"{plugin.name}-control",
            ]
            for scratch in scratches:
                scratch.mkdir()
            # Collect commits sequentially. Replay itself uses two workers, so
            # the harness, recorder and workers total no more than four processes.
            planted = (plants or {}).get(plugin.name)
            requests: list[tuple[Path, Path, str | None]] = [
                (checkouts["base"], scratches[0], None)
            ]
            reuse_base = same_commit and planted is None
            if not reuse_base:
                requests.append((checkouts["head"], scratches[1], planted))
            recordings = [plugin.collect(*request) for request in requests]
            base_evidence = recordings[0]
            head_evidence = base_evidence if reuse_base else recordings[1]
            collected[plugin.name] = {"base": base_evidence, "head": head_evidence}

            control_plugin, control_baseline = plugin.noise_control(base_evidence)
            assert control_baseline.fixtures == NOISE_CONTROL_FIXTURES_PER_PLUGIN
            control = control_plugin.collect(checkouts["base"], scratches[2], None)
            noisy.extend(control_plugin.compare(control_baseline, control))
            if not noisy:
                differences.extend(plugin.compare(base_evidence, head_evidence))
    status = "noisy" if noisy else ("different" if differences else "identical")
    result: dict[str, object] = {
        "status": status,
        "base": base,
        "head": head,
        "control_runs": 2,
        "control_fixtures_per_plugin": NOISE_CONTROL_FIXTURES_PER_PLUGIN,
        "self_diff_runs": 1 if same_commit and not plants else 2,
        "runtime_seconds": round(time.perf_counter() - started, 3),
        "evidence": {
            name: {side: _plain(value) for side, value in sides.items()}
            for name, sides in collected.items()
        },
        "differences": [item.plain() for item in (noisy or differences)],
    }
    output.mkdir(parents=True, exist_ok=True)
    (output / "proof.json").write_text(json.dumps(result, indent=2) + "\n", "utf-8")
    (output / "proof.md").write_text(_markdown(result), "utf-8")
    return (0 if status == "identical" else 1), result


def selected(names: str) -> list[Plugin]:
    requested = names.split(",")
    unknown = set(requested) - PLUGINS.keys()
    if unknown:
        raise ValueError("unknown proof kind: " + ", ".join(sorted(unknown)))
    return [PLUGINS[name] for name in requested]
