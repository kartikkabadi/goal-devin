#!/usr/bin/env python3
"""goal-devin: unbounded goal-loop wrapper around the Devin CLI.

Burns tokens on GLM 5.2 / Kimi K 2.7 (or any Devin model) toward a fixed goal.
Each iteration is one non-interactive `devin -p` call into a single resumed
session, so the model keeps context across iterations. The model cannot stop
the loop — only Ctrl+C (or --max-iters N) stops it.

Usage:
  goal-devin goal "make all tests pass"
  goal-devin resume [session-id]
  goal-devin status [--all]
  goal-devin logs [session-id] [-f]

Stop with Ctrl+C. State lives in ~/.goal-devin/.
"""
import argparse
import hashlib
import json
import os
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path

__version__ = "0.1.0"

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
}

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

# --- ANSI colors (stdlib, no deps) ---
class C:
    RESET = "\033[0m"
    BOLD = "\033[1m"
    DIM = "\033[2m"
    RED = "\033[31m"
    GREEN = "\033[32m"
    YELLOW = "\033[33m"
    BLUE = "\033[34m"
    MAGENTA = "\033[35m"
    CYAN = "\033[36m"
    GRAY = "\033[90m"

_NO_COLOR = not sys.stdout.isatty() or os.environ.get("NO_COLOR")

def _c(text, color):
    if _NO_COLOR:
        return text
    return f"{color}{text}{C.RESET}"

def _strip_ansi(text):
    import re
    return re.sub(r"\033\[[0-9;]*m", "", text)

# --- UI helpers ---
def banner():
    """One-time header on goal start."""
    if _NO_COLOR:
        print("goal-devin v" + __version__)
        return
    art = r"""
   ____      _ _         _ _  __     _    
  / ___|__ _| | | ___  _| | |/ /__ _| |_  
 | |  _ / _` | | |/ / || | ' // _` | __|
 | |_| | (_| | |   <  _  | . \ (_| | |_  
  \____|\__,_|_|_|\_\_, |_|\_\__,_|\__|  v{}
                    |___/               """.format(__version__)
    print(_c(art, C.CYAN))
    print(_c("  unbounded goal-loop for the Devin CLI", C.DIM))
    print()


def iter_header(iters, session_id, elapsed=None):
    """Per-iteration separator with elapsed timer."""
    parts = [f"iter {iters}", f"session {session_id}"]
    if elapsed is not None:
        parts.append(f"elapsed {elapsed}")
    parts.append(datetime.now().strftime("%H:%M:%S"))
    line = " | ".join(parts)
    width = len(_strip_ansi(line)) + 4
    if _NO_COLOR:
        print(f"\n{'=' * width}")
        print(f"  {line}")
        print(f"{'=' * width}")
    else:
        print(f"\n{C.GRAY}{'─' * width}{C.RESET}")
        print(f"  {_c(f'iter {iters}', C.BOLD)} {_c(f'session {session_id}', C.DIM)} "
              f"{_c(f'elapsed {elapsed}', C.DIM)} {_c(datetime.now().strftime('%H:%M:%S'), C.DIM)}")
        print(f"{C.GRAY}{'─' * width}{C.RESET}")


def fmt_elapsed(seconds):
    """Human-friendly elapsed: 1m 23s, 2h 14m, etc."""
    if seconds < 60:
        return f"{int(seconds)}s"
    if seconds < 3600:
        return f"{int(seconds // 60)}m {int(seconds % 60)}s"
    h = int(seconds // 3600)
    m = int((seconds % 3600) // 60)
    return f"{h}h {m}m"


def print_goal_start(goal, model, session_id=None):
    """Pretty-print the goal + model at loop start."""
    if _NO_COLOR:
        sid = session_id or "(new)"
        print(f"goal: {goal}")
        print(f"model: {model} | session: {sid}")
        return
    sid = session_id or _c("(new session)", C.DIM)
    print(f"  {_c('goal', C.BOLD)}   {goal}")
    print(f"  {_c('model', C.BOLD)}  {_c(model, C.CYAN)}  {_c(sid, C.DIM)}")
    print()


def print_interrupt(iters, session_id):
    """Clean Ctrl+C message."""
    if _NO_COLOR:
        print(f"\ninterrupted at iter {iters}. resume: goal-devin resume {session_id}")
        return
    print(f"\n  {_c('stopped', C.YELLOW)} at iter {_c(str(iters), C.BOLD)}")
    print(f"  resume with: {_c('goal-devin resume ' + session_id, C.CYAN)}")


def print_status_table(states):
    """Pretty-print all goal states as a table."""
    if not states:
        print("no goal states found.")
        return
    if _NO_COLOR:
        for s in states:
            cwd = s.get("cwd", "?")
            cwd_short = cwd.replace(str(Path.home()), "~")
            print(f"[{cwd_short}]  session={s.get('session_id', '?')}  "
                  f"iters={s.get('iters', 0)}  model={s.get('model', '?')}  "
                  f"goal={s.get('goal', '?')[:60]!r}")
        return
    for s in states:
        cwd = s.get("cwd", "?")
        cwd_short = cwd.replace(str(Path.home()), "~")
        goal = s.get("goal", "?")
        if len(goal) > 50:
            goal = goal[:47] + "..."
        print(f"  {_c(cwd_short, C.BLUE)}")
        print(f"    {_c('session', C.DIM)} {_c(s.get('session_id', '?'), C.BOLD)}  "
              f"{_c('iters', C.DIM)} {_c(str(s.get('iters', 0)), C.GREEN)}  "
              f"{_c('model', C.DIM)} {_c(s.get('model', '?'), C.CYAN)}")
        print(f"    {_c('goal', C.DIM)} {goal}")
        print()


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
    """Yield (cwd, state) for every saved state file."""
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


# --- devin subprocess ---
def run_devin(args, timeout=None):
    cmd = ["devin"] + args
    try:
        return subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
    except FileNotFoundError:
        print(f"\n  {_c('error', C.RED)}: `devin` binary not found on PATH. "
              f"Install Devin CLI first: {_c('https://devin.ai', C.CYAN)}", file=sys.stderr)
        sys.exit(2)
    except subprocess.TimeoutExpired:
        return subprocess.CompletedProcess(cmd, returncode=124, stdout="",
                                           stderr=f"timed out after {timeout}s")


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


# --- core loop ---
def run_loop(goal, session_id=None, model=None, permission_mode=None,
             sleep_secs=None, max_iters=None, iter_timeout=None, quiet=False):
    """Run the goal loop. If session_id is None, start a new session first."""
    sleep_secs = sleep_secs if sleep_secs is not None else DEFAULTS["sleep_secs"]
    max_iters = max_iters if max_iters is not None else DEFAULTS["max_iters"]
    iter_timeout = iter_timeout if iter_timeout is not None else DEFAULTS["iter_timeout"]

    if not quiet and session_id is None:
        banner()

    start_time = time.monotonic()
    iters = 0

    try:
        if session_id is None:
            # Iter 0: start fresh session.
            model = model or DEFAULTS["model"]
            permission_mode = permission_mode or DEFAULTS["permission_mode"]
            print_goal_start(goal, model)
            iter_header(0, "(new)")
            r = run_devin([
                "-p", "--model", model,
                "--permission-mode", permission_mode,
                "--", INITIAL_PROMPT.format(goal=goal),
            ], timeout=iter_timeout)
            sys.stdout.write(r.stdout)
            sys.stderr.write(r.stderr)
            if r.returncode != 0:
                print(f"\n  {_c('error', C.RED)}: devin exited {r.returncode} on iter 0, aborting.",
                      file=sys.stderr)
                return 1
            session_id = latest_session_id(os.getcwd())
            if not session_id:
                print(f"\n  {_c('error', C.RED)}: could not resolve session id from `devin list`.",
                      file=sys.stderr)
                return 1
            save_state({
                "session_id": session_id,
                "cwd": os.getcwd(),
                "goal": goal,
                "iters": 1,
                "model": model,
                "permission_mode": permission_mode,
                "started_at": datetime.now().isoformat(timespec="seconds"),
            })
            append_log(session_id, f"--- iter 0 (session {session_id}) ---\n{r.stdout}\n")
            iters = 1
        else:
            state = load_state() or {}
            iters = state.get("iters", 0) if state.get("session_id") == session_id else 0
            # ponytail: fall back to state's model/permission_mode so resume matches start
            model = model or state.get("model") or DEFAULTS["model"]
            permission_mode = permission_mode or state.get("permission_mode") or DEFAULTS["permission_mode"]
            if not goal:
                goal = state.get("goal")
            if not goal:
                print(f"  {_c('error', C.RED)}: no goal recorded for that session; pass --goal.",
                      file=sys.stderr)
                return 1
            if not quiet:
                banner()
                print_goal_start(goal, model, session_id)

        while True:
            if max_iters > 0 and iters >= max_iters:
                elapsed = fmt_elapsed(time.monotonic() - start_time)
                if not quiet:
                    print(f"\n  {_c('done', C.GREEN)} — reached max_iters={max_iters} "
                          f"({_c(elapsed, C.DIM)})")
                break
            time.sleep(sleep_secs)
            elapsed = fmt_elapsed(time.monotonic() - start_time)
            if not quiet:
                iter_header(iters, session_id, elapsed)
            r = run_devin([
                "-r", session_id, "-p",
                "--model", model,
                "--permission-mode", permission_mode,
                "--", CONTINUE_PROMPT.format(goal=goal),
            ], timeout=iter_timeout)
            sys.stdout.write(r.stdout)
            sys.stderr.write(r.stderr)
            append_log(session_id, f"--- iter {iters} ---\n{r.stdout}\n")
            iters += 1
            state = load_state() or {}
            state.update({
                "session_id": session_id,
                "cwd": os.getcwd(),
                "goal": goal,
                "iters": iters,
                "model": model,
                "permission_mode": permission_mode,
                "last_iter_at": datetime.now().isoformat(timespec="seconds"),
            })
            save_state(state)
            if r.returncode != 0:
                print(f"  {_c('warn', C.YELLOW)}: devin exited {r.returncode}; continuing.",
                      file=sys.stderr)
    except KeyboardInterrupt:
        print_interrupt(iters, session_id)
    return 0


# --- subcommands ---
def cmd_goal(args):
    return run_loop(
        goal=args.prompt,
        session_id=None,
        model=args.model,
        permission_mode=args.permission_mode,
        sleep_secs=args.sleep,
        max_iters=args.max_iters,
        iter_timeout=args.iter_timeout,
        quiet=args.quiet,
    )


def cmd_resume(args):
    state = load_state() or {}
    session_id = args.session_id or state.get("session_id")
    if not session_id:
        print(f"  {_c('error', C.RED)}: no session to resume in this directory. "
              f"Pass a session id or run {_c('goal-devin goal', C.CYAN)} first.",
              file=sys.stderr)
        return 1
    goal = args.goal or state.get("goal")
    return run_loop(
        goal=goal,
        session_id=session_id,
        model=args.model,
        permission_mode=args.permission_mode,
        sleep_secs=args.sleep,
        max_iters=args.max_iters,
        iter_timeout=args.iter_timeout,
        quiet=args.quiet,
    )


def cmd_status(args):
    if args.all:
        print_status_table(list(all_states()))
        return 0
    state = load_state()
    if not state:
        print(f"  {_c('none', C.DIM)} — no goal state in this directory.")
        print(f"  Start one: {_c('goal-devin goal \"...\"', C.CYAN)}")
        print(f"  Or see all: {_c('goal-devin status --all', C.CYAN)}")
        return 0
    print(json.dumps(state, indent=2))
    lp = log_path(state.get("session_id", ""))
    if lp.exists():
        print(f"\n  {_c('log', C.DIM)} {lp} ({lp.stat().st_size} bytes)")
    return 0


def cmd_logs(args):
    state = load_state() or {}
    session_id = args.session_id or state.get("session_id")
    if not session_id:
        print(f"  {_c('error', C.RED)}: no session id.", file=sys.stderr)
        return 1
    lp = log_path(session_id)
    if not lp.exists():
        print(f"  {_c('error', C.RED)}: no log at {lp}", file=sys.stderr)
        return 1
    if args.follow:
        # ponytail: `tail -f` via stdlib — reopen + seek loop, no subprocess dep needed
        with lp.open("r") as f:
            f.seek(0, 2)
            while True:
                chunk = f.read()
                if chunk:
                    sys.stdout.write(chunk)
                    sys.stdout.flush()
                else:
                    time.sleep(0.5)
    else:
        sys.stdout.write(lp.read_text())
    return 0


def cmd_version(args):
    print(f"goal-devin {__version__}")


# --- arg parsing ---
def build_parser():
    p = argparse.ArgumentParser(
        prog="goal-devin",
        description="Unbounded goal-loop wrapper around the Devin CLI. "
                    "Burns tokens on a fixed goal until Ctrl+C or --max-iters.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""\
examples:
  goal-devin goal "make all tests pass"
  goal-devin goal "refactor auth" --model kimi-k2.7
  goal-devin goal "fix the bug" --max-iters 10
  goal-devin resume
  goal-devin status --all
  goal-devin logs -f

stop:  Ctrl+C (or --max-iters N)
state: ~/.goal-devin/
""",
    )
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("--model", default=None, help=f"Devin model (default: {DEFAULTS['model']})")
    common.add_argument("--permission-mode", default=None,
                        help=f"permission mode (default: {DEFAULTS['permission_mode']})")
    common.add_argument("--sleep", type=float, default=None,
                        help=f"seconds between iters (default: {DEFAULTS['sleep_secs']})")
    common.add_argument("--max-iters", type=int, default=None,
                        help=f"stop after N iters, 0=forever (default: {DEFAULTS['max_iters']})")
    common.add_argument("--iter-timeout", type=float, default=None,
                        help=f"per-iter timeout in seconds (default: {DEFAULTS['iter_timeout']})")
    common.add_argument("-q", "--quiet", action="store_true", help="minimal output (for scripts)")

    sub = p.add_subparsers(dest="command", required=True)

    g = sub.add_parser("goal", parents=[common], help="Start a new goal loop.")
    g.add_argument("prompt", help="The goal prompt.")
    g.set_defaults(func=cmd_goal)

    r = sub.add_parser("resume", parents=[common], help="Resume a goal loop on an existing session.")
    r.add_argument("session_id", nargs="?", default=None, help="Session id (default: last from state).")
    r.add_argument("--goal", default=None, help="Override goal text for this run.")
    r.set_defaults(func=cmd_resume)

    s = sub.add_parser("status", help="Show goal-loop state (this dir), or all with --all.")
    s.add_argument("--all", action="store_true", help="Show all goal states across every directory.")
    s.set_defaults(func=cmd_status)

    l = sub.add_parser("logs", help="Print iteration logs for a session.")
    l.add_argument("session_id", nargs="?", default=None, help="Session id (default: last from state).")
    l.add_argument("-f", "--follow", action="store_true", help="Follow the log file (tail -f).")
    l.set_defaults(func=cmd_logs)

    v = sub.add_parser("version", help="Print version and exit.")
    v.set_defaults(func=cmd_version)
    return p


def main(argv=None):
    args = build_parser().parse_args(argv)
    ensure_dirs()
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
