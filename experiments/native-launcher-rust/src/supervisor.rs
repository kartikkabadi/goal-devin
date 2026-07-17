use crate::companion::model::{CompanionState, RunState};
use crate::companion::transport::write_state as write_companion_state;
use crate::limits::load_limits;
use crate::manifest::build_manifest;
use crate::profile::{make_profile, make_profile_id, remove_profile};
use crate::schema::load_schema;
use crate::utils::{
    atomic_write, copy_file_with_mode, ensure_private_dir, has_symlink_component, lifecycle_log,
    random_id, safe_path_under, set_mode, shlex_quote, validate_model, validate_permission_mode,
};
use anyhow::{anyhow, Context, Result};
use chrono::{DateTime, Utc};
use serde_json::{Map, Value};
use std::fs;
use std::io::{self, Write};
use std::os::unix::fs::PermissionsExt;
use std::os::unix::process::{CommandExt, ExitStatusExt};
use std::path::PathBuf;
use std::process::{Child, Command, Stdio};
use std::sync::atomic::{AtomicBool, Ordering};
use std::sync::Arc;
use std::thread;
use std::time::{Duration, Instant};

pub struct Supervisor {
    model: String,
    permission_mode: String,
    devin_bin: PathBuf,
    contract_dir: PathBuf,
    runtime_root: PathBuf,
    canary_arg: Option<PathBuf>,
    existing_hooks: Option<PathBuf>,
    keep_canary: bool,
    companion_enabled: bool,
    companion_poll_ms: u64,
    companion_state_path: PathBuf,

    run_id: String,
    runtime_dir: PathBuf,
    canary: PathBuf,
    canary_created: bool,
    events_dir: PathBuf,
    summary_path: PathBuf,
    lifecycle_path: PathBuf,
    manifest_path: PathBuf,
    profile_id: String,
    profile_path: PathBuf,
    hook_path: PathBuf,
    hook_command: Vec<String>,
    hook_owned: bool,
    original_hooks_bytes: Option<Vec<u8>>,
    original_hooks_mode: Option<u32>,

    sidecar_proc: Option<Child>,
    devin_proc: Option<Child>,
    devin_returncode: Option<i32>,
    started_at: Option<DateTime<Utc>>,

    sigint_received: Arc<AtomicBool>,
    sigterm_received: Arc<AtomicBool>,
    signal_ids: Vec<signal_hook::SigId>,

    owned_dirs: Vec<PathBuf>,
    owned_paths: Vec<PathBuf>,

    cleaned: bool,
}

impl Drop for Supervisor {
    fn drop(&mut self) {
        if !self.cleaned {
            let _ = self.final_cleanup();
        }
    }
}

fn validate_existing_hooks_config(config: &Value) -> Result<()> {
    let obj = config
        .as_object()
        .ok_or_else(|| anyhow!("Existing hooks file must be a JSON object"))?;
    for (key, entries) in obj {
        let arr = entries
            .as_array()
            .ok_or_else(|| anyhow!("Existing hooks event {} must be a list", key))?;
        for (i, entry) in arr.iter().enumerate() {
            let e = entry
                .as_object()
                .ok_or_else(|| anyhow!("Existing hooks event {}[{}] must be an object", key, i))?;
            if let Some(m) = e.get("matcher") {
                if !m.is_string() && !m.is_null() {
                    return Err(anyhow!(
                        "Existing hooks event {}[{}].matcher must be a string or null",
                        key,
                        i
                    ));
                }
            }
            let hooks = e.get("hooks").and_then(|v| v.as_array()).ok_or_else(|| {
                anyhow!("Existing hooks event {}[{}].hooks must be a list", key, i)
            })?;
            for (j, h) in hooks.iter().enumerate() {
                if !h.is_object() {
                    return Err(anyhow!(
                        "Existing hooks event {}[{}].hooks[{}] must be an object",
                        key,
                        i,
                        j
                    ));
                }
            }
        }
    }
    Ok(())
}

fn validate_existing_hooks_data(raw: &[u8]) -> Result<Value> {
    let text = String::from_utf8(raw.to_vec()).context("Existing hooks file is not valid UTF-8")?;
    let config: Value =
        serde_json::from_str(&text).context("Existing hooks file is not valid JSON")?;
    validate_existing_hooks_config(&config)?;
    Ok(config)
}

impl Supervisor {
    pub fn new(args: crate::cli::Args) -> Result<Self> {
        validate_model(&args.model).map_err(|e| anyhow!(e))?;
        validate_permission_mode(&args.permission_mode).map_err(|e| anyhow!(e))?;

        let devin_bin = fs::canonicalize(&args.devin_bin)
            .or_else(|_| Ok::<_, anyhow::Error>(args.devin_bin.clone()))?;
        let contract_dir = fs::canonicalize(&args.contract_dir)
            .or_else(|_| Ok::<_, anyhow::Error>(args.contract_dir.clone()))?;

        let event_schema_path = contract_dir.join("expected").join("event.schema.json");
        if !event_schema_path.exists() {
            return Err(anyhow!(
                "--contract-dir must contain expected/event.schema.json: {}",
                contract_dir.display()
            ));
        }
        let schema = load_schema(&event_schema_path)?;
        if !schema.is_object() || !schema.as_object().unwrap().contains_key("properties") {
            return Err(anyhow!(
                "Invalid event schema shape: {}",
                event_schema_path.display()
            ));
        }

        let limits_path = contract_dir.join("limits.json");
        let limits_schema_path = contract_dir.join("expected").join("limits.schema.json");
        if !limits_path.exists() {
            return Err(anyhow!(
                "--contract-dir must contain limits.json: {}",
                contract_dir.display()
            ));
        }
        load_limits(Some(&limits_path), Some(&limits_schema_path), true)?;

        let runtime_root = fs::canonicalize(&args.runtime_root)
            .or_else(|_| Ok::<_, anyhow::Error>(args.runtime_root.clone()))?;

        let run_id = random_id(16);
        let runtime_dir = runtime_root.join(&run_id);

        Ok(Self {
            model: args.model,
            permission_mode: args.permission_mode,
            devin_bin,
            contract_dir,
            runtime_root,
            canary_arg: args.canary,
            existing_hooks: args.existing_hooks,
            keep_canary: args.keep_canary,
            companion_enabled: args.companion,
            companion_poll_ms: args.companion_poll_ms,
            companion_state_path: PathBuf::new(),
            run_id,
            runtime_dir,
            canary: PathBuf::new(),
            canary_created: false,
            events_dir: PathBuf::new(),
            summary_path: PathBuf::new(),
            lifecycle_path: PathBuf::new(),
            manifest_path: PathBuf::new(),
            profile_id: String::new(),
            profile_path: PathBuf::new(),
            hook_path: PathBuf::new(),
            hook_command: Vec::new(),
            hook_owned: false,
            original_hooks_bytes: None,
            original_hooks_mode: None,
            sidecar_proc: None,
            devin_proc: None,
            devin_returncode: None,
            started_at: None,
            sigint_received: Arc::new(AtomicBool::new(false)),
            sigterm_received: Arc::new(AtomicBool::new(false)),
            signal_ids: Vec::new(),
            owned_dirs: Vec::new(),
            owned_paths: Vec::new(),
            cleaned: false,
        })
    }

    pub fn run(mut self) -> i32 {
        let result = self.run_lifecycle();
        let _ = self.final_cleanup();
        self.cleaned = true;
        match result {
            Ok(code) => code,
            Err(e) => {
                let _ = writeln!(io::stderr(), "goal-devin-dev: {}", e);
                self.devin_returncode.unwrap_or(1)
            }
        }
    }

    fn run_lifecycle(&mut self) -> Result<i32> {
        self.register_signals();

        self.create_runtime_dirs()?;
        self.update_companion_state(RunState::PreparingRuntime, "setup");
        self.copy_runtime_files()?;
        self.update_companion_state(RunState::PreparingRuntime, "setup");
        self.create_canary()?;
        self.update_companion_state(RunState::PreparingRuntime, "setup");
        self.install_hook_script()?;
        self.update_companion_state(RunState::InstallingHook, "hook");
        self.create_profile()?;
        self.update_companion_state(RunState::CreatingProfile, "profile");
        self.install_canary_hook()?;
        self.update_companion_state(RunState::CreatingProfile, "profile");
        self.write_manifest()?;
        self.update_companion_state(RunState::StartingSidecar, "sidecar");
        self.start_sidecar()?;

        if self.signal_received() {
            // Abort before launching Devin; final cleanup will still run.
            return self.interrupt_return();
        }

        self.update_companion_state(RunState::LaunchingDevin, "launch");
        self.print_companion_command();
        self.run_devin()?;
        self.update_companion_state(RunState::CleaningUp, "cleanup");
        self.stop_sidecar();
        self.log_lifecycle("supervisor_end");
        Ok(self.devin_returncode.unwrap_or(1))
    }

    fn register_signals(&mut self) {
        let sigint = Arc::clone(&self.sigint_received);
        if let Ok(id) = signal_hook::flag::register(signal_hook::consts::SIGINT, sigint) {
            self.signal_ids.push(id);
        }
        let sigterm = Arc::clone(&self.sigterm_received);
        if let Ok(id) = signal_hook::flag::register(signal_hook::consts::SIGTERM, sigterm) {
            self.signal_ids.push(id);
        }
    }

    fn signal_received(&self) -> bool {
        self.sigint_received.load(Ordering::Relaxed)
            || self.sigterm_received.load(Ordering::Relaxed)
    }

    fn interrupt_return(&mut self) -> Result<i32> {
        let code = if self.sigint_received.load(Ordering::Relaxed) {
            130
        } else {
            143
        };
        self.devin_returncode = Some(code);
        Ok(code)
    }

    fn create_runtime_dirs(&mut self) -> Result<()> {
        for _ in 0..10 {
            if !self.runtime_dir.exists() {
                break;
            }
            self.run_id = random_id(16);
            self.runtime_dir = self.runtime_root.join(&self.run_id);
        }
        let created = ensure_private_dir(&self.runtime_dir, 0o700, false)?;
        self.owned_dirs.extend(created);

        self.events_dir = self.runtime_dir.join("events");
        let created = ensure_private_dir(&self.events_dir, 0o700, false)?;
        self.owned_dirs.extend(created);

        self.companion_state_path = self.runtime_dir.join("companion").join("state.json");
        if self.companion_enabled {
            let _ = ensure_private_dir(self.companion_state_path.parent().unwrap(), 0o700, false);
        }

        self.summary_path = self.runtime_dir.join("summary.json");
        self.lifecycle_path = self.runtime_dir.join("lifecycle.log");

        atomic_write(
            &self.runtime_dir.join("supervisor.pid"),
            &format!("{}\n", std::process::id()),
            0o600,
        )?;
        self.owned_paths
            .push(self.runtime_dir.join("supervisor.pid"));

        self.started_at = Some(Utc::now());
        self.log_lifecycle("supervisor_start");
        Ok(())
    }

    fn copy_runtime_files(&mut self) -> Result<()> {
        let event_schema_src = self.contract_dir.join("expected").join("event.schema.json");
        if !event_schema_src.exists() {
            return Err(anyhow!("Event schema missing in contract dir"));
        }
        let event_schema_dst = self.runtime_dir.join("event.schema.json");
        copy_file_with_mode(&event_schema_src, &event_schema_dst, 0o600)?;
        self.owned_paths.push(event_schema_dst);

        let limits_src = self.contract_dir.join("limits.json");
        let limits_dst = self.runtime_dir.join("limits.json");
        copy_file_with_mode(&limits_src, &limits_dst, 0o600)?;
        self.owned_paths.push(limits_dst);

        let limits_schema_src = self
            .contract_dir
            .join("expected")
            .join("limits.schema.json");
        if limits_schema_src.exists() {
            let limits_schema_dst = self.runtime_dir.join("limits.schema.json");
            copy_file_with_mode(&limits_schema_src, &limits_schema_dst, 0o600)?;
            self.owned_paths.push(limits_schema_dst);
        }
        Ok(())
    }

    fn create_canary(&mut self) -> Result<()> {
        if let Some(ref c) = self.canary_arg {
            if !safe_path_under(&self.runtime_root, c) {
                return Err(anyhow!("canary must be inside runtime-root"));
            }
            if has_symlink_component(&self.runtime_root, c)? {
                return Err(anyhow!("canary path contains a symlink"));
            }
            self.canary = c.clone();
            let existed = self.canary.exists();
            let created = ensure_private_dir(&self.canary, 0o700, true)?;
            self.owned_dirs.extend(created);
            self.canary_created = !existed;
        } else {
            self.canary = self.runtime_dir.join("canary");
            let created = ensure_private_dir(&self.canary, 0o700, false)?;
            self.owned_dirs.extend(created);
            self.canary_created = true;
        }

        let devin_dir = self.canary.join(".devin");
        if has_symlink_component(&self.canary, &devin_dir)? {
            return Err(anyhow!("canary .devin path contains a symlink"));
        }
        let created = ensure_private_dir(&devin_dir, 0o700, true)?;
        self.owned_dirs.extend(created);

        let hooks_file = devin_dir.join("hooks.v1.json");
        if hooks_file.exists() {
            if has_symlink_component(&self.canary, &hooks_file)? {
                return Err(anyhow!("canary hooks.v1.json path contains a symlink"));
            }
            let bytes = fs::read(&hooks_file)?;
            let mode = fs::metadata(&hooks_file)?.permissions().mode() & 0o777;
            validate_existing_hooks_data(&bytes)?;
            self.original_hooks_bytes = Some(bytes);
            self.original_hooks_mode = Some(mode);
            self.hook_owned = false;
        }

        if let Some(ref src) = self.existing_hooks {
            if !src.exists() {
                return Err(anyhow!(
                    "existing-hooks fixture not found: {}",
                    src.display()
                ));
            }
            let bytes = fs::read(src)?;
            let mode = fs::metadata(src)?.permissions().mode() & 0o777;
            validate_existing_hooks_data(&bytes)?;
            fs::copy(src, &hooks_file)?;
            set_mode(&hooks_file, mode)?;
            self.original_hooks_bytes = Some(bytes);
            self.original_hooks_mode = Some(mode);
            self.hook_owned = false;
        }

        Ok(())
    }

    fn install_hook_script(&mut self) -> Result<()> {
        let exe = std::env::current_exe()?;
        let bin_dir = exe
            .parent()
            .ok_or_else(|| anyhow!("cannot determine binary directory"))?;
        let hook_src = bin_dir.join("goal-devin-hook");
        if !hook_src.exists() {
            return Err(anyhow!(
                "hook binary not found beside launcher: {}",
                hook_src.display()
            ));
        }
        let hook_dst = self.runtime_dir.join("hook");
        fs::copy(&hook_src, &hook_dst)?;
        set_mode(&hook_dst, 0o700)?;
        self.hook_path = hook_dst;
        self.hook_command = vec![
            self.hook_path.to_string_lossy().into_owned(),
            self.events_dir.to_string_lossy().into_owned(),
        ];
        self.owned_paths.push(self.hook_path.clone());
        Ok(())
    }

    fn create_profile(&mut self) -> Result<()> {
        for _ in 0..10 {
            self.profile_id = make_profile_id();
            match make_profile(&self.canary, &self.profile_id, &self.model) {
                Ok((path, created)) => {
                    self.profile_path = path;
                    self.owned_dirs.extend(created);
                    return Ok(());
                }
                Err(_) => continue,
            }
        }
        Err(anyhow!(
            "Could not create a unique profile directory after 10 attempts"
        ))
    }

    fn install_canary_hook(&mut self) -> Result<()> {
        let hooks_file = self.canary.join(".devin").join("hooks.v1.json");
        let existing_config: Value = if let Some(ref bytes) = self.original_hooks_bytes {
            validate_existing_hooks_data(bytes)?
        } else {
            Value::Object(Map::new())
        };

        let command_str = self
            .hook_command
            .iter()
            .map(|s| shlex_quote(s))
            .collect::<Vec<_>>()
            .join(" ");
        let goal_entry = serde_json::json!({
            "matcher": "",
            "hooks": [{
                "type": "command",
                "command": command_str,
                "timeout": 5,
            }]
        });

        let mut new_config = Map::new();
        for event_name in ["PreToolUse", "PostToolUse"] {
            let mut list = vec![goal_entry.clone()];
            if let Some(arr) = existing_config.get(event_name).and_then(|v| v.as_array()) {
                list.extend(arr.iter().cloned());
            }
            new_config.insert(event_name.to_string(), Value::Array(list));
        }
        if let Some(obj) = existing_config.as_object() {
            for (key, value) in obj {
                if !new_config.contains_key(key) {
                    new_config.insert(key.clone(), value.clone());
                }
            }
        }

        let data = serde_json::to_string_pretty(&Value::Object(new_config))?;
        atomic_write(&hooks_file, &data, 0o600)?;
        if self.original_hooks_bytes.is_none() {
            self.hook_owned = true;
        }
        Ok(())
    }

    fn write_manifest(&mut self) -> Result<()> {
        let extra_paths: Vec<PathBuf> = if self.companion_enabled {
            vec![self.companion_state_path.clone()]
        } else {
            Vec::new()
        };
        let manifest = build_manifest(
            &self.run_id,
            &self.runtime_dir,
            &self.model,
            &self.permission_mode,
            &self.devin_bin,
            &self.canary,
            &self.hook_command,
            &self.hook_path,
            self.hook_owned,
            &self.profile_id,
            &self.profile_path,
            &self.events_dir,
            &self.summary_path,
            &self.lifecycle_path,
            &self.owned_dirs,
            &extra_paths,
        )?;
        self.manifest_path = self.runtime_dir.join("manifest.json");
        manifest.write(&self.manifest_path)?;
        self.owned_paths.push(self.manifest_path.clone());
        Ok(())
    }

    fn env(&self) -> std::collections::HashMap<String, String> {
        let mut env: std::collections::HashMap<String, String> = std::env::vars().collect();
        env.insert(
            "GOAL_DEVIN_RUNTIME_DIR".to_string(),
            self.runtime_dir.to_string_lossy().into_owned(),
        );
        env.insert(
            "GOAL_DEVIN_EVENTS_DIR".to_string(),
            self.events_dir.to_string_lossy().into_owned(),
        );
        env.insert(
            "GOAL_DEVIN_LIFECYCLE_LOG".to_string(),
            self.lifecycle_path.to_string_lossy().into_owned(),
        );
        env
    }

    fn start_sidecar(&mut self) -> Result<()> {
        let exe = std::env::current_exe()?;
        let bin_dir = exe
            .parent()
            .ok_or_else(|| anyhow!("cannot determine binary directory"))?;
        let sidecar_bin = bin_dir.join("goal-devin-sidecar");
        if !sidecar_bin.exists() {
            return Err(anyhow!(
                "sidecar binary not found beside launcher: {}",
                sidecar_bin.display()
            ));
        }

        let mut cmd = Command::new(&sidecar_bin);
        cmd.arg(&self.runtime_dir)
            .stdin(Stdio::null())
            .stdout(Stdio::null())
            .stderr(Stdio::null())
            .env_clear()
            .envs(self.env());
        unsafe {
            cmd.pre_exec(|| {
                libc::setsid();
                Ok(())
            });
        }
        let child = cmd.spawn()?;
        self.sidecar_proc = Some(child);

        let ready_path = self.runtime_dir.join("sidecar-ready");
        let deadline = Instant::now() + Duration::from_secs(5);
        while Instant::now() < deadline {
            if self.signal_received() {
                return Err(anyhow!("interrupted while waiting for sidecar"));
            }
            if ready_path.exists() {
                return Ok(());
            }
            if let Some(ref mut child) = self.sidecar_proc {
                if let Ok(Some(_)) = child.try_wait() {
                    break;
                }
            }
            thread::sleep(Duration::from_millis(10));
        }
        Err(anyhow!("Sidecar failed to become ready within timeout"))
    }

    fn run_devin(&mut self) -> Result<()> {
        let mut cmd = Command::new(&self.devin_bin);
        cmd.arg("--model")
            .arg(&self.model)
            .arg("--permission-mode")
            .arg(&self.permission_mode)
            .current_dir(&self.canary)
            .stdin(Stdio::inherit())
            .stdout(Stdio::inherit())
            .stderr(Stdio::inherit())
            .env_clear()
            .envs(self.env());

        let child = cmd.spawn()?;
        let pid = child.id() as i32;
        self.devin_proc = Some(child);

        // Mark the active session immediately and refresh Goal Devin-owned
        // state periodically without touching Devin's terminal streams.
        self.update_companion_state(RunState::DevinActive, "Devin");

        let mut child = self.devin_proc.take().unwrap();
        let refresh_interval = Duration::from_millis(self.companion_poll_ms.max(50));
        let mut signal_sent: Option<i32> = None;
        let signal_deadline = Duration::from_secs(10);
        let signal_start = Instant::now();

        loop {
            thread::sleep(refresh_interval);

            if let Some(status) = child.try_wait().context("try_wait on devin process")? {
                if let Some(code) = status.code() {
                    self.devin_returncode = Some(code);
                } else if let Some(sig) = ExitStatusExt::signal(&status) {
                    // Conventional 128+signal exit status.
                    self.devin_returncode = Some(128 + (sig & 0x7f));
                }
                break;
            }

            // Refresh observable state while the session is live.
            self.update_companion_state(RunState::DevinActive, "Devin");

            if signal_sent.is_none() {
                if self.sigint_received.load(Ordering::Relaxed) {
                    signal_sent = Some(libc::SIGINT);
                    unsafe {
                        let _ = libc::kill(pid, libc::SIGINT);
                    }
                } else if self.sigterm_received.load(Ordering::Relaxed) {
                    signal_sent = Some(libc::SIGTERM);
                    unsafe {
                        let _ = libc::kill(pid, libc::SIGTERM);
                    }
                }
            } else if signal_start.elapsed() > signal_deadline {
                // Devin did not exit after the forwarded signal; force terminate.
                unsafe {
                    let _ = libc::kill(pid, libc::SIGKILL);
                }
                let _ = child.wait();
                self.devin_returncode = signal_sent.map(|s| 128 + (s & 0x7f));
                break;
            }
        }

        self.devin_proc = Some(child);

        if self.devin_returncode.is_some() {
            Ok(())
        } else {
            Err(anyhow!("devin process terminated by signal"))
        }
    }

    fn stop_sidecar(&mut self) {
        if let Some(mut child) = self.sidecar_proc.take() {
            let pid = child.id() as i32;
            unsafe {
                let _ = libc::kill(pid, libc::SIGTERM);
            }
            let deadline = Instant::now() + Duration::from_secs(5);
            loop {
                match child.try_wait() {
                    Ok(Some(_)) => break,
                    Ok(None) => {}
                    Err(_) => break,
                }
                if Instant::now() > deadline {
                    let _ = child.kill();
                    break;
                }
                thread::sleep(Duration::from_millis(50));
            }
            let _ = child.wait();
        }
    }

    fn log_lifecycle(&self, label: &str) {
        let _ = lifecycle_log(&self.lifecycle_path, label);
    }

    fn print_companion_command(&self) {
        if !self.companion_enabled {
            return;
        }
        let exe = std::env::current_exe().unwrap_or_else(|_| PathBuf::from("goal-devin-companion"));
        let bin_dir = exe.parent().unwrap_or_else(|| std::path::Path::new("."));
        let companion_bin = bin_dir.join("goal-devin-companion");
        eprintln!(
            "[goal-devin-companion] run in an adjacent terminal pane:\n  {} --runtime-dir {} --poll-ms {}\n",
            companion_bin.display(),
            self.runtime_dir.display(),
            self.companion_poll_ms,
        );
    }

    fn update_companion_state(&mut self, run_state: RunState, phase: &str) {
        if !self.companion_enabled {
            return;
        }
        let sidecar_healthy = self
            .sidecar_proc
            .as_mut()
            .map(|c| c.try_wait().map(|s| s.is_none()).unwrap_or(false))
            .unwrap_or(false);
        let mut state = CompanionState::new();
        state.run_state = run_state;
        state.lifecycle_phase = phase.to_string();
        state.model.clone_from(&self.model);
        state.permission_mode.clone_from(&self.permission_mode);
        state.profile_id.clone_from(&self.profile_id);
        state.sidecar_healthy = sidecar_healthy;
        state.started_at = self.started_at;
        state.updated_at = Some(Utc::now());
        if let Ok(text) = fs::read_to_string(&self.summary_path) {
            if let Ok(summary) = serde_json::from_str::<Map<String, Value>>(&text) {
                state.event_count = summary
                    .get("total_events")
                    .and_then(|v| v.as_u64())
                    .unwrap_or(0);
                state.last_event_type = summary
                    .get("last_event")
                    .and_then(|v| v.get("tool_name"))
                    .and_then(|v| v.as_str())
                    .unwrap_or("")
                    .to_string();
            }
        }
        state.finished = matches!(state.run_state, RunState::Complete | RunState::Failed);
        state.devin_returncode = self.devin_returncode;
        let _ = write_companion_state(&self.companion_state_path, &state);
    }

    fn final_cleanup(&mut self) -> Result<()> {
        self.stop_sidecar();
        self.log_lifecycle("supervisor_end");
        self.restore_canary_hook();
        if !self.profile_path.as_os_str().is_empty() {
            let created: Vec<_> = self
                .owned_dirs
                .iter()
                .filter(|p| p.starts_with(self.canary.join(".devin")))
                .cloned()
                .collect();
            let _ = remove_profile(&self.profile_path, &created);
        }

        let mut dirs: Vec<_> = self.owned_dirs.clone();
        dirs.sort_by_key(|p| p.components().count());
        dirs.reverse();
        for d in dirs {
            if d == self.canary || d == self.runtime_dir {
                continue;
            }
            if d.exists() && d.is_dir() {
                if let Ok(mut iter) = fs::read_dir(&d) {
                    if iter.next().is_none() {
                        let _ = fs::remove_dir(&d);
                    }
                }
            }
        }

        let _ = self.print_summary();

        let final_state = if self.devin_returncode == Some(0) {
            RunState::Complete
        } else {
            RunState::Failed
        };
        self.update_companion_state(final_state, "cleanup");

        if self.canary_created && !self.keep_canary && self.canary.exists() {
            let _ = fs::remove_dir_all(&self.canary);
        }
        Ok(())
    }

    fn restore_canary_hook(&self) {
        let hooks_file = self.canary.join(".devin").join("hooks.v1.json");
        if let Some(ref bytes) = self.original_hooks_bytes {
            let _ = fs::write(&hooks_file, bytes);
            if let Some(mode) = self.original_hooks_mode {
                let _ = set_mode(&hooks_file, mode);
            }
        } else if hooks_file.exists() && self.hook_owned {
            let _ = fs::remove_file(&hooks_file);
        }
    }

    fn print_summary(&self) -> Result<()> {
        if !self.summary_path.exists() {
            eprintln!("Goal Devin native mode completed (no summary)");
            return Ok(());
        }
        let text = fs::read_to_string(&self.summary_path)?;
        let summary: Value = serde_json::from_str(&text)?;
        let total = summary
            .get("total_events")
            .and_then(|v| v.as_u64())
            .unwrap_or(0);
        let last_tool = summary
            .get("last_event")
            .and_then(|v| v.get("tool_name"))
            .and_then(|v| v.as_str())
            .unwrap_or("");
        println!(
            "goal-devin-dev v0.1.0: model={}, events={}, last_tool={}",
            self.model, total, last_tool
        );
        Ok(())
    }
}
