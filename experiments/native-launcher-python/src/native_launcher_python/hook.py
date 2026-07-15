"""Install and restore the Goal Devin observation hook."""

from __future__ import annotations

import json
from pathlib import Path

from native_launcher_python.config import (
    HOOK_COMMAND_TIMEOUT,
    HOOK_FILE,
)


HOOK_EVENTS = ("SessionStart", "PreToolUse", "PostToolUse", "SessionEnd")


def _make_hook_entry(command: str) -> dict[str, object]:
    return {
        "type": "command",
        "command": command,
        "timeout": HOOK_COMMAND_TIMEOUT,
    }


def _empty_hook_config(template: str) -> dict[str, list[dict[str, object]]]:
    return {
        event: [
            {
                "matcher": "",
                "hooks": [_make_hook_entry(template.replace("{event}", event))],
            }
        ]
        for event in HOOK_EVENTS
    }


def install_hook(
    workdir: Path,
    runtime_dir: Path,
    hook_command: str,
) -> tuple[Path, bytes | None]:
    """Install the Goal Devin hook into the project hook file.

    Returns the hook file path and the original bytes (or None if the file did
    not exist).  If a hook file already exists, it is backed up exactly and
    restored on removal.
    """
    devin_dir = workdir / ".devin"
    devin_dir.mkdir(parents=True, exist_ok=True)
    hook_path = devin_dir / HOOK_FILE

    original: bytes | None = None
    if hook_path.exists():
        original = hook_path.read_bytes()

    config = _empty_hook_config(hook_command)
    hook_path.write_text(json.dumps(config, indent=2) + "\n", encoding="utf-8")
    return hook_path, original


def remove_hook(hook_path: Path, original: bytes | None) -> None:
    """Remove the Goal Devin hook file or restore the original bytes."""
    if original is None:
        hook_path.unlink(missing_ok=True)
        # Remove .devin only if it is empty and we created it.
        devin_dir = hook_path.parent
        try:
            if devin_dir.exists() and not any(devin_dir.iterdir()):
                devin_dir.rmdir()
        except OSError:
            pass
    else:
        hook_path.write_bytes(original)
