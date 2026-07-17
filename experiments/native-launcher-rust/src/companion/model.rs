use chrono::{DateTime, Utc};
use serde::{Deserialize, Serialize};

const MAX_WARNINGS: usize = 10;
const MAX_WARNING_LEN: usize = 200;

fn sanitize_string(s: &mut String, max_len: usize) {
    *s = s
        .chars()
        .map(|c| if c.is_control() { ' ' } else { c })
        .take(max_len)
        .collect();
}

#[derive(Clone, Debug, Default, PartialEq, Eq, Serialize, Deserialize)]
pub enum RunState {
    #[default]
    Initializing,
    PreparingRuntime,
    InstallingHook,
    CreatingProfile,
    StartingSidecar,
    LaunchingDevin,
    DevinActive,
    CleaningUp,
    Complete,
    Warning,
    Failed,
}

impl RunState {
    pub fn label(&self) -> &'static str {
        match self {
            RunState::Initializing => "initializing",
            RunState::PreparingRuntime => "preparing runtime",
            RunState::InstallingHook => "installing hook",
            RunState::CreatingProfile => "creating worker profile",
            RunState::StartingSidecar => "starting sidecar",
            RunState::LaunchingDevin => "launching Devin",
            RunState::DevinActive => "Devin active",
            RunState::CleaningUp => "cleaning up",
            RunState::Complete => "complete",
            RunState::Warning => "warning",
            RunState::Failed => "failed",
        }
    }

    pub fn is_terminal(&self) -> bool {
        matches!(self, RunState::Complete | RunState::Failed)
    }
}

#[derive(Clone, Debug, Default, PartialEq, Eq, Serialize, Deserialize)]
pub struct CompanionState {
    pub schema_version: i32,
    pub run_state: RunState,
    pub model: String,
    pub permission_mode: String,
    pub profile_id: String,
    pub sidecar_healthy: bool,
    pub event_count: u64,
    pub last_event_type: String,
    pub lifecycle_phase: String,
    pub warnings: Vec<String>,
    pub started_at: Option<DateTime<Utc>>,
    pub updated_at: Option<DateTime<Utc>>,
    pub finished: bool,
    pub devin_returncode: Option<i32>,
}

impl CompanionState {
    pub fn new() -> Self {
        Self {
            schema_version: 1,
            run_state: RunState::Initializing,
            model: String::new(),
            permission_mode: String::new(),
            profile_id: String::new(),
            sidecar_healthy: false,
            event_count: 0,
            last_event_type: String::new(),
            lifecycle_phase: String::new(),
            warnings: Vec::new(),
            started_at: None,
            updated_at: None,
            finished: false,
            devin_returncode: None,
        }
    }

    pub fn sanitize(&mut self) {
        sanitize_string(&mut self.model, 64);
        sanitize_string(&mut self.permission_mode, 32);
        sanitize_string(&mut self.profile_id, 64);
        sanitize_string(&mut self.last_event_type, 64);
        sanitize_string(&mut self.lifecycle_phase, 64);
        self.warnings.retain(|w| !w.is_empty());
        self.warnings.truncate(MAX_WARNINGS);
        for w in &mut self.warnings {
            sanitize_string(w, MAX_WARNING_LEN);
        }
    }

    pub fn short_profile_id(&self) -> String {
        if self.profile_id.is_empty() {
            return String::from("—");
        }
        if self.profile_id.len() > 24 {
            format!("{}…", &self.profile_id[..24])
        } else {
            self.profile_id.clone()
        }
    }

    pub fn elapsed_since_start(&self) -> String {
        let Some(started) = self.started_at else {
            return String::from("—");
        };
        let duration = Utc::now().signed_duration_since(started);
        let secs = duration.num_seconds().max(0);
        format!(
            "{:02}:{:02}:{:02}",
            secs / 3600,
            (secs % 3600) / 60,
            secs % 60
        )
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn sanitize_truncates_and_strips_control() {
        let mut state = CompanionState::new();
        state.warnings = vec!["ok".to_string(), "bad\nline".to_string(), "x".repeat(300)];
        state.sanitize();
        assert_eq!(state.warnings.len(), 3);
        assert!(!state.warnings[1].contains('\n'));
        assert!(state.warnings[2].len() <= 200);
    }

    #[test]
    fn short_profile_id_caps_length() {
        let mut state = CompanionState::new();
        state.profile_id = "a".repeat(50);
        let short = state.short_profile_id();
        assert!(short.chars().count() <= 25);
        assert!(short.ends_with('…'));
    }

    #[test]
    fn elapsed_before_start_is_dash() {
        let state = CompanionState::new();
        assert_eq!(state.elapsed_since_start(), "—");
    }
}
