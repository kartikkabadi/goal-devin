#!/usr/bin/env python3
"""Negative-control candidate that writes a valid sidecar.pid but no child.pid.
The runner must reject the overlap and still reap the valid sidecar process.
"""

import argparse
import os
import subprocess
import time
from pathlib import Path


def main() -> None:
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

    # Start a real helper that is in the candidate process tree.
    helper = subprocess.Popen(["sleep", "60"])

    (run_dir / "supervisor.pid").write_text(str(os.getpid()), encoding="utf-8")
    (run_dir / "sidecar.pid").write_text(str(helper.pid), encoding="utf-8")
    # Intentionally omit child.pid.

    while True:
        time.sleep(3600)


if __name__ == "__main__":
    main()
