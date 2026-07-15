# Live Evidence — Print-Mode Canary Session

## Evidence classification

- **DOCUMENTED** — from the official Devin CLI public documentation.
- **OBSERVED LIVE** — from a live `devin` session in this research phase.
- **INFERRED** — deduced from other evidence but not directly observed.
- **UNKNOWN** — not yet determined.

## Purpose

Run a single real `devin -p` print-mode session against a disposable canary
repository, verify that the CLI authenticated and operated on the selected
model, observe the resulting session identity, Git diff, and test status, and
check the ATIF export metadata.

## Environment

| Setting | Value |
|---------|-------|
| Devin CLI version | `devin 3000.1.27 (0d4bf12e)` |
| Authentication | Logged in via API key (status confirmed before test) |
| Home directory (isolated) | `/home/ubuntu/repos/goal-devin/.research-evidence/home-real` |
| Canary repo | `/home/ubuntu/repos/goal-devin/.research-evidence/canary2` |
| Initial commit | `init` with `fib.py` and `test_fib.py` |

## Command / argv (OBSERVED LIVE)

```text
devin -p --model swe-1-7 --permission-mode accept-edits -- \
  "Add a short harmless docstring comment to fib.py explaining what it does. Do not change the function logic."
```

Exact model selected: `swe-1-7`.
Permission mode selected: `accept-edits`.
Working directory: `/home/ubuntu/repos/goal-devin/.research-evidence/canary2`.

## Timestamps

- Start (epoch seconds): `1784110068`
- End (epoch seconds): `1784110084`
- Wall time: approximately 16 seconds.

## Exit code / stdout / stderr

| Stream | Value |
|--------|-------|
| Exit code | `0` |
| Stdout | `Added a docstring to `fib` in <ref_file file="/home/ubuntu/repos/goal-devin/.research-evidence/canary2/fib.py" />.` |
| Stderr | (empty) |

## Session identity

From `devin list --format json` run immediately after the session:

```json
[
  {
    "id": "level-bathroom",
    "short_id": "level-bathroom",
    "working_directory": "/home/ubuntu/repos/goal-devin/.research-evidence/canary2",
    "working_directory_display": "./",
    "last_activity_at": 1784110084,
    "last_activity_ago": "just now",
    "title": "Add a short harmless docstring comment to fib.py explaining what it does. Do not change the function logic."
  }
]
```

Session ID source: `devin list --format json`, first element, `id` field.

## ATIF export metadata (OBSERVED LIVE)

A separate `devin -p --export /path/to/file.atif ...` run produced an ATIF file with:

- `schema_version`: `ATIF-v1.7`
- `session_id`: `<redacted>`
- `agent.name`: `devin`
- `agent.version`: `3000.1.27`
- `agent.model_name`: `SWE-1.7`

The full ATIF file is stored under `.research-evidence/` and is gitignored.

## Resulting Git diff (OBSERVED LIVE)

```diff
diff --git a/fib.py b/fib.py
index d9bc097..c028cc2 100644
--- a/fib.py
+++ b/fib.py
@@ -1,4 +1,5 @@
 def fib(n):
+    """Return the nth Fibonacci number."""
     if n <= 1:
         return n
     return fib(n-1) + fib(n-2)
```

## Test status (OBSERVED LIVE)

```python
from fib import fib
assert fib(5) == 5
print("ok")
```

Result: `ok` (exit 0).

## Classification of facts

| Fact | Classification |
|------|----------------|
| `devin -p` accepts `--model swe-1-7` and `--permission-mode accept-edits` | **OBSERVED LIVE** |
| The session creates a row in `devin list` with `id`, `short_id`, `working_directory`, `title`, `last_activity_at` | **OBSERVED LIVE** |
| The edit is applied to `fib.py` | **OBSERVED LIVE** |
| Export produces `ATIF-v1.7` with `model_name` `SWE-1.7` | **OBSERVED LIVE** |
| The function logic is preserved | **OBSERVED LIVE** |

## Notes for Goal Devin

- `devin -p` is a valid, low-cost way to run a single deterministic turn and inspect the diff.
- `devin list --format json` returned the new session as the first element in this test. That supports, but does not prove, the `latest_session_id()` assumption.
- The `--model` value is passed through to the agent and recorded in ATIF (`SWE-1.7`).
- `--permission-mode accept-edits` auto-approved the harmless file edit without an interactive prompt.

## Known race in `latest_session_id()`

The evidence supports:

- `devin list --format json` returns newest-first in the tested environment.
- A newly created isolated session appeared as the newest entry.
- Explicit resume by known session ID is stable.

The evidence does **not** yet prove:

- Safety when two sessions start concurrently in one cwd.
- Safety when list visibility is delayed.
- Safety when timestamps collide.
- Safety when another process creates a newer session before Goal Devin lists.
- Safety across all Devin versions.

Classify this as a known race to harden later. Where possible, prefer explicit
session IDs over list-order heuristics.
