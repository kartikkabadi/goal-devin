# Devin CLI — Command Behavior

## Evidence classification

- **DOCUMENTED** — from the official Devin CLI public documentation.
- **OBSERVED LIVE** — from the installed `devin` binary in this research phase.
- **INFERRED** — deduced from other evidence but not directly observed.
- **UNKNOWN** — not yet determined.

## Notes on this document

Observations are split between the **real** `devin` binary (version `3000.1.27`)
with an isolated `HOME`, and the **fake** `devin` used to exercise `goal-devin`.

## Real binary commands

### `devin --version`

- **CWD**: any
- **Exit**: `0`
- **Stdout**: `devin 3000.1.27 (0d4bf12e)`
- **Stderr**: empty
- **Repeatable**: yes

### `devin --help`

- **Exit**: `0`
- **Stdout**: full options and subcommands list (see `.research-evidence/commands/v3000.1.27-help.out`).
- **Key facts**:
  - Default permission mode is `auto`.
  - Sandbox is `[Research Preview]`.
  - `--model` examples include Claude, OpenAI Codex, GLM, Kimi.
  - `-p/--print` runs non-interactively.
  - `-r/--resume` and `-c/--continue` exist.
- **Live discrepancy**: `--help` lists `smart` as a permission mode, but the
  executable rejects it. See `DEVIN_VERSION_COMPATIBILITY.md`.

### `devin auth status` (with stored credentials)

- **Exit**: `0`
- **Observation**: After creating a valid `~/.local/share/devin/credentials.toml`
  with a `windsurf_api_key` field, `devin auth status` reports:
  - Logged in (via API key)
  - Credentials file path
  - API server
  - User name/email/user id
  - Account tier/plan/team id
  - Team settings including allowed models and sandbox option
- **Security note**: The exact user/account identifiers are not committed; only
  the fact that authentication succeeded is recorded.

### `devin list --format json`

- **Exit**: `0`
- **Stdout**: JSON array of session objects, newest first.
- **Shape** (OBSERVED LIVE):
  - `id`, `short_id`, `working_directory`, `working_directory_display`,
    `last_activity_at`, `last_activity_ago`, `title`
- **Repeatable**: yes
- **Safety**: Returns all sessions for the current directory; picking the first
  element gives the newest.

### `devin -p --model swe-1-7 --permission-mode accept-edits -- <prompt>` (authenticated)

- **Exit**: `0`
- **Stdout**: agent response text
- **Stderr**: empty or `✓ Organization: <org>`
- **Observation**: Print mode works when credentials are stored. It creates a
  session visible in `devin list`.

### `devin -r <session-id> -p --model swe-1-7 --permission-mode accept-edits -- <prompt>` (authenticated)

- **Exit**: `0`
- **Observation**: Resumes the same session id, updates `last_activity_at`,
  preserves `working_directory`, and continues conversation context. See
  `LIVE_SESSION_RESUME.md`.

### Permission-mode acceptance matrix

Live `devin -p` tests with `--model swe-1-7`:

| `--permission-mode` | Result |
|----------------------|--------|
| `auto` | Accepted, exit 0 |
| `normal` | Accepted, exit 0 |
| `accept-edits` | Accepted, exit 0 |
| `dangerous` | Accepted, exit 0 |
| `bypass` | Accepted, exit 0 |
| `autonomous` | Rejected without `--sandbox`, exit 1 |
| `smart` | Rejected, exit 2 |

See `DEVIN_VERSION_COMPATIBILITY.md` for the exact error text.

### Subcommand helps

All run with `--help` and exit `0`:

- `devin auth --help`
- `devin mcp --help`
- `devin rules --help`
- `devin skills --help`
- `devin plugins --help`
- `devin cloud --help`
- `devin list --help`
- `devin update --help`
- `devin sandbox --help`
- `devin setup --help`
- `devin shell --help`
- `devin acp --help`

Notable `acp` help details:

- `--agent-type summarizer` writes summaries to `~/.local/share/devin/summaries/<session_id>.md`.
- `--agent-type review` is a read-only + shell code-review agent.

## Fake-driven Goal Devin commands

| Command | Exit | Files created | `devin` invocations | Notes |
|---------|------|---------------|---------------------|-------|
| `goal-devin goal "P" --max-iters 1 --no-worktree` | `0` | `~/.goal-devin/state/*.json`, `~/.goal-devin/logs/<sid>.log` | iter 0: `devin -p --model ... -- GOAL: P...` | state `status=stopped`, `iters=1` |
| `goal-devin goal "P" --max-iters 1` | `0` | state, log, git worktree under `.goal-wt/` | same argv, cwd = worktree | worktree kept on `max_iters` |
| `goal-devin resume <sid> --max-iters 2` | `0` | state updated, log appended | `devin -r <sid> -p --model ... -- CONTINUE_PROMPT` | `iters` increments |
| `goal-devin status` (from worktree cwd) | `0` | none | none | prints state JSON and log path |
| `goal-devin status` (from main repo) | `0` | none | none | `none — no goal state in this directory.` |
| `goal-devin status --all` | `0` | none | none | lists all states with cwd, sid, iters, model, status, goal |
| `goal-devin logs <sid>` | `0` | none | none | prints log file contents |
| `goal-devin version` | `0` | none | none | `goal-devin 0.6.0` |

## Commands not run

- `devin cloud`
- `devin mcp`
- `devin acp` full JSON-RPC flow beyond `initialize`/`session/new`
- `devin sandbox setup` (could be run safely)

## Notes and risks

- `devin -p` requires stored credentials in `~/.local/share/devin/credentials.toml`
  (or a completed `devin auth login`); the `WINDSURF_API_KEY` environment variable
  alone is not sufficient for `devin -p` but is used by `devin acp`.
- `devin list --format json` returns `[]` immediately when no sessions exist; it is
  safe to call frequently.
- `devin --help` and `devin <subcommand> --help` are entirely local and deterministic.
- The `goal-devin` behavior contract is reproducible with the fake fixture and an isolated `HOME`.
