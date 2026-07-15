"""Temporary worker profile generation."""

from pathlib import Path

from .utils import atomic_write, mkdir_private, random_id


def make_profile_id() -> str:
    """Return a fresh Goal Devin worker profile ID."""
    return f"goal-devin-worker-{random_id(8)}"


def make_profile(canary: Path, profile_id: str, model: str) -> Path:
    """Create a read-only AGENT.md profile under the canary and return its path."""
    profile_dir = canary / ".devin" / "agents" / profile_id
    mkdir_private(profile_dir, mode=0o700)
    profile_path = profile_dir / "AGENT.md"
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
    return profile_path


def remove_profile(canary: Path, profile_id: str) -> None:
    """Remove only the generated profile directory, never the parent agent store."""
    profile_dir = canary / ".devin" / "agents" / profile_id
    if profile_dir.exists():
        import shutil

        shutil.rmtree(profile_dir)
