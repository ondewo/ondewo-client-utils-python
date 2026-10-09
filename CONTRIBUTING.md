# Contributing

## Setup

Python 3.12 or newer. The Makefile installs [uv](https://docs.astral.sh/uv/), syncs the locked runtime + dev
dependencies into `.venv` and installs the pre-commit hooks:

```bash
make setup_developer_environment_locally
```

Without make: `uv sync --extra dev`, then `uv run pre-commit install` and
`uv run pre-commit install --hook-type commit-msg` (the commit-message hooks below need the second one).

## Checks

```bash
make test                 # uv run pytest: unit tests + the 100% branch-coverage gate
make ruff                 # lint (ruff check); `make ruff_format` formats
make mypy                 # static type checks
uv run pre-commit run --all-files
```

The coverage gate is enforced: every new runtime line or branch needs a covering test. Name test files `test_*.py`.

## Branches and commits

- Branch from `master` with the JIRA ticket in the name, e.g. `feature/OND211-2443-short-description`
  (`bugfix/`, `support/` and `hotfix/` work too).
- Write [Conventional Commits](https://www.conventionalcommits.org/) subjects (`feat(tls): ...`, `fix: ...`,
  `docs: ...`); the `commit-msg` hook checks them.
- Do **not** type the ticket into the subject: the `giticket` hook prepends `[OND211-2443]` from the branch name.
- Commits straight onto `master` are refused by a hook; open a pull request.

## Release notes

Add a bullet for every user-visible change to the topmost (unreleased) section of `RELEASE.md`, under
`New Features`, `Improvements`, `Bug Fixes` or `Breaking Changes`.
