# Goal Devin — Rust Architecture Decision

## Status

**The final language decision is deferred until the native-integration trial
completes.** The existing Python implementation remains the behavioral oracle
and stable implementation. No major new workflow feature or production rewrite
should be built before the trial described in
`research/NATIVE_INTEGRATION_TRIAL.md`.

The next implementation phase is split into:

- **R1A** — Python native-integration candidate in
  `experiments/native-launcher-python/`.
- **R1B** — Rust native-integration candidate in
  `experiments/native-launcher-rust/`.
- **R1C** — Differential evaluation and language decision.

## Question

Should the Goal Devin native launcher/sidecar be implemented in Python or Rust?

## Evidence summary

- The `devin` binary itself is a large (~133 MiB) statically-linked Rust
  program using `tokio`, `crossterm`, `clap`, `reqwest`, `tokio-tungstenite`,
  `tracing-subscriber`, and custom crates `chisel`/`chisel-agent`/`scrollback`.
- Goal Devin's current Python implementation is small, stdlib-only, and passes
  58 tests.
- The corrected product scope (`research/PRODUCT_SCOPE.md`) prioritizes a native
  Devin TUI launcher, model selection passthrough, Goal Devin-owned
  status/policy, and native subagent usage over a workflow-scripting DSL or full
  rewrite.

## Trial approach

Both candidates implement the same small contract documented in
`research/NATIVE_INTEGRATION_TRIAL.md`. They share a single testkit under
`experiments/native-launcher-testkit/`:

```text
experiments/
  native-launcher-python/   # R1A
  native-launcher-rust/     # R1B
  native-launcher-testkit/  # shared fake devin, canary, fixtures, runner
```

The language decision must be based on a measured comparison, not on:

- Devin being written in Rust.
- Existing Goal Devin being written in Python.
- One candidate merely "working."
- Subjective language preference.

The final decision rule is **not** "try Python; use Rust only if Python fails."
Basic subprocess launching is expected to work in either language. The
interesting differences are signal handling, TTY ownership, sidecar isolation,
startup latency, idle memory, test complexity, packaging complexity,
cross-platform prospects, and long-term ability to support ACP and rate-limit
state machines.

### Candidate A — Python

A contained implementation under `experiments/native-launcher-python/`. It adds
a candidate-local `dev` executable, supervisor, sidecar, and temporary custom
profile without disturbing the existing `goal`/`resume` loop or the production
`goal-devin` package.

Pros:

- Uses the existing Python test harness and fake `devin` fixture through the
  shared testkit.
- Fastest path to a working end-to-end trial.
- Easy to iterate and measure.

Cons:

- Requires Python in the user's environment (already required by `goal-devin`).
- Less portable as a single static binary if distribution becomes a goal later.
- Long-running process supervision and TTY handling are workable but less robust
  than Rust.

### Candidate B — Rust

A contained launcher prototype under `experiments/native-launcher-rust/` that
does **not** port the existing autonomous `GoalLoop`. It reuses the shared testkit
and must prove the same hook, profile, and TTY contracts as the Python
candidate. It must not become the primary package during the trial.

Pros:

- Self-contained static binary, no Python dependency for the launcher.
- Easier to reason about long-running process lifetimes and signal handling.
- Aligns with the `devin` runtime stack (`tokio`, `crossterm`).

Cons:

- Requires building the Rust project, dependency resolution, and a new test
  harness.
- Re-implementing the `GoalLoop`/worktree/state layer would be out of scope.
- Must reuse the shared testkit; it cannot rely on a separate independent
  acceptance harness.

## Evaluation criteria

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

## R1C measurement methodology

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

Do not use subjective impressions as a deciding metric. The full methodology is
also recorded in `research/NATIVE_INTEGRATION_TRIAL.md`.

## Decision rule

1. Run **R1A** (Python) and stop at its exact-head review.
2. Run **R1B** (Rust) and stop at its exact-head review.
3. Run **R1C**: execute the shared black-box contract against both candidates,
   measure the criteria above using the shared methodology, and write an
   architecture decision.
4. Do **not** start the production integration until the R1C decision is
   approved.

The final language decision must be justified by the measured comparison, not
by language bias or the fact that one candidate works.

## If Rust is chosen later

If R1C selects Rust, the production integration should still keep the existing
Python `GoalLoop`/worktree/state as the behavioral oracle initially and replace
only the launcher/sidecar surface. The full rewrite of Goal Devin in Rust is
out of scope for the trial and should be a separate, later decision.

Proposed Rust workspace (provisional):

```text
crates/
  goal-devin-cli          # argv, subcommands, config
  goal-devin-core         # GoalLoop, state, journal, budget
  goal-devin-process      # devin/ACP process spawning
  goal-devin-devin        # ACP client, session identity
  goal-devin-git          # worktree helpers
  goal-devin-policy       # permission/sandbox passthrough
  goal-devin-rate-limit   # backoff/retry
  goal-devin-tui          # optional Ratatui/crossterm dashboard
  goal-devin-testkit      # fake devin / behavior tests
```

Candidate crates:

| Concern | Candidate | Justification |
|---------|-----------|---------------|
| CLI | `clap` | Established, matches Devin CLI. |
| Async | `tokio` | Matches Devin runtime. |
| Serialization | `serde` + `serde_json` | Matches Devin. |
| JSON-RPC/ACP | manual `tokio::io` + `serde_json` | ACP is line-delimited, simple. |
| Error handling | `thiserror` / `eyre` | `color-eyre` seen in Devin; avoid for lib. |
| Termcap | `crossterm` | Confirmed in Devin; portable. |
| TUI | `ratatui` | If a rich TUI is needed; Devin uses custom `scrollback`, but Ratatui is the community standard. |
| Git | `git2` or `gix` | Worktree/branch operations. |
| SQLite | `rusqlite` | If mirroring `sessions.db` locally. |
| Testing | `insta` / `assert_cmd` | Snapshot and CLI assertions. |

## Conclusion

Defer the Rust decision to R1C. Keep Python as the behavioral oracle. Run both
candidates against the same native-integration contract, measure them with the
shared methodology, then decide.
