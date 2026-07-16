"""Small helpers used by the native launcher candidate."""

import json
import os
import stat
import tempfile
from datetime import datetime, timezone
from pathlib import Path


def utcnow_iso() -> str:
    """Return an ISO 8601 UTC timestamp."""
    return datetime.now(timezone.utc).isoformat()


def random_id(nbytes: int = 16) -> str:
    """Return a cryptographically random hex identifier."""
    return os.urandom(nbytes).hex()


def safe_path_under(root: Path | str, path: Path | str) -> bool:
    """Return True if *path* resolves to a location inside *root*."""
    root_resolved = Path(root).resolve()
    path_resolved = Path(path).resolve()
    if path_resolved == root_resolved:
        return True
    try:
        common = Path(os.path.commonpath([root_resolved, path_resolved]))
    except ValueError:
        return False
    return common == root_resolved


def has_symlink_component(root: Path | str, path: Path | str) -> bool:
    """Return True if any existing component of *path* under *root* is a symlink."""
    root = Path(root)
    path = Path(path)
    try:
        rel = path.relative_to(root.resolve())
    except ValueError:
        return True
    current = root
    for part in rel.parts:
        current = current / part
        if current.is_symlink():
            return True
    return current.is_symlink()


def mkdir_private(path: Path, mode: int = 0o700) -> None:
    """Create a directory with restricted permissions."""
    path.mkdir(parents=True, exist_ok=True)
    os.chmod(path, mode)


def ensure_private_dir(path: Path, mode: int = 0o700, exist_ok: bool = False) -> list[Path]:
    """Create *path* and any missing parents with *mode*, returning created dirs.

    If ``exist_ok`` is false (the default), the leaf directory is created with
    ``exist_ok=False`` so a pre-existing leaf is a collision.  If ``exist_ok`` is
    true, a pre-existing directory leaf is allowed but not claimed as created.
    Each newly created directory is chmodded to *mode* after creation to ignore
    the process umask.
    """
    created: list[Path] = []
    stack: list[Path] = []
    current = path
    while True:
        stack.append(current)
        if current == path.anchor or current.parent == current:
            break
        current = current.parent

    for p in reversed(stack):
        if p.exists():
            if not p.is_dir():
                raise FileExistsError(f"{p} exists and is not a directory")
            if p == path and not exist_ok:
                raise FileExistsError(f"directory already exists: {path}")
            continue
        p.mkdir(mode=mode, exist_ok=False)
        created.append(p)
    for p in created:
        os.chmod(p, mode)
    # Pre-existing directories are intentionally NOT chmodded; we create missing
    # directories with the requested mode and preserve any user/project directory
    # that already existed.
    return created


def atomic_write(path: Path, data: str, file_mode: int = 0o600) -> None:
    """Atomically write *data* to *path* with *file_mode* permissions."""
    directory = path.parent
    directory.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(dir=directory, prefix=f"{path.name}.", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            fh.write(data)
            fh.flush()
            os.fsync(fh.fileno())
        os.chmod(tmp_name, file_mode)
        os.rename(tmp_name, path)
    except Exception:
        try:
            os.unlink(tmp_name)
        except FileNotFoundError:
            pass
        raise


def read_json_bounded(stream, max_bytes: int = 1024 * 1024) -> dict:
    """Read at most *max_bytes* from *stream* and parse JSON."""
    raw = stream.read(max_bytes + 1)
    if len(raw) > max_bytes:
        raise ValueError(f"Input exceeds {max_bytes} bytes")
    return json.loads(raw.decode("utf-8"))


def mode_is_owner_only(path: Path) -> bool:
    """Return True if the file is readable/writable only by the owner."""
    mode = stat.S_IMODE(path.stat().st_mode)
    return mode == 0o600


def directory_mode_is_private(path: Path) -> bool:
    """Return True if the directory is owner-only."""
    mode = stat.S_IMODE(path.stat().st_mode)
    return mode == 0o700
