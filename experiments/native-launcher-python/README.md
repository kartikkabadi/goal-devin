# Native Launcher Python Candidate (R1A.1)

This directory contains the Python implementation of the Goal Devin native
launcher candidate. It is an experiment; it does **not** install the production
`goal-devin dev` command.

## Entry point

```bash
experiments/native-launcher-python/goal-devin-dev \
  --model swe-1-7 \
  --permission-mode accept-edits \
  --devin-bin <path-to-fake-devin> \
  --contract-dir experiments/native-launcher-testkit \
  --runtime-root <temporary-runtime-root>
```

Optional flags:

- `--canary <dir>` — use a pre-existing canary directory inside `--runtime-root`.
- `--existing-hooks <path>` — pre-seed `.devin/hooks.json` and restore it after
  the run (original bytes and mode preserved).
- `--keep-canary` — do not remove the canary directory after the run.
- `--contract-dir <dir>` — path to the shared testkit directory containing the
  authoritative `expected/*.schema.json` schemas (required).

## Running the shared contract

```bash
python3 experiments/native-launcher-testkit/run-contract.py \
  --candidate experiments/native-launcher-python/goal-devin-dev \
  --devin-bin experiments/native-launcher-testkit/fake-devin \
  --contract-dir experiments/native-launcher-testkit \
  --canary-fixture experiments/native-launcher-testkit/fixtures/canary \
  --runtime-root $(mktemp -d) \
  --base-dir $(mktemp -d) \
  --keep-artifacts
```

Use `--process-overlap` to prove supervisor, sidecar, and fake child are alive
simultaneously, and `--tty` to prove stdio TTY inheritance.

## Running candidate tests

```bash
export PATH=/home/ubuntu/.pyenv/versions/3.12.8/bin:$PATH
uv run pytest experiments/native-launcher-python/tests/ -v
```

## Structure

```text
experiments/native-launcher-python/
  goal-devin-dev            # candidate-local executable
  native_launcher/
    cli.py                  # argument parsing
    supervisor.py           # main lifecycle (sidecar, child, cleanup)
    sidecar.py              # event-spool observer
    hook.py                 # observation hook (self-contained)
    profile.py              # temporary AGENT.md profile generation
    manifest.py             # run manifest writing
    schema.py               # minimal JSON-schema validator
    utils.py                # path safety, atomic writes, random IDs
  tests/
    test_native_launcher.py # deterministic candidate tests
```

## Security and ownership

- The supervisor creates a private runtime directory with mode `0700`.
- The canary and all generated artifacts live under the supplied runtime root.
- No user or project Devin configuration is copied or merged.
- `hook.py` extracts only approved event fields and never persists raw prompts,
commands, output, repository paths, session IDs, credentials, or environment
dumps.

## What is proven

- A self-contained Python candidate can implement the shared happy-path contract.
- The candidate can generate a read-only worker profile, install a project-local
observation hook, run a sidecar, spawn a fake `devin` child with inherited
stdio, and clean up generated artifacts.
- The event spool uses atomic temp-to-`.json` renames.
- The sidecar consumes events and writes a bounded summary.
- `devin` is spawned with the exact allowed argv (`--model` and `--permission-mode`
  only) and no `-p`/`--print` flag.
- The fake child can be blocked while the runner observes supervisor, sidecar,
  and child PIDs simultaneously (no `exec`).
- All runtime artifacts have explicit expected file and directory modes.
- Existing hook fixtures are byte- and mode-preserved.
- `model` and `permission-mode` are validated as one-line identifiers before YAML
  interpolation.

## What is not proven

- Effective worker model usage at runtime. The profile is configured with the
exact root model and presented to `devin`; whether `devin` honors it is not
verified here.
- Production integration with the real `goal-devin` package.
- Real Devin CLI behavior, ACP orchestration, or native TUI `--export` support.
- Failure handling, signal interruption, sidecar restart, or rate limits.
- Symlink-escape hardening beyond runtime-root/canary path resolution; production
  must use a more robust sandbox.
