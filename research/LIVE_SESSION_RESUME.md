# Live Evidence — Session Resumption

## Evidence classification

- **DOCUMENTED** — from the official Devin CLI public documentation.
- **OBSERVED LIVE** — from a live `devin` session in this research phase.
- **INFERRED** — deduced from other evidence but not directly observed.
- **UNKNOWN** — not yet determined.

## Purpose

Resume the canary print-mode session from `LIVE_PRINT_SESSION.md` with a trivial
follow-up, verify the same session ID, model, cwd, and context continuity, and
confirm Git/test coherence.

## Environment

Same as `LIVE_PRINT_SESSION.md`: isolated home, canary2 repo, Devin CLI
`3000.1.27`, authenticated.

## Command / argv (OBSERVED LIVE)

```text
devin -r level-bathroom -p --model swe-1-7 --permission-mode accept-edits -- \
  "Add a short harmless docstring comment to test_fib.py. Do not change the function logic."
```

## Timestamps

- Start (epoch seconds): `1784110143`
- End (epoch seconds): `1784110160`
- Wall time: approximately 17 seconds.

## Exit code / stdout / stderr

| Stream | Value |
|--------|-------|
| Exit code | `0` |
| Stdout | `Done. Added a docstring to `test_fib` in <ref_file file="/home/ubuntu/repos/goal-devin/.research-evidence/canary2/test_fib.py" />.` |
| Stderr | (empty) |

## Session identity after resume

From `devin list --format json`:

```json
[
  {
    "id": "level-bathroom",
    "short_id": "level-bathroom",
    "working_directory": "/home/ubuntu/repos/goal-devin/.research-evidence/canary2",
    "working_directory_display": "./",
    "last_activity_at": 1784110160,
    "last_activity_ago": "just now",
    "title": "Add a short harmless docstring comment to fib.py explaining what it does. Do not change the function logic."
  }
]
```

- Same session ID: `level-bathroom`.
- Same `working_directory`: canary2 absolute path.
- `last_activity_at` updated to the resume timestamp.
- Title remains the original session title (first prompt).

## Model supplied / preserved

The resume command re-supplied `--model swe-1-7`. The `sessions` table stores
`model TEXT NOT NULL`, so the original model is preserved even if `--model` is
omitted. Goal Devin's resume path passes `args.model or state.get("model")`,
which matches this behavior.

## Context continuity

The agent recognized the previous turn and applied the follow-up edit to the
other file, demonstrating that the resumed session retains conversation and
repository context.

## Resulting Git diff after resume (OBSERVED LIVE)

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
diff --git a/test_fib.py b/test_fib.py
index db05dc4..479a870 100644
--- a/test_fib.py
+++ b/test_fib.py
@@ -1,4 +1,5 @@
 from fib import fib
 
 def test_fib():
+    """Check that fib(5) returns the fifth Fibonacci number."""
     assert fib(5) == 5
```

## Test status after resume (OBSERVED LIVE)

```python
from fib import fib
assert fib(5) == 5
print("ok")
```

Result: `ok` (exit 0).

## `devin list --format json` safety with multiple sessions

The canary2 directory had only the `level-bathroom` session during the resume
test. A separate check in `canary/` showed that `devin list --format json`
returns all sessions for the current directory sorted newest-first. Goal Devin's
`latest_session_id()` picks the first element, which is the newest matching
session. This is safe when a new session is created and immediately listed.

## Classification of facts

| Fact | Classification |
|------|----------------|
| `devin -r <id> -p` resumes the same session id | **OBSERVED LIVE** |
| `working_directory` is preserved | **OBSERVED LIVE** |
| `last_activity_at` is updated on resume | **OBSERVED LIVE** |
| Context continuity across resume | **OBSERVED LIVE** |
| Model persistence if `--model` omitted | **INFERRED** from sessions DB schema; not directly tested by omitting `--model` |

## Notes for Goal Devin

- `devin -r <id> -p` is the correct continuation command for a prior print-mode session.
- Session IDs are stable and resumable.
- `devin list --format json` newest-first ordering is reliable for picking the just-created session.
- Always supply the same model on resume to avoid silent model switches.
