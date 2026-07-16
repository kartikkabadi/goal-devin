#!/usr/bin/env python3
"""Negative-control candidate that writes a bogus child PID pointing at an
unrelated live sentinel process.  The runner must reject the overlap without
signaling the sentinel.
"""

import argparse
import os
import subprocess
import time
from pathlib import Path


def main() -> None:
    os.umask(0o077)
    parser = argparse.ArgumentParser()
    parser.add_argument("--model", required=True)
    parser.add_argument("--permission-mode", required=True)
    parser.add_argument("--devin-bin", required=True)
    parser.add_argument("--contract-dir", required=True)
    parser.add_argument("--runtime-root", required=True)
    parser.add_argument("--canary", default=None)
    parser.add_argument("--existing-hooks", default=None)
    parser.add_argument("--keep-canary", action="store_true")
    args = parser.parse_args()

    runtime_root = Path(args.runtime_root).resolve()
    run_id = os.urandom(16).hex()
    run_dir = runtime_root / run_id
    run_dir.mkdir(parents=True, exist_ok=True)

    canary = Path(args.canary).resolve() if args.canary else runtime_root / "canary"
    canary.mkdir(parents=True, exist_ok=True)

    sentinel_pid = int(os.environ.get("GOAL_DEVIN_SENTINEL_PID", "0"))
    if sentinel_pid <= 0:
        raise SystemExit("GOAL_DEVIN_SENTINEL_PID not set")

    # A helper that is actually in the candidate tree, to fill the sidecar PID slot.
    helper = subprocess.Popen(["sleep", "60"])

    (run_dir / "supervisor.pid").write_text(str(os.getpid()), encoding="utf-8")
    (run_dir / "sidecar.pid").write_text(str(helper.pid), encoding="utf-8")
    (run_dir / "child.pid").write_text(str(sentinel_pid), encoding="utf-8")

    # Keep the candidate alive until the runner reaps it.
    while True:
        time.sleep(1)


if __name__ == "__main__":
    main()
