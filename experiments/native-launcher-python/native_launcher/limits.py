"""Language-neutral runtime limits for the native launcher.

The canonical values live in ``experiments/native-launcher-testkit/limits.json`` so
that both the Python candidate and the future Rust candidate can read the same
configuration.  This module provides a typed fallback for runs where the file is
not present.
"""

import json
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class Limits:
    max_tool_name_length: int = 128
    max_profile_length: int = 128
    max_event_value_length: int = 256
    max_event_json_bytes: int = 4096
    max_total_spool_bytes: int = 1024 * 1024
    max_retained_event_files: int = 100
    max_distinct_tools: int = 50
    max_distinct_profiles: int = 50
    max_recent_event_ids: int = 20
    max_summary_size_bytes: int = 64 * 1024


def load_limits(path: Path | None = None) -> Limits:
    """Load limits from *path* or return the default set."""
    if path is not None and path.is_file():
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            return Limits(**{k: v for k, v in data.items() if k in Limits.__dataclass_fields__})
        except (OSError, json.JSONDecodeError, TypeError, ValueError):
            pass
    return Limits()
