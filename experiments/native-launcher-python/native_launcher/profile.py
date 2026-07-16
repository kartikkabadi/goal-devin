"""Temporary worker profile generation."""

import re
import shutil
from pathlib import Path

from .utils import atomic_write, ensure_private_dir, has_symlink_component, random_id


def make_profile_id() -> str:
    """Return a fresh Goal Devin worker profile ID."""
    return f"goal-devin-worker-{random_id(8)}"


def make_profile(canary: Path, profile_id: str, model: str) -> tuple[Path, list[Path]]:
    """Create a read-only AGENT.md profile under the canary and return its path.

    The returned list contains every directory that was newly created while
    building the profile path (e.g. ``.devin``, ``.devin/agents``,
    ``.devin/agents/<profile_id>``).
    """
    if not re.fullmatch(r"[A-Za-z0-9_.:/-]+", model):
        raise ValueError("model must be a one-line identifier safe for YAML")
    profile_dir = canary / ".devin" / "agents" / profile_id
    if has_symlink_component(canary, profile_dir):
        raise ValueError(f"Profile directory path contains a symlink: {profile_dir}")
    profile_path = profile_dir / "AGENT.md"
    if has_symlink_component(canary, profile_path):
        raise ValueError(f"Profile path contains a symlink: {profile_path}")
    created = ensure_private_dir(profile_dir, mode=0o700)
    body = f"""---
name: {profile_id}
description: Goal Devin read-only worker for the native integration trial
model: {model}
allowed-tools:
  - read
  - grep
  - glob
permissions:
  deny:
    - write
    - edit
---

<!-- goal-devin-generated: true -->

You are a read-only Goal Devin trial worker. Use the selected model and follow
project instructions. Do not perform destructive operations outside the current
task.
"""
    atomic_write(profile_path, body)
    return profile_path, created


def remove_profile(canary: Path, profile_id: str, created_dirs: list[Path] | None = None) -> None:
    """Remove only the generated profile directory, then any empty ancestors we created.

    Pre-existing directories (e.g. a user-owned ``.devin``) are never removed,
    even if they become empty.
    """
    profile_dir = canary / ".devin" / "agents" / profile_id
    if has_symlink_component(canary, profile_dir):
        raise ValueError(f"Profile directory path contains a symlink: {profile_dir}")
    if profile_dir.exists():
        shutil.rmtree(profile_dir)

    if created_dirs:
        # Remove only directories this run created, deepest first, if now empty.
        for d in sorted(created_dirs, key=lambda x: len(x.parts), reverse=True):
            if d.exists() and d.is_dir() and not any(d.iterdir()):
                try:
                    d.rmdir()
                except OSError:
                    pass
