"""Sidecar management for the native launcher."""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

from native_launcher_python.runtime import RuntimeDirectory


class Sidecar:
    """Owns the sidecar subprocess that watches the hook spool."""

    def __init__(self, runtime: RuntimeDirectory) -> None:
        self.runtime = runtime
        self.process: subprocess.Popen[str] | None = None

    def start(self, pythonpath_entries: list[str] | None = None) -> int:
        """Start the sidecar process and return its PID."""
        sidecar_script = Path(__file__).with_name("sidecar_entry.py")
        env = os.environ.copy()
        env["GOAL_DEVIN_RUNTIME_DIR"] = str(self.runtime.runtime_dir)
        if pythonpath_entries:
            existing = env.get("PYTHONPATH", "")
            env["PYTHONPATH"] = os.pathsep.join(
                [p for p in pythonpath_entries if p] + ([existing] if existing else [])
            )

        self.process = subprocess.Popen(
            [sys.executable, str(sidecar_script), str(self.runtime.runtime_dir)],
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            env=env,
        )
        return self.process.pid

    def stop(self) -> None:
        """Signal the sidecar to stop and wait for it to exit."""
        self.runtime.create_stop_sentinel()
        if self.process is not None and self.process.poll() is None:
            try:
                self.process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                self.process.kill()
                self.process.wait(timeout=5)

    def terminate(self) -> None:
        """Forcefully terminate the sidecar (used by tests that simulate failure)."""
        if self.process is not None and self.process.poll() is None:
            self.process.terminate()
            try:
                self.process.wait(timeout=1)
            except subprocess.TimeoutExpired:
                self.process.kill()
                self.process.wait(timeout=1)

    def is_alive(self) -> bool:
        return self.process is not None and self.process.poll() is None
