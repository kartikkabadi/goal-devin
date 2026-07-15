# Devin CLI — Version Compatibility and Permission-Mode Mapping

## Evidence classification

- **DOCUMENTED** — from the official Devin CLI public documentation.
- **OBSERVED LIVE** — from the installed `devin` binary in this research phase.
- **INFERRED** — deduced from other evidence but not directly observed.
- **UNKNOWN** — not yet determined.

## Installed version

| Attribute | Value |
|-----------|-------|
| Binary path | `/home/ubuntu/.local/bin/devin` |
| Resolved path | `~/.local/share/devin/cli/_versions/3000.1.27/bin/devin` |
| Version string | `devin 3000.1.27 (0d4bf12e)` |
| Architecture | statically linked ELF64 PIE |
| SHA-256 | `6c0a5345055781da752b982c77b3179b5ece1b1bf1a38433156dad9564e2f079` |

## Permission-mode discrepancy

The installed `devin` v3000.1.27 `--help` text lists the following permission modes:

```text
Modes: "auto" auto-approves read-only tools, "accept-edits" also auto-approves workspace edits, "smart" additionally auto-runs actions a fast model judges safe, "dangerous" auto-approves all tools.
[default: auto]
```

The official public documentation (`docs.devin.ai/cli/reference/permissions`) lists:

| Mode | Read-only | Fetch | Bash | File edits |
|------|-----------|-------|------|------------|
| `normal` | Auto | Prompt | Prompt | Prompt |
| `accept-edits` | Auto | Prompt | Prompt | Auto (in workspace) |
| `bypass` | Auto | Auto | Auto | Auto |
| `autonomous` (requires `--sandbox`) | Auto | Auto | Auto | Prompt |

## Live executable acceptance matrix (OBSERVED LIVE)

| Value passed to `--permission-mode` | Result |
|--------------------------------------|--------|
| `auto` | Accepted; exit 0 |
| `normal` | Accepted; exit 0 |
| `accept-edits` | Accepted; exit 0 |
| `dangerous` | Accepted; exit 0 |
| `bypass` | Accepted; exit 0 |
| `autonomous` | Rejected with `--permission-mode autonomous requires --sandbox`; exit 1 |
| `smart` | Rejected with error listing valid options; exit 2 |

## Exact error message from installed binary

```text
error: invalid value 'smart' for '--permission-mode <PERMISSION_MODE>': Invalid permission mode: smart. Valid options: normal (auto), accept-edits, dangerous (yolo, bypass), autonomous (requires --sandbox)
```

This message reveals the **canonical accepted values** for this binary:

- `normal` (alias `auto`)
- `accept-edits`
- `dangerous` (aliases `yolo`, `bypass`)
- `autonomous` (requires `--sandbox`)

## Mapping to public docs

| Executable value | Public-doc equivalent | Meaning |
|------------------|----------------------|---------|
| `normal` / `auto` | `normal` | Prompt for edits, fetch, bash |
| `accept-edits` | `accept-edits` | Auto-approve workspace edits, prompt for fetch/bash |
| `dangerous` / `yolo` / `bypass` | `bypass` | Auto-approve all tools |
| `autonomous` | `autonomous` | Auto-approve read/fetch/bash; prompt for file edits; requires `--sandbox` |

## Feature detection recommendation for Goal Devin

- **Do not hardcode a global permission enum.** The installed binary already accepts more aliases than the `--help` text lists, and future versions may add or rename modes.
- Pass the user-supplied string directly to `devin --permission-mode` and let the executable validate it.
- If validation is required before spawning, run `devin --help` or attempt a dry `devin -p` with `--permission-mode <value>` and a minimal prompt; inspect the exit code and stderr.
- Prefer the **public-doc canonical names** (`normal`, `accept-edits`, `bypass`, `autonomous`) in user-facing Goal Devin documentation, while documenting the executable aliases that are known to work.
- For `--sandbox` + `autonomous`, construct the full argv `["devin", "-p", "--sandbox", "--permission-mode", "autonomous", ...]`; never use `autonomous` without `--sandbox`.

## Version skew / aliasing / staged rollout

| Question | Status | Evidence |
|----------|--------|----------|
| Is the installed v3000.1.27 help text stale? | **INFERRED** | `--help` mentions `smart`, which the executable rejects. |
| Are aliases `auto`, `yolo`, `bypass` intentionally supported? | **OBSERVED LIVE** | Error message explicitly lists them. |
| Could older/newer binaries have different accepted values? | **UNKNOWN** | Only v3000.1.27 was tested. |
| Is there a hidden `--permission-mode plan` or `--mode`? | **UNKNOWN** | Slash command `/mode` accepts `plan` per docs, but `--permission-mode plan` was not tested. |

## Implications for Goal Devin

- Treat `permission_mode` as an opaque, user-provided string that is passed through to `devin`.
- If a user supplies `smart`, Goal Devin should not silently rewrite it; let `devin` fail and surface the error.
- To support canonical naming, Goal Devin can map a small allowlist (`normal`, `accept-edits`, `bypass`, `autonomous`) to the executable-accepted forms only if the executable rejects the canonical form. The safer default is pass-through.
