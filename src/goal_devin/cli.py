"""Hidden CLI for goal-devin (scriptable mode).

The primary interface is the TUI (goal-devin with no args). This CLI is kept
for scripts/cron/CI: `goal-devin -- goal "..."` or subcommands.

Usage:
  goal-devin                          # launch TUI (default)
  goal-devin -- goal "make tests pass"  # hidden CLI: start goal
  goal-devin -- resume [session-id]    # hidden CLI: resume
  goal-devin -- status [--all]         # hidden CLI: status
  goal-devin -- logs [session-id] [-f] # hidden CLI: logs
  goal-devin -- version                # hidden CLI: version
"""
import argparse
import json
import os
import sys
import threading
import time
import uuid
from pathlib import Path

from . import core
from .core import (
    GoalLoop, load_state, all_states, find_state_by_session_id, log_path,
    fmt_elapsed, DEFAULTS, notify,
)
from .worktree import is_git_repo, create_worktree, remove_worktree


# --- ANSI colors (stdlib) ---
class C:
    RESET = "\033[0m"
    BOLD = "\033[1m"
    DIM = "\033[2m"
    RED = "\033[31m"
    GREEN = "\033[32m"
    YELLOW = "\033[33m"
    BLUE = "\033[34m"
    CYAN = "\033[36m"
    GRAY = "\033[90m"

_NO_COLOR = not sys.stdout.isatty() or os.environ.get("NO_COLOR")

def _c(text, color):
    if _NO_COLOR:
        return text
    return f"{color}{text}{C.RESET}"


def _run_goal_loop(goal, session_id=None, model=None, permission_mode=None,
                   sleep_secs=None, max_iters=None, iter_timeout=None,
                   use_worktree=False, use_sandbox=False, cwd=None,
                   worktree_id=None):
    """Start a GoalLoop and block until it finishes or Ctrl+C. Returns exit code."""
    done_event = threading.Event()
    result = {"reason": None, "iters": 0, "elapsed": 0}

    def on_iter(iters, sid, output, elapsed):
        elapsed_str = fmt_elapsed(elapsed)
        print(f"\n  {_c(f'iter {iters}', C.BOLD)} | "
              f"{_c(sid, C.DIM)} | "
              f"{_c(elapsed_str, C.DIM)}")
        if output:
            print(output)

    def on_done(reason, iters, elapsed):
        result["reason"] = reason
        result["iters"] = iters
        result["elapsed"] = elapsed
        # ponytail: remove worktree on kill — user discarded the work.
        # max_iters/error keep worktree so user can merge/debug.
        if reason == "killed" and use_worktree and worktree_id:
            ok, err = remove_worktree(worktree_id, cwd=cwd, force=True)
            if not ok:
                print(f"  {_c('warn', C.YELLOW)} worktree cleanup failed: {err}", file=sys.stderr)
        done_event.set()

    def on_status(status, detail):
        if status == core.STATUS_ERROR:
            print(f"  {_c('error', C.RED)}: {detail}", file=sys.stderr)

    loop = GoalLoop(
        goal=goal,
        session_id=session_id,
        model=model,
        permission_mode=permission_mode,
        sleep_secs=sleep_secs,
        max_iters=max_iters,
        iter_timeout=iter_timeout,
        use_worktree=use_worktree,
        use_sandbox=use_sandbox,
        cwd=cwd,
        worktree_id=worktree_id,
        on_iter=on_iter,
        on_status=on_status,
        on_done=on_done,
    )
    loop.start()

    print(f"  {_c('goal-devin', C.BOLD)} v{core.__version__}")
    print(f"  {_c('goal', C.BOLD)}   {goal}")
    sid_display = session_id or _c("(new session)", C.DIM)
    print(f"  {_c('model', C.BOLD)}  {_c(loop.model, C.CYAN)}  {sid_display}")
    if use_sandbox:
        print(f"  {_c('sandbox', C.BOLD)} on (OS isolation)")
    if use_worktree:
        print(f"  {_c('worktree', C.BOLD)} {cwd}")
    print()

    try:
        while not done_event.is_set():
            time.sleep(0.5)
    except KeyboardInterrupt:
        loop.kill()
        done_event.wait(timeout=5)

    reason = result["reason"]
    iters = result["iters"]
    elapsed_str = fmt_elapsed(result["elapsed"])
    if reason == "max_iters":
        print(f"\n  {_c('done', C.GREEN)} — {iters} iters in {elapsed_str}")
    elif reason == "killed":
        print(f"\n  {_c('stopped', C.YELLOW)} at iter {iters} ({elapsed_str})")
    elif reason == "error":
        print(f"\n  {_c('error', C.RED)} at iter {iters}")
    notify("goal-devin", f"goal {reason}: {iters} iters in {elapsed_str}")
    return 0 if reason != "error" else 1


def cmd_goal(args):
    """Start a new goal loop (blocking, Ctrl+C to stop)."""
    use_worktree = args.worktree and is_git_repo()
    use_sandbox = args.sandbox
    cwd = os.getcwd()
    worktree_id = None

    if use_worktree:
        worktree_id = f"goal-{uuid.uuid4().hex[:8]}"
        wt_path, err = create_worktree(worktree_id, cwd=cwd)
        if wt_path:
            cwd = str(wt_path)
        else:
            print(f"  {_c('warn', C.YELLOW)} worktree failed: {err}")
            use_worktree = False
            worktree_id = None

    permission_mode = args.permission_mode
    return _run_goal_loop(
        goal=args.prompt,
        model=args.model,
        permission_mode=permission_mode,
        sleep_secs=args.sleep,
        max_iters=args.max_iters,
        iter_timeout=args.iter_timeout,
        use_worktree=use_worktree,
        use_sandbox=use_sandbox,
        cwd=cwd,
        worktree_id=worktree_id,
    )


def cmd_resume(args):
    """Resume a goal loop on an existing session."""
    state = load_state() or {}
    session_id = args.session_id or state.get("session_id")
    if not session_id:
        print(f"  {_c('error', C.RED)}: no session to resume.", file=sys.stderr)
        return 1
    # if current cwd has no state, search all states for this session_id
    if not state.get("session_id"):
        found = find_state_by_session_id(session_id)
        if found:
            state = found
    goal = args.goal or state.get("goal")
    if not goal:
        print(f"  {_c('error', C.RED)}: no goal recorded.", file=sys.stderr)
        return 1
    cwd = state.get("cwd", os.getcwd())
    worktree_id = state.get("worktree_id")
    use_worktree = state.get("use_worktree", False)
    use_sandbox = state.get("use_sandbox", False)
    permission_mode = args.permission_mode or state.get("permission_mode")
    return _run_goal_loop(
        goal=goal,
        session_id=session_id,
        model=args.model or state.get("model"),
        permission_mode=permission_mode,
        sleep_secs=args.sleep,
        max_iters=args.max_iters,
        iter_timeout=args.iter_timeout,
        use_worktree=use_worktree,
        use_sandbox=use_sandbox,
        cwd=cwd,
        worktree_id=worktree_id,
    )


def cmd_status(args):
    if args.all:
        states = list(all_states())
        if not states:
            print("no goal states found.")
            return 0
        for s in states:
            cwd = s.get("cwd", "?").replace(str(Path.home()), "~")
            goal = s.get("goal", "?")
            if len(goal) > 50:
                goal = goal[:47] + "..."
            status = s.get("status", "?")
            color = {
                "running": C.GREEN, "paused": C.YELLOW,
                "stopped": C.GRAY, "killed": C.RED, "error": C.RED,
            }.get(status, C.GRAY)
            print(f"  [{_c(cwd, C.BLUE)}]")
            print(f"    {_c('session', C.DIM)} {_c(s.get('session_id', '?'), C.BOLD)}  "
                  f"{_c('iters', C.DIM)} {_c(str(s.get('iters', 0)), C.GREEN)}  "
                  f"{_c('model', C.DIM)} {_c(s.get('model', '?'), C.CYAN)}  "
                  f"{_c('status', C.DIM)} {_c(status, color)}")
            print(f"    {_c('goal', C.DIM)} {goal}")
            print()
        return 0
    state = load_state()
    if not state:
        print(f"  {_c('none', C.DIM)} — no goal state in this directory.")
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
    print(f"goal-devin {core.__version__}")


def build_parser():
    p = argparse.ArgumentParser(
        prog="goal-devin",
        description="Unbounded goal-loop wrapper around the Devin CLI. "
                    "Run with no args for TUI, or use subcommands for scripts.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""\
TUI mode (default):
  goal-devin                          # launch interactive TUI

hidden CLI mode (for scripts):
  goal-devin -- goal "make tests pass"
  goal-devin -- goal "..." --model kimi-k2.7 --max-iters 10
  goal-devin -- resume
  goal-devin -- status --all
  goal-devin -- logs -f

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
    common.add_argument("--worktree", action="store_true", default=DEFAULTS["use_worktree"],
                        help="create git worktree for branch isolation")
    common.add_argument("--no-worktree", action="store_false", dest="worktree",
                        help="don't create git worktree")
    common.add_argument("--sandbox", action="store_true", default=DEFAULTS["use_sandbox"],
                        help="use devin --sandbox (OS isolation, OS-level exec isolation)")
    common.add_argument("--no-sandbox", action="store_false", dest="sandbox",
                        help="don't use devin sandbox")

    sub = p.add_subparsers(dest="command")

    g = sub.add_parser("goal", parents=[common], help="Start a new goal loop.")
    g.add_argument("prompt", help="The goal prompt.")
    g.set_defaults(func=cmd_goal)

    r = sub.add_parser("resume", parents=[common], help="Resume a goal loop.")
    r.add_argument("session_id", nargs="?", default=None, help="Session id.")
    r.add_argument("--goal", default=None, help="Override goal text.")
    r.set_defaults(func=cmd_resume)

    s = sub.add_parser("status", help="Show goal state.")
    s.add_argument("--all", action="store_true", help="Show all goals.")
    s.set_defaults(func=cmd_status)

    l = sub.add_parser("logs", help="Print logs.")
    l.add_argument("session_id", nargs="?", default=None, help="Session id.")
    l.add_argument("-f", "--follow", action="store_true", help="Follow log.")
    l.set_defaults(func=cmd_logs)

    v = sub.add_parser("version", help="Print version.")
    v.set_defaults(func=cmd_version)
    return p


def main(argv=None):
    """Entry point. No args → TUI. Subcommands → hidden CLI."""
    if argv is None:
        argv = sys.argv[1:]
    if not argv:
        from .tui import run_tui
        run_tui()
        return 0
    if argv in (["--help"], ["-h"], ["help"]):
        build_parser().print_help()
        return 0
    if argv in (["version"], ["--version"], ["-V"]):
        print(f"goal-devin {core.__version__}")
        return 0
    args = build_parser().parse_args(argv)
    core.ensure_dirs()
    if not getattr(args, "func", None):
        build_parser().print_help()
        return 1
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
