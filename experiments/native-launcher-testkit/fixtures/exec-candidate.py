#!/usr/bin/env python3
"""Negative-control candidate that execs fake-devin in the supervisor process.

This intentionally violates the shared contract by reusing the supervisor PID
as the child PID. The runner must reject it because supervisor, sidecar, and
child are no longer pairwise distinct.
"""

import argparse
import json
import os
import subprocess
import sys
from pathlib import Path

HOOK_SCRIPT = """import os, sys, pathlib, json, tempfile
events_dir = os.environ.get("GOAL_DEVIN_EVENTS_DIR")
if events_dir:
    pathlib.Path(events_dir).mkdir(parents=True, exist_ok=True)
    # Write a harmless event so the sidecar has something to consume if the
    # contract ever got that far (it should not).
    event = {
        "schema_version": 1,
        "event": "PostToolUse",
        "tool_name": "run_subagent",
        "profile": "exec-worker",
        "is_background": False,
        "success": True,
        "observed_at": "2024-01-01T00:00:00+00:00",
    }
    pathlib.Path(events_dir).mkdir(parents=True, exist_ok=True)
    pathlib.Path(tempfile.mkstemp(dir=events_dir, suffix=".json")[1]).write_text(
        json.dumps(event), encoding="utf-8"
    )
sys.exit(0)
"""

PROFILE_TEMPLATE = """---
name: {profile_id}
description: Goal Devin read-only worker for the native integration trial
model: {model}
allowed-tools:
  - read
  - grep
  - glob
permissions:
  deny:
    - write
    - edit
---

<!-- goal-devin-generated: true -->
"""


def main() -> None:
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
    run_id = os.urandom(16).hex()
    run_dir = runtime_root / run_id
    run_dir.mkdir(parents=True, exist_ok=True)

    devin_bin = str(Path(args.devin_bin).resolve())
    canary = Path(args.canary).resolve() if args.canary else runtime_root / "canary"
    canary.mkdir(parents=True, exist_ok=True)
    devin_dir = canary / ".devin"
    devin_dir.mkdir(parents=True, exist_ok=True)
    agents_dir = devin_dir / "agents"
    agents_dir.mkdir(parents=True, exist_ok=True)

    # Install a harmless hook script.
    hook_path = run_dir / "hook"
    hook_path.write_text(HOOK_SCRIPT, encoding="utf-8")
    os.chmod(hook_path, 0o700)
    events_dir = run_dir / "events"
    events_dir.mkdir(parents=True, exist_ok=True)
    os.chmod(events_dir, 0o700)

    # Generate a worker profile so fake-devin can verify it.
    profile_id = f"goal-devin-worker-exec-{os.getpid()}"
    profile_dir = agents_dir / profile_id
    profile_dir.mkdir(parents=True, exist_ok=True)
    os.chmod(profile_dir, 0o700)
    profile_path = profile_dir / "AGENT.md"
    profile_path.write_text(
        PROFILE_TEMPLATE.format(profile_id=profile_id, model=args.model),
        encoding="utf-8",
    )
    os.chmod(profile_path, 0o600)

    # Write the project-local hooks file that fake-devin will read.
    command = f"python3 {hook_path}"
    hooks_config = {
        "PreToolUse": [
            {"matcher": "", "hooks": [{"type": "command", "command": command, "timeout": 5}]}
        ],
        "PostToolUse": [
            {"matcher": "", "hooks": [{"type": "command", "command": command, "timeout": 5}]}
        ],
    }
    hooks_file = devin_dir / "hooks.v1.json"
    hooks_file.write_text(json.dumps(hooks_config, indent=2), encoding="utf-8")
    os.chmod(hooks_file, 0o600)

    # Spawn a fake sidecar and record its PID.
    sidecar = subprocess.Popen(
        [sys.executable, "-c", "import time; time.sleep(30)"],
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    (run_dir / "supervisor.pid").write_text(str(os.getpid()), encoding="utf-8")
    (run_dir / "sidecar.pid").write_text(str(sidecar.pid), encoding="utf-8")
    os.chmod(run_dir / "supervisor.pid", 0o600)
    os.chmod(run_dir / "sidecar.pid", 0o600)

    (run_dir / "lifecycle.log").write_text("supervisor_start\n", encoding="utf-8")

    env = os.environ.copy()
    env["GOAL_DEVIN_RUNTIME_DIR"] = str(run_dir)
    os.chdir(canary)
    os.execve(
        devin_bin,
        [devin_bin, "--model", args.model, "--permission-mode", args.permission_mode],
        env,
    )


if __name__ == "__main__":
    main()
