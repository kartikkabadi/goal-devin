# Goal Devin — Product Scope (corrected)

This document replaces any prior product interpretation. It aligns Goal Devin with the actual Devin CLI product surface and the user's intent to port Ultra Code *concepts* (orchestrator/worker model selection, sticky model policy, transient-failure handling, bounded retries, reliability around long-running agent sessions) without importing Claude Code's dynamic-workflow scripting API as the central product.

## In scope

1. **Preserve and harden the existing autonomous goal-loop functionality.**
   - The `goal` and `resume` subcommands must continue to work exactly as they do today.
   - Per-cwd state, atomic state writes, `devin list` session resolution, worktree create/keep/remove rules, log format, exit codes, and env var defaults must be preserved.

2. **Add an interactive `dev` mode that launches the genuine native Devin TUI.**
   - The provisional command is `goal-devin dev`.
   - `goal-devin` should be able to hand the terminal to `devin` (no argv translation to `devin -p`) so the user gets the real Devin interactive experience.
   - `devin` remains directly attached to the user's terminal.

3. **Keep Devin directly attached to the user's terminal.**
   - Goal Devin is a launcher/supervisor, not a middleman that intercepts or re-renders the Devin TUI.
   - The native TUI owns the terminal for the duration of the session.

4. **Add Goal Devin-owned status, policy, reliability, and verification around the native TUI.**
   - Before launch: show session model, permission mode, worktree status, and any policy warnings.
   - After exit: record outcome, show summary, maintain logs, and (later) verify expected software-development outcomes.

5. **Model selection.**
   - Let the user select **one exact orchestrator model** for a session.
   - Default all workers to the **same exact model**.
   - Allow a different worker model only through **explicit user configuration**.
   - Never silently switch models.

6. **Rate-limit and transient-failure handling.**
   - Detect rate limits.
   - Wait for the selected model.
   - Safely continue on that same model.
   - Use bounded retries.

7. **Subagent usage.**
   - Use **native Devin subagents** where appropriate (read-only `subagent_explore`, write-capable `subagent_general`, custom profiles).
   - Use independent `devin -p` sessions only for explicitly Goal Devin-owned jobs where independent sessions are semantically correct (e.g., stateless verifiers, detached watchers).

8. **Existing commands.**
   - Continue supporting `goal`, `resume`, `status`, and `logs`.

9. **Future deterministic software-development verifiers and release gates.**
   - Design the status/log/policy layer to eventually support outcome verification (tests, diffs, review gates) without implementing them now.

10. **Remain completely separate from any project named Loop.**

## Out of scope (this phase and the next implementation trial)

- A `goal-devin ultra --script <file>` workflow scripting DSL.
- Arbitrary parallel independent `devin -p` sessions as the primary fan-out mechanism.
- A full Rust rewrite of Goal Devin.
- A complete native-TUI reimplementation or dashboard.
- Rate-limit auto-retry (to be designed after evidence).
- PTY interception, keyboard injection, or screen scraping of the Devin TUI.

## Relationship to Ultra Code / dynamic workflows

Ultra Code is an architectural reference for:

- preserving a native agent interface;
- orchestrator/worker model selection;
- sticky model policy;
- transient-failure handling;
- bounded retries;
- reliability around long-running agent sessions.

It is **not** a request to make Claude Code's `agent()`/`parallel()`/`pipeline()` JavaScript/TypeScript API the central Goal Devin product. Goal Devin orchestrates the Devin CLI, not a language-agnostic workflow runtime.

## Language and integration strategy

The current Python implementation remains the behavioral oracle and stable implementation.
A small native-integration trial will compare a Python candidate and a Rust candidate for the launcher/sidecar, but **no major new workflow feature or rewrite should be built before that trial**.
