"""Runtime manifest creation and helpers."""

import json
from pathlib import Path

from .utils import atomic_write, utcnow_iso


def make_manifest(
    run_id: str,
    runtime_dir: Path,
    model: str,
    permission_mode: str,
    devin_bin: Path,
    canary: Path,
    hook_command: list[str],
    profile_id: str,
    profile_path: Path,
    events_dir: Path,
    summary_path: Path,
) -> Path:
    """Write the run manifest into *runtime_dir* and return its path."""
    manifest = {
        "schema_version": 1,
        "run_id": run_id,
        "created_at": utcnow_iso(),
        "command": "goal-devin-dev",
        "model": model,
        "permission_mode": permission_mode,
        "devin_bin": str(devin_bin.resolve()),
        "canary": str(canary.resolve()),
        "hook_command": hook_command,
        "profile_id": profile_id,
        "profile_path": str(profile_path.resolve()),
        "events_dir": str(events_dir.resolve()),
        "summary_path": str(summary_path.resolve()),
        "goal_devin_generated": True,
    }
    runtime_dir.mkdir(parents=True, exist_ok=True)
    manifest_path = runtime_dir / "manifest.json"
    atomic_write(manifest_path, json.dumps(manifest, indent=2))
    return manifest_path
