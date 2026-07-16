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
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

MAX_STDIN_BYTES = 1024 * 1024

# Semantic minimums for the canonical PostToolUse/run_subagent evidence event.
MIN_TOOL_NAME_LENGTH = len("run_subagent")
MIN_PROFILE_LENGTH = len("goal-devin-worker-" + "0" * 16)
MIN_EVENT_VALUE_LENGTH = max(
    MIN_TOOL_NAME_LENGTH,
    MIN_PROFILE_LENGTH,
    len("2026-07-15T00:00:00.000000+00:00"),
)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


@dataclass(frozen=True)
class Limits:
    max_tool_name_length: int = 128
    max_profile_length: int = 128
    max_event_value_length: int = 256
    max_event_json_bytes: int = 4096


def _default_limits() -> Limits:
    return Limits()


def _coerce_limits(data: Any) -> Limits:
    """Return a validated Limits object from parsed JSON, or defaults on any error."""
    if not isinstance(data, dict):
        return _default_limits()
    try:
        tool = int(data.get("max_tool_name_length", Limits.max_tool_name_length))
        profile = int(data.get("max_profile_length", Limits.max_profile_length))
        value = int(data.get("max_event_value_length", Limits.max_event_value_length))
        event = int(data.get("max_event_json_bytes", Limits.max_event_json_bytes))
        for v, name in (
            (tool, "max_tool_name_length"),
            (profile, "max_profile_length"),
            (value, "max_event_value_length"),
            (event, "max_event_json_bytes"),
        ):
            if not isinstance(v, int) or isinstance(v, bool) or v < 1:
                raise ValueError(f"{name} must be a positive integer")
        if tool < MIN_TOOL_NAME_LENGTH:
            raise ValueError(f"max_tool_name_length must be >= {MIN_TOOL_NAME_LENGTH}")
        if profile < MIN_PROFILE_LENGTH:
            raise ValueError(f"max_profile_length must be >= {MIN_PROFILE_LENGTH}")
        if value < MIN_EVENT_VALUE_LENGTH:
            raise ValueError(f"max_event_value_length must be >= {MIN_EVENT_VALUE_LENGTH}")
        if value < max(tool, profile):
            raise ValueError(
                "max_event_value_length must be >= max(max_tool_name_length, max_profile_length)"
            )
        min_event_json = max(value, 256)
        if event < min_event_json:
            raise ValueError(f"max_event_json_bytes must be >= {min_event_json}")
        return Limits(tool, profile, value, event)
    except (ValueError, TypeError):
        return _default_limits()


def _load_limits(events_dir: Path) -> Limits:
    """Load limits from the runtime directory if present; otherwise use defaults."""
    runtime_dir = events_dir.parent
    limits_path = runtime_dir / "limits.json"
    if not limits_path.is_file():
        return _default_limits()
    try:
        data = json.loads(limits_path.read_text(encoding="utf-8"))
        return _coerce_limits(data)
    except (OSError, ValueError, json.JSONDecodeError, UnicodeDecodeError):
        return _default_limits()


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


def _sanitize_string(value: Any, max_length: int) -> str | None:
    if not isinstance(value, str):
        return None
    return value[:max_length]


def extract_event(payload: dict, limits: Limits) -> dict:
    """Extract only the approved, length-bounded event fields from a raw Devin hook payload."""
    hook_name = _sanitize_string(payload.get("hook_event_name"), limits.max_event_value_length)
    if not hook_name:
        hook_name = "PreToolUse"
    tool_name = _sanitize_string(payload.get("tool_name"), limits.max_tool_name_length)

    tool_input = payload.get("tool_input", {}) or {}
    if not isinstance(tool_input, dict):
        tool_input = {}

    profile = _sanitize_string(tool_input.get("profile"), limits.max_profile_length)
    is_background = tool_input.get("is_background", False)
    if not isinstance(is_background, bool):
        is_background = bool(is_background)

    tool_response = payload.get("tool_response", {}) or {}
    if not isinstance(tool_response, dict):
        tool_response = {}

    if hook_name == "PostToolUse":
        success = tool_response.get("success")
        if not isinstance(success, bool):
            success = None
    else:
        success = None

    return {
        "schema_version": 1,
        "event": hook_name,
        "tool_name": tool_name,
        "profile": profile,
        "is_background": is_background,
        "success": success,
        "observed_at": _now(),
    }


def _event_within_limits(event: dict, limits: Limits) -> bool:
    """Return True if the serialized event and its string fields fit the limits."""
    for key in ("event", "tool_name", "profile", "observed_at"):
        value = event.get(key)
        if isinstance(value, str) and len(value) > limits.max_event_value_length:
            return False
    if (
        isinstance(event.get("tool_name"), str)
        and len(event["tool_name"]) > limits.max_tool_name_length
    ):
        return False
    if isinstance(event.get("profile"), str) and len(event["profile"]) > limits.max_profile_length:
        return False
    try:
        serialized = json.dumps(event, separators=(",", ":")).encode("utf-8")
    except (TypeError, ValueError):
        return False
    if len(serialized) > limits.max_event_json_bytes:
        return False
    return True


def main(events_dir: Path | None = None) -> int:
    """Publish a sanitized event; always exit zero so Devin is never blocked."""
    try:
        events_dir = events_dir or Path(os.environ["GOAL_DEVIN_EVENTS_DIR"])
        limits = _load_limits(events_dir)
        payload = _read_payload()
        event = extract_event(payload, limits)
        if not _event_within_limits(event, limits):
            # Oversized or malformed events are dropped fail-open.
            return 0
        event_id = os.urandom(16).hex()
        final_path = events_dir / f"{event_id}.json"
        _atomic_write(final_path, json.dumps(event, indent=2))
    except Exception:
        pass
    return 0


if __name__ == "__main__":
    if len(sys.argv) > 1:
        events_dir = Path(sys.argv[1])
    else:
        events_dir = None
    sys.exit(main(events_dir))
