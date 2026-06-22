"""Git worktree management for goal-devin.

Each goal can run in an isolated git worktree on branch goal-devin/<session-id>,
so the model's changes don't touch the user's working branch.
"""
import subprocess
from pathlib import Path

WORKTREE_DIR = ".goal-wt"
BRANCH_PREFIX = "goal-devin"


def is_git_repo(cwd=None):
    """True if cwd is inside a git repo."""
    try:
        r = subprocess.run(
            ["git", "rev-parse", "--is-inside-work-tree"],
            capture_output=True, text=True, cwd=cwd or ".",
        )
        return r.returncode == 0 and r.stdout.strip() == "true"
    except FileNotFoundError:
        return False


def repo_root(cwd=None):
    """Return repo root path, or None if not in a repo.

    Returns the worktree's own top-level when called from inside a worktree,
    NOT the main repo root. Use main_repo_root for that.
    """
    try:
        r = subprocess.run(
            ["git", "rev-parse", "--show-toplevel"],
            capture_output=True, text=True, cwd=cwd or ".",
        )
        if r.returncode == 0:
            return Path(r.stdout.strip())
    except FileNotFoundError:
        pass
    return None


def main_repo_root(cwd=None):
    """Return the main repo root (the one with .git/ dir, not a worktree).

    Works from any cwd inside a repo, including linked worktrees.
    Returns None if not in a repo or git unavailable.
    """
    try:
        r = subprocess.run(
            ["git", "rev-parse", "--git-common-dir"],
            capture_output=True, text=True, cwd=cwd or ".",
        )
        if r.returncode == 0:
            common_dir = Path(r.stdout.strip())
            # git may return a relative path — resolve against cwd
            if not common_dir.is_absolute():
                base = Path(cwd) if cwd else Path.cwd()
                common_dir = (base / common_dir).resolve()
            else:
                common_dir = common_dir.resolve()
            # common dir is <main_repo>/.git — parent is the main repo root
            return common_dir.parent
    except FileNotFoundError:
        pass
    return None


def branch_name(session_id):
    return f"{BRANCH_PREFIX}/{session_id}"


def create_worktree(session_id, cwd=None):
    """Create a git worktree for a session. Returns (path, None) or (None, error)."""
    if not is_git_repo(cwd):
        return None, "not a git repo"
    root = repo_root(cwd)
    wt = root / WORKTREE_DIR / session_id
    branch = branch_name(session_id)
    # ensure .goal-wt is gitignored
    _ensure_gitignore(root)
    r = subprocess.run(
        ["git", "worktree", "add", str(wt), "-b", branch],
        capture_output=True, text=True, cwd=root,
    )
    if r.returncode != 0:
        return None, r.stderr.strip() or "git worktree add failed"
    return wt, None


def remove_worktree(session_id, cwd=None, force=False):
    """Remove a worktree. Returns (True, None) or (False, error).

    cwd can be the main repo root OR a worktree path — main_repo_root
    resolves the actual repo root from either.
    """
    if not is_git_repo(cwd):
        return False, "not a git repo"
    root = main_repo_root(cwd)
    if not root:
        return False, "could not resolve main repo root"
    wt = root / WORKTREE_DIR / session_id
    branch = branch_name(session_id)
    args = ["git", "worktree", "remove"]
    if force:
        args.append("--force")
    args.append(str(wt))
    r = subprocess.run(args, capture_output=True, text=True, cwd=root)
    if r.returncode != 0:
        return False, r.stderr.strip() or "git worktree remove failed"
    # delete the branch too
    subprocess.run(
        ["git", "branch", "-D", branch],
        capture_output=True, text=True, cwd=root,
    )
    return True, None


def merge_worktree(session_id, target_branch=None, cwd=None):
    """Merge a worktree's branch into target (default: current branch).

    cwd can be the main repo root OR a worktree path — main_repo_root
    resolves the actual repo root from either.
    """
    if not is_git_repo(cwd):
        return False, "not a git repo"
    root = main_repo_root(cwd)
    if not root:
        return False, "could not resolve main repo root"
    branch = branch_name(session_id)
    if target_branch:
        if target_branch.startswith("-"):
            return False, "invalid branch name"
        # checkout target first
        r = subprocess.run(
            ["git", "checkout", target_branch],
            capture_output=True, text=True, cwd=root,
        )
        if r.returncode != 0:
            return False, f"checkout {target_branch} failed: {r.stderr.strip()}"
    r = subprocess.run(
        ["git", "merge", "--no-ff", branch, "-m", f"merge goal-devin/{session_id}"],
        capture_output=True, text=True, cwd=root,
    )
    if r.returncode != 0:
        return False, r.stderr.strip() or "git merge failed"
    return True, None


def list_worktrees(cwd=None):
    """List all goal-devin worktrees. Returns list of dicts."""
    if not is_git_repo(cwd):
        return []
    root = repo_root(cwd)
    r = subprocess.run(
        ["git", "worktree", "list", "--porcelain"],
        capture_output=True, text=True, cwd=root,
    )
    if r.returncode != 0:
        return []
    worktrees = []
    current = {}
    for line in r.stdout.splitlines():
        if line.startswith("worktree "):
            if current:
                worktrees.append(current)
            current = {"path": line[len("worktree "):]}
        elif line.startswith("branch "):
            current["branch"] = line[len("branch "):]
        elif line == "bare":
            current["bare"] = True
        elif not line:
            if current:
                worktrees.append(current)
                current = {}
    if current:
        worktrees.append(current)
    # filter to goal-devin branches (strip refs/heads/ prefix)
    return [w for w in worktrees
            if w.get("branch", "").replace("refs/heads/", "").startswith(f"{BRANCH_PREFIX}/")]


def _ensure_gitignore(root):
    """Add .goal-wt/ to .gitignore if not already present."""
    gitignore = root / ".gitignore"
    entry = f"{WORKTREE_DIR}/"
    existing = gitignore.read_text() if gitignore.exists() else ""
    if entry not in existing:
        with gitignore.open("a") as f:
            if existing and not existing.endswith("\n"):
                f.write("\n")
            f.write(f"{entry}\n")
