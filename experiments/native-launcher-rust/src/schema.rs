use serde_json::Value;
use std::collections::HashSet;
use std::path::Path;

const KEYWORDS: &[&str] = &[
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
];

fn schema_is_valid(schema: &Value) -> bool {
    if !schema.is_object() {
        return false;
    }
    let obj = schema.as_object().unwrap();
    if obj.is_empty() {
        return false;
    }
    obj.keys().any(|k| KEYWORDS.contains(&k.as_str()))
}

fn type_matches(value: &Value, expected: &str) -> bool {
    match expected {
        "object" => value.is_object(),
        "array" => value.is_array(),
        "string" => value.is_string(),
        "integer" => value.is_i64() || value.is_u64(),
        "number" => value.is_number(),
        "boolean" => value.is_boolean(),
        "null" => value.is_null(),
        _ => true,
    }
}

fn validate_value(value: &Value, schema: &Value, path: &str, errors: &mut Vec<String>) {
    if !schema_is_valid(schema) {
        return;
    }

    if let Some(t) = schema.get("type") {
        let ok = if let Some(arr) = t.as_array() {
            arr.iter()
                .filter_map(|v| v.as_str())
                .any(|s| type_matches(value, s))
        } else if let Some(s) = t.as_str() {
            type_matches(value, s)
        } else {
            true
        };
        if !ok {
            let expected = if let Some(s) = t.as_str() {
                s.to_string()
            } else {
                format!("{}", t)
            };
            errors.push(format!(
                "{}: expected {}, got {}",
                path,
                expected,
                json_type(value)
            ));
            return;
        }
    }

    if let Some(en) = schema.get("enum") {
        if let Some(arr) = en.as_array() {
            if !arr.iter().any(|v| v == value) {
                errors.push(format!("{}: expected one of {:?}", path, arr));
            }
        }
    }

    if let Some(c) = schema.get("const") {
        if c != value {
            errors.push(format!("{}: expected {}", path, c));
        }
    }

    if let Some(min) = schema.get("minLength") {
        if let (Some(n), Some(s)) = (min.as_u64(), value.as_str()) {
            if (s.len() as u64) < n {
                errors.push(format!("{}: length < {}", path, n));
            }
        }
    }

    if let Some(min) = schema.get("minimum") {
        if let Some(n) = as_f64(value) {
            if let Some(m) = as_f64(min) {
                if n < m {
                    errors.push(format!("{}: value < {}", path, m));
                }
            }
        }
    }

    if let Some(max) = schema.get("maximum") {
        if let Some(n) = as_f64(value) {
            if let Some(m) = as_f64(max) {
                if n > m {
                    errors.push(format!("{}: value > {}", path, m));
                }
            }
        }
    }

    if let Some(obj) = value.as_object() {
        if let Some(req) = schema.get("required") {
            if let Some(arr) = req.as_array() {
                for key in arr.iter().filter_map(|v| v.as_str()) {
                    if !obj.contains_key(key) {
                        errors.push(format!("{}: missing required key '{}'", path, key));
                    }
                }
            }
        }

        let props = schema.get("properties").and_then(|p| p.as_object());
        if let Some(props) = props {
            for (key, sub) in props {
                if let Some(v) = obj.get(key) {
                    validate_value(v, sub, &format!("{}.{}", path, key), errors);
                }
            }
        }

        if let Some(add) = schema.get("additionalProperties") {
            let allowed: HashSet<String> = props
                .map(|p| p.keys().cloned().collect())
                .unwrap_or_default();
            if add.is_boolean() && !add.as_bool().unwrap_or(true) {
                for key in obj.keys() {
                    if !allowed.contains(key) {
                        errors.push(format!(
                            "{}: additional property '{}' not allowed",
                            path, key
                        ));
                    }
                }
            } else if add.is_object() {
                for (key, v) in obj {
                    if !allowed.contains(key) {
                        validate_value(v, add, &format!("{}.{}", path, key), errors);
                    }
                }
            }
        }
    }

    if let Some(arr) = value.as_array() {
        if let Some(items_schema) = schema.get("items") {
            for (i, item) in arr.iter().enumerate() {
                validate_value(item, items_schema, &format!("{}[{}]", path, i), errors);
            }
        }
    }
}

fn as_f64(v: &Value) -> Option<f64> {
    if v.is_boolean() {
        return None;
    }
    v.as_f64()
        .or_else(|| v.as_i64().map(|i| i as f64))
        .or_else(|| v.as_u64().map(|i| i as f64))
}

fn json_type(value: &Value) -> &'static str {
    match value {
        Value::Object(_) => "object",
        Value::Array(_) => "array",
        Value::String(_) => "string",
        Value::Number(_) => "number",
        Value::Bool(_) => "boolean",
        Value::Null => "null",
    }
}

pub fn validate(value: &Value, schema: &Value) -> Vec<String> {
    if !schema_is_valid(schema) {
        return vec!["schema is not a valid JSON Schema object".to_string()];
    }
    let mut errors = Vec::new();
    validate_value(value, schema, "$", &mut errors);
    errors
}

pub fn validate_file(value: &Value, schema_path: &Path) -> anyhow::Result<Vec<String>> {
    let text = std::fs::read_to_string(schema_path)?;
    let schema: Value = serde_json::from_str(&text)?;
    Ok(validate(value, &schema))
}

pub fn load_schema(path: &Path) -> anyhow::Result<Value> {
    let text = std::fs::read_to_string(path)?;
    Ok(serde_json::from_str(&text)?)
}

#[cfg(test)]
mod tests {
    use super::*;
    use serde_json::json;

    #[test]
    fn validates_typed_string() {
        let schema = json!({"type": "string"});
        assert!(validate(&json!("hello"), &schema).is_empty());
        assert!(!validate(&json!(42), &schema).is_empty());
    }

    #[test]
    fn validates_required_and_properties() {
        let schema = json!({
            "type": "object",
            "required": ["name"],
            "properties": {
                "name": {"type": "string"},
                "age": {"type": "integer", "minimum": 0}
            },
            "additionalProperties": false
        });
        let good = json!({"name": "alice", "age": 30});
        assert!(validate(&good, &schema).is_empty());

        let missing = json!({"age": 30});
        let errs = validate(&missing, &schema);
        assert!(errs
            .iter()
            .any(|e| e.contains("missing required key 'name'")));

        let extra = json!({"name": "alice", "unknown": 1});
        let errs = validate(&extra, &schema);
        assert!(errs
            .iter()
            .any(|e| e.contains("additional property 'unknown' not allowed")));

        let bad_age = json!({"name": "alice", "age": -1});
        let errs = validate(&bad_age, &schema);
        assert!(errs.iter().any(|e| e.contains("value < 0")));
    }

    #[test]
    fn validates_enum_and_const() {
        let schema = json!({"enum": ["a", "b", "c"]});
        assert!(validate(&json!("b"), &schema).is_empty());
        assert!(!validate(&json!("d"), &schema).is_empty());

        let schema = json!({"const": 42});
        assert!(validate(&json!(42), &schema).is_empty());
        assert!(!validate(&json!(43), &schema).is_empty());
    }

    #[test]
    fn validates_array_items() {
        let schema = json!({
            "type": "array",
            "items": {"type": "integer"}
        });
        assert!(validate(&json!([1, 2, 3]), &schema).is_empty());
        assert!(!validate(&json!([1, "x", 3]), &schema).is_empty());
    }
}
