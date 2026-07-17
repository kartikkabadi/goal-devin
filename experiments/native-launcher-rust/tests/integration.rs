use std::path::{Path, PathBuf};
use std::process::{Command, Stdio};
use std::thread;
use std::time::{Duration, Instant};

fn candidate_path() -> PathBuf {
    PathBuf::from(env!("CARGO_BIN_EXE_goal-devin-dev"))
}

fn contract_dir() -> PathBuf {
    PathBuf::from(env!("CARGO_MANIFEST_DIR"))
        .parent()
        .unwrap()
        .join("native-launcher-testkit")
}

fn wait_for_runtime_dir(runtime_root: &Path, timeout: Duration) -> PathBuf {
    let deadline = Instant::now() + timeout;
    loop {
        let dirs: Vec<_> = std::fs::read_dir(runtime_root)
            .unwrap()
            .filter_map(|e| e.ok().map(|e| e.path()))
            .filter(|p| p.is_dir())
            .collect();
        if dirs.len() == 1 {
            return dirs.into_iter().next().unwrap();
        }
        if Instant::now() > deadline {
            panic!(
                "timed out waiting for run directory in {}",
                runtime_root.display()
            );
        }
        thread::sleep(Duration::from_millis(20));
    }
}

fn read_state(path: &Path) -> Option<serde_json::Value> {
    std::fs::read_to_string(path)
        .ok()
        .and_then(|s| serde_json::from_str(&s).ok())
}

#[test]
fn end_to_end_normal_mode_produces_summary() {
    let dir = tempfile::tempdir().unwrap();
    let runtime_root = dir.path().join("runtime");
    std::fs::create_dir_all(&runtime_root).unwrap();

    let manifest_dir = PathBuf::from(env!("CARGO_MANIFEST_DIR"));
    let contract_dir = manifest_dir
        .parent()
        .unwrap()
        .join("native-launcher-testkit");
    let candidate = env!("CARGO_BIN_EXE_goal-devin-dev");
    let fake_devin = contract_dir.join("fake-devin");

    let mut cmd = Command::new(candidate);
    cmd.arg("--model")
        .arg("swe-1-7")
        .arg("--permission-mode")
        .arg("accept-edits")
        .arg("--devin-bin")
        .arg(&fake_devin)
        .arg("--contract-dir")
        .arg(&contract_dir)
        .arg("--runtime-root")
        .arg(&runtime_root)
        .arg("--keep-canary")
        .env("GOAL_DEVIN_FAKE_SLEEP", "0.05");

    let output = cmd.output().expect("failed to launch candidate");
    if !output.status.success() {
        panic!(
            "candidate exited with {}\nstderr: {}",
            output.status,
            String::from_utf8_lossy(&output.stderr)
        );
    }

    let mut run_dirs: Vec<_> = std::fs::read_dir(&runtime_root)
        .unwrap()
        .filter_map(|e| e.ok().map(|e| e.path()))
        .filter(|p| p.is_dir())
        .collect();
    assert_eq!(run_dirs.len(), 1, "expected exactly one run directory");
    let summary_path = run_dirs.pop().unwrap().join("summary.json");
    assert!(summary_path.exists(), "summary.json not produced");

    let text = std::fs::read_to_string(&summary_path).unwrap();
    let summary: serde_json::Value = serde_json::from_str(&text).unwrap();
    assert_eq!(summary.get("total_events").unwrap().as_u64().unwrap(), 1);

    let last_event = summary.get("last_event").unwrap();
    assert_eq!(
        last_event.get("tool_name").unwrap().as_str().unwrap(),
        "run_subagent"
    );
    assert!(last_event.get("success").unwrap().as_bool().unwrap());
}

#[test]
fn companion_state_refreshes_during_barrier_and_finishes() {
    let dir = tempfile::tempdir().unwrap();
    let runtime_root = dir.path().join("runtime");
    std::fs::create_dir_all(&runtime_root).unwrap();

    let fake_devin = contract_dir().join("fake-devin");
    let mut cmd = Command::new(candidate_path());
    cmd.arg("--model")
        .arg("swe-1-7")
        .arg("--permission-mode")
        .arg("accept-edits")
        .arg("--devin-bin")
        .arg(&fake_devin)
        .arg("--contract-dir")
        .arg(contract_dir())
        .arg("--runtime-root")
        .arg(&runtime_root)
        .arg("--companion")
        .arg("--companion-poll-ms")
        .arg("50")
        .arg("--keep-canary")
        .env("GOAL_DEVIN_BARRIER", "1")
        .env("GOAL_DEVIN_FAKE_SLEEP", "0.05");

    cmd.stdout(Stdio::null()).stderr(Stdio::null());
    let mut child = cmd.spawn().expect("failed to launch candidate");
    let runtime_dir = wait_for_runtime_dir(&runtime_root, Duration::from_secs(5));
    let state_path = runtime_dir.join("companion").join("state.json");

    // Wait for the supervisor to spawn Devin and transition to DevinActive.
    let deadline = Instant::now() + Duration::from_secs(5);
    let mut saw_active = false;
    while Instant::now() < deadline {
        if let Some(state) = read_state(&state_path) {
            let run_state = state.get("run_state").and_then(|v| v.as_str());
            let phase = state.get("lifecycle_phase").and_then(|v| v.as_str());
            if run_state == Some("DevinActive") && phase == Some("Devin") {
                saw_active = true;
                break;
            }
        }
        thread::sleep(Duration::from_millis(50));
    }
    assert!(
        saw_active,
        "did not observe DevinActive state while barrier held"
    );

    // Release the barrier and watch the session finish successfully.
    std::fs::write(runtime_dir.join("continue"), "\n").unwrap();

    let deadline = Instant::now() + Duration::from_secs(10);
    let mut finished = false;
    while Instant::now() < deadline {
        if let Some(state) = read_state(&state_path) {
            if state.get("finished").and_then(|v| v.as_bool()) == Some(true) {
                assert_eq!(
                    state.get("run_state").and_then(|v| v.as_str()),
                    Some("Complete")
                );
                assert_eq!(state.get("event_count").and_then(|v| v.as_u64()), Some(1));
                finished = true;
                break;
            }
        }
        thread::sleep(Duration::from_millis(50));
    }

    let status = child.wait().expect("candidate did not exit");
    assert!(status.success(), "candidate exited with {}", status);
    assert!(finished, "companion state did not finish");
}

#[test]
fn sigint_cleans_up_sidecar_profile_and_hook() {
    let dir = tempfile::tempdir().unwrap();
    let runtime_root = dir.path().join("runtime");
    std::fs::create_dir_all(&runtime_root).unwrap();

    let fake_devin = contract_dir().join("fake-devin");
    let mut cmd = Command::new(candidate_path());
    cmd.arg("--model")
        .arg("swe-1-7")
        .arg("--permission-mode")
        .arg("accept-edits")
        .arg("--devin-bin")
        .arg(&fake_devin)
        .arg("--contract-dir")
        .arg(contract_dir())
        .arg("--runtime-root")
        .arg(&runtime_root)
        .arg("--companion")
        .arg("--companion-poll-ms")
        .arg("50")
        .arg("--keep-canary")
        .env("GOAL_DEVIN_BARRIER", "1")
        .env("GOAL_DEVIN_FAKE_SLEEP", "0.05");

    cmd.stdout(Stdio::null()).stderr(Stdio::null());
    let mut child = cmd.spawn().expect("failed to launch candidate");
    let supervisor_pid = child.id() as libc::pid_t;
    let runtime_dir = wait_for_runtime_dir(&runtime_root, Duration::from_secs(5));
    let state_path = runtime_dir.join("companion").join("state.json");

    // Wait until Devin is active behind the barrier.
    let deadline = Instant::now() + Duration::from_secs(5);
    loop {
        if let Some(state) = read_state(&state_path) {
            if state.get("run_state").and_then(|v| v.as_str()) == Some("DevinActive") {
                break;
            }
        }
        if Instant::now() > deadline {
            panic!("candidate never reached DevinActive");
        }
        thread::sleep(Duration::from_millis(50));
    }

    // Read the sidecar pid before interrupting.
    let sidecar_pid_path = runtime_dir.join("sidecar.pid");
    let sidecar_pid: libc::pid_t = std::fs::read_to_string(&sidecar_pid_path)
        .unwrap()
        .trim()
        .parse()
        .unwrap();

    unsafe {
        libc::kill(supervisor_pid, libc::SIGINT);
    }

    let status = child.wait().expect("candidate did not exit");
    assert_eq!(
        status.code(),
        Some(130),
        "expected conventional SIGINT exit code 130"
    );

    // Sidecar should be reaped by final cleanup.
    let deadline = Instant::now() + Duration::from_secs(5);
    loop {
        let alive = unsafe { libc::kill(sidecar_pid, 0) } == 0;
        if !alive {
            break;
        }
        if Instant::now() > deadline {
            panic!("sidecar process {} survived SIGINT cleanup", sidecar_pid);
        }
        thread::sleep(Duration::from_millis(50));
    }

    // Profile and hook should be removed from the kept canary.
    let canary = runtime_dir.join("canary");
    assert!(
        !canary.join(".devin").join("agents").exists(),
        "profile dir leaked"
    );
    assert!(
        !canary.join(".devin").join("hooks.v1.json").exists(),
        "hook file leaked"
    );

    // Companion state should record the interruption as Failed.
    let state = read_state(&state_path).expect("companion state missing");
    assert_eq!(state.get("finished").and_then(|v| v.as_bool()), Some(true));
    assert_eq!(
        state.get("run_state").and_then(|v| v.as_str()),
        Some("Failed")
    );
    assert_eq!(
        state.get("devin_returncode").and_then(|v| v.as_i64()),
        Some(130)
    );
}
