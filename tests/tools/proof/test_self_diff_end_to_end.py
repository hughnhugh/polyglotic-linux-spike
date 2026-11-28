"""The difference harness end to end: a commit diffed against itself, with
the replay and the pictures, inside the budget (HQ 1016: within 10 minutes
on GitHub's Windows machine).

Slow, so it runs only with PROOF_E2E=1. Run it directly
(`python tests/tools/proof/test_self_diff_end_to_end.py`), which sets that
and runs this file through pytest, or through `scripts/remote_test.py --each`.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import time
from pathlib import Path

import pytest

SELF_DIFF_BUDGET_S = 600.0
"""Seconds for the whole self-diff (replay and pictures, every fixture) on
GitHub's Windows machine: the budget in 933's PLAN for platform-4. Range:
the budget itself; a slower machine only reports."""

ROOT = Path(__file__).resolve().parents[3]


@pytest.mark.skipif(os.environ.get("PROOF_E2E") != "1", reason="slow: PROOF_E2E=1")
def test_a_commit_diffed_against_itself_is_quiet_and_within_budget(
    tmp_path: Path,
) -> None:
    began = time.monotonic()
    done = subprocess.run(
        [
            sys.executable,
            "-m",
            "tools.proof",
            "diff",
            "--base",
            "HEAD",
            "--head",
            "HEAD",
            "--what",
            "replay,pictures",
            "--output",
            str(tmp_path),
        ],
        cwd=ROOT,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
    )
    took = time.monotonic() - began
    tail = "\n".join((done.stdout + done.stderr).splitlines()[-20:])
    print(f"self-diff took {took:.1f} s (exit {done.returncode})\n{tail}")
    report = tmp_path / "proof.json"
    assert report.exists(), f"no proof.json after {took:.1f} s:\n{tail}"
    found = json.loads(report.read_text(encoding="utf-8"))
    print(json.dumps({k: found[k] for k in found if k != "differences"})[:2000])
    assert done.returncode == 0, tail
    assert took <= SELF_DIFF_BUDGET_S, f"self-diff took {took:.1f} s"


if __name__ == "__main__":
    os.environ["PROOF_E2E"] = "1"
    sys.exit(pytest.main(["-q", "-s", "-p", "no:cacheprovider", __file__]))
