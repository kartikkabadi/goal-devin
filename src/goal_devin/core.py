"""Core logic for goal-devin: state, devin subprocess, goal loop.

UI-agnostic. Both the TUI and the hidden CLI call this module.
"""
import hashlib
import json
from dataclasses import dataclass
import os
import platform
import re
import shutil
import subprocess
import sys
import threading
import time
from datetime import datetime
from pathlib import Path

from . import __version__

# --- paths ---
STATE_DIR = Path.home() / ".goal-devin"
STATE_DIR_FOR_CWD = STATE_DIR / "states"
LOG_DIR = STATE_DIR / "logs"

# --- defaults (env-overridable) ---
DEFAULTS = {
    "model": os.environ.get("GOAL_DEVIN_MODEL", "glm-5.2"),
    "permission_mode": os.environ.get("GOAL_DEVIN_PERMISSION_MODE", "dangerous"),
    "sleep_secs": float(os.environ.get("GOAL_DEVIN_SLEEP", "2")),
    "max_iters": int(os.environ.get("GOAL_DEVIN_MAX_ITERS", "0")),  # 0 = forever
    "iter_timeout": float(os.environ.get("GOAL_DEVIN_ITER_TIMEOUT", "1800")),  # 30 min
    "use_worktree": os.environ.get("GOAL_DEVIN_WORKTREE", "1") not in ("0", "false", ""),
    "use_sandbox": os.environ.get("GOAL_DEVIN_SANDBOX", "1") not in ("0", "false", ""),
}

# --- models (hardcoded, refreshable via parse_devin_models) ---
MODELS = [
    "glm-5.2", "glm-5.1",
    "kimi-k2.7", "kimi-k2.6",
    "gpt-5.5", "gpt-5.4", "gpt-5.4-mini", "gpt-5.3-codex", "gpt-5.2",
    "claude-opus-4.8", "claude-opus-4.7", "claude-opus-4.6", "claude-opus-4.5",
    "claude-sonnet-4.6", "claude-sonnet-4.5", "claude-haiku-4.5",
    "gemini-3.5-flash", "gemini-3.1-pro", "gemini-3-flash",
    "deepseek-v4-pro",
    "swe-1.6-fast", "swe-1.6", "swe-1.5",
    "adaptive",
]

# --- prompts ---
INITIAL_PROMPT = """\
GOAL: {goal}

You are running in goal-loop mode. Work toward this goal with concrete actions
this iteration: read files, edit code, run commands, verify. Do not just plan —
make real progress. End with a one-line summary of what you did this iteration.
"""

CONTINUE_PROMPT = """\
Continue toward the goal: {goal}

Do the next concrete step. Make real changes, run real checks. End with a
one-line summary of what you did.
"""

# --- status constants ---
STATUS_RUNNING = "running"
STATUS_PAUSED = "paused"
STATUS_STOPPED = "stopped"      # stopped by user (Ctrl+C or max_iters)
STATUS_KILLED = "killed"        # killed, cannot resume
STATUS_ERROR = "error"          # devin failed on iter 0
STATUS_STARTING = "starting"    # created but iter 0 not yet complete


@dataclass
class GoalState:
    """In-memory state for a single goal. Source of truth for the TUI while running."""
    goal: str
    model: str = ""
    session_id: str = ""
    status: str = STATUS_STARTING
    iters: int = 0
    elapsed: float = 0.0
    last_output: str = ""
    started_at: str = ""
    cwd: str = ""
    worktree_id: str | None = None
    use_worktree: bool = False
    use_sandbox: bool = False
    error: str = ""


# --- state management ---
def ensure_dirs():
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    STATE_DIR_FOR_CWD.mkdir(parents=True, exist_ok=True)


def state_file_for(cwd=None):
    """Per-cwd state file. Concurrent goals in different folders don't collide."""
    cwd = str(Path(cwd or os.getcwd()).resolve())
    h = hashlib.md5(cwd.encode()).hexdigest()[:12]
    return STATE_DIR_FOR_CWD / f"{h}.json"


def load_state(cwd=None):
    f = state_file_for(cwd)
    if f.exists():
        try:
            return json.loads(f.read_text())
        except json.JSONDecodeError:
            return None
    return None


def save_state(state, cwd=None):
    ensure_dirs()
    f = state_file_for(cwd)
    tmp = f.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(state, indent=2))
    tmp.replace(f)


def all_states():
    """Yield every saved state across all directories."""
    if not STATE_DIR_FOR_CWD.exists():
        return
    for f in sorted(STATE_DIR_FOR_CWD.glob("*.json")):
        try:
            yield json.loads(f.read_text())
        except json.JSONDecodeError:
            continue


def log_path(session_id):
    return LOG_DIR / f"{session_id}.log"


def append_log(session_id, text):
    ensure_dirs()
    with log_path(session_id).open("a") as f:
        f.write(text)
        if not text.endswith("\n"):
            f.write("\n")


def read_log_tail(session_id, lines=20):
    """Return last N lines of a session's log, or empty string."""
    lp = log_path(session_id)
    if not lp.exists():
        return ""
    text = lp.read_text()
    return "\n".join(text.splitlines()[-lines:])


# --- devin subprocess ---
def run_devin(args, timeout=None):
    """Run devin CLI with args. Returns CompletedProcess. Exits 2 if devin missing."""
    cmd = ["devin"] + args
    try:
        return subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
    except FileNotFoundError:
        raise  # let caller handle
    except subprocess.TimeoutExpired:
        return subprocess.CompletedProcess(cmd, returncode=124, stdout="",
                                           stderr=f"timed out after {timeout}s")


def parse_devin_models():
    """Parse available models from `devin --help` output. Returns list or None."""
    try:
        r = run_devin(["--help"])
    except FileNotFoundError:
        return None
    if r.returncode != 0:
        return None
    # ponytail: parse "Available: ..." line from error output — fragile but works
    m = re.search(r"Available:\s*(.+)", r.stderr + r.stdout)
    if not m:
        return None
    raw = m.group(1)
    models = [s.strip().rstrip(",") for s in raw.split(",")]
    return [m for m in models if m]


def find_state_by_session_id(session_id):
    """Find a state by session_id across all cwds. Returns dict or None."""
    for state in all_states():
        if state.get("session_id") == session_id:
            return state
    return None


def latest_session_id(cwd, retries=3, delay=1.0):
    """Most recent devin session id in cwd, or None. Retries to handle list lag."""
    cwd_resolved = str(Path(cwd).resolve())
    for _ in range(retries):
        r = run_devin(["list", "--format", "json"])
        if r.returncode != 0:
            time.sleep(delay)
            continue
        try:
            sessions = json.loads(r.stdout)
        except json.JSONDecodeError:
            time.sleep(delay)
            continue
        for s in sessions:
            if Path(s.get("working_directory", "")).resolve() == Path(cwd_resolved):
                return s.get("id")
        if sessions:
            # ponytail: fallback to most recent if cwd match fails — devin may report cwd differently
            return sessions[0].get("id")
        time.sleep(delay)
    return None


def fmt_elapsed(seconds):
    """Human-friendly elapsed: 1m 23s, 2h 14m, etc."""
    if seconds < 60:
        return f"{int(seconds)}s"
    if seconds < 3600:
        return f"{int(seconds // 60)}m {int(seconds % 60)}s"
    h = int(seconds // 3600)
    m = int((seconds % 3600) // 60)
    return f"{h}h {m}m"


# --- goal loop ---
class GoalLoop:
    """Runs a goal loop in a background thread. Pause/kill via events.

    Call .start() to launch, .pause()/.resume() to pause, .kill() to stop.
    Subscribe to events via on_iter callback.
    """

    def __init__(self, goal, session_id=None, model=None, permission_mode=None,
                 sleep_secs=None, max_iters=None, iter_timeout=None,
                 use_worktree=False, use_sandbox=False, cwd=None,
                 worktree_id=None,
                 on_iter=None, on_status=None, on_done=None):
        self.goal = goal
        self.session_id = session_id
        self.model = model or DEFAULTS["model"]
        # sandbox is just a flag — it enforces OS-level isolation on exec tool
        # it works with any permission mode, no need to override
        permission_mode = permission_mode or DEFAULTS["permission_mode"]
        self.permission_mode = permission_mode
        self.sleep_secs = sleep_secs if sleep_secs is not None else DEFAULTS["sleep_secs"]
        self.max_iters = max_iters if max_iters is not None else DEFAULTS["max_iters"]
        self.iter_timeout = iter_timeout if iter_timeout is not None else DEFAULTS["iter_timeout"]
        self.use_worktree = use_worktree
        self.use_sandbox = use_sandbox
        self.cwd = cwd or os.getcwd()
        self.worktree_id = worktree_id
        self.on_iter = on_iter        # callback(iters, session_id, output, elapsed)
        self.on_status = on_status    # callback(status, detail)
        self.on_done = on_done        # callback(reason, iters, elapsed)

        self.pause_event = threading.Event()
        self.kill_event = threading.Event()
        self._thread = None
        self._proc = None             # current devin subprocess
        self._proc_lock = threading.Lock()
        self.iters = 0
        self.start_time = None

    def start(self):
        """Launch the loop in a background thread."""
        self.start_time = time.monotonic()
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()

    def pause(self):
        self.pause_event.set()
        if self.on_status:
            self.on_status(STATUS_PAUSED, f"paused at iter {self.iters}")

    def resume(self):
        self.pause_event.clear()
        if self.on_status:
            self.on_status(STATUS_RUNNING, f"resumed at iter {self.iters}")

    def kill(self):
        self.kill_event.set()
        self.pause_event.clear()  # unpause so it can exit
        with self._proc_lock:
            if self._proc and self._proc.poll() is None:
                self._proc.terminate()
        if self.on_status:
            self.on_status(STATUS_KILLED, f"killed at iter {self.iters}")

    def is_alive(self):
        return self._thread and self._thread.is_alive()

    def join(self, timeout=None):
        if self._thread:
            self._thread.join(timeout)

    def _run_devin(self, args):
        """Run devin, tracking the subprocess so kill() can terminate it."""
        cmd = ["devin"] + args
        try:
            with self._proc_lock:
                self._proc = subprocess.Popen(
                    cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                    text=True, cwd=self.cwd)
            try:
                stdout, stderr = self._proc.communicate(timeout=self.iter_timeout)
            except subprocess.TimeoutExpired:
                self._proc.kill()
                stdout, stderr = self._proc.communicate()
                return subprocess.CompletedProcess(cmd, 124, stdout, f"timed out after {self.iter_timeout}s")
            return subprocess.CompletedProcess(cmd, self._proc.returncode, stdout, stderr)
        except FileNotFoundError:
            raise
        finally:
            with self._proc_lock:
                self._proc = None

    def _run(self):
        """Main loop body, runs in thread."""
        try:
            if self.session_id is None:
                # iter 0: start fresh session
                if self.on_status:
                    self.on_status(STATUS_RUNNING, "starting iter 0")
                args = ["-p", "--model", self.model,
                        "--permission-mode", self.permission_mode]
                if self.use_sandbox:
                    args.append("--sandbox")
                args += ["--", INITIAL_PROMPT.format(goal=self.goal)]
                r = self._run_devin(args)
                if r.returncode != 0:
                    if self.on_status:
                        self.on_status(STATUS_ERROR, f"devin exited {r.returncode} on iter 0")
                    if self.on_done:
                        self.on_done("error", 0, 0)
                    return
                self.session_id = latest_session_id(self.cwd)
                if not self.session_id:
                    if self.on_status:
                        self.on_status(STATUS_ERROR, "could not resolve session id")
                    if self.on_done:
                        self.on_done("error", 0, 0)
                    return
                save_state({
                    "session_id": self.session_id,
                    "cwd": self.cwd,
                    "goal": self.goal,
                    "iters": 1,
                    "model": self.model,
                    "permission_mode": self.permission_mode,
                    "use_worktree": self.use_worktree,
                    "use_sandbox": self.use_sandbox,
                    "worktree_id": self.worktree_id,
                    "status": STATUS_RUNNING,
                    "started_at": datetime.now().isoformat(timespec="seconds"),
                }, cwd=self.cwd)
                append_log(self.session_id, f"--- iter 0 (session {self.session_id}) ---\n{r.stdout}\n")
                self.iters = 1
                if self.on_iter:
                    self.on_iter(0, self.session_id, r.stdout, 0)
            else:
                state = load_state(self.cwd) or {}
                self.iters = state.get("iters", 0) if state.get("session_id") == self.session_id else 0
                if not self.goal:
                    self.goal = state.get("goal", "")
                if not self.goal:
                    if self.on_status:
                        self.on_status(STATUS_ERROR, "no goal recorded")
                    if self.on_done:
                        self.on_done("error", 0, 0)
                    return
                if self.on_status:
                    self.on_status(STATUS_RUNNING, f"resumed at iter {self.iters}")

            # main loop
            while True:
                if self.kill_event.is_set():
                    self._update_state(STATUS_KILLED)
                    if self.on_done:
                        self.on_done("killed", self.iters, time.monotonic() - self.start_time)
                    return
                if self.max_iters > 0 and self.iters >= self.max_iters:
                    self._update_state(STATUS_STOPPED)
                    if self.on_done:
                        self.on_done("max_iters", self.iters, time.monotonic() - self.start_time)
                    return
                # wait while paused
                while self.pause_event.is_set() and not self.kill_event.is_set():
                    time.sleep(0.5)
                if self.kill_event.is_set():
                    self._update_state(STATUS_KILLED)
                    if self.on_done:
                        self.on_done("killed", self.iters, time.monotonic() - self.start_time)
                    return
                time.sleep(self.sleep_secs)
                elapsed = time.monotonic() - self.start_time
                args = ["-r", self.session_id, "-p",
                        "--model", self.model,
                        "--permission-mode", self.permission_mode]
                if self.use_sandbox:
                    args.append("--sandbox")
                args += ["--", CONTINUE_PROMPT.format(goal=self.goal)]
                r = self._run_devin(args)
                append_log(self.session_id, f"--- iter {self.iters} ---\n{r.stdout}\n")
                self.iters += 1
                self._update_state(STATUS_RUNNING)
                if self.on_iter:
                    self.on_iter(self.iters, self.session_id, r.stdout, elapsed)
                if r.returncode != 0 and self.on_status:
                    self.on_status(STATUS_RUNNING, f"devin exited {r.returncode}; continuing")
        except FileNotFoundError:
            if self.on_status:
                self.on_status(STATUS_ERROR, "devin binary not found")
            if self.on_done:
                self.on_done("error", self.iters, time.monotonic() - self.start_time)
        except Exception as e:
            if self.on_status:
                self.on_status(STATUS_ERROR, str(e))
            if self.on_done:
                self.on_done("error", self.iters, time.monotonic() - self.start_time)

    def _update_state(self, status):
        state = load_state(self.cwd) or {}
        state.update({
            "session_id": self.session_id,
            "cwd": self.cwd,
            "goal": self.goal,
            "iters": self.iters,
            "model": self.model,
            "permission_mode": self.permission_mode,
            "use_worktree": self.use_worktree,
            "use_sandbox": self.use_sandbox,
            "worktree_id": self.worktree_id,
            "status": status,
            "last_iter_at": datetime.now().isoformat(timespec="seconds"),
        })
        save_state(state, cwd=self.cwd)


# --- notifications ---
def notify_desktop(title, message):
    """Send a desktop notification. macOS: osascript, Linux: notify-send. No-op if unavailable."""
    plat = platform.system().lower()
    if plat == "darwin" and shutil.which("osascript"):
        try:
            subprocess.run(["osascript", "-e",
                            f'display notification "{message}" with title "{title}"'],
                           capture_output=True, timeout=5)
        except Exception:
            pass
    elif plat.startswith("linux") and shutil.which("notify-send"):
        try:
            subprocess.run(["notify-send", title, message], capture_output=True, timeout=5)
        except Exception:
            pass


def notify_bell():
    """Terminal bell — only safe in raw CLI mode, not inside a TUI."""
    sys.stdout.write("\a")
    sys.stdout.flush()


def notify(title, message, bell=True):
    """Desktop notification + optional terminal bell. Bell is suppressed in TUI mode."""
    notify_desktop(title, message)
    if bell:
        notify_bell()
