#!/usr/bin/env python3
"""Read-only sidecar that observes atomically renamed event files."""

import json
import os
import signal
import sys
import time
from pathlib import Path

from .schema import validate_file
from .utils import atomic_write

POLL_INTERVAL = 0.05


class Sidecar:
    def __init__(self, runtime_dir: Path) -> None:
        self.runtime_dir = Path(runtime_dir)
        self.events_dir = self.runtime_dir / "events"
        self.summary_path = self.runtime_dir / "summary.json"
        self.schema_path = self.runtime_dir / "event.schema.json"
        self.consumed: set[str] = set()
        self.tools: dict[str, int] = {}
        self.profiles: dict[str, int] = {}
        self.last_event: dict | None = None
        self.running = True

    def _validate_event(self, event: dict) -> bool:
        if not self.schema_path.exists():
            return True
        errors = validate_file(event, self.schema_path)
        if errors:
            print(f"sidecar: schema errors: {errors}", file=sys.stderr, flush=True)
            return False
        return True

    def _update_summary(self) -> None:
        summary = {
            "schema_version": 1,
            "run_id": self.runtime_dir.name,
            "total_events": len(self.consumed),
            "consumed_event_ids": sorted(self.consumed),
            "tools": self.tools,
            "profiles": self.profiles,
            "last_event": self.last_event,
        }
        atomic_write(self.summary_path, json.dumps(summary, indent=2))

    def _process_file(self, path: Path) -> None:
        if path.suffix != ".json":
            return
        event_id = path.stem
        if event_id in self.consumed:
            return
        try:
            data = path.read_text(encoding="utf-8")
            event = json.loads(data)
        except (json.JSONDecodeError, OSError):
            return
        if not self._validate_event(event):
            return
        self.consumed.add(event_id)
        tool = event.get("tool_name")
        if tool:
            self.tools[tool] = self.tools.get(tool, 0) + 1
        profile = event.get("profile")
        if profile:
            self.profiles[profile] = self.profiles.get(profile, 0) + 1
        self.last_event = {
            "tool_name": tool,
            "profile": profile,
            "is_background": event.get("is_background"),
            "success": event.get("success"),
            "observed_at": event.get("observed_at"),
        }
        self._update_summary()

    def run(self) -> int:
        self.events_dir.mkdir(parents=True, exist_ok=True)
        self._update_summary()

        def _stop(signum, _frame):  # noqa: ANN001
            self.running = False

        signal.signal(signal.SIGTERM, _stop)
        signal.signal(signal.SIGINT, _stop)

        while self.running:
            try:
                for name in os.listdir(self.events_dir):
                    path = self.events_dir / name
                    if path.is_file():
                        self._process_file(path)
            except OSError:
                pass
            time.sleep(POLL_INTERVAL)

        self._update_summary()
        return 0


def main(argv: list[str] | None = None) -> int:
    argv = argv or sys.argv[1:]
    if len(argv) < 1:
        print("usage: sidecar.py <runtime-dir>", file=sys.stderr, flush=True)
        return 2
    runtime_dir = Path(argv[0])
    return Sidecar(runtime_dir).run()


if __name__ == "__main__":
    sys.exit(main())
