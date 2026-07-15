#!/usr/bin/env python3
"""Observation hook executed by fake/real Devin to publish sanitized events.

This script is intentionally self-contained so it can be copied into the
private runtime directory and invoked without access to the rest of the
candidate package.
"""

import json
import os
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path

MAX_STDIN_BYTES = 1024 * 1024


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _atomic_write(path: Path, data: str) -> None:
    directory = path.parent
    directory.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=directory, prefix=f"{path.name}.", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            fh.write(data)
            fh.flush()
            os.fsync(fh.fileno())
        os.chmod(tmp, 0o600)
        os.rename(tmp, path)
    except Exception:
        try:
            os.unlink(tmp)
        except FileNotFoundError:
            pass
        raise


def _read_payload() -> dict:
    raw = sys.stdin.buffer.read(MAX_STDIN_BYTES + 1)
    if len(raw) > MAX_STDIN_BYTES:
        raise ValueError("Hook payload too large")
    return json.loads(raw.decode("utf-8"))


def extract_event(payload: dict) -> dict:
    """Extract only the approved event fields from a raw Devin hook payload."""
    hook_name = payload.get("hook_event_name", "PreToolUse")
    tool_name = payload.get("tool_name")
    tool_input = payload.get("tool_input", {}) or {}
    tool_response = payload.get("tool_response", {}) or {}

    profile = tool_input.get("profile") if isinstance(tool_input, dict) else None
    is_background = (
        tool_input.get("is_background", False) if isinstance(tool_input, dict) else False
    )

    if hook_name == "PostToolUse":
        success = tool_response.get("success") if isinstance(tool_response, dict) else None
    else:
        success = None

    return {
        "schema_version": 1,
        "event": hook_name,
        "tool_name": tool_name,
        "profile": profile,
        "is_background": bool(is_background),
        "success": success,
        "observed_at": _now(),
    }


def main(events_dir: Path | None = None) -> int:
    events_dir = events_dir or Path(os.environ["GOAL_DEVIN_EVENTS_DIR"])
    payload = _read_payload()
    event = extract_event(payload)
    event_id = os.urandom(16).hex()
    tmp_path = events_dir / f"{event_id}.tmp"
    final_path = events_dir / f"{event_id}.json"
    _atomic_write(tmp_path, json.dumps(event, indent=2))
    os.rename(tmp_path, final_path)
    return 0


if __name__ == "__main__":
    if len(sys.argv) > 1:
        events_dir = Path(sys.argv[1])
    else:
        events_dir = None
    sys.exit(main(events_dir))
