# Devin CLI — ACP Protocol

## Evidence classification

- **DOCUMENTED** — from the official Devin CLI public documentation.
- **OBSERVED LIVE** — from a live `devin` session in this research phase.
- **INFERRED** — deduced from other evidence but not directly observed.
- **UNKNOWN** — not yet determined.

## Transport

`devin acp` uses **newline-delimited JSON-RPC 2.0** over stdio, **not** LSP
`Content-Length` framing. Each message is a single JSON object terminated by
`\n`.

Incorrect framing (e.g. LSP `Content-Length` headers) produces:

```json
{"jsonrpc":"2.0","error":{"code":-32700,"message":"Parse error","data":{"line":"Content-Length: 270"}}}
```

## Handshake (`initialize`)

### Request

```json
{
  "jsonrpc": "2.0",
  "id": 1,
  "method": "initialize",
  "params": {
    "protocolVersion": 1,
    "clientCapabilities": {
      "fs": {"readTextFile": true, "writeTextFile": false},
      "terminal": false
    },
    "clientInfo": {
      "name": "goal-devin-research-probe",
      "title": "Goal Devin Research Probe",
      "version": "0.0.0"
    }
  }
}
```

### Response

```json
{
  "jsonrpc": "2.0",
  "id": 1,
  "result": {
    "protocolVersion": 1,
    "agentCapabilities": {
      "loadSession": true,
      "promptCapabilities": {"image": true, "audio": false, "embeddedContext": true},
      "mcpCapabilities": {"http": false, "sse": false},
      "sessionCapabilities": {"list": {}, "additionalDirectories": {}},
      "_meta": {
        "cognition.ai/multiRootWorkspace": true,
        "cognition.ai/sessionRename": true,
        "cognition.ai/documentLifecycle": true,
        "cognition.ai/terminalLifecycle": true
      }
    },
    "authMethods": [
      {"id": "devin-browser", "name": "Log in with browser", "description": "Sign in via your browser"}
    ],
    "agentInfo": {
      "name": "affogato",
      "title": "Affogato Agent",
      "version": "0.0.0-dev"
    },
    "_meta": {
      "mcpConfigPath": "<home>/.config/devin/config.json"
    }
  }
}
```

Key takeaways:

- Agent name is `affogato`.
- Only `devin-browser` auth method is advertised in this environment.
- Capabilities include session loading, image prompts, embedded context, multi-root workspace, etc.
- `mcpCapabilities` were `http:false, sse:false` in our minimal client; a richer client may enable them.

## Session creation (`session/new`)

### Request

```json
{
  "jsonrpc": "2.0",
  "id": 2,
  "method": "session/new",
  "params": {
    "cwd": "/tmp",
    "mcpServers": []
  }
}
```

### Response

```json
{
  "jsonrpc": "2.0",
  "id": 2,
  "result": {
    "sessionId": "humorous-impatiens",
    "modes": { "currentModeId": "accept-edits", ... },
    "configOptions": [
      { "id": "mode", "name": "Session Mode", "type": "select", "currentValue": "accept-edits", ... },
      { "id": "model", "name": "Model", "type": "select", "currentValue": "swe-1-7", "options": [ ... ] }
    ]
  }
}
```

The session ID is a human-readable phrase (`<adjective>-<noun>`). The response
also streams a `session/update` notification before the result with the initial
config options (mode, model, etc.).

## Model list observed in ACP (OBSERVED LIVE)

The `model` config option returned by `session/new` included identifiers such as:

- `swe-1-7`, `swe-1-7-lightning`
- `claude-opus-4-8-*` (medium/low/high/xhigh/max + fast variants)
- `claude-sonnet-5-*`
- `claude-5-fable-*`
- `gpt-5-6-sol-*`, `gpt-5-6-luna-*`, `gpt-5-6-terra-*`
- `gemini-3-5-flash-*`
- `glm-5-2` (and `max`, `1m`, `none`, `none-1m` variants)
- `kimi-k2-7`
- `adaptive`

This is the strongest evidence for the exact model identifiers accepted by the
installed binary. The list should be treated as a snapshot; future versions may
add or remove identifiers.

## Session update notifications

Before the `session/new` result, Devin sent `session/update` notifications:

- `sessionUpdate: "config_option_update"` — mode/model/config options.
- `sessionUpdate: "current_mode_update"` — `accept-edits`.
- `sessionUpdate: "available_commands_update"` — slash commands (`login`, `logout`, `status`, `workspace`, `add-dir`, `ask`, `compact`, `context`, `session-stats`, `bug`, `help`, `declarative-repo-setup`).

This confirms ACP is the richer integration seam for model selection, mode
changes, and command availability.

## ACP vs. CLI `devin -p`

- `devin acp` can create a session (`session/new`) without interactive login,
  using `WINDSURF_API_KEY` for API calls.
- `devin -p` (single-turn print mode) requires stored credentials and refuses
  to run headless.
- This suggests `devin -p` is not a thin wrapper over ACP; it has its own
  auth/UI path.

## Sufficient for Goal Devin?

| Need | ACP feasibility |
|------|-----------------|
| Model discovery | **Yes** — `initialize`/`session/new` return model list. |
| Session identity | **Yes** — `session/new` returns `sessionId`. |
| Autonomous execution | **Partial** — `session/prompt` not tested; likely requires auth. |
| Rate-limit evidence | **Unknown** — would need an actual `session/prompt`. |
| Worker/subagent model evidence | **Unknown** — ACP exposes `subagents` capability but not tested. |
| TUI sidecar telemetry | **Yes** — `session/update` provides progress events. |

## Proposed ACP integration for Goal Devin (future)

Rather than wrapping `devin -p` and guessing session IDs, a Goal Devin sidecar
could:

1. Spawn `devin acp` as a long-lived subprocess.
2. Send `initialize` and `session/new`.
3. Send `session/prompt` for each iteration.
4. Listen to `session/update` for progress, tool calls, and final answer.
5. Send `session/cancel` on `Ctrl+C`.

This would replace the brittle `devin -p` / `devin list` loop. However, it
requires keeping `devin acp` running, handling JSON-RPC framing, and dealing
with auth.

## Not tested

- `session/prompt` (would consume model tokens).
- `session/load` and `session/resume`.
- `session/cancel`.
- `authenticate` request.
- Client methods (`fs/readTextFile`, `fs/writeTextFile`, `terminal/*`).
- Permission request flow.
