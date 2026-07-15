# Goal Devin — Research Summary (Phase R0.5)

This summary documents the corrected product scope and the live Devin
integration evidence collected in Phase R0.5. Phase R0 was the initial
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
- **Public interfaces**: `devin list --format json` returns `id`, `short_id`,
  `working_directory`, `working_directory_display`, `last_activity_at`,
  `last_activity_ago`, `title`. The first element is the newest session.
- **Hooks**: Observation-only `PreToolUse`/`PostToolUse` hooks are viable and
  expose `tool_name`, `tool_input`, `tool_use_id`, `tool_response`.
- **Native TUI**: The TUI enters alternate screen, uses `crossterm` terminal
  sequences (cursor hide, bracketed paste, mouse, Kitty keyboard, synchronized
  updates), displays model `SWE-1.7`, and exits cleanly on `/exit`.
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
- Run the **native-integration trial** in Python first
(`research/NATIVE_INTEGRATION_TRIAL.md`):
  - `goal-devin start` launches `devin` with the user's terminal attached.
  - A sidecar observes at least one hook event.
  - A temporary custom subagent profile is created and cleaned up.
  - Existing commands remain unchanged.
- Defer the final Python-vs-Rust language decision until the trial proves the
integration contract.

## 5. Remaining gaps

- Rate-limit error shape and retry behavior: not triggered.
- Exact `read_subagent` tool schema and background subagent parent notification.
- Effective subagent model visibility (CLI does not expose it).
- Full interactive TUI features such as model picker and subagent indicator
  (only basic operation observed).
- Long-term session behavior (compaction, large context, multi-turn TUI).

See `research/GAPS.md` for the full gap list.

## 6. Security / credential handling

- The `windsurf_api_key` secret was used only to populate the Devin CLI
credentials file in isolated `HOME` directories. It was never printed, echoed,
passed in argv, committed, or written into fixtures.
- All live evidence and raw transcripts live in `.research-evidence/`, which
is gitignored.
- No authorization values, session transcripts, or account identifiers appear
in committed research documents.
