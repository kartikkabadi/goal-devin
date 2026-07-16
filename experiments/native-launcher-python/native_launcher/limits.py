"""Language-neutral runtime limits for the native launcher.

The canonical values live in ``experiments/native-launcher-testkit/limits.json`` so
that both the Python candidate and the future Rust candidate can read the same
configuration.  This module validates and loads the shared limits file and
provides a typed fallback for runs where the file is missing.
"""

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .schema import validate


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


def _cross_field_errors(data: dict[str, Any], label: str = "limits") -> list[str]:
    """Enforce necessary relationships between limit values."""
    errors: list[str] = []
    tool = data.get("max_tool_name_length")
    profile = data.get("max_profile_length")
    value = data.get("max_event_value_length")
    event = data.get("max_event_json_bytes")
    total = data.get("max_total_spool_bytes")
    retained = data.get("max_retained_event_files")
    recent = data.get("max_recent_event_ids")
    summary = data.get("max_summary_size_bytes")

    max_field = max((v for v in (tool, profile, value) if isinstance(v, int)), default=0)
    if isinstance(event, int) and isinstance(max_field, int) and event < max_field:
        errors.append(
            f"{label}.max_event_json_bytes ({event}) must be >= largest field limit ({max_field})"
        )
    if isinstance(total, int) and isinstance(event, int) and total < event:
        errors.append(
            f"{label}.max_total_spool_bytes ({total}) must be >= max_event_json_bytes ({event})"
        )
    if isinstance(summary, int) and isinstance(event, int) and summary < event:
        errors.append(
            f"{label}.max_summary_size_bytes ({summary}) must be >= max_event_json_bytes ({event})"
        )
    if isinstance(retained, int) and isinstance(recent, int) and retained < recent:
        errors.append(
            f"{label}.max_retained_event_files ({retained}) must be >= max_recent_event_ids ({recent})"
        )
    return errors


def validate_limits(data: Any, schema: dict[str, Any] | None = None, label: str = "limits") -> None:
    """Validate that *data* is a well-formed limits object.

    If *schema* is provided, it must be a parsed JSON Schema object and is used
    to check types, required keys, and positive-integer bounds.  Cross-field
    constraints are always checked in Python so they can be expressed clearly.
    """
    if not isinstance(data, dict):
        raise ValueError(f"{label} must be a JSON object, got {type(data).__name__}")
    type_errors: list[str] = []
    for key, value in data.items():
        if key not in Limits.__dataclass_fields__:
            continue
        if isinstance(value, bool) or not isinstance(value, int):
            type_errors.append(
                f"{label}.{key} must be a positive integer, got {type(value).__name__}"
            )
        elif value < 1:
            type_errors.append(f"{label}.{key} must be >= 1, got {value}")
    if type_errors:
        raise ValueError("; ".join(type_errors))
    if schema is not None:
        schema_errors = validate(data, schema)
        if schema_errors:
            raise ValueError("; ".join(schema_errors))
    cross = _cross_field_errors(data, label=label)
    if cross:
        raise ValueError("; ".join(cross))


def load_limits(
    path: Path | None = None,
    schema_path: Path | None = None,
    required: bool = False,
) -> Limits:
    """Load limits from *path* or return the default set.

    If *required* is true, a missing or invalid limits file raises an exception.
    If *schema_path* is provided, the loaded data is validated against the schema
    and cross-field constraints.
    """
    if path is None or not path.is_file():
        if required:
            raise FileNotFoundError(f"limits file required but missing: {path}")
        return Limits()

    try:
        raw = path.read_bytes()
    except OSError as exc:
        if required:
            raise ValueError(f"cannot read limits file {path}: {exc}") from exc
        return Limits()

    try:
        data = json.loads(raw.decode("utf-8"))
    except (json.JSONDecodeError, UnicodeDecodeError) as exc:
        if required:
            raise ValueError(f"limits file is not valid JSON: {exc}") from exc
        return Limits()

    schema: dict[str, Any] | None = None
    if schema_path is not None and schema_path.is_file():
        try:
            schema = json.loads(schema_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            pass

    if required or schema is not None:
        validate_limits(data, schema, label=str(path))
    else:
        # Even without a schema, run cross-field checks so malformed defaults do
        # not silently disable caps (e.g. max_recent_event_ids: 0).
        try:
            validate_limits(data, None, label=str(path))
        except ValueError:
            if required:
                raise
            return Limits()

    filtered = {k: v for k, v in data.items() if k in Limits.__dataclass_fields__}
    return Limits(**filtered)
