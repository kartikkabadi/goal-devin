#!/usr/bin/env python3
"""Negative-control candidate that corrupts the canary and exits nonzero before
producing a manifest.  The runner must still detect the canary integrity violation.
"""

import argparse
import os
import sys
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

    canary = (
        Path(args.canary).resolve() if args.canary else Path(args.runtime_root).resolve() / "canary"
    )
    canary.mkdir(parents=True, exist_ok=True)

    # Corrupt the canary and exit before the runner can observe a manifest.
    (canary / "corrupt-before-manifest.txt").write_text("mutation", encoding="utf-8")
    sys.exit(7)


if __name__ == "__main__":
    main()
