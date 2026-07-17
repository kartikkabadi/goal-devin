use crate::schema::{load_schema, validate};
use anyhow::{anyhow, Result};
use serde::Deserialize;
use serde_json::Value;
use std::collections::{HashMap, HashSet};
use std::path::Path;

#[derive(Debug, Clone, Copy, Deserialize)]
pub struct Limits {
    pub max_tool_name_length: usize,
    pub max_profile_length: usize,
    pub max_event_value_length: usize,
    pub max_event_json_bytes: usize,
    pub max_total_spool_bytes: usize,
    pub max_retained_event_files: usize,
    pub max_distinct_tools: usize,
    pub max_distinct_profiles: usize,
    pub max_recent_event_ids: usize,
    pub max_summary_size_bytes: usize,
}

impl Default for Limits {
    fn default() -> Self {
        Self {
            max_tool_name_length: 128,
            max_profile_length: 128,
            max_event_value_length: 256,
            max_event_json_bytes: 4096,
            max_total_spool_bytes: 1024 * 1024,
            max_retained_event_files: 100,
            max_distinct_tools: 50,
            max_distinct_profiles: 50,
            max_recent_event_ids: 20,
            max_summary_size_bytes: 64 * 1024,
        }
    }
}

const LIMITS_KEYS: [&str; 10] = [
    "max_tool_name_length",
    "max_profile_length",
    "max_event_value_length",
    "max_event_json_bytes",
    "max_total_spool_bytes",
    "max_retained_event_files",
    "max_distinct_tools",
    "max_distinct_profiles",
    "max_recent_event_ids",
    "max_summary_size_bytes",
];

fn min_tool_name_length() -> usize {
    "run_subagent".len()
}

fn min_profile_length() -> usize {
    "goal-devin-worker-".len() + 32
}

fn min_event_value_length() -> usize {
    let iso_len = "2026-07-15T00:00:00.000000+00:00".len();
    min_tool_name_length()
        .max(min_profile_length())
        .max(iso_len)
}

fn min_event_json_bytes() -> usize {
    let event = serde_json::json!({
        "schema_version": 1,
        "event": "PostToolUse",
        "tool_name": "run_subagent",
        "profile": "goal-devin-worker-".to_string() + &"0".repeat(32),
        "is_background": false,
        "success": true,
        "observed_at": "2026-07-15T00:00:00.000000+00:00"
    });
    let pretty = serde_json::to_string_pretty(&event).unwrap();
    256.max(pretty.len())
}

fn min_summary_size_bytes() -> usize {
    let summary = serde_json::json!({
        "schema_version": 1,
        "run_id": "a".repeat(32),
        "total_events": 1,
        "consumed_event_ids": Value::Array(vec![]),
        "tools": Value::Object(serde_json::Map::new()),
        "profiles": Value::Object(serde_json::Map::new()),
        "last_event": Value::Null
    });
    let compact = serde_json::to_string(&summary).unwrap();
    256.max(compact.len())
}

fn validate_limits_schema(schema: &Value) -> Result<()> {
    if !schema.is_object() {
        return Err(anyhow!("limits schema must be a JSON object"));
    }
    if schema.get("type").and_then(|v| v.as_str()) != Some("object") {
        return Err(anyhow!("limits schema must declare type 'object'"));
    }
    if schema.get("additionalProperties").and_then(|v| v.as_bool()) != Some(false) {
        return Err(anyhow!(
            "limits schema must set additionalProperties to false"
        ));
    }
    let props = schema
        .get("properties")
        .and_then(|v| v.as_object())
        .ok_or_else(|| anyhow!("limits schema properties must be an object"))?;
    let keys: HashSet<String> = props.keys().cloned().collect();
    let expected: HashSet<String> = LIMITS_KEYS.iter().map(|s| s.to_string()).collect();
    if keys != expected {
        return Err(anyhow!(
            "limits schema properties must exactly match {:?}",
            LIMITS_KEYS
        ));
    }
    let req = schema
        .get("required")
        .and_then(|v| v.as_array())
        .map(|a| a.iter().filter_map(|v| v.as_str()).collect::<HashSet<_>>())
        .unwrap_or_default();
    let expected_req: HashSet<&str> = LIMITS_KEYS.iter().copied().collect();
    if req != expected_req {
        return Err(anyhow!(
            "limits schema required fields must exactly match {:?}",
            LIMITS_KEYS
        ));
    }
    for (key, sub) in props {
        if sub.get("type").and_then(|v| v.as_str()) != Some("integer") {
            return Err(anyhow!(
                "limits schema property {} must declare type 'integer'",
                key
            ));
        }
        let min = sub.get("minimum").and_then(|v| v.as_i64()).unwrap_or(0);
        if min < 1 {
            return Err(anyhow!(
                "limits schema property {} must have minimum >= 1",
                key
            ));
        }
    }
    Ok(())
}

fn validate_limits_data(data: &Value, label: &str) -> Result<()> {
    if !data.is_object() {
        return Err(anyhow!("{} must be a JSON object", label));
    }
    let obj = data.as_object().unwrap();
    let mut type_errors = Vec::new();
    for key in LIMITS_KEYS {
        if let Some(v) = obj.get(key) {
            if v.is_boolean() || !v.is_i64() {
                type_errors.push(format!(
                    "{}.{} must be a positive integer, got {}",
                    label, key, v
                ));
            } else if v.as_i64().unwrap() < 1 {
                type_errors.push(format!("{}.{} must be >= 1, got {}", label, key, v));
            }
        }
    }
    if !type_errors.is_empty() {
        return Err(anyhow!("{}", type_errors.join("; ")));
    }

    let get = |k: &str| -> Option<i64> { obj.get(k).and_then(|v| v.as_i64()) };

    if let Some(tool) = get("max_tool_name_length") {
        let min = min_tool_name_length() as i64;
        if tool < min {
            return Err(anyhow!(
                "{}.max_tool_name_length ({}) must be >= {} to fit 'run_subagent'",
                label,
                tool,
                min
            ));
        }
    }

    if let Some(profile) = get("max_profile_length") {
        let min = min_profile_length() as i64;
        if profile < min {
            return Err(anyhow!(
                "{}.max_profile_length ({}) must be >= {} to fit the generated profile id",
                label,
                profile,
                min
            ));
        }
    }

    if let Some(value) = get("max_event_value_length") {
        let min = min_event_value_length() as i64;
        if value < min {
            return Err(anyhow!(
                "{}.max_event_value_length ({}) must be >= {}",
                label,
                value,
                min
            ));
        }
        for other_key in ["max_tool_name_length", "max_profile_length"] {
            if let Some(other) = get(other_key) {
                if value < other {
                    return Err(anyhow!(
                        "{}.max_event_value_length ({}) must be >= {} ({})",
                        label,
                        value,
                        other_key,
                        other
                    ));
                }
            }
        }
    }

    let max_field = [
        "max_tool_name_length",
        "max_profile_length",
        "max_event_value_length",
    ]
    .iter()
    .filter_map(|k| get(k))
    .max()
    .unwrap_or(0);
    let min_event = max_field.max(min_event_json_bytes() as i64);
    if let Some(event) = get("max_event_json_bytes") {
        if event < min_event {
            return Err(anyhow!(
                "{}.max_event_json_bytes ({}) must be >= {} to fit a valid event",
                label,
                event,
                min_event
            ));
        }
    }

    if let (Some(total), Some(event)) = (get("max_total_spool_bytes"), get("max_event_json_bytes"))
    {
        if total < event {
            return Err(anyhow!(
                "{}.max_total_spool_bytes ({}) must be >= max_event_json_bytes ({})",
                label,
                total,
                event
            ));
        }
    }

    let min_summary = get("max_event_json_bytes")
        .unwrap_or(0)
        .max(min_summary_size_bytes() as i64);
    if let Some(summary) = get("max_summary_size_bytes") {
        if summary < min_summary {
            return Err(anyhow!(
                "{}.max_summary_size_bytes ({}) must be >= {}",
                label,
                summary,
                min_summary
            ));
        }
    }

    if let (Some(retained), Some(recent)) =
        (get("max_retained_event_files"), get("max_recent_event_ids"))
    {
        if retained < recent {
            return Err(anyhow!(
                "{}.max_retained_event_files ({}) must be >= max_recent_event_ids ({})",
                label,
                retained,
                recent
            ));
        }
    }

    Ok(())
}

pub fn load_limits(
    path: Option<&Path>,
    schema_path: Option<&Path>,
    required: bool,
) -> Result<Limits> {
    if path.is_none() || !path.unwrap().exists() {
        if required {
            return Err(anyhow!("limits file required but missing: {:?}", path));
        }
        return Ok(Limits::default());
    }
    let path = path.unwrap();
    let raw = std::fs::read_to_string(path)?;
    let data: Value = serde_json::from_str(&raw)?;

    if let Some(sp) = schema_path {
        if sp.exists() {
            let schema = load_schema(sp)?;
            validate_limits_schema(&schema)?;
            let errors = validate(&data, &schema);
            if !errors.is_empty() {
                return Err(anyhow!(
                    "limits file invalid against schema: {}",
                    errors.join("; ")
                ));
            }
        } else if required {
            return Err(anyhow!("limits schema required but missing: {:?}", sp));
        } else {
            return Err(anyhow!("limits schema required but not provided"));
        }
    }

    validate_limits_data(&data, &path.to_string_lossy())?;

    let obj = data.as_object().unwrap();
    let map: HashMap<String, Value> = obj.iter().map(|(k, v)| (k.clone(), v.clone())).collect();
    let mut limits = Limits::default();
    macro_rules! set {
        ($field:ident) => {
            if let Some(v) = map.get(stringify!($field)).and_then(|v| v.as_i64()) {
                limits.$field = v as usize;
            }
        };
    }
    set!(max_tool_name_length);
    set!(max_profile_length);
    set!(max_event_value_length);
    set!(max_event_json_bytes);
    set!(max_total_spool_bytes);
    set!(max_retained_event_files);
    set!(max_distinct_tools);
    set!(max_distinct_profiles);
    set!(max_recent_event_ids);
    set!(max_summary_size_bytes);
    Ok(limits)
}

#[cfg(test)]
mod tests {
    use super::*;
    use serde_json::json;
    use std::io::Write;

    fn minimal_valid_limits() -> serde_json::Value {
        json!({
            "max_tool_name_length": 128,
            "max_profile_length": 128,
            "max_event_value_length": 256,
            "max_event_json_bytes": 4096,
            "max_total_spool_bytes": 1048576,
            "max_retained_event_files": 100,
            "max_distinct_tools": 50,
            "max_distinct_profiles": 50,
            "max_recent_event_ids": 20,
            "max_summary_size_bytes": 65536
        })
    }

    #[test]
    fn default_limits_are_reasonable() {
        let limits = Limits::default();
        assert!(limits.max_tool_name_length >= "run_subagent".len());
        assert!(limits.max_profile_length >= "goal-devin-worker-".len() + 32);
        assert!(limits.max_event_json_bytes >= 256);
        assert!(limits.max_total_spool_bytes >= limits.max_event_json_bytes);
        assert!(limits.max_retained_event_files >= limits.max_recent_event_ids);
    }

    #[test]
    fn rejects_invalid_tool_name_length() {
        let mut bad = minimal_valid_limits();
        bad.as_object_mut()
            .unwrap()
            .insert("max_tool_name_length".to_string(), json!(1));
        let result = validate_limits_data(&bad, "limits.json");
        assert!(result.is_err());
        let err = result.unwrap_err().to_string();
        assert!(err.contains("max_tool_name_length"));
    }

    #[test]
    fn cross_field_validation() {
        let mut data = minimal_valid_limits();
        data.as_object_mut()
            .unwrap()
            .insert("max_total_spool_bytes".to_string(), json!(100));
        data.as_object_mut()
            .unwrap()
            .insert("max_event_json_bytes".to_string(), json!(4096));
        let result = validate_limits_data(&data, "limits.json");
        assert!(result.is_err());
        let err = result.unwrap_err().to_string();
        assert!(err.contains("max_total_spool_bytes"));
    }

    #[test]
    fn load_limits_from_file() {
        let dir = tempfile::tempdir().unwrap();
        let limits_path = dir.path().join("limits.json");
        let schema_path = dir.path().join("limits.schema.json");
        let mut f = std::fs::File::create(&limits_path).unwrap();
        f.write_all(minimal_valid_limits().to_string().as_bytes())
            .unwrap();
        std::fs::write(
            &schema_path,
            r#"{
                "$schema": "https://json-schema.org/draft/2020-12/schema",
                "type": "object",
                "required": ["max_tool_name_length", "max_profile_length", "max_event_value_length", "max_event_json_bytes", "max_total_spool_bytes", "max_retained_event_files", "max_distinct_tools", "max_distinct_profiles", "max_recent_event_ids", "max_summary_size_bytes"],
                "additionalProperties": false,
                "properties": {
                    "max_tool_name_length": {"type": "integer", "minimum": 1},
                    "max_profile_length": {"type": "integer", "minimum": 1},
                    "max_event_value_length": {"type": "integer", "minimum": 1},
                    "max_event_json_bytes": {"type": "integer", "minimum": 1},
                    "max_total_spool_bytes": {"type": "integer", "minimum": 1},
                    "max_retained_event_files": {"type": "integer", "minimum": 1},
                    "max_distinct_tools": {"type": "integer", "minimum": 1},
                    "max_distinct_profiles": {"type": "integer", "minimum": 1},
                    "max_recent_event_ids": {"type": "integer", "minimum": 1},
                    "max_summary_size_bytes": {"type": "integer", "minimum": 1}
                }
            }"#,
        ).unwrap();
        let limits = load_limits(Some(&limits_path), Some(&schema_path), false).unwrap();
        assert_eq!(limits.max_tool_name_length, 128);
        assert_eq!(limits.max_event_json_bytes, 4096);
    }
}
