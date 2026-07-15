# Goal Devin — Rust Architecture Decision

## Question

Should Goal Devin be rewritten in Rust?

## Evidence summary

- The `devin` binary itself is a large (~133 MiB) statically-linked Rust program using `tokio`, `crossterm`, `clap`, `reqwest`, `tokio-tungstenite`, `tracing-subscriber`, and custom crates `chisel`/`chisel-agent`/`scrollback`.
- Goal Devin's current Python implementation is small (~500 LOC), stdlib-only, and passes 58 tests.
- The planned `ultra` dynamic-workflow feature needs:
  - process supervision of multiple `devin -p`/`devin acp` subprocesses;
  - async I/O and concurrency;
  - optional TUI/dashboard with ANSI terminal control;
  - durable state/journal;
  - Git worktree management.

## Options evaluated

### A. Keep Python

Pros:

- Already works; 58 tests pass.
- Zero runtime deps; easy to install with `uv`/`pip`.
- Fast iteration; contributor accessibility.
- `asyncio` + `subprocess` + `curses`/ANSI can implement `ultra` without external runtime deps.

Cons:

- Packaging/distribution is harder than a single binary.
- Async subprocess + TTY handling in Python is workable but less robust than Rust.
- Large-scale concurrency (hundreds of parallel agents) is possible but less ergonomic.

### B. Full Rust rewrite

Pros:

- Single native binary, easy distribution.
- `tokio` + `crossterm`/`ratatui` align with the terminal behavior observed in `devin`.
- Strong types for ACP JSON-RPC and workflow state.
- Can link to or shell out to `devin` equally well.

Cons:

- Major rewrite risk; must preserve exact `devin -p`/`devin -r` argv matrices and state paths.
- Larger binary; longer compile times; steeper contributor curve.
- No evidence that Rust is *required* for the feature set.

### C. Rust core + Python compatibility wrapper (recommended against)

Pros: best of both worlds in theory.

Cons: doubles maintenance; FFI or RPC overhead for simple CLI tasks.

### D. Python rewrite with optional Rust sidecar (recommended for v2)

Keep Python for the CLI and add a Rust binary for the heavy ACP/TUI sidecar only when needed. This is the lowest-risk path to `ultra`.

## Recommendation

**Do not rewrite Goal Devin in Rust in the next phase.**

Rationale:

1. The current Python code is small, correct, and well-tested.
2. The `ultra` feature can be implemented in Python using `asyncio` + `devin -p` sessions + an ANSI dashboard, with zero new runtime dependencies.
3. The primary risk is not language choice but **integration correctness** (argv, session identity, worktree lifecycle, ACP framing). Those are the same regardless of language.
4. A Rust rewrite should only happen after the `ultra` Python implementation proves the design, and after a decision is made to optimize distribution or TUI performance.

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

Keep Python for now. Add `ultra` in Python. Revisit Rust only when distribution, performance, or TUI depth justify the rewrite cost.
