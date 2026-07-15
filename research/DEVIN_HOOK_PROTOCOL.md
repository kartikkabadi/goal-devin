# Devin CLI — Hook Protocol

## Status

Hooks are a **DOCUMENTED PREVIEW** extensibility feature. The information below is from public docs; no empirical hook execution was performed because creating a hook requires an authenticated `devin -p` session to trigger lifecycle events.

## Lifecycle events

| Event | When it fires | Can block? | Can inject context? |
|-------|---------------|------------|---------------------|
| `PreToolUse` | Before a tool executes | Yes | Yes |
| `PostToolUse` | After a tool finishes | No | Yes |
| `PermissionRequest` | Permission decision needed | Yes | Yes |
| `UserPromptSubmit` | User sends a message | Yes? | Yes? |
| `Stop` | Agent wants to stop | ? | ? |
| `SessionStart` | New session begins | No | Yes |
| `SessionEnd` | Session ends | No | Yes |
| `PostCompaction` | After compaction | No | ? |

## Configuration location

- Project: `.devin/hooks.json` (or `.devin/*.json`)
- User: `~/.config/devin/hooks.json` or similar
- Also picks up `.claude/` directories for compatibility.

Example shape:

```json
{
  "PreToolUse": [
    {
      "matcher": "exec",
      "hooks": [
        {
          "type": "command",
          "command": "./scripts/check-command.sh",
          "timeout": 10
        }
      ]
    }
  ]
}
```

## Stdin / stdout contract (public docs)

### Input (stdin)

A command hook receives JSON on stdin. Example for `PreToolUse`:

```json
{
  "hook_event_name": "PreToolUse",
  "tool_name": "exec",
  "tool_input": {
    "command": "rm -rf /",
    "shell_id": "main"
  }
}
```

For `PostToolUse`:

```json
{
  "hook_event_name": "PostToolUse",
  "tool_name": "exec",
  "tool_input": { ... },
  "tool_response": {
    "success": true,
    "output": "...",
    "error": null
  }
}
```

For `PermissionRequest`:

```json
{
  "hook_event_name": "PermissionRequest",
  "tool_name": "exec",
  "tool_input": { ... }
}
```

### Output (stdout)

A command hook may print a JSON object:

| Field | Purpose |
|-------|---------|
| `decision` | `"approve"` or `"block"` |
| `reason` | Explanation shown to agent |
| `hookSpecificOutput.additionalContext` | Text injected into the agent context |

## Known unknowns

- Exact schema for `UserPromptSubmit`, `Stop`, `SessionStart`, `SessionEnd`, `PostCompaction`.
- Exit-code semantics when a hook wants to block vs. when it crashes.
- Whether multiple hooks run for one event and in what order.
- Timeout default and whether a slow hook blocks the agent.
- Whether hooks run for subagent sessions.

## Implications for Goal Devin

- Goal Devin does not currently use hooks. The native-integration trial will use
  the Devin CLI's documented `PreToolUse`/`PostToolUse` command hooks as a
  read-only observation seam; it must not copy secret-bearing user/project
  config to install them.
- The `ultra` workflow runtime and `agent()` hooks are **superseded** historical
  proposals. Goal Devin orchestrates the `devin` CLI via native mode and
  subagents, not a separate workflow runtime.
