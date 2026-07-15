# Goal Devin — R1A Python Native Launcher

This directory contains the Python candidate for the native-integration trial
(R1A). It implements the black-box acceptance contract in
`research/NATIVE_INTEGRATION_TRIAL.md`.

## What it does

`native_launcher_python` launches the genuine `devin` binary with Goal Devin
policy around it:

- Resolves the real `devin` executable (or `DEVIN_EXECUTABLE`).
- Validates the permission mode.
- Creates a private runtime directory under `~/.goal-devin/runtime/<run-id>/`.
- Installs a Goal Devin observation hook via `.devin/hooks.v1.json`.
- Creates a temporary worker profile under `.devin/agents/<profile-id>/AGENT.md`.
- Starts a read-only sidecar process that watches the hook spool.
- Spawns `devin` with inherited `stdin`/`stdout`/`stderr`.
- Cleans up Goal Devin-owned files and prints a bounded summary.

## Run the candidate

```bash
PYTHONPATH=experiments/native-launcher-python/src:experiments/native-launcher-testkit \
  python -m native_launcher_python.cli <workdir> \
  --model swe-1-7 \
  --permission-mode accept-edits \
  --devin-arg=-p \
  --devin-arg="Read fib.py and report the first line."
```

For an interactive TUI session, omit `--devin-arg=-p` and any prompt.

## Run the tests

The tests live in `experiments/native-launcher-python/tests/` and are included
in the root pytest collection via `pyproject.toml`:

```bash
uv run pytest -v
```

## Live canary

A live canary against the installed `devin` binary was run in
`.research-evidence/canary6/`. It launched with `--model swe-1-7`, loaded the
generated worker profile, and the `PostToolUse` hook captured a `run_subagent`
event with the profile id. Details are in `LIVE_CANARY.md`.
