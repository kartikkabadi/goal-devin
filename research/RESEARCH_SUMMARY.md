# Goal Devin — Research Summary (Phase R0)

1. **Is Devin CLI confirmed to be Rust?**
   Yes. The binary is a statically linked ELF64 PIE binary with Rust panic strings, Cargo registry source paths, and internal crates named `chisel`, `chisel-agent`, and `scrollback`.

2. **What Rust libraries used by Devin are actually confirmed?**
   `tokio` (1.35.0), `tokio-tungstenite` (0.28.0), `hyper` (0.14.28), `reqwest`, `serde` (1.0.195), `clap` builder (4.5.60), `tracing-subscriber` (0.3.22), `crossterm`, `unsafe-libyaml` (0.2.11), and `rusqlite`/SQLite.

3. **What remains unknown?**
   The exact Cargo workspace graph, WebSocket/protobuf backend schema, full TUI rendering internals, `devin -p` auth flow headless automation, real session identity with `devin list` scope, and rate-limit error shape.

4. **Should Goal Devin be rewritten in Rust?**
   Not in the next phase. The Python code is small, correct, and stdlib-only. Implement `ultra` in Python first; consider Rust only if distribution or TUI performance becomes a hard requirement.

5. **Why?**
   The risk of the rewrite (state path compatibility, argv matrices, worktree lifecycle) outweighs the language benefit at this stage. The `ultra` feature is an orchestration layer that can be built on `asyncio` and `devin -p`/`devin acp` without rewriting the existing CLI.

6. **Which public integration seams should Goal Devin use?**
   Primary: `devin -p` and `devin -r` for single-turn continuation. Secondary: `devin acp` over stdio JSON-RPC for richer session control, model selection, and progress events. Avoid parsing `sessions.db` directly.

7. **Which undocumented behaviors are safe enough to rely on?**
   - `devin list --format json` returns a JSON array with `id` and `working_directory`.
   - `devin acp` uses newline-delimited JSON-RPC and returns `sessionId` from `session/new`.
   - Worktree branches use `goal-devin/<id>` under `.goal-wt/`.

8. **Which are too brittle?**
   - Any assumption about the exact `sessions.db` schema beyond what `devin list` returns.
   - Relying on `WINDSURF_API_KEY` for `devin -p` (it only works for ACP API calls).
   - Parsing internal Rust strings for behavior (they are implementation details).

9. **What exact behavior must a Rust rewrite preserve?**
   The black-box contract in `GOAL_DEVIN_BEHAVIOR_CONTRACT.md`: per-cwd state path, atomic state writes, exact `devin -p`/`devin -r` argv, `devin list` session resolution, worktree create/keep/remove rules, log delimiter format, exit codes, and env var defaults.

10. **What is the proposed first trial slice?**
    Add `goal-devin ultra --script <file>` in Python with `agent()`, `parallel()`, `pipeline()`, `phase()`, `log()`, `budget`, `args`, a `Journal`, and a `CliRenderer`, running against the fake `devin` fixture. See `TRIAL_SLICE.md`.

11. **What evidence was captured live?**
    - Installed `devin` v3000.1.27 and recorded binary metadata.
    - Ran `devin --help`, all subcommand helps, `auth status`, `list --format json`, and TTY startup ANSI capture.
    - Performed a full ACP `initialize` + `session/new` handshake over stdio with `WINDSURF_API_KEY`.
    - Built and ran a fake `devin` to exercise `goal-devin goal`, `resume`, `status`, `logs`, and `version`.
    - Captured `~/.config/devin/`, `~/.local/share/devin/cli/`, `~/.cache/devin/` filesystem layout and `sessions.db` schema.

12. **What could not be tested?**
    - Real `devin -p` / `devin -r` due to login requirement.
    - `session/prompt` via ACP due to token usage.
    - Full interactive TUI, hooks, subagents, rate limits.

13. **Were any credentials exposed?**
    No. The `WINDSURF_API_KEY` value was never logged, printed, or committed. Only the environment variable name appears in the fake `devin` journal, which is gitignored.

14. **Were any permanent user files modified?**
    No. All experiments used isolated `HOME` directories under `.research-evidence/` and a disposable canary Git repository. The only real home change was the installation of `devin` itself, which is expected.

15. **Is the repository ready for the architecture-planning phase?**
    Yes. The research package documents the current baseline, the public Devin seams, the ACP protocol, filesystem and terminal behavior, and a proposed trial slice. The remaining gaps are identified and do not block `ultra` implementation against a fake `devin`.
