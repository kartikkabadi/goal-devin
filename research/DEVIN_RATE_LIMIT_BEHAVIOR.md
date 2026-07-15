# Devin CLI — Rate-Limit Behavior

## Status

No real rate-limit event was observed in this research phase. The account used is a Devin session account with unknown quota, and intentionally triggering rate limits would be abusive and consume paid usage.

## Expected public shape (from API docs)

The Devin API uses `cog_`-prefixed bearer tokens and returns standard HTTP rate-limit headers. The CLI likely surfaces rate limits as:

- Non-zero exit code (`1` or `124`).
- Error message on stderr mentioning "rate limit" or "too many requests".
- A `retry-after` value or reset timestamp.

The `sessions` table has no `rate_limit` column, so rate-limit state is either transient or stored in `metadata`/`cogs_json`.

## Proposed capture procedure (for implementation phase)

When a rate-limit event occurs naturally:

1. Record `devin -p` or `devin acp` exit code, stdout, stderr.
2. Record any HTTP response headers if visible (ACP may expose them in `session/update` errors).
3. Record model ID and request ID from error text.
4. Note whether the session remains valid.
5. Note whether `continue` resumes safely.
6. Save sanitized fixture to `.research-evidence/` and add to this doc.

## Implications for Goal Devin

- The `ultra` workflow runtime must handle `devin -p` non-zero exits gracefully, but should distinguish rate-limit exits from content errors.
- If `devin acp` is adopted, rate-limit errors will arrive as `session/update` error payloads; the wrapper should back off and retry or surface to the user.
- A `Budget` abstraction in `ultra` should track approximate agent-call count, but cannot reliably track ACU usage without a public API.

## Unknowns

All rate-limit details remain **UNKNOWN** until a real event is captured.
