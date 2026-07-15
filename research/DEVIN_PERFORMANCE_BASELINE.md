# Devin CLI — Performance Baseline

Hardware: Devin cloud VM, x86_64 Linux, exact CPU unknown.  
Binary: `devin 3000.1.27 (0d4bf12e)`, statically linked ELF64, ~133 MiB.

## Measurements

| Metric | Value | Method |
|--------|-------|--------|
| Binary size | 139,922,344 bytes (~133 MiB) | `stat` |
| `devin --version` (cold) | ~2 ms | Python `subprocess` loop, 5 samples |
| `devin list --format json` (no sessions) | ~174 ms | Python `subprocess` loop, 5 samples |
| ACP startup to `initialize` response | ~2.3 s | `chisel_server::acp` logs |
| ACP `session/new` latency | ~0.5 s after init | `acp-probe2` transcript |
| Memory (idle ACP server) | not measured | not measured in this phase |
| CPU while idle | not measured | not measured |
| File-descriptor count | not measured | not measured |

## Warm vs. cold

`devin --version` was measured repeatedly and stayed at ~2 ms, suggesting the OS page cache was warm. `devin list --format json` reads `~/.local/share/devin/cli/sessions.db` and performs a network refresh of team settings/model configs; its ~174 ms is dominated by API sync, not disk.

## ACP startup breakdown (from stderr logs)

1. `chisel: version=... startup`
2. `chisel_server::acp: Starting ACP server` (~0 ms)
3. Team settings fetch: ~210 ms
4. Model registry fetch: ~300 ms (36 groups)
5. Config load/write
6. Database migrations: ~1.0 s (16 refinery migrations)
7. Total to `initialize` response: ~2.3 s

This means spawning `devin acp` per prompt is too slow; a wrapper should keep one ACP server alive for the duration of a workflow.

## Implications for Goal Devin

- Spawning `devin -p` per iteration is fine (2 ms startup + model latency).
- Spawning `devin acp` per iteration is not fine (~2 s setup).
- A future ACP-based Goal Devin should spawn `devin acp` once and multiplex all prompts through it.
- The 133 MiB binary size means distribution/packaging is heavyweight; a Rust rewrite of Goal Devin should stay small (<20 MiB) and call out to the installed `devin` binary.

## Not measured

- Interactive TUI render frame time.
- Model inference latency (depends on backend, not relevant to CLI overhead).
- Rate-limit delay / retry timing.
- Memory footprint during a long session.
- Disk writes per turn.
