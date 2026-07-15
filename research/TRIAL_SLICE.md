# Goal Devin — Proposed Trial Slice (Phase Next)

## Goal

Prove the `ultra` dynamic-workflow runtime end-to-end in **Python**, using the existing fake `devin` fixture, before committing to a full feature or a Rust rewrite.

## Non-goals

- Do not implement the planner yet.
- Do not implement the live ANSI dashboard yet.
- Do not add `textual` or any runtime dependency.
- Do not modify `GoalLoop` for `goal`/`resume`.
- Do not commit to a Rust rewrite.

## Exact files to add

```text
src/goal_devin/
  agent.py        # AgentResult, DevinAgentRunner
  workflow.py     # WorkflowEngine, Journal, Budget, WorkflowEvent
  planner.py      # stub: raise NotImplementedError or pass-through
  ui.py           # Renderer, CliRenderer
src/goal_devin/cli.py
  # add 'ultra' subparser and cmd_ultra
tests/
  test_workflow.py
tests/fixtures/
  # optional: sample workflow scripts
```

## Exact workflow script format

```python
# sample-workflow.py
phase("Plan")
res = await agent("List the three biggest files", schema={"type":"object","properties":{"files":{"type":"array","items":{"type":"string"}}},"required":["files"]})
files = res["files"]

phase("Check")
results = await parallel([
    lambda f=f: agent(f"Check {f} for TODOs", label=f"check:{f}")
    for f in files[:3]
])

return results
```

## Exact command

```bash
GOAL_DEVIN_MAX_AGENTS=3 \
GOAL_DEVIN_WORKFLOW_CONCURRENCY=2 \
GOAL_DEVIN_FAKE_STATE=/tmp/fake-state \
PATH=research/fixtures:$PATH \
  goal-devin ultra --script sample-workflow.py --output result.json
```

## Exact tests

1. `test_workflow.py::test_agent_runs_fake_devin`
2. `test_workflow.py::test_parallel_runs_concurrently_with_semaphore`
3. `test_workflow.py::test_journal_skips_completed_on_resume`
4. `test_workflow.py::test_budget_stops_after_max_calls`
5. `test_workflow.py::test_phase_and_log_emit_events`
6. `test_cli.py::test_ultra_parser_routes_script`

## Commands to verify

```bash
uv run pytest tests/test_workflow.py tests/test_cli.py -v
uv run ruff check .
uv run ruff format --check .
```

## Expected diff size

~600-900 new lines, ~30 modified lines in `cli.py`.

## Rollback

- Remove `src/goal_devin/{agent,workflow,planner,ui}.py`.
- Remove `ultra` subparser from `cli.py`.
- Remove `tests/test_workflow.py`.
- Existing `goal`/`resume`/`status`/`logs` remain unchanged.

## Acceptance criteria

1. `goal-devin ultra --script <path>` runs without error against the fake `devin`.
2. `agent()` returns either text or a parsed JSON dict when `schema` is supplied.
3. `parallel()` runs thunks concurrently up to a configurable limit.
4. `Journal` caches results by stable key; `resume` skips completed agents.
5. `Budget` stops new agent calls after `--max-agents`.
6. `CliRenderer` prints phase/log lines.
7. All existing 58 tests still pass.
8. `ruff` passes.

## Two adversarial review prompts

1. **Safety**: Does the `WorkflowEngine` correctly restrict the script namespace so it cannot import modules, read files, or access `__builtins__` not on an allowlist? Does it prevent infinite loops without budget?
2. **Correctness**: Does the fake `devin` evidence prove that `agent()` passes the exact same argv to `devin -p` as `GoalLoop` does, and does `parallel()` preserve the per-agent worktree/cwd semantics?

## Why Python for the trial slice

- Validates the `ultra` design before choosing a final language.
- Uses the existing fake `devin` harness and test infrastructure.
- Avoids rewriting the CLI/state/worktree layer in Rust before the workflow semantics are proven.
- If the Python slice succeeds, the same design can be ported to Rust later if distribution/performance demands it.
