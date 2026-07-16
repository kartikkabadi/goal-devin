#!/usr/bin/env python3
"""Negative-control candidate that creates a run directory but never writes PID files."""

import argparse
import os
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

    # Create the run directory but do not write any PID files.
    time.sleep(3600)


if __name__ == "__main__":
    main()
