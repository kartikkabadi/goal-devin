#!/usr/bin/env python3
"""Candidate fixture that forks a small tree of long-lived child processes.

The runner's timeout cleanup must reach a fixed point and reap every descendant.
"""

import argparse
import os
import secrets
import sys
import time
from pathlib import Path


def _spawn_tree(depth: int, width: int = 2) -> None:
    if depth == 0:
        time.sleep(60)
        return
    for _ in range(width):
        pid = os.fork()
        if pid == 0:
            try:
                _spawn_tree(depth - 1, width)
            finally:
                os._exit(0)
    time.sleep(60)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--runtime-root", required=True)
    parser.add_argument("--canary", required=True)
    args, _ = parser.parse_known_args()

    run_id = secrets.token_hex(16)
    run_dir = Path(args.runtime_root) / run_id
    run_dir.mkdir(parents=True, mode=0o700)
    (run_dir / "supervisor.pid").write_text(str(os.getpid()), encoding="utf-8")

    child = os.fork()
    if child == 0:
        try:
            _spawn_tree(2, 2)
        finally:
            os._exit(0)

    (run_dir / "child.pid").write_text(str(child), encoding="utf-8")
    time.sleep(60)
    return 0


if __name__ == "__main__":
    sys.exit(main())
