# Live Evidence — Native Devin TUI

## Evidence classification

- **DOCUMENTED** — from the official Devin CLI public documentation.
- **OBSERVED LIVE** — from a live `devin` session in this research phase.
- **INFERRED** — deduced from other evidence but not directly observed.
- **UNKNOWN** — not yet determined.

## Purpose

Launch the genuine native `devin` TUI inside a PTY, observe startup, terminal
ownership, alternate screen, input handling, and clean exit, and record the
raw ANSI evidence for offline inspection.

## Environment

- Devin CLI: `3000.1.27`, authenticated
- PTY driver: `research/fixtures/tui-pexpect.py` (uses `pexpect`)
- CWD: `/home/ubuntu/repos/goal-devin/.research-evidence/canary3`
- TERM: `xterm-256color`
- HOME: `/home/ubuntu/repos/goal-devin/.research-evidence/home-hooks`

## Method

`research/fixtures/tui-pexpect.py` spawns `devin` in a PTY, waits for the
startup screen, sends `hello` terminated by `\r` (Enter), waits, then sends
`/exit` terminated by `\r`, and finally sends `Ctrl+C` and `Esc` as fallbacks.
All bytes (including ANSI escape sequences) are written raw to
`.research-evidence/tui-pexpect2.out`.

## Key observations (OBSERVED LIVE)

### TUI startup

The TUI immediately enters the alternate screen and draws:

- A Braille-art "Devin CLI" logo.
- Version: `v3000.1.27`.
- Account/plan status line: `<plan> · <usage remaining> (resets in <duration>)`.
- Input prompt: `❭ Ask Devin to build features, fix bugs, or work on your code`.
- Hint line: `Press Ctrl+O to view the full thinking trace`.
- Model indicator: `SWE-1.7`.
- Hint: `Use /clear to start a fresh conversation`.

### Terminal ownership / alternate screen

- The process takes over the terminal: cursor is hidden (`ESC[?25l`),
  bracketed paste enabled (`ESC[?2004h`), mouse mode enabled (`ESC[?1004h`),
  Kitty keyboard protocol enabled (`ESC[?u`), and synchronized updates used
  (`ESC[?2026h`/`ESC[?2026l`).
- OSC title sequences set the window title to `devin: <cwd>` and `devin: hello`
  after the prompt is submitted.

### Input handling

- Typing `hello` appears in a colored input bar at the bottom of the screen
  (`❭ hello`), rendered with a truecolor background (`48;5;234`).
- Submitting with `\r` (Enter) started a turn; the TUI showed:
  `Thinking · 0s (esc to interrupt)` with a spinner.
- The window title changed to `devin: hello` after submission.

### Slash command `/exit`

- Typing `/exit` and submitting with `\r` caused the session to exit cleanly.
- The terminal was restored: alternate screen left, cursor shown, bracketed
  paste/mouse/kitty protocols disabled.
- Final text (after the TUI closed): `Resume this session with devin -r <session-id>, or run devin -r to view recent sessions`.
- Return code observed: `0`.

### Session id from clean exit

The final message revealed the session id as `accessible-waiter`.

### Key sequences tested

| Sequence | Result |
|----------|--------|
| `hello\r` | Typed into input bar, submitted, entered `Thinking` state |
| `/exit\r` | Exited the TUI cleanly (return code 0) |
| `Ctrl+C` (sent after `/exit`) | No effect because process had already exited |
| `Esc` | No effect after exit; before exit it interrupts a thinking turn |

## Raw ANSI evidence

The full raw PTY transcript is in `.research-evidence/tui-pexpect2.out` and is
gitignored. It contains:

- Cursor-hide/show sequences.
- Braille logo art.
- Truecolor ANSI (`38;5;244`, `48;5;234`).
- Synchronized update markers.
- OSC 0/30/133 shell-integration sequences.
- Input-bar redraws and cursor movement.

A sanitized conceptual rendering of the main screen:

```text
[Braille-art logo]  Devin CLI
                    v3000.1.27 · <plan> · <usage> remaining

────────────────────────────────────────────────────────────────────────────────
❭ Ask Devin to build features, fix bugs, or work on your code
────────────────────────────────────────────────────────────────────────────────
SWE-1.7                              Press Ctrl+O to view the full thinking trace
```

## Not tested / gaps

| Item | Status | Notes |
|------|--------|-------|
| Shift+Enter | **UNKNOWN** | Could not reliably generate CSI-u `Shift+Enter` sequence in the PTY driver; not required for basic integration. |
| Native model picker | **NOT TESTED** | TUI opened with `SWE-1.7` already selected; did not trigger `/model` menu. |
| Subagent indicator / panel | **NOT TESTED** | No subagents were spawned during the TUI session. |
| Permission prompt | **NOT TESTED** | Used default permission mode (interactive) for the TUI session; no tool permission dialog appeared because the prompt was trivial. |
| Interrupted exit (Ctrl+C while thinking) | **PARTIALLY OBSERVED** | The screen text `Thinking · 0s (esc to interrupt)` indicates `Esc` is the intended interrupt key; `Ctrl+C` fallback was not needed. |
| Terminal restoration after interrupted exit | **NOT TESTED** | Only clean `/exit` exit observed. |

## Classification of facts

| Fact | Classification |
|------|----------------|
| Native TUI takes over the terminal with alternate screen, cursor hide, mouse, bracketed paste, and Kitty keyboard protocol | **OBSERVED LIVE** |
| TUI displays model `SWE-1.7` and a plan/usage status line | **OBSERVED LIVE** |
| Input bar uses truecolor ANSI and a `❭` prompt | **OBSERVED LIVE** |
| `/exit\r` exits cleanly with return code 0 | **OBSERVED LIVE** |
| TUI session is resumable via `devin -r <session-id>` | **OBSERVED LIVE** |
| `Esc` interrupts a thinking turn | **DOCUMENTED + inferred from on-screen hint** |

## Implications for Goal Devin

- The safest integration is a **launcher**: `goal-devin` spawns `devin` with the
  user's terminal attached, then waits for the process to exit.
- Do **not** try to intercept, re-render, or inject keystrokes into the native
  TUI. The alternate screen, Kitty keyboard protocol, and mouse mode are owned
  by `devin`.
- A separate **read-only sidecar** can run in another process/session and
  observe state via hooks or `devin list --format json` without touching the
  terminal.
- Clean `/exit` restores the terminal; Goal Devin should ensure the child is
  reaped and the terminal is restored if it terminates abnormally.
