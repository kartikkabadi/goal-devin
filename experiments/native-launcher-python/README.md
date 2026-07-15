# Native Launcher Python Candidate (R1A.1)

This directory contains the Python implementation of the Goal Devin native
launcher candidate. It is an experiment; it does **not** install the production
`goal-devin dev` command.

## Entry point

```bash
BASE=$(mktemp -d)
experiments/native-launcher-python/goal-devin-dev \
  --model swe-1-7 \
  --permission-mode accept-edits \
  --devin-bin <path-to-fake-devin> \
  --contract-dir experiments/native-launcher-testkit \
  --runtime-root "$BASE/runtime" \
  --canary "$BASE/canary"
```

`accept-edits` is the value observed in the v3000.1.27 `fake-devin` fixture; it is
used here as an example permission mode, not as a claim that it is a current or
universal Devin enum value.

`--base-dir` belongs to the shared runner (`run-contract.py`), not to the
candidate. The candidate only needs `--runtime-root` and a canary directory
inside it.

`--runtime-root` must be inside `--base-dir` so the outside-write oracle is
meaningful. Optional flags:

- `--canary <dir>` — use a pre-existing canary directory inside `--runtime-root`.
- `--existing-hooks <path>` — pre-seed `.devin/hooks.v1.json` and restore it after
  the run (original bytes and mode preserved).
- `--keep-canary` — do not remove the canary directory after the run.
- `--contract-dir <dir>` — path to the shared testkit directory containing the
  authoritative `expected/*.schema.json` schemas (required).

## Running the shared contract

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
- No complete user or project Devin configuration is copied or merged. The
candidate only reads or temporarily merges the standalone `.devin/hooks.v1.json`
project hook source; any existing hook file is restored byte-for-byte after the
run.
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
  and child PIDs simultaneously. The runner verifies `supervisor.pid` matches the
  launcher process, all three PIDs are pairwise distinct, and none are replaced
  by `exec` (a negative-control candidate that execs fake `devin` is rejected).
- All runtime artifacts have explicit expected file and directory modes;
  generated `AGENT.md` is mode `0600`.
- Existing `.devin/hooks.v1.json` fixtures are parsed and validated before any
  project mutation; malformed JSON, non-object top-level, and non-list event values
  are rejected without creating the generated profile or starting the sidecar/child.
- Existing hook fixtures are byte- and mode-preserved using `.devin/hooks.v1.json`
  only; `.devin/hooks.json` is never used as the standalone source.
- `model` and `permission-mode` are validated as one-line identifiers before YAML
  interpolation.
- The authoritative event schema JSON is parsed and validated before any runtime
  or project artifacts are created; the sidecar rejects events if the schema is
  missing or invalid.
- The candidate rejects symlinks for `.devin`, `.devin/agents`, `.devin/hooks.v1.json`,
  and the generated profile path before mutation.
- The outside-write oracle is self-consistent: `--runtime-root` must be inside
  `--base-dir`; a negative-control candidate that writes a sibling file under the
  base is rejected.
- The manifest declares every generated artifact with `owned_paths`, `owned_roots`,
  and `owned_prefixes`; the runner rejects any generated file not covered by the
  manifest and asserts that pre-existing/user-owned paths are never marked owned.

## What is not proven

- Effective worker model usage at runtime. The profile is configured with the
exact root model and presented to `devin`; whether `devin` honors it is not
verified here.
- Production integration with the real `goal-devin` package.
- Real Devin CLI behavior, ACP orchestration, or native TUI `--export` support.
- Failure handling, signal interruption, sidecar restart, or rate limits.
- Complete system-wide sandboxing; the candidate resolves paths under the
  supplied runtime root but cannot intercept hard-coded paths outside it.
