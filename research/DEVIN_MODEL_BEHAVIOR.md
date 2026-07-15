# Devin CLI — Model Behavior

## Public model identifiers

From `devin --help` (version 3000.1.27):

> `--model <MODEL>` Model to use (e.g. `"claude-sonnet-4"`, `"claude-opus-4.6"`, `"opus"`, `"codex"`)

Additional identifiers seen in public documentation and the `Goal Devin` default:

- `glm-5.2`
- `kimi-k2.7`
- `claude-sonnet-4`
- `claude-opus-4.6`
- `opus`
- `codex`

The CLI help explicitly lists OpenAI/Codex and Anthropic models, and Goal Devin defaults to `glm-5.2` (free GLM/Kimi tier).

## Model persistence

The `sessions` SQLite table stores `model TEXT NOT NULL` per session. This implies:

- A resumed session may continue with its original model unless `--model` is re-supplied.
- The `goal-devin` resume code preserves the model from state: `model=args.model or state.get("model")`.

## Observed resume behavior with fake `devin`

1. `goal-devin goal "..." --model glm-5.2` stores `model: "glm-5.2"`.
2. `goal-devin resume <sid>` without `--model` reads `model` from state and passes it to `devin -r`.
3. `goal-devin resume <sid> --model kimi-k2.7` overrides state.

## Unknowns (not tested)

| Question | Status | Notes |
|----------|--------|-------|
| Are model aliases resolved dynamically? | **UNKNOWN** | `devin --help` gives examples, not a canonical list. |
| Does resume without `--model` preserve original? | **STRONGLY INDICATED** | `Goal Devin` code does this; real CLI likely honors it because `sessions` table stores model. |
| Does `/model` in an interactive session persist? | **UNKNOWN** | Not testable without login. |
| How do unavailable models fail? | **UNKNOWN** | Likely error message and non-zero exit. |
| How do rate-limited models fail? | **UNKNOWN** | See `DEVIN_RATE_LIMIT_BEHAVIOR.md`. |
| Are internal retries performed? | **UNKNOWN** | Not observable from CLI surface. |
| Does `Adaptive` activate without selection? | **UNKNOWN** | No evidence. |

## Implications for Goal Devin

- Goal Devin's `--model` passthrough is correct: it passes the model id literally to `devin --model`.
- A Rust rewrite should keep the same precedence: CLI flag > env `GOAL_DEVIN_MODEL` > default.
- Model strings should be treated as opaque tokens; do not assume a fixed enum.
