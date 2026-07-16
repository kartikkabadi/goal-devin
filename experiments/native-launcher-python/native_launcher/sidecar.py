#!/usr/bin/env python3
"""Read-only sidecar that observes atomically renamed event files.

The sidecar enforces the runtime limits defined in ``limits.json`` so the
spool directory and in-memory summary stay bounded.
"""

import datetime
import json
import os
import signal
import stat
import sys
import time
from pathlib import Path
from typing import Any

from .limits import Limits, load_limits
from .schema import validate_file
from .utils import atomic_write

POLL_INTERVAL = 0.05


def _lifecycle_log(path: Path | None, label: str) -> None:
    if path is None:
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    now = datetime.datetime.now(datetime.timezone.utc).isoformat()
    with open(path, "a", encoding="utf-8") as fh:
        fh.write(f"{label} {now}\n")
        fh.flush()
        os.fsync(fh.fileno())


def _validate_event_json_size(data: bytes, limits: Limits) -> bool:
    if len(data) > limits.max_event_json_bytes:
        print("sidecar: event file exceeds max size; dropping", file=sys.stderr, flush=True)
        return False
    return True


class Sidecar:
    def __init__(self, runtime_dir: Path) -> None:
        self.runtime_dir = Path(runtime_dir)
        self.events_dir = self.runtime_dir / "events"
        self.summary_path = self.runtime_dir / "summary.json"
        self.schema_path = self.runtime_dir / "event.schema.json"
        limits_path = self.runtime_dir / "limits.json"
        limits_schema_path = self.runtime_dir / "limits.schema.json"
        self.limits = load_limits(limits_path, limits_schema_path, required=True)
        lifecycle_path = os.environ.get("GOAL_DEVIN_LIFECYCLE_LOG")
        self.lifecycle_path = Path(lifecycle_path) if lifecycle_path else None
        self.consumed: set[str] = set()
        self.consumed_order: list[str] = []
        self.total_events: int = 0
        self.tools: dict[str, int] = {}
        self.profiles: dict[str, int] = {}
        self.last_event: dict | None = None
        self.running = True

    def _validate_event(self, event: dict) -> bool:
        if not self.schema_path.exists():
            print("sidecar: event schema missing; rejecting event", file=sys.stderr, flush=True)
            return False
        try:
            errors = validate_file(event, self.schema_path)
        except (OSError, json.JSONDecodeError) as exc:
            print(f"sidecar: schema invalid; rejecting event: {exc}", file=sys.stderr, flush=True)
            return False
        if errors:
            print(f"sidecar: schema errors: {errors}", file=sys.stderr, flush=True)
            return False
        return True

    def _check_field_lengths(self, event: Any) -> bool:
        if not isinstance(event, dict):
            print("sidecar: event is not a JSON object; rejecting", file=sys.stderr, flush=True)
            return False
        limits = self.limits
        for key in ("event", "tool_name", "profile", "observed_at"):
            value = event.get(key)
            if isinstance(value, str) and len(value) > limits.max_event_value_length:
                print(
                    f"sidecar: event {key} exceeds max length; dropping",
                    file=sys.stderr,
                    flush=True,
                )
                return False
        if (
            isinstance(event.get("tool_name"), str)
            and len(event["tool_name"]) > limits.max_tool_name_length
        ):
            return False
        if (
            isinstance(event.get("profile"), str)
            and len(event["profile"]) > limits.max_profile_length
        ):
            return False
        return True

    def _update_summary(self) -> None:
        limits = self.limits
        recent_ids = self.consumed_order[-limits.max_recent_event_ids :]
        summary: dict[str, Any] = {
            "schema_version": 1,
            "run_id": self.runtime_dir.name,
            "total_events": self.total_events,
            "consumed_event_ids": recent_ids,
            "tools": self.tools,
            "profiles": self.profiles,
            "last_event": self.last_event,
        }

        # Iteratively trim bounded fields until the serialized summary fits inside
        # max_summary_size_bytes.  The limits file is required to allow a minimal
        # summary, but this loop is the final fail-open guard against any path.
        def _serialize() -> str:
            return json.dumps(summary, indent=2)

        def _size(text: str) -> int:
            return len(text.encode("utf-8"))

        text = _serialize()
        if _size(text) > limits.max_summary_size_bytes:
            summary["consumed_event_ids"] = []
            text = _serialize()
        if _size(text) > limits.max_summary_size_bytes:
            summary["tools"] = {}
            text = _serialize()
        if _size(text) > limits.max_summary_size_bytes:
            summary["profiles"] = {}
            text = _serialize()
        if _size(text) > limits.max_summary_size_bytes:
            summary["last_event"] = None
            text = _serialize()
        if _size(text) > limits.max_summary_size_bytes:
            # Fallback to compact JSON for the smallest possible valid shape.
            text = json.dumps(summary, separators=(",", ":"))
            if _size(text) > limits.max_summary_size_bytes:
                raise RuntimeError(
                    f"summary cannot fit within max_summary_size_bytes "
                    f"({limits.max_summary_size_bytes})"
                )
        atomic_write(self.summary_path, text)

    def _add_tool(self, tool: str | None) -> None:
        if not isinstance(tool, str):
            return
        if tool == "run_subagent":
            if tool not in self.tools and len(self.tools) >= self.limits.max_distinct_tools:
                # Reserve a slot for the canonical run_subagent observation.
                for existing in list(self.tools.keys()):
                    if existing != "run_subagent":
                        del self.tools[existing]
                        break
        elif tool not in self.tools and len(self.tools) >= self.limits.max_distinct_tools:
            # Already at the distinct-tool limit; drop new tools fail-open.
            return
        self.tools[tool] = self.tools.get(tool, 0) + 1

    def _add_profile(self, profile: str | None) -> None:
        if not isinstance(profile, str):
            return
        if profile not in self.profiles and len(self.profiles) >= self.limits.max_distinct_profiles:
            return
        self.profiles[profile] = self.profiles.get(profile, 0) + 1

    def _reject_file(self, path: Path, event_id: str, reason: str) -> None:
        """Mark a spool file as terminally rejected and remove it if possible.

        Files that cannot be deleted are left in the spool but tracked in
        ``consumed`` so they are not reprocessed forever.  The trimmer will
        count them toward the total byte bound and remove them if necessary.
        """
        print(f"sidecar: rejecting {path.name}: {reason}", file=sys.stderr, flush=True)
        self.consumed.add(event_id)
        try:
            path.unlink()
            self.consumed.discard(event_id)
        except OSError:
            pass

    def _process_file(self, path: Path) -> None:
        if path.suffix != ".json":
            return
        event_id = path.stem
        if event_id in self.consumed:
            return
        try:
            data = path.read_bytes()
        except OSError as exc:
            self._reject_file(path, event_id, f"cannot read file: {exc}")
            return

        if not _validate_event_json_size(data, self.limits):
            self._reject_file(path, event_id, "exceeds max event JSON size")
            return

        try:
            text = data.decode("utf-8")
            event = json.loads(text)
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            self._reject_file(path, event_id, f"not valid UTF-8 JSON: {exc}")
            return
        except ValueError as exc:
            self._reject_file(path, event_id, f"JSON parse error: {exc}")
            return

        if not self._check_field_lengths(event):
            self._reject_file(path, event_id, "field length limit exceeded")
            return
        if not self._validate_event(event):
            self._reject_file(path, event_id, "schema validation failed")
            return

        self.consumed.add(event_id)
        self.consumed_order.append(event_id)
        self.total_events += 1
        tool = event.get("tool_name")
        profile = event.get("profile")
        self._add_tool(tool)
        if tool == "run_subagent" and isinstance(profile, str):
            if (
                profile not in self.profiles
                and len(self.profiles) >= self.limits.max_distinct_profiles
            ):
                # Reserve a slot for the worker profile observed through run_subagent.
                for existing in list(self.profiles.keys()):
                    if existing != profile:
                        del self.profiles[existing]
                        break
        self._add_profile(profile)
        self.last_event = {
            "tool_name": tool,
            "profile": profile,
            "is_background": event.get("is_background"),
            "success": event.get("success"),
            "observed_at": event.get("observed_at"),
        }
        self._update_summary()

    def _trim_spool(self) -> None:
        """Remove oldest consumed event files to keep count and size bounded."""
        limits = self.limits
        try:
            paths = list(self.events_dir.iterdir())
        except OSError:
            return

        entries: list[tuple[Path, int, float]] = []
        for p in paths:
            if p.suffix != ".json":
                continue
            try:
                st = p.lstat()
                if not stat.S_ISREG(st.st_mode):
                    continue
                entries.append((p, st.st_size, st.st_mtime))
            except OSError:
                continue

        if not entries:
            return

        entries.sort(key=lambda x: x[2])
        total = sum(size for _, size, _ in entries)
        while (
            len(entries) > limits.max_retained_event_files or total > limits.max_total_spool_bytes
        ):
            removed = False
            for i, (p, size, _) in enumerate(entries):
                if p.stem in self.consumed and p.exists():
                    try:
                        p.unlink()
                        self.consumed.discard(p.stem)
                        # Also discard from the ordered recent list, but keep
                        # total_events as an accurate observed count.
                        if p.stem in self.consumed_order:
                            self.consumed_order.remove(p.stem)
                        total -= size
                        entries.pop(i)
                        removed = True
                        break
                    except OSError:
                        pass
            if not removed:
                break

    def _drain(self) -> None:
        try:
            for name in os.listdir(self.events_dir):
                path = self.events_dir / name
                if path.is_file():
                    self._process_file(path)
        except OSError:
            pass
        self._trim_spool()

    def _write_pid(self) -> None:
        pid_path = self.runtime_dir / "sidecar.pid"
        try:
            with open(pid_path, "w", encoding="utf-8") as fh:
                fh.write(f"{os.getpid()}\n")
                fh.flush()
                os.fsync(fh.fileno())
            os.chmod(pid_path, 0o600)
        except OSError:
            pass

    def _signal_ready(self) -> None:
        ready_path = self.runtime_dir / "sidecar-ready"
        try:
            with open(ready_path, "w", encoding="utf-8") as fh:
                fh.write("ready\n")
                fh.flush()
                os.fsync(fh.fileno())
            os.chmod(ready_path, 0o600)
        except OSError:
            pass

    def run(self) -> int:
        self.events_dir.mkdir(parents=True, exist_ok=True)
        self._update_summary()
        self._write_pid()
        _lifecycle_log(self.lifecycle_path, "sidecar_start")
        self._signal_ready()

        def _stop(signum, _frame):  # noqa: ANN001
            self.running = False

        signal.signal(signal.SIGTERM, _stop)
        signal.signal(signal.SIGINT, _stop)

        while self.running:
            self._drain()
            time.sleep(POLL_INTERVAL)

        self._drain()
        self._update_summary()
        _lifecycle_log(self.lifecycle_path, "sidecar_stop")
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
