# Devin CLI — Public Interface Inventory

## CLI (global)

Observed from `devin --help` (real binary, version 3000.1.27).

| Interface | Status | Notes |
|-----------|--------|-------|
| `devin [OPTIONS] [-- <PROMPT>...] [COMMAND]` | **DOCUMENTED AND STABLE** | Main invocation pattern. |
| `--prompt-file <FILE>` | **DOCUMENTED AND STABLE** | Load initial prompt from file. |
| `--config <PATH>` | **DOCUMENTED AND STABLE** | Override `~/.config/devin/config.json`. |
| `--permission-mode <MODE>` (env `DEVIN_PERMISSION_MODE`) | **DOCUMENTED AND STABLE** | Modes: `auto`, `accept-edits`, `smart`, `dangerous`; default `auto`. |
| `--sandbox` (env `DEVIN_SANDBOX`) | **DOCUMENTED PREVIEW** | OS-level sandbox; `bwrap+seccomp` on Linux. |
| `--model <MODEL>` (env `DEVIN_MODEL`) | **DOCUMENTED AND STABLE** | e.g. `claude-sonnet-4`, `claude-opus-4.6`, `opus`, `codex`, `glm-5.2`, `kimi-k2.7`. |
| `-p, --print [<PROMPT>]` | **DOCUMENTED AND STABLE** | Non-interactive single-turn mode. |
| `--export [<PATH>]` | **DOCUMENTED AND STABLE** | Export conversation after each turn. |
| `-c, --continue` | **DOCUMENTED AND STABLE** | Continue most recent conversation. |
| `-r, --resume [<SESSION_ID>]` | **DOCUMENTED AND STABLE** | Resume a specific session. |
| `--respect-workspace-trust [true|false]` | **DOCUMENTED AND STABLE** | Default `true` interactive, `false` print. |
| `--agent-config <FILE>` | **DOCUMENTED AND STABLE** | JSON/YAML agent config; strict parsing. |
| `-h, --help` / `-V, --version` | **DOCUMENTED AND STABLE** | Standard. |

## Subcommands

| Subcommand | Status | Purpose |
|------------|--------|---------|
| `auth` | **DOCUMENTED AND STABLE** | `login`, `logout`, `status`. |
| `mcp` | **DOCUMENTED AND STABLE** | Add/list/remove/enable/disable/login MCP servers. |
| `rules` | **DOCUMENTED AND STABLE** | Always-on context blobs. |
| `skills` | **DOCUMENTED AND STABLE** | Slash commands / context blobs. |
| `plugins` | **DOCUMENTED AND STABLE** | Install/list/update/remove plugins. |
| `cloud` | **DOCUMENTED PREVIEW** | Declarative repo setup (DRS). |
| `list` | **DOCUMENTED AND STABLE** | List sessions; formats `interactive`, `json`, `csv`. |
| `update` | **DOCUMENTED AND STABLE** | Self-update; `--force`. |
| `version` | **DOCUMENTED AND STABLE** | Print version. |
| `sandbox` | **DOCUMENTED PREVIEW** | `setup` — print platform prerequisites. |
| `setup` | **DOCUMENTED AND STABLE** | Interactive setup wizard; `--force-manual-token-flow`. |
| `uninstall` | **DOCUMENTED AND STABLE** | Remove CLI and data. |
| `acp` | **DOCUMENTED AND STABLE** | Run ACP server over stdio. |
| `shell` | **DOCUMENTED PREVIEW** | Shell integration (`init`, `run`, `setup`). |

## ACP (Agent Client Protocol)

`devin acp` implements the public Agent Client Protocol (v1) over stdio JSON-RPC.

| Method | Status | Direction | Purpose |
|--------|--------|-----------|---------|
| `initialize` | **DOCUMENTED AND STABLE** | Client → Agent | Version/capability negotiation. |
| `authenticate` | **DOCUMENTED AND STABLE** | Client → Agent | Optional auth (Devin uses `WINDSURF_API_KEY` or stored credentials). |
| `session/new` | **DOCUMENTED AND STABLE** | Client → Agent | Create a session for a cwd. |
| `session/load` | **DOCUMENTED AND STABLE** | Client → Agent | Resume session (requires `loadSession` capability). |
| `session/resume` | **DOCUMENTED AND STABLE** | Client → Agent | Resume session. |
| `session/prompt` | **DOCUMENTED AND STABLE** | Client → Agent | Send user message; agent streams `session/update` notifications. |
| `session/cancel` | **DOCUMENTED AND STABLE** | Client → Agent | Cancel in-flight turn. |
| `session/update` | **DOCUMENTED AND STABLE** | Agent → Client | Notifications: message chunks, tool calls, plans, mode changes. |
| `session/request_permission` | **DOCUMENTED AND STABLE** | Agent → Client | Ask before sensitive tool. |
| `fs/readTextFile` | **DOCUMENTED AND STABLE** | Agent → Client | Read file (optional client capability). |
| `fs/writeTextFile` | **DOCUMENTED AND STABLE** | Agent → Client | Write file (optional). |
| `terminal/*` (new, output, release, wait, kill) | **DOCUMENTED AND STABLE** | Agent → Client | Terminal proxy. |

`devin acp` specific flags: `--agent-type <summarizer|review>`.

## Hooks

Devin CLI supports project-level hooks. Public event types (from docs + strings):

- `SessionStart`
- `UserPromptSubmit`
- `PreToolUse`
- `PostToolUse`
- `PermissionRequest`
- `Stop`
- `PostCompaction`
- `SessionEnd`

Status: **DOCUMENTED PREVIEW** for hook authoring; exact stdin/stdout schemas were not empirically verified in this phase.

## Filesystem interfaces

| Path / file | Status | Purpose |
|-------------|--------|---------|
| `~/.config/devin/config.json` | **DOCUMENTED AND STABLE** | User config (`version` field observed). |
| `~/.local/share/devin/credentials.toml` | **DOCUMENTED AND STABLE** | Auth token storage (sensitive; not read). |
| `~/.local/share/devin/cli/sessions.db` | **OBSERVED BUT UNDOCUMENTED** | SQLite session database. |
| `~/.local/share/devin/cli/logs/` | **OBSERVED BUT UNDOCUMENTED** | Startup logs (`devin_YYYYMMDD-HHMMSS_<pid>.log`). |
| `~/.local/share/devin/cli/installation_id` | **OBSERVED BUT UNDOCUMENTED** | Installation UUID. |
| `~/.local/share/devin/summaries/<session_id>.md` | **DOCUMENTED AND STABLE** | ACP summarizer output. |
| `~/.cache/devin/cli/cached_version.json` | **OBSERVED BUT UNDOCUMENTED** | Update check cache. |
| `~/.cache/devin/telemetry_state.json` | **OBSERVED BUT UNDOCUMENTED** | Telemetry state (`{"is_zdr":false}` observed). |
| `~/.local/share/devin/cli/_versions/<version>/bin/devin` | **OBSERVED BUT UNDOCUMENTED** | Installed binary versions. |
| `.devin/` (project) | **DOCUMENTED AND STABLE** | Project config/rules/skills/hooks. |
| `.devinignore` | **STRONGLY INDICATED** | Ignore patterns for agent file access (string evidence). |

## Terminal interfaces

| Feature | Status | Evidence |
|---------|--------|----------|
| Alternate screen | **STRONGLY INDICATED** | `crossterm::terminal::EnterAlternateScreen` / `LeaveAlternateScreen` strings. |
| Bracketed paste | **CONFIRMED** | `crossterm::event::EnableBracketedPaste` string. |
| Kitty keyboard protocol | **STRONGLY INDICATED** | `PushKeyboardEnhancementFlag` / `PopKeyboardEnhancementFlag` strings. |
| Mouse mode | **CONFIRMED** | `crossterm::event::EnableMouseCapture` string. |
| Cursor hide/show | **CONFIRMED** | `crossterm::cursor::Hide` / `Show` strings. |
| Synchronized update | **CONFIRMED** | `crossterm::terminal::BeginSynchronizedUpdate` / `EndSynchronizedUpdate` strings. |
| Truecolor / surface CSS | **STRONGLY INDICATED** | `--surface-base`, `--surface-elevated`, `--text-primary` strings (HTML/CSS theme). |
| PTY proxy | **STRONGLY INDICATED** | `chisel/src/shell/pty_proxy.rs` source path. |

## Model / mode interfaces

| Item | Status | Notes |
|------|--------|-------|
| `--model` aliases | **DOCUMENTED AND STABLE** | Exact model IDs not fully enumerated; examples in help. |
| `agent_mode` field in sessions DB | **OBSERVED** | SQLite schema stores `agent_mode` per session. |
| `backend_type` field | **OBSERVED** | SQLite schema stores backend type per session. |
| Subagent spawning | **DOCUMENTED** | ACP / internal strings mention `run_in_background`, `parentAgentId`, `subagents`. |
| `/model`, `/usage` slash commands | **DOCUMENTED AND STABLE** | In-session commands. |

## Unknown / not verified

- Exact `config.json` schema beyond `version`.
- Exact hook stdin/stdout format and exit-code semantics.
- Complete ACP JSON-RPC schema details (types, discriminators) — public spec at agentclientprotocol.com is the source of truth.
- Whether `devin list --format json` output matches the `sessions` table columns exactly.
- Rate-limit error shape from the CLI surface.
