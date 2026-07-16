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


# Absolute minimum size for a valid event JSON and summary JSON with a 32-hex
# run_id after every trimmable field has been dropped.  These are used to reject
# semantically impossible limit values (e.g. all sizes set to 1).
_MIN_EVENT_JSON = json.dumps(
    {
        "schema_version": 1,
        "event": "X",
        "tool_name": "X",
        "profile": "X",
        "is_background": False,
        "success": True,
        "observed_at": "X",
    },
    separators=(",", ":"),
).encode("utf-8")
MIN_EVENT_JSON_BYTES = len(_MIN_EVENT_JSON)

_MIN_SUMMARY_JSON = json.dumps(
    {
        "schema_version": 1,
        "run_id": "a" * 32,
        "total_events": 1,
        "consumed_event_ids": [],
        "tools": {},
        "profiles": {},
        "last_event": None,
    },
    separators=(",", ":"),
).encode("utf-8")
MIN_SUMMARY_SIZE_BYTES = len(_MIN_SUMMARY_JSON)


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


_LIMITS_KEYS = set(Limits.__dataclass_fields__.keys())


def _validate_limits_schema(schema: Any) -> None:
    """Require the parsed limits schema to be a closed object with exactly the
    expected keys and integer minimum-1 property definitions."""
    if not isinstance(schema, dict):
        raise ValueError("limits schema must be a JSON object")
    if schema.get("type") != "object":
        raise ValueError("limits schema must declare type 'object'")
    if schema.get("additionalProperties") is not False:
        raise ValueError("limits schema must set additionalProperties to false")
    properties = schema.get("properties")
    if not isinstance(properties, dict) or set(properties.keys()) != _LIMITS_KEYS:
        raise ValueError(f"limits schema properties must exactly match {sorted(_LIMITS_KEYS)}")
    required = set(schema.get("required", []))
    if required != _LIMITS_KEYS:
        raise ValueError(f"limits schema required fields must exactly match {sorted(_LIMITS_KEYS)}")
    for key, sub in properties.items():
        if not isinstance(sub, dict) or sub.get("type") != "integer":
            raise ValueError(f"limits schema property {key} must declare type 'integer'")
        minimum = sub.get("minimum")
        if not isinstance(minimum, int) or minimum < 1:
            raise ValueError(f"limits schema property {key} must have minimum >= 1")


def _cross_field_errors(data: dict[str, Any], label: str = "limits") -> list[str]:
    """Enforce necessary relationships between limit values, including the
    absolute minimum serialized sizes for a valid event and a trimmed summary."""
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
    min_event = max(max_field, MIN_EVENT_JSON_BYTES)
    if isinstance(event, int) and event < min_event:
        errors.append(
            f"{label}.max_event_json_bytes ({event}) must be >= {min_event} to fit a valid event"
        )
    if isinstance(total, int) and isinstance(event, int) and total < event:
        errors.append(
            f"{label}.max_total_spool_bytes ({total}) must be >= max_event_json_bytes ({event})"
        )
    min_summary = max(MIN_SUMMARY_SIZE_BYTES, event if isinstance(event, int) else 0)
    if isinstance(summary, int) and isinstance(event, int) and summary < min_summary:
        errors.append(
            f"{label}.max_summary_size_bytes ({summary}) must be >= {min_summary} to fit a valid summary"
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
        _validate_limits_schema(schema)
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

    A present, valid, closed ``expected/limits.schema.json`` is required whenever
    a limits file is actually loaded.  If *required* is true, a missing limits
    file or a missing/invalid schema raises an exception.
    """
    if path is None or not path.is_file():
        if required:
            raise FileNotFoundError(f"limits file required but missing: {path}")
        return Limits()

    try:
        raw = path.read_bytes()
    except OSError as exc:
        raise ValueError(f"cannot read limits file {path}: {exc}") from exc

    try:
        data = json.loads(raw.decode("utf-8"))
    except (json.JSONDecodeError, UnicodeDecodeError) as exc:
        raise ValueError(f"limits file is not valid JSON: {exc}") from exc

    schema: dict[str, Any] | None = None
    if schema_path is not None and schema_path.is_file():
        try:
            schema_text = schema_path.read_text(encoding="utf-8")
        except OSError as exc:
            raise ValueError(f"cannot read limits schema {schema_path}: {exc}") from exc
        try:
            schema = json.loads(schema_text)
        except (json.JSONDecodeError, UnicodeDecodeError) as exc:
            raise ValueError(f"limits schema is not valid JSON: {exc}") from exc
    elif schema_path is not None:
        raise FileNotFoundError(f"limits schema required but missing: {schema_path}")
    elif required:
        raise FileNotFoundError("limits schema required but not provided")

    validate_limits(data, schema, label=str(path))

    filtered = {k: v for k, v in data.items() if k in Limits.__dataclass_fields__}
    return Limits(**filtered)
