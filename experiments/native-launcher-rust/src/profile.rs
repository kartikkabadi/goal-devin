use crate::utils::{
    atomic_write, ensure_private_dir, has_symlink_component, random_id, validate_model,
};
use anyhow::{anyhow, Result};
use std::fs;
use std::path::{Path, PathBuf};

const AGENT_MD: &str = r#"---
name: {name}
description: Goal Devin read-only worker for the native integration trial
model: {model}
allowed-tools:
  - read
  - grep
  - glob
permissions:
  deny:
    - write
    - edit
---
"#;

pub fn make_profile_id() -> String {
    format!("goal-devin-worker-{}", random_id(8))
}

pub fn make_profile(
    canary: &Path,
    profile_id: &str,
    model: &str,
) -> Result<(PathBuf, Vec<PathBuf>)> {
    validate_model(model).map_err(|e| anyhow!(e))?;
    if has_symlink_component(canary, canary)? {
        return Err(anyhow!("canary contains a symlink component"));
    }
    let agents_dir = canary.join(".devin").join("agents");
    let profile_dir = agents_dir.join(profile_id);

    if has_symlink_component(canary, &agents_dir)? {
        return Err(anyhow!(".devin/agents path contains a symlink component"));
    }
    if has_symlink_component(canary, &profile_dir)? {
        return Err(anyhow!(
            "profile directory path contains a symlink component"
        ));
    }

    let created = ensure_private_dir(&profile_dir, 0o700, false)?;
    // parent dirs were created by ensure_private_dir if needed, ensure mode 0o700 for all
    for p in &created {
        let _ = fs::set_permissions(p, std::os::unix::fs::PermissionsExt::from_mode(0o700));
    }

    let content = AGENT_MD
        .replace("{name}", profile_id)
        .replace("{model}", model);
    let profile_path = profile_dir.join("AGENT.md");
    atomic_write(&profile_path, &content, 0o600)?;

    Ok((profile_path, created))
}

pub fn remove_profile(profile_path: &Path, created_dirs: &[PathBuf]) -> Result<()> {
    let profile_dir = profile_path
        .parent()
        .ok_or_else(|| anyhow!("profile path has no parent"))?;
    if profile_dir.exists() {
        fs::remove_dir_all(profile_dir)?;
    }

    let mut dirs: Vec<_> = created_dirs.to_vec();
    dirs.sort_by_key(|p| p.components().count());
    dirs.reverse();
    for p in &dirs {
        if p.exists() && p.is_dir() && p != profile_dir && fs::read_dir(p)?.next().is_none() {
            let _ = fs::remove_dir(p);
        }
    }
    Ok(())
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::os::unix::fs::PermissionsExt;

    #[test]
    fn make_profile_id_has_correct_prefix() {
        let id = make_profile_id();
        assert!(id.starts_with("goal-devin-worker-"));
        assert!(id.len() > "goal-devin-worker-".len());
    }

    #[test]
    fn creates_and_removes_profile() {
        let dir = tempfile::tempdir().unwrap();
        let model = "glm-5.2";
        let profile_id = make_profile_id();
        let (path, created) = make_profile(dir.path(), &profile_id, model).unwrap();
        assert!(path.exists());

        let content = fs::read_to_string(&path).unwrap();
        assert!(content.contains(&format!("name: {}", profile_id)));
        assert!(content.contains(&format!("model: {}", model)));
        assert!(content.contains("deny:"));
        assert!(content.contains("- write"));

        let mode = fs::metadata(&path).unwrap().permissions().mode() & 0o777;
        assert_eq!(mode, 0o600);

        remove_profile(&path, &created).unwrap();
        assert!(!path.exists());
    }

    #[test]
    fn rejects_invalid_model_in_profile() {
        let dir = tempfile::tempdir().unwrap();
        let profile_id = make_profile_id();
        let result = make_profile(dir.path(), &profile_id, "!!invalid!!");
        assert!(result.is_err());
    }
}
