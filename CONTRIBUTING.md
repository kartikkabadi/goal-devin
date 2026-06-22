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

- **Zero dependencies.** Stdlib only. If you need a dep, it doesn't belong here.
- **One file does the work.** `src/goal_devin/cli.py` is the whole tool. Don't split it into modules unless there's a real reason.
- **Ponytail.** Shortest working diff wins. No speculative abstractions, no boilerplate "for later", no config for values that never change.
- **Surgical edits.** Touch only what you must. Match existing style. Don't refactor things that aren't broken.

## Workflow

1. Open an issue describing the bug or feature.
2. Branch from `main`.
3. Make your change. Keep the diff short.
4. Add or update tests in `tests/test_cli.py`.
5. Run `uv run pytest` — must pass.
6. Open a PR. Reference the issue.

## Testing

```bash
uv run pytest              # all tests
uv run pytest -v           # verbose
uv run python -m unittest tests/test_cli.py  # without pytest
```

Tests use stdlib `unittest` so they run without pytest installed, but pytest is the dev convenience runner.

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

1. Update `__version__` in `src/goal_devin/__init__.py` and `cli.py`.
2. Update `CHANGELOG.md`.
3. Tag: `git tag v0.X.Y && git push --tags`.
4. The CI publishes to PyPI on tag push (if configured).

## License

By contributing, you agree your contributions are licensed under the MIT License.
