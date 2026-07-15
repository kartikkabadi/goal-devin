"""Configuration and constants for the native launcher."""

from __future__ import annotations

import os
from pathlib import Path

SCHEMA_VERSION = 1

HOOK_FILE = "hooks.v1.json"
AGENTS_DIR = ".devin/agents"
HOOK_COMMAND_TIMEOUT = 5

DEFAULT_DEVIN = "devin"
DEVIN_EXECUTABLE_ENV = "DEVIN_EXECUTABLE"

GOAL_DEVIN_RUNTIME_DIR_ENV = "GOAL_DEVIN_RUNTIME_DIR"
GOAL_DEVIN_HOOK_MARKER = "goal-devin-generated"

PERMISSION_MODES = frozenset(
    {
        "normal",
        "auto",
        "accept-edits",
        "dangerous",
        "yolo",
        "bypass",
        "autonomous",
    }
)

# Permission modes accepted by Devin v3000.1.27.  Keep this list conservative;
# aliases are resolved by the devin binary, but we pre-check to fail fast with a
# clear message.
VALID_PERMISSION_MODES = frozenset(
    {
        "normal",
        "accept-edits",
        "dangerous",
        "autonomous",
    }
)


def default_runtime_dir() -> Path:
    """Return the base runtime directory under ~/.goal-devin."""
    return Path.home() / ".goal-devin" / "runtime"


def resolve_devin() -> Path:
    """Find the real devin executable or use the override in DEVIN_EXECUTABLE."""
    override = os.environ.get(DEVIN_EXECUTABLE_ENV)
    if override:
        return Path(override)
    import shutil

    path = shutil.which(DEFAULT_DEVIN)
    if not path:
        raise RuntimeError("Could not find 'devin' executable. Set DEVIN_EXECUTABLE to its path.")
    return Path(path)
