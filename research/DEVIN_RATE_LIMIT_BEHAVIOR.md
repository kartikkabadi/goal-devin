# Devin CLI — Rate-Limit Behavior

## Evidence classification

- **DOCUMENTED** — from the official Devin CLI public documentation.
- **OBSERVED LIVE** — from a live `devin` session in this research phase.
- **INFERRED** — deduced from other evidence but not directly observed.
- **UNKNOWN** — not yet determined.

## Status

No real rate-limit event was observed in this research phase. Intentionally
generating traffic to trigger a rate limit would be abusive and consume paid
usage, so the gap is preserved honestly.

A related clue observed in the native TUI: the status line showed a usage quota
with a percentage remaining and a reset time (e.g. `<plan> · <usage>% remaining
(resets in <duration>)`). This confirms that the CLI tracks quota, but the
rate-limit error path itself was not exercised.

## Expected public shape (DOCUMENTED + INFERRED)

The Devin API uses bearer tokens and returns standard HTTP rate-limit headers.
The CLI likely surfaces rate limits as:

- Non-zero exit code (`1` or `124`).
- Error message on stderr mentioning "rate limit" or "too many requests".
- A `retry-after` value or reset timestamp.

For ACP, rate-limit errors may arrive as `session/update` error payloads with
retry hints.

## Proposed capture procedure (for implementation phase)

When a rate-limit event occurs naturally:

1. Record `devin -p` or `devin acp` exit code, stdout, stderr.
2. Record any HTTP response headers if visible (ACP may expose them in `session/update` errors).
3. Record model ID and request ID from error text.
4. Note whether the session remains valid.
5. Note whether `continue` resumes safely.
6. Save sanitized fixture to `.research-evidence/` and add to this doc.

## Implications for Goal Devin

- The Goal Devin orchestrator must handle `devin -p` non-zero exits gracefully,
  but should distinguish rate-limit exits from content errors.
- If `devin acp` is adopted, rate-limit errors will arrive as `session/update`
  error payloads; the wrapper should back off and retry or surface to the user.
- A `Budget` abstraction can track agent-call count, but cannot reliably track
  ACU usage without a public API.

## Unknowns

| Question | Status |
|----------|--------|
| Exact error message / exit code for rate limit | **UNKNOWN** |
| `retry-after` or reset timestamp format | **UNKNOWN** |
| Whether the CLI internally retries | **UNKNOWN** |
| Whether a session is still valid after a rate-limit error | **UNKNOWN** |
| Per-model rate limits | **UNKNOWN** |
