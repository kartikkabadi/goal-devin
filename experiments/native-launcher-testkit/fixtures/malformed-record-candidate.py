#!/usr/bin/env python3
"""Candidate fixture that writes a malformed fake-devin.record.json after the run."""

import sys
from pathlib import Path


candidate_dir = Path(__file__).resolve().parents[2] / "native-launcher-python"
if str(candidate_dir) not in sys.path:
    sys.path.insert(0, str(candidate_dir))

from native_launcher.cli import build_parser  # noqa: E402
from native_launcher.supervisor import Supervisor  # noqa: E402


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()
    supervisor = Supervisor(args)
    rc = supervisor.run()
    if supervisor.runtime_dir is not None and supervisor.runtime_dir.exists():
        (supervisor.runtime_dir / "fake-devin.record.json").write_text(
            "{ not valid json", encoding="utf-8"
        )
    return rc


if __name__ == "__main__":
    sys.exit(main())
