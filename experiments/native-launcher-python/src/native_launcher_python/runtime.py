"""Runtime directory, manifest, and safe file I/O."""

from __future__ import annotations

import json
import os
import secrets
import tempfile
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from native_launcher_python.config import default_runtime_dir


@dataclass
class Manifest:
    """Record of a single launcher run."""

    schema_version: int
    run_id: str
    created_at: str
    devin_path: str
    model: str
    permission_mode: str
    sandbox: bool
    workdir: str
    runtime_dir: str
    events_dir: str
    hook_file: str
    hook_command: str
    profile_id: str
    profile_path: str
    summary_path: str
    sidecar_pid: int | None = None
    child_pid: int | None = None
    child_exit_code: int | None = None
    stopped_at: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "run_id": self.run_id,
            "created_at": self.created_at,
            "devin_path": self.devin_path,
            "model": self.model,
            "permission_mode": self.permission_mode,
            "sandbox": self.sandbox,
            "workdir": self.workdir,
            "runtime_dir": self.runtime_dir,
            "events_dir": self.events_dir,
            "hook_file": self.hook_file,
            "hook_command": self.hook_command,
            "profile_id": self.profile_id,
            "profile_path": self.profile_path,
            "summary_path": self.summary_path,
            "sidecar_pid": self.sidecar_pid,
            "child_pid": self.child_pid,
            "child_exit_code": self.child_exit_code,
            "stopped_at": self.stopped_at,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "Manifest":
        return cls(**{k: v for k, v in data.items() if k in cls.__dataclass_fields__})


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _run_id() -> str:
    return secrets.token_urlsafe(16)


def atomic_write_json(path: Path, data: dict[str, Any]) -> None:
    """Write JSON atomically, readable only by the current user."""
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=".tmp-", suffix=".json")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2)
        os.chmod(tmp, 0o600)
        os.replace(tmp, path)
    except Exception:
        try:
            os.unlink(tmp)
        except FileNotFoundError:
            pass
        raise


class RuntimeDirectory:
    """Owns a single launcher run directory and its cleanup."""

    def __init__(self, base_dir: Path | None = None) -> None:
        self.base_dir = (base_dir or default_runtime_dir()).expanduser().resolve()
        self.run_id = _run_id()
        self.runtime_dir = self.base_dir / self.run_id
        self.events_dir = self.runtime_dir / "events"
        self.summary_path = self.runtime_dir / "summary.json"
        self.manifest_path = self.runtime_dir / "manifest.json"
        self.stop_sentinel = self.runtime_dir / "stop.sidecar"

    def __enter__(self) -> "RuntimeDirectory":
        self.runtime_dir.mkdir(parents=True, mode=0o700, exist_ok=False)
        self.events_dir.mkdir(mode=0o700, exist_ok=False)
        return self

    def __exit__(self, exc_type: Any, exc: Any, tb: Any) -> None:
        # Cleanup is handled explicitly by the launcher so that abnormal failures
        # can be diagnosed; the context manager only creates.
        pass

    def write_manifest(self, manifest: Manifest) -> None:
        atomic_write_json(self.manifest_path, manifest.to_dict())

    def read_manifest(self) -> Manifest:
        with open(self.manifest_path, "r", encoding="utf-8") as f:
            return Manifest.from_dict(json.load(f))

    def update_manifest(self, **kwargs: Any) -> None:
        manifest = self.read_manifest()
        for key, value in kwargs.items():
            if hasattr(manifest, key):
                setattr(manifest, key, value)
        manifest.stopped_at = _now()
        self.write_manifest(manifest)

    def create_stop_sentinel(self) -> None:
        self.stop_sentinel.touch(mode=0o600, exist_ok=True)

    def remove(self) -> None:
        """Remove the entire runtime directory."""
        import shutil

        shutil.rmtree(self.runtime_dir, ignore_errors=True)
