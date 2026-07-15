# Devin CLI — Model Behavior

## Evidence classification

- **DOCUMENTED** — from the official Devin CLI public documentation.
- **OBSERVED LIVE** — from a live `devin` session in this research phase.
- **INFERRED** — deduced from other evidence but not directly observed.
- **UNKNOWN** — not yet determined.

## Available model families (DOCUMENTED)

Devin CLI supports multiple AI model families and recommends "Adaptive" for most users:

- **Adaptive** — intelligent model router that selects the best model for each task.
- Short names like `opus`, `sonnet`, `swe`, `codex`, `gemini` always resolve to the latest version in that model family.
- Cognition SWE family: `SWE-1.7` (latest, free preview until 2026-08-08), `SWE-1.7 Lightning` (Cerebras), `SWE-1.6`, `SWE-1.6 Fast`, `SWE-1.5`, `SWE-1`, `SWE-1-mini`.
- Third-party: Anthropic Claude (`opus`, `sonnet`), OpenAI (`codex`, `gpt`), Google (`gemini`), DeepSeek, Kimi (`kimi-k2.7`), GLM (`glm-5.2`).

Source: `docs.devin.ai/cli/models` and `docs.devin.ai/windsurf/plugins/cascade/models`.

## Setting the model (DOCUMENTED)

| Mechanism | Example | Scope |
|-----------|---------|-------|
| CLI flag | `devin --model opus -- refactor this module` | Single session |
| Slash command | `/model opus`, `/model sonnet`, `/model codex` | In-session switch |
| User config | `~/.config/devin/config.json` (`agent.model`) | User default |
| Subagent profile | `model:` in `AGENT.md` frontmatter | That subagent |

Example user config:

```json
{
  "agent": { "model": "swe-1-6-fast" }
}
```

## Installed CLI `--help` examples (OBSERVED LIVE)

From `devin --help` (version `3000.1.27`):

```text
--model <MODEL>  Model to use (e.g. "claude-sonnet-4", "claude-opus-4.6", "opus", "codex")
```

## Live observed model identifiers (OBSERVED LIVE)

| Where seen | Identifier | Notes |
|------------|------------|-------|
| `devin -p --model swe-1-7` | `swe-1-7` | Accepted and produced output |
| Native TUI header | `SWE-1.7` | Displayed in the bottom status line |
| ATIF export `model_name` | `SWE-1.7` | Export from a `devin -p` session |
| ACP `session/new` response | `swe-1-7`, `swe-1-7-lightning`, `claude-opus-4-8-*`, `claude-sonnet-5-*`, `claude-5-fable-*`, `gpt-5-6-sol-*`, `gpt-5-6-luna-*`, `gpt-5-6-terra-*`, `gemini-3-5-flash-*`, `glm-5-2` (and variants), `kimi-k2-7`, `adaptive` | Listed among available model identifiers |
| Custom subagent `AGENT.md` | `swe-1-6-fast` | Accepted as `model:` frontmatter value |

## Reasoning / thinking levels (DOCUMENTED)

Some models support configurable reasoning levels. The user can cycle the thinking level with `Alt+T` (`Opt+T` on macOS) during a session.

## Model persistence (INFERRED)

The `sessions` SQLite table stores `model TEXT NOT NULL` per session. This implies a resumed session may continue with its original model unless `--model` is re-supplied.

Goal Devin's Python resume code does `model=args.model or state.get("model")`. This matches the intended passthrough behavior.

## Model selection semantics

| Concept | Meaning |
|---------|---------|
| **Configured** | The `agent.model` value in user config or the `--model` argument. |
| **Requested** | The model id passed to `devin --model` or selected in the TUI. |
| **Observed effective** | The actual model producing output. The CLI does not always expose this (e.g., subagent model is not shown in the subagent panel). |

## Unknowns

| Question | Status | Notes |
|----------|--------|-------|
| Exact canonical list accepted by installed `devin` v3000.1.27 | **UNKNOWN** | `--help` only gives examples; ACP response shows additional identifiers. |
| Does resume without `--model` preserve original model? | **STRONGLY INDICATED** | SQLite schema stores model; Goal Devin code preserves it. Live `devin -r <id> -p --model swe-1-7` succeeded in the same session. |
| Does `/model` in an interactive session persist across resume? | **UNKNOWN** | Not yet live-tested. |
| How do unavailable / restricted models fail? | **UNKNOWN** | Likely error message and non-zero exit. |
| How do rate-limited models fail? | **UNKNOWN** | See `DEVIN_RATE_LIMIT_BEHAVIOR.md`. |
| Are internal retries performed? | **UNKNOWN** | Not observable from CLI surface. |
| Does `Adaptive` activate when no model is selected? | **DOCUMENTED** | "Adaptive" is recommended and automatically selects a model per task. |

## Implications for Goal Devin

- Treat model identifiers as opaque strings passed through to `devin --model`.
- Preserve the user's selected model in Goal Devin state; do not silently switch to another model.
- If the user does not specify a model, pass the configured default (`glm-5.2`) or omit `--model` and let Devin use its own default.
- Do not build a fixed enum of valid models; model availability changes frequently.
