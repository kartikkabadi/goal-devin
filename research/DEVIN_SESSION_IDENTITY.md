# Devin CLI — Session Identity Research

## Public identity seam

The only public way to discover a newly created session ID is **`devin list --format json`**. When no sessions exist it returns `[]`; otherwise it returns an array of session objects.

### Known fields

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

The public `devin list --format json` output is **not** documented to expose all columns**, but Goal Devin only requires `id` and `working_directory`.

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

Classify this as a known race to harden later.

## Empirical test with fake `devin`

1. `devin -p ...` runs in worktree `canary/.goal-wt/goal-xxx` and creates session `devin-e7b5cbe46455b1fc`.
2. Fake list returns `[{ "id": "devin-e7b5cbe46455b1fc", "working_directory": "...canary/.goal-wt/goal-xxx", ...}]`.
3. `latest_session_id(cwd=...canary/.goal-wt/goal-xxx)` returns the ID.
4. `goal-devin resume <id>` then runs `devin -r <id> -p ...` in the same worktree.

This matches the intended behavior in the controlled, single-session test.

## Sharp edge: `devin list` scope

`devin list` help says "List sessions in the current directory". If the implementation filters by the cwd of the `list` process, then running `devin list` from the wrapper's cwd (the main repo) could fail to see a session created in a worktree cwd. In the fake test the fake returns all sessions globally, so resolution succeeded. **This is a potential real-world race/bug** and must be tested with the real binary.

## Alternative identity methods considered

| Method | Status | Notes |
|--------|--------|-------|
| Explicit CLI output | **NOT AVAILABLE** | `devin -p` does not print the session id. |
| JSON output (`--output-format`) | **NOT AVAILABLE** | `devin --help` does not list `--output-format` or `--json` for the main `devin -p` flow. |
| `devin list --format json` | **PUBLIC, DOCUMENTED** | Used by Goal Devin. |
| ATIF export | **UNKNOWN** | `devin --export` exists but was not tested. |
| ACP result | **UNKNOWN** | `devin acp` `session/new` returns `sessionId` via JSON-RPC; not used by current Goal Devin. |
| Filesystem artifacts | **UNKNOWN** | `sessions.db` contains the id but is not a public interface. |
| Environment | **UNKNOWN** | No env var is set with the new session id. |

## Recommendation

Keep `devin list --format json` as the public seam, but treat `latest_session_id()`
as a heuristic with a known concurrency race. Prefer explicit session IDs when
available. Consider augmenting list resolution with `--all` or calling from the
same cwd as the `devin -p` invocation to minimize scope mismatch. A future rewrite
should **not** parse `sessions.db` directly because it is a private implementation
detail.
