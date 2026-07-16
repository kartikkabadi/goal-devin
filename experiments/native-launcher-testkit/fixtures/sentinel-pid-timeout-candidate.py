#!/usr/bin/env python3
"""Candidate fixture that writes a non-descendant PID into child.pid and hangs.

The runner's timeout cleanup must not signal the unrelated sentinel process.
"""

import argparse
import os
import secrets
import sys
import time
from pathlib import Path


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--runtime-root", required=True)
    parser.add_argument("--canary", required=True)
    # Accept and ignore other candidate arguments that the runner may pass.
    args, _ = parser.parse_known_args()

    run_id = secrets.token_hex(16)
    run_dir = Path(args.runtime_root) / run_id
    run_dir.mkdir(parents=True, mode=0o700)
    (run_dir / "supervisor.pid").write_text(str(os.getpid()), encoding="utf-8")

    sentinel = int(os.environ["GOAL_DEVIN_SENTINEL_PID"])
    (run_dir / "child.pid").write_text(str(sentinel), encoding="utf-8")

    while True:
        time.sleep(1)


if __name__ == "__main__":
    sys.exit(main())
