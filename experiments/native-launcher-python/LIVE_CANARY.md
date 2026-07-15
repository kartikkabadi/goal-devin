# R1A Python Native Launcher — Live Canary

## Environment

- Devin CLI version: `3000.1.27`
- Model: `swe-1-7`
- Permission mode: `accept-edits`
- Working directory: disposable canary Git repository
- HOME: isolated Devin credentials directory (not the real user home)
- Launcher: `native_launcher_python` from `experiments/native-launcher-python/`

## Command

```text
python -m native_launcher_python.cli . \
  --model swe-1-7 \
  --permission-mode accept-edits \
  --keep-runtime \
  --keep-profile \
  --devin-arg=-p \
  --devin-arg="Run the Goal Devin worker profile to read fib.py and report the first line. Do not edit files."
```

## Observed result

```text
The first line of `fib.py` is:

def fib(n):

Goal Devin dev session finished.
  run_id:         F6HtxynpOJPvvJuJVzWQKQ
  model:          swe-1-7
  permission:     accept-edits
  sandbox:        False
  events:         6
  tools:          run_subagent, read
  profiles:       goal-devin-worker-F6Htxynp
  child exit:     0
```

## Summary file

```json
{
  "schema_version": 1,
  "event_count": 6,
  "tool_names": ["run_subagent", "read"],
  "profiles": ["goal-devin-worker-F6Htxynp"],
  "background_count": 0,
  "success_count": 2,
  "failure_count": 0
}
```

## Key findings

- `devin` accepted the generated `.devin/hooks.v1.json` and invoked the Goal
  Devin hook for `PostToolUse` and `SessionEnd` events.
- The generated worker profile `.devin/agents/goal-devin-worker-F6Htxynp/AGENT.md`
  was created before `devin` started.
- The prompt caused `devin` to invoke `run_subagent` with the generated profile
  id; the hook event captured `tool_name: run_subagent` and
  `profile: goal-devin-worker-F6Htxynp`.
- The runtime directory was created under `~/.goal-devin/runtime/<run-id>/`
  with `0700` permissions, event files with `0600` permissions.
- The launcher printed a bounded final summary and exited with code `0`.

## Classification

- `devin` spawns with native terminal ownership: **OBSERVED** (single print
  mode run; full interactive TUI ownership not exercised in this canary).
- Hook transport via atomic `.json` files in `events/`: **OBSERVED**.
- Generated profile creation and loading: **OBSERVED**.
- Sidecar process observes events and writes `summary.json`: **OBSERVED**.
- Runtime directory permissions and cleanup: **OBSERVED**.
