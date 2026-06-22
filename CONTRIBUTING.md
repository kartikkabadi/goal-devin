# Contributing

Bug reports, fixes, and improvements welcome.

## Setup

```bash
git clone https://github.com/kartikkabadi/goal-devin
cd goal-devin
uv sync
uv run pytest
```

## Rules

- **Minimal dependencies.** `textual` is the only dep (for the TUI). Stdlib for everything else. If you need another dep, it doesn't belong here.
- **Module structure.** `core.py` (state + GoalLoop), `tui.py` (Textual TUI), `cli.py` (hidden CLI), `worktree.py` (git worktrees). Don't add modules unless there's a real reason.
- **Ponytail.** Shortest working diff wins. No speculative abstractions, no boilerplate "for later", no config for values that never change.
- **Surgical edits.** Touch only what you must. Match existing style. Don't refactor things that aren't broken.

## Workflow

1. Open an issue describing the bug or feature.
2. Branch from `main`.
3. Make your change. Keep the diff short.
4. Add or update tests in the appropriate `tests/test_*.py` file.
5. Run `uv run pytest` — must pass.
6. Open a PR. Reference the issue.

## Testing

```bash
uv run pytest              # all tests
uv run pytest -v           # verbose
uv run pytest tests/test_core.py   # just core tests
```

TUI tests use `pytest-asyncio` + Textual's `run_test()` pilot. Core and CLI tests use stdlib `unittest`.

## Style

- Python 3.11+ (use modern syntax where it's clearer).
- 4-space indent.
- Functions and classes with docstrings only when non-obvious.
- Comments only for `ponytail:` shortcuts or non-obvious "why".
- No emojis in code or commit messages. Plain text.

## Commit messages

```
short imperative summary

optional body explaining why, not what.
```

No `feat:` / `fix:` prefixes. Plain English.

## Releasing

Maintainers only:

1. Update `__version__` in `src/goal_devin/__init__.py` and `pyproject.toml`.
2. Update `CHANGELOG.md`.
3. Tag: `git tag v0.X.Y && git push --tags`.
4. The CI publishes to PyPI on tag push (if configured).

## License

By contributing, you agree your contributions are licensed under the MIT License.
