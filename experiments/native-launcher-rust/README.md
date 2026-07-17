# Goal Devin R1B Rust native-launcher candidate

This directory contains the **R1B** native-launcher candidate for Goal Devin,
implemented in Rust. It mirrors the black-box contract of the Python R1A.1
candidate under `experiments/native-launcher-python/` and adds an optional,
experimental companion TUI.

## Repository layout

```text
experiments/native-launcher-rust/
├── Cargo.toml                 # workspace package manifest
├── README.md                  # this file
├── COMPANION_TUI_SPEC.md      # companion TUI feature spec
├── COMPANION_TUI_ARCHITECTURE.md  # adjacent-pane architecture
├── src/
│   ├── lib.rs                 # library exports
│   ├── cli.rs                 # clap argument parser
│   ├── supervisor.rs          # launcher lifecycle orchestration
│   ├── sidecar.rs             # event collection / spooler daemon
│   ├── hook.rs                # Devin observation hook
│   ├── profile.rs             # read-only worker profile generation
│   ├── manifest.rs            # runtime manifest generation
│   ├── limits.rs              # runtime limits validation
│   ├── schema.rs              # JSON Schema validator
│   ├── utils.rs               # small filesystem/path helpers
│   ├── bin/
│   │   ├── goal-devin-dev.rs      # main launcher binary
│   │   ├── goal-devin-hook.rs     # standalone hook (debug/testing)
│   │   ├── goal-devin-sidecar.rs  # standalone sidecar
│   │   └── goal-devin-companion.rs # optional companion TUI
│   └── companion/
│       ├── mod.rs
│       ├── model.rs           # state model + sanitization
│       ├── transport.rs       # state file read/write
│       ├── style.rs           # theme / color fallbacks
│       ├── app.rs             # TUI event loop
│       └── render.rs          # ratatui layout
└── tests/
    └── integration.rs         # end-to-end Rust integration test
```

## Binaries

* `goal-devin-dev` — the native launcher. Runs `devin` inside a private
  runtime directory, installs a read-only worker profile, manages the sidecar,
  and produces a runtime manifest + summary.
* `goal-devin-sidecar` — the event collection daemon. Polls the events spool,
  validates events, and writes a bounded summary.
* `goal-devin-hook` — the Devin observation hook. Reads a JSON payload on
  stdin and writes a sanitized event file.
* `goal-devin-companion` — optional TUI (requires the `companion` Cargo
  feature). Renders Goal Devin-owned state in an adjacent terminal pane.

## Build

Rust toolchain: `rustc` and `cargo` 1.83.0 or later.

```bash
cd experiments/native-launcher-rust

# baseline build (no companion)
cargo build --release

# build with the companion binary
cargo build --release --features companion
```

## Test

```bash
cd experiments/native-launcher-rust

cargo fmt --check
cargo clippy --all-targets --all-features -- -D warnings
cargo test --all-targets --all-features
cargo build --release
```

## Shared black-box contract

The shared contract lives in `experiments/native-launcher-testkit/run-contract.py`.
Run all modes from the repository root:

```bash
python3 experiments/native-launcher-testkit/run-contract.py \
  --candidate experiments/native-launcher-rust/target/release/goal-devin-dev \
  --devin-bin experiments/native-launcher-testkit/fake-devin \
  --model swe-1-7 \
  --permission-mode accept-edits \
  --contract-dir experiments/native-launcher-testkit \
  --canary-fixture experiments/native-launcher-testkit/fixtures/canary \
  --runtime-root /tmp/goal-devin-runtime \
  --base-dir /tmp/goal-devin-base \
  --keep-artifacts
```

Supported modes include `--existing-hooks`, `--tty`, `--process-overlap`,
`--no-poll`, and `--stress`.

## Usage

### Baseline

```bash
./experiments/native-launcher-rust/target/release/goal-devin-dev \
  --model swe-1-7 \
  --permission-mode accept-edits \
  --devin-bin /usr/local/bin/devin \
  --contract-dir experiments/native-launcher-testkit \
  --runtime-root "$XDG_RUNTIME_DIR/goal-devin" \
  --canary "$XDG_RUNTIME_DIR/goal-devin/canary"
```

### With the companion TUI

Launch the main binary with `--companion`:

```bash
./experiments/native-launcher-rust/target/release/goal-devin-dev \
  --model swe-1-7 \
  --permission-mode accept-edits \
  --devin-bin /usr/local/bin/devin \
  --contract-dir experiments/native-launcher-testkit \
  --runtime-root "$XDG_RUNTIME_DIR/goal-devin" \
  --canary "$XDG_RUNTIME_DIR/goal-devin/canary" \
  --companion \
  --companion-poll-ms 100
```

The launcher prints the exact companion command. Open an adjacent terminal pane
and run it, for example:

```bash
./experiments/native-launcher-rust/target/release/goal-devin-companion \
  --runtime-dir "$XDG_RUNTIME_DIR/goal-devin/run-<id>" \
  --poll-ms 100
```

Press `q`, `Esc`, or `Ctrl+C` to close the companion. Closing the companion does
not stop Devin.

## Companion TUI

* Optional and experimental.
* Built behind the `companion` Cargo feature.
* Reads only Goal Devin-owned state (`companion/state.json`).
* Does not parse, buffer, mirror, or redraw native Devin TUI output.
* Supports truecolor, 256-color, 16-color, and `NO_COLOR`/`--ascii` fallbacks.
* Responsive layout down to very narrow terminals.

For details, see:

* `COMPANION_TUI_SPEC.md`
* `COMPANION_TUI_ARCHITECTURE.md`
* `research/DEVIN_TUI_COMPANION_STUDY.md`

## Design constraints

* The supervisor does **not** `exec` or replace itself; it stays alive and waits
  for the native Devin child.
* The native Devin child inherits `stdin/stdout/stderr` directly.
* Goal Devin does not read or redraw native Devin output.
* The companion TUI is optional and does not change the baseline contract.
* No existing production `goal-devin` commands are modified.
* No secrets, credentials, or private state are vendored or logged.

## Research notes

The Devin CLI version recorded during this phase is `devin 3000.1.27
(0d4bf12e)`, installed from `https://cli.devin.ai/install.sh`. The TUI study
is in `research/DEVIN_TUI_COMPANION_STUDY.md`.
