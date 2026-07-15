"""Sidecar entry point: watches the event spool and updates summary.json."""

from __future__ import annotations

import json
import os
import signal
import sys
import time
from pathlib import Path
from typing import Any

from native_launcher_python.config import SCHEMA_VERSION

POLL_INTERVAL = 0.2


def _now() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def _summary_template() -> dict[str, Any]:
    return {
        "schema_version": SCHEMA_VERSION,
        "event_count": 0,
        "tool_names": [],
        "profiles": [],
        "background_count": 0,
        "success_count": 0,
        "failure_count": 0,
        "started_at": _now(),
        "updated_at": _now(),
    }


def _update_summary(summary: dict[str, Any], event: dict[str, Any]) -> None:
    summary["event_count"] += 1
    summary["updated_at"] = _now()

    tool_name = event.get("tool_name")
    if isinstance(tool_name, str) and tool_name not in summary["tool_names"]:
        summary["tool_names"].append(tool_name)

    profile = event.get("profile")
    if isinstance(profile, str) and profile not in summary["profiles"]:
        summary["profiles"].append(profile)

    is_background = event.get("is_background")
    if is_background is True:
        summary["background_count"] += 1

    success = event.get("success")
    if success is True:
        summary["success_count"] += 1
    elif success is False:
        summary["failure_count"] += 1


def _atomic_write_json(path: Path, data: dict[str, Any]) -> None:
    import tempfile

    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=".tmp-", suffix=".json")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2)
        os.chmod(tmp, 0o600)
        os.replace(tmp, path)
    except Exception:
        try:
            os.unlink(tmp)
        except FileNotFoundError:
            pass
        raise


def main() -> int:
    if len(sys.argv) < 2:
        print("usage: sidecar_entry.py <runtime-dir>", file=sys.stderr)
        return 2

    runtime_dir = Path(sys.argv[1]).expanduser().resolve()
    events_dir = runtime_dir / "events"
    summary_path = runtime_dir / "summary.json"
    stop_sentinel = runtime_dir / "stop.sidecar"

    # Ensure the runtime directory exists; the supervisor creates it, but the
    # sidecar may start a tiny bit earlier in some process-scheduling cases.
    events_dir.mkdir(parents=True, exist_ok=True)

    summary = _summary_template()
    _atomic_write_json(summary_path, summary)

    seen: set[str] = set()
    running = True

    def _handle_signal(signum: int, frame: Any) -> None:  # noqa: ARG001
        nonlocal running
        running = False

    signal.signal(signal.SIGTERM, _handle_signal)
    signal.signal(signal.SIGINT, _handle_signal)

    while running:
        if stop_sentinel.exists():
            running = False

        # Parent gone -> orphan; stop cleanly.
        if os.getppid() == 1:
            running = False

        current = set(p.name for p in events_dir.glob("*.json"))
        new = current - seen
        for name in sorted(new):
            path = events_dir / name
            try:
                with open(path, "r", encoding="utf-8") as f:
                    event = json.load(f)
            except (json.JSONDecodeError, OSError):
                event = {}
            if isinstance(event, dict):
                _update_summary(summary, event)
            seen.add(name)

        if new:
            _atomic_write_json(summary_path, summary)

        time.sleep(POLL_INTERVAL)

    _atomic_write_json(summary_path, summary)
    return 0


if __name__ == "__main__":
    sys.exit(main())
