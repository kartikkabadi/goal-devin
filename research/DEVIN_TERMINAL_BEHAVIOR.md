# Devin CLI — Terminal Behavior

## Observation method

A pseudo-TTY was created with `script -q -c 'devin' /dev/null` in an isolated `HOME` with `WINDSURF_API_KEY` set. The process was killed after 5 seconds to capture initial terminal negotiation without consuming a full session.

## Captured ANSI sequences (startup)

```text
\x1b[1mWelcome to Devin CLI!\x1b[0m
\x1b[s\x1b[?u\x1b[c\x1b[?2004h\x1b[6n\x1b[?2026h\r\x1b[?25l\x1b[?2026l
```

Decoded:

| Sequence | Meaning | Status |
|------------|---------|--------|
| `ESC [ ?u` | Kitty keyboard protocol (`CSI ? u`) | **CONFIRMED** |
| `ESC [ c` | Device Attributes (DA1) query | **CONFIRMED** |
| `ESC [ ?2004 h` | Enable bracketed paste | **CONFIRMED** |
| `ESC [ 6n` | Cursor position query | **CONFIRMED** |
| `ESC [ ?2026 h` | Begin synchronized update | **CONFIRMED** |
| `ESC [ ?25 l` | Hide cursor | **CONFIRMED** |
| `ESC [ ?2026 l` | End synchronized update | **CONFIRMED** |

`crossterm` strings found in the binary match every one of these sequences.

## Inferred behavior

- **Cursor**: hidden during startup/TUI rendering.
- **Synchronized updates**: used to avoid tearing while redrawing.
- **Bracketed paste**: enabled, so the app can distinguish typed vs. pasted input.
- **Kitty keyboard protocol**: enabled for richer key events (modifiers, key release, etc.).
- **Device attributes / cursor position**: standard capability/position discovery.

## Alternate screen

`crossterm::terminal::EnterAlternateScreen` / `LeaveAlternateScreen` strings are present in the binary, but the 5-second capture did not show `ESC [ ?1049 h`. The TUI likely enters alternate screen shortly after the initial spinner/welcome screen, once the session begins. **STRONGLY INDICATED** but not observed.

## Mouse mode

`crossterm::event::EnableMouseCapture` string present; not observed in the short capture. **STRONGLY INDICATED**.

## PTY / shell proxy

Source path `chisel/src/shell/pty_proxy.rs` strongly indicates Devin uses a PTY proxy to run shell commands and stream output. This is important for any tool that wants to share the terminal with `devin`.

## Coexistence recommendation for Goal Devin

Goal Devin should **not** write to the same TTY while `devin` is in interactive/alternate-screen mode. For the planned `ultra` dynamic-workflow TUI:

- Use `crossterm` or equivalent for ANSI sequences.
- Enter alternate screen only when `--dashboard` is requested; default CLI mode should remain in normal screen.
- Hide cursor while rendering dashboard, restore on exit.
- Use synchronized updates (`CSI ? 2026 h/l`) to prevent flicker.
- Do **not** enable Kitty keyboard protocol or mouse mode unless needed; keep compatibility with generic terminals.
- If `devin` subprocess is spawned in interactive mode, Goal Devin should either give it the TTY entirely (using `script`/`pty`) or run `devin -p`/`devin acp` non-interactively and render progress itself.

## Untested

- Resize handling (`SIGWINCH`).
- 16/256/truecolor negotiation.
- `NO_COLOR` behavior in TUI mode.
- Restoration after abnormal exit or `SIGINT`.
- Unicode width / grapheme clusters.
