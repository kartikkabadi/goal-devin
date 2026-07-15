"""Tiny hook executable invoked by Devin for each lifecycle event.

Reads one JSON object from stdin, extracts only the approved fields, redacts
everything else, and writes a sanitized event file into the runtime spool.
"""

from __future__ import annotations

import json
import os
import secrets
import sys
import tempfile
import time
from pathlib import Path

from native_launcher_python.config import GOAL_DEVIN_HOOK_MARKER, SCHEMA_VERSION


def _extract(event_name: str, payload: dict[str, object]) -> dict[str, object]:
    """Extract only the fields approved by the trial contract."""
    tool_name: str | None = None
    profile: str | None = None
    is_background: bool | None = None
    success: bool | None = None

    if event_name in {"PreToolUse", "PostToolUse"}:
        tool_name = payload.get("tool_name") if isinstance(payload.get("tool_name"), str) else None
        tool_input = payload.get("tool_input")
        tool_response = payload.get("tool_response")
        if isinstance(tool_input, dict):
            prof = tool_input.get("profile")
            if isinstance(prof, str):
                profile = prof
            bg = tool_input.get("is_background")
            if isinstance(bg, bool):
                is_background = bg
        if isinstance(tool_response, dict):
            succ = tool_response.get("success")
            if isinstance(succ, bool):
                success = succ

    return {
        "schema_version": SCHEMA_VERSION,
        "event": event_name,
        "tool_name": tool_name,
        "profile": profile,
        "is_background": is_background,
        "success": success,
        "observed_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "marker": GOAL_DEVIN_HOOK_MARKER,
    }


def _runtime_dir() -> Path:
    path = os.environ.get("GOAL_DEVIN_RUNTIME_DIR")
    if not path:
        raise RuntimeError("GOAL_DEVIN_RUNTIME_DIR is not set")
    return Path(path).expanduser().resolve()


def main() -> int:
    event_name = sys.argv[1] if len(sys.argv) > 1 else "Unknown"
    runtime_dir = _runtime_dir()
    events_dir = runtime_dir / "events"
    events_dir.mkdir(parents=True, exist_ok=True)

    try:
        payload = json.load(sys.stdin)
    except Exception:
        payload = {}
    if not isinstance(payload, dict):
        payload = {}

    sanitized = _extract(event_name, payload)
    event_id = f"{event_name}-{int(time.time() * 1e9)}-{secrets.token_hex(4)}"
    final_path = events_dir / f"{event_id}.json"

    fd, tmp = tempfile.mkstemp(dir=events_dir, prefix=".tmp-", suffix=".json")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(sanitized, f, separators=(",", ":"))
        os.chmod(tmp, 0o600)
        os.replace(tmp, final_path)
    except Exception:
        try:
            os.unlink(tmp)
        except FileNotFoundError:
            pass
        raise

    return 0


if __name__ == "__main__":
    sys.exit(main())
