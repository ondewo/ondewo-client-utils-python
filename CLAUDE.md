# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Repository Overview

`ondewo-client-utils-python` (distribution name `ondewo-client-utils`, importable as `ondewo.utils`) is a small
library of shared base classes and utilities for ONDEWO gRPC Python clients. Other ONDEWO client packages (nlu, s2t,
t2s, vtsi, …) depend on it. It is deliberately minimal — keep it that way.

Public building blocks (all under `ondewo/utils/`):

- `base_client.py` — `BaseClient`, the abstract base for synchronous clients (`connect` / `disconnect`, holds a
  `services` container).
- `async_base_client.py` — `AsyncBaseClient`, the `async` counterpart.
- `base_services_interface.py` — `BaseServicesInterface` plus channel helpers (`get_secure_channel`,
  `_get_grpc_channel`, `MAX_MESSAGE_LENGTH`) and the constant gRPC channel options.
- `async_base_services_interface.py` — `AsyncBaseServicesInterface`, the `grpc.aio` counterpart.
- `base_client_config.py` — `BaseClientConfig`, a frozen dataclass config (`host`, `port`, `grpc_cert`) with
  hand-rolled `to_dict` / `from_dict` / `to_json` / `from_json` helpers. It deliberately does **not** use
  `dataclasses_json`: that decorator pulled `marshmallow` into every ONDEWO client package purely to provide a
  `schema()` method nobody called. Do not reintroduce it.
- `base_service_container.py` — `BaseServicesContainer`, the dataclass that concrete clients subclass to enumerate
  their services.
- `helpers.py` — `get_struct_from_dict`, `get_attr_recursive`, `set_attr_recursive`.
- `text.py` — `TextHelper.from_camel_to_snake_case`.

The default gRPC channel options (`_DEFAULT_GRPC_OPTIONS` / `_SERVICE_CONFIG_JSON`) are assembled once at import time.
Keep them module-level constants — do not move the `json.dumps` / options-dict construction back into `__init__`, since
a client with N services would otherwise rebuild them N times per connection.

## Development

Python `>=3.9`.

- **Install:** `pip install -r requirements.txt -r requirements-dev.txt && pip install .`
- **Run tests:** `python -m pytest` — configuration lives in `setup.cfg` (`asyncio_mode = auto`, branch coverage, and a
  `--cov-fail-under=100` gate). Any new runtime line needs a covering test or the suite fails.
- **Lint:** `make flake8` (or `flake8 .`); max line length is 120.
- **Types:** `make mypy` (or `pre-commit run mypy --all-files`); configuration in `mypy.ini`.
- **All hooks:** `pre-commit run --all-files`.
- **Docker parity:** `make run_tests` and `make run_code_checks` reproduce CI locally.

CI (`.github/workflows/tests.yml`) runs the test suite on every push and pull request across Python 3.9–3.12. Tests live
in `tests/`; name new files `test_*.py` (enforced by the `name-tests-test` hook).

## Working Principles

Behavioral guidelines to reduce common mistakes. They bias toward caution over speed; for trivial tasks, use judgment.

### Think before coding

Don't assume. Don't hide confusion. Surface tradeoffs.

Before implementing:

- State your assumptions explicitly. If uncertain, ask.
- If multiple interpretations exist, present them — don't pick silently.
- If a simpler approach exists, say so. Push back when warranted.
- If something is unclear, stop. Name what's confusing. Ask.

### Simplicity first

Minimum code that solves the problem. Nothing speculative.

- No features beyond what was asked.
- No abstractions for single-use code.
- No "flexibility" or "configurability" that wasn't requested.
- No error handling for impossible scenarios.
- If you write 200 lines and it could be 50, rewrite it.

Ask yourself: "Would a senior engineer say this is overcomplicated?" If yes, simplify.

### Surgical changes

Touch only what you must. Clean up only your own mess.

When editing existing code:

- Don't "improve" adjacent code, comments, or formatting.
- Don't refactor things that aren't broken.
- Match existing style, even if you'd do it differently.
- If you notice unrelated dead code, mention it — don't delete it.

When your changes create orphans:

- Remove imports/variables/functions that _your_ changes made unused.
- Don't remove pre-existing dead code unless asked.

The test: every changed line should trace directly to the user's request.

### Goal-driven execution

Define success criteria. Loop until verified.

Transform tasks into verifiable goals:

- "Add validation" → "Write tests for invalid inputs, then make them pass"
- "Fix the bug" → "Write a test that reproduces it, then make it pass"
- "Refactor X" → "Ensure tests pass before and after"

For multi-step tasks, state a brief plan:

```text
1. [Step] → verify: [check]
2. [Step] → verify: [check]
3. [Step] → verify: [check]
```

Strong success criteria let you loop independently. Weak criteria ("make it work") require constant clarification.

These guidelines are working if: fewer unnecessary changes in diffs, fewer rewrites due to overcomplication, and
clarifying questions come before implementation rather than after mistakes.

## Logging

This library uses the Python standard-library `logging` module (there is no `loguru` dependency):

```python
from logging import warning
```

- **Levels:** `debug()`, `info()`, `warning()`, `error()`, `exception()`. Choose by hotness/verbosity — `debug` for
  routine method entry/exit, `info` for notable lifecycle events, `warning` / `error` / `exception` for problems.
- **Interpolate with f-strings.** Use `f"…{value}"`; only add the `f` prefix when the string actually interpolates
  (`"START: …"` with no params stays a plain string).
- **`START:` / `DONE:` bracketing.** For a notable operation, wrap it with a `START:` line at entry and a `DONE:` line
  at exit, both naming `ClassName: method_name` (append `: param={value}` context where useful).
- **Timing uses `perf_counter()`, rendered `:.5f`.** Measure elapsed time with `time.perf_counter()` captured as a start
  value and subtracted at the `DONE:` line:

  ```python
  from time import perf_counter

  start_time: float = perf_counter()
  ...
  log.info(f"DONE: BaseClient: connect. Elapsed time: {perf_counter() - start_time:.5f}")
  ```

  Never measure a duration with `time.time()` — reserve `time.time()` for wall-clock timestamps. `perf_counter()` has an
  undefined epoch and must not be stored or compared across processes.

## Docstrings

Google-style, triple double-quotes:

```python
"""
Short imperative summary line.

Args:
    param_name (type):
        Description of the parameter.

Returns:
    type:
        Description of the return value.

Raises:
    ExceptionType:
        When this exception is raised.
"""
```

## Git Commits

- **Never include Claude as author or co-author** in commit messages, PR descriptions, or any other text. Do not add
  `Co-Authored-By: Claude…` trailers, "Generated with Claude Code" footers, or any similar attribution.
- The user's own git author identity (already configured in git) is the only identity that should appear on commits.
- This rule overrides the default Claude Code commit-template guidance.
- **Never prepend the JIRA ticket ID** (e.g. `[OND211-2418]`) to the commit subject yourself. The `giticket` pre-commit
  hook reads the ticket from the branch name and prepends `[<ticket>]` automatically. This repo's regex is
  `(?:(?:feature|bugfix|support|hotfix)/)?(OND[0-9]{3}-[0-9]{1,5})[_-][\w-]+`, so the `feature/` … prefix is optional —
  a branch such as `OND211-2418-add-keycloak-for-2-fa` is matched directly and yields `[OND211-2418] `. Writing the
  prefix manually produces a duplicate like `[OND211-2418] [OND211-2418] …`. Write the subject as a plain message and
  let the hook add the prefix on commit.

## General Principles

- Follow existing patterns before introducing new abstractions.
- Keep changes minimal and consistent with surrounding code.
- Validate inputs early with descriptive, context-rich error messages.
- Use context managers for files, sockets, and thread pools.
- Prefer region comments for grouping methods in files that already use them.
- End edited Markdown and YAML files with a trailing newline.
