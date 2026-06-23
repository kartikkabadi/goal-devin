# goal-devin

[![CI](https://github.com/kartikkabadi/goal-devin/actions/workflows/ci.yml/badge.svg)](https://github.com/kartikkabadi/goal-devin/actions/workflows/ci.yml)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)
[![Python 3.11+](https://img.shields.io/badge/python-3.11+-blue.svg)](https://www.python.org/downloads/)

Unbounded goal-loop wrapper around the [Devin CLI](https://devin.ai). Set a goal, walk away, come back to progress. Burns free GLM 5.2 / Kimi K 2.7 tokens (or any Devin model) toward a fixed goal until you stop it.

```text
  goal-devin goal "make all tests pass"
    │
    │  iter 0:  devin -p --model glm-5.2 "GOAL: ..."
    │  iter 1:  devin -r <id> -p "Continue..."
    │  iter 2:  ...
    ▼  Ctrl+C or --max-iters N
```

## Why

The Devin CLI has a `/loop` command, but it just reviews the diff in a loop — it doesn't keep working toward a goal. `goal-devin` is a real goal loop: each iteration sends "continue toward the goal" into the same session, so the model keeps context and makes real progress across iterations.

GLM 5.2 and Kimi K 2.7 are free on Devin. This tool exists to burn those free tokens unattended toward a fixed goal.

## Features

- **Goal loop** — burns tokens toward a fixed goal until you stop it (model can't self-exit)
- **git worktrees** — each goal runs on an isolated branch (on by default)
- **Devin sandbox** — OS-level isolation via `devin --sandbox` (on by default)
- **Resume** — stop a goal, resume it later in the same session
- **Multiple goals** — run goals in different directories simultaneously
- **Notifications** — desktop notification when a goal stops
- **Scriptable** — plain CLI, works in cron/CI

## Quick start

```bash
# Install
uvx --from git+https://github.com/kartikkabadi/goal-devin goal-devin goal "make tests pass"

# Or pip
pip install git+https://github.com/kartikkabadi/goal-devin
goal-devin goal "make tests pass"
```

## Install

**Prerequisite:** [Devin CLI](https://devin.ai) installed and authenticated (`devin auth login`).

```bash
# Option 1: uvx (no install, runs from git)
uvx --from git+https://github.com/kartikkabadi/goal-devin goal-devin goal "..."

# Option 2: pip
pip install git+https://github.com/kartikkabadi/goal-devin

# Option 3: from source
git clone https://github.com/kartikkabadi/goal-devin
cd goal-devin
uv sync
uv run goal-devin goal "..."
```

## Usage

```bash
# Start a goal (blocking, Ctrl+C to stop)
goal-devin goal "make all tests pass"

# With options
goal-devin goal "refactor auth" --model kimi-k2.7 --max-iters 10

# No worktree, no sandbox
goal-devin goal "..." --no-worktree --no-sandbox

# Resume
goal-devin resume
goal-devin resume quiet-falcon

# Status
goal-devin status          # this directory
goal-devin status --all    # all directories

# Logs
goal-devin logs
goal-devin logs -f         # follow

# Version
goal-devin version
```

## Sandboxing

Three layers, strongest to weakest:

### 1. Devin sandbox (OS isolation, on by default)

Uses Devin CLI's `--sandbox` flag — macOS seatbelt / Linux bwrap+seccomp. Restricts file writes to granted scopes, filters network by domain allow/deny lists. Works with any permission mode.

```bash
goal-devin goal "..." --sandbox          # on (default)
goal-devin goal "..." --no-sandbox       # off
```

### 2. git worktrees (branch isolation, on by default)

Each goal runs in `<repo-root>/.goal-wt/<worktree-id>/` on branch `goal-devin/<worktree-id>`. The model's changes don't touch your working branch. After a successful stop, merge from repo root: `git merge goal-devin/<worktree-id>`. Ctrl+C kill auto-removes the worktree.

```bash
goal-devin goal "..." --worktree         # on (default)
goal-devin goal "..." --no-worktree      # off
```

### 3. Docker (coming later)

Full container isolation. Not yet implemented.

## Multiple goals in parallel

State is keyed by directory. Run goals in different folders simultaneously:

```bash
# terminal 1
cd ~/projects/app
goal-devin goal "make tests pass"

# terminal 2
cd ~/projects/api
goal-devin goal "fix the auth bug"
```

```bash
$ goal-devin status --all
  [~/projects/app]
    session ember-turnover  iters 14  model glm-5.2  status running
    goal make all tests pass

  [~/projects/api]
    session quiet-falcon  iters 3  model kimi-k2.7  status running
    goal fix the auth bug
```

## Flags

| Flag | Default | Description |
|------|---------|-------------|
| `--model` | `glm-5.2` | Devin model |
| `--permission-mode` | `dangerous` | Permission mode |
| `--sleep` | `2` | Seconds between iterations |
| `--max-iters` | `0` | Stop after N iters (0 = forever) |
| `--iter-timeout` | `1800` | Per-iteration timeout in seconds |
| `--worktree` | on | Create git worktree for branch isolation |
| `--sandbox` | on | Use Devin's OS-level sandbox |

## Environment overrides

```bash
GOAL_DEVIN_MODEL=kimi-k2.7 \
GOAL_DEVIN_MAX_ITERS=50 \
GOAL_DEVIN_WORKTREE=0 \
goal-devin goal "..."
```

| Env var | Default |
|---------|---------|
| `GOAL_DEVIN_MODEL` | `glm-5.2` |
| `GOAL_DEVIN_PERMISSION_MODE` | `dangerous` |
| `GOAL_DEVIN_SLEEP` | `2` |
| `GOAL_DEVIN_MAX_ITERS` | `0` |
| `GOAL_DEVIN_ITER_TIMEOUT` | `1800` |
| `GOAL_DEVIN_WORKTREE` | `1` |
| `GOAL_DEVIN_SANDBOX` | `1` |
| `NO_COLOR` | unset |

## Files

| Path | Purpose |
|------|---------|
| `~/.goal-devin/states/<hash>.json` | Per-directory state |
| `~/.goal-devin/logs/<session-id>.log` | Per-session iteration logs |
| `<repo>/.goal-wt/<session-id>/` | Git worktrees (gitignored) |

## Available models

Any model the Devin CLI supports:

| Model | Slug | Notes |
|-------|------|-------|
| GLM 5.2 | `glm-5.2` | Frontier open model (default) |
| Kimi K 2.7 | `kimi-k2.7` | Code-specialized |
| Kimi K 2.6 | `kimi-k2.6` | General-purpose |
| GPT 5.5 | `gpt-5.5` | OpenAI flagship |
| GPT 5.4 Codex | `gpt-5.4-codex` | Code-tuned |
| Claude Opus 4.8 | `claude-opus-4.8` | Anthropic flagship |
| Claude Sonnet 4.6 | `claude-sonnet-4.6` | Mid-tier |
| Gemini 3.5 Flash | `gemini-3.5-flash` | Fast |
| SWE 1.6 Fast | `swe-1.6-fast` | Cognition fast |
| Adaptive | `adaptive` | Auto-router |

Run `devin --help` to see the full list on your version.

## How it works

1. **Iter 0:** calls `devin -p --model glm-5.2 "GOAL: ..."` — starts a fresh session, model does work, exits. Wrapper grabs the session id from `devin list --format json`.
2. **Iter N>0:** calls `devin -r <session-id> -p "Continue toward the goal..."` — resumes the same session, model keeps context, does more work, exits.
3. **Loop:** repeats until Ctrl+C or `--max-iters`. The model cannot stop the loop — only you stop it.

Each iteration's output is logged to `~/.goal-devin/logs/<session-id>.log`. State (session id, goal, iter count, model, status) is saved per-directory so you can resume later.

## Safety

- `--permission-mode dangerous` auto-approves all tool calls. Only run goals you trust.
- `--sandbox` (on by default) uses OS-level isolation — file writes restricted to workspace, network filtered.
- `--worktree` (on by default) isolates changes to a branch — your working branch stays clean.
- The model cannot self-exit the loop. Only Ctrl+C, kill, or `--max-iters` stops it.
- Desktop notification fires when a goal stops (max_iters reached or killed).

## Requirements

- Python 3.11+
- [Devin CLI](https://devin.ai) installed and authenticated
- No runtime dependencies

## Development

```bash
git clone https://github.com/kartikkabadi/goal-devin
cd goal-devin
uv sync
uv run pytest              # run tests
uv run goal-devin goal "..."  # run locally
```

## License

[MIT](LICENSE) — Kartik Kabadi

## See also

- [Devin CLI docs](https://developers.devin.ai/cli)
- [Loop engineering](https://addyosmani.com/blog/loop-engineering/) — the pattern this tool automates
