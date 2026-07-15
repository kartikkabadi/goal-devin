# Goal Devin — Current Baseline

Base commit: `a7bdb9fda37b1308d0ebbdfcb1cffed670e49c4a`

## 1. Repository tree

```
.goal-devin/
.goal-wt/
.github/workflows/ci.yml
CHANGELOG.md
CONTRIBUTING.md
LICENSE
README.md
SECURITY.md
pyproject.toml
src/goal_devin/
  __init__.py
  __main__.py
  cli.py
  core.py
  worktree.py
tests/
  test_cli.py
  test_core.py
  test_worktree.py
```

## 2. Package metadata

- Name: `goal-devin`
- Version: `0.6.0`
- Python: `>=3.11`
- Entry point: `goal-devin = goal_devin.cli:main`
- Build backend: `uv_build`
- Runtime dependencies: none (stdlib only)
- Dev dependencies: `pytest>=8`, `ruff>=0.15`

## 3. Public CLI commands and flags

| Command | Args | Purpose |
|---------|------|---------|
| `goal-devin goal <prompt>` | `--model`, `--permission-mode`, `--sleep`, `--max-iters`, `--iter-timeout`, `--worktree`/`--no-worktree`, `--sandbox`/`--no-sandbox` | Start a new single-session goal loop. |
| `goal-devin resume [session-id]` | same as `goal` | Resume a loop on an existing session. |
| `goal-devin status [--all]` | `--all` | Show per-directory state or all states. |
| `goal-devin logs [session-id]` | `-f`/`--follow` | Print or follow the session log. |
| `goal-devin version` | | Print version. |
| `goal-devin --version` / `-V` | | Print version. |
| `goal-devin help` | | Print help. |

## 4. Environment variable defaults

| Variable | Default | Used in |
|----------|---------|---------|
| `GOAL_DEVIN_MODEL` | `glm-5.2` | `core.DEFAULTS` |
| `GOAL_DEVIN_PERMISSION_MODE` | `dangerous` | `core.DEFAULTS` |
| `GOAL_DEVIN_SLEEP` | `2` | `core.DEFAULTS` |
| `GOAL_DEVIN_MAX_ITERS` | `0` (forever) | `core.DEFAULTS` |
| `GOAL_DEVIN_ITER_TIMEOUT` | `1800` | `core.DEFAULTS` |
| `GOAL_DEVIN_WORKTREE` | `1` | `core.DEFAULTS` |
| `GOAL_DEVIN_SANDBOX` | `1` | `core.DEFAULTS` |
| `NO_COLOR` | unset | `cli._NO_COLOR` |

## 5. Process invocation paths

### Iteration 0 (new session)

```python
["devin", "-p", "--model", <model>, "--permission-mode", <mode>]
# if use_sandbox: append "--sandbox"
# then: ["--", INITIAL_PROMPT.format(goal=goal)]
```

### Iteration N>0 (resume)

```python
["devin", "-r", <session_id>, "-p", "--model", <model>, "--permission-mode", <mode>]
# if use_sandbox: append "--sandbox"
# then: ["--", CONTINUE_PROMPT.format(goal=goal)]
```

### Session resolution

```python
["devin", "list", "--format", "json"]
```

The newest session whose `working_directory` canonicalizes to the loop `cwd` is used. No fallback to `sessions[0]` is allowed.

### Worktree management

```python
["git", "worktree", "add", str(wt), "-b", branch]   # create
["git", "worktree", "remove", "--force", str(wt)]     # cleanup
["git", "branch", "-D", branch]                       # cleanup
["git", "worktree", "list", "--porcelain"]            # list
["git", "merge", "--no-ff", branch, "-m", ...]        # merge
```

Worktree path: `<repo-root>/.goal-wt/<worktree-id>`  
Branch: `goal-devin/<worktree-id>`  
Gitignore entry: `.goal-wt/`

## 6. State format

Per-directory state file: `~/.goal-devin/states/<md5(cwd)[:12]>.json`

Representative state fields:

```json
{
  "session_id": "...",
  "cwd": "/abs/path",
  "goal": "...",
  "iters": 5,
  "model": "glm-5.2",
  "permission_mode": "dangerous",
  "use_worktree": true,
  "use_sandbox": true,
  "worktree_id": "goal-abc123",
  "status": "running",
  "started_at": "2026-07-15T08:00:00",
  "last_iter_at": "2026-07-15T08:05:00"
}
```

State is written atomically via a `.json.tmp` + rename.

## 7. Logging

Per-session log: `~/.goal-devin/logs/<session_id>.log`

Each iteration appends a delimiter:

```text
--- iter 0 (session <sid>) ---
<devin stdout>
--- iter N ---
<devin stdout>
```

## 8. Notifications

- macOS: `osascript -e 'display notification "..." with title "..."'`
- Linux: `notify-send <title> <message>`
- Terminal bell (`\a`) unless suppressed.

## 9. Sandbox behavior

- `--sandbox` is passed to `devin` when enabled.
- Goal Devin treats it as a flag only; it does not implement its own sandbox.
- Comment in `core.py`: *"sandbox is just a flag — it enforces OS-level isolation on exec tool; it works with any permission mode, no need to override."*

## 10. Worktree behavior

- Created for every `goal` when `is_git_repo()` is true and not disabled.
- Worktree ID is `goal-<uuid[:8]>`.
- On `kill`, `GoalLoop._finish` removes the worktree and branch.
- On `max_iters` or `error`, the worktree is kept for manual merge/debug.
- Resume checks whether the worktree path still exists and falls back to `os.getcwd()` if not.

## 11. Interruption behavior

- `Ctrl+C` in the CLI sets `GoalLoop.kill_event`, calls `loop.kill()`, which terminates the current `devin` subprocess.
- The background thread exits and `on_done("killed", ...)` is invoked.
- Worktree cleanup runs for killed goals.

## 12. Timeout behavior

- Each `devin` subprocess is wrapped with `Popen.communicate(timeout=iter_timeout)`.
- On timeout, the process is killed and a synthetic `CompletedProcess` with return code `124` is returned.
- The loop treats non-zero exit codes as warnings and continues (`if r.returncode != 0 and self.on_status: ..."devin exited N; continuing"`).

## 13. Exit / concurrency behavior

- The loop is single-threaded per goal; one `devin` process at a time.
- Multiple goals can run concurrently in different directories because state is keyed by `cwd` hash.
- The model cannot stop the loop; only `Ctrl+C`, `kill`, or `--max-iters` ends it.
- `cmd_goal` returns `0` unless the loop ends with `reason == "error"`.

## 14. Tests

- `tests/test_core.py` — state, log path, latest session resolution, `GoalLoop` behavior, worktree cleanup, notifications.
- `tests/test_cli.py` — resume argument routing, no-args help, no-worktree flag.
- `tests/test_worktree.py` — git worktree create/remove/merge/list.
- All use `unittest` and `unittest.mock`.

## 15. CI

`.github/workflows/ci.yml`:
- Test matrix: Python 3.11, 3.12, 3.13 (`uv sync --dev`, `uv run pytest -v`, `uv run goal-devin --help`).
- Lint: `uv run ruff check .`, `uv run ruff format --check .`.
- Build: `uv build`, upload `dist/`.
- Socket Firewall (`socketdev/action`) wraps dependency install.

## 16. Documented behavior vs. actual behavior

- README documents `--sandbox` and `--worktree` defaults as `on`; `core.DEFAULTS` honors `GOAL_DEVIN_WORKTREE=0` and `GOAL_DEVIN_SANDBOX=0` exactly as documented.
- README says manual `git merge` after successful stop; actual code does not auto-merge.
- `latest_session_id` explicitly rejects the old "first session" fallback; this matches the CHANGELOG fix for session contamination.
- `--permission-mode dangerous` auto-approves all tool calls; this is passed to `devin`.

## 17. Suspected defects / sharp edges

- `latest_session_id` polls `devin list` with retries. If Devin lists sessions slowly, iter 0 can fail with "could not resolve session id" even though the session exists.
- `GoalLoop` does not retry a failed iter 0; any non-zero exit from `devin -p` ends the loop.
- `GoalLoop._run_devin` raises `FileNotFoundError` and the outer `_run` reports `devin binary not found`; the CLI does not preflight-check `devin`.
- The loop sleeps for `sleep_secs` before starting iteration 1, not before iteration 0.
- `devin -r <sid> -p` output is appended to the log even if `devin` exits non-zero.
- There is no concurrency; one goal = one process at a time.
- Worktree cleanup on kill is initiated from `_finish`, but the `remove_worktree` subprocess could itself fail if the branch is dirty.

## 18. Behavior that must be preserved in a rewrite

- Per-directory state keyed by `cwd` hash.
- Atomic state writes.
- Observable session continuity and existing state-file compatibility.
- Explicit session resume behavior.
- `devin -p` for iter 0 and `devin -r <sid> -p` for continuation.
- Session identity: prefer `devin -p --export` ATIF and ACP `session/new`; test
  native TUI `--export` support; keep `devin list --format json` matching
  `working_directory` (with retries, no fallback) only as a compatibility
  fallback with a known concurrency race.
- Never parse Devin's private `sessions.db`.
- Worktree creation/cleanup semantics (kill removes, max_iters/error keeps).
- Worktree path fallback on resume.
- CLI flag/env names and defaults.
- `goal`, `resume`, `status`, `logs`, `version` commands.
- `NO_COLOR` support.

Public session-continuity behavior is not the same as the race-prone
`latest_session_id()` implementation. A rewrite may replace the list-based
heuristic with ATIF/ACP identity as those seams become available and tested.

## 19. Superseded historical proposals

Earlier drafts proposed a dynamic workflow runtime (`agent`/`parallel`/`pipeline`),
an `ultra` command, planner-generated workflow scripts, and a live Goal Devin
dashboard. These are **superseded** by the corrected product scope in
`research/PRODUCT_SCOPE.md` and the native-integration trial contract in
`research/NATIVE_INTEGRATION_TRIAL.md`.

The canonical future direction is:

- Preserve and harden the existing `goal`/`resume` loop.
- Add a `goal-devin dev` native mode that launches the genuine `devin` TUI with
  Goal Devin-owned status, policy, and verification.
- Use native Devin subagents for in-session work; use independent `devin -p`
  sessions only for explicitly independent Goal Devin jobs.
- No `agent()`/`parallel()`/`pipeline()` workflow scripting DSL and no `ultra`
  command.
