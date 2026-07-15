# Devin CLI — Session Identity Research

## Preferred identity hierarchy

Goal Devin should determine the session ID of a newly created session in the
following order:

1. **Print mode with ATIF export** — pass a Goal Devin-owned ATIF path to
   `devin -p --export <path>` and parse `session_id` from the exported file.
2. **ACP `session/new`** — use the `sessionId` field returned by the
   `devin acp` JSON-RPC `session/new` method.
3. **Native TUI `--export`** — test whether the documented global `--export`
   flag produces usable ATIF during an interactive TUI session. This is
   **unproven** and must be verified in R1A/R1B.
4. **`devin list --format json` fallback** — select the newest matching session
   by `working_directory`. This is a heuristic with a known concurrency race.

Do not parse `sessions.db`; it is a private implementation detail.

## Known fields

From the `sessions` SQLite table (observed via `sqlite3` stdlib):

| Field | Type | Notes |
|-------|------|-------|
| `id` | TEXT PRIMARY KEY | Session UUID. |
| `working_directory` | TEXT | Resolved cwd at creation. |
| `backend_type` | TEXT | e.g. cloud vs local? |
| `model` | TEXT | Effective model. |
| `agent_mode` | TEXT | Mode selected. |
| `created_at` | INTEGER | Unix timestamp (ms or s). |
| `last_activity_at` | INTEGER | Updated on activity. |
| `title` | TEXT | Optional session title. |
| `main_chain_id` | INTEGER | Tree pointer. |
| `shell_last_seen_index` | INTEGER | Terminal state. |
| `cogs_json` | TEXT | Serialized agent "cogs" / config. |
| `workspace_dirs` | TEXT | Additional workspace dirs. |
| `hidden` | INTEGER | Visibility flag. |
| `metadata` | TEXT | Opaque metadata blob. |

The public `devin list --format json` output is **not** documented to expose all
columns, but Goal Devin only requires `id` and `working_directory` when using
that seam.

## ATIF export identity (OBSERVED LIVE)

A separate `devin -p --export /path/to/file.atif ...` run produced an ATIF file
with:

- `schema_version`: `ATIF-v1.7`
- `session_id`: the new session ID
- `agent.name`: `devin`
- `agent.version`: the installed CLI version
- `agent.model_name`: the effective root model (e.g. `SWE-1.7`)

The ATIF export path can be Goal Devin-owned (under `~/.goal-devin/runtime/`)
and deleted after the session ID is extracted. No credentials are required in
the export file for identity resolution.

## ACP `session/new` identity (OBSERVED LIVE)

The `devin acp` JSON-RPC handshake returns a `sessionId` in the `session/new`
response. This is a stable, explicit identifier. `devin acp` consumes tokens and
was not exercised for a full turn, but the `session/new` response shape was
observed.

## Goal Devin resolution algorithm (current Python)

```python
def latest_session_id(cwd, retries=3, delay=1.0):
    cwd_resolved = str(Path(cwd).resolve())
    for _ in range(retries):
        r = run_devin(["list", "--format", "json"])
        if r.returncode != 0:
            time.sleep(delay); continue
        sessions = json.loads(r.stdout)
        for s in sessions:
            wd = s.get("working_directory", "")
            if not wd: continue
            if Path(wd).resolve() == Path(cwd_resolved):
                return s.get("id")
        time.sleep(delay)
    return None
```

### Properties

- Selects the **first matching session in `devin list --format json` output**.
- In the tested environment the first matching session is also the newest one.
- Requires `working_directory` to canonicalize to the loop `cwd`.
- **No fallback** to `sessions[0]`.
- Retries up to 3 times to handle list-lag after `devin -p`.

### Known race

The evidence supports:

- `devin list --format json` returns newest-first in the tested environment.
- A newly created isolated session appeared as the newest entry.
- Explicit resume by known session ID is stable.

The evidence does **not** yet prove:

- Safety when two sessions start concurrently in one cwd.
- Safety when list visibility is delayed.
- Safety when timestamps collide.
- Safety when another process creates a newer session before Goal Devin lists.
- Safety across all Devin versions.

Classify this as a known race to harden later. Prefer ATIF or ACP identity when
available.

## Empirical test with fake `devin`

1. `devin -p ...` runs in worktree `canary/.goal-wt/goal-xxx` and creates session `devin-e7b5cbe46455b1fc`.
2. Fake list returns `[{ "id": "devin-e7b5cbe46455b1fc", "working_directory": "...canary/.goal-wt/goal-xxx", ...}]`.
3. `latest_session_id(cwd=...canary/.goal-wt/goal-xxx)` returns the ID.
4. `goal-devin resume <id>` then runs `devin -r <id> -p ...` in the same worktree.

This matches the intended behavior in the controlled, single-session test.

## Sharp edge: `devin list` scope

`devin list` help says "List sessions in the current directory". If the
implementation filters by the cwd of the `list` process, then running `devin
list` from the wrapper's cwd (the main repo) could fail to see a session created
in a worktree cwd. In the fake test the fake returns all sessions globally, so
resolution succeeded. **This is a potential real-world race/bug** and must be
tested with the real binary.

## Alternative identity methods considered

| Method | Status | Notes |
|--------|--------|-------|
| ATIF export (`devin -p --export`) | **OBSERVED LIVE** | Contains `session_id` and effective model. Preferred for print mode. |
| ACP `session/new` | **OBSERVED LIVE** | Returns `sessionId` explicitly. Preferred for ACP mode. |
| Native TUI `--export` | **UNKNOWN** | Documented flag; must be tested in R1A/R1B before use. |
| Explicit CLI output | **NOT AVAILABLE** | `devin -p` does not print the session id. |
| JSON output (`--output-format`) | **NOT AVAILABLE** | `devin --help` does not list `--output-format` or `--json` for the main `devin -p` flow. |
| `devin list --format json` | **PUBLIC, DOCUMENTED** | Fallback heuristic with known race. |
| Filesystem artifacts | **NOT AVAILABLE** | `sessions.db` contains the id but is not a public interface. |
| Environment | **NOT AVAILABLE** | No env var is set with the new session id. |

## Recommendation

- Prefer explicit identity sources: ATIF export for print mode and ACP
  `session/new` for ACP mode.
- Treat `devin list --format json` as a fallback heuristic with a known
  concurrency race.
- Test native TUI `--export` behavior in R1A/R1B before relying on it.
- Do not parse `sessions.db` directly because it is a private implementation
  detail.
