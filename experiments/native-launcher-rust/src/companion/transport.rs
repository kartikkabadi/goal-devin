use super::model::CompanionState;
use anyhow::{Context, Result};
use std::fs;
use std::path::{Path, PathBuf};
use std::time::SystemTime;

const MAX_STATE_BYTES: usize = 64 * 1024;

pub struct Transport {
    path: PathBuf,
    last_mtime: Option<SystemTime>,
}

impl Transport {
    pub fn new(runtime_dir: &Path) -> Self {
        Self {
            path: runtime_dir.join("companion").join("state.json"),
            last_mtime: None,
        }
    }

    pub fn path(&self) -> &Path {
        &self.path
    }

    pub fn read(&mut self) -> Result<Option<CompanionState>> {
        let meta = match fs::metadata(&self.path) {
            Ok(m) => m,
            Err(_) => return Ok(None),
        };
        let mtime = meta.modified().ok();
        if mtime == self.last_mtime {
            return Ok(None);
        }
        let bytes = fs::read(&self.path)
            .with_context(|| format!("failed to read companion state: {}", self.path.display()))?;
        if bytes.len() > MAX_STATE_BYTES {
            return Err(anyhow::anyhow!("companion state file exceeds size limit"));
        }
        let mut state: CompanionState = serde_json::from_slice(&bytes)
            .with_context(|| format!("invalid companion state: {}", self.path.display()))?;
        state.sanitize();
        self.last_mtime = mtime;
        Ok(Some(state))
    }
}

pub fn write_state(path: &Path, state: &CompanionState) -> anyhow::Result<()> {
    if let Some(parent) = path.parent() {
        fs::create_dir_all(parent)?;
    }
    let data = serde_json::to_string(state)?;
    crate::utils::atomic_write(path, &data, 0o600)?;
    Ok(())
}
