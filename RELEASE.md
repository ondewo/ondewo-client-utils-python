# Release History

*****************

## Release ONDEWO CLIENT UTILS PYTHON 3.3.0

### Improvements

* Removed the `dataclasses-json` dependency, and with it the transitive `marshmallow` dependency, from every
  ONDEWO client package. `BaseClientConfig` now implements `to_dict` / `from_dict` / `to_json` / `from_json`
  directly.
* Fixed `from_json(to_json(config))` silently corrupting `grpc_cert`: the certificate is stored as `bytes`, and
  `dataclasses-json` serialized it as a list of integers, so the round trip yielded `b"[109, 121, ...]"`.

### Breaking changes

* `BaseClientConfig.schema()` was removed. It returned a `marshmallow.Schema` and cannot exist without
  `marshmallow`. No ONDEWO client used it.
* `from_dict` / `from_json` now raise `TypeError` rather than `KeyError` when a mandatory field is missing.

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
