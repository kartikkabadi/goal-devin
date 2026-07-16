"""Command-line entry point for the Python native launcher candidate."""

import argparse
import sys

from .supervisor import Supervisor


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="goal-devin-dev",
        description="Goal Devin native-mode launcher candidate (R1A.1).",
    )
    parser.add_argument("--model", required=True, help="Exact root model for the session.")
    parser.add_argument(
        "--permission-mode",
        required=True,
        help="Permission mode to pass through to Devin (e.g. accept-edits in the v3000.1.27 fixture).",
    )
    parser.add_argument(
        "--devin-bin", required=True, help="Path to the devin executable to launch."
    )
    parser.add_argument(
        "--contract-dir",
        required=True,
        help="Path to the shared testkit directory containing expected/*.schema.json.",
    )
    parser.add_argument(
        "--runtime-root",
        required=True,
        help="Directory where the candidate may create its private runtime directory.",
    )
    parser.add_argument(
        "--canary",
        default=None,
        help="Disposable canary directory inside --runtime-root (created if omitted).",
    )
    parser.add_argument(
        "--existing-hooks",
        default=None,
        help="Path to an existing .devin/hooks.v1.json fixture to pre-seed, merge, and restore.",
    )
    parser.add_argument(
        "--keep-canary",
        action="store_true",
        help="Do not remove the canary directory after the run (useful for tests).",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    return Supervisor(args).run()


if __name__ == "__main__":
    sys.exit(main())
