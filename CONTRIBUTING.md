# Contributing

Small bug reports, reproductions, documentation improvements, and focused pull
requests are welcome. For API changes, describe the use case and discuss scope
in an issue before implementing a large change.

Use Python 3.11 or newer and [uv](https://docs.astral.sh/uv/):

```sh
uv sync --locked
uv run pytest -q
uv run ruff check .
uv run ruff format --check .
uv run python scripts/check_governance.py
uv build
```

Tests use synthetic data and do not require API keys or external model calls.
Never attach real prompts, tool credentials, private traces, or machine paths to
an issue. Update tests and relevant docs when changing behavior. Before closeout,
run the governance check with today's date and `--strict`, as described in the
[maintenance workflow](docs/maintenance.md).

Use branches such as `fix/replay-order` and concise conventional commit messages.
Explain what changes, how it was tested, and any compatibility effects in the PR.
Contributions are provided under the repository's MIT license.
