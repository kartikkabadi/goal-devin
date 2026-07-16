use rand::RngCore;
use regex::Regex;
use std::fs::{self, File, OpenOptions, Permissions};
use std::io::{self, Read, Write};
use std::os::unix::fs::{OpenOptionsExt, PermissionsExt};
use std::path::{Component, Path, PathBuf};
use std::sync::LazyLock;

pub fn utcnow_iso() -> String {
    chrono::Utc::now().to_rfc3339_opts(chrono::SecondsFormat::Micros, false)
}

pub fn random_id(nbytes: usize) -> String {
    let mut buf = vec![0u8; nbytes];
    rand::thread_rng().fill_bytes(&mut buf);
    hex::encode(&buf)
}

static MODEL_RE: LazyLock<Regex> = LazyLock::new(|| Regex::new(r"^[A-Za-z0-9_.:/-]+$").unwrap());
static PERM_RE: LazyLock<Regex> = LazyLock::new(|| Regex::new(r"^[A-Za-z0-9_-]+$").unwrap());

pub fn validate_model(model: &str) -> Result<(), String> {
    if MODEL_RE.is_match(model) {
        Ok(())
    } else {
        Err(format!("model must be a one-line identifier: {model}"))
    }
}

pub fn validate_permission_mode(mode: &str) -> Result<(), String> {
    if PERM_RE.is_match(mode) {
        Ok(())
    } else {
        Err(format!(
            "permission-mode must be a one-line identifier: {mode}"
        ))
    }
}

pub fn set_mode(path: &Path, mode: u32) -> io::Result<()> {
    fs::set_permissions(path, Permissions::from_mode(mode))
}

pub fn normalize_path(path: &Path) -> PathBuf {
    let mut components = Vec::new();
    let mut needs_root = false;
    let mut prefix = None;

    for comp in path.components() {
        match comp {
            Component::Prefix(p) => {
                prefix = Some(p);
                components.clear();
            }
            Component::RootDir => {
                needs_root = true;
                components.clear();
            }
            Component::CurDir => {}
            Component::ParentDir => {
                components.pop();
            }
            Component::Normal(s) => components.push(s),
        }
    }

    let mut result = PathBuf::new();
    if let Some(p) = prefix {
        result.push(p.as_os_str());
    }
    if needs_root {
        result.push(Component::RootDir.as_os_str());
    }
    for c in components {
        result.push(c);
    }

    if !result.is_absolute() {
        if let Ok(cwd) = std::env::current_dir() {
            return normalize_path(&cwd.join(result));
        }
    }
    result
}

pub fn safe_path_under(root: &Path, path: &Path) -> bool {
    let root_abs = normalize_path(root);
    let path_abs = normalize_path(path);
    path_abs.starts_with(&root_abs)
}

pub fn has_symlink_component(root: &Path, path: &Path) -> io::Result<bool> {
    let root_abs = normalize_path(root);
    let path_abs = normalize_path(path);
    let rel = match path_abs.strip_prefix(&root_abs) {
        Ok(r) => r,
        Err(_) => return Ok(false),
    };

    let mut current = root_abs;
    for part in rel.components() {
        if let Component::Normal(name) = part {
            current = current.join(name);
            if current.is_symlink() {
                return Ok(true);
            }
        }
    }
    Ok(false)
}

pub fn ensure_private_dir(path: &Path, mode: u32, exist_ok: bool) -> io::Result<Vec<PathBuf>> {
    let mut created = Vec::new();
    if path.exists() {
        if !path.is_dir() {
            return Err(io::Error::new(
                io::ErrorKind::AlreadyExists,
                format!("{} exists and is not a directory", path.display()),
            ));
        }
        if !exist_ok {
            return Err(io::Error::new(
                io::ErrorKind::AlreadyExists,
                format!("directory already exists: {}", path.display()),
            ));
        }
        set_mode(path, mode)?;
        return Ok(created);
    }

    let mut stack = Vec::new();
    let mut current = path.to_path_buf();
    loop {
        stack.push(current.clone());
        if current.parent().is_none() {
            break;
        }
        current = current.parent().unwrap().to_path_buf();
    }

    for p in stack.into_iter().rev() {
        if p.exists() {
            if !p.is_dir() {
                return Err(io::Error::new(
                    io::ErrorKind::AlreadyExists,
                    format!("{} exists and is not a directory", p.display()),
                ));
            }
            continue;
        }
        fs::create_dir(&p)?;
        set_mode(&p, mode)?;
        created.push(p);
    }
    Ok(created)
}

pub fn atomic_write(path: &Path, data: &str, mode: u32) -> io::Result<()> {
    let dir = path
        .parent()
        .ok_or_else(|| io::Error::new(io::ErrorKind::InvalidInput, "path has no parent"))?;
    fs::create_dir_all(dir)?;
    let tmp_name = format!(
        ".{}.{}.tmp",
        path.file_name().unwrap_or_default().to_string_lossy(),
        random_id(4)
    );
    let tmp = dir.join(tmp_name);
    {
        let mut f = File::create(&tmp)?;
        f.write_all(data.as_bytes())?;
        f.flush()?;
        f.sync_all()?;
    }
    set_mode(&tmp, mode)?;
    fs::rename(&tmp, path)?;
    Ok(())
}

pub fn shlex_quote(s: &str) -> String {
    if s.is_empty() {
        return "''".to_string();
    }
    if !s
        .chars()
        .any(|c| c.is_whitespace() || c == '\'' || c == '"' || c == '\\')
    {
        return s.to_string();
    }
    if !s.contains('\'') {
        return format!("'{}'", s);
    }
    // Escape embedded single quotes by ending the quote, inserting an escaped
    // single quote, and starting a new quote.
    let mut out = String::from("'");
    for c in s.chars() {
        if c == '\'' {
            out.push_str("'\\''");
        } else {
            out.push(c);
        }
    }
    out.push('\'');
    out
}

pub fn read_json(path: &Path) -> anyhow::Result<serde_json::Value> {
    let mut f = File::open(path)?;
    let mut buf = String::new();
    f.read_to_string(&mut buf)?;
    let v = serde_json::from_str(&buf)?;
    Ok(v)
}

pub fn write_json(path: &Path, value: &serde_json::Value, mode: u32) -> io::Result<()> {
    let data = serde_json::to_string_pretty(value)?;
    atomic_write(path, &data, mode)
}

pub fn copy_file_with_mode(src: &Path, dst: &Path, mode: u32) -> io::Result<()> {
    fs::copy(src, dst)?;
    set_mode(dst, mode)
}

pub fn read_to_string(path: &Path) -> io::Result<String> {
    fs::read_to_string(path)
}

pub fn lifecycle_log(path: &Path, label: &str) -> io::Result<()> {
    if !path.parent().map(|p| p.exists()).unwrap_or(false) {
        return Ok(());
    }
    let parent = path.parent().unwrap();
    let mode = parent.metadata()?.permissions().mode() & 0o777;
    if mode != 0o700 {
        return Err(io::Error::new(
            io::ErrorKind::PermissionDenied,
            format!(
                "Lifecycle log parent directory {} mode is {:o}, expected 0o700",
                parent.display(),
                mode
            ),
        ));
    }
    let mut f = OpenOptions::new()
        .create(true)
        .append(true)
        .mode(0o600)
        .open(path)?;
    writeln!(f, "{} {}", label, utcnow_iso())?;
    f.flush()?;
    f.sync_all()?;
    // Ensure the mode remains 0o600 even if the file was created earlier.
    let _ = set_mode(path, 0o600);
    Ok(())
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn validate_model_accepts_reasonable() {
        assert!(validate_model("glm-5.2").is_ok());
        assert!(validate_model("claude-sonnet-4").is_ok());
    }

    #[test]
    fn validate_model_rejects_bad() {
        assert!(validate_model("").is_err());
        assert!(validate_model("foo;bar").is_err());
        assert!(validate_model("foo bar").is_err());
    }

    #[test]
    fn validate_permission_mode_accepts_reasonable() {
        assert!(validate_permission_mode("accept-edits").is_ok());
        assert!(validate_permission_mode("auto").is_ok());
    }

    #[test]
    fn validate_permission_mode_rejects_bad() {
        assert!(validate_permission_mode("").is_err());
        assert!(validate_permission_mode("foo;bar").is_err());
        assert!(validate_permission_mode("foo bar").is_err());
    }

    #[test]
    fn shlex_quote_simple() {
        assert_eq!(shlex_quote("foo"), "foo");
        assert_eq!(shlex_quote(""), "''");
    }

    #[test]
    fn shlex_quote_with_spaces_and_quotes() {
        assert_eq!(shlex_quote("hello world"), "'hello world'");
        assert_eq!(shlex_quote("it's"), "'it'\\''s'");
    }

    #[test]
    fn normalize_path_collapses_dotdot() {
        let p = Path::new("/foo/bar/../baz");
        assert_eq!(normalize_path(p), PathBuf::from("/foo/baz"));
    }

    #[test]
    fn safe_path_under_works() {
        assert!(safe_path_under(Path::new("/tmp"), Path::new("/tmp/foo")));
        assert!(!safe_path_under(Path::new("/tmp"), Path::new("/var")));
    }

    #[test]
    fn atomic_write_creates_file_with_mode() {
        let dir = tempfile::tempdir().unwrap();
        let path = dir.path().join("test.txt");
        atomic_write(&path, "hello", 0o600).unwrap();
        let content = fs::read_to_string(&path).unwrap();
        assert_eq!(content, "hello");
        let mode = fs::metadata(&path).unwrap().permissions().mode() & 0o777;
        assert_eq!(mode, 0o600);
    }

    #[test]
    fn ensure_private_dir_creates_with_mode() {
        let dir = tempfile::tempdir().unwrap();
        let path = dir.path().join("a").join("b").join("c");
        let created = ensure_private_dir(&path, 0o700, false).unwrap();
        assert!(path.exists());
        assert_eq!(created.len(), 3);
    }
}
