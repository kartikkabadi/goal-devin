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
- `fixtures/` — canary repo fixture, an existing-hooks fixture, and a language-neutral
  schema conformance corpus used by both candidates.

## Running the contract

```bash
BASE=$(mktemp -d)
python3 experiments/native-launcher-testkit/run-contract.py \
  --candidate experiments/native-launcher-python/goal-devin-dev \
  --devin-bin experiments/native-launcher-testkit/fake-devin \
  --contract-dir experiments/native-launcher-testkit \
  --canary-fixture experiments/native-launcher-testkit/fixtures/canary \
  --runtime-root "$BASE/runtime" \
  --base-dir "$BASE" \
  --keep-artifacts
```

Add `--tty` to run the candidate under a PTY and assert that `fake-devin`
observes TTY file descriptors.
Add `--process-overlap` to block the fake child until the shared runner has
observed supervisor, sidecar, and child PIDs alive simultaneously.

## Security assumptions

- The testkit creates a fresh runtime root and canary for every run.
- The candidate must not read, write, or execute outside the runtime root and
disposable canary.
- The candidate must not copy or merge the user's complete Devin configuration. It
  may only read or temporarily merge the standalone `.devin/hooks.v1.json` project
  hook source and must restore it byte-for-byte.
- `fake-devin` deliberately records no environment variable keys to avoid
leaking secret names; it does not access the network.
- `--runtime-root` is required to be inside `--base-dir` so the outside-write
oracle is self-consistent.

## What is proven

The contract verifies:

- supervisor/sidecar/child lifecycle and exact argv (`--model` + `--permission-mode`);
- process overlap (all three PIDs alive simultaneously) when run with `--process-overlap`,
  with `supervisor.pid` matching the launcher process and pairwise distinct PIDs;
- exact model and permission mode passthrough;
- generated worker profile model, name, read-only tool policy, and `AGENT.md` mode `0600`;
- observation hook installation through `.devin/hooks.v1.json`, fail-open behavior,
  and invocation;
- atomic event publication and sidecar consumption;
- exact-byte and exact-mode restoration of existing hook fixtures using `.devin/hooks.v1.json`;
- profile cleanup, TTY inheritance, and explicit file modes on all artifacts;
- schema validity of manifest, event, and summary artifacts;
- language-neutral schema conformance corpus parity between the shared validator
  and the candidate validator;
- manifest ownership contract (`owned_paths`/`owned_roots`/`owned_prefixes`);
- event schema validation at candidate startup and fail-closed sidecar behavior when
  the schema is missing or invalid;
- malformed/incompatible `.devin/hooks.v1.json` rejection without project mutation;
- symlink-escape rejection for `.devin`, `.devin/agents`, `.devin/hooks.v1.json`, and
  the generated profile path before mutation;
- outside-write rejection: `--runtime-root` must be inside `--base-dir`, and no files
  outside the allowlist are permitted;
- ownership rejection: any generated artifact not declared in the manifest fails the
  contract, and pre-existing/user-owned paths must never be marked as owned.

## What is not proven

- Real Devin CLI behavior (this is a fake-Devin happy path only).
- Authenticated sessions, ACP orchestration, or native TUI `--export` support.
- Worker model enforcement at runtime; only configuration and presentation are
verified.
- Failure handling, signal interruption, sidecar death/restart, or rate-limit
behavior.
- Complete isolation from all system write paths; the runner redirects common
environment variables and rejects writes outside the runtime-root/canary allowlist,
but cannot intercept hard-coded paths that bypass the candidate.
