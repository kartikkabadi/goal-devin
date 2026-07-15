"""Supervisor that launches native Devin with a sidecar and custom profile."""

from __future__ import annotations

import os
import signal
import subprocess
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from native_launcher_python.config import (
    GOAL_DEVIN_RUNTIME_DIR_ENV,
    VALID_PERMISSION_MODES,
    resolve_devin,
)
from native_launcher_python.hook import install_hook, remove_hook
from native_launcher_python.profile import install_profile, remove_profile
from native_launcher_python.runtime import Manifest, RuntimeDirectory
from native_launcher_python.sidecar import Sidecar
from native_launcher_python.summary import print_summary


@dataclass
class LauncherOptions:
    workdir: Path
    model: str
    permission_mode: str
    sandbox: bool = False
    worker_model: str | None = None
    keep_profile: bool = False
    keep_runtime: bool = False
    extra_devin_args: list[str] | None = None


class Launcher:
    """Launch a native Devin session with Goal Devin policy around it."""

    def __init__(self, options: LauncherOptions) -> None:
        self.options = options
        self.runtime: RuntimeDirectory | None = None
        self.sidecar: Sidecar | None = None
        self.hook_path: Path | None = None
        self.hook_backup: bytes | None = None
        self.profile_path: Path | None = None
        self.child: subprocess.Popen[str] | None = None
        self._original_sigint = signal.getsignal(signal.SIGINT)
        self._interrupted = False
        self._cleaned = False

    def _validate(self) -> None:
        if not self.options.model:
            raise ValueError("--model is required")
        mode = self.options.permission_mode
        if mode not in VALID_PERMISSION_MODES:
            raise ValueError(
                f"invalid permission mode: {mode!r}. "
                f"Valid modes: {', '.join(sorted(VALID_PERMISSION_MODES))}"
            )
        workdir = self.options.workdir.resolve()
        if not workdir.is_dir():
            raise FileNotFoundError(f"workdir does not exist: {workdir}")

    def _prepare(self) -> None:
        devin_path = resolve_devin()
        override = os.environ.get("GOAL_DEVIN_RUNTIME_DIR_ENV_OVERRIDE", "")
        base_dir = Path(override).expanduser() if override else None
        # ^ allow tests to override the base runtime location; not part of public CLI.
        self.runtime = RuntimeDirectory(base_dir=base_dir)
        self.runtime.__enter__()

        # Sidecar must be able to import the package, so propagate src dir via PYTHONPATH.
        src_dir = Path(__file__).parent.parent
        pythonpath_entries = [str(src_dir)]

        runtime_dir = self.runtime.runtime_dir
        hook_command = f"{sys.executable} -m native_launcher_python.hook_entry {{event}}"
        # The hook entry expects the event name as argv[1] and GOAL_DEVIN_RUNTIME_DIR env.

        self.hook_path, self.hook_backup = install_hook(
            self.options.workdir,
            runtime_dir,
            hook_command,
        )

        worker_model = self.options.worker_model or self.options.model
        profile_id = f"goal-devin-worker-{self.runtime.run_id[:8]}"
        self.profile_path = install_profile(
            self.options.workdir,
            profile_id,
            worker_model,
        )

        self.sidecar = Sidecar(self.runtime)
        sidecar_pid = self.sidecar.start(pythonpath_entries=pythonpath_entries)

        manifest = Manifest(
            schema_version=1,
            run_id=self.runtime.run_id,
            created_at=datetime.now(timezone.utc).isoformat(timespec="seconds"),
            devin_path=str(devin_path),
            model=self.options.model,
            permission_mode=self.options.permission_mode,
            sandbox=self.options.sandbox,
            workdir=str(self.options.workdir.resolve()),
            runtime_dir=str(runtime_dir),
            events_dir=str(self.runtime.events_dir),
            hook_file=str(self.hook_path),
            hook_command=hook_command,
            profile_id=profile_id,
            profile_path=str(self.profile_path),
            summary_path=str(self.runtime.summary_path),
            sidecar_pid=sidecar_pid,
        )
        self.runtime.write_manifest(manifest)

    def _devin_argv(self) -> list[str]:
        argv = [str(resolve_devin())]
        argv.extend(["--model", self.options.model])
        argv.extend(["--permission-mode", self.options.permission_mode])
        if self.options.sandbox:
            argv.append("--sandbox")
        if self.options.extra_devin_args:
            argv.extend(self.options.extra_devin_args)
        return argv

    def _sigint_handler(self, signum: int, frame: object) -> None:  # noqa: ARG001
        self._interrupted = True
        if self.child is not None and self.child.poll() is None:
            self.child.send_signal(signal.SIGINT)

    def _spawn(self) -> subprocess.Popen[str]:
        env = os.environ.copy()
        env[GOAL_DEVIN_RUNTIME_DIR_ENV] = str(self.runtime.runtime_dir)  # type: ignore[union-attr]
        src_dir = str(Path(__file__).parent.parent)
        existing = env.get("PYTHONPATH", "")
        env["PYTHONPATH"] = src_dir + (os.pathsep + existing if existing else "")

        argv = self._devin_argv()
        return subprocess.Popen(
            argv,
            cwd=self.options.workdir,
            stdin=None,
            stdout=None,
            stderr=None,
            env=env,
        )

    def run(self) -> int:
        self._validate()
        self._prepare()
        assert self.runtime is not None

        signal.signal(signal.SIGINT, self._sigint_handler)
        try:
            self.child = self._spawn()
            self.runtime.update_manifest(child_pid=self.child.pid)
            exit_code = self.child.wait()
        except Exception:
            if self.child is not None and self.child.poll() is None:
                self.child.terminate()
                self.child.wait(timeout=5)
            raise
        finally:
            signal.signal(signal.SIGINT, self._original_sigint)
            self._cleanup(exit_code)

        return exit_code

    def _cleanup(self, exit_code: int) -> None:
        if self._cleaned or self.runtime is None:
            return
        self._cleaned = True
        self.runtime.update_manifest(child_exit_code=exit_code)

        if self.sidecar is not None:
            self.sidecar.stop()

        if self.child is not None and self.child.poll() is None:
            self.child.terminate()
            try:
                self.child.wait(timeout=5)
            except subprocess.TimeoutExpired:
                self.child.kill()
                self.child.wait(timeout=5)

        print_summary(self.runtime.summary_path, self.runtime.read_manifest())

        if self.profile_path is not None and not self.options.keep_profile:
            profile_id = self.runtime.read_manifest().profile_id
            remove_profile(self.options.workdir, profile_id)

        if self.hook_path is not None:
            remove_hook(self.hook_path, self.hook_backup)

        if not self.options.keep_runtime:
            self.runtime.remove()

    def __enter__(self) -> "Launcher":
        return self

    def __exit__(self, exc_type: object, exc: object, tb: object) -> None:
        if exc and self.child is not None and self.child.poll() is None:
            self.child.terminate()
            try:
                self.child.wait(timeout=5)
            except subprocess.TimeoutExpired:
                self.child.kill()
                self.child.wait(timeout=5)
        self._cleanup(self.child.returncode if self.child is not None else 1)
