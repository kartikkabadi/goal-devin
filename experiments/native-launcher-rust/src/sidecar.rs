use crate::hook::sanitize_string;
use crate::limits::{load_limits, Limits};
use crate::schema::{load_schema, validate};
use crate::utils::{atomic_write, lifecycle_log, utcnow_iso};
use anyhow::{anyhow, Result};
use serde_json::{Map, Value};
use std::collections::{HashMap, HashSet};
use std::fs;
use std::io::{self, Write};
use std::os::unix::fs::MetadataExt;
use std::path::{Path, PathBuf};
use std::sync::atomic::{AtomicBool, Ordering};
use std::sync::Arc;
use std::time::Duration;

const POLL_INTERVAL_MS: u64 = 50;

pub struct Sidecar {
    runtime_dir: PathBuf,
    events_dir: PathBuf,
    summary_path: PathBuf,
    schema_path: PathBuf,
    limits: Limits,
    lifecycle_path: Option<PathBuf>,
    consumed: HashSet<String>,
    consumed_order: Vec<String>,
    total_events: u64,
    tools: HashMap<String, u64>,
    profiles: HashMap<String, u64>,
    last_event: Option<Value>,
    profile_id: Option<String>,
    canonical_event_id: Option<String>,
    running: Arc<AtomicBool>,
}

impl Sidecar {
    pub fn new(runtime_dir: PathBuf) -> Result<Self> {
        let events_dir = runtime_dir.join("events");
        let summary_path = runtime_dir.join("summary.json");
        let schema_path = runtime_dir.join("event.schema.json");
        let limits_path = runtime_dir.join("limits.json");
        let limits_schema_path = runtime_dir.join("limits.schema.json");
        let limits = load_limits(Some(&limits_path), Some(&limits_schema_path), true)?;

        let manifest_path = runtime_dir.join("manifest.json");
        let profile_id = if manifest_path.exists() {
            crate::utils::read_json(&manifest_path).ok().and_then(|v| {
                v.get("profile_id")
                    .and_then(|p| p.as_str())
                    .map(|s| s.to_string())
            })
        } else {
            None
        };

        let lifecycle_path = std::env::var_os("GOAL_DEVIN_LIFECYCLE_LOG").map(PathBuf::from);

        Ok(Self {
            runtime_dir,
            events_dir,
            summary_path,
            schema_path,
            limits,
            lifecycle_path,
            consumed: HashSet::new(),
            consumed_order: Vec::new(),
            total_events: 0,
            tools: HashMap::new(),
            profiles: HashMap::new(),
            last_event: None,
            profile_id,
            canonical_event_id: None,
            running: Arc::new(AtomicBool::new(false)),
        })
    }

    fn _lifecycle(&self, label: &str) {
        if let Some(ref p) = self.lifecycle_path {
            let _ = lifecycle_log(p, label);
        }
    }

    fn _write_pid(&self) {
        let pid_path = self.runtime_dir.join("sidecar.pid");
        let data = format!("{}\n", std::process::id());
        let _ = atomic_write(&pid_path, &data, 0o600);
    }

    fn _signal_ready(&self) {
        let ready_path = self.runtime_dir.join("sidecar-ready");
        let _ = atomic_write(&ready_path, "ready\n", 0o600);
    }

    fn _validate_event(&self, event: &Value) -> Vec<String> {
        if !self.schema_path.exists() {
            return vec!["event schema missing".to_string()];
        }
        let schema = match load_schema(&self.schema_path) {
            Ok(s) => s,
            Err(e) => return vec![format!("cannot load event schema: {}", e)],
        };
        validate(event, &schema)
    }

    fn _check_field_lengths(&self, event: &Value) -> bool {
        let limits = &self.limits;
        for key in ["event", "tool_name", "profile", "observed_at"] {
            if let Some(s) = event.get(key).and_then(|v| v.as_str()) {
                if s.len() > limits.max_event_value_length {
                    return false;
                }
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
        true
    }

    fn _add_tool(&mut self, tool: Option<&str>) {
        let limits = &self.limits;
        if let Some(tool) = tool {
            if tool == "run_subagent" {
                if !self.tools.contains_key(tool) && self.tools.len() >= limits.max_distinct_tools {
                    // Reserve a slot
                    let to_remove: Option<String> =
                        self.tools.keys().find(|k| *k != "run_subagent").cloned();
                    if let Some(k) = to_remove {
                        self.tools.remove(&k);
                    }
                }
            } else if !self.tools.contains_key(tool)
                && self.tools.len() >= limits.max_distinct_tools
            {
                return;
            }
            *self.tools.entry(tool.to_string()).or_insert(0) += 1;
        }
    }

    fn _add_profile(&mut self, profile: Option<&str>, tool: Option<&str>) {
        let limits = &self.limits;
        if let Some(profile) = profile {
            let is_worker =
                self.profile_id.as_deref() == Some(profile) && tool == Some("run_subagent");
            if !self.profiles.contains_key(profile)
                && self.profiles.len() >= limits.max_distinct_profiles
            {
                if is_worker {
                    let to_remove: Option<String> =
                        self.profiles.keys().find(|k| *k != profile).cloned();
                    if let Some(k) = to_remove {
                        self.profiles.remove(&k);
                    }
                } else {
                    return;
                }
            }
            *self.profiles.entry(profile.to_string()).or_insert(0) += 1;
        }
    }

    fn _update_summary(&self) -> Result<()> {
        let recent: Vec<Value> = self
            .consumed_order
            .iter()
            .rev()
            .take(self.limits.max_recent_event_ids)
            .rev()
            .map(|s| Value::String(s.clone()))
            .collect();

        let tools: Map<String, Value> = self
            .tools
            .iter()
            .map(|(k, v)| (k.clone(), Value::Number((*v).into())))
            .collect();
        let profiles: Map<String, Value> = self
            .profiles
            .iter()
            .map(|(k, v)| (k.clone(), Value::Number((*v).into())))
            .collect();

        let mut summary = Map::new();
        summary.insert("schema_version".to_string(), Value::Number(1.into()));
        summary.insert(
            "run_id".to_string(),
            Value::String(
                self.runtime_dir
                    .file_name()
                    .unwrap_or_default()
                    .to_string_lossy()
                    .into_owned(),
            ),
        );
        summary.insert(
            "total_events".to_string(),
            Value::Number(self.total_events.into()),
        );
        summary.insert("consumed_event_ids".to_string(), Value::Array(recent));
        summary.insert("tools".to_string(), Value::Object(tools));
        summary.insert("profiles".to_string(), Value::Object(profiles));
        summary.insert(
            "last_event".to_string(),
            self.last_event.clone().unwrap_or(Value::Null),
        );

        let mut data = serde_json::to_string_pretty(&Value::Object(summary.clone()))?;
        if data.as_bytes().len() > self.limits.max_summary_size_bytes {
            summary.insert("consumed_event_ids".to_string(), Value::Array(vec![]));
            data = serde_json::to_string_pretty(&Value::Object(summary.clone()))?;
        }
        if data.as_bytes().len() > self.limits.max_summary_size_bytes {
            summary.insert("tools".to_string(), Value::Object(Map::new()));
            data = serde_json::to_string_pretty(&Value::Object(summary.clone()))?;
        }
        if data.as_bytes().len() > self.limits.max_summary_size_bytes {
            summary.insert("profiles".to_string(), Value::Object(Map::new()));
            data = serde_json::to_string_pretty(&Value::Object(summary.clone()))?;
        }
        if data.as_bytes().len() > self.limits.max_summary_size_bytes {
            summary.insert("last_event".to_string(), Value::Null);
            data = serde_json::to_string_pretty(&Value::Object(summary.clone()))?;
        }
        if data.as_bytes().len() > self.limits.max_summary_size_bytes {
            data = serde_json::to_string(&Value::Object(summary.clone()))?;
        }
        if data.as_bytes().len() > self.limits.max_summary_size_bytes {
            return Err(anyhow!("summary cannot fit within max_summary_size_bytes"));
        }

        atomic_write(&self.summary_path, &data, 0o600)?;
        Ok(())
    }

    fn _process_file(&mut self, path: &Path) {
        let event_id = match path.file_stem().and_then(|s| s.to_str()) {
            Some(s) => s.to_string(),
            None => return,
        };
        if path.extension().and_then(|s| s.to_str()) != Some("json") {
            return;
        }
        if self.consumed.contains(&event_id) {
            return;
        }

        let data = match fs::read(path) {
            Ok(d) => d,
            Err(_) => return,
        };

        if data.len() > self.limits.max_event_json_bytes {
            let _ = fs::remove_file(path);
            return;
        }

        let event: Value = match serde_json::from_slice(&data) {
            Ok(v) => v,
            Err(_) => {
                let _ = fs::remove_file(path);
                return;
            }
        };

        if !self._check_field_lengths(&event) {
            let _ = fs::remove_file(path);
            return;
        }

        let errors = self._validate_event(&event);
        if !errors.is_empty() {
            let _ = fs::remove_file(path);
            return;
        }

        self.consumed.insert(event_id.clone());
        self.consumed_order.push(event_id.clone());
        self.total_events += 1;

        let tool = event
            .get("tool_name")
            .and_then(|v| v.as_str())
            .map(|s| sanitize_string(s, self.limits.max_tool_name_length));
        let profile = event
            .get("profile")
            .and_then(|v| v.as_str())
            .map(|s| sanitize_string(s, self.limits.max_profile_length));

        self._add_tool(tool.as_deref());
        self._add_profile(profile.as_deref(), tool.as_deref());

        if event.get("event").and_then(|v| v.as_str()) == Some("PostToolUse")
            && event.get("success").and_then(|v| v.as_bool()) == Some(true)
            && tool.as_deref() == Some("run_subagent")
            && profile.as_deref() == self.profile_id.as_deref()
        {
            self.canonical_event_id = Some(event_id.clone());
        }

        let mut last = Map::new();
        last.insert(
            "tool_name".to_string(),
            tool.map(Value::String).unwrap_or(Value::Null),
        );
        last.insert(
            "profile".to_string(),
            profile.map(Value::String).unwrap_or(Value::Null),
        );
        last.insert(
            "is_background".to_string(),
            event.get("is_background").cloned().unwrap_or(Value::Null),
        );
        last.insert(
            "success".to_string(),
            event.get("success").cloned().unwrap_or(Value::Null),
        );
        last.insert(
            "observed_at".to_string(),
            event
                .get("observed_at")
                .and_then(|v| v.as_str())
                .map(|s| sanitize_string(s, self.limits.max_event_value_length))
                .map(Value::String)
                .unwrap_or_else(|| Value::String(utcnow_iso())),
        );
        self.last_event = Some(Value::Object(last));

        let _ = self._update_summary();
    }

    fn _trim_spool(&mut self) {
        let mut entries: Vec<(PathBuf, u64, u64)> = Vec::new();
        if let Ok(iter) = fs::read_dir(&self.events_dir) {
            for entry in iter.flatten() {
                let p = entry.path();
                if p.extension().and_then(|s| s.to_str()) != Some("json") {
                    continue;
                }
                if let Ok(meta) = entry.metadata() {
                    if !meta.is_file() {
                        continue;
                    }
                    let mtime = meta.mtime() as u64;
                    let size = meta.size();
                    entries.push((p, size, mtime));
                }
            }
        }
        if entries.is_empty() {
            return;
        }

        entries.sort_by(|a, b| a.2.cmp(&b.2));
        let mut total: u64 = entries.iter().map(|e| e.1).sum();

        while entries.len() > self.limits.max_retained_event_files
            || total > self.limits.max_total_spool_bytes as u64
        {
            let mut removed = false;
            for i in 0..entries.len() {
                let (p, size, _) = &entries[i];
                let stem = p.file_stem().and_then(|s| s.to_str()).unwrap_or("");
                if self.canonical_event_id.as_deref() == Some(stem) {
                    continue;
                }
                if self.consumed.contains(stem) && p.exists() && fs::remove_file(p).is_ok() {
                    self.consumed.remove(stem);
                    self.consumed_order.retain(|s| s != stem);
                    total -= size;
                    entries.remove(i);
                    removed = true;
                    break;
                }
            }
            if !removed {
                break;
            }
        }
    }

    fn _drain(&mut self) {
        if let Ok(iter) = fs::read_dir(&self.events_dir) {
            for entry in iter.flatten() {
                let p = entry.path();
                if p.is_file() {
                    self._process_file(&p);
                }
            }
        }
        self._trim_spool();
    }

    pub fn run(&mut self) -> i32 {
        if fs::create_dir_all(&self.events_dir).is_err() {
            return 1;
        }
        let _ = self._update_summary();
        self._write_pid();
        self._lifecycle("sidecar_start");
        self._signal_ready();

        let running = Arc::clone(&self.running);
        let term_id =
            signal_hook::flag::register(signal_hook::consts::SIGTERM, Arc::clone(&running));
        if let Err(e) = &term_id {
            self._lifecycle(&format!("sigterm_register_failed:{}", e));
        }
        let int_id = signal_hook::flag::register(signal_hook::consts::SIGINT, Arc::clone(&running));
        if let Err(e) = &int_id {
            self._lifecycle(&format!("sigint_register_failed:{}", e));
        }

        while !running.load(Ordering::Relaxed) {
            self._drain();
            std::thread::sleep(Duration::from_millis(POLL_INTERVAL_MS));
        }

        self._drain();
        let _ = self._update_summary();
        self._lifecycle("sidecar_stop");
        0
    }
}

pub fn run(runtime_dir: PathBuf) -> i32 {
    match Sidecar::new(runtime_dir) {
        Ok(mut sidecar) => sidecar.run(),
        Err(e) => {
            let _ = writeln!(io::stderr(), "sidecar: cannot initialize: {}", e);
            1
        }
    }
}
