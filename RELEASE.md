# Release History

*****************

## Unreleased

### New Features

* Public module `ondewo.utils.grpc_retry_policy` with `is_idempotent_method`, `build_service_config_json`, `service_config_json_for`, `service_config_json_for_classes`, `READ_ONLY_METHOD_NAME_PATTERN`, `NON_IDEMPOTENT_DESPITE_NAME` and `IDEMPOTENT_RETRY_POLICY`
* Opt-in shared channel: `build_shared_channel(config, use_secure_channel, service_classes, options=None)` in `base_services_interface` and `async_base_services_interface`, plus a keyword-only `grpc_channel=` parameter on `BaseServicesInterface` / `AsyncBaseServicesInterface`. One TCP/TLS connection and one name resolution for all of a client's services (16 services, construction + first call on each: 44.1 ms with a channel per service, 6.5 ms shared over TLS); every method keeps its per-class retry policy
* `make security_audit`: a blocking pip-audit of the locked dependency set, also run in CI

### Improvements

* The retry policy is built once per service class (cached) instead of on every service construction
* `maxAttempts` for idempotent methods lowered from 10 to 5, which gRPC clamped it to anyway
* `grpc.dns_enable_srv_queries` is no longer set: it only discovers deprecated grpclb balancers and cost ~14 ms per channel (median channel creation + first call to 127.0.0.1: 15.9 ms before, 1.4 ms after)
* Keepalive no longer triggers a server `too_many_pings` GOAWAY on silent streams: `grpc.http2.max_pings_without_data` is gRPC's default 2 instead of unlimited (a silent stream at a 10 s keepalive failed `UNAVAILABLE` after 50 s with unlimited pings and completed with 2)
* `disconnect()` works on Python 3.14, closes channels of services declared on a parent container, closes a channel shared by several services once, and still closes every channel and clears `services` when one `close()` raises (the first error is re-raised)
* `BaseClientConfig.grpc_cert` accepts `bytes`, survives `dataclasses.replace`, and round-trips through `to_dict` / `from_dict` and `to_json` / `from_json` (the JSON carries the PEM as text)
* The insecure-channel warning is logged on a module logger and names the target; it no longer configures the host application's root logger
* The missing-certificate `ValueError` names the config class and `host:port` only, never the config's fields (which may include a password)
* `protobuf` is a declared dependency, `>=5.29.6` excluding the releases affected by PYSEC-2026-1805 / PYSEC-2026-1806, `<7`
* CI runs on Python 3.12 and 3.14 and also checks formatting, type-checks the tests and audits dependencies
* Release tooling no longer echoes or puts the PyPI password / GitHub token on a command line, and pins the uv image
* Pre-commit: the conventional-commit check accepts a `[TICKET]` prefix, the giticket regex is anchored, the mypy hook runs from the uv environment, and the hook revisions are current

### Breaking Changes

* Python 3.12 or newer is required (`requires-python = ">=3.12"`); 3.9, 3.10 and 3.11 are no longer supported. The release tooling image builds on `python:3.12-slim`
* The gRPC retry policy now retries idempotent methods only. Methods declared `NO_SIDE_EFFECTS` / `IDEMPOTENT` in their proto, or whose name starts with `Get`, `List`, `BatchGet`, `Check`, `Validate` or `Ping`, are retried up to 5 attempts on transient status codes (no longer on `NOT_FOUND` / `DATA_LOSS`). Every other method is no longer retried on any status code, `UNAVAILABLE` included, because a failed attempt may already have acted on the server; gRPC's transparent retries stay on. Pass `wait_for_ready=True` to wait for a server that is not reachable yet, or your own `grpc.service_config` option to restore a different policy
* `ondewo.nlu.Sessions/GetSessionReview` and `GetLatestSessionReview` are no longer retried: they compute and store a review when none exists
* `_DEFAULT_GRPC_OPTIONS["grpc.service_config"]` and `_SERVICE_CONFIG_JSON` now retry no method at all (they are the fallback for a class whose services cannot be found). Code that builds its own channel from them should use `service_config_json_for(<service class>)` instead
* `get_struct_from_dict` raises `TypeError` instead of `AssertionError` for an argument that is neither a `dict` nor `None`

*****************

## Release ONDEWO CLIENT UTILS PYTHON 3.2.0

### New Features

* Added a test suite with 100% code coverage
* Added a GitHub Actions workflow that runs the tests on every push and pull request

### Improvements

* Serialize the gRPC service config and default channel options once at import instead of on every service construction to reduce client construction latency
* Enabled gRPC keepalive to keep long-lived streaming RPCs warm and detect half-open connections
* Updated GitHub Actions to their Node 24 releases to remove the Node 20 deprecation warnings
* Documented all Makefile targets and added a CLAUDE.md with repository and development guidance

*****************

## Release ONDEWO CLIENT UTILS PYTHON 3.1.0

### Improvements

* Added async client functionality

*****************

## Release ONDEWO CLIENT UTILS PYTHON 3.0.0

### Improvements

* Automated versioning of the package

*****************

## Release ONDEWO CLIENT UTILS PYTHON 2.0.0

### Improvements

* Added functionality to pass grpc options to grpc clients

*****************

## Release ONDEWO CLIENT UTILS PYTHON 1.0.1

### Improvements

* Relaxed requirements of grpc libraries

*****************

## Release ONDEWO CLIENT UTILS PYTHON 1.0.0

### Improvements

* Upgraded pre-commit hook configurations

*****************

## Release ONDEWO CLIENT UTILS PYTHON 0.1.1

### New Features

* Use latest version of dataclasses-json and regex

## Release ONDEWO CLIENT UTILS PYTHON 0.1.0

### New Features

* First release with common interfaces on Python Clients
