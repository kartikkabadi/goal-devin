"""Final summary formatting and printing."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any


def print_summary(summary_path: Path, manifest: Any) -> None:
    """Print a bounded final summary to stdout."""
    try:
        with open(summary_path, "r", encoding="utf-8") as f:
            summary = json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        summary = {}

    lines = [
        "Goal Devin dev session finished.",
        f"  run_id:         {manifest.run_id}",
        f"  model:          {manifest.model}",
        f"  permission:     {manifest.permission_mode}",
        f"  sandbox:        {manifest.sandbox}",
        f"  events:         {summary.get('event_count', 0)}",
        f"  tools:          {', '.join(summary.get('tool_names', [])) or 'none'}",
        f"  profiles:       {', '.join(summary.get('profiles', [])) or 'none'}",
        f"  child exit:     {manifest.child_exit_code}",
    ]
    print("\n".join(lines))
