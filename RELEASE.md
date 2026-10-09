# Release History

*****************

## Release ONDEWO CLIENT UTILS PYTHON 4.1.1

### Bug Fixes

* `BaseClient.disconnect()` / `AsyncBaseClient.disconnect()` closed no further channel once a services field had no channel (e.g. `None`): the lookup raised outside the per-channel error handling. Every remaining channel is now closed, and that error is still re-raised afterwards
* gRPC retry-policy discovery no longer raises `AttributeError` when a scanned module holds a type whose `__module__` is not a `str` (as Cython's shared `coroutine` / `generator` types have)

### Improvements

* The sdist no longer ships a partial test suite (test modules without `conftest.py` and fixtures); it now matches the one built in the release image
* The release guard (`make spc`) stops on an existing release branch or tag with `&& exit 1` (the echo was backgrounded with `&`) and also asks origin by exact ref name, since local refs can be stale

*****************

## Release ONDEWO CLIENT UTILS PYTHON 4.1.0

### New Features

* Mutual TLS: `BaseClientConfig` takes an optional client identity, `grpc_client_cert` (PEM client certificate chain) and `grpc_client_key` (its PEM private key). With both set, the sync and the async secure channel present the client leaf to a server that requires client certificates; with neither set the channel is plain TLS, exactly as before. `get_secure_channel` (sync and async) takes the same pair as `client_cert` / `client_key`
* Both fields are encoded and serialized like `grpc_cert` (`str` becomes `bytes`, `to_dict` / `to_json` carry PEM text, `from_dict` / `from_json` / `dataclasses.replace` round-trip), and a document written before 4.1.0 still loads

### Improvements

* Setting only one of `grpc_client_cert` / `grpc_client_key` raises `ValueError`, as does a plaintext channel (`use_secure_channel=False`) for a config that carries a client identity, which would otherwise silently send it nowhere. Neither message renders a PEM
* `grpc_client_key` is left out of the config's `repr`, so a logged or traceback-printed config never shows the private key
* Real handshake tests (sync and `grpc.aio`) pin both modes: mutual TLS serves a client leaf from the server's CA and refuses none or a foreign one, a TLS-only server serves clients with and without a leaf, and server verification is unchanged. They also cover `build_shared_channel` with a client identity and CRLF-terminated PEMs
* `get_secure_channel` (sync and async) refuses half a `client_cert` / `client_key` pair, or one empty PEM, with `ValueError`. grpc core would otherwise abort the whole Python process. An empty pair (`b""` / `""`) is plain TLS
* The wheel ships `py.typed`, so downstream mypy type-checks against `ondewo.utils` instead of treating it as untyped
* README: a new "TLS, mutual TLS and certificates" guide covers plaintext, TLS and mutual TLS; PEM content vs file paths; `grpc.ssl_target_name_override`; a test PKI with openssl; security notes (`to_json` carries the private key in clear text); and troubleshooting common handshake errors. CONTRIBUTING.md now describes the real development workflow
* The release guard (`make spc`) matches the release branch and tag exactly instead of by substring

### Bug Fixes

* `BaseClientConfig.to_json(**kwargs)` and `to_dict(encode_json=True)` rendered an `Enum` field with `TypeError`; they now write its value, like bare `to_json()` and dataclasses-json
* Bare `to_json()` raised on a mapping with non-`str` keys (e.g. `Dict[int, str]`); it now stringifies them like `to_json(**kwargs)` and dataclasses-json

*****************

## Release ONDEWO CLIENT UTILS PYTHON 4.0.1

### Bug Fixes

* `protobuf` 7.x is accepted again (`<8` instead of `<7`). 4.0.0 could not be installed next to protobuf 7, which ondewo-csi, ondewo-sip and ondewo-vtsi run (7.35.1). The floor and the excluded vulnerable 6.x releases are unchanged

### Improvements

* CI runs the whole test suite on protobuf 7 (with grpcio 1.83+) in addition to the locked 6.x

*****************

## Release ONDEWO CLIENT UTILS PYTHON 4.0.0

### New Features

* Public module `ondewo.utils.grpc_retry_policy` with `is_idempotent_method`, `build_service_config_json`, `service_config_json_for`, `service_config_json_for_classes`, `READ_ONLY_METHOD_NAME_PATTERN`, `NON_IDEMPOTENT_DESPITE_NAME` and `IDEMPOTENT_RETRY_POLICY`
* Opt-in shared channel: `build_shared_channel(config, use_secure_channel, service_classes, options=None)` in `base_services_interface` and `async_base_services_interface`, plus a keyword-only `grpc_channel=` parameter on `BaseServicesInterface` / `AsyncBaseServicesInterface`. One TCP/TLS connection and one name resolution for all of a client's services (16 services, construction + first call on each: 44.1 ms with a channel per service, 6.5 ms shared over TLS); every method keeps its per-class retry policy
* `make security_audit`: a blocking pip-audit of the locked dependency set, also run in CI

### Improvements

* `dataclasses-json` (and with it `marshmallow` and `typing-inspect`) is no longer a dependency: `BaseClientConfig` implements `to_dict` / `from_dict` / `to_json` / `from_json` itself on top of `orjson` (`>=3.11.1`, the first release with CPython 3.14 wheels). The outcomes are pinned against golden fixtures recorded under dataclasses-json 0.6.7: unknown keys are still ignored on read, absent fields take their defaults, `from_dict` / `from_json` still build the subclass they are called on, values are still converted as before (a port `50051` becomes `"50051"`), and `to_json(...)` with any `json.dumps` keyword argument is byte-identical to before. A subclass still decorated with `@dataclass_json` keeps working and keeps writing `grpc_cert` as text, as long as that package declares `dataclasses-json` itself (every ONDEWO SDK that imports it does)
* Error messages of `from_dict` / `from_json` name the class, field and value type, never the value (a mistyped secret is no longer echoed by `int()`'s `ValueError`)
* `build_service_config_json` names a service passed more than once (same `full_name`) only once. grpc-core rejects a service config that names a method path twice and then fails every RPC on that channel with `INVALID_ARGUMENT`
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
* Release tooling no longer echoes or puts the PyPI password / GitHub token on a command line (neither on twine's, docker's, `/bin/sh -c`'s nor `make release`'s argv), and pins the uv image
* Pre-commit: the conventional-commit check accepts a `[TICKET]` prefix, the giticket regex is anchored, the mypy hook runs from the uv environment, and the hook revisions are current

### Breaking Changes

* Python 3.12 or newer is required (`requires-python = ">=3.12"`); 3.9, 3.10 and 3.11 are no longer supported. The release tooling image builds on `python:3.12-slim`
* The gRPC retry policy now retries idempotent methods only. Methods declared `NO_SIDE_EFFECTS` / `IDEMPOTENT` in their proto, or whose name starts with `Get`, `List`, `BatchGet`, `Check`, `Validate` or `Ping`, are retried up to 5 attempts on transient status codes (no longer on `NOT_FOUND` / `DATA_LOSS`). Every other method is no longer retried on any status code, `UNAVAILABLE` included, because a failed attempt may already have acted on the server; gRPC's transparent retries stay on. Pass `wait_for_ready=True` to wait for a server that is not reachable yet, or your own `grpc.service_config` option to restore a different policy
* `ondewo.nlu.Sessions/GetSessionReview` and `GetLatestSessionReview` are no longer retried: they compute and store a review when none exists
* `_DEFAULT_GRPC_OPTIONS["grpc.service_config"]` and `_SERVICE_CONFIG_JSON` now retry no method at all (they are the fallback for a class whose services cannot be found). Code that builds its own channel from them should use `service_config_json_for(<service class>)` instead
* `BaseClientConfig.schema()` is removed. It returned a `marshmallow.Schema` and cannot exist without marshmallow; no ONDEWO package calls it. `isinstance(config, dataclasses_json.DataClassJsonMixin)` is no longer true for a config that is not itself decorated with `@dataclass_json`
* `BaseClientConfig.to_json()` called without arguments returns the same JSON document in orjson's compact UTF-8 form (`{"host":"h","port":"1","grpc_cert":null}`, non-ASCII characters unescaped) instead of `json.dumps`'s `{"host": "h", ...}` with `\u` escapes. Pass any `json.dumps` keyword argument (e.g. `ensure_ascii=True`) to get the previous bytes
* `from_dict` / `from_json`: a missing field without a default raises `TypeError` (was `KeyError`); a document that is not a JSON object (`null`, a list, a string) raises `TypeError` (was `AttributeError`); a value that cannot be converted to its field type raises `ValueError` without the value in the message; `bytes` given for `grpc_cert` (or any `str` field) are kept instead of becoming the text `"b'...'"`; the non-standard `NaN` / `Infinity` literals are rejected as invalid JSON. Collection-typed subclass fields are passed through as decoded (no element conversion)
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
