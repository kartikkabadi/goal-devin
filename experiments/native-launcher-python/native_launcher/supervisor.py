"""Supervisor that manages the sidecar, fake Devin child, and cleanup."""

import datetime
import json
import os
import re
import shlex
import shutil
import stat
import subprocess
import sys
import time
from pathlib import Path
from types import SimpleNamespace
from typing import Any

from . import __version__
from .manifest import make_manifest
from .profile import make_profile, make_profile_id, remove_profile
from .utils import atomic_write, has_symlink_component, mkdir_private, random_id, safe_path_under


def _validate_model(model: str) -> None:
    if not isinstance(model, str) or not re.fullmatch(r"[A-Za-z0-9_.:/-]+", model):
        raise ValueError("model must be a one-line identifier")


def _validate_permission_mode(mode: str) -> None:
    if not isinstance(mode, str) or not re.fullmatch(r"[A-Za-z0-9_-]+", mode):
        raise ValueError("permission-mode must be a one-line identifier")


def _validate_existing_hooks_config(config: Any) -> None:
    """Validate the parsed contents of a hooks.v1.json file."""
    if not isinstance(config, dict):
        raise ValueError("Existing hooks file must be a JSON object")
    for key, entries in config.items():
        if not isinstance(entries, list):
            raise ValueError(
                f"Existing hooks event {key!r} must be a list, got {type(entries).__name__}"
            )
        for i, entry in enumerate(entries):
            if not isinstance(entry, dict):
                raise ValueError(
                    f"Existing hooks event {key}[{i}] must be an object, got {type(entry).__name__}"
                )
            matcher = entry.get("matcher")
            if matcher is not None and not isinstance(matcher, str):
                raise ValueError(f"Existing hooks event {key}[{i}].matcher must be a string")
            hooks = entry.get("hooks", [])
            if not isinstance(hooks, list):
                raise ValueError(
                    f"Existing hooks event {key}[{i}].hooks must be a list, got {type(hooks).__name__}"
                )
            for j, h in enumerate(hooks):
                if not isinstance(h, dict):
                    raise ValueError(
                        f"Existing hooks event {key}[{i}].hooks[{j}] must be an object"
                    )


def _validate_existing_hooks_data(raw: bytes, label: str = "existing hooks") -> dict[str, Any]:
    """Parse and validate *raw* bytes before any mutation."""
    try:
        config = json.loads(raw.decode("utf-8"))
    except (json.JSONDecodeError, UnicodeDecodeError) as exc:
        raise ValueError(f"{label} is not valid JSON: {exc}") from exc
    _validate_existing_hooks_config(config)
    return config


def _validate_existing_hooks_file(hooks_file: Path) -> dict[str, Any]:
    """Parse and validate an existing hooks.v1.json file before any mutation."""
    return _validate_existing_hooks_data(hooks_file.read_bytes(), label=str(hooks_file))


def _lifecycle_log(path: Path | None, label: str) -> None:
    if path is None:
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    # Regression guard: the parent directory must already be private before any
    # lifecycle data is written.  This fails the run if the directory is created
    # with the process umask and only later chmodded.
    parent_mode = stat.S_IMODE(path.parent.stat().st_mode)
    if parent_mode != 0o700:
        raise RuntimeError(
            f"Lifecycle log parent directory {path.parent} mode is {oct(parent_mode)}, expected 0o700"
        )
    now = datetime.datetime.now(datetime.timezone.utc).isoformat()
    with open(path, "a", encoding="utf-8") as fh:
        fh.write(f"{label} {now}\n")
        fh.flush()
        os.fsync(fh.fileno())
    try:
        os.chmod(path, 0o600)
    except OSError:
        pass


def _set_file_mode(path: Path, mode: int) -> None:
    try:
        os.chmod(path, mode)
    except OSError:
        pass


def _candidate_dir() -> Path:
    """Return the directory that contains the native_launcher package."""
    return Path(__file__).resolve().parent.parent


class Supervisor:
    def __init__(self, args: SimpleNamespace) -> None:
        _validate_model(args.model)
        _validate_permission_mode(args.permission_mode)
        self.model = args.model
        self.permission_mode = args.permission_mode
        self.devin_bin = Path(args.devin_bin).resolve()
        self.contract_dir = Path(args.contract_dir).resolve()
        event_schema_path = self.contract_dir / "expected" / "event.schema.json"
        if not event_schema_path.exists():
            raise RuntimeError(
                f"--contract-dir must contain expected/event.schema.json: {self.contract_dir}"
            )
        try:
            schema = json.loads(event_schema_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise RuntimeError(f"Invalid event schema JSON in {event_schema_path}: {exc}") from exc
        if not isinstance(schema, dict) or "properties" not in schema:
            raise RuntimeError(f"Invalid event schema shape: {event_schema_path}")
        self._event_schema = schema

        self.runtime_root = Path(args.runtime_root).resolve()
        self.canary_arg = Path(args.canary).resolve() if args.canary else None
        self.existing_hooks = Path(args.existing_hooks).resolve() if args.existing_hooks else None
        self.keep_canary = args.keep_canary

        self.run_id = random_id(16)
        self.runtime_dir = self.runtime_root / self.run_id
        self.canary: Path | None = None
        self.profile_id: str | None = None
        self.profile_path: Path | None = None
        self.hook_path: Path | None = None
        self.events_dir: Path | None = None
        self.summary_path: Path | None = None
        self.manifest_path: Path | None = None
        self.sidecar_proc: subprocess.Popen | None = None
        self.sidecar_returncode: int | None = None
        self.devin_proc: subprocess.Popen | None = None
        self.devin_returncode: int | None = None
        self.original_hooks_bytes: bytes | None = None
        self.original_hooks_mode: int | None = None
        self.hook_owned: bool = False
        self.lifecycle_path: Path | None = None

    def _env(self) -> dict[str, str]:
        env = os.environ.copy()
        env["GOAL_DEVIN_RUNTIME_DIR"] = str(self.runtime_dir)
        if self.events_dir:
            env["GOAL_DEVIN_EVENTS_DIR"] = str(self.events_dir)
        if self.lifecycle_path:
            env["GOAL_DEVIN_LIFECYCLE_LOG"] = str(self.lifecycle_path)
        candidate_dir = _candidate_dir()
        old_pythonpath = env.get("PYTHONPATH", "")
        env["PYTHONPATH"] = (
            f"{candidate_dir}{os.pathsep}{old_pythonpath}" if old_pythonpath else str(candidate_dir)
        )
        return env

    def _write_pid(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(str(os.getpid()), encoding="utf-8")
        os.chmod(path, 0o600)

    def _copy_runtime_files(self) -> None:
        event_schema_src = self.contract_dir / "expected" / "event.schema.json"
        if not event_schema_src.exists():
            raise FileNotFoundError(f"Event schema missing in contract dir: {event_schema_src}")
        event_schema_dst = self.runtime_dir / "event.schema.json"
        shutil.copyfile(event_schema_src, event_schema_dst)
        os.chmod(event_schema_dst, 0o600)

        limits_src = self.contract_dir / "limits.json"
        if limits_src.exists():
            limits_dst = self.runtime_dir / "limits.json"
            shutil.copyfile(limits_src, limits_dst)
            os.chmod(limits_dst, 0o600)

    def _install_hook_script(self) -> list[str]:
        hook_src = Path(__file__).resolve().parent / "hook.py"
        hook_dst = self.runtime_dir / "hook"
        shutil.copyfile(hook_src, hook_dst)
        os.chmod(hook_dst, 0o700)
        self.hook_path = hook_dst
        return [sys.executable, str(hook_dst), str(self.events_dir)]

    def _install_canary_hook(self, hook_command: list[str]) -> None:
        devin_dir = self.canary / ".devin"
        hooks_file = devin_dir / "hooks.v1.json"
        if has_symlink_component(self.canary, devin_dir):
            raise ValueError("canary .devin path contains a symlink")
        if has_symlink_component(self.canary, hooks_file):
            raise ValueError("canary hooks.v1.json path contains a symlink")

        # Snapshot existence before any mutation.  The temporary project hook is
        # only marked as owned when it did not exist before this run.
        hook_file_existed = hooks_file.exists()
        if hook_file_existed:
            self.original_hooks_bytes = hooks_file.read_bytes()
            self.original_hooks_mode = stat.S_IMODE(hooks_file.stat().st_mode)
            existing_config = _validate_existing_hooks_data(
                self.original_hooks_bytes, label=str(hooks_file)
            )
        else:
            self.original_hooks_bytes = None
            self.original_hooks_mode = None
            existing_config = {}

        self.hook_owned = not hook_file_existed

        # Only create/chmod .devin if it does not already exist; a
        # pre-existing .devin directory belongs to the user/project.
        devin_dir_created = not devin_dir.exists()
        devin_dir.mkdir(parents=True, exist_ok=True)
        if devin_dir_created:
            os.chmod(devin_dir, 0o700)

        command_str = " ".join(shlex.quote(str(part)) for part in hook_command)
        goal_devin_entry = {
            "matcher": "",
            "hooks": [
                {
                    "type": "command",
                    "command": command_str,
                    "timeout": 5,
                }
            ],
        }

        new_config: dict[str, Any] = {}
        for event_name in ("PreToolUse", "PostToolUse"):
            new_config[event_name] = [goal_devin_entry] + existing_config.get(event_name, [])

        # Preserve any other event keys the existing fixture may contain.
        for key, value in existing_config.items():
            if key not in new_config:
                new_config[key] = value

        atomic_write(hooks_file, json.dumps(new_config, indent=2), file_mode=0o600)

    def _restore_canary_hook(self) -> None:
        if self.canary is None:
            return
        hooks_file = self.canary / ".devin" / "hooks.v1.json"
        if self.original_hooks_bytes is not None:
            hooks_file.write_bytes(self.original_hooks_bytes)
            if self.original_hooks_mode is not None:
                os.chmod(hooks_file, self.original_hooks_mode)
        elif hooks_file.exists():
            hooks_file.unlink()

    def _create_canary(self) -> None:
        if self.canary_arg:
            if not safe_path_under(self.runtime_root, self.canary_arg):
                raise ValueError("canary must be inside runtime-root")
            if has_symlink_component(self.runtime_root, self.canary_arg):
                raise ValueError("canary path contains a symlink")
            self.canary = self.canary_arg
            self.canary.mkdir(parents=True, exist_ok=True)
        else:
            self.canary = self.runtime_dir / "canary"
            self.canary.mkdir(parents=True, exist_ok=True)

        if self.existing_hooks:
            if not self.existing_hooks.exists():
                raise FileNotFoundError(f"existing-hooks fixture not found: {self.existing_hooks}")
            # Validate the source bytes before any canary mutation.
            source_bytes = self.existing_hooks.read_bytes()
            _validate_existing_hooks_data(source_bytes, label=str(self.existing_hooks))

            devin_dir = self.canary / ".devin"
            if has_symlink_component(self.canary, devin_dir):
                raise ValueError("canary .devin path contains a symlink")
            dst = devin_dir / "hooks.v1.json"
            if has_symlink_component(self.canary, dst):
                raise ValueError("canary hooks.v1.json path contains a symlink")

            devin_dir_created = not devin_dir.exists()
            devin_dir.mkdir(parents=True, exist_ok=True)
            if devin_dir_created:
                os.chmod(devin_dir, 0o700)
            shutil.copyfile(self.existing_hooks, dst)
            os.chmod(dst, stat.S_IMODE(self.existing_hooks.stat().st_mode))
        else:
            # Pre-existing canary hooks must be validated before any profile or
            # sidecar work is started, and their pre-mutation state captured.
            hooks_file = self.canary / ".devin" / "hooks.v1.json"
            if hooks_file.exists():
                if has_symlink_component(self.canary, hooks_file):
                    raise ValueError("canary hooks.v1.json path contains a symlink")
                self.original_hooks_bytes = hooks_file.read_bytes()
                self.original_hooks_mode = stat.S_IMODE(hooks_file.stat().st_mode)
                _validate_existing_hooks_data(self.original_hooks_bytes, label=str(hooks_file))
                self.hook_owned = False

    def _start_sidecar(self) -> None:
        candidate_dir = _candidate_dir()
        cmd = [sys.executable, "-m", "native_launcher.sidecar", str(self.runtime_dir)]
        env = self._env()
        self.sidecar_proc = subprocess.Popen(
            cmd,
            cwd=candidate_dir,
            env=env,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            start_new_session=True,
        )
        ready_path = self.runtime_dir / "sidecar-ready"
        deadline = time.monotonic() + 5
        while time.monotonic() < deadline:
            if ready_path.exists():
                return
            if self.sidecar_proc.poll() is not None:
                break
            time.sleep(0.01)
        raise RuntimeError("Sidecar failed to become ready within timeout")

    def _run_devin(self) -> None:
        env = self._env()
        cmd = [
            str(self.devin_bin),
            "--model",
            self.model,
            "--permission-mode",
            self.permission_mode,
        ]
        self.devin_proc = subprocess.Popen(
            cmd,
            cwd=self.canary,
            env=env,
            stdin=None,
            stdout=None,
            stderr=None,
        )
        self.devin_returncode = self.devin_proc.wait()

    def _stop_sidecar(self) -> None:
        if self.sidecar_proc is None:
            return
        try:
            self.sidecar_proc.terminate()
            try:
                self.sidecar_returncode = self.sidecar_proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                self.sidecar_proc.kill()
                self.sidecar_returncode = self.sidecar_proc.wait()
        except ProcessLookupError:
            pass

    def _read_summary(self) -> dict | None:
        if self.summary_path and self.summary_path.exists():
            return json.loads(self.summary_path.read_text(encoding="utf-8"))
        return None

    def _print_summary(self, summary: dict | None) -> None:
        if summary is None:
            print("Goal Devin native mode completed (no summary)", file=sys.stderr, flush=True)
            return
        total = summary.get("total_events", 0)
        last = summary.get("last_event", {}) or {}
        print(
            f"goal-devin-dev v{__version__}: model={self.model}, "
            f"events={total}, last_tool={last.get('tool_name')}"
        )

    def run(self) -> int:
        """Execute the happy-path lifecycle and return the child's exit code."""
        # Create/chmod the runtime directory to 0700 before any file or
        # subdirectory is written, including the lifecycle log.
        mkdir_private(self.runtime_dir, mode=0o700)

        self.events_dir = self.runtime_dir / "events"
        self.events_dir.mkdir(parents=True, exist_ok=True)
        os.chmod(self.events_dir, 0o700)
        self.summary_path = self.runtime_dir / "summary.json"
        self._write_pid(self.runtime_dir / "supervisor.pid")

        self.lifecycle_path = self.runtime_dir / "lifecycle.log"
        _lifecycle_log(self.lifecycle_path, "supervisor_start")

        self._create_canary()
        if self.canary is None:
            raise RuntimeError("canary was not created")

        self.profile_id = make_profile_id()
        self.profile_path = make_profile(self.canary, self.profile_id, self.model)

        hook_command = self._install_hook_script()
        self._install_canary_hook(hook_command)

        self.manifest_path = make_manifest(
            run_id=self.run_id,
            runtime_dir=self.runtime_dir,
            model=self.model,
            permission_mode=self.permission_mode,
            devin_bin=self.devin_bin,
            canary=self.canary,
            hook_command=hook_command,
            hook_path=self.hook_path,
            hook_owned=self.hook_owned,
            profile_id=self.profile_id,
            profile_path=self.profile_path,
            events_dir=self.events_dir,
            summary_path=self.summary_path,
            lifecycle_log_path=self.lifecycle_path,
        )

        self._copy_runtime_files()
        self._start_sidecar()

        try:
            self._run_devin()
        finally:
            self._stop_sidecar()
            _lifecycle_log(self.lifecycle_path, "supervisor_end")

        if self.profile_id:
            remove_profile(self.canary, self.profile_id)
        self._restore_canary_hook()

        summary = self._read_summary()
        self._print_summary(summary)

        if not self.keep_canary and self.canary is not None:
            shutil.rmtree(self.canary, ignore_errors=True)

        if self.devin_returncode is None:
            return 1
        return self.devin_returncode
