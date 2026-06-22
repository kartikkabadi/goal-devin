# Changelog

All notable changes to goal-devin will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

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
