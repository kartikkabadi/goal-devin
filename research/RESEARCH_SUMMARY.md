# Goal Devin — Research Summary (Phase R0.6 / R0.7)

This summary documents the corrected product scope and the live Devin
integration evidence collected in Phase R0.5, refined by the R0.6 trial
contract and the R0.7 independent-review corrections. Phase R0 was the initial
baseline; see the commit history for those documents.

## 1. Corrected product scope

- Preserve the existing autonomous `goal`/`resume` loop.
- Add an interactive mode that launches the genuine native Devin TUI and hands
the terminal to `devin`.
- Add Goal Devin-owned status, policy, reliability, and verification around the
native TUI.
- Enforce exact orchestrator model selection; default all workers to the same
model; allow different worker models only through explicit user configuration.
- Detect rate limits and wait for the selected model.
- Use native Devin subagents where appropriate; use independent `devin -p`
sessions only for Goal Devin-owned jobs.
- Remain completely separate from any project named Loop.
- The old `goal-devin ultra --script` trial is superseded by
`research/NATIVE_INTEGRATION_TRIAL.md`.

Full scope: `research/PRODUCT_SCOPE.md`.

## 2. What was corrected from R0

- **Permission modes**: The installed `devin` v3000.1.27 `--help` lists `auto`,
  `accept-edits`, `smart`, `dangerous`, but the executable actually accepts
  `normal` (alias `auto`), `accept-edits`, `dangerous` (aliases `yolo`,
  `bypass`), and `autonomous` (requires `--sandbox`). `smart` is rejected.
  `research/DEVIN_VERSION_COMPATIBILITY.md` documents this discrepancy and the
  feature-detection recommendation.
- **Subagent behavior**: `subagent_general` inherits the parent model,
  `subagent_explore` uses the default subagent model, and custom profiles use
  `model:` in `AGENT.md`. The internal `run_subagent` tool schema was observed
  live: `title`, `task`, `profile`, `is_background`.
- **Model behavior**: `swe-1-7` is a valid identifier for the installed binary.
  The native TUI and ATIF export confirm the effective model `SWE-1.7`.
- **Session identity**: `devin -p --export <path>` produces an ATIF file
  containing the new `session_id` and the effective root model
  (`model_name`). `devin acp` `session/new` returns an explicit `sessionId`.
  Both are **OBSERVED LIVE** and preferred over `devin list --format json`,
  which is a fallback heuristic with a known concurrency race. Native TUI
  `--export` support is still unproven.
- **Hooks**: Observation-only `PreToolUse`/`PostToolUse` hooks are viable and
  expose `tool_name`, `tool_input`, `tool_use_id`, `tool_response`. Trial
  hook injection must not copy or merge user/project config that may
  contain secrets; it must use a project hook file in the disposable canary
  or a hook-only `--config` capability probe.
- **Native TUI**: The TUI enters alternate screen, uses `crossterm` terminal
  sequences (cursor hide, bracketed paste, mouse, Kitty keyboard, synchronized
  updates), displays model `SWE-1.7`, and exits cleanly on `/exit`.
- **Trial contract**: The native-integration trial uses a spool-directory event
  transport, documented-only `AGENT.md` frontmatter, project-only or hook-only
  `--config` hook installation, and symmetrical Python/Rust candidates under
  `experiments/native-launcher-{python,rust,testkit}/`. It does not copy or
  merge secret-bearing user/project config.
- **Authentication**: `devin -p` requires stored credentials in
`~/.local/share/devin/credentials.toml` (or a completed `devin auth login`);
`WINDSURF_API_KEY` alone is not sufficient for `devin -p` but is used by
`devin acp`.

## 3. Live evidence captured

| Document | What it contains |
|----------|------------------|
| `research/LIVE_PRINT_SESSION.md` | Real `devin -p` canary session with `--model swe-1-7`, edit, session id, diff, test status. |
| `research/LIVE_SESSION_RESUME.md` | Resume of the same session id, context continuity, model/cwd preservation. |
| `research/LIVE_HOOK_PROTOCOL.md` | Observation-only hooks, sanitized payload shapes for `PreToolUse`/`PostToolUse`/`run_subagent`/etc. |
| `research/LIVE_SUBAGENT_BEHAVIOR.md` | `subagent_general`, `subagent_explore`, and a custom `reviewer` profile. |
| `research/LIVE_NATIVE_TUI.md` | PTY-driven TUI capture: startup, input, `/exit`, terminal sequences, clean exit. |

## 4. Recommendation for next phase

- Do not implement the full Ultra Code workflow or Rust rewrite yet.
- Run the **native-integration trial** (`research/NATIVE_INTEGRATION_TRIAL.md`):
  - The provisional command is `goal-devin dev`.
  - A supervisor spawns `devin` attached directly to the user's terminal, with a
    separate read-only sidecar.
  - A temporary custom subagent profile is created and cleaned up.
  - Existing commands remain unchanged.
- Split implementation into R1A (Python candidate), R1B (Rust candidate), and
  R1C (differential evaluation and language decision).
- Defer the final language decision until both candidates are measured against
  the same contract.

## 5. Remaining gaps

- Session-identity concurrency race: `devin list --format json` newest-first
  behavior is observed but not proven safe under concurrent session creation,
  list delays, timestamp collisions, or across all Devin versions.
- Rate-limit error shape and retry behavior: not triggered.
- Exact `read_subagent` tool schema and background subagent parent notification.
- Effective subagent model visibility (CLI does not expose it).
- Full interactive TUI features such as model picker and subagent indicator
  (only basic operation observed).
- Long-term session behavior (compaction, large context, multi-turn TUI).
- Config-precedence behavior when `--config`, project config, user config, and
  `AGENT.md` frontmatter interact.

See `research/GAPS.md` for the full gap list.

## 6. Security / credential handling

- The `windsurf_api_key` secret was used only to populate the Devin CLI
credentials file in isolated `HOME` directories. It was never printed, echoed,
passed in argv, committed, or written into fixtures.
- All live evidence and raw transcripts live in `.research-evidence/`, which
is gitignored.
- No authorization values, session transcripts, or account identifiers appear
in committed research documents.
