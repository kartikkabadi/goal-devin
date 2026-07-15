#!/usr/bin/env python3
"""Negative-control candidate that writes a file outside the runtime root.

The runner must reject this because the file sits under the test-owned base
but not under the runtime root/canary allowlist.
"""

import argparse
import json
import os
from datetime import datetime, timezone
from pathlib import Path


def main() -> None:
    # Restrict default permissions so created artifacts look like the real candidate.
    os.umask(0o077)
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

    runtime_root = Path(args.runtime_root).resolve()
    base_dir = runtime_root.parent
    run_id = os.urandom(16).hex()
    run_dir = runtime_root / run_id
    run_dir.mkdir(parents=True, exist_ok=True)

    canary = Path(args.canary).resolve() if args.canary else runtime_root / "canary"
    canary.mkdir(parents=True, exist_ok=True)

    profile_id = f"goal-devin-worker-{os.getpid()}"
    events_dir = run_dir / "events"
    events_dir.mkdir(parents=True, exist_ok=True)
    summary_path = run_dir / "summary.json"
    manifest_path = run_dir / "manifest.json"

    observed = datetime.now(timezone.utc).isoformat()
    event = {
        "schema_version": 1,
        "event": "PostToolUse",
        "tool_name": "run_subagent",
        "profile": profile_id,
        "is_background": False,
        "success": True,
        "observed_at": observed,
    }
    event_path = events_dir / f"{os.urandom(16).hex()}.json"
    event_path.write_text(json.dumps(event, indent=2), encoding="utf-8")
    os.chmod(event_path, 0o600)

    summary = {
        "schema_version": 1,
        "run_id": run_id,
        "total_events": 1,
        "consumed_event_ids": [event_path.stem],
        "tools": {"run_subagent": 1},
        "profiles": {profile_id: 1},
        "last_event": {
            "tool_name": "run_subagent",
            "profile": profile_id,
            "is_background": False,
            "success": True,
            "observed_at": observed,
        },
    }
    summary_path.write_text(json.dumps(summary, indent=2), encoding="utf-8")
    os.chmod(summary_path, 0o600)

    manifest = {
        "schema_version": 1,
        "run_id": run_id,
        "created_at": observed,
        "command": f"outside-write-candidate --model {args.model} --permission-mode {args.permission_mode}",
        "model": args.model,
        "permission_mode": args.permission_mode,
        "devin_bin": str(Path(args.devin_bin).resolve()),
        "canary": str(canary.resolve()),
        "hook_command": ["python3", "/bin/true"],
        "profile_id": profile_id,
        "profile_path": str(canary / ".devin" / "agents" / profile_id / "AGENT.md"),
        "events_dir": str(events_dir),
        "summary_path": str(summary_path),
        "goal_devin_generated": True,
    }
    manifest_path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    os.chmod(manifest_path, 0o600)

    record = {
        "argv": ["--model", args.model, "--permission-mode", args.permission_mode],
        "cwd": str(canary.resolve()),
        "tty": {"stdin": False, "stdout": False, "stderr": False},
        "model": args.model,
        "permission_mode": args.permission_mode,
        "profile_id": profile_id,
        "hook_command": ["python3", "/bin/true"],
        "hook_returncode": 0,
        "sidecar_total_events": 1,
        "exit_code": 0,
        "timestamp": observed,
    }
    (run_dir / "fake-devin.record.json").write_text(json.dumps(record, indent=2), encoding="utf-8")
    os.chmod(run_dir / "fake-devin.record.json", 0o600)

    # Copy the authoritative event schema so the sidecar checks pass if reached.
    schema_src = Path(args.contract_dir).resolve() / "expected" / "event.schema.json"
    schema_dst = run_dir / "event.schema.json"
    schema_dst.write_text(schema_src.read_text(encoding="utf-8"), encoding="utf-8")
    os.chmod(schema_dst, 0o600)

    # PID files and lifecycle log.
    for name in ("supervisor.pid", "sidecar.pid", "child.pid"):
        (run_dir / name).write_text(str(os.getpid()), encoding="utf-8")
        os.chmod(run_dir / name, 0o600)
    (run_dir / "sidecar-ready").write_text("ready\n", encoding="utf-8")
    os.chmod(run_dir / "sidecar-ready", 0o600)
    lifecycle = (
        "supervisor_start\nsidecar_start\nchild_start\nchild_end\nsidecar_stop\nsupervisor_end\n"
    )
    (run_dir / "lifecycle.log").write_text(lifecycle, encoding="utf-8")
    os.chmod(run_dir / "lifecycle.log", 0o600)

    hook = run_dir / "hook"
    hook.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
    os.chmod(hook, 0o700)

    # The malicious write: a sibling file under the test-owned base.
    outside = base_dir / "outside.txt"
    outside.write_text("I should not be here", encoding="utf-8")

    print("Goal Devin native mode completed (events=1)")


if __name__ == "__main__":
    main()
