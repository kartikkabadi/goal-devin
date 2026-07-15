"""CLI entry point for the R1A Python native launcher."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from native_launcher_python.launcher import Launcher, LauncherOptions


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="goal-devin dev",
        description="Launch the native Devin TUI with Goal Devin policy and observation.",
    )
    parser.add_argument(
        "workdir",
        nargs="?",
        default=".",
        help="Working directory for the Devin session (default: current directory)",
    )
    parser.add_argument(
        "--model",
        required=True,
        help="Exact orchestrator model for the root session",
    )
    parser.add_argument(
        "--permission-mode",
        default="accept-edits",
        help="Permission mode for the session (default: accept-edits)",
    )
    parser.add_argument(
        "--sandbox",
        action="store_true",
        help="Enable Devin sandbox",
    )
    parser.add_argument(
        "--worker-model",
        default=None,
        help="Exact model for the temporary worker profile (default: same as root model)",
    )
    parser.add_argument(
        "--keep-profile",
        action="store_true",
        help="Do not remove the generated worker profile on exit",
    )
    parser.add_argument(
        "--keep-runtime",
        action="store_true",
        help="Do not remove the runtime directory on exit",
    )
    parser.add_argument(
        "--devin-arg",
        action="append",
        default=[],
        dest="extra_devin_args",
        help="Extra argument to pass through to the devin executable (repeatable)",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = _parser()
    args = parser.parse_args(argv)

    options = LauncherOptions(
        workdir=Path(args.workdir),
        model=args.model,
        permission_mode=args.permission_mode,
        sandbox=args.sandbox,
        worker_model=args.worker_model,
        keep_profile=args.keep_profile,
        keep_runtime=args.keep_runtime,
        extra_devin_args=args.extra_devin_args,
    )

    try:
        with Launcher(options) as launcher:
            return launcher.run()
    except Exception as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
