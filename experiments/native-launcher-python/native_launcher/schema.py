"""Minimal runtime JSON-schema validator (draft-2020-12 subset)."""

import json
from pathlib import Path
from typing import Any


def _check_type(value: Any, typespec: str | list[str]) -> bool:
    if isinstance(typespec, list):
        return any(_check_type(value, t) for t in typespec)
    type_map = {
        "object": dict,
        "array": list,
        "string": str,
        "integer": int,
        "number": (int, float),
        "boolean": bool,
        "null": type(None),
    }
    py_type = type_map.get(typespec)
    if py_type is None:
        return True
    return isinstance(value, py_type)


def _validate(value: Any, schema: Any, path: str = "") -> list[str]:
    errors: list[str] = []
    if isinstance(schema, bool):
        if schema is False:
            errors.append(f"{path}: additional properties not allowed")
        return errors

    if "const" in schema:
        if value != schema["const"]:
            errors.append(f"{path}: expected {schema['const']!r}, got {value!r}")
        return errors

    if "enum" in schema:
        if value not in schema["enum"]:
            errors.append(f"{path}: expected one of {schema['enum']}, got {value!r}")
        return errors

    if "type" in schema:
        if not _check_type(value, schema["type"]):
            errors.append(f"{path}: type mismatch, expected {schema['type']}")
            return errors

    if isinstance(value, dict):
        if "minProperties" in schema and len(value) < schema["minProperties"]:
            errors.append(f"{path}: too few properties")
        if "maxProperties" in schema and len(value) > schema["maxProperties"]:
            errors.append(f"{path}: too many properties")
        if "required" in schema:
            for key in schema["required"]:
                if key not in value:
                    errors.append(f"{path}: missing required property {key!r}")
        allowed_props = set()
        prop_schemas = {}
        if "properties" in schema:
            allowed_props.update(schema["properties"].keys())
            prop_schemas.update(schema["properties"])
        if "patternProperties" in schema:
            import re

            for pattern in schema["patternProperties"].keys():
                allowed_props.update(k for k in value if re.search(pattern, k))
                prop_schemas.update(
                    {
                        k: schema["patternProperties"][pattern]
                        for k in value
                        if re.search(pattern, k)
                    }
                )
        if "additionalProperties" in schema:
            add = schema["additionalProperties"]
            if add is False:
                for key in value:
                    if key not in allowed_props:
                        errors.append(f"{path}: additional property {key!r} not allowed")
            elif isinstance(add, dict):
                for key in value:
                    if key not in allowed_props:
                        errors.extend(_validate(value[key], add, f"{path}.{key}"))
        for key, val in value.items():
            if key in prop_schemas:
                errors.extend(_validate(val, prop_schemas[key], f"{path}.{key}"))

    if isinstance(value, list):
        if "minItems" in schema and len(value) < schema["minItems"]:
            errors.append(f"{path}: too few items")
        if "maxItems" in schema and len(value) > schema["maxItems"]:
            errors.append(f"{path}: too many items")
        if "items" in schema:
            for i, item in enumerate(value):
                errors.extend(_validate(item, schema["items"], f"{path}[{i}]"))

    if isinstance(value, str):
        if "minLength" in schema and len(value) < schema["minLength"]:
            errors.append(f"{path}: string too short")
        if "maxLength" in schema and len(value) > schema["maxLength"]:
            errors.append(f"{path}: string too long")

    if isinstance(value, (int, float)):
        if "minimum" in schema and value < schema["minimum"]:
            errors.append(f"{path}: value below minimum")
        if "maximum" in schema and value > schema["maximum"]:
            errors.append(f"{path}: value above maximum")

    return errors


def validate(value: Any, schema: Any) -> list[str]:
    """Validate *value* against *schema*. Returns a list of error messages."""
    return _validate(value, schema)


def validate_file(value: Any, schema_path: Path) -> list[str]:
    """Load a JSON schema from *schema_path* and validate *value*."""
    schema = json.loads(schema_path.read_text(encoding="utf-8"))
    return validate(value, schema)
