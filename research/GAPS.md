# Goal Devin — Research Gaps

This phase intentionally did not implement or run everything. The following gaps are acknowledged and should be addressed before a full architecture/implementation phase.

## Authentication / live session gap

**What we could not do**: Run real `devin -p` or `devin -r` sessions.

**Why**: `devin -p` requires a stored credential or a completed browser/PKCE login. The available `WINDSURF_API_KEY` authenticates `devin acp` API calls but does not satisfy `devin -p` login. A browser login could not be completed headlessly.

**Impact**: Session identity, resume, model behavior, subagent behavior, hooks, rate limits, and real TUI behavior were inferred from documentation, strings, and ACP handshake rather than live observation.

**Mitigation**: 

- The fake `devin` provides a deterministic black-box contract for Goal Devin's current behavior.
- ACP handshake and `session/new` prove the richer integration seam is viable.
- Live session testing should be done in a later phase with a real login or a dedicated service user API key.

## ACP `session/prompt` gap

**What we could not do**: Send a `session/prompt` and observe the full turn lifecycle.

**Why**: It would consume model tokens/ACU and require the ACP server to be authenticated for inference.

**Impact**: Tool-call streaming, permission requests, stop reasons, and error payloads are documented but not empirically verified.

## Real TUI gap

**What we could not do**: Observe the full interactive TUI (alternate screen, resize, mouse, color modes).

**Why**: The TUI requires an authenticated session. Only the startup ANSI sequence capture was possible.

**Impact**: Terminal/theme docs are based on strings and a 5-second TTY capture, not extended usage.

## Rate-limit gap

**What we could not do**: Capture a rate-limit event.

**Why**: No rate limit occurred naturally and intentionally triggering one would be abusive.

## Hook protocol gap

**What we could not do**: Run a real hook and capture stdin/stdout.

**Why**: Hooks fire during lifecycle events inside a `devin -p` session.

## Subagent schema gap

**What we could not do**: Determine the exact input schema or CLI seam for Devin's internal `agent()`/`subagent()` tool.

**Why**: It is an internal feature not exposed through `devin --help`; only strings are available.

## Binary internals gap

**What we could not do**: Confirm the exact Cargo workspace layout, crate graph, or WebSocket/protobuf endpoints.

**Why**: Only non-invasive `strings`, `readelf`, and `ldd` were used. Decompilation was not performed per phase rules.

## Recommended next steps to close gaps

1. Obtain a `cog_` service-user API key or complete `devin auth login` in a controlled environment.
2. Run one minimal `devin -p` session and capture `devin list --format json` output immediately after.
3. Run a full `devin acp` `session/prompt` turn with a trivial prompt and capture `session/update` notifications.
4. Observe the interactive TUI in a real terminal for 30-60 seconds and capture ANSI sequences.
5. Wait for a natural rate-limit event and capture the error shape.
