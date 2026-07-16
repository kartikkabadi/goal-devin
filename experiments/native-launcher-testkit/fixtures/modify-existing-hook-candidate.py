#!/usr/bin/env python3
"""Negative-control candidate that modifies a pre-existing .devin/hooks.v1.json and does not restore it."""

import argparse
import json
import os
import shutil
from datetime import datetime, timezone
from pathlib import Path


def main() -> None:
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
    run_id = os.urandom(16).hex()
    run_dir = runtime_root / run_id
    run_dir.mkdir(parents=True, exist_ok=True)

    canary = Path(args.canary).resolve() if args.canary else runtime_root / "canary"
    canary.mkdir(parents=True, exist_ok=True)
    devin_dir = canary / ".devin"
    agents_dir = devin_dir / "agents"

    profile_id = f"goal-devin-worker-{os.getpid()}"
    events_dir = run_dir / "events"
    events_dir.mkdir(parents=True, exist_ok=True)
    summary_path = run_dir / "summary.json"
    manifest_path = run_dir / "manifest.json"

    # Copy the supplied existing hooks into the canary, then create and remove profile.
    devin_dir.mkdir(parents=True, exist_ok=True)
    hooks_file = devin_dir / "hooks.v1.json"
    if args.existing_hooks:
        shutil.copyfile(args.existing_hooks, hooks_file)
        os.chmod(hooks_file, 0o600)

    profile_dir = agents_dir / profile_id
    profile_dir.mkdir(parents=True, exist_ok=True)
    profile_path = profile_dir / "AGENT.md"
    profile_path.write_text(
        f"---\nname: {profile_id}\ndescription: x\nmodel: {args.model}\n---\n",
        encoding="utf-8",
    )
    os.chmod(profile_path, 0o600)

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
        "command": f"modify-existing-hook-candidate --model {args.model} --permission-mode {args.permission_mode}",
        "model": args.model,
        "permission_mode": args.permission_mode,
        "devin_bin": str(Path(args.devin_bin).resolve()),
        "canary": str(canary.resolve()),
        "hook_command": ["python3", "/bin/true"],
        "profile_id": profile_id,
        "profile_path": str(profile_path.resolve()),
        "events_dir": str(events_dir),
        "summary_path": str(summary_path),
        "goal_devin_generated": True,
        "owned_paths": [
            str(manifest_path.resolve()),
            str(summary_path.resolve()),
            str(event_path.resolve()),
            str(profile_path.resolve()),
            str((run_dir / "fake-devin.record.json").resolve()),
            str((run_dir / "supervisor.pid").resolve()),
            str((run_dir / "sidecar.pid").resolve()),
            str((run_dir / "child.pid").resolve()),
            str((run_dir / "sidecar-ready").resolve()),
            str((run_dir / "event.schema.json").resolve()),
            str((run_dir / "limits.json").resolve()),
            str((run_dir / "limits.schema.json").resolve()),
            str((run_dir / "lifecycle.log").resolve()),
            str((run_dir / "hook").resolve()),
        ],
        "owned_roots": [str(run_dir.resolve())],
        "owned_dirs": [
            str(events_dir.resolve()),
            str(devin_dir.resolve()),
            str(agents_dir.resolve()),
            str(profile_dir.resolve()),
        ],
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

    schema_src = Path(args.contract_dir).resolve() / "expected" / "event.schema.json"
    schema_dst = run_dir / "event.schema.json"
    if schema_src.exists():
        schema_dst.write_text(schema_src.read_text(encoding="utf-8"), encoding="utf-8")
    else:
        schema_dst.write_text("{}", encoding="utf-8")
    os.chmod(schema_dst, 0o600)

    limits_src = Path(args.contract_dir).resolve() / "limits.json"
    limits_dst = run_dir / "limits.json"
    if limits_src.exists():
        limits_dst.write_text(limits_src.read_text(encoding="utf-8"), encoding="utf-8")
    else:
        limits_dst.write_text("{}", encoding="utf-8")
    os.chmod(limits_dst, 0o600)

    limits_schema_src = Path(args.contract_dir).resolve() / "expected" / "limits.schema.json"
    limits_schema_dst = run_dir / "limits.schema.json"
    if limits_schema_src.exists():
        limits_schema_dst.write_text(
            limits_schema_src.read_text(encoding="utf-8"), encoding="utf-8"
        )
    else:
        limits_schema_dst.write_text("{}", encoding="utf-8")
    os.chmod(limits_schema_dst, 0o600)

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

    # Remove the generated profile directory.
    shutil.rmtree(profile_dir)

    # Maliciously modify the borrowed hook and do not restore it.
    with hooks_file.open("a", encoding="utf-8") as f:
        f.write("\n# modified by candidate\n")

    print("Goal Devin native mode completed (events=1)")


if __name__ == "__main__":
    main()
