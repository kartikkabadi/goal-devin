"""Minimal runtime JSON-schema validator (draft-2020-12 subset).

Behavior is intentionally aligned with the shared testkit validator so that the
same conformance corpus can be run against the Python candidate and, later, the
Rust candidate.
"""

import json
from pathlib import Path
from typing import Any


def _type_match(value: Any, expected: str | list[str]) -> bool:
    """Return True if *value* matches the JSON Schema *expected* type(s)."""
    if isinstance(expected, list):
        return any(_type_match(value, t) for t in expected)
    if expected == "object":
        return isinstance(value, dict)
    if expected == "array":
        return isinstance(value, list)
    if expected == "string":
        return isinstance(value, str)
    if expected == "integer":
        return isinstance(value, int) and not isinstance(value, bool)
    if expected == "number":
        return isinstance(value, (int, float)) and not isinstance(value, bool)
    if expected == "boolean":
        return isinstance(value, bool)
    if expected == "null":
        return value is None
    return True


def _validate(value: Any, schema: Any, path: str) -> list[str]:
    """Validate *value* against *schema* at *path*."""
    errors: list[str] = []
    if not isinstance(schema, dict):
        return errors

    if "type" in schema and not _type_match(value, schema["type"]):
        expected = schema["type"]
        got = type(value).__name__
        errors.append(f"{path}: expected {expected}, got {got}")
        return errors

    if "enum" in schema and value not in schema["enum"]:
        errors.append(f"{path}: expected one of {schema['enum']}")

    if "const" in schema and value != schema["const"]:
        errors.append(f"{path}: expected {schema['const']}")

    if "minLength" in schema and isinstance(value, str) and len(value) < schema["minLength"]:
        errors.append(f"{path}: length < {schema['minLength']}")

    if (
        "minimum" in schema
        and isinstance(value, (int, float))
        and not isinstance(value, bool)
        and value < schema["minimum"]
    ):
        errors.append(f"{path}: value < {schema['minimum']}")

    if (
        "maximum" in schema
        and isinstance(value, (int, float))
        and not isinstance(value, bool)
        and value > schema["maximum"]
    ):
        errors.append(f"{path}: value > {schema['maximum']}")

    if isinstance(value, dict):
        if "required" in schema:
            for key in schema["required"]:
                if key not in value:
                    errors.append(f"{path}: missing required key {key!r}")

        properties = schema.get("properties", {})
        for key, sub_schema in properties.items():
            if key in value:
                errors.extend(_validate(value[key], sub_schema, f"{path}.{key}"))

        additional = schema.get("additionalProperties", True)
        if additional is False:
            allowed = set(properties.keys())
            for key in value:
                if key not in allowed:
                    errors.append(f"{path}: additional property {key!r} not allowed")
        elif isinstance(additional, dict):
            for key in value:
                if key not in properties:
                    errors.extend(_validate(value[key], additional, f"{path}.{key}"))

    if isinstance(value, list) and "items" in schema:
        for i, item in enumerate(value):
            errors.extend(_validate(item, schema["items"], f"{path}[{i}]"))

    return errors


_SCHEMA_KEYWORDS = {
    "type",
    "enum",
    "const",
    "properties",
    "required",
    "additionalProperties",
    "items",
    "minimum",
    "maximum",
    "exclusiveMinimum",
    "exclusiveMaximum",
    "minLength",
    "maxLength",
    "multipleOf",
    "pattern",
    "uniqueItems",
    "minItems",
    "maxItems",
}


def validate(value: Any, schema: Any) -> list[str]:
    """Validate *value* against *schema*. Returns a list of error messages."""
    if (
        not isinstance(schema, dict)
        or not schema
        or not any(key in _SCHEMA_KEYWORDS for key in schema)
    ):
        return ["schema is not a valid JSON Schema object"]
    return _validate(value, schema, "$")


def validate_file(value: Any, schema_path: Path) -> list[str]:
    """Load a JSON schema from *schema_path* and validate *value*."""
    schema = json.loads(schema_path.read_text(encoding="utf-8"))
    return validate(value, schema)
