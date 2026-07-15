# Goal Devin — Rust Architecture Decision

## Status

**Final language decision is deferred until the native-integration trial
completes.** The existing Python implementation remains the behavioral oracle
and stable implementation. No major new workflow feature or Rust rewrite
should be built before the trial described in `research/NATIVE_INTEGRATION_TRIAL.md`.

## Question

Should Goal Devin be rewritten in Rust?

## Evidence summary

- The `devin` binary itself is a large (~133 MiB) statically-linked Rust program using `tokio`, `crossterm`, `clap`, `reqwest`, `tokio-tungstenite`, `tracing-subscriber`, and custom crates `chisel`/`chisel-agent`/`scrollback`.
- Goal Devin's current Python implementation is small, stdlib-only, and passes 58 tests.
- The corrected product scope (`research/PRODUCT_SCOPE.md`) prioritizes a native Devin TUI launcher, model selection passthrough, Goal Devin-owned status/policy, and native subagent usage over a workflow-scripting DSL or full rewrite.

## Options evaluated

### A. Keep Python for the trial

Pros:

- Already works; existing tests pass.
- Zero runtime deps; easy to install with `uv`/`pip`.
- Fast iteration; contributor accessibility.
- Can spawn `devin` directly with the user's terminal and run a read-only sidecar.

Cons:

- Packaging as a single binary is harder.
- Long-running process supervision and TTY handling are workable but less robust than Rust.

### B. Full Rust rewrite

Pros:

- Single native binary, easy distribution.
- `tokio` + `crossterm`/`ratatui` align with the terminal behavior observed in `devin`.
- Strong types for ACP JSON-RPC and workflow state.

Cons:

- Major rewrite risk; must preserve exact `devin -p`/`devin -r` argv matrices and state paths.
- Larger binary; longer compile times; steeper contributor curve.
- No evidence that Rust is *required* for the corrected feature set.

### C. Rust launcher/sidecar with Python core

Pros:

- Keeps existing Python `GoalLoop`/state/worktree implementation.
- Rust handles the terminal-owned `devin` spawn and read-only sidecar.

Cons:

- Two runtimes to build and test; RPC or file-based coordination overhead.
- Adds complexity before the integration contract is proven.

## Recommendation

1. **Do not rewrite Goal Devin in Rust in the next phase.**
2. **Run the Python native-integration trial first** (`research/NATIVE_INTEGRATION_TRIAL.md`).
3. **Revisit Rust only if** the trial shows Python cannot reliably spawn `devin`, observe hooks, and clean up temp files, or if a single-binary distribution becomes an explicit requirement.

Rationale:

- The current Python code is small, correct, and well-tested.
- The primary risk is integration correctness (argv, session identity, model passthrough, worktree lifecycle, ACP/hook behavior), not language performance.
- Those integration risks are the same in Python and Rust; proving them in Python first is lower cost.

## If Rust is chosen later

Proposed workspace (provisional):

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

Defer the Rust decision. Keep Python as the behavioral oracle. Implement the
native-integration trial in Python, then decide whether Rust is justified.
