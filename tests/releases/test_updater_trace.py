"""Command-level trace of the updater's platform and channel contract."""

import json
import subprocess
import sys

import pytest
from tools.standins.updater_trace import VERSION

from polyglotic_desktop.core.releases.updates import CHANNELS

COMMAND = (sys.executable, "-m", "tools.standins.updater_trace")


def run_trace(*arguments: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        (*COMMAND, *arguments),
        check=False,
        capture_output=True,
        text=True,
        timeout=60,
    )


def test_all_81_channel_pairs_have_the_expected_trace() -> None:
    completed = run_trace()
    assert completed.returncode == 0, completed.stderr
    found = json.loads(completed.stdout)
    assert list(found["pairs"]) == sorted(
        f"{installed}->{offered}" for installed in CHANNELS for offered in CHANNELS
    )
    for installed in CHANNELS:
        for offered in CHANNELS:
            same_platform = installed.rsplit("-", 1)[0] == offered.rsplit("-", 1)[0]
            switching = same_platform and installed != offered
            channel = offered if switching else "installed"
            assert found["pairs"][f"{installed}->{offered}"] == [
                f"find:{channel}:{switching}",
                f"download:{VERSION}",
            ]


def test_trace_records_late_and_forced_ordinary_and_linux_paths() -> None:
    found = json.loads(run_trace().stdout)
    assert found["late_subscriber"] == [f"asking:{VERSION}"]
    assert found["ordinary"] == [
        "find:installed:False",
        f"download:{VERSION}",
    ]
    assert found["forced"] == [
        "find:installed:False",
        f"download:{VERSION}",
        f"restart:{VERSION}",
    ]
    assert found["linux_exit"] == [
        "find:installed:False",
        f"download:{VERSION}",
        f"apply:{VERSION}:restart=False",
    ]


def test_trace_is_identical_in_separate_processes() -> None:
    assert run_trace().stdout == run_trace().stdout


@pytest.mark.parametrize("fault", ["double-apply", "unasked-download"])
def test_planted_fault_is_rejected(fault: str) -> None:
    completed = run_trace("--fault", fault)
    assert completed.returncode != 0
    assert "AssertionError" in completed.stderr
