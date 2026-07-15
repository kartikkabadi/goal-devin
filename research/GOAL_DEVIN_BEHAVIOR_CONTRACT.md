# Goal Devin — Black-Box Behavior Contract

This document defines observable behavior that a future implementation (including a Rust rewrite) must satisfy. It was produced by running the current `goal-devin` against a deterministic fake `devin` executable in isolated `HOME` and canary Git repositories. All raw evidence lives in `.research-evidence/` and is gitignored.

## Test harness

`research/fixtures/fake-devin` is a Python stand-in that:

- Records every invocation (`argv`, `cwd`, environment key names, stdout, stderr, exit code, created session id, timestamp) in `invocations.jsonl`.
- Maintains `sessions.jsonl` with session records matching the keys `goal-devin` uses: `id`, `working_directory`, `prompt`, `model`, `permission_mode`, `sandbox`, `created_at`.
- Supports `devin --version`, `devin --help`, `devin list --format json`, `devin -p ... -- <prompt>`, `devin -r <sid> -p ... -- <prompt>`, and `devin auth status`.
- Exposes `GOAL_DEVIN_FAKE_STATE` for isolation.

The fixture is installed as `devin` on a temporary `PATH` and `HOME` is pointed to `.research-evidence/home-test` so no real user files are modified.

## Command matrix (observed)

| Command | CWD | TTY | Args passed to `devin` iter 0 | Args passed to `devin` continuation | State file key | Exit | Side effects |
|---------|-----|-----|-------------------------------|--------------------------------------|----------------|------|--------------|
| `goal-devin goal "P" --max-iters 1 --no-worktree` | canary | no | `devin -p --model glm-5.2 --permission-mode dangerous -- GOAL: P...` | none | `~/.goal-devin/states/<md5(cwd)>.json` | `0` | log, state |
| `goal-devin goal "P" --max-iters 1` (worktree default) | canary | no | `devin -p --model glm-5.2 --permission-mode dangerous -- GOAL: P...` (cwd = worktree) | none | same | `0` | git worktree created, kept after stop |
| `goal-devin resume <sid> --max-iters 2` | canary | no | none | `devin -r <sid> -p --model glm-5.2 --permission-mode dangerous -- CONTINUE_PROMPT` | same | `0` | log appended, iters increments |
| `goal-devin status` | main repo | no | none | none | local state | `0` | none |
| `goal-devin status --all` | any | no | none | none | all states | `0` | none |
| `goal-devin logs <sid>` | any | no | none | none | log file | `0` | none |
| `goal-devin version` | any | no | none | none | none | `0` | none |

## Observable invariants

1. **Per-cwd state**. `goal-devin` uses `state_file_for(cwd)` = `~/.goal-devin/states/<md5(resolved cwd)[:12]>.json`. Running the same goal in two different directories produces two different state files.
2. **Atomic state writes**. The state file is written as `*.json.tmp` and renamed; no partial JSON is observed after a crash.
3. **Session resolution via `devin list`**. After iter 0, `goal-devin` calls `devin list --format json` and selects the newest session whose `working_directory` exactly matches the loop `cwd` (which is the worktree path when worktree is enabled). It does **not** fall back to `sessions[0]`.
4. **Iter 0 failure ends the loop**. Any non-zero exit from `devin -p` on iter 0 causes `reason="error"` and CLI exit `1`. Non-zero exits on continuation iterations are logged and the loop continues.
5. **Worktree lifecycle**. `create_worktree` is called before iter 0 when the repo is git and worktree is enabled. `remove_worktree` is called only when `reason == "killed"`; `max_iters` and `error` keep the worktree.
6. **Log format**. Each iteration appends a delimiter line `--- iter N ---` (or `--- iter 0 (session <sid>) ---`) followed by raw `devin` stdout and a trailing newline.
7. **Resume cwd fallback**. `cmd_resume` loads `cwd` from state. If the worktree path no longer exists, it prints a warning, falls back to `os.getcwd()`, and disables worktree.
8. **Environment precedence**. `GOAL_DEVIN_MODEL`, `GOAL_DEVIN_PERMISSION_MODE`, `GOAL_DEVIN_SLEEP`, `GOAL_DEVIN_MAX_ITERS`, `GOAL_DEVIN_ITER_TIMEOUT`, `GOAL_DEVIN_WORKTREE`, `GOAL_DEVIN_SANDBOX` override built-in defaults. CLI flags override environment. `--no-worktree`/`--no-sandbox` set the booleans false.
9. **Notification behavior**. On loop end, `notify_desktop` and `notify_bell` are called; failures are swallowed. On non-TTY, the bell writes `\a` to stdout.
10. **Sandbox flag passthrough**. `--sandbox` adds the literal `--sandbox` argument to the `devin` command line; `goal-devin` does not implement its own sandbox.

## Golden outputs (sanitized)

### `goal-devin goal "make tests pass" --max-iters 1 --no-worktree`

```text
  goal-devin v0.6.0
  goal   make tests pass
  model  glm-5.2  (new session)


  iter 0 | <session-id> | 0s
<devin-stdout>


  done — 1 iters in 0s
```

State file contains: `session_id`, `cwd` (resolved), `goal`, `iters=1`, `model`, `permission_mode`, `use_worktree=false`, `use_sandbox=false`, `worktree_id=null`, `status="stopped"`, `started_at`, `last_iter_at`.

### `goal-devin resume <session-id> --max-iters 2`

```text
  goal-devin v0.6.0
  goal   make tests pass
  model  glm-5.2  <session-id>


  iter 2 | <session-id> | 0s
<devin-stdout>


  done — 2 iters in 0s
```

`iters` increments from the prior value; log appends `--- iter 1 ---`.

### `goal-devin status` from a directory with no state

```text
  none — no goal state in this directory.
```

### `goal-devin status --all` with one stopped session

```text
  [~/<worktree-path>]
    session <session-id>  iters 2  model glm-5.2  status stopped
    goal make tests pass
```

## Fake `devin` journal shape

Each line of `invocations.jsonl` is:

```json
{
  "timestamp": "ISO8601",
  "argv": ["...", "-p", "--", "GOAL: ..."],
  "cwd": "...",
  "env_keys": ["..."],
  "stdout": "...",
  "stderr": "...",
  "exit_code": 0,
  "created_session": "devin-..."
}
```

Environment values are **not** recorded.

## Stable contract for a rewrite

A replacement implementation must, at minimum, preserve:

- the same argv matrices for iter 0 and continuation;
- per-cwd state file path and atomic write semantics;
- `devin list` session resolution by `working_directory` with retries;
- worktree create/keep/remove rules;
- log delimiter format;
- exit-code mapping (`0` for `max_iters`/`killed`, `1` for iter 0 error);
- environment variable names and defaults.

It may intentionally change:

- the single-threaded model;
- the `devin -r` continuation loop;
- the lack of structured output;
- the lack of concurrency or subagent orchestration.
