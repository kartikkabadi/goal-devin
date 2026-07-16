# Goal Devin Companion TUI Specification

## 1. Purpose

The Goal Devin companion TUI is an **optional, experimental** adjacent surface
that displays only Goal Devin-owned context that the native Devin TUI does not
surface clearly:

* supervisor health
* sidecar health
* requested root model
* generated worker profile ID (safely shortened)
* worker policy
* sanitized event count
* latest safe event category
* active lifecycle phase
* bounded warnings

It must not duplicate the Devin interface, display private task content, parse
native Devin output, or interfere with the baseline contract.

## 2. Scope

* The companion is an **optional mode** of the Rust candidate.
* The baseline contract mode remains unchanged and testable without the TUI.
* The companion does not start unless the user explicitly runs the launcher with
  `--companion` or launches the separate `goal-devin-companion` binary.
* The companion never reads, buffers, mirrors, or redraws Devin TUI output.
* The companion consumes only Goal Devin-owned state files produced by the
  supervisor.

## 3. Information architecture

```text
Goal Devin
────────────────────
Session
  state
  elapsed time
  selected model
  permission mode

Worker
  profile
  policy
  configured model

Observation
  sidecar health
  sanitized event count
  latest safe event type

Lifecycle
  setup → hook → profile → sidecar → launch → Devin → cleanup

Warnings
  bounded actionable messages
```

### 3.1 Fields

| Section | Field | Source | Notes |
|---------|-------|--------|-------|
| Header | Run state | `companion/state.json` | e.g. "Devin active" |
| Header | Elapsed time | `started_at` in state | HH:MM:SS since supervisor start |
| Session | State | `run_state` | lifecycle phase label |
| Session | Elapsed | `started_at` | updates every second |
| Session | Model | `model` | requested root model |
| Session | Permission | `permission_mode` | e.g. "accept-edits" |
| Worker | Profile | `profile_id` | shortened to 24 chars + ellipsis |
| Worker | Policy | derived | "read-only" when profile exists |
| Worker | Configured model | `model` | same as session |
| Observation | Sidecar | `sidecar_healthy` | "healthy" / "waiting" |
| Observation | Events | `event_count` | from `summary.json` |
| Observation | Latest | `last_event.tool_name` | sanitized tool name |
| Lifecycle | Phases | `lifecycle_phase` | highlight current, dim others |
| Warnings | List | `warnings` | scrollable, max 10, max 200 chars each |

### 3.2 Excluded content

The companion must never display:

* raw prompts
* user task text
* shell commands
* tool output
* source file contents
* absolute private paths
* credentials
* raw session IDs beyond a shortened profile identifier
* complete event payloads
* full transcripts
* native Devin screen contents

## 4. Visual relationship to Devin

The companion should feel like a native Devin surface, not a generic Ratatui demo.

### 4.1 Design tokens

Derived from direct observation of the Devin CLI TUI:

| Token | Truecolor | 256 fallback | Basic fallback | NO_COLOR |
|-------|-----------|--------------|----------------|----------|
| `text.primary` | `#E0E0E0` | `lightgray` | `White` | default |
| `text.secondary` | `#A0A0A0` | `gray` | `Gray`/`DarkGray` | default |
| `text.dim` | `#707070` | `darkgray` | `DarkGray`/`Gray` | default |
| `accent.primary` | `#4FC3F7` | `cyan` | `Cyan`/`Blue` | default |
| `state.success` | `#4CC088` | `green` | `Green` | default |
| `state.warning` | `#F5C54C` | `yellow` | `Yellow` | default |
| `state.error` | `#FF6B6B` | `red` | `Red` | default |
| `border.default` | `#444444` | `darkgray` | `DarkGray` | default |
| `border.active` | `#4FC3F7` | `cyan` | `Cyan` | default |
| `spinner` | `#4FC3F7` | `cyan` | `Cyan` | ASCII only |

* No background color is hardcoded; the companion inherits the terminal theme.
* If `COLORFGBG` indicates a light background, the basic fallback swaps
  `White`/`Black` accordingly.

### 4.2 Layout

The intended visual layout is an adjacent terminal pane:

```text
┌──────────────────────── native Devin TUI ───────────────────────┬──────── Goal Devin companion ────────┐
│                                                                 │                                         │
│                  genuine Devin-controlled terminal               │         Goal Devin-owned status         │
│                                                                 │                                         │
└─────────────────────────────────────────────────────────────────┴─────────────────────────────────────────┘
```

### 4.3 Responsive behavior

| Terminal width | Companion behavior |
|----------------|-------------------|
| >= 160 cols    | Full companion pane (~22–30% width) with all sections visible. |
| 120–159 cols   | Standard companion pane with normal spacing. |
| 80–119 cols    | Compact labels and reduced padding. |
| < 80 cols      | Collapse to a minimal header + status line or disable. |
| < 40 cols      | "Terminal too small" placeholder. |
| < 10 rows      | "Terminal too small" placeholder. |

Low-height terminals drop secondary sections and keep only header + active state.

### 4.4 Borders and separators

* Default: thin Unicode box drawing (`ratatui::symbols::border::PLAIN`).
* `--ascii` mode: ASCII `+`, `-`, `|` borders for non-Unicode or unreliable
  font environments.
* No rounded corners, double lines, or heavy shadows.

### 4.5 Copy tone

* Sentence case labels (`Sidecar:`, `Events:`).
* Operational, not conversational.
* Use `▸` to mark the active lifecycle phase, two spaces for inactive phases.
* Checkmark or plain text for healthy; warning text for issues.

## 5. State model

The companion consumes a JSON state file written by the supervisor at
`{runtime_dir}/companion/state.json`.

```json
{
  "schema_version": 1,
  "run_state": "DevinActive",
  "model": "glm-5.2",
  "permission_mode": "accept-edits",
  "profile_id": "goal-devin-worker-...",
  "sidecar_healthy": true,
  "event_count": 3,
  "last_event_type": "run_subagent",
  "lifecycle_phase": "Devin",
  "warnings": [],
  "started_at": "2026-07-16T16:44:20Z",
  "updated_at": "2026-07-16T16:44:25Z",
  "finished": false,
  "devin_returncode": null
}
```

All strings are sanitized on read:

* control characters replaced with spaces
* strings truncated to bounded lengths
* warnings list truncated to 10 items, 200 chars each

## 6. Input behavior

The companion is read-only during this phase. It does not inject input into
Devin.

| Key | Action |
|-----|--------|
| `q` | Close/hide companion (exit companion binary). |
| `?` | Toggle help overlay. |
| `j` / `↓` | Scroll warnings down. |
| `k` / `↑` | Scroll warnings up. |
| `g` | Jump to first warning. |
| `G` | Jump to last warning. |
| `Ctrl+c` | Exit. |
| `Esc` | Exit. |

## 7. Transport

The companion reads `companion/state.json` from the runtime directory:

* local-only
* private permissions (parent directory `0o700`, file `0o600`)
* bounded size (64 KiB)
* atomic replacement (write-then-rename)
* tolerates missing/corrupt files gracefully
* never blocks the supervisor or Devin

## 8. Fallback behavior

If the companion cannot open an adjacent pane or if the terminal is too small:

* The supervisor continues in baseline native mode.
* A concise command is printed so the user can launch the companion manually.
* Devin remains usable.
* The companion binary exits cleanly and restores the terminal.

## 9. Lifecycle isolation

* Companion failure does not stop Devin.
* Sidecar failure does not stop Devin.
* Devin exit causes the final state file to be marked `finished=true`.
* The companion exits on `q`/`Esc`/`Ctrl+c` and restores the terminal.
* The supervisor cleans up runtime files; the companion does not keep files
  open after exit.

## 10. Platform notes

* Linux: full support for `crossterm`/`ratatui` terminal control.
* macOS: expected to work with `crossterm` but TTY ownership was not validated
  in this phase.
* The companion is not a web UI, dashboard, or Devin replacement.
