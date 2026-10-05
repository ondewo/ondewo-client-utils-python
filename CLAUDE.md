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
  `_get_grpc_channel`, `build_shared_channel`, `MAX_MESSAGE_LENGTH`) and the constant gRPC channel options.
- `async_base_services_interface.py` — `AsyncBaseServicesInterface`, the `grpc.aio` counterpart.
- `base_client_config.py` — `BaseClientConfig`, a frozen `dataclass_json` config (`host`, `port`, `grpc_cert`). A `str`
  cert is encoded to `bytes` in `__post_init__`; a field encoder writes it back as text so `to_json`/`from_json`,
  `to_dict`/`from_dict` and `dataclasses.replace` round-trip. dataclasses-json stays (decided; do not replace it).
- `base_service_container.py` — `BaseServicesContainer`, the dataclass that concrete clients subclass to enumerate
  their services.
- `helpers.py` — `get_struct_from_dict`, `get_attr_recursive`, `set_attr_recursive`.
- `text.py` — `TextHelper.from_camel_to_snake_case`.

- `grpc_retry_policy.py` — the per-method gRPC retry policy shared by both service interfaces.

The default gRPC channel options (`_DEFAULT_GRPC_OPTIONS` / `_SERVICE_CONFIG_JSON`) are assembled once at import time,
and the per-class options (`_grpc_options_items_for`, `service_config_json_for`) once per service class (`lru_cache`).
Keep it that way — do not move the `json.dumps` / options-dict construction back into `__init__`, since a client with N
services would otherwise rebuild them N times per connection. `ondewo-vtsi`'s tests import `_DEFAULT_GRPC_OPTIONS`, so
keep that name. The sync and async modules hold two hand-maintained copies of `_DEFAULT_GRPC_OPTIONS`;
`test_sync_and_async_default_options_are_identical` and `tests/test_channel_option_contract.py` (every `__init__`
option assertion runs against both) keep them from drifting.

`disconnect()` iterates `dataclasses.fields(self.services)`, never `__annotations__`: a Python 3.14 instance has no
`__annotations__` (PEP 649), and on every version `__annotations__` omits fields a parent container declares. It
closes a channel shared by several services once, attempts every channel, always clears `services`, and re-raises
the first close error.

### Channel defaults and latency

- **One shared channel is the latency lever, and it is opt-in.** By default each service interface opens its own
  channel: N services = N TCP connections, N resolutions, N TLS handshakes. `build_shared_channel(config,
  use_secure_channel, service_classes)` builds one, with `service_config_json_for_classes(tuple)` (the union of the
  per-class configs; `methodConfig` names fully qualified service/method, so no method's policy changes), and each
  service takes it via the keyword-only `grpc_channel=`. Measured: 16 services, construction + first call each, 44.1
  ms per-service vs 6.5 ms shared (TLS, loopback). Defaults stay per-service so existing SDKs are unchanged.
- **No `grpc.dns_enable_srv_queries`.** It only finds deprecated grpclb balancers and cost ~14 ms per channel (15.9 vs
  1.4 ms to 127.0.0.1). A grpclb user passes it in `options`.
- **Keepalive** (`keepalive_time_ms=30000`, `keepalive_permit_without_calls=False`,
  `http2.max_pings_without_data=2`, gRPC's default): pings only during active calls and stop after 2 without data.
  Never set `max_pings_without_data=0`: a default grpc-core server GOAWAYs a client that keeps pinging a silent stream
  (`too_many_pings`; measured UNAVAILABLE after 50 s at a 10 s keepalive, OK with 2), which tears down the shared
  connection and every non-retried RPC on it. Do not "re-disable" keepalive back to `2**31-1` either.
- **Logging:** the insecure-channel warning goes to a module logger and names `host:port`. Never call the module-level
  `logging.warning()` / `logging.info()`: they run `basicConfig()` on the HOST application's root logger. Error
  messages never interpolate a config object (downstream subclasses carry passwords); name the class and
  `host_and_port`.

## gRPC retry policy — only idempotent methods are retried

The policy used to be ONE `retryPolicy` for every method (`"name": [{}]`, maxAttempts 10 — silently clamped to 5 by
gRPC's `grpc.max_retry_attempts` — on nine codes incl. `DEADLINE_EXCEEDED`, `INTERNAL`, `UNKNOWN`, `UNAVAILABLE`). In
ondewo-vtsi-release #115 that re-sent a `StartCallers` the server was already executing (a GOAWAY mid-deploy surfaced as
`UNAVAILABLE`) and one batch was deployed twice. Now:

- **Idempotent** = proto `idempotency_level` `NO_SIDE_EFFECTS`/`IDEMPOTENT`, or the name starts with a read verb
  (`READ_ONLY_METHOD_NAME_PATTERN`: `BatchGet|Get|List|Check|Validate|Ping`, whole word). No ONDEWO proto sets
  `idempotency_level` (469 methods across nlu/qa/vtsi/sip/csi/s2t/t2s checked), so the verb list carries everything; it
  was chosen from those protos. Namespaced names (`SipGetSipStatus`, `RagList*`, `LlmEvaluationGet*`) deliberately do
  NOT match — the wrong direction for a heuristic to fail is "one retry too few", never "one duplicate side effect".
  Idempotent methods retry on everything transient but `NOT_FOUND` / `DATA_LOSS` (definitive answers).
- **Everything else has NO configured retry, not even on `UNAVAILABLE`.** Measured with two in-process servers on one
  port: with `UNAVAILABLE` in a non-idempotent policy, a request whose server died mid-handler was executed again by the
  replacement server (the #115 shape); without it, once. gRPC transparent retries (request never reached the server
  application) stay on. The cost is that a call made while the server is not yet reachable fails at once instead of
  being retried; `wait_for_ready=True` covers that without re-sending.
- **Discovery:** the channel is built in `__init__`, before the subclass's `stub` exists, so the services are found by
  scanning the module globals of the class's MRO for `*_pb2` modules and `*_pb2_grpc` classes (every ONDEWO client
  service module imports its `XStub`), then reading `DESCRIPTOR.services_by_name`. Nothing found → the safe default.
- **Denylist:** `NON_IDEMPOTENT_DESPITE_NAME` removes get-or-create reads from the verb rule
  (`ondewo.nlu.Sessions.GetSessionReview` / `GetLatestSessionReview` compute and store a review if none exists). It is
  checked AFTER `idempotency_level` (an explicit proto declaration wins) and before the regex. Add to it, never remove
  a retry by widening it to non-read verbs.
- **Streaming:** the same name rule applies to streaming methods (`GetControlStream` is retried); gRPC never retries a
  stream after its first response reached the client.
- **ondewo-vtsi still carries its own copy** (`ondewo_vtsi/utils/grpc_retry_policy.py`), which treats `SipGet*` as
  reads, i.e. wider than this library. Reconcile that before vtsi drops its copy for this one.
- Pinned by `tests/test_retry_only_idempotent_methods.py` (written against the public surface; 45 of its cases fail on
  the old policy, incl. a real server executing a failing `StartCallers` 5 times) and `tests/test_grpc_retry_policy.py`.

## Development

Everything runs through uv and the Makefile; the config lives in `pyproject.toml`, `pytest.ini` and `.coveragerc`.

- **Set up:** `make setup_developer_environment_locally` (installs uv if missing, `uv sync --extra dev` into `.venv`,
  installs the pre-commit and commit-msg hooks).
- **Tests:** `make test` (`uv run pytest`). `pytest.ini` sets `asyncio_mode = auto` and `--cov-fail-under=100`, and
  `.coveragerc` (branch coverage) repeats `fail_under = 100`, so `pytest -o addopts=` cannot bypass the gate. Any new
  runtime line needs a covering test.
- **Lint / format / types:** `make ruff`, `make ruff_format` (`ruff format --check .` is what CI checks), `make mypy`
  (`mypy ondewo tests`, config in `[tool.mypy]`, `python_version = "3.10"`).
- **Security:** `make security_audit` (pip-audit over `uv export --frozen --all-extras`, blocking; fix a finding by
  raising the floor or upgrading the locked package, never with `--ignore-vuln`).
- **All hooks:** `make precommit_hooks_run_all_files`. The mypy hook is a local `uv run --no-sync mypy ondewo tests`,
  so it works without an activated venv.
- **Python 3.14:** downstream (ondewo-vtsi) runs 3.14. Run the suite there with
  `UV_PROJECT_ENVIRONMENT=/tmp/venv314 UV_PYTHON=3.14 uv sync --extra dev --frozen && UV_PROJECT_ENVIRONMENT=/tmp/venv314 uv run --frozen pytest`.

CI (`.github/workflows/tests.yml`) runs on every push and pull request on Python 3.12 and 3.14: ruff check, ruff format
check, mypy over `ondewo` and `tests`, the test suite with the coverage gate, and `make security_audit`. Tests live in
`tests/`; name new files `test_*.py` (enforced by the `name-tests-test` hook).

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
import logging

_LOGGER: logging.Logger = logging.getLogger(__name__)
```

- **Always a module logger** (`_LOGGER.warning(...)`), never the module-level `logging.warning()` & co: those run
  `basicConfig()` and add a stderr handler to the host application's root logger.
- **Levels:** `_LOGGER.debug()`, `info()`, `warning()`, `error()`, `exception()`. Choose by hotness/verbosity — `debug` for
  routine method entry/exit, `info` for notable lifecycle events, `warning` / `error` / `exception` for problems.
- **Interpolate with f-strings** (`f"…{value}"`), or lazy `%s` arguments as the insecure-channel warning does; only add
  the `f` prefix when the string actually interpolates (`"START: …"` with no params stays a plain string).
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
- **Never prepend the JIRA ticket ID** (e.g. `[OND211-2418]`) to the commit subject yourself. The `giticket` commit-msg
  hook reads the ticket from the branch name and prepends `[<ticket>]` automatically. Its regex (pinned by
  `tests/test_giticket_regex.py`, same value as ondewo-sip and ondewo-vtsi) is anchored:
  `^(?:Merge (?:branch|…|pull request) |(?:(?:feature|bugfix|support|hotfix)/)?\[?([A-Z]{3}[0-9]{3}-[0-9]{1,5})(?:[_-][\w-]+$|\] ))`.
  It matches a whole ticket branch name (`feature/OND233-367-…` or bare `OND211-2418-…`) and a message line that
  already STARTS with `[<TICKET>]` (so an amend is not prefixed twice), and nothing else: a body line merely
  mentioning a ticket branch no longer drops the prefix. Writing the prefix manually is tolerated, not needed.
- **Commit-msg hook order:** the conventional check runs first, through `scripts/hooks/conventional_commit_msg.py`
  (copied from ondewo-vtsi), which strips one leading `[<TICKET>]` before delegating to upstream
  `conventional-pre-commit` 4.4.0; giticket runs second. Upstream alone rejects every prefixed message.

## General Principles

- Follow existing patterns before introducing new abstractions.
- Keep changes minimal and consistent with surrounding code.
- Validate inputs early with descriptive, context-rich error messages.
- Use context managers for files, sockets, and thread pools.
- Prefer region comments for grouping methods in files that already use them.
- End edited Markdown and YAML files with a trailing newline.

## Release / build gotchas (hard-won this session)

- Downstream release images build on `python:3.12-slim`, which has **no `setuptools`** — anything running `python setup.py …` must `pip install setuptools wheel` first.
- gRPC keepalive: see "Channel defaults and latency" above (`max_pings_without_data=2`, never 0).

## Python tooling — uv + ruff + mypy + pyproject.toml (this session's refactor)

This repo was migrated off `setup.py` / `.flake8` / `mypy.ini` to a single **pyproject.toml** with **uv**, **ruff**, and **mypy**. Going forward:

- **Build backend stays setuptools** (for PyPI compatibility). Build with `python -m build --no-isolation` or `uv build` — NOT `python setup.py sdist bdist_wheel` (setup.py is deleted). `Dockerfile.utils` installs `twine setuptools wheel build`.
- **Dependencies via uv + a committed `uv.lock`.** CI runs `uv sync --extra dev --frozen`. To add/change a dep: edit `[project.dependencies]`/`[project.optional-dependencies].dev` in pyproject.toml then `uv lock`.
- **Lint is ruff** (`[tool.ruff]`, line-length 120, generated `*_pb2*` excluded) — `uv run ruff check .`. flake8 is gone.
- **mypy config lives in `[tool.mypy]`.** Do **NOT** re-create `mypy.ini` — it silently _shadows_ the pyproject config. Generated `*_pb2*` modules get `ignore_errors` overrides.
- **Do NOT re-add `setup.py`** — with setuptools>=61 it conflicts with `[project]` on duplicated metadata.
- **PEP 625**: the sdist is now underscore-normalised (`ondewo_<name>-<v>.tar.gz`); anything that greps the tarball name by hand must use underscores.
- The version lives in `ondewo/version.py` (pyproject reads it dynamically); there is no version-bump target. Bump it by hand in a release PR.

## uv migration — completed conversion (this session)

The repo is now fully on **uv** (not just pyproject.toml):

- `make setup_developer_environment_locally` bootstraps uv (installs it if missing), runs `uv sync --extra dev` (creates `.venv` + installs all runtime+dev deps + pre-commit), then `uv run pre-commit install`. **No conda** — the old `create_conda_env`/`setup_conda_env` scaffolding was removed.
- Every Makefile target uses uv: `uv sync --extra dev` (deps), `uv run pytest`/`ruff`/`mypy` (tools), `uv build` (wheel). No `pip install`, no `python -m build`, no `python setup.py`.
- New targets: `make ruff` / `make ruff_fix` / `make ruff_format` / `make mypy`. The `flake8` target is **removed**.
- Removed for good: `requirements.txt`, `requirements-dev.txt`, `setup.cfg` — deps + tool config live in `pyproject.toml`. Do **not** re-add them.
- `Dockerfile.utils` installs uv (`COPY --from=ghcr.io/astral-sh/uv`) and builds with uv; it no longer `COPY`s `requirements.txt`.
- `[tool.mypy] python_version` is `3.10` here (mypy no longer accepts 3.9); numpy is not on this repo's mypy path. Downstream repos that type-check numpy 2.x need `3.12`.
- The release targets create a branch and a tag; they make no commit. Credentials reach twine and docker through the environment (the Makefile's global `export`), never as argv values (`/proc/<pid>/cmdline` is world-readable); `tests/test_release_makefile_hygiene.py` pins it. `Dockerfile.utils` pins `ghcr.io/astral-sh/uv:0.12.23`.
- Pre-commit hook revisions are bumped with `uv run pre-commit autoupdate`; keep `ruff==<rev>` in the dev extra equal to the ruff-pre-commit rev. autoupdate flips giticket between the `v1.92` and `1.92` tags (same commit); keep `v1.92`.
- **Validated by a real PyPI publish** — `ondewo-t2s-client 6.5.0` was built with `uv build` and uploaded via twine end-to-end; the uv release pipeline works.
