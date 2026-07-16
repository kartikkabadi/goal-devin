#!/usr/bin/env python3
"""Candidate fixture that delays sidecar PID creation to test the timeout re-discovery path.

The sidecar is not started until after the runner's first PID discovery window has
passed, forcing the normal-mode timeout cleanup to re-discover and kill it.
"""

import os
import sys
import time
from pathlib import Path


candidate_dir = Path(__file__).resolve().parents[2] / "native-launcher-python"
if str(candidate_dir) not in sys.path:
    sys.path.insert(0, str(candidate_dir))

from native_launcher.cli import build_parser  # noqa: E402
from native_launcher.supervisor import Supervisor as BaseSupervisor  # noqa: E402


class Supervisor(BaseSupervisor):
    def _start_sidecar(self) -> None:
        # Delay long enough that the runner's initial _discover_pids window
        # (about 2s) closes before sidecar.pid is written.
        time.sleep(2.5)
        super()._start_sidecar()


def main() -> int:
    os.environ["GOAL_DEVIN_FAKE_HANG"] = "1"
    parser = build_parser()
    args = parser.parse_args()
    return Supervisor(args).run()


if __name__ == "__main__":
    sys.exit(main())
