# Devin CLI — Binary Metadata

## Installation

- Installed via `curl -fsSL https://cli.devin.ai/install.sh | bash` on 2026-07-15.
- Resolved version: `devin 3000.1.27 (0d4bf12e)`.
- Symlink chain:
  - `~/.local/bin/devin` → `~/.local/share/devin/cli/_versions/current/bin/devin`
  - `current` → `3000.1.27`
  - Real binary: `~/.local/share/devin/cli/_versions/3000.1.27/bin/devin`

## Binary facts

| Property | Value |
|----------|-------|
| File | `~/.local/share/devin/cli/_versions/3000.1.27/bin/devin` |
| Size | 139,922,344 bytes (~133 MiB) |
| SHA-256 | `6c0a5345055781da752b982c77b3179b5ece1b1bf1a38433156dad9564e2f079` |
| Format | ELF64, PIE, `e_machine = EM_X86_64` |
| Linkage | statically linked (`ldd` reports "statically linked") |
| Dynamic section | present but contains no `NEEDED` entries (see `readelf-dynamic.out`) |
| Symbol visibility | `.dynsym` contains one `UND NOTYPE` entry; no exported API surface. The binary is effectively stripped of useful symbols. |
| Signatures | No code-signature metadata was extracted (Linux ELF). |

Evidence files: `.research-evidence/devin.sha256`, `.research-evidence/ldd.out`, `.research-evidence/readelf-header.out`, `.research-evidence/readelf-dynamic.out`, `.research-evidence/readelf-symbols.out`.

## Rust / Cargo evidence

The binary is **CONFIRMED** to be a Rust/Cargo build. Evidence:

- Rust panic strings and `std::result::Result` error messages are present.
- Cargo registry source paths are embedded in panic/debug strings:
  - `tokio-tungstenite-0.28.0/src/compat.rs`
  - `tokio v1.35.0`
  - `hyper v0.14.28`
  - `serde v1.0.195`
  - `tracing-subscriber-0.3.22/src/registry/sharded.rs`
  - `unsafe-libyaml-0.2.11/src/parser.rs`
  - `clap_builder-4.5.60/src/builder/arg.rs`
  - `reqwest::config::RequestConfig<...>`
- Internal crate/source paths:
  - `chisel/src/setup.rs`
  - `chisel/src/shell/pty_proxy.rs`
  - `chisel/src/export.rs`
  - `chisel-agent/src/session_db.rs`
  - `chisel-agent/src/acp_server/agent_impl.rs`
  - `chisel-agent/src/acp_server/auth.rs`
  - `chisel-agent/src/skills_loading.rs`
  - `chisel-agent/src/wiki.rs`
  - `scrollback/src/tui/border.rs`
  - `scrollback/src/tui/cell_render.rs`
  - `scrollback/src/tui/diff.rs`
  - `scrollback/src/tui/surface.rs`

These path fragments identify at least two internal workspace crates: `chisel` (the CLI / UI) and `chisel-agent` (session/ACP/agent logic), plus `scrollback` (a custom terminal buffer/TUI crate). No third-party TUI framework such as Ratatui or tui-rs was found.

## Library classification

| Library | Evidence level | Notes |
|---------|---------------|-------|
| `tokio` / `tokio-tungstenite` | **CONFIRMED** | Version strings and source paths in panic messages; async runtime and WebSocket transport. |
| `hyper` | **CONFIRMED** | Version string in strings. |
| `reqwest` | **CONFIRMED** | Type names present. |
| `serde` | **CONFIRMED** | Version string and `Deserialize` implementation errors. |
| `clap` (builder 4.5.60) | **CONFIRMED** | Source paths match the `--help` output style. |
| `tracing-subscriber` | **CONFIRMED** | Version string and source path. |
| `crossterm` | **CONFIRMED** | Multiple terminal control strings: `crossterm::event::EnableBracketedPaste`, `crossterm::cursor::Hide`, `crossterm::terminal::EnterAlternateScreen`, etc. |
| `ratatui` / `tui-rs` / `termion` | **NOT INDICATED** | No strings or source paths found. |
| `SQLite` | **CONFIRMED** | `SQLite format 3` magic and `session_db.rs` paths; sessions stored in `~/.local/share/devin/cli/sessions.db`. |
| `unsafe-libyaml` | **CONFIRMED** | Version string; YAML config parsing. |
| `tonic` / `gRPC` | **NOT CONFIRMED** | No explicit tonic paths; some protobuf-style strings (`exa.seat_management_pb`) are present but no tonic runtime markers. |

## What remains unknown

- The exact Cargo workspace layout (`chisel`, `chisel-agent`, `scrollback` relationships).
- Whether the binary bundles a bundled Node/Python runtime or merely static Rust libraries (the 133 MiB size is consistent with a fully static Rust binary plus embedded assets).
- Whether `tokio` is configured with a multi-threaded or current-thread runtime.
- The exact WebSocket endpoint and protobuf schema used by the agent backend (only message names, not definitions, are visible in strings).
- Whether the TUI uses a custom immediate-mode renderer on top of `crossterm` or maintains an off-screen buffer; `scrollback` strongly suggests a custom buffer.

## Non-invasive inspection performed

- `which`, `realpath`, `ls -la`, `stat`, `sha256sum`
- `ldd`
- `readelf -h`, `-d`, `-s`
- `strings -n 4` with targeted greps for crate names, terminal control sequences, and internal source paths

No decompilation, no patching, no binary modification, and no network interception were performed.
