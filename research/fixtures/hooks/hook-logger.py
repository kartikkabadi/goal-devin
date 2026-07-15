#!/usr/bin/env python3
"""Observation-only Devin CLI hook logger for research.

Reads a JSON event from stdin, redacts values for sensitive keys, records the
sanitized payload to a per-event log under $HOOK_LOG_DIR, and exits 0.
"""

import json
import os
import sys


REDACT_KEYS = {
    "session_id",
    "prompt",
    "command",
    "content",
    "message",
    "chat_message",
    "metadata",
    "output",
    "error",
    "summary",
    "reason",
    "source",
    "title",
    "working_directory",
    "workspace_dirs",
    "cogs_json",
    "tool_call_json",
    "tool_call_update_json",
    "tool_input",
    "tool_response",
    "request_id",
    "installation_id",
    "user_id",
    "team_id",
    "email",
    "name",
}
SAFE_KEYS = {"tool_name", "hook_event_name", "success", "matcher", "timeout", "type", "decision"}


def redact(obj, key=None):
    if isinstance(obj, dict):
        return {k: redact(v, key=k) for k, v in obj.items()}
    if isinstance(obj, list):
        return [redact(item) for item in obj]
    if isinstance(obj, str):
        if key in SAFE_KEYS:
            return obj
        if key in REDACT_KEYS:
            return "<REDACTED>"
        # Heuristic: long strings are likely content/ids.
        if len(obj) > 64:
            return "<REDACTED>"
        return obj
    if isinstance(obj, bool):
        return obj
    if isinstance(obj, (int, float)):
        return obj
    return obj


def main():
    event_name = sys.argv[1] if len(sys.argv) > 1 else "Unknown"
    log_dir = os.environ.get(
        "HOOK_LOG_DIR", "/home/ubuntu/repos/goal-devin/.research-evidence/hooks"
    )
    os.makedirs(log_dir, exist_ok=True)
    log_path = os.path.join(log_dir, f"{event_name}.jsonl")

    payload = {}
    try:
        payload = json.load(sys.stdin)
    except Exception:
        payload = {"raw": sys.stdin.read()}

    sanitized = {
        "hook_event_name": event_name,
        "payload": redact(payload),
    }

    with open(log_path, "a") as f:
        f.write(json.dumps(sanitized, separators=(",", ":")) + "\n")


if __name__ == "__main__":
    main()
