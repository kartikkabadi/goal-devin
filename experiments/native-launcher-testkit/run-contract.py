#!/usr/bin/env python3
"""Shared black-box acceptance contract for the native-launcher candidates."""

import argparse
import json
import os
import re
import shutil
import signal
import stat
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from typing import Any

import schema_validator

DEFAULT_MODEL = "swe-1-7"
DEFAULT_PERMISSION = "accept-edits"
LIFECYCLE_LABELS = [
    "supervisor_start",
    "sidecar_start",
    "child_start",
    "child_end",
    "sidecar_stop",
    "supervisor_end",
]
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
        "--contract-dir",
        default=None,
        help="Path to the shared testkit directory containing expected/*.schema.json.",
    )
    parser.add_argument(
        "--canary-fixture",
        default=None,
        help="Optional canary fixture directory to seed inside the runtime root.",
    )
    parser.add_argument(
        "--existing-hooks",
        default=None,
        help="Optional existing .devin/hooks.v1.json fixture to pre-seed and verify restoration.",
    )
    parser.add_argument(
        "--runtime-root",
        default=None,
        help="Directory for the private runtime directory.",
    )
    parser.add_argument(
        "--base-dir",
        default=None,
        help="Parent directory used to detect writes outside the runtime root.",
    )
    parser.add_argument("--tty", action="store_true", help="Run the candidate under a PTY.")
    parser.add_argument(
        "--process-overlap",
        action="store_true",
        help="Block the fake child until all three PIDs are observed alive.",
    )
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


def find_run_dir(runtime_root: Path, timeout: float = 10.0) -> Path | None:
    hex_chars = set("0123456789abcdef")
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        for entry in runtime_root.iterdir():
            name = entry.name
            if entry.is_dir() and len(name) == 32 and all(c in hex_chars for c in name.lower()):
                return entry
        time.sleep(0.01)
    return None


def _first_command(hooks_config: Any) -> str | None:
    if not isinstance(hooks_config, dict):
        return None
    for event_name, entries in hooks_config.items():
        if not isinstance(entries, list):
            continue
        for entry in entries:
            if not isinstance(entry, dict):
                continue
            for hook in entry.get("hooks", []):
                if isinstance(hook, dict):
                    cmd = hook.get("command")
                    if cmd:
                        return str(cmd)
    return None


def _is_process_alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except (OSError, ProcessLookupError):
        return False
    return True


def _collect_pids(proc_pid: int, run_dir: Path) -> list[int]:
    supervisor_pid_path = run_dir / "supervisor.pid"
    deadline = time.monotonic() + 5
    while not supervisor_pid_path.exists() and time.monotonic() < deadline:
        time.sleep(0.01)
    if not supervisor_pid_path.exists():
        raise RuntimeError("supervisor.pid missing")
    supervisor_pid = int(supervisor_pid_path.read_text(encoding="utf-8").strip().split()[0])
    if supervisor_pid != proc_pid:
        raise RuntimeError(
            f"supervisor.pid {supervisor_pid} does not match runner process {proc_pid}"
        )

    pids: list[int] = [supervisor_pid]
    for name in ("sidecar.pid", "child.pid"):
        pid_path = run_dir / name
        deadline = time.monotonic() + 5
        while not pid_path.exists() and time.monotonic() < deadline:
            time.sleep(0.01)
        if not pid_path.exists():
            raise RuntimeError(f"PID file missing: {name}")
        pids.append(int(pid_path.read_text(encoding="utf-8").strip().split()[0]))

    if len(set(pids)) != 3:
        raise RuntimeError(f"supervisor/sidecar/child PIDs are not pairwise distinct: {pids}")

    not_alive = [pid for pid in pids if not _is_process_alive(pid)]
    if not_alive:
        raise RuntimeError(f"Processes not alive during overlap: {not_alive}")
    return pids


def _prepare_isolated_env(runtime_root: Path, env: dict[str, str]) -> dict[str, str]:
    """Redirect common writable directories under the runtime root."""
    env = env.copy()
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    env["PYTHONPYCACHEPREFIX"] = str(runtime_root / "pycache")
    env["TMPDIR"] = str(runtime_root / "tmp")
    env["TEMP"] = str(runtime_root / "tmp")
    env["TMP"] = str(runtime_root / "tmp")
    env["HOME"] = str(runtime_root / "home")
    env["XDG_CACHE_HOME"] = str(runtime_root / "cache")
    env["XDG_CONFIG_HOME"] = str(runtime_root / "config")
    env["XDG_DATA_HOME"] = str(runtime_root / "data")
    for key in (
        "PYTHONPYCACHEPREFIX",
        "TMPDIR",
        "TEMP",
        "TMP",
        "HOME",
        "XDG_CACHE_HOME",
        "XDG_CONFIG_HOME",
        "XDG_DATA_HOME",
    ):
        Path(env[key]).mkdir(parents=True, exist_ok=True)
    return env


def run_candidate(
    args: argparse.Namespace, runtime_root: Path, canary: Path
) -> tuple[subprocess.Popen, int, Path | None, bytes, bytes]:
    contract_dir = Path(args.contract_dir).resolve() if args.contract_dir else Path(__file__).parent
    if not (contract_dir / "expected" / "event.schema.json").exists():
        raise RuntimeError(f"--contract-dir missing expected schemas: {contract_dir}")

    cmd = [
        args.candidate,
        "--model",
        args.model,
        "--permission-mode",
        args.permission_mode,
        "--devin-bin",
        args.devin_bin,
        "--contract-dir",
        str(contract_dir),
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
    env = _prepare_isolated_env(runtime_root, env)

    if args.existing_hooks:
        existing = load_json(Path(args.existing_hooks))
        expected_cmd = _first_command(existing)
        if expected_cmd:
            env["GOAL_DEVIN_EXPECTED_EXISTING_HOOK_COMMAND"] = expected_cmd

    if args.process_overlap:
        env["GOAL_DEVIN_BARRIER"] = "1"

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
        run_dir: Path | None = None
        if args.process_overlap:
            raise RuntimeError("--tty and --process-overlap are not supported together")
        returncode = proc.wait()
        try:
            os.read(master, 4096)
        except OSError:
            pass
        os.close(master)
        return proc, returncode, run_dir, b"", b""

    proc = subprocess.Popen(
        cmd,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        env=env,
    )

    run_dir: Path | None = None
    try:
        if args.process_overlap:
            run_dir = find_run_dir(runtime_root, timeout=10)
            if run_dir is None:
                stdout, stderr = proc.communicate(timeout=5)
                raise RuntimeError(
                    f"No run directory appeared under {runtime_root}: {stderr.decode()}"
                )
            _collect_pids(proc.pid, run_dir)
            continue_path = run_dir / "continue"
            continue_path.write_text("go\n", encoding="utf-8")
            os.chmod(continue_path, 0o600)

        stdout, stderr = proc.communicate()
    except Exception:
        try:
            proc.kill()
            proc.wait(timeout=2)
        except Exception:
            pass
        for name in ("sidecar.pid", "child.pid"):
            if run_dir is not None:
                pid_path = run_dir / name
                if pid_path.exists():
                    try:
                        pid = int(pid_path.read_text(encoding="utf-8").strip().split()[0])
                        os.kill(pid, signal.SIGKILL)
                    except (OSError, ProcessLookupError, ValueError):
                        pass
        raise
    finally:
        if run_dir is not None:
            continue_path = run_dir / "continue"
            if continue_path.exists():
                continue_path.unlink()

    return proc, proc.returncode, run_dir, stdout, stderr


def _check_lifecycle(log_path: Path, errors: list[str]) -> None:
    if not log_path.exists():
        errors.append("lifecycle.log missing")
        return
    lines = [
        line.strip() for line in log_path.read_text(encoding="utf-8").splitlines() if line.strip()
    ]
    labels = [line.split()[0] for line in lines if line]
    for label in LIFECYCLE_LABELS:
        if label not in labels:
            errors.append(f"lifecycle.log missing {label}")
    for i in range(len(LIFECYCLE_LABELS) - 1):
        a = LIFECYCLE_LABELS[i]
        b = LIFECYCLE_LABELS[i + 1]
        if a in labels and b in labels:
            if labels.index(a) > labels.index(b):
                errors.append(f"lifecycle ordering violated: {a} after {b}")


def _no_outside_writes(base_dir: Path, runtime_root: Path, errors: list[str]) -> None:
    runtime_resolved = runtime_root.resolve()
    for path in base_dir.rglob("*"):
        if path.is_file() or path.is_dir():
            resolved = path.resolve()
            if not resolved.is_relative_to(runtime_resolved):
                errors.append(f"File or directory outside runtime root: {resolved}")


def _check_file_modes(run_dir: Path, errors: list[str]) -> None:
    check_directory_mode(run_dir, 0o700, "run_dir", errors)
    events_dir = run_dir / "events"
    check_directory_mode(events_dir, 0o700, "events_dir", errors)

    files_600 = [
        ("supervisor.pid", "supervisor.pid"),
        ("sidecar.pid", "sidecar.pid"),
        ("child.pid", "child.pid"),
        ("sidecar-ready", "sidecar-ready"),
        ("lifecycle.log", "lifecycle.log"),
        ("manifest.json", "manifest.json"),
        ("summary.json", "summary.json"),
        ("event.schema.json", "event.schema.json"),
        ("fake-devin.record.json", "fake-devin.record.json"),
    ]
    for name, label in files_600:
        path = run_dir / name
        if path.exists():
            check_file_mode(path, 0o600, label, errors)
        else:
            errors.append(f"Expected file missing: {label}")

    hook_path = run_dir / "hook"
    if hook_path.exists():
        check_file_mode(hook_path, 0o700, "hook executable", errors)
    else:
        errors.append("hook executable missing")

    for event_file in events_dir.glob("*.json"):
        check_file_mode(event_file, 0o600, f"event file {event_file.name}", errors)


def run_contract(args: argparse.Namespace) -> list[str]:
    errors: list[str] = []

    if args.runtime_root:
        runtime_root = Path(args.runtime_root).resolve()
        runtime_root.mkdir(parents=True, exist_ok=True)
    else:
        runtime_root = Path(tempfile.mkdtemp(prefix="goal-devin-contract-"))

    if args.base_dir:
        base_dir = Path(args.base_dir).resolve()
        base_dir.mkdir(parents=True, exist_ok=True)
        if not runtime_root.resolve().is_relative_to(base_dir):
            errors.append("--runtime-root must be inside --base-dir")
            if not args.keep_artifacts:
                shutil.rmtree(base_dir, ignore_errors=True)
            return errors
    else:
        base_dir = runtime_root

    canary = runtime_root / "canary"
    if args.canary_fixture:
        if canary.exists():
            shutil.rmtree(canary)
        shutil.copytree(args.canary_fixture, canary, symlinks=True)
    else:
        canary.mkdir(parents=True, exist_ok=True)

    existing_bytes: bytes | None = None
    if args.existing_hooks:
        hooks_file = canary / ".devin" / "hooks.v1.json"
        hooks_file.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(args.existing_hooks, hooks_file)
        existing_bytes = hooks_file.read_bytes()

    try:
        _proc, returncode, run_dir, _stdout, stderr = run_candidate(args, runtime_root, canary)
    except RuntimeError as exc:
        errors.append(str(exc))
        if not args.keep_artifacts:
            shutil.rmtree(base_dir, ignore_errors=True)
        return errors

    if returncode != 0:
        errors.append(f"Candidate exited with code {returncode}")
        if stderr:
            text = stderr.decode("utf-8", errors="replace").replace("\n", " ").strip()
            # Capture the tail so the actual exception message is visible.
            errors.append(f"stderr: ...{text[-500:]}")

    if run_dir is None:
        run_dir = find_run_dir(runtime_root)
    if run_dir is None:
        errors.append("No run directory found under runtime root")
        if not args.keep_artifacts:
            shutil.rmtree(base_dir, ignore_errors=True)
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
            shutil.rmtree(base_dir, ignore_errors=True)
        return errors

    manifest = load_json(manifest_path)
    summary = load_json(summary_path)
    record = load_json(record_path)

    contract_dir = Path(args.contract_dir).resolve() if args.contract_dir else Path(__file__).parent
    errors.extend(
        schema_validator.validate_file(manifest, contract_dir / "expected" / "manifest.schema.json")
    )
    errors.extend(
        schema_validator.validate_file(summary, contract_dir / "expected" / "summary.schema.json")
    )

    _check_file_modes(run_dir, errors)

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

    expected_argv = ["--model", args.model, "--permission-mode", args.permission_mode]
    if record.get("argv") != expected_argv:
        errors.append(f"fake-devin argv is not exactly {expected_argv}: {record.get('argv')}")

    profile_id = manifest.get("profile_id")
    if not profile_id:
        errors.append("manifest missing profile_id")
    elif record.get("profile_id") != profile_id:
        errors.append("fake-devin profile_id mismatch")

    if args.tty:
        tty = record.get("tty", {})
        if not tty.get("stdin"):
            errors.append("fake-devin did not observe a TTY stdin")
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
            errors.extend(
                schema_validator.validate_file(
                    event, contract_dir / "expected" / "event.schema.json"
                )
            )
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
        hooks_file = canary / ".devin" / "hooks.v1.json"
        if not hooks_file.exists():
            errors.append("Existing hook fixture was not restored")
        elif hooks_file.read_bytes() != existing_bytes:
            errors.append("Existing hook fixture bytes changed")
        else:
            original_mode = stat.S_IMODE(Path(args.existing_hooks).stat().st_mode)
            if stat.S_IMODE(hooks_file.stat().st_mode) != original_mode:
                errors.append("Existing hook fixture mode was not preserved")

    _check_lifecycle(run_dir / "lifecycle.log", errors)
    _no_outside_writes(base_dir, runtime_root, errors)

    secret_hits = secret_scan(run_dir, redact=runtime_root) + secret_scan(
        canary, redact=runtime_root
    )
    if secret_hits:
        for hit in secret_hits[:10]:
            errors.append(f"Secret-like pattern: {hit}")

    if not args.keep_artifacts:
        shutil.rmtree(base_dir, ignore_errors=True)

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
