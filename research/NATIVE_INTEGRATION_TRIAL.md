# Goal Devin — Native Integration Trial (R0.6)

This document is the final trial contract before implementation begins. It
replaces the superseded `goal-devin ultra --script` trial and describes the
smallest implementation slice that closes the live Devin integration gaps
identified in Phase R0.5.

The trial is **language-neutral** and will be executed twice: once as a Python
candidate (R1A) and once as a Rust candidate (R1B). The final language decision
is made in R1C after a measured comparison, not before.

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
and integration approach are approved.

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
4. Create one generated temporary Devin config.
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

## 4. Temporary config design

The trial must preserve the user's real `HOME` and Devin credential storage.
It must not create a temporary `HOME` to hold Devin configuration.

Instead, the launcher creates a temporary merged config and passes it to the
native process:

```text
devin --config <goal-devin-generated-config> ...
```

The generated config must:

1. Start from the existing effective user config where safely available.
2. Preserve unrelated user configuration.
3. Preserve existing hooks.
4. Append one uniquely identified Goal Devin observation hook.
5. Never copy credentials into the config.
6. Never contain authentication tokens.
7. Be readable only by the current user.
8. Live in the private Goal Devin runtime directory.
9. Be deleted after the run.
10. Be recoverable as stale Goal Devin-owned state after an abnormal crash.

The Goal Devin hook must be appended to the `hooks` object without replacing any
existing user hooks array. The launcher must not mutate the user's permanent
config, project hook configuration, or Devin credential store.

Config-precedence behavior between `--config`, project `.devin/config.json`,
user `~/.config/devin/config.json`, and `AGENT.md` frontmatter is currently
unresolved. The trial must document observed behavior honestly and include a
specific test that verifies the Goal Devin hook is actually invoked.

## 5. Private runtime directory

Use a directory structure conceptually equivalent to:

```text
~/.goal-devin/runtime/<run-id>/
├── manifest.json
├── devin-config.json
├── hook-events.jsonl
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
- Bounded event-file growth.
- Schema version on persisted JSON.
- Only one process may own a run.
- Every generated path must be recorded in `manifest.json`.

Production code must not write to `.research-evidence/`. That directory
remains research-only.

## 6. Hook transport

Use the simplest reliable language-neutral transport for the trial:

```text
Devin invokes tiny hook process
        ↓
hook sanitizes event
        ↓
one bounded JSON line appended atomically
        ↓
sidecar tails the JSONL file
        ↓
sidecar updates summary
```

The hook must:

- Read exactly one JSON object from stdin.
- Accept only a bounded payload.
- Extract only approved fields.
- Redact before writing.
- Use one append operation for each JSON line.
- Never block or rewrite a tool.
- Never return updated input.
- Never approve permissions.
- Never inject context.
- Never perform network I/O.
- Exit zero even if the sidecar is absent.
- Complete within a strict timeout.
- Fail open.

The first approved event fields are limited to:

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

Requirements:

- Explicit exact `model:` frontmatter matching the user-selected worker model.
- Generated-file marker (`goal-devin-generated: true`).
- Run ID marker (`goal-devin-run-id: <run-id>`).
- Minimal tools and permissions suitable for a harmless trial.
- No credentials.
- No hidden instructions unrelated to the trial.
- Remove only the generated profile directory.
- Never remove `.devin/agents`.
- Never remove user profiles.
- Preserve the profile after an abnormal failure only when needed for
  diagnosis, and mark it stale.
- Provide safe stale-profile cleanup on the next run.

Example minimal `AGENT.md`:

```markdown
---
model: <exact-user-selected-model>
goal-devin-generated: true
goal-devin-run-id: <run-id>
---

You are a Goal Devin trial worker. Use the selected model and follow project
instructions. Do not perform destructive operations outside the current task.
```

## 8. Profile loading proof

Creating a file does not prove Devin recognized it. The trial contract
includes two levels of proof.

### Deterministic fake-Devin test

The fake executable verifies:

- Profile path exists before launch.
- Profile frontmatter contains the exact selected worker model.
- Generated config points to the Goal Devin hook.
- Exact root `--model` reaches `devin`.
- Profile is removed after exit.

### Explicit live canary test

A bounded live canary must:

1. Launch with root model `swe-1-7`.
2. Load the generated Goal Devin profile.
3. Invoke it once for a harmless read-only task.
4. Capture the `run_subagent` hook event.
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
language. Both candidates implement the same small contract.

### Candidate A — Python

A contained implementation using the current Python package.

### Candidate B — Rust

A contained launcher prototype that does **not** port the existing
autonomous `GoalLoop`. It may live temporarily under:

```text
experiments/native-launcher-rust/
```

or another clearly isolated location. It must not become the primary package
during the trial.

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

Implement only the Python candidate. Stop after its exact-head review.

### R1B — Rust native-integration candidate

Implement only the equivalent Rust candidate. Do not port existing Goal Devin
behavior. Stop after its exact-head review.

### R1C — Differential evaluation and language decision

Run the shared contract against both candidates. Write an architecture
decision. Do not start the production integration until that decision is
approved.

### R1A acceptance contract

The Python candidate must prove:

1. `goal-devin dev` resolves `devin`, validates model/permission mode, creates
   the runtime directory, generates a temporary config, writes a temporary
   custom profile, and spawns `devin` with inherited `stdin`/`stdout`/`stderr`.
2. The supervisor stays alive and does not call `os.execvp`.
3. A read-only sidecar runs in a separate process and tails the JSONL hook
   events file.
4. The generated `devin` config points `PreToolUse`/`PostToolUse` at the Goal
   Devin hook.
5. The hook appends sanitized events to `hook-events.jsonl` inside the runtime
   directory.
6. At least one `run_subagent` or `PostToolUse` event is captured in the live
   canary and reflected in `summary.json`.
7. The generated custom profile exists before `devin` starts, contains the
   exact worker model in frontmatter, and is removed after exit (or marked
   stale after an abnormal failure and safely cleaned up later).
8. Existing user hooks and config are preserved and not mutated.
9. Credentials remain accessible to `devin` but never appear in the generated
   config, runtime files, logs, or test artifacts.
10. Normal exit, launch failure, and `SIGINT` interruption all leave only
    Goal Devin-owned files, restore the terminal, and print a bounded summary.

### R1B acceptance contract

The Rust candidate must prove the same items as R1A, plus:

1. The Rust candidate must not replace the supervisor process with `exec`.
2. It must produce the exact same argv and runtime artifacts as the Python
   candidate.
3. It must run from `experiments/native-launcher-rust/` (or another isolated
   directory) without disturbing the existing Python package.
4. It must provide its own fake-Devin and live-canary test harness that
   verifies the same hook, profile, and TTY contracts.

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

## 13. Verification plan

1. Run all existing tests: `uv run pytest tests/ -v`.
2. Run Ruff check and format check:
   `uv run ruff check . && uv run ruff format --check .`.
3. Run the deterministic fake-Devin test for the candidate.
4. Run a bounded manual live canary with `goal-devin dev --model swe-1-7` in a
   disposable canary repository.
5. Verify the sidecar captured at least one sanitized `PostToolUse` or
   `run_subagent` event.
6. Verify the generated profile directory under `.devin/agents/` was removed.
7. Verify `goal-devin status` and `goal-devin logs` still work.
8. Scan the diff and runtime artifacts for credentials before final review.

## 14. Known unknowns

- Exact config-precedence behavior when `--config`, project config, user config,
  and `AGENT.md` frontmatter all interact.
- Whether the hook transport must be a single executable file or can be a
  shell/Python script invoked by `devin`.
- Exact Devin CLI behavior when the generated config is unreadable or contains
  a hooks entry for an event not supported by the installed binary.
- Cross-platform runtime directory and signal handling differences (Linux,
  macOS).
