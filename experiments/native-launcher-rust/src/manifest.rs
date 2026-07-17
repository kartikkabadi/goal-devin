use crate::utils::{atomic_write, utcnow_iso};
use anyhow::Result;
use serde::Serialize;
use std::path::{Path, PathBuf};

#[derive(Serialize)]
pub struct Manifest {
    pub schema_version: i32,
    pub run_id: String,
    pub created_at: String,
    pub command: String,
    pub model: String,
    pub permission_mode: String,
    pub devin_bin: String,
    pub canary: String,
    pub hook_command: Vec<String>,
    pub profile_id: String,
    pub profile_path: String,
    pub events_dir: String,
    pub summary_path: String,
    pub goal_devin_generated: bool,
    pub owned_paths: Vec<String>,
    pub owned_roots: Vec<String>,
    pub owned_dirs: Vec<String>,
}

impl Manifest {
    pub fn write(&self, path: &Path) -> Result<()> {
        let data = serde_json::to_string_pretty(self)?;
        atomic_write(path, &data, 0o600)?;
        Ok(())
    }
}

pub fn canonical_str(path: &Path) -> String {
    path.canonicalize()
        .unwrap_or_else(|_| path.to_path_buf())
        .to_string_lossy()
        .into_owned()
}

#[allow(clippy::too_many_arguments)]
pub fn build_manifest(
    run_id: &str,
    runtime_dir: &Path,
    model: &str,
    permission_mode: &str,
    devin_bin: &Path,
    canary: &Path,
    hook_command: &[String],
    hook_path: &Path,
    hook_owned: bool,
    profile_id: &str,
    profile_path: &Path,
    events_dir: &Path,
    summary_path: &Path,
    lifecycle_path: &Path,
    owned_dirs: &[PathBuf],
    extra_paths: &[PathBuf],
) -> Result<Manifest> {
    let manifest_path = runtime_dir.join("manifest.json");
    let hooks_file = canary.join(".devin").join("hooks.v1.json");
    let profile_dir = profile_path
        .parent()
        .ok_or_else(|| anyhow::anyhow!("profile path has no parent"))?;

    let mut owned_paths = vec![
        canonical_str(&manifest_path),
        canonical_str(hook_path),
        canonical_str(lifecycle_path),
        canonical_str(&runtime_dir.join("supervisor.pid")),
        canonical_str(&runtime_dir.join("sidecar.pid")),
        canonical_str(&runtime_dir.join("child.pid")),
        canonical_str(&runtime_dir.join("sidecar-ready")),
        canonical_str(&runtime_dir.join("event.schema.json")),
        canonical_str(&runtime_dir.join("limits.json")),
        canonical_str(&runtime_dir.join("limits.schema.json")),
        canonical_str(summary_path),
        canonical_str(&runtime_dir.join("fake-devin.record.json")),
        canonical_str(profile_path),
    ];
    if hook_owned {
        owned_paths.push(canonical_str(&hooks_file));
    }
    for p in extra_paths {
        owned_paths.push(canonical_str(p));
    }

    let owned_roots = vec![
        canonical_str(runtime_dir),
        canonical_str(events_dir),
        canonical_str(profile_dir),
    ];

    let mut dirs: Vec<String> = owned_dirs.iter().map(|p| canonical_str(p)).collect();
    dirs.sort();
    dirs.dedup();

    Ok(Manifest {
        schema_version: 1,
        run_id: run_id.to_string(),
        created_at: utcnow_iso(),
        command: "goal-devin-dev".to_string(),
        model: model.to_string(),
        permission_mode: permission_mode.to_string(),
        devin_bin: canonical_str(devin_bin),
        canary: canonical_str(canary),
        hook_command: hook_command.to_vec(),
        profile_id: profile_id.to_string(),
        profile_path: canonical_str(profile_path),
        events_dir: canonical_str(events_dir),
        summary_path: canonical_str(summary_path),
        goal_devin_generated: true,
        owned_paths,
        owned_roots,
        owned_dirs: dirs,
    })
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn build_manifest_sets_goal_devin_generated() {
        let dir = tempfile::tempdir().unwrap();
        let runtime = dir.path().join("runtime");
        let canary = dir.path().join("canary");
        let events = runtime.join("events");
        let summary = runtime.join("summary.json");
        let lifecycle = runtime.join("lifecycle.log");
        std::fs::create_dir_all(&events).unwrap();
        std::fs::create_dir_all(&canary).unwrap();
        let profile_path = canary
            .join(".devin")
            .join("agents")
            .join("goal-devin-worker-abc")
            .join("AGENT.md");
        std::fs::create_dir_all(profile_path.parent().unwrap()).unwrap();

        let manifest = build_manifest(
            "run-123",
            &runtime,
            "glm-5.2",
            "accept-edits",
            Path::new("/usr/bin/devin"),
            &canary,
            &["/runtime/hook".to_string(), "/runtime/events".to_string()],
            &runtime.join("hook"),
            false,
            "goal-devin-worker-abc",
            &profile_path,
            &events,
            &summary,
            &lifecycle,
            &[events.clone(), profile_path.parent().unwrap().to_path_buf()],
            &[],
        )
        .unwrap();

        assert_eq!(manifest.schema_version, 1);
        assert_eq!(manifest.command, "goal-devin-dev");
        assert!(manifest.goal_devin_generated);
        assert!(manifest
            .owned_paths
            .iter()
            .any(|p| p.contains("manifest.json")));
    }
}
