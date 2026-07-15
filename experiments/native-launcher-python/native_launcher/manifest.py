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
    hook_path: Path,
    hook_owned: bool,
    profile_id: str,
    profile_path: Path,
    events_dir: Path,
    summary_path: Path,
    lifecycle_log_path: Path,
) -> Path:
    """Write the run manifest into *runtime_dir* and return its path.

    The manifest declares every path the candidate owns or creates, separated into
    explicit ``owned_paths`` and directory ``owned_roots`` so the shared runner can
    verify cleanup targets without requiring a manifest rewrite for every event file.
    """
    manifest_path = runtime_dir / "manifest.json"
    hooks_file = canary / ".devin" / "hooks.v1.json"
    profile_dir = profile_path.parent
    agents_dir = profile_dir.parent
    devin_dir = agents_dir.parent

    owned_paths: list[str] = [
        str(manifest_path.resolve()),
        str(hook_path.resolve()),
        str(lifecycle_log_path.resolve()),
        str((runtime_dir / "supervisor.pid").resolve()),
        str((runtime_dir / "sidecar.pid").resolve()),
        str((runtime_dir / "child.pid").resolve()),
        str((runtime_dir / "sidecar-ready").resolve()),
        str((runtime_dir / "event.schema.json").resolve()),
        str(summary_path.resolve()),
        str((runtime_dir / "fake-devin.record.json").resolve()),
        str(profile_path.resolve()),
    ]
    if hook_owned:
        owned_paths.append(str(hooks_file.resolve()))

    owned_roots: list[str] = [
        str(runtime_dir.resolve()),
        str(events_dir.resolve()),
        str(profile_dir.resolve()),
        str(agents_dir.resolve()),
    ]
    if hook_owned:
        owned_roots.append(str(devin_dir.resolve()))

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
        "owned_paths": owned_paths,
        "owned_roots": owned_roots,
        "owned_prefixes": [],
    }
    runtime_dir.mkdir(parents=True, exist_ok=True)
    atomic_write(manifest_path, json.dumps(manifest, indent=2))
    return manifest_path
