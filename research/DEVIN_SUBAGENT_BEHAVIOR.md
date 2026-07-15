# Devin CLI — Subagent Behavior

## Public ACP documentation

The Agent Client Protocol (ACP) supports third-party agents running as subprocesses. Public docs state that `session/prompt` can result in:

- `session/update` with `tool_call` and `tool_call_update`
- `session/request_permission` for sensitive operations
- `session/update` with `plan` for agent plans

The protocol has a `subagents` concept but does not publicly document a dedicated `subagent` method.

## Strings-derived evidence

Non-invasive `strings` inspection of the binary found many subagent-related terms (not full schemas):

- `run_in_background`
- `parentAgentId`
- `subagents`
- `cognition.ai/subagent_context`
- `cognition.ai/subagent`
- `agent_depth`
- `is_background`
- `subagent completed without calling StructuredOutput`
- `agent({isolation:'remote'}) is not available in this build`
- `agent abandoned: user requested retry on all`
- `agent stalled on all`

This indicates subagents are a first-class internal concept with:

- foreground vs. background execution;
- parent/child relationships;
- structured output requirements;
- isolation modes (likely `local`, `worktree`, `remote`);
- retry/abandon semantics.

## Claude Code Ultra Code dynamic workflow API (reference)

The user's original feature target is Claude Code's dynamic workflows, whose public gist defines:

| Primitive | Behavior |
|-----------|----------|
| `agent(prompt, opts?)` | Spawn ONE subagent → return result |
| `parallel(thunks)` | Barrier fan-out |
| `pipeline(items, ...stages)` | Per-item chain, no barrier |
| `phase(title)` | Progress UI label |
| `log(msg)` | Progress line |
| `budget` | Output-token accounting |
| `args` | Workflow arguments |

These are the semantics Goal Devin should port, implemented on top of `devin -p` sessions rather than Claude's internal subagent runtime.

## What Goal Devin should support

For the `ultra` dynamic-workflow feature:

- `agent(prompt, schema=..., worktree=..., model=...)` → run a `devin -p` session and parse/return output.
- `parallel([() => agent(...), ...])` → run multiple `devin -p` sessions concurrently with a semaphore.
- `pipeline(items, stage1, stage2, ...)` → per-item stage chains, concurrent across items.
- `phase(title)`, `log(msg)` → event emission to a renderer.
- `budget` / `args` → workflow namespace.

This is **not** the same as Devin's internal subagent tool; it is a wrapper-level orchestration of independent `devin` sessions.

## Unknowns

| Question | Status |
|----------|--------|
| Exact `agent()` input schema in Devin | **UNKNOWN** |
| Can `devin -p` spawn background subagents? | **UNKNOWN** (no CLI flag for it) |
| Subagent model pinning | **UNKNOWN** |
| Nested subagent limits | **UNKNOWN** |
| ACP events for subagent lifecycle | **UNKNOWN** |

## Implications

Because Devin CLI does **not** expose a public `subagent` command, Goal Devin's `ultra` mode should treat each `agent()` call as a separate `devin -p` session. This is the only verifiable, public seam.
