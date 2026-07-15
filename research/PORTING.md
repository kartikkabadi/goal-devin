# Goal Devin — Python-to-Rust Porting Contract

This map is a contingency plan. It applies only if the R1C evaluation selects
Rust for the native launcher/sidecar. It preserves behavior defined in
`GOAL_DEVIN_BEHAVIOR_CONTRACT.md` and the contracts in
`research/NATIVE_INTEGRATION_TRIAL.md`.

The `agent()`/`parallel()`/`pipeline()` workflow runtime and the `ultra` command
are **superseded** historical proposals. The native `dev` mode is provisional
until the R1C language decision is approved.

| Python module/function | Current behavior | Known defects | Rust destination | Parity test | Intentional change | Migration risk |
|------------------------|------------------|---------------|------------------|-------------|--------------------|----------------|
| `src/goal_devin/__init__.py` | Version string | | `goal-devin-cli` metadata | `goal-devin --version` | none | low |
| `src/goal_devin/cli.py` | Argparse, `_run_goal_loop`, commands `goal`, `resume`, `status`, `logs`, `version` | | `goal-devin-cli` | All CLI parser tests | none for existing commands; `dev` remains experimental until R1C | low |
| `core.DEFAULTS` | Env-overridable defaults | | `goal-devin-core::config` | Env var tests | same | low |
| `core.GoalLoop` | Single-threaded `devin -p`/`devin -r` loop | Iter 0 failure ends loop | `goal-devin-core::GoalLoop` | Fake `devin` end-to-end | same | medium |
| `core.run_devin` | `subprocess.run(["devin"]+args)` | Raises `FileNotFoundError` | `goal-devin-process::DevinRunner` | Fake `devin` argv capture | same | low |
| `core.latest_session_id` | `devin list --format json` with cwd match and retries | Potential list-scope mismatch | `goal-devin-devin::session::resolve_latest` | Fake `devin` list JSON | same; prefer ATIF/ACP identity when available | medium |
| `core.state_file_for` | `~/.goal-devin/states/<md5(cwd)[:12]>.json` | | `goal-devin-core::state::path_for_cwd` | State tests | same | low |
| `core.load_state` / `save_state` | JSON load / atomic rename save | | `goal-devin-core::state` | Roundtrip tests | same | low |
| `core.append_log` | `~/.goal-devin/logs/<sid>.log` append | | `goal-devin-core::log` | Log tests | same | low |
| `core.notify_*` | Desktop + bell | | `goal-devin-cli::notify` | Mocked tests | same | low |
| `worktree.py` all | Git worktree create/remove/merge/list | | `goal-devin-git` | Worktree tests | same | medium |

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

A Rust implementation must read this JSON as-is. Native launcher/sidecar state
for the `dev` mode must be stored under
`~/.goal-devin/runtime/<run-id>/` and kept separate from the `goal`/`resume`
state directory.

## Command compatibility

All current commands (`goal`, `resume`, `status`, `logs`, `version`) must keep
the same flags, env vars, and exit codes. The `dev` command is provisional and
only becomes a production command after the R1C decision.

## Environment variables

`GOAL_DEVIN_MODEL`, `GOAL_DEVIN_PERMISSION_MODE`, `GOAL_DEVIN_SLEEP`,
`GOAL_DEVIN_MAX_ITERS`, `GOAL_DEVIN_ITER_TIMEOUT`, `GOAL_DEVIN_WORKTREE`,
`GOAL_DEVIN_SANDBOX`, `NO_COLOR` must be honored.

## Worktree / resume compatibility

- Existing `~/.goal-devin/` and `.goal-wt/` must not be deleted by the new binary.
- `goal-devin resume` must find old session states.
- Worktree branches `goal-devin/<id>` must remain mergeable.

## Rollback

If a Rust implementation ships for the launcher/sidecar, the existing Python
`GoalLoop`/worktree/state layer should remain installable as the behavioral
oracle until parity is fully proven.
