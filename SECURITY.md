# Security Policy

## Summary

`goal-devin` is a wrapper around the Devin CLI. It calls `devin -p` in a loop with `--permission-mode dangerous` by default, which auto-approves all tool calls. **The model can read, write, and execute anything in your workspace.** Only run goals you trust.

## Reporting a vulnerability

Email: `1kartikkabadi1@gmail.com` with subject `goal-devin security`.

Do not open a public issue for security vulnerabilities. I will acknowledge within 48 hours and aim for a fix within 7 days.

## Hardening

If running unattended or on untrusted goals:

1. **Use Devin's sandbox mode.** `goal-devin goal "..." --permission-mode auto` — Devin will prompt for dangerous operations instead of auto-approving.
2. **Set `--iter-timeout`.** Default is 1800s (30 min). Lower it if you want faster failure on hung iterations.
3. **Set `--max-iters`.** Don't let the loop run forever on untrusted goals. `--max-iters 10` caps the burn.
4. **Read the logs.** `goal-devin logs` shows every iteration's output. Check what the model actually did.
5. **Run in a container or VM.** For fully untrusted goals, don't run on your host machine.

## What goal-devin does NOT do

- Does not send your data anywhere except to the Devin CLI (which sends to the model provider).
- Does not store secrets, tokens, or credentials.
- Does not phone home, telemetry, or analytics.
- Does not execute code itself — it only calls `devin`, which executes code per its own permission model.

## Scope

Vulnerabilities in scope:
- `goal-devin` source code (`src/goal_devin/`)
- State file corruption or race conditions
- Path traversal in state/log file handling
- Argument injection into the `devin` subprocess call

Out of scope:
- The Devin CLI itself (report to [Cognition](https://devin.ai))
- The model's behavior (that's the model provider's problem)
- Your goal prompt (that's your problem)
