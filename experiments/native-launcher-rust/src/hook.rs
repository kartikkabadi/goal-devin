use crate::limits::{load_limits, Limits};
use crate::utils::{atomic_write, random_id, utcnow_iso};
use serde_json::{Map, Value};
use std::fs;
use std::io::{self, Read};
use std::path::{Path, PathBuf};

const MAX_STDIN_BYTES: usize = 1024 * 1024;

pub(crate) fn sanitize_string(s: &str, max_len: usize) -> String {
    s.chars()
        .take(max_len)
        .map(|c| if c.is_control() { ' ' } else { c })
        .collect()
}

fn event_within_limits(event: &Value, limits: &Limits) -> bool {
    if let Ok(s) = serde_json::to_string(event) {
        if s.as_bytes().len() > limits.max_event_json_bytes {
            return false;
        }
    }
    if let Some(s) = event.get("tool_name").and_then(|v| v.as_str()) {
        if s.len() > limits.max_tool_name_length {
            return false;
        }
    }
    if let Some(s) = event.get("profile").and_then(|v| v.as_str()) {
        if s.len() > limits.max_profile_length {
            return false;
        }
    }
    if let Some(s) = event.get("observed_at").and_then(|v| v.as_str()) {
        if s.len() > limits.max_event_value_length {
            return false;
        }
    }
    true
}

pub fn extract_event(payload: &Value, limits: &Limits) -> Option<Value> {
    let mut obj = Map::new();
    obj.insert("schema_version".to_string(), Value::Number(1.into()));

    let hook_name = payload
        .get("hook_event_name")
        .and_then(|v| v.as_str())
        .unwrap_or("PreToolUse");
    let hook_event = sanitize_string(hook_name, limits.max_event_value_length);
    let allowed = ["PreToolUse", "PostToolUse", "SessionStart", "SessionEnd"];
    if !allowed.contains(&hook_event.as_str()) {
        return None;
    }
    obj.insert("event".to_string(), Value::String(hook_event.clone()));

    let tool_name = payload.get("tool_name").and_then(|v| v.as_str());
    let tool_name = tool_name.map(|s| sanitize_string(s, limits.max_tool_name_length));

    let mut profile: Option<String> = None;
    let mut is_background = false;
    if let Some(input) = payload.get("tool_input").and_then(|v| v.as_object()) {
        if let Some(p) = input.get("profile").and_then(|v| v.as_str()) {
            profile = Some(sanitize_string(p, limits.max_profile_length));
        }
        if let Some(b) = input.get("is_background").and_then(|v| v.as_bool()) {
            is_background = b;
        }
    }

    let mut success: Option<bool> = None;
    if hook_event == "PostToolUse" {
        if let Some(resp) = payload.get("tool_response").and_then(|v| v.as_object()) {
            if let Some(s) = resp.get("success").and_then(|v| v.as_bool()) {
                success = Some(s);
            }
        }
    }

    obj.insert(
        "tool_name".to_string(),
        tool_name.map(Value::String).unwrap_or(Value::Null),
    );
    obj.insert(
        "profile".to_string(),
        profile.map(Value::String).unwrap_or(Value::Null),
    );
    obj.insert("is_background".to_string(), Value::Bool(is_background));
    obj.insert(
        "success".to_string(),
        success.map(Value::Bool).unwrap_or(Value::Null),
    );
    obj.insert("observed_at".to_string(), Value::String(utcnow_iso()));

    let event = Value::Object(obj);
    if event_within_limits(&event, limits) {
        Some(event)
    } else {
        None
    }
}

fn load_limits_for_events(events_dir: &Path) -> Limits {
    if let Some(runtime_dir) = events_dir.parent() {
        let limits_path = runtime_dir.join("limits.json");
        let limits_schema_path = runtime_dir.join("limits.schema.json");
        if limits_path.exists() {
            if let Ok(l) = load_limits(Some(&limits_path), Some(&limits_schema_path), true) {
                return l;
            }
        }
    }
    Limits::default()
}

pub fn run_hook(events_dir: &Path, limits: &Limits) -> i32 {
    let mut stdin = Vec::new();
    if io::stdin()
        .take(MAX_STDIN_BYTES as u64)
        .read_to_end(&mut stdin)
        .is_err()
    {
        return 0;
    }
    if stdin.len() >= MAX_STDIN_BYTES {
        return 0;
    }
    let payload: Value = match serde_json::from_slice(&stdin) {
        Ok(v) => v,
        Err(_) => return 0,
    };
    let event = match extract_event(&payload, limits) {
        Some(e) => e,
        None => return 0,
    };

    let event_id = random_id(16);
    let event_path = events_dir.join(format!("{}.json", event_id));
    if !events_dir.exists() && fs::create_dir_all(events_dir).is_err() {
        return 0;
    }
    let data = match serde_json::to_string(&event) {
        Ok(d) => d,
        Err(_) => return 0,
    };
    if atomic_write(&event_path, &data, 0o600).is_err() {
        return 0;
    }
    0
}

pub fn run(events_dir_arg: Option<PathBuf>) -> i32 {
    let events_dir = events_dir_arg
        .or_else(|| std::env::var_os("GOAL_DEVIN_EVENTS_DIR").map(PathBuf::from))
        .unwrap_or_else(|| PathBuf::from("."));
    let limits = load_limits_for_events(&events_dir);
    run_hook(&events_dir, &limits)
}

#[cfg(test)]
mod tests {
    use super::*;
    use serde_json::json;

    #[test]
    fn extract_event_sanitizes_basic_post_tool_use() {
        let payload = json!({
            "hook_event_name": "PostToolUse",
            "tool_name": "run_subagent",
            "tool_input": {
                "profile": "goal-devin-worker-abc123",
                "is_background": false
            },
            "tool_response": {
                "success": true
            }
        });
        let limits = Limits::default();
        let event = extract_event(&payload, &limits).unwrap();
        assert_eq!(event.get("event").unwrap().as_str().unwrap(), "PostToolUse");
        assert_eq!(
            event.get("tool_name").unwrap().as_str().unwrap(),
            "run_subagent"
        );
        assert_eq!(
            event.get("profile").unwrap().as_str().unwrap(),
            "goal-devin-worker-abc123"
        );
        assert!(event.get("success").unwrap().as_bool().unwrap());
        assert!(event.get("observed_at").is_some());
    }

    #[test]
    fn extract_event_rejects_unknown_event() {
        let payload = json!({"hook_event_name": "BadEvent"});
        let limits = Limits::default();
        assert!(extract_event(&payload, &limits).is_none());
    }

    #[test]
    fn extract_event_strips_control_chars_and_truncates() {
        let long = "a".repeat(1000);
        let payload = json!({
            "hook_event_name": "PostToolUse",
            "tool_name": &long,
        });
        let limits = Limits::default();
        let event = extract_event(&payload, &limits).unwrap();
        let tool = event.get("tool_name").unwrap().as_str().unwrap();
        assert!(tool.len() <= limits.max_tool_name_length);
        assert!(!tool.contains('\n'));
    }

    #[test]
    fn extract_event_sanitizes_adversarial_terminal_controls() {
        // ANSI clear-screen and xterm title sequences embedded in tool_name.
        let adversarial = "\u{001b}[2J\u{001b}]0;owned\u{0007}\nsubagent";
        let payload = json!({
            "hook_event_name": "PostToolUse",
            "tool_name": adversarial,
        });
        let limits = Limits::default();
        let event = extract_event(&payload, &limits).unwrap();
        let tool = event.get("tool_name").unwrap().as_str().unwrap();
        assert!(!tool.contains('\u{001b}'));
        assert!(!tool.contains('\n'));
        assert!(!tool.contains('\u{0007}'));
    }
}
