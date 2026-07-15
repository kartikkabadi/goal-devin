"""Supervisor that manages the sidecar, fake Devin child, and cleanup."""

import json
import os
import shlex
import shutil
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

from . import __version__
from .manifest import make_manifest
from .profile import make_profile, make_profile_id, remove_profile
from .utils import atomic_write, mkdir_private, random_id, safe_path_under


def _candidate_dir() -> Path:
    """Return the directory that contains the native_launcher package."""
    return Path(__file__).resolve().parent.parent


class Supervisor:
    def __init__(self, args: SimpleNamespace) -> None:
        self.model = args.model
        self.permission_mode = args.permission_mode
        self.devin_bin = Path(args.devin_bin).resolve()
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
        self.testkit_dir: Path | None = None

    def _env(self) -> dict[str, str]:
        env = os.environ.copy()
        env["GOAL_DEVIN_RUNTIME_DIR"] = str(self.runtime_dir)
        if self.events_dir:
            env["GOAL_DEVIN_EVENTS_DIR"] = str(self.events_dir)
        candidate_dir = _candidate_dir()
        old_pythonpath = env.get("PYTHONPATH", "")
        env["PYTHONPATH"] = (
            f"{candidate_dir}{os.pathsep}{old_pythonpath}" if old_pythonpath else str(candidate_dir)
        )
        return env

    def _find_testkit_dir(self) -> Path | None:
        candidate = self.devin_bin.parent
        if (candidate / "expected" / "event.schema.json").exists():
            return candidate
        return None

    def _copy_event_schema(self) -> None:
        if self.testkit_dir is None:
            return
        src = self.testkit_dir / "expected" / "event.schema.json"
        if src.exists():
            dst = self.runtime_dir / "event.schema.json"
            shutil.copyfile(src, dst)
            os.chmod(dst, 0o600)

    def _install_hook_script(self) -> list[str]:
        hook_src = Path(__file__).resolve().parent / "hook.py"
        hook_dst = self.runtime_dir / "hook"
        shutil.copyfile(hook_src, hook_dst)
        os.chmod(hook_dst, 0o700)
        self.hook_path = hook_dst
        return [sys.executable, str(hook_dst), str(self.events_dir)]

    def _install_canary_hook(self, hook_command: list[str]) -> None:
        devin_dir = self.canary / ".devin"
        devin_dir.mkdir(parents=True, exist_ok=True)
        os.chmod(devin_dir, 0o700)
        hooks_file = devin_dir / "hooks.json"

        if hooks_file.exists():
            self.original_hooks_bytes = hooks_file.read_bytes()

        command_str = " ".join(shlex.quote(str(part)) for part in hook_command)
        config = {
            "PreToolUse": [
                {
                    "matcher": "",
                    "hooks": [
                        {
                            "type": "command",
                            "command": command_str,
                            "timeout": 5,
                        }
                    ],
                }
            ],
            "PostToolUse": [
                {
                    "matcher": "",
                    "hooks": [
                        {
                            "type": "command",
                            "command": command_str,
                            "timeout": 5,
                        }
                    ],
                }
            ],
        }
        atomic_write(hooks_file, json.dumps(config, indent=2), file_mode=0o600)

    def _restore_canary_hook(self) -> None:
        if self.canary is None:
            return
        hooks_file = self.canary / ".devin" / "hooks.json"
        if self.original_hooks_bytes is not None:
            hooks_file.write_bytes(self.original_hooks_bytes)
            os.chmod(hooks_file, 0o600)
        elif hooks_file.exists():
            hooks_file.unlink()

    def _create_canary(self) -> None:
        if self.canary_arg:
            if not safe_path_under(self.runtime_root, self.canary_arg):
                raise ValueError("canary must be inside runtime-root")
            self.canary = self.canary_arg
            self.canary.mkdir(parents=True, exist_ok=True)
        else:
            self.canary = self.runtime_dir / "canary"
            self.canary.mkdir(parents=True, exist_ok=True)

        if self.existing_hooks:
            if not self.existing_hooks.exists():
                raise FileNotFoundError(f"existing-hooks fixture not found: {self.existing_hooks}")
            devin_dir = self.canary / ".devin"
            devin_dir.mkdir(parents=True, exist_ok=True)
            os.chmod(devin_dir, 0o700)
            dst = devin_dir / "hooks.json"
            shutil.copyfile(self.existing_hooks, dst)
            os.chmod(dst, 0o600)

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

    def _run_devin(self) -> None:
        env = self._env()
        cmd = [
            str(self.devin_bin),
            "-p",
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
        self.testkit_dir = self._find_testkit_dir()

        mkdir_private(self.runtime_dir, mode=0o700)
        self.events_dir = self.runtime_dir / "events"
        self.events_dir.mkdir(parents=True, exist_ok=True)
        os.chmod(self.events_dir, 0o700)
        self.summary_path = self.runtime_dir / "summary.json"

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
            profile_id=self.profile_id,
            profile_path=self.profile_path,
            events_dir=self.events_dir,
            summary_path=self.summary_path,
        )

        self._copy_event_schema()
        self._start_sidecar()

        try:
            self._run_devin()
        finally:
            self._stop_sidecar()

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
