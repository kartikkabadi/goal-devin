#!/usr/bin/env python3
"""Deterministic fake Devin for the native-launcher testkit.

Mimics the surface the R1A Python launcher needs for black-box testing:
- --version / --help
- --model, --permission-mode, --sandbox, --export
- -p / --print mode
- Project hook file .devin/hooks.v1.json
- run_subagent simulation when the prompt mentions a generated profile
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

VERSION = "3000.1.27-fake"


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _usage() -> str:
    return (
        "fake-devin: deterministic stand-in for native-launcher tests\n"
        "Usage:\n"
        "  fake-devin --version\n"
        "  fake-devin --help\n"
        "  fake-devin -p [--model M] [--permission-mode P] [--sandbox] [--export PATH] -- <prompt>\n"
    )


def _session_id() -> str:
    return f"fake-{int(time.time() * 1000):x}"


def _run_hooks(hook_path: Path, event_name: str, payload: dict[str, object]) -> None:
    if not hook_path.exists():
        return
    try:
        config = json.loads(hook_path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return
    if not isinstance(config, dict):
        return
    entries = config.get(event_name, [])
    if not isinstance(entries, list):
        return
    for entry in entries:
        if not isinstance(entry, dict):
            continue
        for hook in entry.get("hooks", []):
            if not isinstance(hook, dict):
                continue
            command = hook.get("command")
            timeout = hook.get("timeout", 5)
            if not isinstance(command, str):
                continue
            try:
                subprocess.run(
                    command,
                    input=json.dumps(payload).encode("utf-8"),
                    shell=True,
                    timeout=timeout,
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    check=False,
                )
            except Exception:
                pass


def _extract_profile(workdir: Path) -> tuple[str | None, str | None]:
    """Find the first generated worker profile and return (profile_id, model)."""
    agents_dir = workdir / ".devin" / "agents"
    if not agents_dir.exists():
        return None, None
    for profile_dir in agents_dir.iterdir():
        if not profile_dir.is_dir():
            continue
        marker = profile_dir / "AGENT.md"
        if not marker.exists():
            continue
        text = marker.read_text(encoding="utf-8")
        if "goal-devin-generated" not in text:
            continue
        profile_id = profile_dir.name
        model: str | None = None
        in_frontmatter = False
        for line in text.splitlines():
            if line == "---":
                if in_frontmatter:
                    break
                in_frontmatter = True
                continue
            if in_frontmatter and line.startswith("model:"):
                model = line.split(":", 1)[1].strip()
        return profile_id, model
    return None, None


def _export_atif(path: Path, session_id: str, model: str) -> None:
    atif = {
        "schema_version": "ATIF-v1.7",
        "session_id": session_id,
        "agent": {
            "name": "devin",
            "version": "3000.1.27-fake",
            "model_name": model,
        },
    }
    path.write_text(json.dumps(atif, indent=2) + "\n", encoding="utf-8")


def main() -> int:
    argv = sys.argv[:]
    if len(argv) < 2 or argv[1] in ("--help", "-h"):
        print(_usage())
        return 0
    if argv[1] in ("--version", "-v"):
        print(VERSION)
        return 0

    i = 1
    print_mode = False
    model = "glm-5.2"
    permission_mode = "accept-edits"
    sandbox = False
    export_path: Path | None = None
    while i < len(argv) and argv[i].startswith("-") and argv[i] not in ("-p", "--print", "--"):
        if argv[i] == "--model":
            model = argv[i + 1]
            i += 2
        elif argv[i] == "--permission-mode":
            permission_mode = argv[i + 1]
            i += 2
        elif argv[i] == "--sandbox":
            sandbox = True
            i += 1
        elif argv[i] == "--export":
            export_path = Path(argv[i + 1])
            i += 2
        else:
            print(f"unknown flag {argv[i]}", file=sys.stderr)
            return 1

    if i < len(argv) and argv[i] in ("-p", "--print"):
        print_mode = True
        i += 1

    if i < len(argv) and argv[i] == "--":
        prompt = " ".join(argv[i + 1 :])
        i = len(argv)
    elif i < len(argv):
        prompt = argv[i]
        i += 1
    else:
        prompt = ""

    if not print_mode and i < len(argv):
        # Non-print interactive mode ignores trailing prompt arguments.
        prompt = ""

    workdir = Path.cwd()
    sid = _session_id()

    hook_path = workdir / ".devin" / "hooks.v1.json"
    _run_hooks(hook_path, "SessionStart", {"session_id": sid})

    if os.environ.get("DEVIN_FAIL"):
        return 1

    profile_id, profile_model = _extract_profile(workdir)
    if profile_id:
        payload: dict[str, object] = {
            "tool_name": "run_subagent",
            "tool_input": {
                "title": "fake subagent task",
                "task": prompt,
                "profile": profile_id,
                "is_background": False,
            },
            "tool_response": {"success": True, "output": "done"},
        }
        _run_hooks(hook_path, "PostToolUse", payload)
    else:
        _run_hooks(
            hook_path,
            "PostToolUse",
            {
                "tool_name": "read",
                "tool_input": {"file_path": "fake.txt"},
                "tool_response": {"success": True, "output": ""},
            },
        )

    _run_hooks(hook_path, "SessionEnd", {"session_id": sid})

    if export_path:
        _export_atif(export_path, sid, model)

    print(
        f"[fake-devin] session {sid}: model={model} permission={permission_mode} sandbox={sandbox}"
    )
    return int(os.environ.get("DEVIN_EXIT_CODE", "0"))


if __name__ == "__main__":
    sys.exit(main())
