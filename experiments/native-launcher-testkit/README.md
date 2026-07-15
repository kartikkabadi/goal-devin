# Native Launcher Shared Testkit

This directory contains the language-neutral black-box acceptance testkit for
the Goal Devin native-mode launcher trial. It is used by both the Python
candidate (R1A) and the future Rust candidate (R1B).

## Contents

- `fake-devin` — deterministic stand-in for the Devin CLI. It records its
  invocation, verifies the Goal Devin worker profile and observation hook,
  invokes the hook with a sanitized `run_subagent` payload, and exits without
  network access.
- `run-contract.py` — shared happy-path contract runner.
- `expected/` — JSON schemas for the manifest, event, and summary artifacts.
- `fixtures/` — canary repo fixture and an existing-hooks fixture.

## Running the contract

```bash
python3 experiments/native-launcher-testkit/run-contract.py \
  --candidate experiments/native-launcher-python/goal-devin-dev \
  --devin-bin experiments/native-launcher-testkit/fake-devin \
  --canary-fixture experiments/native-launcher-testkit/fixtures/canary \
  --runtime-root $(mktemp -d) \
  --keep-artifacts
```

Add `--tty` to run the candidate under a PTY and assert that `fake-devin`
observes TTY file descriptors.

## Security assumptions

- The testkit creates a fresh runtime root and canary for every run.
- The candidate must not read, write, or execute outside the runtime root and
disposable canary.
- The candidate must not copy or merge the user's Devin configuration.
- `fake-devin` deliberately records no environment variable keys to avoid
leaking secret names; it does not access the network.

## What is proven

The contract verifies:

- supervisor/sidecar/child lifecycle;
- exact model and permission mode passthrough;
- generated worker profile model and read-only tool policy;
- observation hook installation and invocation;
- atomic event publication and sidecar consumption;
- exact-byte restoration of existing hook fixtures;
- profile cleanup and TTY inheritance.

## What is not proven

- Real Devin CLI behavior (this is a fake-Devin happy path only).
- Authenticated sessions, ACP orchestration, or native TUI `--export` support.
- Worker model enforcement at runtime; only configuration and presentation are
verified.
- Failure handling, signal interruption, sidecar death/restart, or rate-limit
behavior.
