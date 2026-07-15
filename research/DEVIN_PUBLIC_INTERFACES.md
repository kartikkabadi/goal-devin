# Devin CLI — Public Interface Inventory

## Evidence classification

- **DOCUMENTED** — from the official Devin CLI public documentation.
- **OBSERVED LIVE** — from the installed `devin` binary in this research phase.
- **INFERRED** — deduced from other evidence but not directly observed.
- **UNKNOWN** — not yet determined.

## CLI (global) flags (DOCUMENTED + OBSERVED LIVE)

| Flag | Status | Notes |
|------|--------|-------|
| `devin [OPTIONS] [-- <PROMPT>...] [COMMAND]` | **DOCUMENTED** | Main invocation pattern. |
| `--prompt-file <FILE>` | **DOCUMENTED** | Load initial prompt from file. |
| `--config <PATH>` | **DOCUMENTED** | Override `~/.config/devin/config.json`. |
| `--permission-mode <MODE>` | **OBSERVED LIVE / DOCUMENTED** | Installed v3000.1.27 accepts `normal` (alias `auto`), `accept-edits`, `dangerous` (aliases `yolo`, `bypass`), `autonomous` (requires `--sandbox`). Official docs list `normal`, `accept-edits`, `bypass`, `autonomous`. See `DEVIN_VERSION_COMPATIBILITY.md`. |
| `--sandbox` | **DOCUMENTED** | OS-level sandbox. `autonomous` permission mode is selected when sandbox is active. |
| `--model <MODEL>` | **DOCUMENTED** | e.g. `opus`, `sonnet`, `swe`, `codex`, `glm-5.2`, `kimi-k2.7`. Short names resolve to latest family version. |
| `-p, --print [<PROMPT>]` | **DOCUMENTED** | Non-interactive single-turn mode. |
| `--export [<PATH>]` | **DOCUMENTED** | Export conversation to ATIF format after each turn. |
| `-c, --continue` | **DOCUMENTED** | Resume the most recent session in the current directory. |
| `-r, --resume [<SESSION_ID>]` | **DOCUMENTED** | Resume a specific session. |
| `--respect-workspace-trust [true|false]` | **DOCUMENTED** | Whether to respect workspace trust settings. |
| `--agent-config <FILE>` | **DOCUMENTED** | JSON/YAML agent config. |
| `-h, --help` / `-V, --version` | **DOCUMENTED** | Standard. |

## Permission modes (DOCUMENTED + OBSERVED LIVE)

Official documentation (`docs.devin.ai/cli/reference/permissions`) defines:

| Mode | Read-only | Fetch | Bash | File edits |
|------|-----------|-------|------|------------|
| `normal` | Auto | Prompt | Prompt | Prompt |
| `accept-edits` | Auto | Prompt | Prompt | Auto (in workspace) |
| `bypass` | Auto | Auto | Auto | Auto |
| `autonomous` (requires `--sandbox`) | Auto | Auto | Auto | Prompt |

Slash commands: `/mode [normal|accept-edits|plan|bypass]`, with `/bypass` aliases `/yolo` and `/dangerous`.

**OBSERVED LIVE** in installed `devin --help` v3000.1.27: `auto`, `accept-edits`, `smart`, `dangerous`. Live tests showed the executable accepts `normal`, `auto`, `accept-edits`, `dangerous`, `yolo`, `bypass`; rejects `smart`; requires `--sandbox` with `autonomous`. See `DEVIN_VERSION_COMPATIBILITY.md`.

## Subcommands (DOCUMENTED)

| Subcommand | Status | Purpose |
|------------|--------|---------|
| `auth` | **DOCUMENTED** | `login`, `logout`, `status`. Login supports `--force-manual-token-flow` for remote/SSH sessions. |
| `mcp` | **DOCUMENTED** | Add/list/remove/enable/disable/login MCP servers. |
| `rules` | **DOCUMENTED** | Manage always-on context blobs. |
| `skills` | **DOCUMENTED** | Manage slash commands / context blobs. |
| `plugins` | **DOCUMENTED** | Install/list/update/remove plugins. |
| `cloud` | **DOCUMENTED PREVIEW** | Declarative repo setup (DRS). |
| `list` | **DOCUMENTED** | List sessions; formats `interactive`, `json`, `csv`. Alias `ls`. |
| `update` | **DOCUMENTED** | Self-update; `--force`. |
| `version` | **DOCUMENTED** | Print version. |
| `sandbox` | **DOCUMENTED PREVIEW** | `setup` — print platform prerequisites. |
| `setup` | **DOCUMENTED** | Interactive setup wizard; `--force-manual-token-flow`. |
| `uninstall` | **DOCUMENTED** | Remove CLI and data. `--clean` removes all data. |
| `acp` | **DOCUMENTED** | Run ACP server over stdio. |
| `shell` | **DOCUMENTED PREVIEW** | Shell integration (`init`, `run`, `setup`). |

## `devin list` output shape (OBSERVED LIVE)

`devin list --format json` returns a JSON array sorted by recency (newest first). Each object has:

- `id` (string) — session id, e.g. `level-bathroom`
- `short_id` (string) — same value observed
- `working_directory` (string) — absolute path of the session cwd
- `working_directory_display` (string) — e.g. `./`
- `last_activity_at` (integer) — Unix timestamp (seconds)
- `last_activity_ago` (string) — human-readable, e.g. `just now`, `1m ago`
- `title` (string) — first user prompt or auto-generated title

When multiple sessions exist in the same directory, `devin list --format json` returns all of them, newest first. This is safe for Goal Devin's `latest_session_id()` logic, which picks the first element.

## ACP (Agent Client Protocol)

`devin acp` implements ACP v1 over stdio JSON-RPC.

| Method | Status | Direction | Purpose |
|--------|--------|-----------|---------|
| `initialize` | **DOCUMENTED + OBSERVED LIVE** | Client → Agent | Version/capability negotiation. |
| `authenticate` | **DOCUMENTED + OBSERVED LIVE** | Client → Agent | Optional auth. Devin uses `WINDSURF_API_KEY` or stored credentials. |
| `session/new` | **DOCUMENTED + OBSERVED LIVE** | Client → Agent | Create a session for a cwd. |
| `session/load` | **DOCUMENTED** | Client → Agent | Resume session (requires `loadSession` capability). |
| `session/resume` | **DOCUMENTED** | Client → Agent | Resume session. |
| `session/prompt` | **DOCUMENTED** | Client → Agent | Send user message; agent streams `session/update`. |
| `session/cancel` | **DOCUMENTED** | Client → Agent | Cancel in-flight turn. |
| `session/update` | **DOCUMENTED + OBSERVED LIVE** | Agent → Client | Notifications: message chunks, tool calls, plans, mode changes, config options. |
| `session/request_permission` | **DOCUMENTED** | Agent → Client | Ask before sensitive tool. |
| `fs/readTextFile` | **DOCUMENTED** | Agent → Client | Read file (optional client capability). |
| `fs/writeTextFile` | **DOCUMENTED** | Agent → Client | Write file (optional). |
| `terminal/*` | **DOCUMENTED** | Agent → Client | Terminal proxy (new, output, release, wait, kill). |

`devin acp` flags: `--agent-type <summarizer|review>`.

## Configuration precedence (DOCUMENTED)

Highest to lowest:

1. Organization / Team Settings
2. Session (interactive approvals)
3. Project Local (`.devin/config.local.json`)
4. Project (`.devin/config.json`)
5. User (`~/.config/devin/config.json`)

## Config levels and available settings (DOCUMENTED)

| Setting | User config | Project config |
|---------|-------------|----------------|
| `permissions` | ✓ | ✓ |
| `mcpServers` | ✓ | ✓ |
| `read_config_from` | ✓ | ✓ |
| `hooks` | ✓ | ✓ |
| `agent.model` | ✓ | ✗ |
| `theme_mode` | ✓ | ✗ |
| `unicode_mode` | ✓ | ✗ |
| `show_path` | ✓ | ✗ |
| `show_hints` | ✓ | ✗ |
| `include_gitignored_files` | ✓ | ✗ |
| `sandbox` | ✓ | ✗ |

## Hooks (DOCUMENTED + OBSERVED LIVE)

Public event types:

- `PreToolUse`
- `PostToolUse`
- `PermissionRequest`
- `UserPromptSubmit`
- `Stop`
- `PostCompaction`
- `SessionStart`
- `SessionEnd`

Hook matcher is a regex against `tool_name`. Tool names observed: `read`, `edit`, `grep`, `glob`, `exec`, `run_subagent`, plus `mcp__<server>__<tool>`.

Live `PreToolUse` payload shape (observed):

```json
{
  "hook_event_name": "PreToolUse",
  "tool_name": "glob",
  "tool_input": { "pattern": "*.py", "path": "/path/to/cwd" },
  "tool_use_id": "find_file_by_name_0"
}
```

## Filesystem interfaces

| Path / file | Status | Purpose |
|-------------|--------|---------|
| `~/.config/devin/config.json` | **DOCUMENTED + OBSERVED** | User config. |
| `~/.local/share/devin/credentials.toml` | **DOCUMENTED + OBSERVED** | Auth token storage (sensitive; not read). |
| `~/.local/share/devin/cli/sessions.db` | **OBSERVED** | SQLite session database. |
| `~/.local/share/devin/cli/logs/` | **OBSERVED** | Startup logs. |
| `~/.local/share/devin/cli/installation_id` | **OBSERVED** | Installation UUID. |
| `~/.local/share/devin/summaries/<session_id>.md` | **DOCUMENTED** | ACP summarizer output. |
| `~/.cache/devin/cli/cached_version.json` | **OBSERVED** | Update check cache. |
| `~/.cache/devin/telemetry_state.json` | **OBSERVED** | Telemetry state. |
| `~/.local/share/devin/cli/_versions/<version>/bin/devin` | **OBSERVED** | Installed binary versions. |
| `.devin/` (project) | **DOCUMENTED** | Project config/rules/skills/hooks. |
| `.devin/config.local.json` | **DOCUMENTED** | Personal project overrides (gitignored). |
| `.devin/agents/<profile>/AGENT.md` | **DOCUMENTED + OBSERVED** | Custom subagent profile. |
| `AGENTS.md` | **DOCUMENTED** | Always-on context/rules at project root. |
| `~/.config/devin/AGENTS.md` | **DOCUMENTED** | Global always-on context/rules. |

## Terminal interfaces

| Feature | Status | Evidence |
|---------|--------|----------|
| Alternate screen | **CONFIRMED** | TUI renders a full-screen UI and restores the terminal on clean exit. |
| Bracketed paste | **OBSERVED LIVE** | ANSI sequence `ESC[?2004h` in TTY startup. |
| Kitty keyboard protocol | **OBSERVED LIVE** | `ESC[?u` in TTY startup. |
| Cursor position query | **OBSERVED LIVE** | `ESC[6n` in TTY startup. |
| Synchronized update | **OBSERVED LIVE** | `ESC[?2026h` / `ESC[?2026l` in TTY startup. |
| Cursor hide/show | **OBSERVED LIVE** | `ESC[?25l` in TTY startup; `crossterm` strings. |
| Mouse mode | **OBSERVED LIVE** | `ESC[?1004h` in TTY startup. |
| PTY proxy | **INFERRED** | `chisel/src/shell/pty_proxy.rs` source path. |
| OSC window title | **OBSERVED LIVE** | `ESC]0;devin: <cwd>BEL` and `ESC]30;devin: <cwd>BEL`. |

## Model / mode interfaces

| Item | Status | Notes |
|------|--------|-------|
| `--model` aliases | **DOCUMENTED** | Short names resolve to latest family. |
| `/model` slash command | **DOCUMENTED** | In-session model switch. |
| `agent.model` config | **DOCUMENTED** | User-config default. |
| `agent_mode` field in sessions DB | **OBSERVED** | SQLite schema. |
| `backend_type` field | **OBSERVED** | SQLite schema. |
| Subagent spawning | **DOCUMENTED + OBSERVED LIVE** | `run_subagent`/`read_subagent` tool names; `subagent_explore`, `subagent_general`, custom profiles. |
| Slash commands | **DOCUMENTED** | `/mode`, `/model`, `/ask`, `/bypass` (`/yolo`, `/dangerous`), `/clear`, `/continue`, `/fork`, `/steps`, `/revert`, `/resume`, `/ls`, `/rename-session`, `/rm-session`, `/export`, `/exit`. |

## ATIF export (OBSERVED LIVE)

`devin -p ... --export <path>` writes an ATIF JSON file. Observed metadata:

- `schema_version`: `ATIF-v1.7`
- `session_id`: `<session-id>`
- `agent.name`: `devin`
- `agent.version`: `3000.1.27`
- `agent.model_name`: `SWE-1.7`
- `tool_definitions`: array of tool definitions with `name`, `description`, `parameters`

The full ATIF file is large and contains proprietary tool definitions; only the metadata summary is committed in research docs.

## Unknown / not verified

- Exact `config.json` schema beyond documented fields.
- Whether `devin list --format json` output matches the `sessions` table columns exactly.
- Rate-limit error shape from the CLI surface.
- Whether installed v3000.1.27 accepts `plan` as a `--permission-mode` value (slash command only).
