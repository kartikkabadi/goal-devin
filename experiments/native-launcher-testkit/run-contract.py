#!/usr/bin/env python3
"""Shared black-box acceptance contract for the native-launcher candidates."""

import argparse
import json
import os
import re
import shutil
import stat
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any

DEFAULT_MODEL = "swe-1-7"
DEFAULT_PERMISSION = "accept-edits"
SECRET_PATTERNS = [
    re.compile(r"\bapi[_-]?key\b", re.IGNORECASE),
    re.compile(r"\btoken\b", re.IGNORECASE),
    re.compile(r"\bsecret\b", re.IGNORECASE),
    re.compile(r"\bpassword\b", re.IGNORECASE),
    re.compile(r"\bcredential\b", re.IGNORECASE),
    re.compile(r"\bbearer\b", re.IGNORECASE),
]


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run the native launcher happy-path contract.")
    parser.add_argument("--candidate", required=True, help="Path to the candidate executable.")
    parser.add_argument("--devin-bin", required=True, help="Path to the fake-devin executable.")
    parser.add_argument("--model", default=DEFAULT_MODEL, help="Root model to request.")
    parser.add_argument(
        "--permission-mode", default=DEFAULT_PERMISSION, help="Permission mode to request."
    )
    parser.add_argument(
        "--canary-fixture",
        default=None,
        help="Optional canary fixture directory to seed inside the runtime root.",
    )
    parser.add_argument(
        "--existing-hooks",
        default=None,
        help="Optional existing .devin/hooks.json fixture to pre-seed and verify restoration.",
    )
    parser.add_argument(
        "--runtime-root",
        default=None,
        help="Optional parent directory for the private runtime directory.",
    )
    parser.add_argument("--tty", action="store_true", help="Run the candidate under a PTY.")
    parser.add_argument(
        "--keep-artifacts",
        action="store_true",
        help="Do not remove the runtime root after the run.",
    )
    return parser.parse_args(argv)


def load_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def secret_scan(root: Path, redact: Path | None = None) -> list[str]:
    hits = []
    redact_text = str(redact.resolve()) if redact else ""
    for path in root.rglob("*"):
        if path.is_file() and path.stat().st_size < 1024 * 1024:
            try:
                text = path.read_text(encoding="utf-8")
            except (UnicodeDecodeError, OSError):
                continue
            if redact_text:
                text = text.replace(redact_text, "REDACTED_PATH")
            for pattern in SECRET_PATTERNS:
                if pattern.search(text):
                    hits.append(f"{path.relative_to(root)} matched {pattern.pattern}")
    return hits


def check_directory_mode(path: Path, expected: int, label: str, errors: list[str]) -> None:
    mode = stat.S_IMODE(path.stat().st_mode)
    if mode != expected:
        errors.append(f"{label} mode is {oct(mode)}, expected {oct(expected)}")


def check_file_mode(path: Path, expected: int, label: str, errors: list[str]) -> None:
    mode = stat.S_IMODE(path.stat().st_mode)
    if mode != expected:
        errors.append(f"{label} mode is {oct(mode)}, expected {oct(expected)}")


def find_run_dir(runtime_root: Path) -> Path | None:
    hex_chars = set("0123456789abcdef")
    for entry in runtime_root.iterdir():
        name = entry.name
        if entry.is_dir() and len(name) == 32 and all(c in hex_chars for c in name.lower()):
            return entry
    return None


def run_candidate(
    args: argparse.Namespace, runtime_root: Path, canary: Path
) -> tuple[subprocess.Popen, int]:
    cmd = [
        args.candidate,
        "--model",
        args.model,
        "--permission-mode",
        args.permission_mode,
        "--devin-bin",
        args.devin_bin,
        "--runtime-root",
        str(runtime_root),
        "--canary",
        str(canary),
        "--keep-canary",
    ]
    if args.existing_hooks:
        cmd.extend(["--existing-hooks", args.existing_hooks])
    env = os.environ.copy()
    env["GOAL_DEVIN_FAKE_EXIT_CODE"] = "0"
    env["GOAL_DEVIN_FAKE_SLEEP"] = "0.1"

    if args.tty:
        import pty

        master, slave = pty.openpty()
        proc = subprocess.Popen(
            cmd,
            stdin=slave,
            stdout=slave,
            stderr=slave,
            env=env,
            close_fds=True,
        )
        os.close(slave)
        returncode = proc.wait()
        try:
            os.read(master, 4096)
        except OSError:
            pass
        os.close(master)
        return proc, returncode

    proc = subprocess.Popen(
        cmd,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        env=env,
    )
    stdout, stderr = proc.communicate()
    return proc, proc.returncode


def run_contract(args: argparse.Namespace) -> list[str]:
    errors: list[str] = []

    if args.runtime_root:
        runtime_root = Path(args.runtime_root).resolve()
        runtime_root.mkdir(parents=True, exist_ok=True)
    else:
        runtime_root = Path(tempfile.mkdtemp(prefix="goal-devin-contract-"))

    canary = runtime_root / "canary"
    if args.canary_fixture:
        shutil.copytree(args.canary_fixture, canary)
    else:
        canary.mkdir(parents=True, exist_ok=True)

    existing_bytes: bytes | None = None
    if args.existing_hooks:
        hooks_file = canary / ".devin" / "hooks.json"
        hooks_file.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(args.existing_hooks, hooks_file)
        existing_bytes = hooks_file.read_bytes()

    proc, returncode = run_candidate(args, runtime_root, canary)

    if returncode != 0:
        errors.append(f"Candidate exited with code {returncode}")
        try:
            stderr = proc.stderr.read() if proc.stderr else b""
            if stderr:
                errors.append(f"stderr: {stderr.decode('utf-8', errors='replace')[:500]}")
        except Exception:
            pass

    run_dir = find_run_dir(runtime_root)
    if run_dir is None:
        errors.append("No run directory found under runtime root")
        if not args.keep_artifacts:
            shutil.rmtree(runtime_root, ignore_errors=True)
        return errors

    manifest_path = run_dir / "manifest.json"
    summary_path = run_dir / "summary.json"
    record_path = run_dir / "fake-devin.record.json"
    events_dir = run_dir / "events"

    if not manifest_path.exists():
        errors.append("manifest.json missing")
    if not summary_path.exists():
        errors.append("summary.json missing")
    if not record_path.exists():
        errors.append("fake-devin.record.json missing")
    if not events_dir.is_dir():
        errors.append("events/ directory missing")

    if errors:
        if not args.keep_artifacts:
            shutil.rmtree(runtime_root, ignore_errors=True)
        return errors

    manifest = load_json(manifest_path)
    summary = load_json(summary_path)
    record = load_json(record_path)

    check_directory_mode(run_dir, 0o700, "run_dir", errors)
    check_directory_mode(events_dir, 0o700, "events_dir", errors)
    check_file_mode(manifest_path, 0o600, "manifest.json", errors)
    check_file_mode(summary_path, 0o600, "summary.json", errors)

    if manifest.get("model") != args.model:
        errors.append(f"manifest model mismatch: {manifest.get('model')}")
    if manifest.get("permission_mode") != args.permission_mode:
        errors.append(f"manifest permission_mode mismatch: {manifest.get('permission_mode')}")
    if manifest.get("devin_bin") != str(Path(args.devin_bin).resolve()):
        errors.append("manifest devin_bin mismatch")

    if record.get("model") != args.model:
        errors.append(f"fake-devin saw model {record.get('model')}")
    if record.get("permission_mode") != args.permission_mode:
        errors.append(f"fake-devin saw permission_mode {record.get('permission_mode')}")
    if record.get("cwd") != str(canary.resolve()):
        errors.append(f"fake-devin cwd mismatch: {record.get('cwd')}")
    if "--model" not in record.get("argv", []):
        errors.append("fake-devin argv missing --model")
    if "--permission-mode" not in record.get("argv", []):
        errors.append("fake-devin argv missing --permission-mode")

    profile_id = manifest.get("profile_id")
    if not profile_id:
        errors.append("manifest missing profile_id")
    elif record.get("profile_id") != profile_id:
        errors.append("fake-devin profile_id mismatch")

    if args.tty:
        tty = record.get("tty", {})
        if not tty.get("stdout"):
            errors.append("fake-devin did not observe a TTY stdout")
        if not tty.get("stderr"):
            errors.append("fake-devin did not observe a TTY stderr")

    event_files = [p for p in events_dir.iterdir() if p.suffix == ".json"]
    tmp_files = [p for p in events_dir.iterdir() if p.suffix == ".tmp"]
    if not event_files:
        errors.append("No event .json files published")
    if tmp_files:
        errors.append(f"Temporary event files remain: {tmp_files}")
    if event_files:
        try:
            event = load_json(event_files[0])
            if event.get("tool_name") != "run_subagent":
                errors.append("event tool_name is not run_subagent")
            if event.get("profile") != profile_id:
                errors.append("event profile does not match manifest")
        except json.JSONDecodeError as exc:
            errors.append(f"event file is not valid JSON: {exc}")

    if summary.get("total_events", 0) < 1:
        errors.append("summary reports no consumed events")
    if summary.get("last_event", {}).get("profile") != profile_id:
        errors.append("summary last_event profile mismatch")

    profile_dir = canary / ".devin" / "agents" / profile_id
    if profile_dir.exists():
        errors.append("Generated profile directory was not removed")

    if existing_bytes is not None:
        hooks_file = canary / ".devin" / "hooks.json"
        if not hooks_file.exists():
            errors.append("Existing hook fixture was not restored")
        elif hooks_file.read_bytes() != existing_bytes:
            errors.append("Existing hook fixture bytes changed")

    secret_hits = secret_scan(run_dir, redact=runtime_root) + secret_scan(
        canary, redact=runtime_root
    )
    if secret_hits:
        for hit in secret_hits[:10]:
            errors.append(f"Secret-like pattern: {hit}")

    if not args.keep_artifacts:
        shutil.rmtree(runtime_root, ignore_errors=True)

    return errors


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    errors = run_contract(args)
    if errors:
        print("CONTRACT FAILED", file=sys.stderr)
        for err in errors:
            print(f"  - {err}", file=sys.stderr)
        return 1
    print("CONTRACT PASSED")
    return 0


if __name__ == "__main__":
    sys.exit(main())
