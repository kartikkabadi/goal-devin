# Live Evidence — Hook Protocol

## Evidence classification

- **DOCUMENTED** — from the official Devin CLI public documentation.
- **OBSERVED LIVE** — from a live `devin` session in this research phase.
- **INFERRED** — deduced from other evidence but not directly observed.
- **UNKNOWN** — not yet determined.

## Purpose

Install observation-only Devin CLI lifecycle hooks in an isolated
configuration, trigger them with real `devin -p` sessions, capture their stdin
payloads, and document the exact JSON shape for each event.

## Environment

- Isolated HOME: `/home/ubuntu/repos/goal-devin/.research-evidence/home-hooks`
- Hook logger: `research/fixtures/hooks/hook-logger.py`
- Hook config: `home-hooks/.config/devin/config.json`
- Hook output dir: `.research-evidence/hooks/` (gitignored)
- Devin CLI version: `3000.1.27`
- Permission mode: `dangerous` (so tools run without blocking permission prompts)

## Hook configuration (DOCUMENTED + OBSERVED LIVE)

Project/user config supports a `hooks` object mapping event names to matcher/hook
lists. The installed `devin` accepted a JSON config with one command hook per
event:

```json
{
  "hooks": {
    "SessionStart": [{"matcher": "", "hooks": [{"type": "command", "command": "python3 /.../hook-logger.py SessionStart", "timeout": 5}]}],
    "UserPromptSubmit": [...],
    "PreToolUse": [...],
    "PostToolUse": [...],
    "PermissionRequest": [...],
    "Stop": [...],
    "SessionEnd": [...]
  }
}
```

## Hook logger behavior

`research/fixtures/hooks/hook-logger.py`:

- Reads a JSON object from stdin.
- Redacts values for keys that may contain prompts, paths, tool output, or
  identifiers (e.g. `session_id`, `prompt`, `command`, `output`, `path`,
  `tool_input`, `tool_response`, `title`, `working_directory`).
- Writes the sanitized payload to `.research-evidence/hooks/<event>.jsonl`.
- Exits 0 immediately without approving, blocking, or rewriting anything.

## Observed payload shapes (OBSERVED LIVE)

All payloads are shown after redaction. Values marked `<REDACTED>` were
sanitized; keys and structure are preserved.

### `SessionStart`

```json
{
  "hook_event_name": "SessionStart",
  "source": "<REDACTED>"
}
```

### `UserPromptSubmit`

```json
{
  "hook_event_name": "UserPromptSubmit",
  "prompt": "<REDACTED>"
}
```

### `PreToolUse`

Examples observed for `glob` and `exec` tools:

```json
{
  "hook_event_name": "PreToolUse",
  "tool_name": "glob",
  "tool_input": {
    "pattern": "*.py",
    "path": "<REDACTED>"
  },
  "tool_use_id": "find_file_by_name_0"
}
```

```json
{
  "hook_event_name": "PreToolUse",
  "tool_name": "exec",
  "tool_input": {
    "command": "<REDACTED>",
    "shell_id": "shell_4"
  },
  "tool_use_id": "exec_8"
}
```

### `PostToolUse`

```json
{
  "hook_event_name": "PostToolUse",
  "tool_name": "glob",
  "tool_input": {
    "pattern": "*.py",
    "path": "<REDACTED>"
  },
  "tool_use_id": "find_file_by_name_0",
  "tool_response": {
    "success": true,
    "output": "<REDACTED>",
    "error": null
  }
}
```

```json
{
  "hook_event_name": "PostToolUse",
  "tool_name": "exec",
  "tool_input": {
    "command": "<REDACTED>",
    "shell_id": "shell_4"
  },
  "tool_use_id": "exec_8",
  "tool_response": {
    "success": true,
    "output": "<REDACTED>",
    "error": null
  }
}
```

### `run_subagent` hook payload (OBSERVED LIVE)

```json
{
  "hook_event_name": "PreToolUse",
  "tool_name": "run_subagent",
  "tool_input": {
    "title": "<REDACTED>",
    "task": "<REDACTED>",
    "profile": "subagent_explore",
    "is_background": false
  },
  "tool_use_id": "run_subagent_0"
}
```

```json
{
  "hook_event_name": "PostToolUse",
  "tool_name": "run_subagent",
  "tool_input": {
    "title": "<REDACTED>",
    "task": "<REDACTED>",
    "profile": "subagent_general",
    "is_background": false
  },
  "tool_use_id": "run_subagent_2",
  "tool_response": {
    "success": true,
    "output": "<REDACTED>",
    "error": null
  }
}
```

### `Stop`

```json
{
  "hook_event_name": "Stop",
  "stop_hook_active": false
}
```

### `SessionEnd`

```json
{
  "hook_event_name": "SessionEnd",
  "reason": "<REDACTED>"
}
```

## Tool names observed (OBSERVED LIVE)

- `glob`
- `exec`
- `run_subagent`
- `read` (implied by tool definitions, not live-triggered in these sessions)
- `edit` (implied by tool definitions)
- `grep` (implied by tool definitions)

## Hook semantics (DOCUMENTED + OBSERVED LIVE)

- Hooks run as external commands.
- They receive the event JSON on stdin and must exit 0 quickly.
- They must not block, rewrite context, or approve tools; that is the parent
  agent's job.
- A non-zero exit or timeout may abort the session, so the observation logger
  always exits 0.

## Unknowns

| Question | Status |
|----------|--------|
| Exact `PermissionRequest` payload shape | **UNKNOWN** (not triggered because `dangerous` mode auto-approves) |
| `PostCompaction` payload shape | **UNKNOWN** (not triggered in these short sessions) |
| Whether hooks receive environment variables with session metadata | **UNKNOWN** |
| Whether `tool_input` schema differs for `read`/`edit`/`grep` | **INFERRED** from tool definitions; not live-observed |

## Implications for Goal Devin

- Hooks are a safe, read-only extension point for policy/observation.
- Goal Devin can install a `PreToolUse`/`PostToolUse` hook to log subagent
  invocations and tool usage without intercepting the TUI.
- The `run_subagent` tool input shape (`title`, `task`, `profile`,
  `is_background`) is now empirically known for v3000.1.27.
- Redaction is mandatory: raw hook transcripts must never be committed.
