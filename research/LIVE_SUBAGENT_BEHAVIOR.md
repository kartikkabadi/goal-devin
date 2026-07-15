# Live Evidence — Native Subagent Behavior

## Evidence classification

- **DOCUMENTED** — from the official Devin CLI public documentation.
- **OBSERVED LIVE** — from a live `devin` session in this research phase.
- **INFERRED** — deduced from other evidence but not directly observed.
- **UNKNOWN** — not yet determined.

## Purpose

Ask the root agent to run one `subagent_general`, one `subagent_explore`, and one
custom profile, capture the profile, foreground/background flag, tool name, input
schema, completion event, and effective-model evidence.

## Environment

- Canary repo: `/home/ubuntu/repos/goal-devin/.research-evidence/canary3`
- Initial files: `hello.py`, `test_hello.py`
- Custom profile: `.devin/agents/reviewer/AGENT.md` with frontmatter `model: swe-1-6-fast`
- Devin CLI: `3000.1.27`
- Mode: `devin -p --model swe-1-7 --permission-mode dangerous`
- Hooks: `PreToolUse`/`PostToolUse` logger from `research/fixtures/hook-logger.py`

## Test 1 — `subagent_explore`

### Prompt

```text
Spawn a subagent_explore to list the Python files in this directory and return the result.
```

### Observed output

```text
The subagent found 2 Python files in the directory:

- `hello.py`
- `test_hello.py`
```

### Hook payload

```json
{
  "hook_event_name": "PreToolUse",
  "tool_name": "run_subagent",
  "tool_input": {
    "title": "<REDACTED>",
    "task": "<REDACTED>",
    "profile": "subagent_explore",
    "is_background": false
  },
  "tool_use_id": "run_subagent_0"
}
```

### Findings

- Profile used: `subagent_explore`.
- Foreground: `is_background: false`.
- Tool name: `run_subagent`.
- Task completed successfully; returned a concise list.

## Test 2 — `subagent_general`

### Prompt

```text
Use a subagent_general to add a harmless docstring comment to hello.py.
```

### Observed output

```text
Done. The `subagent_general` added a docstring to `hello.py`:

<ref_file file="/home/ubuntu/repos/goal-devin/.research-evidence/canary3/hello.py" />
```

### Resulting diff

```diff
--- a/hello.py
+++ b/hello.py
@@ -1,2 +1,3 @@
 def hello():
+    """Return the number 1."""
     return 1
```

### Hook payload

```json
{
  "hook_event_name": "PostToolUse",
  "tool_name": "run_subagent",
  "tool_input": {
    "title": "<REDACTED>",
    "task": "<REDACTED>",
    "profile": "subagent_general",
    "is_background": false
  },
  "tool_use_id": "run_subagent_2",
  "tool_response": {
    "success": true,
    "output": "<REDACTED>",
    "error": null
  }
}
```

### Findings

- Profile used: `subagent_general`.
- Foreground: `is_background: false`.
- Completed a write operation (added a docstring).
- Effective model not independently displayed, but because `subagent_general`
  is documented to inherit the parent model, the parent `swe-1-7` is the
  configured/expected model.

## Test 3 — Custom profile `reviewer`

### Custom profile definition

`.devin/agents/reviewer/AGENT.md`:

```markdown
---
model: swe-1-6-fast
---

You are a code reviewer. Provide a one-sentence summary of the Python files in this directory.
```

### Prompt

```text
Use the reviewer subagent to summarize the Python files in this directory.
```

### Observed output

```text
Here is the reviewer subagent’s summary of the Python files in the directory:

- **`hello.py`**: A minimal utility file that defines `hello()`, which returns `1`. The implementation matches its docstring. <ref_file file="/home/ubuntu/repos/goal-devin/.research-evidence/canary3/hello.py" />
- **`test_hello.py`**: A unit test that imports `hello()` and asserts it returns `1`. Simple and correct. <ref_file file="/home/ubuntu/repos/goal-devin/.research-evidence/canary3/test_hello.py" />

Both files are small, correct, and appear to be a basic example/test pair.
```

### Hook payload

```json
{
  "hook_event_name": "PostToolUse",
  "tool_name": "run_subagent",
  "tool_input": {
    "title": "<REDACTED>",
    "task": "<REDACTED>",
    "profile": "reviewer",
    "is_background": false
  },
  "tool_use_id": "run_subagent_1",
  "tool_response": {
    "success": true,
    "output": "<REDACTED>",
    "error": null
  }
}
```

### Findings

- Custom profile id: `reviewer`.
- `AGENT.md` frontmatter `model: swe-1-6-fast` was accepted (no parse/usage error).
- The subagent produced a read-only summary.
- Whether `swe-1-6-fast` was actually used cannot be confirmed from the CLI
  surface (TUI does not label subagent model).

## Effective-model evidence

| Profile | Configured/requested | Observed effective model |
|---------|----------------------|--------------------------|
| `subagent_general` | Inherit parent `swe-1-7` | **Not independently exposed** |
| `subagent_explore` | Default subagent model / router | **Not independently exposed** |
| Custom `reviewer` | `swe-1-6-fast` (frontmatter) | **Not independently exposed** |

The only model evidence visible to Goal Devin is the parent session's ATIF
`model_name` (`SWE-1.7`) and the native TUI status line.

## Cancellation / completion

- All three subagents completed successfully (`success: true`).
- No cancellation was tested because the sessions were tiny and fast.
- The `run_subagent` tool response provides a single `success`/`output`/`error`
  payload; the parent agent summarizes it.

## TUI model labeling

- Not tested in the TUI; the CLI subagent panel does not display the model per
  the public docs.

## Classification of facts

| Fact | Classification |
|------|----------------|
| `run_subagent` tool exists and takes `title`, `task`, `profile`, `is_background` | **OBSERVED LIVE** |
| `subagent_explore` returns read-only summaries | **OBSERVED LIVE** |
| `subagent_general` performs file edits | **OBSERVED LIVE** |
| Custom profile is loaded from `.devin/agents/<id>/AGENT.md` | **OBSERVED LIVE** |
| `is_background` is `false` for these foreground tasks | **OBSERVED LIVE** |
| Effective subagent model is not exposed | **DOCUMENTED + INFERRED** |

## Notes for Goal Devin

- Native subagents are the correct fan-out mechanism for work inside a session.
- Goal Devin should not spawn independent `devin -p` sessions for ordinary
  parallel work; reserve those for Goal Devin-owned side jobs.
- Custom profiles should only be used when the user explicitly provides one.
- Because effective subagent models are not visible, Goal Devin must rely on the
  documented model inheritance rules and the parent session model.
