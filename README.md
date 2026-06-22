# goal-devin

[![CI](https://github.com/kartikkabadi/goal-devin/actions/workflows/ci.yml/badge.svg)](https://github.com/kartikkabadi/goal-devin/actions/workflows/ci.yml)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)
[![Python 3.11+](https://img.shields.io/badge/python-3.11+-blue.svg)](https://www.python.org/downloads/)
[![Zero deps](https://img.shields.io/badge/dependencies-zero-brightgreen.svg)](#)

Unbounded goal-loop wrapper around the [Devin CLI](https://devin.ai). Set a goal, walk away, come back to progress. Burns free GLM 5.2 / Kimi K 2.7 tokens (or any Devin model) toward a fixed goal until you stop it.

```text
  goal-devin goal "make all tests pass"
    │
    │  iter 0:  devin -p --model glm-5.2 "GOAL: make all tests pass..."
    │           → model does work, prints output, exits
    │           → wrapper grabs session id
    │
    │  iter 1:  devin -r <id> -p "Continue toward the goal..."
    │           → same session, model keeps context
    │           → does more work, exits
    │
    │  iter 2:  devin -r <id> -p "Continue toward the goal..."
    │  iter 3:  ...
    │
    ▼  Ctrl+C or --max-iters N
```

## Why

The Devin CLI has a `/loop` command, but it just reviews the diff in a loop — it doesn't keep working toward a goal. `goal-devin` is a real goal loop: each iteration sends "continue toward the goal" into the same session, so the model keeps context and makes real progress across iterations.

GLM 5.2 and Kimi K 2.7 are free on Devin. This tool exists to burn those free tokens unattended toward a fixed goal.

## Quick start

```bash
# Install
uvx --from git+https://github.com/kartikkabadi/goal-devin goal-devin goal "hello"

# Or pip install
pip install git+https://github.com/kartikkabadi/goal-devin
goal-devin goal "make all tests pass"
```

That's it. The loop runs forever, working toward your goal. Ctrl+C to stop.

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

### Start a goal loop

```bash
goal-devin goal "make all tests pass"
```

Burns GLM-5.2 tokens forever, working toward the goal. Ctrl+C to stop.

### Switch model

```bash
goal-devin goal "refactor auth module" --model kimi-k2.7
goal-devin goal "..." --model gpt-5.5
```

### Bounded run

```bash
goal-devin goal "fix the failing test" --max-iters 10
```

Stops after 10 iterations automatically.

### Resume after Ctrl+C

```bash
goal-devin resume                  # resume this directory's last session
goal-devin resume quiet-falcon     # resume a specific session by id
```

### Check state

```bash
goal-devin status          # this directory's goal
goal-devin status --all    # every goal across all directories
```

### Watch logs

```bash
goal-devin logs       # print all iteration logs
goal-devin logs -f    # tail -f, live
```

### Quiet mode (for scripts)

```bash
goal-devin goal "..." --quiet    # minimal output, no banner
```

## Multiple goals in parallel

State is keyed by directory. Run goals in different folders simultaneously:

```bash
# terminal 1
cd ~/projects/app
goal-devin goal "make all tests pass"

# terminal 2
cd ~/projects/api
goal-devin goal "fix the auth bug" --model kimi-k2.7
```

```bash
$ goal-devin status --all
  ~/projects/app
    session ember-turnover  iters 14  model glm-5.2
    goal make all tests pass

  ~/projects/api
    session quiet-falcon  iters 3  model kimi-k2.7
    goal fix the auth bug
```

## Flags

| Flag | Default | Description |
|------|---------|-------------|
| `--model` | `glm-5.2` | Devin model (`glm-5.2`, `kimi-k2.7`, `gpt-5.5`, etc.) |
| `--permission-mode` | `dangerous` | Auto-approve all tool calls |
| `--sleep` | `2` | Seconds between iterations |
| `--max-iters` | `0` | Stop after N iters (0 = forever) |
| `--iter-timeout` | `1800` | Per-iteration timeout in seconds (30 min) |
| `-q`, `--quiet` | off | Minimal output (no banner, no headers) |

## Environment overrides

```bash
GOAL_DEVIN_MODEL=kimi-k2.7 \
GOAL_DEVIN_MAX_ITERS=50 \
goal-devin goal "..."
```

| Env var | Default |
|---------|---------|
| `GOAL_DEVIN_MODEL` | `glm-5.2` |
| `GOAL_DEVIN_PERMISSION_MODE` | `dangerous` |
| `GOAL_DEVIN_SLEEP` | `2` |
| `GOAL_DEVIN_MAX_ITERS` | `0` |
| `GOAL_DEVIN_ITER_TIMEOUT` | `1800` |
| `NO_COLOR` | unset |

## Files

| Path | Purpose |
|------|---------|
| `~/.goal-devin/states/<hash>.json` | Per-directory state (one per folder) |
| `~/.goal-devin/logs/<session-id>.log` | Per-session iteration logs |

## Available models

Any model the Devin CLI supports. Short names resolve to latest:

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

Run `devin --help` to see the full list on your version.

## How it works

1. **Iter 0:** calls `devin -p --model glm-5.2 --permission-mode dangerous "GOAL: ..."` — starts a fresh session, model does work, exits. Wrapper grabs the session id from `devin list --format json`.
2. **Iter N>0:** calls `devin -r <session-id> -p "Continue toward the goal..."` — resumes the same session, model keeps context, does more work, exits.
3. **Loop:** repeats until Ctrl+C or `--max-iters`. The model cannot stop the loop — only you stop it.

Each iteration's output is logged to `~/.goal-devin/logs/<session-id>.log`. State (session id, goal, iter count, model) is saved per-directory to `~/.goal-devin/states/<hash>.json` so you can resume later.

## Safety

- `--permission-mode dangerous` auto-approves all tool calls. The model can read, write, and execute anything in your workspace. Only run goals you trust.
- For unattended runs, consider Devin's `--sandbox` mode (OS-level isolation). `goal-devin` passes `--permission-mode` through, so you can set it to `auto` or `smart` if you want approval prompts.
- The model cannot self-exit the loop. Only Ctrl+C or `--max-iters` stops it. This is intentional — the whole point is unbounded token burning.

## Requirements

- Python 3.11+
- [Devin CLI](https://devin.ai) installed and authenticated
- Zero Python dependencies (stdlib only)

## Development

```bash
git clone https://github.com/kartikkabadi/goal-devin
cd goal-devin
uv sync
uv run pytest              # run tests
uv run goal-devin --help   # run locally
```

## License

[MIT](LICENSE) — Kartik Kabadi

## See also

- [Devin CLI docs](https://developers.devin.ai/cli)
- [Loop engineering](https://addyosmani.com/blog/loop-engineering/) — the pattern this tool automates
