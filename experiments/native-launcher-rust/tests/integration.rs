use std::path::PathBuf;
use std::process::Command;

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
