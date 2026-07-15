# Goal Devin — Product Scope (corrected)

This document replaces any prior product interpretation. It aligns Goal Devin with the actual Devin CLI product surface and the user's intent to port Ultra Code *concepts* (orchestrator/worker model selection, sticky model policy, transient-failure handling, bounded retries, reliability around long-running agent sessions) without importing Claude Code's dynamic-workflow scripting API as the central product.

## In scope

1. **Preserve and harden the existing autonomous goal-loop functionality.**
   - The `goal` and `resume` subcommands must continue to work exactly as they do today.
   - Per-cwd state, atomic state writes, explicit session resume behavior, worktree create/keep/remove rules, log format, exit codes, and env var defaults must be preserved.
   - Session identity must prefer `devin -p --export` ATIF and ACP `session/new`, test native TUI `--export` support, and keep `devin list --format json` only as a compatibility fallback with a known concurrency race. Goal Devin must never parse Devin's private `sessions.db`.

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

5. **Model selection and worker policy.**
   - Let the user select **one exact orchestrator model** for a session.
   - Default all workers to the **same exact model** as the root session.
   - `subagent_general` satisfies this default because it inherits the parent model.
   - A Goal Devin-generated custom profile with an exact `model:` pin is the default read-only or policy-specific worker.
   - `subagent_explore` does **not** satisfy the same-model default because Devin routes it through the default subagent model, which may differ from the root model.
   - `subagent_explore` may only be used when the user explicitly opts into a routed/different worker model.
   - Any other custom profile that uses a different model also requires explicit user configuration.
   - Never silently switch models.
   - Because Devin does not expose the effective subagent model independently, Goal Devin must distinguish:
     - the selected policy;
     - the configured/requested model (frontmatter or profile choice);
     - the observed effective model (where it can be inferred from ATIF or other non-invasive evidence).
   - Never claim runtime proof of a worker model when only configuration proof exists.

6. **Rate-limit and transient-failure handling.**
   - Detect rate limits.
   - Wait for the selected model.
   - Safely continue on that same model.
   - Use bounded retries.

7. **Subagent usage.**
   - Use **native Devin subagents** where appropriate.
   - The default same-model worker is `subagent_general` or a Goal Devin-generated custom profile with the exact root model.
   - `subagent_explore` is only appropriate when the user explicitly accepts a routed/different worker model.
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
- Production-grade enforcement of worker model selection (R1A/R1B prove profile generation and loading only; enforcement belongs to a later bounded phase).

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
