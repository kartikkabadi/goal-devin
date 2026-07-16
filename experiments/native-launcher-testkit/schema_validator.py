"""Minimal JSON-schema validator for the shared testkit.

Supports a subset of JSON Schema needed by the R1A.1 contracts:
type, required, properties, additionalProperties, enum, const, items,
minLength, minimum, maximum.
"""

import json
from pathlib import Path
from typing import Any


def _type_match(value: Any, expected: str | list[str]) -> bool:
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


def _validate(value: Any, schema: Any, path: str, errors: list[str]) -> None:
    if not isinstance(schema, dict):
        return

    if "type" in schema and not _type_match(value, schema["type"]):
        errors.append(f"{path}: expected {schema['type']}, got {type(value).__name__}")
        return

    if "enum" in schema and value not in schema["enum"]:
        errors.append(f"{path}: expected one of {schema['enum']}")

    if "const" in schema and value != schema["const"]:
        errors.append(f"{path}: expected {schema['const']}")

    if "minLength" in schema and isinstance(value, str) and len(value) < schema["minLength"]:
        errors.append(f"{path}: length < {schema['minLength']}")

    if "minimum" in schema and isinstance(value, (int, float)) and value < schema["minimum"]:
        errors.append(f"{path}: value < {schema['minimum']}")

    if "maximum" in schema and isinstance(value, (int, float)) and value > schema["maximum"]:
        errors.append(f"{path}: value > {schema['maximum']}")

    if isinstance(value, dict):
        if "required" in schema:
            for key in schema["required"]:
                if key not in value:
                    errors.append(f"{path}: missing required key {key!r}")

        properties = schema.get("properties", {})
        for key, sub_schema in properties.items():
            if key in value:
                _validate(value[key], sub_schema, f"{path}.{key}", errors)

        additional = schema.get("additionalProperties", True)
        if additional is False:
            allowed = set(properties.keys())
            for key in value:
                if key not in allowed:
                    errors.append(f"{path}: additional property {key!r} not allowed")
        elif isinstance(additional, dict):
            for key in value:
                if key not in properties:
                    _validate(value[key], additional, f"{path}.{key}", errors)

    if isinstance(value, list) and "items" in schema:
        for i, item in enumerate(value):
            _validate(item, schema["items"], f"{path}[{i}]", errors)


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


def _schema_is_valid(schema: Any) -> bool:
    if not isinstance(schema, dict):
        return False
    if not schema:
        return False
    if any(key in _SCHEMA_KEYWORDS for key in schema):
        return True
    return False


def validate(value: Any, schema: Any) -> list[str]:
    if not _schema_is_valid(schema):
        return ["schema is not a valid JSON Schema object"]
    errors: list[str] = []
    _validate(value, schema, "$", errors)
    return errors


def validate_file(value: Any, schema_path: str | Path) -> list[str]:
    schema = json.loads(Path(schema_path).read_text(encoding="utf-8"))
    return validate(value, schema)
