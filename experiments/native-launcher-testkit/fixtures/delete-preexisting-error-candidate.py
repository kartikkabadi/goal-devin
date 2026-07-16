#!/usr/bin/env python3
"""Negative-control candidate that deletes a pre-existing canary file and exits
nonzero before producing a manifest. The shared runner must still detect the
missing pre-existing path.
"""

import argparse
import sys
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

    canary = (
        Path(args.canary).resolve() if args.canary else Path(args.runtime_root).resolve() / "canary"
    )
    canary.mkdir(parents=True, exist_ok=True)

    fib_path = canary / "fib.py"
    if fib_path.exists():
        fib_path.unlink()

    sys.exit(7)


if __name__ == "__main__":
    main()
