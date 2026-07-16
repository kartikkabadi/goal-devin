#!/usr/bin/env python3
"""Candidate fixture that creates a new canary symlink pointing at an owned runtime file.

The symlink target is inside the runtime root (owned), but the symlink entry itself is
not declared in the manifest and must be rejected.
"""

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
    if supervisor.canary is not None and supervisor.manifest_path is not None:
        link = supervisor.canary / "owned-link"
        link.symlink_to(supervisor.manifest_path)
    return rc


if __name__ == "__main__":
    sys.exit(main())
