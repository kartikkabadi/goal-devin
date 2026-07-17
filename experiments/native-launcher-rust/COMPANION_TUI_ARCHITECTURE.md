# Goal Devin Companion TUI Architecture

## Decision summary

The Goal Devin companion TUI uses a **separate companion process in an
adjacent user-created terminal pane**. The supervisor writes a bounded, local,
read-only state file; the companion binary renders it with `ratatui` and
`crossterm`.

The selected mechanism preserves **direct terminal ownership** for the native
Devin process while giving Goal Devin an independent surface for its own state.

## Mechanisms considered

| Mechanism | Terminal ownership | Stream isolation | Input routing | Resize | macOS | Linux | Notes |
|-----------|-------------------|------------------|---------------|--------|-------|-------|-------|
| tmux split | tmux owns the pty; Devin gets a tmux pane | Good if Goal Devin only writes to its own pane | tmux handles focus | tmux commands | tmux available | tmux available | Adds a heavy runtime dependency and tmux keybinding conflicts. |
| screen split | screen owns the pty | Good | screen handles focus | screen commands | screen available | screen available | Similar to tmux but older and less common. |
| Terminal emulator pane API (Konsole D-Bus) | Native Devin gets a real Konsole pane | Good if split via D-Bus | Konsole routes input | Konsole D-Bus | Not available | Konsole only | Too vendor-specific and hard to test. |
| **Separate companion command in adjacent pane** (chosen) | Native Devin keeps the original terminal/pane | Companion reads only Goal Devin-owned state files | Companion only consumes its own keyboard events | Independent terminal resize events | Works in any terminal | Works in any terminal | Simplest, safest, and does not require a multiplexer. |

The chosen approach is the smallest architecture that honestly satisfies the
requirement that the companion "appears beside" Devin without intercepting
Devin streams.

## Components

### 1. Supervisor (`goal-devin-dev`)

* Runs the baseline contract lifecycle unchanged.
* When `--companion` is passed, writes `companion/state.json` after every major
  lifecycle phase and before/after launching Devin.
* Prints the exact command to run `goal-devin-companion` in an adjacent pane.
* Adds `companion/state.json` to the manifest `owned_paths` so the runtime
  ownership model remains consistent.

### 2. Companion binary (`goal-devin-companion`)

* Compiled only with the `companion` Cargo feature.
* Reads `--runtime-dir`, `--poll-ms`, `--no-color`, `--ascii`.
* Enters the terminal alternate screen, hides the cursor, enables raw mode.
* Polls `companion/state.json` every `--poll-ms` milliseconds.
* Renders a responsive layout with `ratatui`.
* Handles keyboard input locally (`q`, `?`, `j`/`k`, arrows, `Ctrl+c`, `Esc`).
* Restores the terminal on exit.

### 3. State transport (`companion/state.json`)

* Located at `{runtime_dir}/companion/state.json`.
* Written by the supervisor using `atomic_write` (temp file + rename).
* File permissions: parent directory `0o700`, file `0o600`.
* Bounded to 64 KiB on read.
* All rendered strings are sanitized before display.

### 4. Rendering

* Centralized in `companion::style::Theme`.
* Supports truecolor, 256-color, basic 16-color, and `NO_COLOR` fallbacks.
* `--ascii` swaps Unicode borders for ASCII `+`, `-`, `|`.
* Responsive layouts for 80x24, 100x30, 120x40, 160x50, very narrow, and very
  low-height terminals.

## Stream isolation

* The native Devin child inherits stdin/stdout/stderr directly from its pane.
* The companion runs in a **separate** pane and only reads `companion/state.json`
  and `summary.json`.
* No Goal Devin code reads, buffers, mirrors, or redraws native Devin output.
* The companion cannot inject keystrokes into Devin.

## Process ownership

```text
supervisor (goal-devin-dev)
├── sidecar (goal-devin-sidecar)
├── native Devin (devin)
└── state file: {runtime_dir}/companion/state.json

companion pane (goal-devin-companion) --read-only--> companion/state.json
```

* The supervisor does not spawn the companion; the user launches it in a separate
  pane. This avoids the supervisor needing to manage another terminal's pty or
  multiplexer state.
* If the companion is closed, Devin continues unaffected.
* If Devin exits, the supervisor writes a final `finished=true` state and the
  companion keeps displaying the final summary until the user closes it.

## Input routing

* Devin's pane receives all keyboard input intended for Devin.
* The companion pane receives all keyboard input intended for the companion.
* The companion's keys are local and never forwarded to Devin.

## Resize behavior

* Each pane is an independent terminal stream.
* The companion reacts to `crossterm::Event::Resize` and re-renders.
* Devin's pane resizes through the normal terminal mechanism.
* No shared layout manager exists; the two panes are independent.

## Cleanup and crash behavior

* The companion restores raw mode and the main screen on drop (via panic hook
  and normal exit).
* The supervisor's `Drop`/`final_cleanup` removes runtime files.
* The companion exiting does not stop the supervisor or Devin.
* The supervisor exiting does not force the companion to exit; it will simply
  stop seeing state updates.

## macOS support

The companion uses `crossterm`, which supports macOS. However, this phase was
validated only on Linux. macOS-specific behavior (signal handling, file modes,
terminal restore) is unproven.

## Dependency justification

* `ratatui` 0.27.0 — justified for rendering the companion UI. Used only when
  the `companion` feature is enabled.
* `crossterm` 0.27.0 — justified for terminal control and input events. Used only
  with the `companion` feature.
* `unicode-segmentation` 1.10.1 — pinned to keep the MSRV compatible with Rust
  1.83.0 and to support correct width calculations.

## Why this preserves the baseline contract

The `goal-devin-dev` binary without `--companion` is identical to the baseline
contract candidate. The companion feature only adds:

* new optional CLI flags (`--companion`, `--companion-poll-ms`)
* an additional file (`companion/state.json`) written only when `--companion` is
  set
* a separate binary that is not invoked by the contract tests

The shared black-box contract is run against the baseline flags and remains
unchanged.

## Known limitations

* The user must manually create the adjacent pane. Future phases could add an
  optional terminal-emulator launcher (e.g., Konsole D-Bus, `tmux split`) if
  research proves it safe.
* macOS TTY behavior has not been validated end-to-end.
* Mouse support is not implemented.
