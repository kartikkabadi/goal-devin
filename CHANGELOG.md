# Changelog

All notable changes to goal-devin will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [0.3.0] - 2026-06-22

### Added
- In-memory goal registry — GoalDevinApp maintains `session_id -> GoalState` dict as the single source of truth for the TUI while running. State files remain for cross-restart persistence only.
- Real-time TUI updates via callbacks — GoalLoop's on_iter/on_status/on_done now update the in-memory GoalState via `call_from_thread`, replacing 2-second file polling.
- Pre-iter-0 state — goals appear in the list instantly with status="starting" before the first devin call completes. Session ID is remapped from temp key to real ID on first iter.
- Live elapsed timer — 1-second timer updates elapsed time for running goals without re-reading files.
- Toast notifications — error and completion notifications via Textual's `notify()`.
- Startup recovery — on mount, all state files are loaded into the registry as "stopped" so previous-session goals are visible.
- ctrl+s keybinding in NewGoalScreen to start a goal without a mouse.
- 9 TUI integration tests using Textual's `run_test()` pilot (start, iter, kill, error, recovery).
- pytest-asyncio dev dependency for async TUI tests.

### Changed
- MainScreen reads from `app.goals` registry instead of `all_states()` disk scan.
- GoalDetailScreen reads from registry, refreshes info panel + log tail every 1s.
- GoalListItem renders from GoalState with status, iters, elapsed.
- GoalListItem no longer renders unused model/last_output fields.
- AdvancedScreen actions are info-only (show current settings, don't change them).
- CONTRIBUTING.md updated — reflects multi-module structure and textual dep.
- README updated — ctrl+s binding, removed q binding, corrected test count (52), accurate AdvancedScreen docs.

### Fixed
- AdvancedScreen `action_worktree` crashed with NameError — `wt` module was never imported. Now uses `list_worktrees` directly.
- GoalListItem had unused `model` and `last` variables.
- Inline imports in MainScreen._tick_elapsed and action_resume_goal moved to module level.
- core.py had unused `field` import from dataclasses.
- SECURITY.md hardening section used wrong CLI syntax (`goal-devin goal` instead of `goal-devin -- goal`).

### Removed
- 2-second file-polling timer in MainScreen (replaced by callback-driven updates).
- 'q' keybinding (ctrl+c quits the TUI).


## [0.2.0] - 2026-06-22

### Added
- Textual TUI — full-screen terminal UI with arrow-key navigation, model picker, toggles.
  - MainScreen: goal list + normal menu (n/r/s/l/a/q)
  - NewGoalScreen: prompt + model picker + worktree/sandbox toggles + max iters
  - GoalDetailScreen: goal info + log tail + pause/resume/kill/merge
  - AdvancedScreen: model/permission/worktree/timeout/sleep/kill/export/delete
  - LogsScreen: full log viewer + follow mode
- git worktree support — each goal runs on isolated branch `goal-devin/<session-id>` at `<repo>/.goal-wt/<session-id>/`. On by default. Auto-gitignored.
- Devin sandbox support — `--sandbox` flag uses OS-level isolation (macOS seatbelt / Linux bwrap+seccomp). Forces `autonomous` permission mode. On by default.
- Pause / kill — pause a running goal, resume later, or kill it. Uses threading events.
- Goal status tracking — state file now includes `status` field: running / paused / stopped / killed / error.
- Desktop notifications — osascript (macOS) / notify-send (Linux) + terminal bell when a goal stops.
- Hidden CLI mode — `goal-devin -- goal "..."` for scripts/cron/CI. TUI is default, CLI is hidden.
- `--worktree` / `--no-worktree` and `--sandbox` / `--no-sandbox` flags.
- `GOAL_DEVIN_WORKTREE` and `GOAL_DEVIN_SANDBOX` env overrides.
- Model picker with hardcoded list + refresh button (parses from `devin --help`).
- `core.py` extracted — UI-agnostic core logic (GoalLoop class, state, devin subprocess).
- `worktree.py` — git worktree create/list/remove/merge module.
- 30 tests (test_core.py + test_worktree.py).

### Changed
- Default interface is now TUI (was CLI). Running `goal-devin` with no args launches TUI.
- `textual>=0.80` is now a dependency (was zero-dep).
- Version bumped to 0.2.0.
- README rewritten with TUI docs, sandbox docs, key bindings table.
- CI updated — removed zero-deps check, added textual to install.

### Removed
- Zero-dependency claim (textual is now required for TUI).
- Old CLI banner / subcommand-style help (replaced by TUI + hidden CLI).


## [0.1.0] - 2026-06-22

### Added
- Initial release.
- `goal-devin goal "..."` — start an unbounded goal loop on GLM 5.2 (default) or any Devin model.
- `goal-devin resume [session-id]` — resume a goal loop on an existing session.
- `goal-devin status [--all]` — show goal-loop state (per-directory, or all).
- `goal-devin logs [session-id] [-f]` — print or follow iteration logs.
- `goal-devin version` — print version.
- Per-directory state isolation (`~/.goal-devin/states/<hash>.json`) — concurrent goals in different folders don't collide.
- Per-session iteration logs (`~/.goal-devin/logs/<session-id>.log`).
- ANSI-colored UI: banner, iter headers with elapsed timer, pretty status table, clean Ctrl+C message.
- `--quiet` / `-q` flag for script-friendly minimal output.
- `NO_COLOR` env var support.
- Flags: `--model`, `--permission-mode`, `--sleep`, `--max-iters`, `--iter-timeout`.
- Env overrides: `GOAL_DEVIN_MODEL`, `GOAL_DEVIN_PERMISSION_MODE`, `GOAL_DEVIN_SLEEP`, `GOAL_DEVIN_MAX_ITERS`, `GOAL_DEVIN_ITER_TIMEOUT`.
- Atomic state writes (temp + rename) — no corruption on kill.
- Per-iteration timeout (default 30 min) — hung iterations don't block the loop.
- Retry logic for session id resolution (handles `devin list` lag).
- Clean error on missing `devin` binary.
- Ctrl+C caught during iter 0 (not just the while loop).
- Resume falls back to state's model/permission_mode so it matches the original start.
- Zero Python dependencies (stdlib only).
- MIT License.
