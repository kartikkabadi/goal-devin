#!/usr/bin/env python3
"""Shared black-box acceptance contract for the native-launcher candidates."""

import argparse
import hashlib
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

MANAGED_BASE_MARKER = "GOAL_DEVIN_CONTRACT_BASE"


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
        help="Path to the shared testkit directory containing expected/*.schema.json and limits.json.",
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
        "--no-poll",
        action="store_true",
        help="Instruct fake-devin to exit immediately after invoking the hook.",
    )
    parser.add_argument(
        "--stress",
        action="store_true",
        help="Run the fake-devin stress mode and enforce spool/summary bounds.",
    )
    parser.add_argument(
        "--timeout",
        type=float,
        default=30.0,
        help="Overall runner timeout in seconds (default: 30).",
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
    for path in _walk_no_follow(root):
        if path.is_file() and path.stat().st_size < 1024 * 1024:
            try:
                text = path.read_text(encoding="utf-8")
            except (UnicodeDecodeError, OSError):
                continue
            if redact_text:
                text = text.replace(redact_text, "REDACTED_PATH")
            for pattern in SECRET_PATTERNS:
                if pattern.search(text):
                    try:
                        rel = path.relative_to(root)
                    except ValueError:
                        rel = path
                    hits.append(f"{rel} matched {pattern.pattern}")
    return hits


def check_directory_mode(path: Path, expected: int, label: str, errors: list[str]) -> None:
    mode = stat.S_IMODE(path.stat().st_mode)
    if mode != expected:
        errors.append(f"{label} mode is {oct(mode)}, expected {oct(expected)}")


def check_file_mode(path: Path, expected: int, label: str, errors: list[str]) -> None:
    mode = stat.S_IMODE(path.stat().st_mode)
    if mode != expected:
        errors.append(f"{label} mode is {oct(mode)}, expected {oct(expected)}")


def _sha256_file(path: Path) -> str | None:
    h = hashlib.sha256()
    try:
        with open(path, "rb") as fh:
            for chunk in iter(lambda: fh.read(65536), b""):
                h.update(chunk)
        return h.hexdigest()
    except OSError:
        return None


class SnapshotEntry:
    __slots__ = ("kind", "mode", "size", "digest", "target")

    def __init__(
        self,
        kind: str,
        mode: int,
        size: int,
        digest: str | None,
        target: str | None,
    ) -> None:
        self.kind = kind
        self.mode = mode
        self.size = size
        self.digest = digest
        self.target = target


def _snapshot_path(path: Path) -> SnapshotEntry | None:
    try:
        st = path.lstat()
    except OSError:
        return None
    mode = stat.S_IMODE(st.st_mode)
    if stat.S_ISLNK(st.st_mode):
        try:
            target = os.readlink(path)
        except OSError:
            target = None
        return SnapshotEntry(
            kind="symlink",
            mode=mode,
            size=len(target) if target else 0,
            digest=None,
            target=target,
        )
    if stat.S_ISDIR(st.st_mode):
        return SnapshotEntry(kind="dir", mode=mode, size=0, digest=None, target=None)
    if stat.S_ISREG(st.st_mode):
        digest = _sha256_file(path)
        return SnapshotEntry(kind="file", mode=mode, size=st.st_size, digest=digest, target=None)
    return SnapshotEntry(kind="other", mode=mode, size=st.st_size, digest=None, target=None)


def _walk_no_follow(path: Path) -> list[Path]:
    """Walk *path* without following symlinks."""
    results: list[Path] = []
    try:
        for child in path.iterdir():
            results.append(child)
            if child.is_dir() and not child.is_symlink():
                results.extend(_walk_no_follow(child))
    except OSError:
        pass
    return results


def _snapshot_base_dir(base_dir: Path) -> dict[Path, SnapshotEntry]:
    snapshot: dict[Path, SnapshotEntry] = {}
    base_abs = base_dir.absolute()
    snapshot[base_abs] = _snapshot_path(base_dir)
    for p in _walk_no_follow(base_dir):
        snapshot[p.absolute()] = _snapshot_path(p)
    return snapshot


def _is_allowed_path(path: Path, runtime_root: Path) -> bool:
    """Return True if *path* is inside or is the runtime root."""
    try:
        return path.is_relative_to(runtime_root)
    except (ValueError, TypeError):
        return False


def _load_contract_limits(contract_dir: Path) -> dict[str, int]:
    limits_path = contract_dir / "limits.json"
    schema_path = contract_dir / "expected" / "limits.schema.json"
    if not limits_path.exists():
        raise RuntimeError(f"limits.json missing in contract dir: {limits_path}")
    if not schema_path.exists():
        raise RuntimeError(f"limits.schema.json missing in contract dir: {schema_path}")
    limits = load_json(limits_path)
    errors = schema_validator.validate_file(limits, schema_path)
    if errors:
        raise RuntimeError(f"limits.json invalid against schema: {errors}")
    required = {
        "max_tool_name_length",
        "max_profile_length",
        "max_event_value_length",
        "max_event_json_bytes",
        "max_total_spool_bytes",
        "max_retained_event_files",
        "max_distinct_tools",
        "max_distinct_profiles",
        "max_recent_event_ids",
        "max_summary_size_bytes",
    }
    missing = required - set(limits.keys())
    if missing:
        raise RuntimeError(f"limits.json missing keys: {sorted(missing)}")
    for key, value in limits.items():
        if isinstance(value, bool) or not isinstance(value, int) or value < 1:
            raise RuntimeError(f"limits.{key} must be a positive integer, got {value!r}")
    max_field = max(
        limits["max_tool_name_length"],
        limits["max_profile_length"],
        limits["max_event_value_length"],
    )
    if limits["max_event_json_bytes"] < max_field:
        raise RuntimeError("max_event_json_bytes must be >= largest field limit")
    if limits["max_total_spool_bytes"] < limits["max_event_json_bytes"]:
        raise RuntimeError("max_total_spool_bytes must be >= max_event_json_bytes")
    if limits["max_summary_size_bytes"] < limits["max_event_json_bytes"]:
        raise RuntimeError("max_summary_size_bytes must be >= max_event_json_bytes")
    if limits["max_retained_event_files"] < limits["max_recent_event_ids"]:
        raise RuntimeError("max_retained_event_files must be >= max_recent_event_ids")
    return limits


def find_run_dir(
    runtime_root: Path,
    deadline: float | None = None,
    timeout: float | None = None,
) -> Path | None:
    hex_chars = set("0123456789abcdef")
    if deadline is None:
        if timeout is None:
            timeout = 10.0
        deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            for entry in runtime_root.iterdir():
                name = entry.name
                if (
                    entry.is_dir()
                    and not entry.is_symlink()
                    and len(name) == 32
                    and all(c in hex_chars for c in name.lower())
                ):
                    return entry
        except OSError:
            pass
        time.sleep(0.01)
    return None


def _is_process_alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except (OSError, ProcessLookupError):
        return False
    return True


def _kill_process_tree(proc: subprocess.Popen, run_dir: Path | None) -> None:
    """Reap the candidate process group and any recorded sidecar/child pids."""
    try:
        os.killpg(proc.pid, signal.SIGTERM)
    except (OSError, ProcessLookupError):
        pass
    try:
        proc.wait(timeout=2)
    except subprocess.TimeoutExpired:
        try:
            os.killpg(proc.pid, signal.SIGKILL)
        except (OSError, ProcessLookupError):
            pass
        try:
            proc.wait(timeout=2)
        except subprocess.TimeoutExpired:
            pass

    if run_dir is not None:
        for name in ("supervisor.pid", "sidecar.pid", "child.pid"):
            pid_path = run_dir / name
            if pid_path.exists():
                try:
                    pid = int(pid_path.read_text(encoding="utf-8").strip().split()[0])
                    if not _is_process_alive(pid):
                        continue
                    os.kill(pid, signal.SIGTERM)
                    time.sleep(0.1)
                    if _is_process_alive(pid):
                        os.kill(pid, signal.SIGKILL)
                except (OSError, ProcessLookupError, ValueError):
                    pass
        continue_path = run_dir / "continue"
        if continue_path.exists():
            try:
                continue_path.unlink()
            except OSError:
                pass


def _collect_pids(proc_pid: int, run_dir: Path, deadline: float) -> list[int]:
    supervisor_pid_path = run_dir / "supervisor.pid"
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


def _find_run_dir_or_cleanup(
    proc: subprocess.Popen, runtime_root: Path, deadline: float
) -> Path | None:
    while time.monotonic() < deadline and proc.poll() is None:
        run_dir = find_run_dir(runtime_root, timeout=0.2)
        if run_dir is not None:
            return run_dir
    # Deadline expired without a run directory: make sure the candidate tree is
    # reaped before we return.
    if proc.poll() is None:
        _kill_process_tree(proc, None)
    return find_run_dir(runtime_root, timeout=0.0)


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


def _run_tty(
    cmd: list[str],
    env: dict[str, str],
    runtime_root: Path,
    deadline: float,
) -> tuple[subprocess.Popen, int, Path | None, bytes, bytes]:
    """Run the candidate under a PTY while continuously draining the master fd."""
    import pty
    import select
    import threading

    if runtime_root is None:
        raise RuntimeError("TTY mode requires a runtime-root")

    master, slave = pty.openpty()
    proc = subprocess.Popen(
        cmd,
        stdin=slave,
        stdout=slave,
        stderr=slave,
        env=env,
        close_fds=True,
        start_new_session=True,
    )
    os.close(slave)
    returncode = -1

    stdout_buf = bytearray()
    stop_event = threading.Event()
    run_dir_holder: list[Path | None] = [None]

    def drain() -> None:
        while not stop_event.is_set():
            try:
                ready, _, _ = select.select([master], [], [], 0.1)
                if ready:
                    data = os.read(master, 4096)
                    if not data:
                        break
                    stdout_buf.extend(data)
            except (OSError, ValueError):
                break

    def finder() -> None:
        while not stop_event.is_set() and time.monotonic() < deadline:
            run_dir = find_run_dir(runtime_root, timeout=0.2)
            if run_dir is not None:
                run_dir_holder[0] = run_dir
                return
            time.sleep(0.01)

    drain_thread = threading.Thread(target=drain, daemon=True)
    finder_thread = threading.Thread(target=finder, daemon=True)
    drain_thread.start()
    finder_thread.start()

    try:
        try:
            returncode = proc.wait(timeout=max(0, deadline - time.monotonic()))
        except subprocess.TimeoutExpired:
            _kill_process_tree(proc, run_dir_holder[0])
            returncode = -1
    finally:
        if proc.poll() is None:
            _kill_process_tree(proc, run_dir_holder[0])
        stop_event.set()
        try:
            os.close(master)
        except OSError:
            pass
        drain_thread.join(timeout=2)
        finder_thread.join(timeout=0.5)

    return proc, returncode, run_dir_holder[0], bytes(stdout_buf), b""


def _run_normal(
    cmd: list[str],
    env: dict[str, str],
    runtime_root: Path,
    deadline: float,
) -> tuple[subprocess.Popen, int, Path | None, bytes, bytes]:
    proc = subprocess.Popen(
        cmd,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        env=env,
        start_new_session=True,
    )
    run_dir: Path | None = None
    try:
        remaining = deadline - time.monotonic()
        stdout, stderr = proc.communicate(timeout=max(0, remaining))
        returncode = proc.returncode if proc.returncode is not None else -1
    except subprocess.TimeoutExpired:
        _kill_process_tree(proc, None)
        run_dir = find_run_dir(runtime_root, timeout=0.5)
        _kill_process_tree(proc, run_dir)
        return proc, -1, run_dir, b"", b""
    finally:
        if proc.poll() is None:
            _kill_process_tree(proc, run_dir)
    run_dir = find_run_dir(runtime_root, timeout=0.5)
    return proc, returncode, run_dir, stdout, stderr


def _run_normal_with_overlap(
    cmd: list[str],
    env: dict[str, str],
    runtime_root: Path,
    deadline: float,
) -> tuple[subprocess.Popen, int, Path | None, bytes, bytes]:
    proc = subprocess.Popen(
        cmd,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        env=env,
        start_new_session=True,
    )
    run_dir: Path | None = None
    continue_path: Path | None = None

    try:
        run_dir = _find_run_dir_or_cleanup(proc, runtime_root, deadline)
        if run_dir is None:
            _kill_process_tree(proc, None)
            try:
                remaining = deadline - time.monotonic()
                stdout, stderr = proc.communicate(timeout=max(0, min(5, remaining)))
            except subprocess.TimeoutExpired:
                stdout, stderr = b"", b""
            raise RuntimeError(
                f"No run directory appeared under {runtime_root}: {stderr.decode(errors='replace')}"
            )

        _collect_pids(proc.pid, run_dir, deadline)
        continue_path = run_dir / "continue"
        continue_path.write_text("go\n", encoding="utf-8")
        os.chmod(continue_path, 0o600)

        try:
            remaining = deadline - time.monotonic()
            stdout, stderr = proc.communicate(timeout=max(0, remaining))
            returncode = proc.returncode if proc.returncode is not None else -1
        except subprocess.TimeoutExpired:
            _kill_process_tree(proc, run_dir)
            returncode = -1
            stdout, stderr = b"", b""
    finally:
        if proc.poll() is None:
            _kill_process_tree(proc, run_dir)
        if continue_path is not None and continue_path.exists():
            try:
                continue_path.unlink()
            except OSError:
                pass

    return proc, returncode, run_dir, stdout, stderr


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
    if args.no_poll or args.stress:
        env["GOAL_DEVIN_FAKE_NO_POLL"] = "1"
    if args.stress:
        env["GOAL_DEVIN_FAKE_STRESS"] = "1"
    if args.process_overlap:
        env["GOAL_DEVIN_BARRIER"] = "1"
    env = _prepare_isolated_env(runtime_root, env)

    if args.existing_hooks:
        try:
            existing = load_json(Path(args.existing_hooks))
            expected_cmd = _first_command(existing)
            if expected_cmd:
                env["GOAL_DEVIN_EXPECTED_EXISTING_HOOK_COMMAND"] = expected_cmd
        except (json.JSONDecodeError, ValueError):
            pass

    deadline = time.monotonic() + args.timeout

    if args.tty:
        if args.process_overlap:
            raise RuntimeError("--tty and --process-overlap are not supported together")
        return _run_tty(cmd, env, runtime_root, deadline)

    if args.process_overlap:
        return _run_normal_with_overlap(cmd, env, runtime_root, deadline)

    return _run_normal(cmd, env, runtime_root, deadline)


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


def _check_spool_bounds(run_dir: Path, limits: dict[str, int], errors: list[str]) -> None:
    events_dir = run_dir / "events"
    if not events_dir.is_dir():
        errors.append("events/ directory missing")
        return

    json_files = [p for p in events_dir.iterdir() if p.suffix == ".json"]
    tmp_files = [p for p in events_dir.iterdir() if p.suffix == ".tmp"]
    if tmp_files:
        errors.append(f"Temporary event files remain: {[str(p.name) for p in tmp_files]}")

    total_size = 0
    for p in json_files:
        try:
            size = p.stat().st_size
        except OSError:
            continue
        total_size += size
        if size > limits["max_event_json_bytes"]:
            errors.append(
                f"Event file {p.name} size {size} exceeds max_event_json_bytes "
                f"{limits['max_event_json_bytes']}"
            )

    if len(json_files) > limits["max_retained_event_files"]:
        errors.append(
            f"Retained event files {len(json_files)} exceeds max "
            f"{limits['max_retained_event_files']}"
        )
    if total_size > limits["max_total_spool_bytes"]:
        errors.append(
            f"Total spool bytes {total_size} exceeds max {limits['max_total_spool_bytes']}"
        )

    summary_path = run_dir / "summary.json"
    if not summary_path.exists():
        errors.append("summary.json missing for spool bounds check")
        return
    try:
        summary = load_json(summary_path)
    except (json.JSONDecodeError, OSError) as exc:
        errors.append(f"summary.json invalid: {exc}")
        return

    if summary.get("total_events", 0) < 1:
        errors.append("summary reports no consumed events")
    if len(summary.get("consumed_event_ids", [])) > limits["max_recent_event_ids"]:
        errors.append(
            f"Recent event IDs {len(summary['consumed_event_ids'])} exceeds max "
            f"{limits['max_recent_event_ids']}"
        )
    if len(summary.get("tools", {})) > limits["max_distinct_tools"]:
        errors.append(
            f"Distinct tools {len(summary['tools'])} exceeds max {limits['max_distinct_tools']}"
        )
    if len(summary.get("profiles", {})) > limits["max_distinct_profiles"]:
        errors.append(
            f"Distinct profiles {len(summary['profiles'])} exceeds max "
            f"{limits['max_distinct_profiles']}"
        )

    try:
        summary_size = summary_path.stat().st_size
    except OSError:
        summary_size = 0
    if summary_size > limits["max_summary_size_bytes"]:
        errors.append(
            f"summary.json size {summary_size} exceeds max {limits['max_summary_size_bytes']}"
        )


def _is_owned(
    path: Path,
    owned_paths: set[Path],
    owned_roots: list[Path],
    owned_dirs: set[Path],
) -> bool:
    resolved = path.resolve()
    if resolved in owned_paths:
        return True
    if resolved in owned_dirs:
        return True
    for root in owned_roots:
        try:
            if resolved.is_relative_to(root):
                return True
        except ValueError:
            pass
    return False


def _check_ownership(
    run_dir: Path,
    canary: Path,
    manifest: dict[str, Any],
    canary_fixture: Path | None,
    preexisting_canary_hook: Path,
    preexisting_canary_hook_bytes: bytes | None,
    errors: list[str],
) -> None:
    """Verify every generated artifact is declared in the manifest and pre-existing
    paths are never marked as owned.  Directories are inventoried as well as files.
    """
    owned_paths = {Path(p).resolve() for p in manifest.get("owned_paths", [])}
    owned_roots = [Path(p).resolve() for p in manifest.get("owned_roots", [])]
    owned_dirs = {Path(p).resolve() for p in manifest.get("owned_dirs", [])}

    pre_existing: set[Path] = set()
    if canary_fixture and canary_fixture.is_dir():
        for src in _walk_no_follow(canary_fixture):
            rel = src.relative_to(canary_fixture)
            pre_existing.add((canary / rel).resolve())
    if preexisting_canary_hook_bytes is not None:
        pre_existing.add(preexisting_canary_hook.resolve())

    for path in _walk_no_follow(run_dir):
        resolved = path.resolve()
        if path.is_file():
            if not _is_owned(resolved, owned_paths, owned_roots, owned_dirs):
                errors.append(f"Generated runtime file not owned: {resolved}")
        elif path.is_dir():
            if not _is_owned(resolved, owned_paths, owned_roots, owned_dirs):
                errors.append(f"Generated runtime directory not owned: {resolved}")

    devin_dir = canary / ".devin"
    if devin_dir.is_dir():
        for path in _walk_no_follow(devin_dir):
            resolved = path.resolve()
            if resolved in pre_existing:
                continue
            if path.is_file():
                if not _is_owned(resolved, owned_paths, owned_roots, owned_dirs):
                    errors.append(f"Generated canary file not owned: {resolved}")
            elif path.is_dir():
                if not _is_owned(resolved, owned_paths, owned_roots, owned_dirs):
                    errors.append(f"Generated canary directory not owned: {resolved}")

    profile_path = Path(manifest["profile_path"]).resolve()
    if not _is_owned(profile_path, owned_paths, owned_roots, owned_dirs):
        errors.append("Generated profile path not declared in manifest")

    hooks_path = (canary / ".devin" / "hooks.v1.json").resolve()
    if preexisting_canary_hook_bytes is None and hooks_path.is_file():
        if hooks_path not in owned_paths and hooks_path not in owned_dirs:
            errors.append("Temporary project hook not declared in manifest")

    for pre in pre_existing:
        if _is_owned(pre, owned_paths, owned_roots, owned_dirs):
            errors.append(f"Pre-existing/user-owned path marked as owned: {pre}")


def _check_canary_cleanup(
    canary: Path,
    canary_snapshot: dict[Path, SnapshotEntry],
    manifest: dict[str, Any],
    preexisting_canary_hook: Path,
    preexisting_canary_hook_bytes: bytes | None,
    errors: list[str],
) -> None:
    """Assert generated profile and hook artifacts are removed and any
    pre-existing canary path (including .devin/hooks.v1.json) is unchanged.
    """
    hooks_file = canary / ".devin" / "hooks.v1.json"
    if preexisting_canary_hook_bytes is not None:
        if not hooks_file.is_file():
            errors.append("Pre-existing .devin/hooks.v1.json was removed instead of restored")
        else:
            if hooks_file.read_bytes() != preexisting_canary_hook_bytes:
                errors.append("Pre-existing .devin/hooks.v1.json was not restored byte-for-byte")
            old = canary_snapshot.get(hooks_file.resolve())
            if old is not None:
                current_mode = stat.S_IMODE(hooks_file.lstat().st_mode)
                if current_mode != old.mode:
                    errors.append(
                        f"Pre-existing .devin/hooks.v1.json mode changed: "
                        f"{oct(old.mode)} -> {oct(current_mode)}"
                    )
    else:
        if hooks_file.is_file():
            errors.append("Run-created .devin/hooks.v1.json was not removed")

    profile_path_str = manifest.get("profile_path")
    if profile_path_str:
        profile_dir = Path(profile_path_str).resolve().parent
        if profile_dir.is_dir():
            errors.append(f"Generated profile directory was not removed: {profile_dir}")

    # Every path that existed in the canary before the run must still exist with
    # the same kind, mode, size, digest, and symlink target.
    for path, old in canary_snapshot.items():
        if not path.exists() and not path.is_symlink():
            errors.append(f"Pre-existing canary path was removed: {path}")
            continue
        new = _snapshot_path(path)
        if new is None:
            errors.append(f"Cannot stat pre-existing canary path: {path}")
            continue
        if (
            old.kind != new.kind
            or old.mode != new.mode
            or old.size != new.size
            or old.digest != new.digest
            or old.target != new.target
        ):
            errors.append(
                f"Pre-existing canary path changed: {path} "
                f"({old.kind} {oct(old.mode)} size={old.size}) -> "
                f"({new.kind} {oct(new.mode)} size={new.size})"
            )


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
        ("limits.json", "limits.json"),
        ("limits.schema.json", "limits.schema.json"),
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


def _check_base_dir_integrity(
    base_dir: Path,
    runtime_root: Path,
    snapshot: dict[Path, SnapshotEntry],
    errors: list[str],
) -> None:
    """Detect new, modified, or deleted pre-existing paths outside the runtime root."""
    runtime_abs = runtime_root.absolute()
    current_paths: set[Path] = set()

    for p in _walk_no_follow(base_dir):
        abs_path = p.absolute()
        current_paths.add(abs_path)
        if _is_allowed_path(abs_path, runtime_abs):
            continue
        if abs_path not in snapshot:
            errors.append(f"New file or directory outside runtime root: {abs_path}")
            continue
        old = snapshot[abs_path]
        new = _snapshot_path(p)
        if old is None or new is None:
            errors.append(f"Cannot stat path: {abs_path}")
            continue
        if old.kind != new.kind:
            errors.append(f"Path type changed: {abs_path}")
            continue
        if old.kind == "file":
            if old.mode != new.mode:
                errors.append(f"File mode changed: {abs_path}")
            if old.size != new.size:
                errors.append(f"File size changed: {abs_path}")
            if old.digest != new.digest:
                errors.append(f"File digest changed: {abs_path}")
        elif old.kind == "dir":
            if old.mode != new.mode:
                errors.append(f"Directory mode changed: {abs_path}")
        elif old.kind == "symlink":
            if old.target != new.target:
                errors.append(f"Symlink target changed: {abs_path}")
            if old.mode != new.mode:
                errors.append(f"Symlink mode changed: {abs_path}")

    base_abs = base_dir.absolute()
    current_paths.add(base_abs)
    if base_abs not in snapshot:
        snapshot[base_abs] = _snapshot_path(base_dir)

    for abs_path, old in snapshot.items():
        if _is_allowed_path(abs_path, runtime_abs):
            continue
        if abs_path not in current_paths and not os.path.lexists(str(abs_path)):
            errors.append(f"Pre-existing path was deleted: {abs_path}")


def _cleanup(
    base_dir: Path,
    runtime_root: Path,
    keep: bool,
    base_dir_removable: bool,
    runtime_root_removable: bool,
) -> None:
    if keep:
        return
    if base_dir_removable:
        shutil.rmtree(base_dir, ignore_errors=True)
    elif runtime_root_removable and runtime_root.resolve() != base_dir.resolve():
        shutil.rmtree(runtime_root, ignore_errors=True)


def run_contract(args: argparse.Namespace) -> list[str]:
    errors: list[str] = []

    runtime_root_provided = args.runtime_root is not None
    if runtime_root_provided:
        runtime_root = Path(args.runtime_root).resolve()
    else:
        runtime_root = Path(tempfile.mkdtemp(prefix="goal-devin-contract-"))

    runtime_root_existed = runtime_root.exists()
    runtime_root.mkdir(parents=True, exist_ok=True)
    runtime_root_initial = set(runtime_root.iterdir())
    if runtime_root_existed and runtime_root_initial and runtime_root_provided:
        errors.append(f"--runtime-root already contains files: {runtime_root_initial}")
        return errors
    runtime_root_removable = (
        not runtime_root_provided or not runtime_root_existed or not runtime_root_initial
    )

    if args.base_dir:
        base_dir = Path(args.base_dir).resolve()
        base_dir.mkdir(parents=True, exist_ok=True)
        base_dir_initial_iter = set(base_dir.iterdir())
        if base_dir_initial_iter:
            base_dir_removable = False
        else:
            marker = base_dir / MANAGED_BASE_MARKER
            marker.write_text("managed\n", encoding="utf-8")
            base_dir_removable = True
    else:
        base_dir = runtime_root
        base_dir_removable = runtime_root_removable

    if not runtime_root.resolve().is_relative_to(base_dir.resolve()):
        errors.append("--runtime-root must be inside --base-dir")
        _cleanup(
            base_dir, runtime_root, args.keep_artifacts, base_dir_removable, runtime_root_removable
        )
        return errors

    canary_fixture = Path(args.canary_fixture).resolve() if args.canary_fixture else None

    canary = runtime_root / "canary"
    if canary_fixture:
        if canary.exists():
            shutil.rmtree(canary)
        shutil.copytree(canary_fixture, canary, symlinks=True)
    else:
        canary.mkdir(parents=True, exist_ok=True)

    base_dir_snapshot = _snapshot_base_dir(base_dir)
    canary_snapshot = _snapshot_base_dir(canary)

    preexisting_canary_hook = canary / ".devin" / "hooks.v1.json"
    if preexisting_canary_hook.is_file():
        preexisting_canary_hook_bytes = preexisting_canary_hook.read_bytes()
    elif args.existing_hooks:
        preexisting_canary_hook_bytes = Path(args.existing_hooks).resolve().read_bytes()
    else:
        preexisting_canary_hook_bytes = None

    run_dir: Path | None = None
    returncode = -1
    stdout = b""
    stderr = b""
    try:
        _proc, returncode, run_dir, stdout, stderr = run_candidate(args, runtime_root, canary)
    except RuntimeError as exc:
        errors.append(str(exc))
        _check_base_dir_integrity(base_dir, runtime_root, base_dir_snapshot, errors)
        _cleanup(
            base_dir, runtime_root, args.keep_artifacts, base_dir_removable, runtime_root_removable
        )
        return errors

    if returncode != 0:
        errors.append(f"Candidate exited with code {returncode}")
        if stderr:
            text = stderr.decode("utf-8", errors="replace").replace("\n", " ").strip()
            errors.append(f"stderr: ...{text[-500:]}")

    _check_base_dir_integrity(base_dir, runtime_root, base_dir_snapshot, errors)

    if run_dir is None:
        run_dir = find_run_dir(runtime_root, timeout=0.5)
    if run_dir is None:
        errors.append("No run directory found under runtime root")
        _cleanup(
            base_dir, runtime_root, args.keep_artifacts, base_dir_removable, runtime_root_removable
        )
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
        _cleanup(
            base_dir, runtime_root, args.keep_artifacts, base_dir_removable, runtime_root_removable
        )
        return errors

    manifest = load_json(manifest_path)
    summary = load_json(summary_path)
    record = load_json(record_path)

    contract_dir = Path(args.contract_dir).resolve() if args.contract_dir else Path(__file__).parent
    try:
        limits = _load_contract_limits(contract_dir)
    except RuntimeError as exc:
        errors.append(str(exc))
        _cleanup(
            base_dir, runtime_root, args.keep_artifacts, base_dir_removable, runtime_root_removable
        )
        return errors

    errors.extend(
        schema_validator.validate_file(manifest, contract_dir / "expected" / "manifest.schema.json")
    )
    errors.extend(
        schema_validator.validate_file(summary, contract_dir / "expected" / "summary.schema.json")
    )

    _check_file_modes(run_dir, errors)
    _check_ownership(
        run_dir,
        canary,
        manifest,
        canary_fixture,
        preexisting_canary_hook,
        preexisting_canary_hook_bytes,
        errors,
    )
    _check_canary_cleanup(
        canary,
        canary_snapshot,
        manifest,
        preexisting_canary_hook,
        preexisting_canary_hook_bytes,
        errors,
    )
    _check_spool_bounds(run_dir, limits, errors)

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

    if args.stress:
        if summary.get("total_events", 0) <= limits["max_retained_event_files"]:
            errors.append("stress mode did not consume more events than max_retained_event_files")

    _check_lifecycle(run_dir / "lifecycle.log", errors)

    secret_hits = secret_scan(run_dir, redact=runtime_root) + secret_scan(
        canary, redact=runtime_root
    )
    if secret_hits:
        for hit in secret_hits[:10]:
            errors.append(f"Secret-like pattern: {hit}")

    _cleanup(
        base_dir, runtime_root, args.keep_artifacts, base_dir_removable, runtime_root_removable
    )

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
