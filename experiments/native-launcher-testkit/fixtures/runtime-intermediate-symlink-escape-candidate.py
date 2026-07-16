#!/usr/bin/env python3
"""Candidate fixture that creates a runtime symlink whose lexical target is inside
runtime/ but whose effective target escapes through an intermediate symlink.
"""

import argparse
import os
import secrets
import sys
from pathlib import Path


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--runtime-root", required=True)
    parser.add_argument("--canary", required=True)
    args, _ = parser.parse_known_args()

    run_id = secrets.token_hex(16)
    run_dir = Path(args.runtime_root) / run_id
    run_dir.mkdir(parents=True, mode=0o700)
    (run_dir / "supervisor.pid").write_text(str(os.getpid()), encoding="utf-8")

    (run_dir / "bridge").symlink_to("/tmp")
    (run_dir / "link").symlink_to("bridge/file")

    return 0


if __name__ == "__main__":
    sys.exit(main())
