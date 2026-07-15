# Goal Devin — Python-to-Rust Porting Contract

This map is a contingency plan. It is only relevant if the project later decides to rewrite in Rust. It preserves behavior defined in `GOAL_DEVIN_BEHAVIOR_CONTRACT.md`.

| Python module/function | Current behavior | Known defects | Rust destination | Parity test | Intentional change | Migration risk |
|------------------------|------------------|---------------|------------------|-------------|--------------------|----------------|
| `src/goal_devin/__init__.py` | Version string | | `goal-devin-cli` metadata | `goal-devin --version` | none | low |
| `src/goal_devin/cli.py` | Argparse, `_run_goal_loop`, commands `goal`, `resume`, `status`, `logs`, `version` | | `goal-devin-cli` | All CLI parser tests | Add `ultra` command | medium |
| `core.DEFAULTS` | Env-overridable defaults | | `goal-devin-core::config` | Env var tests | same | low |
| `core.GoalLoop` | Single-threaded `devin -p`/`devin -r` loop | Iter 0 failure ends loop; no concurrency | `goal-devin-core::GoalLoop` | Fake `devin` end-to-end | Keep for `goal`/`resume`; `ultra` uses new runtime | high if changed |
| `core.run_devin` | `subprocess.run(["devin"]+args)` | Raises `FileNotFoundError` | `goal-devin-process::DevinRunner` | Fake `devin` argv capture | same | low |
| `core.latest_session_id` | `devin list --format json` with cwd match and retries | Potential list-scope mismatch | `goal-devin-devin::session::resolve_latest` | Fake `devin` list JSON | same | high |
| `core.state_file_for` | `~/.goal-devin/states/<md5(cwd)[:12]>.json` | | `goal-devin-core::state::path_for_cwd` | State tests | same | low |
| `core.load_state` / `save_state` | JSON load / atomic rename save | | `goal-devin-core::state` | Roundtrip tests | same | low |
| `core.append_log` | `~/.goal-devin/logs/<sid>.log` append | | `goal-devin-core::log` | Log tests | same | low |
| `core.notify_*` | Desktop + bell | | `goal-devin-cli::notify` | Mocked tests | same | low |
| `worktree.py` all | Git worktree create/remove/merge/list | | `goal-devin-git` | Worktree tests | same | medium |
| `ultra` (planned) | `agent`, `parallel`, `pipeline`, `phase`, `log`, `budget`, `args` | | `goal-devin-core::workflow` + `goal-devin-tui` | New tests | new feature | n/a |

## State schema migration

Current state JSON:

```json
{
  "session_id": "...",
  "cwd": "...",
  "goal": "...",
  "iters": 1,
  "model": "glm-5.2",
  "permission_mode": "dangerous",
  "use_worktree": true,
  "use_sandbox": false,
  "worktree_id": "goal-...",
  "status": "running|stopped|killed|error",
  "started_at": "...",
  "last_iter_at": "..."
}
```

A Rust rewrite must read this JSON as-is. New `ultra` state should be stored in a separate `~/.goal-devin/workflows/<run_id>/` directory to avoid collision.

## Command compatibility

All current commands (`goal`, `resume`, `status`, `logs`, `version`) must keep the same flags, env vars, and exit codes.

## Environment variables

`GOAL_DEVIN_MODEL`, `GOAL_DEVIN_PERMISSION_MODE`, `GOAL_DEVIN_SLEEP`, `GOAL_DEVIN_MAX_ITERS`, `GOAL_DEVIN_ITER_TIMEOUT`, `GOAL_DEVIN_WORKTREE`, `GOAL_DEVIN_SANDBOX`, `NO_COLOR` must be honored.

## Worktree / resume compatibility

- Existing `~/.goal-devin/` and `.goal-wt/` must not be deleted by the new binary.
- `goal-devin resume` must find old session states.
- Worktree branches `goal-devin/<id>` must remain mergeable.

## Rollback

If a Rust rewrite ships, keep the Python version installable as `goal-devin-py` or provide a `goal-devin migrate` command to downgrade state.
