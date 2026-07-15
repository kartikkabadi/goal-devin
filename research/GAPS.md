# Goal Devin — Research Gaps

This phase intentionally did not implement or run everything. The following
gaps are acknowledged and should be addressed as work proceeds.

## Closed in Phase R0.5

- **Authentication / live session**: Resolved by writing a valid
  `~/.local/share/devin/credentials.toml` in isolated `HOME` directories. Real
  `devin -p` and `devin -r` sessions now run.
- **Real TUI**: A PTY-driven capture via `research/fixtures/tui-pexpect.py`
  launched the native TUI, sent input, and exited cleanly.
- **Hooks**: Real `PreToolUse`/`PostToolUse`/`SessionStart`/`UserPromptSubmit`/
  `Stop`/`SessionEnd` payloads were captured with an observation-only hook.
- **Subagent schema**: `run_subagent` input/output shape was observed live.
- **Custom subagent profile**: `.devin/agents/reviewer/AGENT.md` with `model:`
  frontmatter was loaded and used.
- **Session identity**: `devin list --format json` shape and newest-first
  ordering observed in a controlled single-session test. Full concurrency safety
  remains unproven.

## Still open

### Rate-limit behavior

**What we could not do**: Capture a real rate-limit event.

**Why**: No rate limit occurred naturally; intentionally triggering one would be
abusive and consume paid usage.

**Impact**: Goal Devin cannot yet implement rate-limit detection and backoff.

**Location**: `research/DEVIN_RATE_LIMIT_BEHAVIOR.md`.

### Background subagent and `read_subagent` semantics

**What we could not do**: Exercise a background subagent or the `read_subagent`
tool.

**Why**: The live tests used foreground subagents in `devin -p` mode; background
mode and subagent state inspection are TUI/native features.

**Impact**: Full subagent panel behavior and parent notification are not
empirically known.

**Location**: `research/LIVE_SUBAGENT_BEHAVIOR.md`.

### Effective subagent model visibility

**What we could not do**: Confirm the exact model used by `subagent_explore` or
a custom profile, or empirically verify that `subagent_general` always inherits
the parent model.

**Why**: The CLI does not label subagent models in hooks, ATIF, or TUI, so
there is no independent observation of the *effective* worker model. Goal
Devin can only record the *selected policy*, the *configured/requested model*
(profile or `model:` frontmatter), and any *observed effective model* inferred
from non-invasive evidence.

**Impact**: Goal Devin must trust documented inheritance rules. It cannot
claim runtime proof that a worker ran on the root model when only configuration
proof exists. `subagent_explore` does not satisfy the same-model default because
it is routed through the default subagent model; it should only be used when the
user explicitly opts into a routed/different worker model.

**Location**: `research/DEVIN_MODEL_BEHAVIOR.md`,
`research/DEVIN_SUBAGENT_BEHAVIOR.md`.

### Full interactive TUI features

**What we could not do**: Test the native model picker, subagent indicator,
subagent panel, permission prompts, or interrupted exit recovery.

**Why**: The PTY probe only exercised basic input, `/exit`, and `Esc`/`Ctrl+C`
fallbacks.

**Impact**: Some TUI integration details (e.g. permission prompt handling) remain
undocumented.

**Location**: `research/LIVE_NATIVE_TUI.md`.

### Session-identity concurrency race

**What we could not do**: Prove that `devin list --format json` newest-first
ordering safely identifies the just-created session under concurrency.

**Why**: Only isolated, sequential sessions were tested; no controlled concurrent
starts, list delays, or timestamp-collision tests were performed.

**Impact**: Goal Devin's `latest_session_id()` heuristic may pick the wrong
session if two sessions start in the same cwd, if list visibility lags, or if
another process creates a newer session before Goal Devin lists.

**Location**: `research/DEVIN_SESSION_IDENTITY.md`,
`research/LIVE_PRINT_SESSION.md`, `research/LIVE_SESSION_RESUME.md`.

### Explicit `--config` override interaction

**What we could not do**: Determine how `devin --config <hook-only-config>`
interacts with the normal documented project, user, and `AGENT.md` hook sources.

**Why**: Normal config and hook collection precedence is publicly documented, but
the effect of an explicit `--config` file on those normal sources was not
empirically tested. The trial must use a project hook file in the disposable
canary or a hook-only `--config` capability probe rather than copying or merging
secret-bearing user/project config.

**Impact**: A hook-only `--config` might augment or replace normal sources; the
trial must observe and record which behavior occurs.

**Location**: `research/NATIVE_INTEGRATION_TRIAL.md`.

### Long-session behavior

**What we could not do**: Observe compaction, context-window limits, or multi-turn
TUI sessions over many minutes.

**Why**: All live sessions were tiny and short.

**Impact**: Reliability policies for long-running orchestration are not
empirically grounded yet.

### `devin acp` full turn lifecycle

**What we could not do**: Send `session/prompt` and observe the complete stream
of `session/update` notifications for a real turn.

**Why**: It consumes tokens and was not required for the current corrected
scope.

**Impact**: ACP-based orchestration is not yet proven end-to-end.

**Location**: `research/DEVIN_ACP_PROTOCOL.md`.

### Permission-mode feature detection

**What we could not do**: Determine a robust runtime way to enumerate the exact
permission modes accepted by an arbitrary installed `devin` version.

**Why**: Only v3000.1.27 was tested.

**Impact**: Future versions may accept different aliases; Goal Devin should pass
user input through and let `devin` validate it.

**Location**: `research/DEVIN_VERSION_COMPATIBILITY.md`.

## Recommended next steps

1. Run the native-integration trial (`research/NATIVE_INTEGRATION_TRIAL.md`).
2. When a rate-limit occurs naturally, capture the error and update
   `DEVIN_RATE_LIMIT_BEHAVIOR.md`.
3. Extend the TUI probe to exercise the model picker, subagent panel, and
   permission prompt.
4. Perform a full `devin acp` `session/prompt` turn if ACP becomes the chosen
   integration seam.
