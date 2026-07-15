# Devin CLI — Subagent Behavior

## Evidence classification

- **DOCUMENTED** — from the official Devin CLI public documentation.
- **OBSERVED LIVE** — from a live `devin` session in this research phase.
- **INFERRED** — deduced from other evidence but not directly observed.
- **UNKNOWN** — not yet determined.

## Built-in subagent profiles (DOCUMENTED)

| Profile | Description | Tool Access | Model |
|---------|-------------|-------------|-------|
| `subagent_explore` | Read-only codebase exploration and research | Read-only codebase tools + web search; cannot edit files or fetch arbitrary URLs | Default subagent model (SWE-1.6 by default, router-resolved). **Does not satisfy the same-model default** because it is routed through the default subagent model, which may differ from the parent model. |
| `subagent_general` | General-purpose tasks including code changes | Full tool access (foreground) or pre-approved tools only (background) | Same model as the parent agent. Satisfies the Goal Devin same-model default. |

Source: `docs.devin.ai/cli/subagents`.

## Model selection rules (DOCUMENTED)

| Profile | Model source |
|---------|--------------|
| `subagent_explore` | Default subagent model. Not fixed — resolved through a router at spawn time. With the default Subagent router setting it resolves to SWE-1.6. An admin can override it. Because it does not inherit the parent model, it **does not satisfy** the Goal Devin same-model default and should only be used when the user explicitly opts into a routed/different worker model. |
| `subagent_general` | Same model as the parent agent (whatever was selected in the model picker). Satisfies the Goal Devin same-model default. |
| Custom subagent | The `model:` field in `AGENT.md` if set, otherwise the default subagent model. If the `model:` value differs from the parent model, it requires explicit user configuration to satisfy Goal Devin's policy. |

There is no way to name a model for a subagent in a natural-language prompt — the `run_subagent` tool takes a profile, not a model.

## Tool names and live schema (OBSERVED LIVE)

The live `devin -p` sessions produced `PreToolUse` / `PostToolUse` hook payloads for the internal subagent tool:

- Tool name: **`run_subagent`**
- Input schema (observed keys):
  - `title` (string) — subagent title
  - `task` (string) — task description
  - `profile` (string) — e.g. `subagent_explore`, `subagent_general`, or a custom profile id
  - `is_background` (boolean) — `false` for foreground; `true` for background
- Response schema (observed keys):
  - `success` (boolean)
  - `output` (string) — result summary
  - `error` (string or null)
- Tool use id examples: `run_subagent_0`, `run_subagent_1`, `run_subagent_2`

The public documentation also mentions a **`read_subagent`** tool for inspecting subagent state.

## Custom subagent profiles (DOCUMENTED + OBSERVED LIVE)

Custom profiles are defined as `AGENT.md` files inside a named directory under `.devin/agents/<profile-id>/` (or `.agents/agents/<profile-id>/`, or `~/.config/devin/agents/<profile-id>/`).

Live test:

- Created `.devin/agents/reviewer/AGENT.md` with frontmatter `model: swe-1-6-fast`.
- Prompted the root agent: `Use the reviewer subagent to summarize the Python files in this directory.`
- Hook payload confirmed `profile: "reviewer"` in `run_subagent` input.
- The subagent returned a summary of the files.

Frontmatter keys (DOCUMENTED):

- `model:` — pin the subagent model
- tool restrictions / permission rules
- `max-nesting:` — allow nested subagent spawning beyond the default depth of 0

## Native TUI subagent display (DOCUMENTED)

- A subagent indicator appears below the input area for background subagents; `↓` then `Enter` opens the subagent panel.
- Foreground subagent spinner text: "Subagent running · Ctrl+B to run in background".
- The subagent panel shows profile, title, status, elapsed time, and tool call count.
- **DOCUMENTED limitation**: the native TUI does not label which model a running subagent is using.

## Live subagent tests (OBSERVED LIVE)

| Test | Profile | Request | Outcome | Tool input keys |
|------|---------|---------|---------|-----------------|
| List Python files | `subagent_explore` | `Spawn a subagent_explore to list the Python files in this directory and return the result.` | Returned a list of two files | `title`, `task`, `profile`, `is_background: false` |
| Add a docstring | `subagent_general` | `Use a subagent_general to add a harmless docstring comment to hello.py.` | Added a docstring to `hello.py` | `title`, `task`, `profile`, `is_background: false` |
| Custom reviewer | `reviewer` (custom profile) | `Use the reviewer subagent to summarize the Python files in this directory.` | Returned a one-sentence summary per file | `title`, `task`, `profile`, `is_background: false` |

All live tests ran in `devin -p` mode with `--model swe-1-7 --permission-mode dangerous`.

## Foreground / background behavior (DOCUMENTED)

- Foreground subagents behave like the main agent — tool calls can be approved/denied as usual.
- Background subagents run in parallel while the parent continues; unapproved tools are automatically denied.
- Cancel a running subagent: press `x` in the subagent panel (background) or `Ctrl+C`/`Esc` (foreground).
- Resumed subagents always run in the foreground.

## Nesting depth (DOCUMENTED)

By default, subagents cannot spawn their own subagents. Custom profiles can opt in with `max-nesting:`.

## General vs explore model semantics

| Profile | Configured / requested | Observed effective model | Notes |
|---------|------------------------|--------------------------|-------|
| `subagent_general` | Inherits parent model (`swe-1-7`) | **Not independently exposed** | Parent session ATIF shows `SWE-1.7`; subagent model not separately labeled |
| `subagent_explore` | Default subagent model / router | **Not independently exposed** | Observed output is consistent with a cheap/fast model |
| Custom `reviewer` | `swe-1-6-fast` in `AGENT.md` | **Not independently exposed** | Hook payload did not include model; TUI does not label subagent model |

## Distinguishing session types

| Mechanism | Semantics | When to use |
|-----------|-----------|-------------|
| `subagent_*` | Same Devin session context, child conversation chain, native UI integration, parent model inheritance | Most parallel work within a goal |
| `devin -p` independent session | Separate Devin process, separate `sessions.db` row, no native subagent UI | Goal Devin-owned side jobs, verifiers, detached tasks |

Independent `devin -p` sessions are **not** the only available architecture; they should not be conflated with native subagents.

## Unknowns

| Question | Status |
|----------|--------|
| Exact `read_subagent` input/output schema | **UNKNOWN** |
| Background subagent parent notification mechanism | **INFERRED** from docs; not live-tested |
| Nested subagent runtime behavior with `max-nesting` | **UNKNOWN** |
| Whether subagent effective model can be observed from ATIF or hooks | **UNKNOWN** |

## Implications for Goal Devin

- Use `subagent_general` or a Goal Devin-generated custom profile with the exact root `model:` pin as the default same-model worker.
- Use `subagent_explore` for read-only research only when the user explicitly opts into a routed/different worker model; it does not satisfy the same-model default.
- Any Goal Devin-generated custom profile must be session-scoped, clearly owned (e.g. `goal-devin-worker-<nonce>`), narrowly permissioned, and safely cleaned up after exit.
- Do not claim runtime proof of a worker model when only configuration proof exists; Devin does not independently expose the effective subagent model.
- Do not build an alternate fan-out mechanism using independent `devin -p` sessions as the default; reserve that for Goal Devin-owned verifiers or watchers.
- Treat `is_background` as the devin-determined foreground/background flag; Goal Devin should not force background mode for subagents because background subagents cannot prompt for new permissions.
