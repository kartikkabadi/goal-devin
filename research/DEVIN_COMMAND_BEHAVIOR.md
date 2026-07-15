# Devin CLI — Command Behavior

Observations are split between the **real** `devin` binary (version 3000.1.27) with an isolated `HOME`, and the **fake** `devin` used to exercise `goal-devin`. Commands that would consume model tokens or require interactive login are marked as not run.

## Real binary commands

### `devin --version`

- **CWD**: any
- **Exit**: `0`
- **Stdout**: `devin 3000.1.27 (0d4bf12e)`
- **Stderr**: empty
- **Repeatable**: yes

### `devin --help`

- **Exit**: `0`
- **Stdout**: full options and subcommands list (see `.research-evidence/commands/real-help.out`).
- **Key facts**:
  - Default permission mode is `auto`.
  - Sandbox is `[Research Preview]`.
  - `--model` examples include Claude, OpenAI Codex, GLM, Kimi.
  - `-p/--print` runs non-interactively.
  - `-r/--resume` and `-c/--continue` exist.

### `devin auth status` (with `WINDSURF_API_KEY` set but no stored login)

- **Exit**: `0`
- **Stdout**:
  ```text
  Not logged in.
    Credentials path: <home>/.local/share/devin/credentials.toml
  Run `devin auth login` to authenticate.
  ```
- **Observation**: `WINDSURF_API_KEY` is **not** treated as stored credentials by `auth status`; it is consumed by `devin acp` and possibly by `devin -p` only after an auth flow.

### `devin list --format json` (no sessions)

- **Exit**: `0`
- **Stdout**: `[]`
- **Stderr**: empty
- **Observation**: Returns a JSON array even when no sessions exist.

### `devin -p --model glm-5.2 --permission-mode dangerous -- <prompt>` (without stored login)

- **Exit**: `1` (timeout `124` if timeout fires, but here `1`)
- **Stdout**: `[1mWelcome to Devin CLI![0m` followed by `Error: Login canceled`
- **Observation**: `devin -p` does **not** authenticate purely from `WINDSURF_API_KEY`; it requires a completed `devin auth login` flow (browser or manual PKCE code).

### `devin auth login --force-manual-token-flow` (token piped to stdin)

- **Exit**: `1`
- **Stdout**: OAuth URL to open in browser, then `Error: Failed to read code - user canceled`
- **Observation**: The manual flow expects a PKCE authorization code from the browser, not the `WINDSURF_API_KEY` token. A real login session could not be completed in this headless environment.

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

- Real `devin -p` with an authenticated session (blocked by login requirement).
- `devin -r` with a real session.
- `devin export`.
- `devin cloud`.
- `devin mcp`.
- `devin acp` full JSON-RPC flow.
- `devin sandbox setup` (could be run safely; see note below).

## Notes and risks

- `devin -p` **requires stored credentials** even if `WINDSURF_API_KEY` is present, unless a supported non-interactive auth seam is found. This is a critical integration constraint for any headless wrapper like Goal Devin.
- `devin list --format json` returns `[]` immediately without a network round-trip when no sessions exist; it is safe to call frequently.
- `devin --help` and `devin <subcommand> --help` are entirely local and deterministic.
- The `goal-devin` behavior contract is reproducible with the fake fixture and an isolated `HOME`.
