# Devin CLI — Filesystem Contract

All observations used an isolated `HOME` (`.research-evidence/home-real`) and a `WINDSURF_API_KEY` for commands that do not require stored credentials. No real user files outside the isolated tree were touched.

## Isolation method

```bash
export HOME=/path/to/empty/home
export WINDSURF_API_KEY="$WINDSURF_API_KEY"  # name only, value redacted
devin <command>
```

## Directories and files created

| Path | Created by | Contains |
|------|------------|----------|
| `~/.config/devin/config.json` | first run | `{"version": 1}` |
| `~/.local/share/devin/cli/` | install | Binary runtime state. |
| `~/.local/share/devin/cli/sessions.db` | first run | SQLite session database. |
| `~/.local/share/devin/cli/logs/devin_YYYYMMDD-HHMMSS_<pid>.log` | every run | Startup log line. |
| `~/.local/share/devin/cli/installation_id` | install | UUID string. |
| `~/.local/share/devin/credentials.toml` | `auth login` (not created here) | Auth token (sensitive). |
| `~/.cache/devin/cli/cached_version.json` | update check | `{"latest":"3000.1.27"}` |
| `~/.cache/devin/telemetry_state.json` | first run | `{"is_zdr":false}` |
| `~/.local/share/devin/cli/_versions/<version>/bin/devin` | install | Versioned binary. |

## `sessions.db` schema (observed via `sqlite3` Python stdlib)

```sql
CREATE TABLE app_state (
    key TEXT PRIMARY KEY NOT NULL,
    value TEXT NOT NULL
);

CREATE TABLE sessions (
  id TEXT PRIMARY KEY,
  working_directory TEXT NOT NULL,
  backend_type TEXT NOT NULL,
  model TEXT NOT NULL,
  agent_mode TEXT NOT NULL,
  created_at INTEGER NOT NULL,
  last_activity_at INTEGER NOT NULL,
  title TEXT,
  main_chain_id INTEGER,
  shell_last_seen_index INTEGER DEFAULT 0,
  cogs_json TEXT,
  workspace_dirs TEXT,
  hidden INTEGER NOT NULL DEFAULT 0,
  metadata TEXT
);

CREATE TABLE message_nodes (
  row_id INTEGER PRIMARY KEY AUTOINCREMENT,
  session_id TEXT NOT NULL,
  node_id INTEGER NOT NULL,
  parent_node_id INTEGER,
  chat_message TEXT NOT NULL,
  created_at INTEGER NOT NULL,
  metadata TEXT,
  FOREIGN KEY (session_id) REFERENCES sessions(id),
  UNIQUE(session_id, node_id)
);

CREATE TABLE rendered_commits (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  session_id TEXT NOT NULL,
  sequence_number INTEGER NOT NULL,
  rendered_html TEXT NOT NULL,
  created_at INTEGER NOT NULL,
  FOREIGN KEY (session_id) REFERENCES sessions(id),
  UNIQUE(session_number, sequence_number)
);

CREATE TABLE prompt_history (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  content TEXT NOT NULL,
  timestamp INTEGER NOT NULL,
  session_id TEXT NOT NULL,
  is_shell INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE tool_call_state (
  session_id TEXT NOT NULL,
  tool_call_id TEXT NOT NULL,
  tool_call_json TEXT,
  tool_call_update_json TEXT,
  PRIMARY KEY (session_id, tool_call_id),
  FOREIGN KEY (session_id) REFERENCES sessions(id)
);
```

A `refinery_schema_history` table confirms migration-based schema management.

## Inferred filesystem contract

1. **XDG base dirs**. Uses `~/.config/devin/`, `~/.local/share/devin/cli/`, `~/.cache/devin/`. Falls back to `~/.local/share/` when `XDG_*` unset (observed default behavior).
2. **SQLite session store**. Local session identity, working directory, model, backend type, agent mode, and message tree are persisted locally; the backend conversation state is likely mirrored in the cloud.
3. **Versioned binary layout**. The updater keeps multiple versions under `cli/_versions/` and uses a `current` symlink. This allows rollback and in-place updates.
4. **No per-project state in real home**. Without `devin -p` or session creation, only global config/cache/DB are created.
5. **Sensitive credential file**. `credentials.toml` is the only file known to contain secrets; its value was not read.

## Goal Devin implications

- Goal Devin must not assume a fixed `devin` path; `which devin` resolves through the `current` symlink.
- Session identity must prefer `devin -p --export` ATIF and ACP `session/new`, test native TUI `--export` support, and keep `devin list --format json` only as a compatibility fallback with a known concurrency race. Goal Devin must never read, parse, or depend on Devin's private `sessions.db`.
- `devin list --format json` output schema is not guaranteed to match the DB columns exactly; only `id` and `working_directory` are known to be used by Goal Devin.
- A future Rust Goal Devin must avoid writing into `~/.config/devin/` or `~/.local/share/devin/` unless intentionally wrapping `devin`; its own state should live under `~/.goal-devin/` or XDG equivalents.
