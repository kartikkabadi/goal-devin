# Goal Devin — Native Integration Trial (R0.6 / R0.7)

This document is the final trial contract before implementation begins. It
replaces the superseded `goal-devin ultra --script` trial and describes the
smallest implementation slice that closes the live Devin integration gaps
identified in Phase R0.5.

The trial is **language-neutral** and will be executed twice: once as a Python
candidate (R1A) and once as a Rust candidate (R1B). The final language decision
is made in R1C after a measured comparison, not before. R0.7 corrected the
config, hook transport, custom-profile, and candidate-structure details after an
independent review.

## 1. Corrected product scope to preserve

The canonical product remains as corrected in Phase R0.5:

- The existing autonomous `goal`/`resume` loop is preserved and hardened.
- Goal Devin gains a mode that launches the genuine native `devin` TUI.
- The native `devin` process owns the user's terminal directly.
- Goal Devin owns surrounding policy, status, reliability, and verification.
- The selected orchestrator model is exact and sticky.
- Workers default to the same exact model; a different worker model is allowed
  only through explicit user configuration.
- No silent model fallback.
- Native Devin subagents are used for ordinary in-session work.
- Independent `devin -p` sessions are reserved for explicitly independent Goal
  Devin jobs.
- Goal Devin remains unrelated to any project named Loop.
- The previous `ultra --script` workflow DSL remains superseded.

## 2. Command name

The provisional command for the native mode is:

```text
goal-devin dev
```

Do not use `goal-devin start` in this trial.

Rationale:

- `start` is ambiguous with starting an autonomous goal.
- `dev` clearly means "open Goal Devin's enhanced native development mode."
- It leaves room for future commands such as `goal`, `verify`, `doctor`, and
  `watch`.

The command name is **provisional** until the trial completes and the language
and integration approach are approved. During R1A and R1B each candidate may
expose a candidate-local executable that is compatible with this interface, but
neither becomes the installed production command before R1C.

## 3. Launcher lifecycle

The stable process structure is:

```text
goal-devin dev
├── parent supervisor
├── observation sidecar
└── native devin child attached directly to the user TTY
```

The supervisor is a real, persistent process. Neither the Python candidate nor
the Rust candidate may replace the supervisor with `exec`, `os.execvp`, or any
other process-replacement primitive.

The supervisor must:

1. Resolve the real `devin` executable.
2. Validate the selected model and permission mode.
3. Create one private runtime directory.
4. Install the Goal Devin observation hook through a project hook file in the
   disposable canary (for the live canary) or a hook-only `--config` capability
   probe (for the installed-version test).
5. Create one temporary custom subagent profile.
6. Start the read-only sidecar.
7. Spawn `devin` with inherited `stdin`, `stdout`, and `stderr`.
8. Wait for `devin`.
9. Observe normal exit, signal exit, and launch failure.
10. Stop the sidecar.
11. Read the sanitized event summary.
12. Remove only Goal Devin-owned temporary files.
13. Print a bounded final summary.
14. Return an appropriate exit code.

The native Devin child must not run behind a PTY parser or ptywrapper owned by
Goal Devin. In the real terminal:

```text
isatty(child stdin)  = true
isatty(child stdout) = true
isatty(child stderr) = true
```

Goal Devin must not read, transform, buffer, mirror, or redraw the native TUI
output. It must not inject keystrokes or simulate terminal input.

## 4. Hook installation strategy

The trial must preserve the user's real `HOME` and Devin credential storage.
It must not create a temporary `HOME` and must not copy or merge the user's
complete Devin configuration into a runtime file. User and project-local Devin
configuration may contain secrets such as MCP environment variables.

### Live disposable-canary trial

For the live canary:

1. Use a documented project hook source such as `.devin/hooks.v1.json`
   (or `.devin/hooks.json` if that is the documented filename for the installed
   `devin` version).
2. Create or modify files only inside the disposable canary repository.
3. If the hook file already exists, record its exact bytes, restore it exactly
   after the test, and clean up any added Goal Devin entries.
4. The hook file must contain only the Goal Devin observation hook and must not
   copy credentials, user config, or project config.
5. Remove the file after the test.

Example minimal project hook file:

```json
{
  "PreToolUse": [
    {
      "matcher": "",
      "hooks": [
        {
          "type": "command",
          "command": "/path/to/goal-devin-hook",
          "timeout": 5
        }
      ]
    }
  ],
  "PostToolUse": [
    {
      "matcher": "",
      "hooks": [
        {
          "type": "command",
          "command": "/path/to/goal-devin-hook",
          "timeout": 5
        }
      ]
    }
  ]
}
```

### Installed-version capability probe

For the installed-version test, create a **hook-only** config file that
contains nothing except a Goal Devin observation hook and pass it explicitly:

```text
devin --config <hook-only-config> ...
```

The probe must:

1. Verify whether `--config` augments or replaces the normal user/project hook
   sources.
2. Observe at least one real hook event to confirm the Goal Devin hook is
   active.
3. Use the native `/hooks` interface where useful to confirm the loaded hook
   configuration.
4. Record the observed precedence behavior.
5. Delete the hook-only config after the probe.

Do not copy secret-bearing user or project configuration under any
circumstance. Production-grade hook injection remains out of scope until R1C
chooses a safe supported seam.

## 5. Private runtime directory

Use a directory structure conceptually equivalent to:

```text
~/.goal-devin/runtime/<run-id>/
├── manifest.json
├── hook-only-config.json
├── events/
│   └── <event-id>.json
├── sidecar.pid
└── summary.json
```

Requirements:

- Directory permission: current user only (`0700`).
- Files containing runtime data: current user only (`0600`).
- Random, unguessable run ID.
- No raw prompts.
- No raw tool responses.
- No credentials.
- No authorization headers.
- No full session transcript.
- Bounded event sizes.
- Bounded number of event files and total directory size.
- Schema version on persisted JSON.
- Only one process may own a run.
- Every generated path must be recorded in `manifest.json`.

Production code must not write to `.research-evidence/`. That directory
remains research-only.

## 6. Hook transport

Use a spool directory as the primary multi-writer hook transport:

```text
Devin invokes tiny hook process
        ↓
hook sanitizes event
        ↓
hook writes one temporary JSON file
        ↓
hook atomically renames it to events/<event-id>.json
        ↓
sidecar observes newly renamed event files
        ↓
sidecar validates schema and updates summary
```

For each hook invocation the hook must:

1. Read exactly one JSON object from stdin.
2. Accept only a bounded payload.
3. Extract only approved fields.
4. Redact before writing.
5. Generate a unique event identifier.
6. Write to a temporary file inside the spool directory.
7. Flush and close it.
8. Atomically rename it to its final `.json` name.
9. Exit zero.

The sidecar must:

- Observe newly renamed event files in the spool directory.
- Validate each file against the approved event schema.
- Update its in-memory summary.
- Record which event files were consumed.
- Remain a separate failure domain; killing it must not stop `devin`.

The approved event fields are limited to:

```json
{
  "schema_version": 1,
  "event": "PreToolUse|PostToolUse|SessionStart|SessionEnd",
  "tool_name": "run_subagent|exec|glob|...",
  "profile": "optional-profile-id",
  "is_background": "optional-boolean",
  "success": "optional-boolean",
  "observed_at": "timestamp"
}
```

The hook must not persist:

- Prompt text.
- Task text.
- Shell commands.
- Tool output.
- File contents.
- Absolute repository paths.
- Session IDs in raw form.

Where correlation is needed, store a digest rather than the raw identifier.

Requirements:

- No shared-writer corruption.
- Duplicate-safe event identifiers.
- Bounded number and total size of event files.
- Fail open.
- No network access.
- No raw prompts, commands, output, paths, credentials, or session IDs.
- Sidecar absence must not affect `devin`.
- Cleanup removes only files listed in the run manifest.

## 7. Custom-profile handling

The temporary custom profile is Goal Devin-owned, transparent, and
session-scoped.

Use a unique profile ID such as:

```text
goal-devin-worker-<nonce>
```

Write it under the supported project profile location:

```text
.devin/agents/<profile-id>/AGENT.md
```

Use only documented `AGENT.md` frontmatter fields. Do not rely on unknown
frontmatter being accepted.

Example minimal `AGENT.md`:

```markdown
---
name: goal-devin-worker-<nonce>
description: Goal Devin read-only worker for the native integration trial
model: <exact-worker-model>
allowed-tools:
  - read
  - grep
  - glob
permissions:
  deny:
    - write
    - edit
---

<!-- goal-devin-generated: true; run-id: <run-id> -->

You are a Goal Devin trial worker. Use the selected model and follow project
instructions. Do not perform destructive operations outside the current task.
```

Requirements:

- Explicit exact `model:` frontmatter matching the user-selected worker model.
- Documented `name` and `description` fields.
- Narrow tool policy (`allowed-tools`) and permission deny-list suitable for a
  harmless, read-only trial.
- No credentials.
- No hidden instructions unrelated to the trial.
- Ownership recorded in the runtime manifest and a non-frontmatter comment.
- Remove only the generated profile directory.
- Never remove `.devin/agents`.
- Never remove user profiles.
- Preserve the profile after an abnormal failure only when needed for
  diagnosis, and mark it stale.
- Provide safe stale-profile cleanup on the next run.

## 8. Profile loading proof

Creating a file does not prove Devin recognized it. The trial contract
includes two levels of proof.

### Deterministic fake-Devin test

The fake executable verifies:

- Profile path exists before launch.
- Profile frontmatter contains the exact selected worker model.
- Documented tool policy is narrow and read-only.
- The Goal Devin hook is configured and reachable.
- Exact root `--model` reaches `devin`.
- Profile is removed after exit (or marked stale after an abnormal failure).

### Explicit live canary test

A bounded live canary must:

1. Launch with root model `swe-1-7`.
2. Load the generated Goal Devin profile.
3. Invoke it once for a harmless read-only task.
4. Capture the `run_subagent` hook event in the spool directory.
5. Verify the hook event references the generated profile ID.
6. Record configured versus observed-effective model honestly.
7. Exit cleanly.
8. Confirm cleanup.

The live canary is a manual protected test and must not run in public CI.

Do not claim effective worker-model proof merely because the profile contains
`model:` in its frontmatter.

## 9. Fair Python-versus-Rust trial

The final language decision must not use:

```text
Try Python; use Rust only if Python fails.
```

That is biased because basic subprocess launching is expected to work in either
language. Both candidates implement the same small contract and share the same
fixtures, test runner, and measurement script.

### Candidate locations

```text
experiments/
  native-launcher-python/   # R1A
  native-launcher-rust/     # R1B
  native-launcher-testkit/  # shared fixtures, fake devin, canary, test runner
```

Neither candidate becomes the installed production command before R1C. Each may
expose a candidate-local executable compatible with the provisional `goal-devin
dev` interface.

### Shared testkit

Both candidates must use:

- The same fake `devin` executable.
- The same canary repository fixture.
- The same existing-user-hook fixture.
- The same generated-profile fixture.
- The same hook event spool schema.
- The same black-box test runner.
- The same failure scenarios.
- The same measurement script.

Candidate-specific unit tests are additional; they do not replace the shared
contract.

### Evaluation criteria

Both candidates must be evaluated on:

- Exact argv.
- Native terminal ownership.
- Signal behavior.
- Sidecar isolation.
- Hook latency.
- Cleanup after normal exit.
- Cleanup after launch failure.
- Cleanup after signal interruption.
- Stale-state recovery.
- Startup latency.
- Idle memory.
- Added source complexity.
- Test complexity.
- Packaging complexity.
- Cross-platform prospects.
- Ability to support future ACP and rate-limit state machines.
- Developer ergonomics.
- Resulting artifact size.

The language decision must be based on the measured comparison, not on:

- Devin being written in Rust.
- Existing Goal Devin being written in Python.
- One candidate merely "working."
- Subjective language preference.

## 10. Later phases

The implementation is split into three later phases.

### R1A — Python native-integration candidate

Implement only the Python candidate under
`experiments/native-launcher-python/`. Stop after its exact-head review.

### R1B — Rust native-integration candidate

Implement only the equivalent Rust candidate under
`experiments/native-launcher-rust/`. Do not port existing Goal Devin behavior.
Stop after its exact-head review.

### R1C — Differential evaluation and language decision

Run the shared contract against both candidates. Write an architecture
decision. Do not start the production integration until that decision is
approved.

### R1A acceptance contract

The Python candidate must prove:

1. The candidate-local `dev` executable resolves `devin`, validates
   model/permission mode, creates the runtime directory, installs the
   observation hook, writes a temporary custom profile, and spawns `devin` with
   inherited `stdin`/`stdout`/`stderr`.
2. The supervisor stays alive and does not call `os.execvp`.
3. A read-only sidecar runs in a separate process and observes newly renamed
   event files in the spool directory.
4. The hook writes sanitized events as atomic `.json` files in the runtime
   `events/` directory.
5. At least one `run_subagent` or `PostToolUse` event is captured in the live
   canary and reflected in `summary.json`.
6. The generated custom profile exists before `devin` starts, contains the
   exact worker model in frontmatter, uses only documented frontmatter fields,
   and is removed after exit (or marked stale after an abnormal failure and
   safely cleaned up later).
7. Existing user hooks and config are preserved and not mutated.
8. Credentials remain accessible to `devin` but never appear in generated files,
   runtime files, logs, or test artifacts.
9. Normal exit, launch failure, and `SIGINT` interruption all leave only
   Goal Devin-owned files, restore the terminal, and print a bounded summary.

### R1B acceptance contract

The Rust candidate must prove the same items as R1A, plus:

1. The Rust candidate must not replace the supervisor process with `exec`.
2. It must produce the exact same argv and runtime artifacts as the Python
   candidate.
3. It must run from `experiments/native-launcher-rust/` without disturbing the
   existing Python package.
4. It must reuse the shared testkit; it must not require a separate
   independent acceptance harness.

### R1C measurement methodology

All measurements must be reproducible and performed in identical conditions:

- Five or more cold starts.
- Five or more warm starts.
- Median and p95 startup time.
- Idle RSS after a fixed interval.
- Peak RSS during the canary.
- Release-mode Rust binary.
- Normal non-debug Python execution.
- Identical machine and environment.
- Identical `devin` executable.
- Identical fake/live tasks.
- Exact measurement boundaries.
- Source LOC excluding tests and generated files.
- Test LOC.
- Build/install time.
- Final artifact size.
- Signal and cleanup behavior.

Do not use subjective impressions as a deciding metric.

## 11. Black-box acceptance contract

Both candidates must prove the following contract before R1C:

1. Root model flag is exact.
2. Worker-profile model field is exact.
3. Devin directly owns the TTY.
4. Supervisor remains alive.
5. Sidecar is a separate failure domain.
6. Killing the sidecar does not stop Devin.
7. Hook failure does not stop Devin.
8. Existing user hooks remain configured.
9. Existing user config remains unchanged.
10. Credentials remain accessible to Devin but absent from generated files.
11. Generated profile exists before Devin starts.
12. Generated profile is loaded in the live canary.
13. At least one sanitized hook event is observed.
14. Goal Devin never reads native TUI output.
15. Goal Devin never writes native TUI input.
16. Normal exit restores the terminal.
17. Interrupt exit restores the terminal where testable.
18. Only Goal Devin-owned files are cleaned.
19. No permanent project or user configuration is changed.
20. Existing Goal Devin commands remain untouched.
21. The candidate prints a bounded final summary.
22. Secrets do not appear in logs, state, generated config, or test artifacts.

## 12. Out of scope

- Changing the existing `goal`/`resume`/`status`/`logs` implementation.
- Implementing a workflow scripting DSL (`goal-devin ultra --script`).
- Spawning parallel independent `devin -p` sessions as the primary fan-out.
- Auto-retry on rate limits.
- A full dashboard or native TUI reimplementation.
- PTY interception, keyboard injection, or screen scraping.
- A full Rust rewrite of Goal Devin.
- Production-grade hook injection before R1C.

## 13. Verification plan

1. Run all existing tests: `uv run pytest tests/ -v`.
2. Run Ruff check and format check:
   `uv run ruff check . && uv run ruff format --check .`.
3. Run the deterministic fake-Devin test for the candidate.
4. Run a bounded manual live canary with the candidate-local `dev` executable and
   `--model swe-1-7` in a disposable canary repository.
5. Verify the sidecar captured at least one sanitized `PostToolUse` or
   `run_subagent` event in the spool directory.
6. Verify the generated profile directory under `.devin/agents/` was removed.
7. Verify `goal-devin status` and `goal-devin logs` still work.
8. Scan the diff and runtime artifacts for credentials before final review.

## 14. Session identity for native mode

The native `dev` trial should determine the session ID using the hierarchy in
`research/DEVIN_SESSION_IDENTITY.md`:

1. Print mode: pass a Goal Devin-owned ATIF export path and parse `session_id`.
2. ACP mode: use the `sessionId` returned by `session/new`.
3. Native TUI: test whether the documented global `--export` flag produces usable
   ATIF during an interactive session; do not claim support until observed.
4. `devin list --format json`: fallback heuristic only, with its known race.

## 15. Known unknowns

- Whether the documented global `--export` flag produces usable ATIF during an
  interactive TUI session.
- Whether `devin --config <hook-only-config>` augments or replaces normal
  user/project hook sources.
- Exact Devin CLI behavior when the hook-only config is unreadable or contains
  a hooks entry for an event not supported by the installed binary.
- Cross-platform runtime directory and signal handling differences (Linux,
  macOS).
