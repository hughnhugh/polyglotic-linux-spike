"""Command line entry point for ``python -m tools.proof``."""

import argparse
from pathlib import Path

from tools.proof.harness import run, selected


def main() -> int:
    parser = argparse.ArgumentParser(prog="python -m tools.proof")
    commands = parser.add_subparsers(dest="command", required=True)
    diff = commands.add_parser("diff", help="compare replay evidence from two commits")
    diff.add_argument("--base", required=True)
    diff.add_argument("--head", required=True)
    diff.add_argument("--what", default="replay,pictures")
    diff.add_argument("--output", type=Path, default=Path.cwd())
    args = parser.parse_args()
    if args.command == "diff":
        return run(Path.cwd(), args.base, args.head, selected(args.what), args.output)[
            0
        ]
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
